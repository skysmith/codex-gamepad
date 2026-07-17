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
    "voice": str,
    "speed": (int, float),
    "max_characters": int,
    "compat_rollout_fallback": bool,
}


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
            key in {"speed", "max_characters"} and isinstance(item, bool)
        ):
            raise CodexGamepadError(f"Invalid value for Codex Gamepad config key: {key}")
    return value
