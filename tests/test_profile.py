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
                        and {
                            "is_game_pad": True,
                            "vendor_id": 11720,
                            "product_id": 12315,
                        }
                        in condition.get("identifiers", [])
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

    def test_vibe_coding_controls_are_exact(self) -> None:
        navigation_rule = self.profile["rules"][0]
        mappings = {
            item["from"]["pointing_button"]: item["to"][0]
            for item in navigation_rule["manipulators"]
            if "pointing_button" in item["from"]
        }
        self.assertEqual(
            mappings,
            {
                "button1": {
                    "key_code": "d",
                    "modifiers": ["left_control", "left_shift"],
                },
                "button2": {"key_code": "escape"},
                "button3": {"key_code": "k", "modifiers": ["left_command"]},
                "button5": {"key_code": "tab"},
                "button7": {
                    "key_code": "open_bracket",
                    "modifiers": ["left_command", "left_shift"],
                },
                "button8": {
                    "key_code": "close_bracket",
                    "modifiers": ["left_command", "left_shift"],
                },
                "button10": {"key_code": "return_or_enter", "repeat": False},
            },
        )

    def test_x_sends_allowlisted_speech_command(self) -> None:
        receiver_rule = self.profile["rules"][1]
        buttons = {
            item["from"]["pointing_button"]
            for item in receiver_rule["manipulators"]
        }
        self.assertEqual(buttons, {"button4"})
        command = receiver_rule["manipulators"][0]["to"][0]["send_user_command"]
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
                for event_key in (
                    "to",
                    "to_if_alone",
                    "to_if_held_down",
                    "to_after_key_up",
                ):
                    for event in manipulator.get(event_key, []):
                        command = event.get("send_user_command")
                        if command is not None:
                            self.assertEqual(command["endpoint"], endpoint)
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
        self.assertEqual(len(generated["rules"][0]["manipulators"]), 11)
        mappings = {
            item["from"]["pointing_button"]: item["to"][0]
            for item in generated["rules"][0]["manipulators"]
            if "pointing_button" in item["from"]
        }
        self.assertEqual(
            mappings["button1"],
            {"key_code": "d", "modifiers": ["left_control", "left_shift"]},
        )
        self.assertEqual(
            mappings["button10"],
            {"key_code": "return_or_enter", "repeat": False},
        )
        self.assertNotIn("button4", mappings)
        self.assertNotIn("button6", mappings)


if __name__ == "__main__":
    unittest.main()
