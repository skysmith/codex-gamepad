from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class CodexGamepadError(RuntimeError):
    """A user-actionable error that is safe to display or log."""


@dataclass(frozen=True)
class CompletedReply:
    text: str
    thread_id: str
    source: str
    completed_at: int | float | str | None = None
    rollout_path: Path | None = None

    @property
    def character_count(self) -> int:
        return len(self.text)
