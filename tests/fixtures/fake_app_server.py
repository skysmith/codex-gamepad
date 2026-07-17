#!/usr/bin/env python3
from __future__ import annotations

import json
import sys


THREAD = {
    "id": "019fixture-app-server",
    "turns": [
        {
            "id": "turn-complete",
            "status": "completed",
            "completedAt": 100,
            "items": [
                {"type": "agentMessage", "phase": "commentary", "text": "working"},
                {"type": "tool", "text": "ignored"},
                {
                    "type": "agentMessage",
                    "phase": "final_answer",
                    "text": "Synthetic final answer.",
                },
            ],
        },
        {
            "id": "turn-streaming",
            "status": "inProgress",
            "completedAt": None,
            "items": [
                {
                    "type": "agentMessage",
                    "phase": "commentary",
                    "text": "Do not select the streaming turn.",
                }
            ],
        },
    ],
}


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        print(json.dumps({"id": request_id, "result": {"serverInfo": {"name": "fake"}}}), flush=True)
    elif method == "initialized":
        continue
    elif method == "thread/list":
        if message.get("params", {}).get("useStateDbOnly"):
            print(
                json.dumps(
                    {
                        "id": request_id,
                        "result": {"data": [{"id": "stale-index-thread"}]},
                    }
                ),
                flush=True,
            )
            continue
        print(
            json.dumps(
                {
                    "method": "server/notification",
                    "params": {},
                }
            ),
            flush=True,
        )
        print(
            json.dumps(
                {
                    "id": request_id,
                    "result": {"data": [{"id": THREAD["id"]}], "nextCursor": None},
                }
            ),
            flush=True,
        )
    elif method == "thread/read":
        print(json.dumps({"id": request_id, "result": {"thread": THREAD}}), flush=True)
