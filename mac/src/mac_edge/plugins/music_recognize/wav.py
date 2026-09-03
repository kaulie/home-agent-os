"""Minimal in-memory WAV writer for int16 mono PCM (16 kHz)."""

from __future__ import annotations

import struct
import wave
from io import BytesIO

from mac_edge.plugins.music_recognize.config import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH


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
