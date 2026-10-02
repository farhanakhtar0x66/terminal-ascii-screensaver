import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
import fcntl
import pty
import select
import signal
import struct
import termios
import time
from unittest.mock import patch

from ascii_screensaver import engine_effects, hidden_tmux_status, shuffled_effects


def terminal_settings(settings):
    # Darwin sets PENDIN when canonical input is restored. This is transient
    # kernel bookkeeping, not a changed echo/input/output configuration.
    normalized = list(settings)
    normalized[3] &= ~getattr(termios, "PENDIN", 0)
    normalized[6] = [bytes([value]) if isinstance(value, int) else value for value in settings[6]]
    return normalized


class InstalledCommandTests(unittest.TestCase):
    def run_task_in_terminal(self, program, key=None, cancel=False):
        with tempfile.TemporaryDirectory() as directory:
            master, slave = pty.openpty()
            original = termios.tcgetattr(slave)
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            env = dict(os.environ, XDG_CONFIG_HOME=directory, XDG_STATE_HOME=directory)
            env.pop("TMUX", None)
            command = [sys.executable, "-m", "ascii_screensaver", "--engine", "tte", "--effect", "expand",
                       "--run", sys.executable, "-c", program]
            process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, env=env)
            data = bytearray()
            started = time.monotonic()
            sent = False
            try:
                while time.monotonic() - started < 12:
                    if not sent and time.monotonic() - started > .5:
                        if key:
                            os.write(master, key)
                        if cancel:
                            process.send_signal(signal.SIGINT)
                        sent = True
                    if select.select([master], [], [], .05)[0]:
                        data.extend(os.read(master, 65536))
                    elif process.poll() is not None:
                        break
                status = process.wait(timeout=1)
                self.assertEqual(terminal_settings(termios.tcgetattr(slave)), terminal_settings(original))
                logs = list(Path(directory).glob("terminal-ascii-screensaver/logs/*.log"))
                self.assertEqual(len(logs), 1)
                return status, bytes(data), logs[0].read_text()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)
                os.close(slave)

    def test_task_completion_replays_log_and_returns_failure_status(self):
        status, output, log = self.run_task_in_terminal(
            "import sys,time; print('BUILD-OUT', flush=True); print('BUILD-ERR',file=sys.stderr); time.sleep(.3); sys.exit(7)")
        self.assertEqual(status, 7)
        self.assertIn(b"BUILD-OUT", output)
        self.assertIn(b"BUILD-ERR", output)
        self.assertIn("BUILD-OUT", log)
        self.assertIn("BUILD-ERR", log)

    def test_dismissal_does_not_cancel_task(self):
        status, output, log = self.run_task_in_terminal(
            "import time; time.sleep(1); print('STILL-FINISHED')", key=b"q")
        self.assertEqual(status, 0)
        self.assertIn(b"STILL-FINISHED", output)
        self.assertIn("STILL-FINISHED", log)

    def test_ctrl_c_cancels_task(self):
        status, _, _ = self.run_task_in_terminal("import time; time.sleep(30)", cancel=True)
        self.assertEqual(status, 130)

    def test_shuffled_cycles_cover_all_effects_without_boundary_repeats(self):
        effects = ["beams", "matrix", "fireworks", "rain"]
        selection = shuffled_effects(effects)
        previous = None
        for _ in range(30):
            cycle = [next(selection) for _ in effects]
            self.assertCountEqual(cycle, effects)
            self.assertNotEqual(cycle[0], previous)
            previous = cycle[-1]

    def test_single_effect_catalog_is_supported(self):
        selection = shuffled_effects(["beams"])
        self.assertEqual([next(selection) for _ in range(3)], ["beams"] * 3)

    def test_python_engine_catalog(self):
        catalog = engine_effects([sys.executable, "-m", "terminaltexteffects"])
        self.assertIn("beams", catalog)
        self.assertIn("matrix", catalog)
        self.assertGreater(len(catalog), 20)
        self.assertNotIn("help", catalog)

    @unittest.skipUnless(shutil.which("ttfx"), "ttfx not installed")
    def test_rust_engine_catalog(self):
        catalog = engine_effects(["ttfx"])
        self.assertIn("fireworks", catalog)
        self.assertGreater(len(catalog), 20)
        self.assertNotIn("help", catalog)

    @unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
    def test_tmux_status_restores_inheritance_and_explicit_value(self):
        with tempfile.TemporaryDirectory() as directory:
            socket = str(Path(directory) / "tmux.sock")
            def tmux(*args):
                return subprocess.check_output(["tmux", "-S", socket, *args], text=True).strip()
            tmux("-f", "/dev/null", "new-session", "-d", "-s", "check", "sleep 60")
            try:
                pane = tmux("display-message", "-p", "-t", "check", "#{pane_id}")
                with patch.dict(os.environ, TMUX=f"{socket},0,0", TMUX_PANE=pane):
                    tmux("set-option", "-g", "status", "on")
                    tmux("set-option", "-u", "-t", "check", "status")
                    with hidden_tmux_status():
                        self.assertEqual(tmux("show-options", "-v", "-t", "check", "status"), "off")
                    self.assertEqual(tmux("show-options", "-qv", "-t", "check", "status"), "")
                    tmux("set-option", "-t", "check", "status", "2")
                    with self.assertRaises(RuntimeError):
                        with hidden_tmux_status():
                            self.assertEqual(tmux("show-options", "-v", "-t", "check", "status"), "off")
                            raise RuntimeError("simulate animation failure")
                    self.assertEqual(tmux("show-options", "-v", "-t", "check", "status"), "2")
            finally:
                tmux("kill-server")

    def test_new_art_persists_and_empty_prompt_keeps_existing_art(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, XDG_CONFIG_HOME=directory)
            command = [sys.executable, "-m", "ascii_screensaver"]
            location = subprocess.check_output(command + ["--art-path"], env=env, text=True).strip()
            art = Path(location)
            self.assertEqual(art, Path(directory) / "terminal-ascii-screensaver" / "ascii.txt")
            result = subprocess.run(command + ["--new-art"], input="Linux\n", env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            generated = art.read_text()
            self.assertGreater(len(generated.splitlines()), 1)
            result = subprocess.run(command + ["--new-art"], input="\n", env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(art.read_text(), generated)


if __name__ == "__main__":
    unittest.main()
