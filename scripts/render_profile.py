#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--speaker", required=True)
    args = parser.parse_args()

    profile: dict[str, Any] = json.loads(args.input.read_text(encoding="utf-8"))
    shell_command = (
        f"{shlex.quote(args.speaker)} --background --toggle --require-frontmost"
    )
    event_keys = ("to", "to_if_alone", "to_if_held_down", "to_after_key_up")
    for rule in profile.get("rules", []):
        for manipulator in rule.get("manipulators", []):
            for event_key in event_keys:
                for event in manipulator.get(event_key, []):
                    user_command = event.get("send_user_command")
                    if isinstance(user_command, dict):
                        user_command["endpoint"] = args.endpoint
                    if "shell_command" in event:
                        event["shell_command"] = shell_command

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
