import fcntl
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
import shlex
from unittest.mock import patch

from terminal_auto.controller import Display, Markers, IDLE, BUSY, install_shell
from test_cli import terminal_settings


class AutomaticSessionTests(unittest.TestCase):
    def test_markers_survive_every_read_boundary(self):
        for marker, expected in ((IDLE, "idle"), (BUSY, "busy")):
            for split in range(1, len(marker)):
                parser = Markers()
                parts = parser.feed(b"before" + marker[:split]) + parser.feed(marker[split:] + b"after")
                self.assertEqual([kind for kind, _ in parts if kind != "output"], [expected])
                self.assertEqual(b"".join(data for kind, data in parts if kind == "output"), b"beforeafter")

    def test_alternate_buffer_restore_keeps_shell_screen(self):
        import pyte
        screen = Display(40, 10)
        stream = pyte.Stream(screen)
        stream.feed("shell output\x1b[?1049hagent working")
        self.assertTrue(screen.alternate)
        self.assertIn("agent working", screen.display[0])
        self.assertIn(b"agent working", screen.redraw())
        stream.feed("\x1b[?1049l")
        self.assertFalse(screen.alternate)
        self.assertIn("shell output", screen.display[0])

    def test_split_color_controls_and_utf8_are_forwarded_atomically(self):
        for sequence in (b"\x1b[38;2;123;45;67m", b"\x1b]0;title\x07", "█".encode(), b"\x1b(B"):
            for split in range(1, len(sequence)):
                parser = Markers()
                initial = parser.feed(b"plain" + sequence[:split])
                self.assertEqual(b"".join(data for _, data in initial), b"plain")
                final = parser.feed(sequence[split:] + b"after")
                self.assertEqual(b"".join(data for _, data in final), sequence + b"after")

    def test_shell_install_is_idempotent_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, HOME=directory):
            path = Path(directory, ".bash_profile" if sys.platform == "darwin" else ".bashrc")
            path.write_text("alias keep='true'\n")
            install_shell("bash")
            contents = path.read_text()
            self.assertIn("alias keep='true'", contents)
            self.assertIn("exec screensaver --auto --shell bash", contents)
            install_shell("bash")
            self.assertEqual(path.read_text(), contents)
            self.assertEqual(path.with_name(path.name + ".screensaver-backup").read_text(), "alias keep='true'\n")

    def terminal_session(self, shell, task, check):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".bashrc").write_text("PS1='READY> '\n")
            Path(directory, ".bash_profile").write_text("source ~/.bashrc\n")
            Path(directory, ".zshrc").write_text("PS1='READY> '\n")
            art = Path(directory, "ascii.txt")
            art.write_text("ANIMATION\n")
            master, slave = pty.openpty()
            original = termios.tcgetattr(slave)
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            env = dict(os.environ, HOME=directory, XDG_CONFIG_HOME=directory)
            env.pop("ZDOTDIR", None)
            command = [sys.executable, "-m", "ascii_screensaver", str(art), "--auto", "--shell", shell,
                       "--engine", "tte", "--effect", "expand", "--idle-after", ".2"]
            process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, env=env)
            self.automatic_process = process
            data = bytearray()

            def read_for(seconds):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if select.select([master], [], [], .02)[0]:
                        data.extend(os.read(master, 65536))
                return bytes(data)

            try:
                read_for(.4)
                self.assertIn(b"READY>", data)
                data.clear()
                os.write(master, task.encode() + b"\r")
                check(master, data, read_for, directory)
                os.write(master, b"exit\r")
                deadline = time.monotonic() + 5
                while process.poll() is None and time.monotonic() < deadline:
                    read_for(.05)
                self.assertEqual(process.wait(timeout=1), 0)
                self.assertEqual(terminal_settings(termios.tcgetattr(slave)), terminal_settings(original))
                self.assertFalse(list(Path(directory).rglob("*.log")))
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                os.close(master)
                os.close(slave)

    def test_bash_automatically_starts_and_restores_output_without_logs(self):
        def check(master, data, read_for, directory):
            read_for(1.8)
            self.assertIn(b"\x1b[?1049h", data)
            self.assertIn(b"\x1b[?1049l", data)
            self.assertEqual(bytes(data).count(b"DURING-TASK\r\n"), 1)
            self.assertEqual(bytes(data).count(b"TASK-COMPLETE\r\n"), 1)
            self.assertIn(b"READY>", data)
        self.terminal_session("bash", "sleep .4; printf 'DURING-TASK\\n'; sleep .4; printf 'TASK-COMPLETE\\n'", check)

    @unittest.skipUnless(shutil.which("zsh"), "zsh not installed")
    def test_zsh_automatically_starts_and_restores_output_without_logs(self):
        def check(master, data, read_for, directory):
            read_for(1.8)
            self.assertIn(b"\x1b[?1049h", data)
            self.assertIn(b"\x1b[?1049l", data)
            self.assertIn(b"TASK-COMPLETE\r\n", data)
        self.terminal_session("zsh", "sleep .4; printf 'DURING-TASK\\n'; sleep .4; printf 'TASK-COMPLETE\\n'", check)

    def test_confirmation_prompt_never_gets_covered(self):
        def check(master, data, read_for, directory):
            read_for(.7)
            self.assertIn(b"Proceed? [Y/n]", data)
            self.assertNotIn(b"\x1b[?1049h", data)
            os.write(master, b"y\r")
            read_for(.8)
            self.assertIn(b"READY>", data)
        self.terminal_session("bash", "read -p 'Proceed? [Y/n] ' answer; sleep .1", check)

    def test_command_exit_status_is_preserved_in_shell(self):
        def check(master, data, read_for, directory):
            read_for(.8)
            os.write(master, b"printf 'STATUS-%s\\n' \"$?\"\r")
            read_for(.4)
            self.assertIn(b"STATUS-7\r\n", data)
        self.terminal_session("bash", "sleep .4; (exit 7)", check)

    def test_activity_dismisses_animation_without_cancelling_task(self):
        def check(master, data, read_for, directory):
            read_for(.5)
            self.assertIn(b"\x1b[?1049h", data)
            os.write(master, b"q")
            read_for(.1)
            self.assertIn(b"\x1b[?1049l", data)
            read_for(1.2)
            self.assertIn(b"STILL-FINISHED\r\n", data)
        self.terminal_session("bash", "sleep 1; printf 'STILL-FINISHED\\n'", check)

    def test_resize_restores_output_and_uses_new_terminal_dimensions(self):
        def check(master, data, read_for, directory):
            read_for(.45)
            self.assertIn(b"\x1b[?1049h", data)
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
            self.automatic_process.send_signal(signal.SIGWINCH)
            read_for(.45)
            self.assertIn(b"\x1b[?1049l", data)
            self.assertIn(b"\x1b[40;1H\x1b7", data)
            read_for(.8)
            self.assertIn(b"RESIZE-DONE\r\n", data)
        self.terminal_session("bash", "sleep 1.1; printf 'RESIZE-DONE\\n'", check)

    def test_mouse_movement_resets_inactivity(self):
        def check(master, data, read_for, directory):
            for _ in range(6):
                os.write(master, b"\x1b[<35;10;10M")
                read_for(.08)
            self.assertNotIn(b"\x1b[?1049h", data)
            read_for(.4)
            self.assertIn(b"\x1b[?1049h", data)
            read_for(.8)
        self.terminal_session("bash", "sleep 1.2", check)

    def test_agent_waiting_and_idle_events_stop_overlay_without_exiting_agent(self):
        program = """import os,socket,json,sys,time,tty
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
s.connect(os.environ['SCREENSAVER_CONTROL_SOCKET'])
def send(state):
 s.sendall((json.dumps({'pid':os.getpid(),'state':state})+'\\n').encode())
sys.stdout.write('\\x1b[?1049h\\x1b[2J\\x1b[HAGENT-WORKING')
sys.stdout.flush()
tty.setraw(0)
send('busy')
time.sleep(.8)
sys.stdout.write('\\x1b[HAGENT-PERMISSION?')
sys.stdout.flush()
send('waiting')
time.sleep(.7)
sys.stdout.write('\\x1b[HAGENT-IDLE')
sys.stdout.flush()
send('idle')
time.sleep(.7)
sys.stdout.write('\\x1b[?1049l')
sys.stdout.flush()
"""
        command = shlex.quote(sys.executable) + " -c " + shlex.quote("exec(" + repr(program) + ")")
        def check(master, data, read_for, directory):
            read_for(.5)
            self.assertIn(b"\x1b7", data)  # The animation is drawing in the TUI buffer.
            read_for(.65)
            self.assertIn(b"AGENT-PERMISSION?", data)
            count = bytes(data).count(b"\x1b7")
            read_for(.25)
            self.assertEqual(bytes(data).count(b"\x1b7"), count)
            read_for(.9)
            self.assertIn(b"AGENT-IDLE", data)
            self.assertEqual(bytes(data).count(b"\x1b7"), count)
        self.terminal_session("bash", command, check)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_actual_opencode_plugin_reports_busy_waiting_and_idle(self):
        script = r"""
const fs = require('node:fs'); const net = require('node:net');
(async () => {
  const messages = []; const clients = [];
  const server = net.createServer(socket => {
    clients.push(socket); let buffer = '';
    socket.on('data', chunk => {
      buffer += chunk; let end;
      while ((end = buffer.indexOf('\n')) >= 0) {
        messages.push(JSON.parse(buffer.slice(0,end)).state); buffer = buffer.slice(end+1);
      }
    });
  });
  await new Promise(resolve => server.listen(process.env.SCREENSAVER_CONTROL_SOCKET, resolve));
  const source = fs.readFileSync(process.argv[1], 'utf8');
  const plugin = (await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))).default;
  const hooks = await plugin();
  const pause = () => new Promise(resolve => setTimeout(resolve,30));
  await pause();
  const emit = async (type, properties) => { await hooks.event({event:{type,properties}}); await pause(); };
  await emit('session.status', {sessionID:'one',status:{type:'busy'}});
  await emit('permission.asked', {sessionID:'one',id:'permission'});
  await emit('question.asked', {sessionID:'one',id:'question'});
  await emit('permission.replied', {sessionID:'one',requestID:'permission'});
  await emit('question.replied', {sessionID:'one',requestID:'question'});
  await emit('session.idle', {sessionID:'one'});
  const expected = ['idle','busy','waiting','waiting','waiting','busy','idle'];
  if (JSON.stringify(messages) !== JSON.stringify(expected)) throw Error(JSON.stringify(messages));
  for (const socket of clients) socket.destroy(); server.close();
})().catch(error => { console.error(error); process.exitCode=1; });
"""
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            env = dict(os.environ, SCREENSAVER_CONTROL_SOCKET=str(Path(directory, "control.sock")))
            result = subprocess.run(["node", "-e", script, str(Path(__file__).parents[1] / "terminal_auto/opencode.js")],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
