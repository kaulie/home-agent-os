"""CLI: WAV or continuous mic → STT text → optional POST /api/v1/intent."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from mac_voice.audio.types import AudioUtterance
from mac_voice.config import load_config
from mac_voice.pipeline import handle_transcript
from mac_voice.stt.factory import create_stt

log = logging.getLogger("mac_voice.transcribe")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _run_file(args: argparse.Namespace) -> int:
    cfg = load_config()
    utterance = AudioUtterance.from_wav_path(args.file)
    stt = create_stt(cfg)
    text = await stt.transcribe(utterance)
    handle_transcript(cfg, text, post=args.post_intent)
    return 0 if (text or "").strip() or not args.post_intent else 1


async def _run_live(args: argparse.Namespace) -> int:
    """Continuous capture thread + async STT (capture never blocks on cloud ASR)."""
    from mac_voice.listen import run_live

    cfg = load_config()
    stt = create_stt(cfg)
    device = args.device if args.device is not None else cfg.input_device
    try:
        await run_live(cfg, stt, device=device, post_intent=args.post_intent)
    except KeyboardInterrupt:
        log.info("stopped by user")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mac voice.stream (kind=input): WAV or mic → text → optional Brain intent"
    )
    parser.add_argument("--file", help="Path to WAV (offline one-shot)")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Continuous USB mic (sounddevice), silence-gated utterances → STT",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="sounddevice device index or name (default MAC_VOICE_INPUT_DEVICE / 0)",
    )
    parser.add_argument(
        "--post-intent",
        action="store_true",
        help="After STT, POST /api/v1/intent as hosting Mac Runtime (requires edge_id)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.device is not None:
        raw = str(args.device).strip()
        try:
            args.device = int(raw)
        except ValueError:
            args.device = raw

    if args.live and args.file:
        parser.error("use either --live or --file, not both")
    if not args.live and not args.file:
        parser.error("require --file PATH or --live")

    try:
        if args.live:
            return asyncio.run(_run_live(args))
        return asyncio.run(_run_file(args))
    except Exception as e:
        log.error("%s", e)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
