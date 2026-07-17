from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .models import CodexGamepadError, CompletedReply


SYSTEM_APPLICATIONS_DIRECTORY = Path("/Applications")
CODEX_APP_BUNDLES = ("ChatGPT.app", "Codex.app")
CODEX_BINARY_IN_BUNDLE = Path("Contents/Resources/codex")


def _bundled_codex_candidates() -> list[Path]:
    application_directories = (
        SYSTEM_APPLICATIONS_DIRECTORY,
        Path.home() / "Applications",
    )
    return [
        directory / bundle / CODEX_BINARY_IN_BUNDLE
        for directory in application_directories
        for bundle in CODEX_APP_BUNDLES
    ]


def find_codex_binary(explicit: str | os.PathLike[str] | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("CODEX_BINARY"):
        candidates.append(Path(os.environ["CODEX_BINARY"]).expanduser())
    candidates.extend(_bundled_codex_candidates())
    on_path = shutil.which("codex")
    if on_path:
        candidates.append(Path(on_path))

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise CodexGamepadError(
        "Codex executable not found. Set CODEX_BINARY to the Codex CLI path."
    )


class CodexAppServer:
    """Small newline-delimited JSON client for Codex's supported app-server API."""

    def __init__(
        self,
        command: Sequence[str] | None = None,
        *,
        codex_binary: str | os.PathLike[str] | None = None,
        timeout: float = 2.0,
    ) -> None:
        if command is None:
            command = [str(find_codex_binary(codex_binary)), "app-server"]
        self.command = [str(part) for part in command]
        self.timeout = timeout
        self._process: subprocess.Popen[bytes] | None = None
        self._next_id = 1
        self._read_buffer = b""
        self._pending_messages: list[dict[str, Any]] = []

    def __enter__(self) -> "CodexAppServer":
        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except OSError as error:
            raise CodexGamepadError("Could not start the Codex app server.") from error

        try:
            self._request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex_gamepad",
                        "title": "Codex Gamepad",
                        "version": __version__,
                    }
                },
            )
            self._notify("initialized", {})
        except Exception:
            self._close_process()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._close_process()

    def _close_process(self) -> None:
        process = self._process
        if process is None:
            return
        self._process = None
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.5)
        if process.stdout:
            process.stdout.close()

    def _send(self, message: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise CodexGamepadError("Codex app server is not running.")
        try:
            encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
            self._process.stdin.write(encoded)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise CodexGamepadError("Codex app server closed unexpectedly.") from error

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({"method": method, "id": request_id, "params": params})
        response = self._wait_for_response(request_id)
        if "error" in response:
            raise CodexGamepadError(f"Codex app server rejected {method}.")
        result = response.get("result")
        if not isinstance(result, dict):
            raise CodexGamepadError(f"Codex app server returned an invalid {method} response.")
        return result

    def _wait_for_response(self, request_id: int) -> dict[str, Any]:
        if self._process is None or self._process.stdout is None:
            raise CodexGamepadError("Codex app server is not running.")

        for index, message in enumerate(self._pending_messages):
            if message.get("id") == request_id:
                return self._pending_messages.pop(index)

        selector = selectors.DefaultSelector()
        descriptor = self._process.stdout.fileno()
        selector.register(descriptor, selectors.EVENT_READ)
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                while b"\n" in self._read_buffer:
                    raw_line, self._read_buffer = self._read_buffer.split(b"\n", 1)
                    try:
                        message = json.loads(raw_line)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(message, dict):
                        continue
                    if message.get("id") == request_id:
                        return message
                    self._pending_messages.append(message)

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexGamepadError("Codex app server timed out.")
                if not selector.select(remaining):
                    raise CodexGamepadError("Codex app server timed out.")
                chunk = os.read(descriptor, 65_536)
                if not chunk:
                    raise CodexGamepadError("Codex app server closed unexpectedly.")
                self._read_buffer += chunk
        finally:
            selector.close()

    def most_recent_thread_id(self, source_kind: str = "vscode") -> str:
        base_params: dict[str, Any] = {
            "sourceKinds": [source_kind],
            "archived": False,
            "limit": 1,
            "sortKey": "recency_at",
            "sortDirection": "desc",
        }
        # Do the full supported lookup. The state-only index is faster, but it
        # can lag an active task and therefore is not safe for read-aloud.
        result = self._request("thread/list", base_params)
        data = result.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise CodexGamepadError(f"No recent Codex {source_kind} task was found.")
        thread_id = data[0].get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise CodexGamepadError("Codex returned a task without an id.")
        return thread_id

    def read_thread(self, thread_id: str) -> dict[str, Any]:
        result = self._request(
            "thread/read", {"threadId": thread_id, "includeTurns": True}
        )
        thread = result.get("thread")
        if not isinstance(thread, dict):
            raise CodexGamepadError("Codex returned an invalid task history.")
        return thread


def _completion_sort_key(indexed_turn: tuple[int, dict[str, Any]]) -> tuple[int, float, int]:
    index, turn = indexed_turn
    completed_at = turn.get("completedAt")
    if isinstance(completed_at, (int, float)):
        return (1, float(completed_at), index)
    return (0, 0.0, index)


def extract_last_completed_reply(thread: dict[str, Any]) -> CompletedReply:
    thread_id = thread.get("id")
    if not isinstance(thread_id, str) or not thread_id:
        raise CodexGamepadError("Codex task history has no task id.")
    turns = thread.get("turns")
    if not isinstance(turns, list):
        raise CodexGamepadError("Codex task history has no turns.")

    completed: list[tuple[int, dict[str, Any]]] = [
        (index, turn)
        for index, turn in enumerate(turns)
        if isinstance(turn, dict) and turn.get("status") == "completed"
    ]
    if not completed:
        raise CodexGamepadError("This Codex task has no completed response yet.")

    for _, turn in sorted(completed, key=_completion_sort_key, reverse=True):
        items = turn.get("items")
        if not isinstance(items, list):
            continue
        final_messages = [
            item
            for item in items
            if isinstance(item, dict)
            and item.get("type") == "agentMessage"
            and item.get("phase") == "final_answer"
            and isinstance(item.get("text"), str)
            and item["text"].strip()
        ]
        if final_messages:
            selected = final_messages[-1]
        else:
            legacy_messages = [
                item
                for item in items
                if isinstance(item, dict)
                and item.get("type") == "agentMessage"
                and item.get("phase") in (None, "final_answer")
                and isinstance(item.get("text"), str)
                and item["text"].strip()
            ]
            if legacy_messages:
                selected = legacy_messages[-1]
            else:
                continue

        return CompletedReply(
            text=selected["text"].strip(),
            thread_id=thread_id,
            source="app-server",
            completed_at=turn.get("completedAt"),
        )

    raise CodexGamepadError("The last completed Codex turn has no speakable response.")


def load_last_completed_reply(
    *,
    thread_id: str | None = None,
    source_kind: str = "vscode",
    codex_binary: str | os.PathLike[str] | None = None,
    command: Sequence[str] | None = None,
    timeout: float = 2.0,
) -> CompletedReply:
    with CodexAppServer(
        command=command, codex_binary=codex_binary, timeout=timeout
    ) as server:
        selected_thread = thread_id or server.most_recent_thread_id(source_kind)
        thread = server.read_thread(selected_thread)
    return extract_last_completed_reply(thread)
