from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

from .models import CodexGamepadError, CompletedReply


def _records(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # The last line can be incomplete while Codex is writing it.
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError as error:
        raise CodexGamepadError("Could not read the Codex compatibility transcript.") from error


def _metadata(path: Path) -> dict[str, Any] | None:
    for record in _records(path):
        if record.get("type") == "session_meta" and isinstance(record.get("payload"), dict):
            return record["payload"]
        break
    return None


def _is_root_desktop_session(metadata: dict[str, Any]) -> bool:
    source = metadata.get("source")
    return metadata.get("agent_path") in (None, "") and source == "vscode"


def find_rollout(
    codex_home: Path,
    *,
    thread_id: str | None = None,
) -> Path:
    sessions = codex_home.expanduser() / "sessions"
    if not sessions.is_dir():
        raise CodexGamepadError("Codex sessions directory was not found.")
    candidates = list(sessions.rglob("rollout-*.jsonl"))
    candidates.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
    for candidate in candidates:
        metadata = _metadata(candidate)
        if not metadata or not _is_root_desktop_session(metadata):
            continue
        if thread_id and metadata.get("id") != thread_id:
            continue
        return candidate
    raise CodexGamepadError("No compatible Codex Desktop transcript was found.")


def extract_rollout_reply(path: Path) -> CompletedReply:
    metadata = _metadata(path)
    if not metadata:
        raise CodexGamepadError("Codex compatibility transcript has no metadata.")
    final: tuple[str, Any] | None = None
    legacy: tuple[str, Any] | None = None
    for record in _records(path):
        if record.get("type") != "response_item":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "message" or payload.get("role") != "assistant":
            continue
        content = payload.get("content")
        if not isinstance(content, list):
            continue
        text = "\n".join(
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "output_text"
            and isinstance(part.get("text"), str)
        ).strip()
        if not text:
            continue
        phase = payload.get("phase")
        candidate = (text, record.get("timestamp"))
        if phase == "final_answer":
            final = candidate
        elif phase is None:
            legacy = candidate

    selected = final or legacy
    if selected is None:
        raise CodexGamepadError("Codex compatibility transcript has no completed response.")
    thread_id = metadata.get("id")
    if not isinstance(thread_id, str):
        thread_id = "unknown"
    return CompletedReply(
        text=selected[0],
        thread_id=thread_id,
        source="rollout-compatibility",
        completed_at=selected[1],
        rollout_path=path,
    )


def load_rollout_reply(
    *,
    rollout: str | os.PathLike[str] | None = None,
    codex_home: str | os.PathLike[str] | None = None,
    thread_id: str | None = None,
) -> CompletedReply:
    path = (
        Path(rollout).expanduser()
        if rollout
        else find_rollout(
            Path(codex_home).expanduser()
            if codex_home
            else Path.home() / ".codex",
            thread_id=thread_id,
        )
    )
    return extract_rollout_reply(path)
