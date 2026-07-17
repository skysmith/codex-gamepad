from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence


@dataclass(frozen=True)
class RuntimePaths:
    directory: Path
    state: Path
    lock: Path
    log: Path


def runtime_paths() -> RuntimePaths:
    override = os.environ.get("CODEX_GAMEPAD_STATE_DIR")
    directory = (
        Path(override).expanduser()
        if override
        else Path.home() / "Library" / "Application Support" / "Codex Gamepad"
    )
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    return RuntimePaths(
        directory=directory,
        state=directory / "speaker.json",
        lock=directory / "speaker.lock",
        log=directory / "speaker.log",
    )


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        with os.fdopen(descriptor, "r+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
    finally:
        # fdopen owns and closes the descriptor.
        pass


def _read_state(path: Path) -> tuple[int, str] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    pid = value.get("pid")
    token = value.get("token")
    if not isinstance(pid, int) or pid <= 1 or not isinstance(token, str):
        return None
    return pid, token


def _write_state(path: Path, pid: int, token: str) -> None:
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"pid": pid, "token": token}, handle)
            handle.write("\n")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(path)


def _is_our_worker(pid: int, token: str) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        result = subprocess.run(
            ["/bin/ps", "-ww", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=0.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "codex_gamepad" in result.stdout and token in result.stdout


def _terminate_worker(pid: int, token: str, *, grace_seconds: float = 0.5) -> None:
    if not _is_our_worker(pid, token):
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not _is_our_worker(pid, token):
            return
        time.sleep(0.05)
    if _is_our_worker(pid, token):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline and _is_our_worker(pid, token):
        time.sleep(0.05)


def stop_worker() -> bool:
    paths = runtime_paths()
    with _state_lock(paths.lock):
        state = _read_state(paths.state)
        if state is None:
            paths.state.unlink(missing_ok=True)
            return False
        pid, token = state
        if not _is_our_worker(pid, token):
            paths.state.unlink(missing_ok=True)
            return False
        _terminate_worker(pid, token)
        paths.state.unlink(missing_ok=True)
        return True


def launch_worker(arguments: Sequence[str], *, toggle: bool) -> str:
    paths = runtime_paths()
    with _state_lock(paths.lock):
        existing = _read_state(paths.state)
        if existing and _is_our_worker(*existing):
            if toggle:
                _terminate_worker(*existing)
                paths.state.unlink(missing_ok=True)
                return "stopped"
            return "already-running"
        paths.state.unlink(missing_ok=True)

        token = uuid.uuid4().hex
        child_arguments = [
            argument for argument in arguments if argument not in {"--background", "--toggle"}
        ]
        command = [
            sys.executable,
            "-m",
            "codex_gamepad",
            *child_arguments,
            "--worker-token",
            token,
        ]
        log_descriptor = os.open(paths.log, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_descriptor,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            os.close(log_descriptor)
        _write_state(paths.state, process.pid, token)
        return "started"


def clear_worker_state(token: str) -> None:
    paths = runtime_paths()
    with _state_lock(paths.lock):
        state = _read_state(paths.state)
        if state and state[1] == token:
            paths.state.unlink(missing_ok=True)
