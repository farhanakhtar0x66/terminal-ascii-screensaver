#!/usr/bin/env python3
"""Loop TerminalTextEffects' random effects over editable local ASCII art."""

import argparse
import importlib.util
import os
import random
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
import tty
from pathlib import Path
from contextlib import ExitStack, contextmanager


def cancel_task(task):
    """Cancel the whole command process group, including build workers."""
    if task.poll() is not None:
        return
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(task.pid, signum)
        except ProcessLookupError:
            return
        try:
            task.wait(timeout=2)
            # The command may exit before its workers; clean up the remaining group.
            try:
                os.killpg(task.pid, signal.SIGTERM)
                time.sleep(0.1)
                os.killpg(task.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return
        except subprocess.TimeoutExpired:
            pass


def run_task(command, default_art):
    """Save command output, animate until completion, then replay/follow the log."""
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    logs = state / "terminal-ascii-screensaver" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="task-", suffix=".log", dir=logs, delete=False) as output:
        log_path = Path(output.name)
        try:
            task = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as error:
            print(f"Could not start task: {error}", file=sys.stderr)
            return 127
        try:
            animation_status = main(default_art, task=task)
            if animation_status:
                cancel_task(task)
            # Any ordinary key dismisses the animation without stopping the task.
            # Replay captured output, then stream new output until the task ends.
            with log_path.open("rb") as log:
                while True:
                    chunk = log.read(65536)
                    if chunk:
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
                    elif task.poll() is not None:
                        break
                    else:
                        time.sleep(0.05)
            status = task.wait()
            return animation_status or (status if status >= 0 else 128 - status)
        except KeyboardInterrupt:
            cancel_task(task)
            return 130
        finally:
            if task.poll() is None:
                cancel_task(task)
            print(f"\nTask log: {log_path}", file=sys.stderr)


def engine_effects(engine):
    """Discover the actual effect catalog from either engine's CLI."""
    help_text = subprocess.check_output(engine + ["--help"], text=True, timeout=10)
    if "Commands:\n" in help_text:
        section = help_text.split("Commands:\n", 1)[1].split("Options:", 1)[0]
    elif "Effect:\n" in help_text:
        section = help_text.split("Effect:\n", 1)[1]
    else:
        raise ValueError("Could not discover animation effects from the engine")
    effects = list(dict.fromkeys(re.findall(r"^ {2,4}([a-z][a-z0-9]*) {2,}\S", section, re.MULTILINE)))
    effects = [effect for effect in effects if effect != "help"]
    if not effects:
        raise ValueError("The animation engine did not report any effects")
    return effects


def shuffled_effects(effects):
    """Play each effect once per shuffled cycle, with no boundary repeat."""
    previous = None
    while True:
        cycle = list(effects)
        if not cycle:
            raise ValueError("An effect cycle cannot be empty")
        random.shuffle(cycle)
        if len(cycle) > 1 and cycle[0] == previous:
            index = random.randrange(1, len(cycle))
            cycle[0], cycle[index] = cycle[index], cycle[0]
        for effect in cycle:
            previous = effect
            yield effect


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


def main(default_art=None, task=None):
    parser = argparse.ArgumentParser(description="Animated ASCII terminal screensaver")
    parser.add_argument("--new-art", action="store_true", help="replace ascii.txt with newly generated text art")
    parser.add_argument("--effect", help="loop a specific ttfx effect instead of choosing randomly (e.g. beams)")
    parser.add_argument("--theme", "--no-color", action="store_true", help="use your terminal's foreground color instead of effect palettes")
    parser.add_argument("--engine", choices=("auto", "ttfx", "tte"), default="auto", help="animation engine (auto prefers installed ttfx)")
    parser.add_argument("--art-path", action="store_true", help="print the artwork file location and exit")
    parser.add_argument("--keep-tmux-status", action="store_true", help="leave the tmux status bar visible")
    parser.add_argument("--run", nargs=argparse.REMAINDER, help="animate while a non-interactive command runs; must be the last option")
    parser.add_argument("--auto", action="store_true", help="start a shell with automatic idle-task animations")
    parser.add_argument("--shell", choices=("bash", "zsh"), default=Path(os.environ.get("SHELL", "/bin/bash")).name if Path(os.environ.get("SHELL", "/bin/bash")).name in ("bash", "zsh") else "bash")
    parser.add_argument("--idle-after", type=float, default=10, help="unattended seconds before automatic animation (default: 10)")
    parser.add_argument("--install-shell", choices=("bash", "zsh"), help="enable automatic sessions in this shell's rc file")
    parser.add_argument("--install-opencode", action="store_true", help="install the OpenCode busy/permission/question integration")
    parser.add_argument("art_file", nargs="?", help="optional ASCII art text file")
    args = parser.parse_args()
    if args.install_shell or args.install_opencode:
        from terminal_auto.controller import install_opencode, install_shell
        if args.install_shell:
            print(f"Enabled automatic sessions in {install_shell(args.install_shell)}. Open a new terminal.")
        if args.install_opencode:
            print(f"Installed {install_opencode()}. Quit and restart OpenCode inside an automatic session.")
        return 0
    command = args.run
    if command is not None:
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error("--run requires a command")
        if args.new_art or args.art_path:
            parser.error("--run cannot be combined with --new-art or --art-path")
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
    if not art_path.read_text(encoding="utf-8").strip() and not args.auto:
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
    try:
        effects = None if args.effect else shuffled_effects(engine_effects(engine))
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"Could not load animations: {error}", file=sys.stderr)
        return 1
    current_effect = args.effect
    if args.auto:
        if command is not None or args.new_art:
            parser.error("--auto cannot be combined with --run or --new-art")
        from terminal_auto.controller import session
        if args.effect:
            from itertools import repeat
            effects = repeat(args.effect)
        return session(args.shell, args.idle_after, engine, art_path, effects,
                       args.theme or os.environ.get("NO_COLOR") is not None,
                       lambda: hidden_tmux_status(not args.keep_tmux_status))
    if command is not None and task is None:
        return run_task(command, default_art)

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
        if _signum and task is not None:
            cancel_task(task)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, stop)

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
        while active and (task is None or task.poll() is None):
            resized = False
            if current_effect is None:
                current_effect = next(effects)
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
            command.append(current_effect)
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
                while active and process.poll() is None and (task is None or task.poll() is None):
                    ready, _, _ = select.select([fd], [], [], 0.05)
                    if ready and os.read(fd, 64):
                        stop(None, None)
                if task is not None and task.poll() is not None and process.poll() is None:
                    process.terminate()
            if active and not resized and process.returncode != 0 and (task is None or task.poll() is None):
                return process.returncode
            if not resized and not args.effect:
                current_effect = None
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
