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


class CreateVenvMarkerSafetyTests(unittest.TestCase):
    def _environment(self, home: Path, prefix: Path) -> tuple[dict[str, str], Path]:
        tools = home / "test-tools"
        tools.mkdir()
        uv_log = home / "uv.log"
        uv = tools / "uv"
        uv.write_text(
            f"#!{sys.executable}\n"
            "from pathlib import Path\n"
            "import shlex\n"
            "import sys\n"
            f"log = Path({str(uv_log)!r})\n"
            "with log.open('a', encoding='utf-8') as handle:\n"
            "    handle.write(shlex.join(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:2] == ['venv']:\n"
            "    target = Path(sys.argv[-1])\n"
            "    python = target / 'bin' / 'python'\n"
            "    python.parent.mkdir(parents=True, exist_ok=True)\n"
            "    python.write_text(\n"
            "        '#!/bin/sh\\n'\n"
            "        'if [ \"${1:-}\" = \"-c\" ]; then exit 0; fi\\n'\n"
            f"        'exec {shlex.quote(sys.executable)} \"$@\"\\n',\n"
            "        encoding='utf-8',\n"
            "    )\n"
            "    python.chmod(0o755)\n"
            "elif sys.argv[1:2] != ['pip']:\n"
            "    raise SystemExit(2)\n",
            encoding="utf-8",
        )
        uv.chmod(0o755)
        for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
            blocker = tools / name
            blocker.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            blocker.chmod(0o755)

        environment = os.environ.copy()
        environment.pop("CODEX_GAMEPAD_PYTHON", None)
        environment.update(
            {
                "HOME": str(home),
                "CODEX_GAMEPAD_PREFIX": str(prefix),
                "CODEX_GAMEPAD_BIN_DIR": str(home / ".local" / "bin"),
                "PATH": str(tools) + os.pathsep + os.defpath,
            }
        )
        return environment, uv_log

    def _legacy_launcher(self, home: Path, prefix: Path) -> Path:
        installed_prefix = prefix.resolve()
        python = installed_prefix / "venv" / "bin" / "python"
        launcher = home / ".local" / "bin" / "codex-speak-last"
        launcher.parent.mkdir(parents=True)
        launcher.write_text(
            "#!/bin/sh\n\n"
            f"APP_PATH={shlex.quote(str(installed_prefix))}\n"
            f"PYTHON_PATH={shlex.quote(str(python))}\n"
            'PYTHONPATH="$APP_PATH/src${PYTHONPATH:+:$PYTHONPATH}"\n'
            "PYTHONDONTWRITEBYTECODE=1\n"
            "export PYTHONPATH PYTHONDONTWRITEBYTECODE\n"
            'exec "$PYTHON_PATH" -m codex_gamepad "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        return launcher

    def _run(self, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "install-local.sh"),
                "--create-venv",
                "--skip-receiver",
                "--skip-karabiner",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_fresh_create_venv_does_not_create_legacy_evidence_before_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            prefix = home / ".local" / "share" / "codex-gamepad"
            launcher = self._legacy_launcher(home, prefix)
            original_launcher = launcher.read_bytes()
            environment, uv_log = self._environment(home, prefix)

            result = self._run(environment)

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("Refusing unowned external artifact", result.stderr)
            self.assertEqual(launcher.read_bytes(), original_launcher)
            self.assertFalse(prefix.exists())
            self.assertEqual(len(uv_log.read_text(encoding="utf-8").splitlines()), 2)

            launcher.unlink()
            retry = self._run(environment)

            self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
            self.assertTrue((prefix / "venv" / "bin" / "python").is_file())
            self.assertEqual(
                (prefix / ".codex-gamepad-install").read_text(encoding="utf-8"),
                "codex-gamepad-v1\n",
            )
            self.assertTrue((prefix / ".codex-gamepad-ownership.json").is_file())
            self.assertEqual(len(uv_log.read_text(encoding="utf-8").splitlines()), 4)

    def test_preexisting_marker_still_supports_create_venv_and_idempotent_upgrade(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            prefix = home / ".local" / "share" / "codex-gamepad"
            prefix.mkdir(parents=True)
            marker = prefix / ".codex-gamepad-install"
            marker.write_text("codex-gamepad-v1\n", encoding="utf-8")
            self._legacy_launcher(home, prefix)
            environment, uv_log = self._environment(home, prefix)

            first = self._run(environment)
            first_uv_calls = uv_log.read_text(encoding="utf-8")
            second = self._run(environment)

            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(
                marker.read_text(encoding="utf-8"), "codex-gamepad-v1\n"
            )
            self.assertEqual(uv_log.read_text(encoding="utf-8"), first_uv_calls)
            self.assertEqual(len(first_uv_calls.splitlines()), 2)
            manifest = json.loads(
                (prefix / ".codex-gamepad-ownership.json").read_text(encoding="utf-8")
            )
            self.assertEqual(set(manifest["artifacts"]), {"launcher", "uninstaller"})


if __name__ == "__main__":
    unittest.main()
