#!/usr/bin/env python3
"""Emit a stable, privacy-safe subset of Karabiner connected-device JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def sanitize_devices(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("device data is not a list")

    sanitized: list[dict[str, Any]] = []
    for device in value:
        if not isinstance(device, dict):
            continue
        identifiers = device.get("device_identifiers")
        if not isinstance(identifiers, dict):
            identifiers = {}
        sanitized.append(
            {
                "product": _text(device.get("product")),
                "manufacturer": _text(device.get("manufacturer")),
                "transport": _text(device.get("transport")),
                "vendor_id": _integer(identifiers.get("vendor_id")),
                "product_id": _integer(identifiers.get("product_id")),
                "is_game_pad": _boolean(identifiers.get("is_game_pad")),
            }
        )
    return sorted(
        sanitized,
        key=lambda device: json.dumps(
            device, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ),
    )


def _looks_like_controller(device: dict[str, Any]) -> bool:
    if device["is_game_pad"] is True:
        return True
    label = " ".join(
        value
        for value in (device["manufacturer"], device["product"])
        if isinstance(value, str)
    )
    return re.search(r"8bitdo|game[ _-]*pad|controller", label, re.IGNORECASE) is not None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove private fields from Karabiner connected-device JSON."
    )
    parser.add_argument(
        "--controllers-only",
        action="store_true",
        help="omit devices that are neither gamepads nor controller-like",
    )
    arguments = parser.parse_args()
    try:
        devices = sanitize_devices(json.load(sys.stdin))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        print("Karabiner connected-device data could not be safely parsed.", file=sys.stderr)
        return 1
    if arguments.controllers_only:
        devices = [device for device in devices if _looks_like_controller(device)]
    json.dump(devices, sys.stdout, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
