"""Cut continuous PCM into utterances (energy / silence based)."""

from __future__ import annotations

import logging
import struct
import time
from collections.abc import Callable, Iterator
from typing import Iterable

from mac_voice.audio.types import AudioFormat, AudioUtterance, PCM_16K_MONO

log = logging.getLogger("mac_voice.audio.segmenter")

# Start speech when RMS clears this multiple of energy_threshold.
# 2× (not 3×): 开灯 often peaks ~1200–2500 while HVAC sits just above 500.
_START_GATE = 2.0
# After this much "speech" without a voice-like peak, drop (never queue).
# Keep ≥1s so a short command that starts on HVAC rumble is not aborted
# before its peak is visible.
_AMBIENT_ABORT_MS = 1500
# peak/mean below this at mid level ⇒ steady noise, not 面条.
_AMBIENT_CREST = 1.4
# After a voiced peak, RMS this far below the peak counts as trailing quiet
# even when HVAC still sits above energy_threshold — but never when the
# current chunk is still above start_threshold (that is a follow-up 开灯).
_VOICE_DROP_RATIO = 0.25
# Back to the pre-speech floor (HVAC) counts as trailing quiet.
_FLOOR_QUIET_RATIO = 1.35
# Speech that opened just above start_th is rumble, not a shout; returning
# to that onset is trailing quiet.
_ONSET_FLOOR_MULT = 1.3


def _rms_s16le(pcm: bytes) -> float:
    """RMS of little-endian int16 PCM (no audioop — removed in Py3.13+)."""
    if len(pcm) < 2:
        return 0.0
    n = len(pcm) // 2
    total = 0
    for i in range(n):
        sample = struct.unpack_from("<h", pcm, i * 2)[0]
        total += sample * sample
    return (total / n) ** 0.5


def _looks_ambient(peak: float, mean: float, start_threshold: float) -> bool:
    """True when the clip is rumble / HVAC, not voiced speech."""
    if peak < start_threshold:
        return True
    if peak >= start_threshold * 1.5:
        return False
    return peak / max(mean, 1.0) < _AMBIENT_CREST


# Phone Home Mic: room music often sits above start_th after 面条 — still
# treat a clear drop from the voice peak as trailing quiet.
_PHONE_VOICE_DROP_RATIO = 0.42


def _is_trailing_quiet(
    level: float,
    peak_rms: float,
    energy_threshold: float,
    start_threshold: float,
    floor_rms: float = 0.0,
    onset_rms: float = 0.0,
    *,
    voice_drop_ratio: float = _VOICE_DROP_RATIO,
    allow_peak_drop_above_start: bool = False,
) -> bool:
    """True at true silence, or after a voice peak when energy falls back to rumble.

    A loud TTS echo (又咋了 ~16k RMS) must not make a follow-up 关闭台灯
    (~2k) look like trailing quiet: anything still at start_threshold is speech
    unless we have returned to the HVAC floor / rumble onset.

    ``allow_peak_drop_above_start`` (phone HAP1): after a strong peak, a drop
    to ``voice_drop_ratio`` of peak counts even when room noise is still above
    start_threshold — otherwise music bleed waits until max_speech.
    """
    if level < energy_threshold:
        return True
    if floor_rms > 0 and level <= max(energy_threshold, floor_rms * _FLOOR_QUIET_RATIO):
        return True
    if (
        0 < onset_rms < start_threshold * _ONSET_FLOOR_MULT
        and peak_rms > onset_rms * 1.5
        and level <= max(energy_threshold, onset_rms * _FLOOR_QUIET_RATIO)
    ):
        return True
    if (
        allow_peak_drop_above_start
        and peak_rms >= start_threshold * 2.0
        and level <= peak_rms * voice_drop_ratio
    ):
        return True
    if level >= start_threshold:
        return False
    if peak_rms < start_threshold:
        return False
    return level <= peak_rms * voice_drop_ratio


def iter_utterances(
    pcm_chunks: Iterable[bytes],
    *,
    format: AudioFormat = PCM_16K_MONO,
    energy_threshold: float = 500.0,
    start_threshold: float | None = None,
    silence_ms: int = 1000,
    min_speech_ms: int = 400,
    max_speech_ms: int = 8000,
    pre_roll_ms: int = 200,
    ambient_abort_ms: int = _AMBIENT_ABORT_MS,
    clock: Callable[[], float] = time.monotonic,
    muted: Callable[[], bool] | None = None,
    on_activity: Callable[[str], None] | None = None,
    voice_drop_ratio: float = _VOICE_DROP_RATIO,
    allow_peak_drop_above_start: bool = False,
) -> Iterator[AudioUtterance]:
    """
    Yield utterances from a continuous PCM stream.

    Open a clip on the first chunk with RMS >= start_threshold (default 2×
    energy_threshold) so a ~1s 开灯 is queued. Stay in the clip until
    silence_ms of trailing quiet (true silence or drop back to the HVAC
    floor), or max_speech_ms. Flat / low rumble is dropped here and never
    queued for STT.
    """
    start_th = float(
        start_threshold if start_threshold is not None else energy_threshold * _START_GATE
    )
    start_th = max(start_th, energy_threshold)
    drop_ratio = float(voice_drop_ratio)
    peak_drop_ok = bool(allow_peak_drop_above_start)
    sw = format.sample_width
    bytes_per_ms = max(1, format.sample_rate * format.channels * sw // 1000)
    silence_bytes = silence_ms * bytes_per_ms
    min_speech_bytes = min_speech_ms * bytes_per_ms
    max_speech_bytes = max_speech_ms * bytes_per_ms
    pre_roll_bytes = pre_roll_ms * bytes_per_ms
    abort_bytes = max(min_speech_bytes, ambient_abort_ms * bytes_per_ms)

    pre_roll = bytearray()
    buf = bytearray()
    in_speech = False
    pending_start = bytearray()
    pending_start_at = 0.0
    silent_run = 0
    speech_start = 0.0
    last_voice = 0.0
    peak_rms = 0.0
    rms_sum = 0.0
    rms_n = 0
    floor_rms = 0.0
    onset_rms = 0.0
    idle_floor = 0.0

    def _note(state: str) -> None:
        if on_activity is not None:
            on_activity(state)

    def _reset() -> None:
        nonlocal in_speech, silent_run, peak_rms, rms_sum, rms_n, floor_rms, onset_rms
        buf.clear()
        pending_start.clear()
        in_speech = False
        silent_run = 0
        peak_rms = 0.0
        rms_sum = 0.0
        rms_n = 0
        floor_rms = 0.0
        onset_rms = 0.0
        pre_roll.clear()
        _note("idle")

    for chunk in pcm_chunks:
        if not chunk:
            continue
        if muted is not None and muted():
            if in_speech or pending_start:
                log.info("playback mute — drop in-progress clip")
                _reset()
            else:
                pending_start.clear()
                pre_roll.clear()
            continue
        now = clock()
        level = _rms_s16le(chunk)
        if not in_speech:
            pre_roll.extend(chunk)
            if len(pre_roll) > pre_roll_bytes * 2:
                pre_roll = pre_roll[-pre_roll_bytes:]
            if level < start_th:
                idle_floor = level if idle_floor <= 0 else idle_floor * 0.9 + level * 0.1
            if level >= start_th:
                in_speech = True
                silent_run = 0
                speech_start = now
                last_voice = now
                floor_rms = idle_floor if idle_floor > 0 else energy_threshold
                onset_rms = level
                buf = bytearray(pre_roll)
                buf.extend(chunk)
                pending_start.clear()
                pre_roll.clear()
                peak_rms = level
                rms_sum = level
                rms_n = 1
                _note("speech")
                log.debug("speech start rms=%.0f start_th=%.0f", level, start_th)
            continue

        buf.extend(chunk)
        rms_sum += level
        rms_n += 1
        if level > peak_rms:
            peak_rms = level
        if _is_trailing_quiet(
            level,
            peak_rms,
            energy_threshold,
            start_th,
            floor_rms,
            onset_rms,
            voice_drop_ratio=drop_ratio,
            allow_peak_drop_above_start=peak_drop_ok,
        ):
            silent_run += len(chunk)
        else:
            silent_run = 0
            last_voice = now

        mean_rms = rms_sum / max(rms_n, 1)
        if len(buf) >= abort_bytes and _looks_ambient(peak_rms, mean_rms, start_th):
            log.info(
                "ambient drop peak_rms=%.0f mean_rms=%.0f ~%.1fs (not queued)",
                peak_rms,
                mean_rms,
                len(buf) / bytes_per_ms / 1000.0,
            )
            # Keep the abort chunk if it is already a command-level onset.
            keep_voice = level >= start_th
            keep = bytes(chunk) if keep_voice else b""
            keep_at = now
            _reset()
            if keep:
                in_speech = True
                silent_run = 0
                speech_start = keep_at
                last_voice = keep_at
                floor_rms = idle_floor if idle_floor > 0 else energy_threshold
                onset_rms = level
                buf = bytearray(keep)
                peak_rms = level
                rms_sum = level
                rms_n = 1
                _note("speech")
            continue

        too_long = len(buf) >= max_speech_bytes
        ended = silent_run >= silence_bytes and len(buf) >= min_speech_bytes
        if too_long or ended:
            trim = min(silent_run, len(buf) // 2) if ended else 0
            pcm = bytes(buf[: len(buf) - trim] if trim else buf)
            speech_end = last_voice if ended else now
            if len(pcm) >= min_speech_bytes and not _looks_ambient(
                peak_rms, mean_rms, start_th
            ):
                log.info(
                    "utterance ready bytes=%d ~%.1fs reason=%s peak_rms=%.0f",
                    len(pcm),
                    len(pcm) / bytes_per_ms / 1000.0,
                    "max" if too_long else "silence",
                    peak_rms,
                )
                yield AudioUtterance.from_pcm(
                    pcm,
                    format=format,
                    speech_start=speech_start,
                    speech_end=speech_end,
                )
            elif len(pcm) >= min_speech_bytes:
                log.info(
                    "ambient drop peak_rms=%.0f mean_rms=%.0f ~%.1fs (not queued)",
                    peak_rms,
                    mean_rms,
                    len(pcm) / bytes_per_ms / 1000.0,
                )
            _reset()
