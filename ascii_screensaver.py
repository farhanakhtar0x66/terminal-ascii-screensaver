#!/usr/bin/env python3
"""Loop TerminalTextEffects' random effects over editable local ASCII art."""

import argparse
import importlib.util
import os
import select
import shutil
import signal
import subprocess
import sys
import termios
import tty
from pathlib import Path
from contextlib import ExitStack, contextmanager


@contextmanager
def hidden_tmux_status(enabled=True):
    """Temporarily override status only in this pane's tmux session."""
    session = None
    previous = None

    def tmux(*args):
        return subprocess.run(
            ["tmux", *args], capture_output=True, text=True, timeout=3, check=True,
        ).stdout.strip()

    try:
        if enabled and os.environ.get("TMUX") and shutil.which("tmux"):
            try:
                session = tmux("display-message", "-p", "-t", os.environ.get("TMUX_PANE", ""), "#{session_id}")
                previous = tmux("show-options", "-qv", "-t", session, "status")
                tmux("set-option", "-t", session, "status", "off")
            except (OSError, subprocess.SubprocessError):
                session = None
        yield
    finally:
        if session is not None:
            try:
                if previous:
                    tmux("set-option", "-t", session, "status", previous)
                else:
                    # Restore inheritance, rather than pinning the global value.
                    tmux("set-option", "-u", "-t", session, "status")
            except (OSError, subprocess.SubprocessError):
                pass


def get_tty_size(fd):
    """Read dimensions from the controlling terminal (works with redirected stdin)."""
    try:
        import fcntl
        import struct
        import termios as tty_termios

        rows, columns, _, _ = struct.unpack("HHHH", fcntl.ioctl(fd, tty_termios.TIOCGWINSZ, b"\0" * 8))
        if columns and rows:
            return columns, rows
    except (ImportError, OSError, AttributeError):
        pass
    return shutil.get_terminal_size((80, 24))


def fit_art(text, width, height):
    """Scale the artwork in terminal cells to fit, preserving its aspect ratio."""
    lines = text.expandtabs(4).splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    art_width = max(map(len, lines))
    art_height = len(lines)
    if not art_width:
        return text
    # Keep margin for animation particles and avoid the terminal's wrap/scroll edge.
    max_width, max_height = max(1, width - 4), max(1, height - 4)
    ratio = min(1.0, max_width / art_width, max_height / art_height)
    if ratio >= 1:
        return "\n".join(line.rstrip() for line in lines)
    out_width = max(1, int(art_width * ratio))
    out_height = max(1, int(art_height * ratio))
    scaled = []
    for y in range(out_height):
        source_y = min(art_height - 1, int(y / ratio))
        source = lines[source_y].ljust(art_width)
        scaled.append("".join(source[min(art_width - 1, int(x / ratio))] for x in range(out_width)).rstrip())
    return "\n".join(scaled)

SAMPLE_ART = r"""  ███████╗ ██████╗██████╗ ███████╗███████╗███╗   ██╗
  ██╔════╝██╔════╝██╔══██╗██╔════╝██╔════╝████╗  ██║
  ███████╗██║     ██████╔╝█████╗  █████╗  ██╔██╗ ██║
  ╚════██║██║     ██╔══██╗██╔══╝  ██╔══╝  ██║╚██╗██║
  ███████║╚██████╗██║  ██║███████╗███████╗██║ ╚████║
  ╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═══╝

        T E R M I N A L   S C R E E N S A V E R"""


def main(default_art=None):
    parser = argparse.ArgumentParser(description="Animated ASCII terminal screensaver")
    parser.add_argument("--new-art", action="store_true", help="replace ascii.txt with newly generated text art")
    parser.add_argument("--effect", help="loop a specific ttfx effect instead of choosing randomly (e.g. beams)")
    parser.add_argument("--theme", "--no-color", action="store_true", help="use your terminal's foreground color instead of effect palettes")
    parser.add_argument("--engine", choices=("auto", "ttfx", "tte"), default="auto", help="animation engine (auto prefers installed ttfx)")
    parser.add_argument("--art-path", action="store_true", help="print the artwork file location and exit")
    parser.add_argument("--keep-tmux-status", action="store_true", help="leave the tmux status bar visible")
    parser.add_argument("art_file", nargs="?", help="optional ASCII art text file")
    args = parser.parse_args()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    art_path = Path(args.art_file).expanduser() if args.art_file else default_art or config / "terminal-ascii-screensaver" / "ascii.txt"
    if args.art_path:
        print(art_path)
        return 0
    art_path.parent.mkdir(parents=True, exist_ok=True)
    if args.new_art:
        try:
            phrase = input("What should the screensaver say? ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.", file=sys.stderr)
            return 1
        if not phrase:
            print("Please enter some text; ascii.txt was not changed.", file=sys.stderr)
            return 1
        try:
            import pyfiglet
        except ImportError:
            print("Missing dependency for --new-art: install with `python3 -m pip install --user pyfiglet`", file=sys.stderr)
            return 127
        art_path.write_text(pyfiglet.figlet_format(phrase, font="slant"), encoding="utf-8")
        print(f"Saved new artwork to {art_path}")
        return 0
    if not art_path.exists():
        art_path.write_text(SAMPLE_ART + "\n", encoding="utf-8")
        print(f"Created {art_path}; edit this file to customize the screensaver.", file=sys.stderr)
    if not art_path.read_text(encoding="utf-8").strip():
        print(f"{art_path} is empty; add ASCII art and run again.", file=sys.stderr)
        return 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Run this program in an interactive terminal.", file=sys.stderr)
        return 2
    if args.engine != "tte" and shutil.which("ttfx"):
        engine = ["ttfx"]
    elif args.engine != "ttfx" and importlib.util.find_spec("terminaltexteffects"):
        engine = [sys.executable, "-m", "terminaltexteffects"]
    else:
        print("Animation engine unavailable. Install this project with pipx, or install ttfx from https://github.com/omacom/ttfx", file=sys.stderr)
        return 127

    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        try:
            fd = os.open("/dev/tty", os.O_RDWR)
        except OSError:
            print("Could not open the controlling terminal for keyboard input.", file=sys.stderr)
            return 2
    saved = termios.tcgetattr(fd)
    active = True
    process = None
    resized = False

    def stop(_signum, _frame):
        nonlocal active
        active = False
        if process and process.poll() is None:
            process.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    def resize(_signum, _frame):
        nonlocal resized
        resized = True
        if process and process.poll() is None:
            process.terminate()

    if hasattr(signal, "SIGWINCH"):
        signal.signal(signal.SIGWINCH, resize)
    # Leave the terminal's configured background and palette untouched.
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[0m\x1b[2J\x1b[H")
    sys.stdout.flush()
    cleanup = ExitStack()
    try:
        cleanup.enter_context(hidden_tmux_status(not args.keep_tmux_status))
        # cbreak disables input echo/buffering but preserves output processing.
        # Raw mode disables ONLCR, breaking TTE's newline-separated frame rows.
        tty.setcbreak(fd)
        mode = termios.tcgetattr(fd)
        mode[1] |= termios.OPOST | termios.ONLCR
        termios.tcsetattr(fd, termios.TCSANOW, mode)
        while active:
            resized = False
            width, height = get_tty_size(fd)
            width, height = max(1, width - 1), max(1, height - 1)
            art = fit_art(art_path.read_text(encoding="utf-8"), width, height)
            if not art.strip():
                print(f"{art_path} is empty; add ASCII art and run again.", file=sys.stderr)
                break
            command = engine + [
                "--frame-rate", "120",
                "--canvas-width", str(width), "--canvas-height", str(height),
                "--anchor-canvas", "sw", "--anchor-text", "c",
                "--reuse-canvas", "--no-eol", "--no-restore-cursor",
            ]
            if args.theme or os.environ.get("NO_COLOR") is not None:
                command.append("--no-color")
            command.append(args.effect if args.effect else "--random-effect")
            # TTE's reuse mode restores a saved cursor below the canvas, then
            # moves up by its height. Seed that cursor before each invocation.
            sys.stdout.write(f"\x1b[2J\x1b[{height + 1};1H\x1b7")
            sys.stdout.flush()
            # Override stale exported dimensions: both TTE engines prefer these
            # environment variables over the TTY query.
            env = dict(os.environ, COLUMNS=str(width), LINES=str(height))
            with subprocess.Popen(command, stdin=subprocess.PIPE, env=env) as process:
                process.stdin.write((art + "\n").encode("utf-8"))
                process.stdin.close()
                while active and process.poll() is None:
                    ready, _, _ = select.select([fd], [], [], 0.05)
                    if ready and os.read(fd, 64):
                        stop(None, None)
            if active and not resized and process.returncode != 0:
                return process.returncode
            if active:
                # Clear the previous effect before the next randomly selected one.
                sys.stdout.write("\x1b[2J\x1b[H")
                sys.stdout.flush()
    finally:
        try:
            if process and process.poll() is None:
                process.terminate()
                process.wait()
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
            sys.stdout.write("\x1b[?25h\x1b[?1049l\x1b[0m")
            sys.stdout.flush()
        finally:
            cleanup.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
