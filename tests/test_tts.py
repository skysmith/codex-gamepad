from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from codex_gamepad import tts
from codex_gamepad.models import CodexGamepadError


class FakeBackend:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text: str, **_: object) -> tuple[list[float], int]:
        self.texts.append(text)
        return [0.0, 0.1, 0.0], 24_000

    def write(self, path: Path, samples: object, sample_rate: int) -> None:
        self.assertion = (samples, sample_rate)
        path.write_bytes(b"RIFFsynthetic")

    def concatenate(self, rendered: list[tuple[object, int]]) -> tuple[object, int]:
        return rendered[0]


class TTSTests(unittest.TestCase):
    def test_readiness_checks_assets_and_python_apis_without_loading_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / tts.DEFAULT_MODEL_NAME
            voices = root / tts.DEFAULT_VOICES_NAME
            model.touch()
            voices.touch()
            modules = {
                "kokoro_onnx": SimpleNamespace(Kokoro=object),
                "soundfile": SimpleNamespace(write=lambda *_: None),
            }
            with mock.patch.object(
                tts, "import_module", side_effect=lambda name: modules[name]
            ) as import_module:
                self.assertEqual(
                    tts.check_kokoro_readiness(model, voices),
                    (model.resolve(), voices.resolve()),
                )
            self.assertEqual(
                import_module.call_args_list,
                [mock.call("kokoro_onnx"), mock.call("soundfile")],
            )

    def test_readiness_rejects_missing_python_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / tts.DEFAULT_MODEL_NAME
            voices = root / tts.DEFAULT_VOICES_NAME
            model.touch()
            voices.touch()
            with mock.patch.object(
                tts, "import_module", side_effect=ImportError("missing")
            ):
                with self.assertRaisesRegex(
                    CodexGamepadError, "dependencies could not be loaded"
                ):
                    tts.check_kokoro_readiness(model, voices)

    def test_finds_assets_in_public_user_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            model_directory = (
                home / ".local" / "share" / "codex-gamepad" / "models"
            )
            model_directory.mkdir(parents=True)
            model = model_directory / tts.DEFAULT_MODEL_NAME
            voices = model_directory / tts.DEFAULT_VOICES_NAME
            model.touch()
            voices.touch()

            with (
                mock.patch.object(tts.Path, "home", return_value=home),
                mock.patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(
                    tts.find_kokoro_assets(), (model.resolve(), voices.resolve())
                )

    def test_does_not_use_private_nodex_asset_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            private_directory = home / ".nodex" / "kokoro"
            private_directory.mkdir(parents=True)
            (private_directory / tts.DEFAULT_MODEL_NAME).touch()
            (private_directory / tts.DEFAULT_VOICES_NAME).touch()

            with (
                mock.patch.object(tts.Path, "home", return_value=home),
                mock.patch.dict(os.environ, {}, clear=True),
            ):
                with self.assertRaises(CodexGamepadError):
                    tts.find_kokoro_assets()

    def test_streaming_prefetches_and_deletes_temporary_wavs(self) -> None:
        backend = FakeBackend()
        played: list[Path] = []

        def fake_play(path: Path) -> None:
            self.assertTrue(path.exists())
            played.append(path)

        with mock.patch("codex_gamepad.tts._play", side_effect=fake_play):
            tts.speak_streaming(
                backend, ["First synthetic sentence.", "Second synthetic sentence."],
                voice="af_heart", speed=1.05
            )
        self.assertEqual(backend.texts, ["First synthetic sentence.", "Second synthetic sentence."])
        self.assertEqual(len(played), 2)
        self.assertTrue(all(not path.exists() for path in played))

    def test_explicit_output_is_private(self) -> None:
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "response.wav"
            tts.render_to_file(
                backend,
                ["Synthetic response."],
                output,
                voice="af_heart",
                speed=1.05,
            )
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
