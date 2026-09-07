"""Minimal in-memory WAV writer for int16 mono PCM (16 kHz)."""

from __future__ import annotations

import logging
import struct
import wave
from io import BytesIO
from pathlib import Path

from mac_edge.plugins.music_recognize.config import (
    CHANNELS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    MusicRecognizeConfig,
)

log = logging.getLogger("mac_edge.music_recognize.wav")


def pcm_to_wav(pcm: bytes, *, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw little-endian int16 mono PCM into a WAV byte blob."""
    if not pcm:
        raise ValueError("empty pcm cannot be wrapped as wav")
    bio = BytesIO()
    with wave.open(bio, "wb") as fh:
        fh.setnchannels(CHANNELS)
        fh.setsampwidth(SAMPLE_WIDTH)
        fh.setframerate(sample_rate)
        fh.writeframes(pcm)
    return bio.getvalue()


def maybe_keep_wav(
    cfg: MusicRecognizeConfig,
    stem: str,
    wav_bytes: bytes,
) -> Path | None:
    """When WAV_KEEP is on, write ``wav_bytes`` under ``cfg.wav_dir`` and return path."""
    if not cfg.keep_wav or cfg.wav_dir is None or not wav_bytes:
        return None
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (stem or "clip"))
    if not safe:
        safe = "clip"
    try:
        cfg.wav_dir.mkdir(parents=True, exist_ok=True)
        path = cfg.wav_dir / f"{safe}.wav"
        path.write_bytes(wav_bytes)
        log.info("music.recognize kept wav path=%s bytes=%s", path, len(wav_bytes))
        return path
    except OSError as e:
        log.warning("music.recognize keep wav failed stem=%s: %s", safe, e)
        return None


def pcm_rms(pcm: bytes) -> float:
    """Root-mean-square of int16 PCM (bytes), 0.0 for empty/silent input."""
    if not pcm or len(pcm) % 2:
        return 0.0
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm)
    total = 0.0
    for value in samples:
        total += float(value) * float(value)
    return (total / n) ** 0.5


def has_signal(pcm: bytes, threshold: float) -> bool:
    """Heuristic gate: meaningful audio above near-silence."""
    return pcm_rms(pcm) >= float(threshold)
