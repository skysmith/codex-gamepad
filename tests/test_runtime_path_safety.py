from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class RuntimePathSafetyTests(unittest.TestCase):
    def _environment(self, home: Path) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(home),
                "CODEX_GAMEPAD_PREFIX": str(
                    home / ".local" / "share" / "codex-gamepad"
                ),
                "CODEX_GAMEPAD_BIN_DIR": str(home / ".local" / "bin"),
            }
        )
        return environment

    def test_install_and_uninstall_reject_runtime_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            outside = root / "outside"
            (home / "Library").mkdir(parents=True)
            outside.mkdir()
            sentinel = outside / "keep-me"
            sentinel.write_text("keep\n", encoding="utf-8")
            (home / "Library" / "Application Support").symlink_to(
                outside,
                target_is_directory=True,
            )
            environment = self._environment(home)

            for script, arguments in (
                ("install-local.sh", ["--dry-run"]),
                ("uninstall-local.sh", []),
            ):
                with self.subTest(script=script):
                    result = subprocess.run(
                        ["bash", str(ROOT / "scripts" / script), *arguments],
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                    )
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("Unsafe Codex Gamepad runtime directory", result.stderr)
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")


if __name__ == "__main__":
    unittest.main()
