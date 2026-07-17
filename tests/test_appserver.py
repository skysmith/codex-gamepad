from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_gamepad import appserver
from codex_gamepad.appserver import extract_last_completed_reply, load_last_completed_reply
from codex_gamepad.models import CodexGamepadError


class AppServerExtractionTests(unittest.TestCase):
    def test_selects_final_from_newest_completed_turn(self) -> None:
        thread = {
            "id": "thread-1",
            "turns": [
                {
                    "status": "completed",
                    "completedAt": 20,
                    "items": [
                        {"type": "agentMessage", "phase": "commentary", "text": "ignore"},
                        {"type": "agentMessage", "phase": "final_answer", "text": "new final"},
                    ],
                },
                {
                    "status": "completed",
                    "completedAt": 10,
                    "items": [
                        {"type": "agentMessage", "phase": "final_answer", "text": "old final"}
                    ],
                },
                {
                    "status": "interrupted",
                    "completedAt": 30,
                    "items": [
                        {"type": "agentMessage", "phase": "final_answer", "text": "interrupted"}
                    ],
                },
            ],
        }
        reply = extract_last_completed_reply(thread)
        self.assertEqual(reply.text, "new final")
        self.assertEqual(reply.completed_at, 20)

    def test_legacy_unphased_message(self) -> None:
        thread = {
            "id": "legacy",
            "turns": [
                {
                    "status": "completed",
                    "items": [{"type": "agentMessage", "phase": None, "text": "legacy final"}],
                }
            ],
        }
        self.assertEqual(extract_last_completed_reply(thread).text, "legacy final")

    def test_plan_only_completed_turn_is_not_spoken(self) -> None:
        thread = {
            "id": "plan",
            "turns": [
                {
                    "status": "completed",
                    "items": [{"type": "plan", "text": "A completed plan."}],
                }
            ],
        }
        with self.assertRaises(CodexGamepadError):
            extract_last_completed_reply(thread)

    def test_real_protocol_sequence_against_fake_server(self) -> None:
        fake = Path(__file__).parent / "fixtures" / "fake_app_server.py"
        reply = load_last_completed_reply(command=[sys.executable, str(fake)], timeout=1.0)
        self.assertEqual(reply.thread_id, "019fixture-app-server")
        self.assertEqual(reply.text, "Synthetic final answer.")


class CodexBinaryDiscoveryTests(unittest.TestCase):
    def test_discovers_supported_app_bundle_locations(self) -> None:
        locations = (
            ("system", "ChatGPT.app"),
            ("system", "Codex.app"),
            ("user", "ChatGPT.app"),
            ("user", "Codex.app"),
        )
        for location, bundle in locations:
            with self.subTest(location=location, bundle=bundle):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    system_applications = root / "system-applications"
                    home = root / "home"
                    applications = (
                        system_applications
                        if location == "system"
                        else home / "Applications"
                    )
                    executable = (
                        applications / bundle / appserver.CODEX_BINARY_IN_BUNDLE
                    )
                    executable.parent.mkdir(parents=True)
                    executable.write_text("#!/bin/sh\n", encoding="utf-8")
                    executable.chmod(0o755)

                    with (
                        mock.patch.object(
                            appserver,
                            "SYSTEM_APPLICATIONS_DIRECTORY",
                            system_applications,
                        ),
                        mock.patch.object(appserver.Path, "home", return_value=home),
                        mock.patch.object(appserver.shutil, "which", return_value=None),
                        mock.patch.dict(os.environ, {}, clear=True),
                    ):
                        self.assertEqual(
                            appserver.find_codex_binary(), executable.resolve()
                        )

    def test_explicit_then_environment_then_path_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = root / "explicit-codex"
            environment = root / "environment-codex"
            on_path = root / "path-codex"
            for executable in (explicit, environment, on_path):
                executable.write_text("#!/bin/sh\n", encoding="utf-8")
                executable.chmod(0o755)

            with (
                mock.patch.object(
                    appserver, "SYSTEM_APPLICATIONS_DIRECTORY", root / "missing"
                ),
                mock.patch.object(
                    appserver.Path, "home", return_value=root / "missing-home"
                ),
                mock.patch.object(
                    appserver.shutil, "which", return_value=str(on_path)
                ),
                mock.patch.dict(
                    os.environ, {"CODEX_BINARY": str(environment)}, clear=True
                ),
            ):
                self.assertEqual(
                    appserver.find_codex_binary(explicit), explicit.resolve()
                )
                self.assertEqual(
                    appserver.find_codex_binary(), environment.resolve()
                )

            with (
                mock.patch.object(
                    appserver, "SYSTEM_APPLICATIONS_DIRECTORY", root / "missing"
                ),
                mock.patch.object(
                    appserver.Path, "home", return_value=root / "missing-home"
                ),
                mock.patch.object(
                    appserver.shutil, "which", return_value=str(on_path)
                ),
                mock.patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(appserver.find_codex_binary(), on_path.resolve())


if __name__ == "__main__":
    unittest.main()
