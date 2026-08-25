"""Detect lamp wake reply 在呢 / 我在呢 from the USB-mic pause window.

Playback RMS is not wake success. Lamp-on SUCCESS is still vision.ask.
This field is independent. STT reuse is mac_voice (no Runtime change).
If STT is unavailable, heard stays None and the gap is recorded.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from mac_edge.plugins.voice_test.loopback import LoopbackError, record_seconds
from mac_edge.plugins.voice_test.timeline import iso_now

log = logging.getLogger("mac_edge.voice_test.wake_reply")

# Strip spaces / punctuation so 「我在呢。」 still matches.
_ZAI_NE = re.compile(r"我?在呢")


def parse_wake_reply(text: str) -> bool:
    compact = re.sub(r"[\s，。！？,.!?\"'“”]", "", text or "")
    return bool(_ZAI_NE.search(compact))


def transcribe_wav(path: Path) -> tuple[str, str]:
    """Return (text, error). error non-empty means STT gap, not lamp FAIL."""
    try:
        from mac_voice.audio.types import AudioUtterance
        from mac_voice.config import load_config
        from mac_voice.stt.factory import create_stt
    except ImportError as e:
        return "", f"stt_unavailable:{e}"
    try:
        cfg = load_config()
        stt = create_stt(cfg)
        utt = AudioUtterance.from_wav_path(path)
        text = asyncio.run(stt.transcribe(utt))
    except Exception as e:  # noqa: BLE001 — trial continues; this is a side channel
        log.warning("wake-reply STT failed: %s", e)
        return "", f"stt_error:{e}"
    return (text or "").strip(), ""


def record_wake_reply_window(dest: Path, duration_ms: int) -> dict[str, Any]:
    """Record the wake→command gap only. Does not STT (that would stretch the gap)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {
        "heard": None,
        "text": "",
        "wav": "",
        "source": "",
        "error": "",
        "listen_started_at": iso_now(),
        "listen_ended_at": "",
        "stt_ended_at": "",
    }
    try:
        wav = record_seconds(max(duration_ms, 0) / 1000.0, wav_dest=dest)
    except LoopbackError as e:
        out["source"] = "mic_error"
        out["error"] = str(e)
        out["listen_ended_at"] = iso_now()
        return out
    out["wav"] = str(wav)
    out["listen_ended_at"] = iso_now()
    out["source"] = "recorded"
    return out


def finish_wake_reply_stt(out: dict[str, Any]) -> dict[str, Any]:
    """STT a previously recorded pause window. Call after the command has started."""
    blob = dict(out)
    wav = Path(str(blob.get("wav") or ""))
    if blob.get("source") != "recorded" or not wav.is_file():
        return blob
    text, err = transcribe_wav(wav)
    blob["stt_ended_at"] = iso_now()
    blob["text"] = text
    if err:
        blob["source"] = "stt_unavailable" if err.startswith("stt_unavailable") else "stt_error"
        blob["error"] = err
        blob["heard"] = None
        return blob
    blob["source"] = "stt"
    blob["heard"] = parse_wake_reply(text)
    return blob


def transcribe_pickup_channels(
    channels: list[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    """STT each pickup WAV after playback. Does not change lamp SUCCESS.

    channels: (channel_id, wav_path, intended_or_role)
    """
    out: list[dict[str, Any]] = []
    for channel, wav, role in channels:
        item: dict[str, Any] = {
            "channel": channel,
            "role": role,
            "wav": wav,
            "text": "",
            "error": "",
        }
        path = Path(wav) if wav else Path()
        if not wav or not path.is_file():
            item["error"] = "no_wav"
            out.append(item)
            continue
        text, err = transcribe_wav(path)
        item["text"] = text
        item["error"] = err
        out.append(item)
    return out


def capture_wake_reply(dest: Path, duration_ms: int) -> dict[str, Any]:
    """Record the gap then STT. Prefer record_wake_reply_window + finish_wake_reply_stt
    in the trial so STT does not sit between the two phrases.
    """
    recorded = record_wake_reply_window(dest, duration_ms)
    return finish_wake_reply_stt(recorded)
