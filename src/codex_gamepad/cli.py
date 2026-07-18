from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path
from typing import Sequence

from .appserver import load_last_completed_reply
from .config import load_config
from .macos import CODEX_BUNDLE_ID, frontmost_bundle_id, notify
from .models import CodexGamepadError, CompletedReply
from .rollout import load_rollout_reply
from .runtime import clear_worker_state, launch_worker, stop_worker
from .text import chunk_for_kokoro, clean_for_speech
from .tts import (
    KokoroBackend,
    check_kokoro_readiness,
    check_system_speech_readiness,
    find_kokoro_assets,
    render_to_file,
    speak_streaming,
    speak_system,
    stop_active_player,
)


_TERMINATED_BY_SIGNAL = False


def build_parser(defaults: dict[str, object] | None = None) -> argparse.ArgumentParser:
    defaults = defaults or {}
    parser = argparse.ArgumentParser(
        prog="codex-speak-last",
        description="Speak the last completed Codex Desktop response with a local voice.",
    )
    parser.add_argument("--config", help="Path to a Codex Gamepad JSON config")
    parser.add_argument(
        "--thread", default=defaults.get("thread"), help="Read a specific Codex thread id"
    )
    parser.add_argument(
        "--source-kind",
        default=defaults.get("source_kind", "vscode"),
        help="Codex task source for automatic selection (default: vscode/Desktop)",
    )
    parser.add_argument(
        "--codex-binary", default=defaults.get("codex_binary"), help="Path to the Codex executable"
    )
    parser.add_argument("--codex-home", help="CODEX_HOME for compatibility rollout mode")
    parser.add_argument("--rollout", help="Read a specific rollout JSONL (compatibility mode)")
    parser.add_argument(
        "--compat-rollout-fallback",
        action="store_true",
        default=defaults.get("compat_rollout_fallback", False),
        help="Use private rollout JSONL only if app-server fails",
    )
    parser.add_argument(
        "--speech-backend",
        choices=("apple", "kokoro"),
        default=defaults.get("speech_backend", "apple"),
        help="Speech engine (default: apple)",
    )
    parser.add_argument(
        "--system-voice",
        default=defaults.get("system_voice"),
        help="Apple system voice (default: the macOS selected voice)",
    )
    parser.add_argument(
        "--system-rate",
        type=int,
        default=defaults.get("system_rate", 200),
        help="Apple speech rate in words per minute (default: 200)",
    )
    parser.add_argument(
        "--model", default=defaults.get("model"), help="Path to kokoro-v1.0.onnx"
    )
    parser.add_argument(
        "--voices", default=defaults.get("voices"), help="Path to voices-v1.0.bin"
    )
    parser.add_argument(
        "--voice",
        default=os.environ.get("KOKORO_VOICE", str(defaults.get("voice", "af_heart"))),
        help="Kokoro voice",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=float(
            os.environ.get("KOKORO_SPEED", str(defaults.get("speed", "1.05")))
        ),
        help="Kokoro speech speed (default: 1.05)",
    )
    parser.add_argument(
        "--max-characters",
        type=int,
        default=defaults.get("max_characters", 12_000),
        help="Maximum response characters to speak",
    )
    parser.add_argument("--output", type=Path, help="Render to a WAV instead of playing it")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check selection and chunking without exposing or synthesizing response text",
    )
    parser.add_argument(
        "--check-speech-runtime",
        action="store_true",
        help="Check the configured speech engine without reading or synthesizing a response",
    )
    parser.add_argument(
        "--require-frontmost",
        action="store_true",
        help="Refuse unless Codex is the frontmost app",
    )
    parser.add_argument(
        "--background", action="store_true", help="Run detached for a controller trigger"
    )
    parser.add_argument(
        "--toggle",
        action="store_true",
        help="With --background, a second invocation stops current speech",
    )
    parser.add_argument("--stop", action="store_true", help="Stop current speech and exit")
    parser.add_argument("--worker-token", help=argparse.SUPPRESS)
    return parser


def _load_reply(args: argparse.Namespace) -> CompletedReply:
    if args.rollout:
        return load_rollout_reply(
            rollout=args.rollout, codex_home=args.codex_home, thread_id=args.thread
        )
    try:
        return load_last_completed_reply(
            thread_id=args.thread,
            source_kind=args.source_kind,
            codex_binary=args.codex_binary,
        )
    except CodexGamepadError:
        if not args.compat_rollout_fallback:
            raise
        return load_rollout_reply(codex_home=args.codex_home, thread_id=args.thread)


def _install_signal_handlers() -> None:
    global _TERMINATED_BY_SIGNAL
    _TERMINATED_BY_SIGNAL = False

    def stop(_signum: int, _frame: object) -> None:
        global _TERMINATED_BY_SIGNAL
        _TERMINATED_BY_SIGNAL = True
        stop_active_player()
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def _run(args: argparse.Namespace) -> None:
    if args.check_speech_runtime:
        if args.speech_backend == "kokoro":
            check_kokoro_readiness(args.model, args.voices)
        else:
            check_system_speech_readiness()
        return
    if args.require_frontmost:
        frontmost = frontmost_bundle_id()
        if frontmost != CODEX_BUNDLE_ID:
            raise CodexGamepadError("Codex is not the frontmost app; speech was ignored.")
    if args.speech_backend == "kokoro" and not 0.5 <= args.speed <= 2.0:
        raise CodexGamepadError("Kokoro speed must be between 0.5 and 2.0.")
    if args.speech_backend == "apple" and not 80 <= args.system_rate <= 500:
        raise CodexGamepadError("Apple speech rate must be between 80 and 500.")
    if not 100 <= args.max_characters <= 100_000:
        raise CodexGamepadError("Maximum characters must be between 100 and 100000.")

    reply = _load_reply(args)
    spoken = clean_for_speech(reply.text, max_characters=args.max_characters)
    chunks = chunk_for_kokoro(spoken)
    if not chunks:
        raise CodexGamepadError("The last Codex response contains no speakable text.")

    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "thread_id": reply.thread_id,
                    "source": reply.source,
                    "response_characters": reply.character_count,
                    "spoken_characters": len(spoken),
                    "chunks": len(chunks),
                    "completed_at": reply.completed_at,
                },
                indent=2,
            )
        )
        return

    if args.speech_backend == "apple":
        if args.output:
            raise CodexGamepadError("WAV output requires the optional Kokoro backend.")
        speak_system(chunks, voice=args.system_voice, rate=args.system_rate)
        return

    model_path, voices_path = find_kokoro_assets(args.model, args.voices)
    backend = KokoroBackend(model_path, voices_path)
    if args.output:
        render_to_file(
            backend,
            chunks,
            args.output,
            voice=args.voice,
            speed=args.speed,
        )
    else:
        speak_streaming(
            backend,
            chunks,
            voice=args.voice,
            speed=args.speed,
        )


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(argv if argv is not None else sys.argv[1:])
    # Stop paths must remain available even when a config file has become
    # malformed. In particular, a second controller press must always cancel.
    if "--stop" in arguments:
        stop_worker()
        return
    if "--background" in arguments and "--toggle" in arguments and stop_worker():
        return

    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument("--config")
    preliminary_args, _ = preliminary.parse_known_args(arguments)
    try:
        defaults = load_config(preliminary_args.config)
    except CodexGamepadError as error:
        if "--background" in arguments:
            notify(str(error))
        print(f"codex-speak-last: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    parser = build_parser(defaults)
    args = parser.parse_args(arguments)

    if args.toggle and not args.background:
        parser.error("--toggle requires --background")
    if args.background and not args.worker_token:
        launch_worker(arguments, toggle=args.toggle)
        return

    _install_signal_handlers()
    try:
        _run(args)
    except CodexGamepadError as error:
        if args.worker_token:
            notify(str(error))
        print(f"codex-speak-last: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    finally:
        if args.worker_token and not _TERMINATED_BY_SIGNAL:
            clear_worker_state(args.worker_token)
