from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import CodexGamepadError


ALLOWED_TYPES: dict[str, type[Any] | tuple[type[Any], ...]] = {
    "thread": str,
    "source_kind": str,
    "codex_binary": str,
    "model": str,
    "voices": str,
    "speech_backend": str,
    "system_voice": str,
    "system_rate": int,
    "voice": str,
    "speed": (int, float),
    "max_characters": int,
    "compat_rollout_fallback": bool,
    "bindings": dict,
    "custom_shortcuts": dict,
}

SPEECH_BACKENDS = {"apple", "kokoro"}


def default_config_path() -> Path:
    override = os.environ.get("CODEX_GAMEPAD_CONFIG")
    return (
        Path(override).expanduser()
        if override
        else Path.home() / ".config" / "codex-gamepad" / "config.json"
    )


def load_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    config_path = Path(path).expanduser() if path else default_config_path()
    if not config_path.exists():
        if path:
            raise CodexGamepadError("The requested Codex Gamepad config file was not found.")
        return {}
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CodexGamepadError("Codex Gamepad config is not valid JSON.") from error
    if not isinstance(value, dict):
        raise CodexGamepadError("Codex Gamepad config must be a JSON object.")
    unknown = sorted(set(value) - set(ALLOWED_TYPES))
    if unknown:
        raise CodexGamepadError(f"Unknown Codex Gamepad config key: {unknown[0]}")
    for key, item in value.items():
        expected = ALLOWED_TYPES[key]
        if not isinstance(item, expected) or (
            key in {"speed", "system_rate", "max_characters"} and isinstance(item, bool)
        ):
            raise CodexGamepadError(f"Invalid value for Codex Gamepad config key: {key}")
    if value.get("speech_backend", "apple") not in SPEECH_BACKENDS:
        raise CodexGamepadError("Speech backend must be apple or kokoro.")
    if "system_rate" in value and not 80 <= value["system_rate"] <= 500:
        raise CodexGamepadError("Apple speech rate must be between 80 and 500.")
    for key, label in (
        ("bindings", "Controller bindings"),
        ("custom_shortcuts", "Custom shortcuts"),
    ):
        mapping = value.get(key, {})
        if any(
            not isinstance(name, str) or not isinstance(item, str)
            for name, item in mapping.items()
        ):
            raise CodexGamepadError(f"{label} must map names to strings.")
    return value
