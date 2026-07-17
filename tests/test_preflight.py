from __future__ import annotations

import json
import os
import plistlib
import socket
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).parents[1]
NAVIGATION = "Codex Gamepad — navigation (8BitDo Ultimate 2C)"
RECEIVER = "Codex Gamepad — Kokoro speak/stop (Karabiner 16 receiver)"


class PreflightTests(unittest.TestCase):
    def _executable(self, path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def _fixture(self, root: Path) -> tuple[dict[str, str], socket.socket]:
        home = root / "home"
        home.mkdir()

        karabiner_app = root / "Karabiner-Elements.app"
        (karabiner_app / "Contents").mkdir(parents=True)
        with (karabiner_app / "Contents" / "Info.plist").open("wb") as handle:
            plistlib.dump({"CFBundleShortVersionString": "16.0.0"}, handle)

        karabiner_cli = root / "karabiner_cli"
        self._executable(
            karabiner_cli,
            'case "$1" in\n'
            '  --version-number) exit 0 ;;\n'
            '  --lint-complex-modifications) exit 0 ;;\n'
            '  --list-connected-devices) printf \'[{"device_id":4815162342,"device_identifiers":{"is_game_pad":true,"is_keyboard":false,"product_id":12315,"vendor_id":11720},"manufacturer":"8BitDo","product":"Ultimate 2C Wireless Controller","transport":"Bluetooth Low Energy","serial_number":"SERIAL-SECRET-123","bluetooth_address":"AA:BB:CC:DD:EE:FF","unexpected":"UNRECOGNIZED-SECRET"}]\\n\' ;;\n'
            "esac\n",
        )

        rule = root / "codex-gamepad.json"
        rule.write_text(json.dumps({"title": "Codex Gamepad", "rules": []}), encoding="utf-8")
        codex_profile = {
            "name": "Codex Controller",
            "selected": True,
            "complex_modifications": {
                "rules": [
                    {"description": NAVIGATION},
                    {"description": RECEIVER},
                ]
            },
            "devices": [
                {
                    "identifiers": {
                        "is_game_pad": True,
                        "product_id": 12315,
                        "vendor_id": 11720,
                    },
                    "ignore": False,
                    "mouse_discard_x": True,
                    "mouse_discard_y": True,
                    "mouse_discard_vertical_wheel": True,
                    "mouse_discard_horizontal_wheel": True,
                }
            ],
        }
        game_profile = deepcopy(codex_profile)
        game_profile.update({"name": "Game Mode", "selected": False})
        game_profile["devices"][0]["ignore"] = True
        config = root / "karabiner.json"
        config.write_text(
            json.dumps({"profiles": [codex_profile, game_profile]}),
            encoding="utf-8",
        )
        profile_state = (
            home
            / "Library"
            / "Application Support"
            / "Codex Gamepad"
            / "karabiner-profile-state.json"
        )
        profile_state.parent.mkdir(parents=True)
        profile_state.write_text(
            json.dumps(
                {
                    "version": 1,
                    "managed_profiles": ["Codex Controller", "Game Mode"],
                    "restore_profile": None,
                }
            ),
            encoding="utf-8",
        )
        profile_state.chmod(0o600)

        receiver = root / "codex-gamepad-receiver"
        self._executable(receiver, "exit 0\n")
        endpoint = root / "user-command.sock"
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(endpoint))

        launch_agent = root / "receiver.plist"
        with launch_agent.open("wb") as handle:
            plistlib.dump(
                {
                    "ProgramArguments": [str(receiver)],
                    "EnvironmentVariables": {
                        "CODEX_GAMEPAD_ENDPOINT": str(endpoint),
                        "CODEX_GAMEPAD_MODE_SWITCHING": "1",
                        "CODEX_GAMEPAD_CODEX_PROFILE": "Codex Controller",
                        "CODEX_GAMEPAD_GAME_PROFILE": "Game Mode",
                        "CODEX_GAMEPAD_KARABINER_CLI": str(karabiner_cli),
                    },
                },
                handle,
            )
        launchctl = root / "launchctl"
        self._executable(launchctl, "exit 0\n")

        codex_app = root / "ChatGPT.app"
        (codex_app / "Contents" / "Resources").mkdir(parents=True)
        with (codex_app / "Contents" / "Info.plist").open("wb") as handle:
            plistlib.dump({"CFBundleIdentifier": "com.openai.codex"}, handle)
        self._executable(codex_app / "Contents" / "Resources" / "codex", "exit 0\n")

        launcher = root / "codex-speak-last"
        self._executable(
            launcher,
            'if [[ "$1" == "--check-speech-runtime" ]]; then\n'
            '  [[ -f "$HOME/.local/share/codex-gamepad/models/kokoro-v1.0.onnx" '
            '&& -f "$HOME/.local/share/codex-gamepad/models/voices-v1.0.bin" ]]\n'
            "  exit\n"
            "fi\n"
            "printf 'PRIVATE RESPONSE MUST NOT LEAK\\n'\n"
            "exit 0\n",
        )
        model_directory = home / ".local" / "share" / "codex-gamepad" / "models"
        model_directory.mkdir(parents=True)
        (model_directory / "kokoro-v1.0.onnx").touch()
        (model_directory / "voices-v1.0.bin").touch()

        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(home),
                "CODEX_GAMEPAD_PREFLIGHT_PYTHON": sys.executable,
                "CODEX_GAMEPAD_KARABINER_APP": str(karabiner_app),
                "CODEX_GAMEPAD_KARABINER_CLI": str(karabiner_cli),
                "CODEX_GAMEPAD_KARABINER_RULE": str(rule),
                "CODEX_GAMEPAD_KARABINER_CONFIG": str(config),
                "CODEX_GAMEPAD_LAUNCH_AGENT": str(launch_agent),
                "CODEX_GAMEPAD_LAUNCHCTL": str(launchctl),
                "CODEX_GAMEPAD_CODEX_APP": str(codex_app),
                "CODEX_GAMEPAD_LAUNCHER": str(launcher),
            }
        )
        return environment, listener

    def test_ready_machine_passes_without_exposing_response_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment, listener = self._fixture(Path(directory))
            try:
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "preflight.sh")],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
            finally:
                listener.close()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("0 failure(s)", result.stdout)
            self.assertIn("8BitDo", result.stdout)
            self.assertIn(
                "PASS  The Codex Controller profile safely captures the connected gamepad.",
                result.stdout,
            )
            self.assertIn(
                "PASS  Game Mode releases the connected gamepad to foreground games.",
                result.stdout,
            )
            self.assertIn('"manufacturer":"8BitDo"', result.stdout)
            self.assertIn('"product_id":12315', result.stdout)
            self.assertIn('"transport":"Bluetooth Low Energy"', result.stdout)
            self.assertNotIn("PRIVATE RESPONSE", result.stdout + result.stderr)
            for secret in (
                "4815162342",
                "SERIAL-SECRET-123",
                "AA:BB:CC:DD:EE:FF",
                "UNRECOGNIZED-SECRET",
                "is_keyboard",
            ):
                self.assertNotIn(secret, result.stdout + result.stderr)

    def test_missing_kokoro_assets_are_a_blocker_without_audible_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, listener = self._fixture(root)
            (
                Path(environment["HOME"])
                / ".local"
                / "share"
                / "codex-gamepad"
                / "models"
                / "kokoro-v1.0.onnx"
            ).unlink()
            try:
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "preflight.sh")],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
            finally:
                listener.close()
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(
                "FAIL  The local Kokoro speech runtime is incomplete",
                result.stdout,
            )
            self.assertNotIn("PRIVATE RESPONSE", result.stdout + result.stderr)

    def test_connected_gamepad_ignored_in_selected_profile_is_a_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, listener = self._fixture(root)
            config_path = Path(environment["CODEX_GAMEPAD_KARABINER_CONFIG"])
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["profiles"][0]["devices"][0]["ignore"] = True
            config_path.write_text(json.dumps(config), encoding="utf-8")
            try:
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "preflight.sh")],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
            finally:
                listener.close()
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(
                "FAIL  The connected gamepad is ignored in the selected Karabiner profile",
                result.stdout,
            )

    def test_connected_gamepad_requires_matching_profile_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, listener = self._fixture(root)
            config_path = Path(environment["CODEX_GAMEPAD_KARABINER_CONFIG"])
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["profiles"][0]["devices"][0]["identifiers"]["product_id"] = 999
            config_path.write_text(json.dumps(config), encoding="utf-8")
            try:
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "preflight.sh")],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
            finally:
                listener.close()
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(
                "FAIL  The connected gamepad has no matching device entry with ignore:false",
                result.stdout,
            )

    def test_connected_gamepad_requires_all_stick_outputs_discarded(self) -> None:
        discard_keys = (
            "mouse_discard_x",
            "mouse_discard_y",
            "mouse_discard_vertical_wheel",
            "mouse_discard_horizontal_wheel",
        )
        for discard_key in discard_keys:
            with self.subTest(discard_key=discard_key), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                environment, listener = self._fixture(root)
                config_path = Path(environment["CODEX_GAMEPAD_KARABINER_CONFIG"])
                config = json.loads(config_path.read_text(encoding="utf-8"))
                config["profiles"][0]["devices"][0][discard_key] = False
                config_path.write_text(json.dumps(config), encoding="utf-8")
                try:
                    result = subprocess.run(
                        ["bash", str(ROOT / "scripts" / "preflight.sh")],
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                    )
                finally:
                    listener.close()
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(
                    "FAIL  The connected gamepad can emit stick pointer or scroll output",
                    result.stdout,
                )
                self.assertIn("enable Discard X, Discard Y", result.stdout)

    def test_game_mode_may_be_selected_when_paired_profiles_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, listener = self._fixture(root)
            config_path = Path(environment["CODEX_GAMEPAD_KARABINER_CONFIG"])
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["profiles"][0]["selected"] = False
            config["profiles"][1]["selected"] = True
            config_path.write_text(json.dumps(config), encoding="utf-8")
            try:
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "preflight.sh")],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
            finally:
                listener.close()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "PASS  The Codex Controller profile safely captures the connected gamepad.",
                result.stdout,
            )
            self.assertIn(
                "PASS  Game Mode releases the connected gamepad to foreground games.",
                result.stdout,
            )

    def test_missing_named_codex_profile_is_a_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, listener = self._fixture(root)
            config_path = Path(environment["CODEX_GAMEPAD_KARABINER_CONFIG"])
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["profiles"][0]["name"] = "Default profile"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            try:
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "preflight.sh")],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
            finally:
                listener.close()
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("FAIL  The Codex Controller Karabiner profile is missing", result.stdout)

    def test_disconnected_controller_still_requires_safe_game_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, listener = self._fixture(root)
            config_path = Path(environment["CODEX_GAMEPAD_KARABINER_CONFIG"])
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["profiles"][1]["devices"][0]["ignore"] = False
            config_path.write_text(json.dumps(config), encoding="utf-8")
            self._executable(
                Path(environment["CODEX_GAMEPAD_KARABINER_CLI"]),
                'case "$1" in --version-number|--lint-complex-modifications) exit 0;; '
                '--list-connected-devices) printf \'[]\\n\';; esac\n',
            )
            try:
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "preflight.sh")],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
            finally:
                listener.close()
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(
                "FAIL  The paired profiles do not safely capture and release the verified 8BitDo.",
                result.stdout,
            )

    def test_unsafe_profile_ownership_state_is_a_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, listener = self._fixture(root)
            (
                Path(environment["HOME"])
                / "Library"
                / "Application Support"
                / "Codex Gamepad"
                / "karabiner-profile-state.json"
            ).chmod(0o644)
            try:
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "preflight.sh")],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
            finally:
                listener.close()
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("FAIL  Profile ownership state is missing or unsafe", result.stdout)

    def test_missing_controller_and_dry_run_are_warnings_not_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, listener = self._fixture(root)
            self._executable(
                Path(environment["CODEX_GAMEPAD_KARABINER_CLI"]),
                'case "$1" in --version-number|--lint-complex-modifications) exit 0;; '
                '--list-connected-devices) exit 1;; esac\n',
            )
            self._executable(
                Path(environment["CODEX_GAMEPAD_LAUNCHER"]),
                '[[ "$1" == "--check-speech-runtime" ]] && exit 0\nexit 1\n',
            )
            try:
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "preflight.sh")],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
            finally:
                listener.close()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("WARN  Speech dry-run did not complete", result.stdout)
            self.assertIn("WARN  Connected devices could not be listed", result.stdout)


if __name__ == "__main__":
    unittest.main()
