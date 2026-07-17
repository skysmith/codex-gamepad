from __future__ import annotations

import os
import subprocess
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from typing import Any, Iterable

from .models import CodexGamepadError


DEFAULT_MODEL_NAME = "kokoro-v1.0.onnx"
DEFAULT_VOICES_NAME = "voices-v1.0.bin"
_ACTIVE_PLAYER: subprocess.Popen[bytes] | None = None


def find_kokoro_assets(
    model: str | os.PathLike[str] | None = None,
    voices: str | os.PathLike[str] | None = None,
) -> tuple[Path, Path]:
    explicit_model = model or os.environ.get("KOKORO_MODEL")
    explicit_voices = voices or os.environ.get("KOKORO_VOICES")
    if explicit_model or explicit_voices:
        if not explicit_model or not explicit_voices:
            raise CodexGamepadError("Both the Kokoro model and voices paths are required.")
        pair = (Path(explicit_model).expanduser(), Path(explicit_voices).expanduser())
        if pair[0].is_file() and pair[1].is_file():
            return pair[0].resolve(), pair[1].resolve()
        raise CodexGamepadError("The configured Kokoro model files were not found.")

    roots = [
        Path.home() / ".local" / "share" / "codex-gamepad" / "models",
        Path.home() / "Library" / "Application Support" / "Codex Gamepad" / "models",
    ]
    for root in roots:
        pair = (root / DEFAULT_MODEL_NAME, root / DEFAULT_VOICES_NAME)
        if pair[0].is_file() and pair[1].is_file():
            return pair[0].resolve(), pair[1].resolve()
    raise CodexGamepadError(
        "Kokoro model files were not found. Run the installer or set KOKORO_MODEL and KOKORO_VOICES."
    )


def check_kokoro_readiness(
    model: str | os.PathLike[str] | None = None,
    voices: str | os.PathLike[str] | None = None,
) -> tuple[Path, Path]:
    """Validate local speech assets and imports without loading or synthesizing text."""
    assets = find_kokoro_assets(model, voices)
    try:
        kokoro_module = import_module("kokoro_onnx")
        soundfile_module = import_module("soundfile")
    except (ImportError, OSError) as error:
        raise CodexGamepadError(
            "Kokoro Python dependencies could not be loaded."
        ) from error
    if not callable(getattr(kokoro_module, "Kokoro", None)) or not callable(
        getattr(soundfile_module, "write", None)
    ):
        raise CodexGamepadError("The installed Kokoro Python packages are incompatible.")
    return assets


class KokoroBackend:
    def __init__(self, model_path: Path, voices_path: Path) -> None:
        try:
            import soundfile as soundfile
            from kokoro_onnx import Kokoro
        except ImportError as error:
            raise CodexGamepadError(
                "Kokoro is not installed in this Python environment."
            ) from error
        try:
            self._kokoro = Kokoro(str(model_path), str(voices_path))
        except Exception as error:
            raise CodexGamepadError("Kokoro could not load its local model files.") from error
        self._soundfile = soundfile

    def synthesize(
        self, text: str, *, voice: str, speed: float, language: str
    ) -> tuple[Any, int]:
        try:
            return self._kokoro.create(
                text, voice=voice, speed=speed, lang=language
            )
        except Exception as error:
            raise CodexGamepadError("Kokoro could not synthesize this response.") from error

    def write(self, path: Path, samples: Any, sample_rate: int) -> None:
        self._soundfile.write(str(path), samples, sample_rate)

    def concatenate(self, rendered: list[tuple[Any, int]]) -> tuple[Any, int]:
        if not rendered:
            raise CodexGamepadError("Kokoro produced no audio.")
        try:
            import numpy as np
        except ImportError as error:
            raise CodexGamepadError("NumPy is required to assemble Kokoro audio.") from error
        sample_rate = rendered[0][1]
        if any(rate != sample_rate for _, rate in rendered):
            raise CodexGamepadError("Kokoro returned inconsistent audio sample rates.")
        silence = np.zeros(int(sample_rate * 0.12), dtype=np.float32)
        pieces: list[Any] = []
        for index, (samples, _) in enumerate(rendered):
            if index:
                pieces.append(silence)
            pieces.append(samples)
        return np.concatenate(pieces), sample_rate


def _secure_wav_path() -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix="codex-gamepad-", suffix=".wav")
    os.close(descriptor)
    os.chmod(raw_path, 0o600)
    return Path(raw_path)


def stop_active_player() -> None:
    global _ACTIVE_PLAYER
    player = _ACTIVE_PLAYER
    if player is not None and player.poll() is None:
        player.terminate()


def _play(path: Path, player_path: str = "/usr/bin/afplay") -> None:
    global _ACTIVE_PLAYER
    if not Path(player_path).is_file():
        raise CodexGamepadError("macOS afplay was not found.")
    try:
        _ACTIVE_PLAYER = subprocess.Popen(
            [player_path, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return_code = _ACTIVE_PLAYER.wait()
    except OSError as error:
        raise CodexGamepadError("The response audio could not be played.") from error
    finally:
        _ACTIVE_PLAYER = None
    if return_code not in (0, -15):
        raise CodexGamepadError("The response audio player exited unexpectedly.")


def speak_streaming(
    backend: KokoroBackend,
    chunks: Iterable[str],
    *,
    voice: str,
    speed: float,
    language: str = "en-us",
) -> None:
    chunk_list = list(chunks)
    if not chunk_list:
        raise CodexGamepadError("The Codex response contains no speakable text.")

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="kokoro") as executor:
        future: Future[tuple[Any, int]] = executor.submit(
            backend.synthesize,
            chunk_list[0],
            voice=voice,
            speed=speed,
            language=language,
        )
        for index in range(len(chunk_list)):
            samples, sample_rate = future.result()
            if index + 1 < len(chunk_list):
                future = executor.submit(
                    backend.synthesize,
                    chunk_list[index + 1],
                    voice=voice,
                    speed=speed,
                    language=language,
                )
            wav_path = _secure_wav_path()
            try:
                backend.write(wav_path, samples, sample_rate)
                _play(wav_path)
            finally:
                wav_path.unlink(missing_ok=True)


def render_to_file(
    backend: KokoroBackend,
    chunks: Iterable[str],
    output: Path,
    *,
    voice: str,
    speed: float,
    language: str = "en-us",
) -> None:
    rendered = [
        backend.synthesize(chunk, voice=voice, speed=speed, language=language)
        for chunk in chunks
    ]
    samples, sample_rate = backend.concatenate(rendered)
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(output, flags, 0o600)
        os.close(descriptor)
        output.chmod(0o600)
    except OSError as error:
        raise CodexGamepadError("The private response audio file could not be created.") from error
    backend.write(output, samples, sample_rate)
