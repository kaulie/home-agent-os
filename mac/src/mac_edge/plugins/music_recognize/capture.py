"""Mic capture for music.recognize — reuse the same 16k/mono stack as mac_voice.

The real path opens a `SoundDeviceAudioSource` (mac_voice.audio.source). The
capability step drives a rolling window and may stop before the max duration,
so the generator is closed from the orchestration layer on early exit.
"""

from __future__ import annotations

import logging
from typing import Iterator

from mac_edge.plugins.music_recognize.config import SAMPLE_RATE, _parse_device
from mac_edge.plugins.music_recognize.errors import MusicCaptureError

log = logging.getLogger("mac_edge.music_recognize.capture")

DEFAULT_CHUNK_SEC = 0.1


def _open_pcm_generator(
    device: int | str | None,
    *,
    chunk_sec: float = DEFAULT_CHUNK_SEC,
) -> Iterator[bytes]:
    """Yield int16 mono PCM chunks from the mic; closes the stream on exit."""
    try:
        from mac_voice.audio.source import SoundDeviceAudioSource
        from mac_voice.audio.types import AudioFormat, PCM_16K_MONO
    except ImportError as e:  # pragma: no cover - mac_voice always importable here
        raise MusicCaptureError(
            "识曲需要 mac_voice 音频栈（sounddevice/numpy）"
        ) from e

    fmt = AudioFormat(sample_rate=SAMPLE_RATE, channels=1, sample_width=2)
    if fmt != PCM_16K_MONO:  # keep linters honest: use the shared constant
        fmt = PCM_16K_MONO
    block_ms = max(20, int(chunk_sec * 1000))

    try:
        source = SoundDeviceAudioSource(device=device, format=fmt, block_ms=block_ms)
    except Exception as e:  # device resolve failures surface on open(); guard anyway
        raise MusicCaptureError(f"无法打开麦克风：{type(e).__name__}: {e}") from e

    try:
        for chunk in source.iter_pcm(chunk_ms=block_ms):
            yield chunk
    except (OSError, ValueError, RuntimeError) as e:
        log.warning("mic capture stopped: %s", e)
        raise MusicCaptureError(f"麦克风收录失败：{e}") from e
    finally:
        try:
            source.close()
        except Exception as e:  # pragma: no cover - best-effort cleanup
            log.warning("mic close failed: %s", e)


def iter_mic_pcm(device: int | str | None) -> Iterator[bytes]:
    """Public capture iterator (lazy open). device may be name/index/None."""
    resolved = _parse_device(str(device) if device is not None else "")
    return _open_pcm_generator(resolved)
