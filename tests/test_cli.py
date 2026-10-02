import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class InstalledCommandTests(unittest.TestCase):
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
