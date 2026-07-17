#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
import shlex
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("template", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=("raw", "shell", "xml"), default="raw")
    parser.add_argument("replacements", nargs="*")
    args = parser.parse_intermixed_args()

    values: dict[str, str] = {}
    for replacement in args.replacements:
        key, separator, value = replacement.partition("=")
        if not separator:
            raise SystemExit(f"invalid replacement: {replacement}")
        values[key] = value

    text = args.template.read_text(encoding="utf-8")
    for key, value in values.items():
        if args.mode == "shell":
            value = shlex.quote(value)
        elif args.mode == "xml":
            value = html.escape(value, quote=True)
        text = text.replace(f"__{key}__", value)
    unresolved = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]*__", text)))
    if unresolved:
        raise SystemExit(f"unresolved template value: {unresolved[0]}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
