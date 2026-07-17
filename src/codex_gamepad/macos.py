from __future__ import annotations

import subprocess


CODEX_BUNDLE_ID = "com.openai.codex"


def frontmost_bundle_id() -> str | None:
    script = (
        'tell application "System Events" to get bundle identifier of '
        "first application process whose frontmost is true"
    )
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def notify(message: str) -> None:
    safe = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    script = f'display notification "{safe}" with title "Codex Gamepad"'
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
