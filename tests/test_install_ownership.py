from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.manage_install_ownership as ownership
from scripts.manage_install_ownership import (
    AllowedArtifact,
    InstallArtifact,
    OwnershipError,
    install_artifacts,
    remove_owned,
)


ROOT = Path(__file__).parents[1]
HELPER = ROOT / "scripts" / "manage_install_ownership.py"


class InstallOwnershipTests(unittest.TestCase):
    def _layout(
        self, root: Path
    ) -> tuple[Path, Path, list[InstallArtifact], dict[str, AllowedArtifact]]:
        home = root / "home"
        prefix = home / ".local" / "share" / "codex-gamepad"
        prefix.mkdir(parents=True)
        (prefix / ".codex-gamepad-install").write_text(
            "codex-gamepad-v1\n", encoding="utf-8"
        )
        sources = root / "sources"
        sources.mkdir()
        launcher_source = sources / "launcher"
        launcher_source.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        rule_source = sources / "rule.json"
        rule_source.write_text('{"title":"Codex Gamepad","rules":[]}\n', encoding="utf-8")
        plist_source = sources / "receiver.plist"
        plist_source.write_text("<plist><dict/></plist>\n", encoding="utf-8")

        artifacts = [
            InstallArtifact(
                "launcher",
                home / ".local" / "bin" / "codex-speak-last",
                "regular",
                source=launcher_source,
                mode=0o755,
            ),
            InstallArtifact(
                "uninstaller",
                home / ".local" / "bin" / "codex-gamepad-uninstall",
                "symlink",
                target=str(prefix / "scripts" / "uninstall-local.sh"),
            ),
            InstallArtifact(
                "karabiner_rule",
                home
                / ".config"
                / "karabiner"
                / "assets"
                / "complex_modifications"
                / "codex-gamepad.json",
                "regular",
                source=rule_source,
                mode=0o644,
            ),
            InstallArtifact(
                "launch_agent",
                home / "Library" / "LaunchAgents" / "com.codex-gamepad.receiver.plist",
                "regular",
                source=plist_source,
                mode=0o644,
            ),
        ]
        allowed = {
            artifact.name: AllowedArtifact(
                artifact.name,
                artifact.path,
                artifact.kind,
                target=artifact.target,
            )
            for artifact in artifacts
        }
        return home, prefix, artifacts, allowed

    def _check_install_command(
        self,
        home: Path,
        prefix: Path,
        artifacts: list[InstallArtifact],
    ) -> list[str]:
        command = [
            sys.executable,
            str(HELPER),
            "check-install",
            "--prefix",
            str(prefix),
            "--manifest",
            str(prefix / ".codex-gamepad-ownership.json"),
            "--home",
            str(home),
            "--profiles-expected",
            "1",
        ]
        for artifact in artifacts:
            if artifact.kind == "regular":
                assert artifact.source is not None
                assert artifact.mode is not None
                command.extend(
                    [
                        "--regular",
                        artifact.name,
                        str(artifact.path),
                        str(artifact.source),
                        format(artifact.mode, "o"),
                    ]
                )
            else:
                assert artifact.target is not None
                command.extend(
                    ["--symlink", artifact.name, str(artifact.path), artifact.target]
                )
        return command

    def test_check_install_validates_parents_without_creating_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, prefix, artifacts, _ = self._layout(root)
            missing_parents = {artifact.path.parent for artifact in artifacts}
            self.assertTrue(all(not path.exists() for path in missing_parents))

            result = subprocess.run(
                self._check_install_command(home, prefix, artifacts),
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(all(not path.exists() for path in missing_parents))
            self.assertFalse((prefix / ".codex-gamepad-ownership.json").exists())

    def test_check_install_rejects_symlink_parent_escape_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, prefix, artifacts, _ = self._layout(root)
            outside = root / "outside"
            outside.mkdir()
            escaped_parent = home / "escaped"
            escaped_parent.symlink_to(outside, target_is_directory=True)
            unsafe = InstallArtifact(
                "launch_agent",
                escaped_parent / "receiver.plist",
                "regular",
                source=artifacts[3].source,
                mode=0o644,
            )

            result = subprocess.run(
                self._check_install_command(home, prefix, [artifacts[0], unsafe]),
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("outside the home directory", result.stderr)
            self.assertFalse((home / ".local" / "bin").exists())
            self.assertFalse(os.path.lexists(outside / "receiver.plist"))
            self.assertFalse((prefix / ".codex-gamepad-ownership.json").exists())

    def test_each_unowned_external_artifact_is_refused_without_following(self) -> None:
        for blocked_name in ("launcher", "uninstaller", "karabiner_rule", "launch_agent"):
            with self.subTest(blocked_name=blocked_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                home, prefix, artifacts, _ = self._layout(root)
                blocked = next(item for item in artifacts if item.name == blocked_name)
                sentinel = root / "sentinel"
                sentinel.write_text("keep\n", encoding="utf-8")
                blocked.path.parent.mkdir(parents=True, exist_ok=True)
                blocked.path.symlink_to(sentinel)

                with self.assertRaisesRegex(OwnershipError, "unowned external artifact"):
                    install_artifacts(
                        prefix,
                        prefix / ".codex-gamepad-ownership.json",
                        artifacts,
                        profiles_expected=True,
                        home=home,
                    )

                self.assertTrue(blocked.path.is_symlink())
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")
                self.assertFalse((prefix / ".codex-gamepad-ownership.json").exists())

    def test_install_and_remove_track_exact_artifacts_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, prefix, artifacts, allowed = self._layout(root)
            manifest_path = prefix / ".codex-gamepad-ownership.json"
            unrelated = home / ".local" / "bin" / "keep-me"

            install_artifacts(
                prefix,
                manifest_path,
                artifacts,
                profiles_expected=True,
                home=home,
            )
            unrelated.write_text("keep\n", encoding="utf-8")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["profiles_expected"])
            self.assertEqual(set(manifest["artifacts"]), set(allowed))
            self.assertEqual(stat.S_IMODE(manifest_path.stat().st_mode), 0o600)
            self.assertEqual(
                stat.S_IMODE(allowed["launcher"].path.stat().st_mode), 0o755
            )
            self.assertEqual(
                stat.S_IMODE(allowed["karabiner_rule"].path.stat().st_mode), 0o644
            )

            remove_owned(manifest_path, allowed)

            self.assertTrue(unrelated.is_file())
            self.assertTrue(all(not os.path.lexists(item.path) for item in artifacts))
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["artifacts"],
                {},
            )

    def test_changed_owned_artifact_blocks_all_removal(self) -> None:
        for changed_name in ("launcher", "uninstaller", "karabiner_rule", "launch_agent"):
            with self.subTest(changed_name=changed_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                home, prefix, artifacts, allowed = self._layout(root)
                manifest_path = prefix / ".codex-gamepad-ownership.json"
                install_artifacts(
                    prefix,
                    manifest_path,
                    artifacts,
                    profiles_expected=False,
                    home=home,
                )
                changed = allowed[changed_name]
                changed.path.unlink()
                changed.path.write_text("not owned\n", encoding="utf-8")

                with self.assertRaisesRegex(OwnershipError, "missing or changed"):
                    remove_owned(manifest_path, allowed)

                self.assertTrue(changed.path.is_file())
                for artifact in artifacts:
                    if artifact.name != changed_name:
                        self.assertTrue(os.path.lexists(artifact.path))
                self.assertTrue(manifest_path.is_file())

    def test_second_quarantine_move_failure_rolls_back_and_can_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, prefix, artifacts, allowed = self._layout(root)
            manifest_path = prefix / ".codex-gamepad-ownership.json"
            install_artifacts(
                prefix,
                manifest_path,
                artifacts,
                profiles_expected=False,
                home=home,
            )
            manifest_before = manifest_path.read_bytes()
            real_move = ownership._move_to_quarantine
            move_count = 0

            def fail_second_move(source: Path, destination: Path) -> None:
                nonlocal move_count
                move_count += 1
                if move_count == 2:
                    raise OSError("injected second move failure")
                real_move(source, destination)

            with mock.patch.object(
                ownership,
                "_move_to_quarantine",
                side_effect=fail_second_move,
            ):
                with self.assertRaisesRegex(OSError, "injected second move failure"):
                    remove_owned(manifest_path, allowed)

            self.assertEqual(manifest_path.read_bytes(), manifest_before)
            self.assertTrue(all(os.path.lexists(item.path) for item in artifacts))
            self.assertFalse(ownership._removal_journal_path(manifest_path).exists())
            for parent in {item.path.parent for item in artifacts}:
                self.assertEqual(list(parent.glob(".*.remove.*")), [])

            remove_owned(manifest_path, allowed)
            self.assertTrue(all(not os.path.lexists(item.path) for item in artifacts))

    def test_pending_removal_journal_recovers_after_process_abort(self) -> None:
        class SimulatedProcessAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, prefix, artifacts, allowed = self._layout(root)
            manifest_path = prefix / ".codex-gamepad-ownership.json"
            install_artifacts(
                prefix,
                manifest_path,
                artifacts,
                profiles_expected=False,
                home=home,
            )
            real_move = ownership._move_to_quarantine
            move_count = 0

            def abort_after_first_move(source: Path, destination: Path) -> None:
                nonlocal move_count
                real_move(source, destination)
                move_count += 1
                if move_count == 1:
                    raise SimulatedProcessAbort

            with mock.patch.object(
                ownership,
                "_move_to_quarantine",
                side_effect=abort_after_first_move,
            ):
                with self.assertRaises(SimulatedProcessAbort):
                    remove_owned(manifest_path, allowed)

            journal_path = ownership._removal_journal_path(manifest_path)
            self.assertTrue(journal_path.is_file())
            self.assertEqual(stat.S_IMODE(journal_path.stat().st_mode), 0o600)
            self.assertTrue(any(not os.path.lexists(item.path) for item in artifacts))

            remove_owned(manifest_path, allowed)

            self.assertFalse(journal_path.exists())
            self.assertTrue(all(not os.path.lexists(item.path) for item in artifacts))

    def test_committed_removal_journal_finishes_cleanup_after_process_abort(self) -> None:
        class SimulatedProcessAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, prefix, artifacts, allowed = self._layout(root)
            manifest_path = prefix / ".codex-gamepad-ownership.json"
            install_artifacts(
                prefix,
                manifest_path,
                artifacts,
                profiles_expected=False,
                home=home,
            )

            with mock.patch.object(
                ownership,
                "_finalize_quarantined",
                side_effect=SimulatedProcessAbort,
            ):
                with self.assertRaises(SimulatedProcessAbort):
                    remove_owned(manifest_path, allowed)

            journal_path = ownership._removal_journal_path(manifest_path)
            self.assertTrue(journal_path.is_file())
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["artifacts"],
                {},
            )

            remove_owned(manifest_path, allowed)

            self.assertFalse(journal_path.exists())
            self.assertTrue(all(not os.path.lexists(item.path) for item in artifacts))

    def test_missing_manifest_never_adopts_during_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, prefix, artifacts, allowed = self._layout(root)
            artifact = artifacts[0]
            artifact.path.parent.mkdir(parents=True)
            artifact.path.write_bytes(artifact.source.read_bytes())
            artifact.path.chmod(artifact.mode)

            with self.assertRaisesRegex(OwnershipError, "rerun the source installer"):
                remove_owned(prefix / ".codex-gamepad-ownership.json", allowed)

            self.assertTrue(artifact.path.is_file())

    def test_run_owned_refuses_modified_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, prefix, artifacts, _ = self._layout(root)
            launcher = artifacts[0]
            log = root / "executed"
            launcher.source.write_text('#!/bin/sh\n: > "$1"\n', encoding="utf-8")
            manifest_path = prefix / ".codex-gamepad-ownership.json"
            install_artifacts(
                prefix,
                manifest_path,
                [launcher],
                profiles_expected=False,
                home=home,
            )
            command = [
                sys.executable,
                str(HELPER),
                "run-owned",
                "--manifest",
                str(manifest_path),
                "--allow-regular",
                "launcher",
                str(launcher.path),
                "--name",
                "launcher",
                "--",
                str(log),
            ]

            first = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(log.is_file())
            log.unlink()
            launcher.path.write_text('#!/bin/sh\n: > "$1"\n# changed\n', encoding="utf-8")
            launcher.path.chmod(0o755)

            second = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(second.returncode, 1)
            self.assertFalse(log.exists())


if __name__ == "__main__":
    unittest.main()
