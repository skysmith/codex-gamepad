from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class InstallScriptSafetyTests(unittest.TestCase):
    def _environment(self, home: Path, prefix: Path) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(home),
                "CODEX_GAMEPAD_PREFIX": str(prefix),
                "CODEX_GAMEPAD_BIN_DIR": str(home / ".local" / "bin"),
            }
        )
        return environment

    def _fake_python(self, home: Path, *, name: str = "fake-python") -> Path:
        executable = home / name
        executable.write_text(
            "#!/bin/sh\n"
            'if [ "${1:-}" = "-c" ]; then exit 0; fi\n'
            f"exec {shlex.quote(sys.executable)} \"$@\"\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return executable

    def _fake_karabiner_cli(self, home: Path) -> Path:
        executable = home / "fake-karabiner-cli"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        return executable

    def _write_fail_once_python_wrapper(
        self,
        path: Path,
        target: Path,
        fail_argument: str,
        marker: Path,
    ) -> None:
        path.write_text(
            "import os\n"
            "import subprocess\n"
            "import sys\n"
            f"marker = {str(marker)!r}\n"
            f"if {fail_argument!r} in sys.argv[1:] and not os.path.exists(marker):\n"
            "    open(marker, 'w', encoding='utf-8').close()\n"
            "    print('injected one-time cleanup failure', file=sys.stderr)\n"
            "    raise SystemExit(86)\n"
            f"raise SystemExit(subprocess.call([sys.executable, {str(target)!r}, *sys.argv[1:]]))\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _install(self, home: Path, prefix: Path) -> dict[str, str]:
        python = self._fake_python(home)
        environment = self._environment(home, prefix)
        environment["CODEX_GAMEPAD_PYTHON"] = str(python)
        result = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "install-local.sh"),
                "--python",
                str(python),
                "--skip-receiver",
                "--skip-karabiner",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(
            any((prefix / "src" / "codex_gamepad").rglob("__pycache__"))
        )
        self.assertFalse(any((prefix / "src" / "codex_gamepad").rglob("*.pyc")))
        return environment

    def _install_with_karabiner(
        self,
        home: Path,
        prefix: Path,
        config: Path,
    ) -> dict[str, str]:
        python = self._fake_python(home)
        karabiner_cli = self._fake_karabiner_cli(home)
        environment = self._environment(home, prefix)
        environment.update(
            {
                "CODEX_GAMEPAD_KARABINER_CLI": str(karabiner_cli),
                "CODEX_GAMEPAD_KARABINER_CONFIG": str(config),
                "CODEX_GAMEPAD_PYTHON": str(python),
            }
        )
        result = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "install-local.sh"),
                "--python",
                str(python),
                "--skip-receiver",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return environment

    def _karabiner_dry_run(
        self,
        home: Path,
        prefix: Path,
        config: Path,
    ) -> subprocess.CompletedProcess[str]:
        python = self._fake_python(home)
        karabiner_cli = self._fake_karabiner_cli(home)
        environment = self._environment(home, prefix)
        environment.update(
            {
                "CODEX_GAMEPAD_KARABINER_CLI": str(karabiner_cli),
                "CODEX_GAMEPAD_KARABINER_CONFIG": str(config),
                "CODEX_GAMEPAD_PYTHON": str(python),
            }
        )
        return subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "install-local.sh"),
                "--dry-run",
                "--python",
                str(python),
                "--skip-receiver",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_dry_run_validates_safe_profiles_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / ".local" / "share" / "codex-gamepad"
            config = home / "karabiner.json"
            config.write_text(
                json.dumps({"profiles": [{"name": "Default", "selected": True}]}),
                encoding="utf-8",
            )
            original = config.read_bytes()
            state = (
                home
                / "Library"
                / "Application Support"
                / "Codex Gamepad"
                / "karabiner-profile-state.json"
            )

            result = self._karabiner_dry_run(home, prefix, config)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Would configure", result.stdout)
            self.assertIn("Dry run complete", result.stdout)
            self.assertNotIn("Install complete", result.stdout)
            self.assertEqual(config.read_bytes(), original)
            self.assertFalse(state.exists())
            self.assertFalse(state.parent.exists())
            self.assertFalse(prefix.exists())
            self.assertFalse((home / ".local" / "bin").exists())
            self.assertFalse(
                (home / ".config" / "karabiner" / "assets").exists()
            )

    def test_dry_run_refuses_profile_collision_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / ".local" / "share" / "codex-gamepad"
            config = home / "karabiner.json"
            config.write_text(
                json.dumps(
                    {
                        "profiles": [
                            {"name": "Default", "selected": True},
                            {"name": "Codex Controller", "selected": False},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            original = config.read_bytes()

            result = self._karabiner_dry_run(home, prefix, config)

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("--adopt-existing", result.stderr)
            self.assertEqual(config.read_bytes(), original)
            self.assertFalse(prefix.exists())
            self.assertFalse(
                (
                    home
                    / "Library"
                    / "Application Support"
                    / "Codex Gamepad"
                    / "karabiner-profile-state.json"
                ).exists()
            )

    def test_dry_run_refuses_invalid_profile_ownership_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / ".local" / "share" / "codex-gamepad"
            config = home / "karabiner.json"
            config.write_text(
                json.dumps({"profiles": [{"name": "Default", "selected": True}]}),
                encoding="utf-8",
            )
            original_config = config.read_bytes()
            state = (
                home
                / "Library"
                / "Application Support"
                / "Codex Gamepad"
                / "karabiner-profile-state.json"
            )
            state.parent.mkdir(parents=True)
            state.write_text(
                json.dumps(
                    {
                        "version": 999,
                        "managed_profiles": ["Codex Controller", "Game Mode"],
                        "restore_profile": "Default",
                    }
                ),
                encoding="utf-8",
            )
            state.chmod(0o600)
            original_state = state.read_bytes()

            result = self._karabiner_dry_run(home, prefix, config)

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("unsupported version", result.stderr)
            self.assertEqual(config.read_bytes(), original_config)
            self.assertEqual(state.read_bytes(), original_state)
            self.assertFalse(prefix.exists())
            self.assertEqual(list(state.parent.glob(".*.tmp")), [])

    def test_uninstall_preserves_models_and_allows_safe_reinstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / ".local" / "share" / "codex-gamepad"
            environment = self._install(home, prefix)
            (prefix / "models").mkdir()
            (prefix / "models" / "model.bin").write_bytes(b"model")
            (prefix / "venv").mkdir()
            result = subprocess.run(
                ["bash", str(prefix / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((prefix / "models" / "model.bin").is_file())
            self.assertFalse((prefix / "venv").exists())
            self.assertEqual(
                (prefix / ".codex-gamepad-install").read_text(encoding="utf-8"),
                "codex-gamepad-v1\n",
            )
            manifest = json.loads(
                (prefix / ".codex-gamepad-ownership.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["artifacts"], {})

            self._install(home, prefix)

            self.assertTrue((prefix / "models" / "model.bin").is_file())
            self.assertTrue((prefix / "scripts" / "uninstall-local.sh").is_file())

    def test_installed_venv_makes_uninstall_checkout_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / ".local" / "share" / "codex-gamepad"
            environment = self._install(home, prefix)
            used = home / "installed-venv-used"
            venv_python = prefix / "venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.write_text(
                "#!/bin/sh\n"
                f"printf used >> {shlex.quote(str(used))}\n"
                'if [ "${1:-}" = "-c" ]; then exit 0; fi\n'
                f"exec {shlex.quote(sys.executable)} \"$@\"\n",
                encoding="utf-8",
            )
            venv_python.chmod(0o755)
            environment.pop("CODEX_GAMEPAD_PYTHON", None)

            result = subprocess.run(
                ["bash", str(prefix / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(used.is_file())
            self.assertFalse((prefix / "venv").exists())

    def test_uninstall_removes_owned_profiles_and_restores_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            prefix = home / ".local" / "share" / "codex-gamepad"
            home.mkdir()
            config = home / "karabiner.json"
            config.write_text(
                json.dumps(
                    {"profiles": [{"name": "Default profile", "selected": True}]}
                ),
                encoding="utf-8",
            )
            environment = self._install_with_karabiner(home, prefix, config)
            installed_uninstaller = prefix / "scripts" / "uninstall-local.sh"
            installed_profile_helper = prefix / "scripts" / "configure_gamepad_profiles.py"
            uninstall_launcher = home / ".local" / "bin" / "codex-gamepad-uninstall"
            self.assertTrue(os.access(installed_uninstaller, os.X_OK))
            self.assertTrue(os.access(installed_profile_helper, os.X_OK))
            self.assertEqual(uninstall_launcher.resolve(), installed_uninstaller.resolve())
            self.assertEqual(
                (prefix / "LICENSE").read_text(encoding="utf-8"),
                (ROOT / "LICENSE").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (prefix / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"),
                (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"),
            )
            state = (
                home
                / "Library"
                / "Application Support"
                / "Codex Gamepad"
                / "karabiner-profile-state.json"
            )
            self.assertTrue(state.is_file())
            configured = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(
                [profile["name"] for profile in configured["profiles"]],
                ["Default profile", "Codex Controller", "Game Mode"],
            )

            result = subprocess.run(
                ["bash", str(uninstall_launcher)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            restored = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(restored["profiles"], [{"name": "Default profile", "selected": True}])
            self.assertFalse(state.exists())
            self.assertFalse(uninstall_launcher.exists())
            self.assertFalse(
                (
                    home
                    / ".config"
                    / "karabiner"
                    / "assets"
                    / "complex_modifications"
                    / "codex-gamepad.json"
                ).exists()
            )

            self._install_with_karabiner(home, prefix, config)
            reconfigured = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(
                [profile["name"] for profile in reconfigured["profiles"]],
                ["Default profile", "Codex Controller", "Game Mode"],
            )
            self.assertTrue(state.is_file())

    def test_uninstall_refuses_missing_expected_profile_state_before_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / ".local" / "share" / "codex-gamepad"
            config = home / "karabiner.json"
            config.write_text(
                json.dumps({"profiles": [{"name": "Default", "selected": True}]}),
                encoding="utf-8",
            )
            environment = self._install_with_karabiner(home, prefix, config)
            state = (
                home
                / "Library"
                / "Application Support"
                / "Codex Gamepad"
                / "karabiner-profile-state.json"
            )
            state.unlink()
            config_before = config.read_bytes()
            manifest = prefix / ".codex-gamepad-ownership.json"
            manifest_before = manifest.read_bytes()
            launcher = home / ".local" / "bin" / "codex-speak-last"
            uninstaller = home / ".local" / "bin" / "codex-gamepad-uninstall"
            rule = (
                home
                / ".config"
                / "karabiner"
                / "assets"
                / "complex_modifications"
                / "codex-gamepad.json"
            )

            result = subprocess.run(
                ["bash", str(prefix / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Ownership state is missing", result.stderr)
            self.assertEqual(config.read_bytes(), config_before)
            self.assertEqual(manifest.read_bytes(), manifest_before)
            self.assertTrue(launcher.is_file())
            self.assertTrue(uninstaller.is_symlink())
            self.assertTrue(rule.is_file())

    def test_uninstall_resumes_after_manifest_commit_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / ".local" / "share" / "codex-gamepad"
            config = home / "karabiner.json"
            config.write_text(
                json.dumps({"profiles": [{"name": "Default", "selected": True}]}),
                encoding="utf-8",
            )
            environment = self._install_with_karabiner(home, prefix, config)
            state = (
                home
                / "Library"
                / "Application Support"
                / "Codex Gamepad"
                / "karabiner-profile-state.json"
            )
            manifest_path = prefix / ".codex-gamepad-ownership.json"
            installed_helper = prefix / "scripts" / "manage_install_ownership.py"
            self._write_fail_once_python_wrapper(
                installed_helper,
                ROOT / "scripts" / "manage_install_ownership.py",
                "set-profiles-expected",
                home / "manifest-commit-failed-once",
            )

            first = subprocess.run(
                ["bash", str(prefix / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertNotEqual(first.returncode, 0)
            self.assertIn("injected one-time cleanup failure", first.stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["profiles_expected"])
            cleanup_state = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(cleanup_state["cleanup"]["phase"], "profiles_removed")
            self.assertEqual(
                json.loads(config.read_text(encoding="utf-8"))["profiles"],
                [{"name": "Default", "selected": True}],
            )
            self.assertTrue((home / ".local" / "bin" / "codex-speak-last").is_file())

            second = subprocess.run(
                ["bash", str(prefix / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertFalse(state.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(manifest["profiles_expected"])
            self.assertEqual(manifest["artifacts"], {})

    def test_uninstall_resumes_after_profile_state_finalize_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / ".local" / "share" / "codex-gamepad"
            config = home / "karabiner.json"
            config.write_text(
                json.dumps({"profiles": [{"name": "Default", "selected": True}]}),
                encoding="utf-8",
            )
            environment = self._install_with_karabiner(home, prefix, config)
            state = (
                home
                / "Library"
                / "Application Support"
                / "Codex Gamepad"
                / "karabiner-profile-state.json"
            )
            manifest_path = prefix / ".codex-gamepad-ownership.json"
            installed_helper = prefix / "scripts" / "configure_gamepad_profiles.py"
            self._write_fail_once_python_wrapper(
                installed_helper,
                ROOT / "scripts" / "configure_gamepad_profiles.py",
                "--finalize-remove",
                home / "profile-finalize-failed-once",
            )

            first = subprocess.run(
                ["bash", str(prefix / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertNotEqual(first.returncode, 0)
            self.assertIn("injected one-time cleanup failure", first.stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(manifest["profiles_expected"])
            cleanup_state = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(cleanup_state["cleanup"]["phase"], "profiles_removed")
            self.assertTrue((home / ".local" / "bin" / "codex-speak-last").is_file())

            second = subprocess.run(
                ["bash", str(prefix / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertFalse(state.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(manifest["profiles_expected"])
            self.assertEqual(manifest["artifacts"], {})

    def test_normal_reinstall_migrates_exact_pre_manifest_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / ".local" / "share" / "codex-gamepad"
            prefix.mkdir(parents=True)
            (prefix / ".codex-gamepad-install").write_text(
                "codex-gamepad-v1\n", encoding="utf-8"
            )
            installed_prefix = prefix.resolve()
            python = self._fake_python(home)
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            launcher = bin_dir / "codex-speak-last"
            launcher.write_text(
                "#!/bin/sh\n\n"
                f"APP_PATH={shlex.quote(str(installed_prefix))}\n"
                f"PYTHON_PATH={shlex.quote(str(python))}\n"
                'PYTHONPATH="$APP_PATH/src${PYTHONPATH:+:$PYTHONPATH}"\n'
                "export PYTHONPATH\n"
                'exec "$PYTHON_PATH" -m codex_gamepad "$@"\n',
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            (bin_dir / "codex-gamepad-uninstall").symlink_to(
                installed_prefix / "scripts" / "uninstall-local.sh"
            )
            environment = self._environment(home, prefix)
            environment["CODEX_GAMEPAD_PYTHON"] = str(python)

            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "install-local.sh"),
                    "--python",
                    str(python),
                    "--skip-receiver",
                    "--skip-karabiner",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads(
                (prefix / ".codex-gamepad-ownership.json").read_text(encoding="utf-8")
            )
            self.assertEqual(set(manifest["artifacts"]), {"launcher", "uninstaller"})
            self.assertIn("PYTHONDONTWRITEBYTECODE=1", launcher.read_text(encoding="utf-8"))

    def test_install_enforces_supported_python_and_exact_kokoro_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / ".local" / "share" / "codex-gamepad"
            unsupported = home / "unsupported-python"
            unsupported.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            unsupported.chmod(0o755)
            environment = self._environment(home, prefix)
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "install-local.sh"),
                    "--dry-run",
                    "--python",
                    str(unsupported),
                    "--skip-receiver",
                    "--skip-karabiner",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("Python 3.10–3.13", result.stderr)
            self.assertFalse(prefix.exists())

            wrong_kokoro = home / "wrong-kokoro-python"
            wrong_kokoro.write_text(
                "#!/bin/sh\n"
                'if [ "${1:-}" = "-c" ]; then\n'
                '  case "${2:-}" in *kokoro-onnx*) exit 1 ;; *) exit 0 ;; esac\n'
                "fi\n"
                f"exec {shlex.quote(sys.executable)} \"$@\"\n",
                encoding="utf-8",
            )
            wrong_kokoro.chmod(0o755)
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "install-local.sh"),
                    "--python",
                    str(wrong_kokoro),
                    "--skip-receiver",
                    "--skip-karabiner",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("exactly version 0.5.0", result.stderr)
            self.assertFalse(prefix.exists())

    def test_uninstall_refuses_unmarked_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / "unmarked"
            prefix.mkdir()
            sentinel = prefix / "user-file"
            sentinel.write_text("keep", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                env=self._environment(home, prefix),
            )
            self.assertEqual(result.returncode, 1)
            self.assertTrue(sentinel.is_file())

    def test_uninstall_rejects_prefix_outside_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                env=self._environment(home, Path("/tmp/not-codex-gamepad")),
            )
            self.assertEqual(result.returncode, 2)

    def test_install_refuses_nonempty_unowned_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / "innocent"
            prefix.mkdir()
            sentinel = prefix / "KEEP-ME"
            sentinel.write_text("keep", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "install-local.sh"), "--dry-run"],
                check=False,
                capture_output=True,
                env=self._environment(home, prefix),
            )
            self.assertEqual(result.returncode, 2)
            self.assertTrue(sentinel.is_file())
            self.assertFalse((prefix / ".codex-gamepad-install").exists())

    def test_uninstall_rejects_dot_component_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                env=self._environment(home, home / "x" / ".."),
            )
            self.assertEqual(result.returncode, 2)

    def test_uninstall_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            outside = root / "outside"
            home.mkdir()
            outside.mkdir()
            (home / "escape").symlink_to(outside, target_is_directory=True)
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "uninstall-local.sh")],
                check=False,
                capture_output=True,
                env=self._environment(home, home / "escape"),
            )
            self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
