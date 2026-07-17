from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from codex_gamepad.cli import main


class CLITests(unittest.TestCase):
    def test_speech_runtime_check_does_not_load_a_response(self) -> None:
        with (
            mock.patch("codex_gamepad.cli.check_kokoro_readiness") as readiness,
            mock.patch("codex_gamepad.cli._load_reply") as load_reply,
        ):
            main(["--check-speech-runtime"])
        readiness.assert_called_once_with(None, None)
        load_reply.assert_not_called()

    def test_speech_runtime_check_uses_configured_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.onnx"
            voices = root / "voices.bin"
            config = root / "config.json"
            config.write_text(
                json.dumps({"model": str(model), "voices": str(voices)}),
                encoding="utf-8",
            )
            with mock.patch(
                "codex_gamepad.cli.check_kokoro_readiness"
            ) as readiness:
                main(["--config", str(config), "--check-speech-runtime"])
            readiness.assert_called_once_with(str(model), str(voices))

    def test_dry_run_never_prints_response_text(self) -> None:
        rollout = Path(__file__).parent / "fixtures" / "root-rollout.jsonl"
        stdout = io.StringIO()
        with mock.patch.dict(
            "os.environ", {"CODEX_GAMEPAD_CONFIG": "/tmp/codex-gamepad-test-missing.json"}
        ), redirect_stdout(stdout):
            main(["--rollout", str(rollout), "--dry-run"])
        output = stdout.getvalue()
        data = json.loads(output)
        self.assertTrue(data["ok"])
        self.assertNotIn("synthetic result", output)
        self.assertNotIn("private code", output)

    def test_toggle_can_stop_even_with_broken_config(self) -> None:
        with mock.patch("codex_gamepad.cli.stop_worker", return_value=True) as stop:
            main(
                [
                    "--background",
                    "--toggle",
                    "--config",
                    "/definitely/missing/codex-gamepad-config.json",
                ]
            )
        stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
