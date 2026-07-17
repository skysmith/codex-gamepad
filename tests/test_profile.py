from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class KarabinerProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = json.loads((ROOT / "karabiner" / "codex-gamepad.json").read_text())

    def test_every_mapping_is_gamepad_and_codex_scoped(self) -> None:
        for rule in self.profile["rules"]:
            for manipulator in rule["manipulators"]:
                conditions = manipulator["conditions"]
                self.assertTrue(
                    any(
                        condition.get("type") == "device_if"
                        and {"is_game_pad": True} in condition.get("identifiers", [])
                        for condition in conditions
                    )
                )
                self.assertTrue(
                    any(
                        condition.get("type") == "frontmost_application_if"
                        and "^com\\.openai\\.codex$" in condition.get("bundle_identifiers", [])
                        for condition in conditions
                    )
                )

    def test_both_extra_buttons_send_allowlisted_command(self) -> None:
        receiver_rule = self.profile["rules"][1]
        buttons = {item["from"]["pointing_button"] for item in receiver_rule["manipulators"]}
        self.assertEqual(buttons, {"button3", "button6"})
        for manipulator in receiver_rule["manipulators"]:
            command = manipulator["to"][0]["send_user_command"]
            self.assertTrue(command["endpoint"].startswith("/"))
            self.assertEqual(
                command["payload"],
                {"command": "codex_speak_last_response", "version": 1},
            )

    def test_installer_renders_dedicated_endpoint_and_speaker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "profile.json"
            endpoint = str(Path(directory) / "user command.sock")
            speaker = str(Path(directory) / "speaker with spaces")
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "render_profile.py"),
                    str(ROOT / "karabiner" / "codex-gamepad.json"),
                    str(output),
                    "--endpoint",
                    endpoint,
                    "--speaker",
                    speaker,
                ],
                check=True,
            )
            rendered = json.loads(output.read_text(encoding="utf-8"))
            receiver_rule = rendered["rules"][1]
            for manipulator in receiver_rule["manipulators"]:
                self.assertEqual(
                    manipulator["to"][0]["send_user_command"]["endpoint"], endpoint
                )
            legacy_rule = rendered["rules"][2]
            self.assertIn("'" + speaker + "'", legacy_rule["manipulators"][0]["to"][0]["shell_command"])

    def test_upstream_generator_emits_valid_navigation_profile(self) -> None:
        result = subprocess.run(
            ["node", str(ROOT / "karabiner" / "upstream" / "codex_gamepad.json.js")],
            check=True,
            capture_output=True,
            text=True,
        )
        generated = json.loads(result.stdout)
        self.assertEqual(len(generated["rules"]), 1)
        self.assertEqual(len(generated["rules"][0]["manipulators"]), 10)


if __name__ == "__main__":
    unittest.main()
