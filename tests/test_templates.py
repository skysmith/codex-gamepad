from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class TemplateTests(unittest.TestCase):
    def test_plist_values_are_xml_escaped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receiver.plist"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "render_template.py"),
                    str(ROOT / "launchd" / "com.codex-gamepad.receiver.plist.in"),
                    str(output),
                    "--mode",
                    "xml",
                    "RECEIVER_PATH=/tmp/a & b/receiver",
                    "LOG_PATH=/tmp/a & b/log",
                    "ENDPOINT_PATH=/tmp/a & b/socket",
                    "MODE_SWITCHING=1",
                    "KARABINER_CLI=/tmp/a & b/karabiner_cli",
                    "CODEX_PROFILE=Codex & Controller",
                    "GAME_PROFILE=Game & Mode",
                    "ARCADE_CHROME_MARKER=--user-data-dir=/tmp/a & b/Arcade Chrome",
                    "LIVING_FOREST_MARKER=/tmp/a & b/Living Forest/runtime/players/",
                    "SPEAKER_PATH=/tmp/a & b/speaker",
                ],
                check=True,
            )
            subprocess.run(["plutil", "-lint", str(output)], check=True, capture_output=True)
            self.assertIn("&amp;", output.read_text(encoding="utf-8"))

    def test_launcher_values_are_shell_quoted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "launcher"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "render_template.py"),
                    str(ROOT / "scripts" / "codex-speak-last.in"),
                    str(output),
                    "--mode",
                    "shell",
                    "APP_PATH=/tmp/app with ' quote",
                    "PYTHON_PATH=/tmp/python with ' quote",
                ],
                check=True,
            )
            subprocess.run(["sh", "-n", str(output)], check=True)


if __name__ == "__main__":
    unittest.main()
