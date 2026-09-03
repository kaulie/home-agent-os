"""music.recognize orchestration: continuous capture → rolling-window recognition.

The session records from the mic continuously for up to `cfg.max_sec`. Once at
least `cfg.min_sec` is captured it tries the provider on the **most recent
min_sec** rolling window every `cfg.retry_every_sec` seconds. A hit stops early;
reaching max_sec without a hit fails gracefully (timeout). Sessions are fully
deterministic in tests by injecting `iter_pcm` / `provider` / `pcm_to_wav`.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from mac_edge.plugins.music_recognize.config import BYTES_PER_SEC, MusicRecognizeConfig
from mac_edge.plugins.music_recognize.errors import MusicRecognizeError
from mac_edge.plugins.music_recognize.providers import ProviderError, SongMatch
from mac_edge.plugins.music_recognize.wav import has_signal, pcm_to_wav

log = logging.getLogger("mac_edge.music_recognize.orchestrate")

TIMEOUT_MSG = "抱歉，没有识别出这首歌。可以靠近音乐、调大音量，或再试一次。"
SILENT_MSG = "没有听到音乐声，没能识曲。请先播放要识别的歌曲，再试一次。"


def _answer_for_match(match: SongMatch) -> str:
    title = (match.title or "").strip()
    artist = (match.artist or "").strip()
    if not title:
        return "识别到一首歌，但没拿到歌名。"
    if artist:
        return f"这首歌是{artist}的《{title}》"
    return f"这首歌叫《{title}》"


def build_match_outputs(match: SongMatch, captured_sec: float) -> dict:
    return {
        "matched": True,
        "song_title": match.title or "",
        "artist": match.artist or "",
        "album": match.album or "",
        "confidence": match.confidence,
        "captured_sec": round(captured_sec, 1),
        "answer_text": _answer_for_match(match),
    }


def build_failure_outputs(captured_sec: float, *, heard_signal: bool) -> dict:
    return {
        "matched": False,
        "song_title": "",
        "artist": "",
        "album": "",
        "confidence": None,
        "captured_sec": round(captured_sec, 1),
        "answer_text": TIMEOUT_MSG if heard_signal else SILENT_MSG,
    }


def run_session(
    cfg: MusicRecognizeConfig,
    *,
    iter_pcm: Iterable[bytes],
    provider: Callable[[bytes], SongMatch | None],
    pcm_to_wav_fn: Callable[[bytes], bytes] = pcm_to_wav,
    signal_fn: Callable[[bytes], bool] | None = None,
) -> dict:
    """Capture & recognize; returns output dict (always matches the wire schema).

    Raises MusicRecognizeError only for provider-level failures (network etc.)
    that should abort the step with a clear message.
    """
    threshold = cfg.signal_threshold
    has_audio = signal_fn or (lambda pcm: has_signal(pcm, threshold))

    collected = bytearray()
    total_sec = 0.0
    window_bytes = max(1, cfg.window_bytes)
    max_bytes = max(window_bytes, cfg.max_bytes)
    heard_signal = False
    attempts = 0
    next_attempt_sec = cfg.min_sec

    iterable = iter(iter_pcm)
    try:
        while total_sec < cfg.max_sec:
            chunk = next(iterable, None)
            if chunk is None:
                break
            if not chunk:
                continue
            collected.extend(chunk)
            total_sec += len(chunk) / BYTES_PER_SEC
            if len(collected) > max_bytes:
                del collected[: len(collected) - max_bytes]

            if total_sec < cfg.min_sec:
                continue
            if total_sec < next_attempt_sec:
                continue

            attempts += 1
            window = bytes(collected[-window_bytes:]) if len(collected) >= window_bytes else bytes(collected)
            if has_audio(window):
                heard_signal = True
                log.info(
                    "music.recognize attempt=%s captured_sec=%.1f window_sec=%.1f",
                    attempts,
                    total_sec,
                    len(window) / BYTES_PER_SEC,
                )
                match = _safe_provider_call(provider, pcm_to_wav_fn(window))
                if match is not None:
                    log.info("music.recognize matched title=%r artist=%r", match.title, match.artist)
                    return build_match_outputs(match, total_sec)
            next_attempt_sec = total_sec + cfg.retry_every_sec
    finally:
        close = getattr(iterable, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # pragma: no cover - best-effort generator cleanup
                pass

    # Reached max duration without a hit (or stream ended): one final attempt.
    if total_sec >= cfg.min_sec and collected:
        attempts += 1
        window = bytes(collected[-window_bytes:]) if len(collected) >= window_bytes else bytes(collected)
        if has_audio(window):
            heard_signal = True
            log.info("music.recognize final attempt captured_sec=%.1f", total_sec)
            match = _safe_provider_call(provider, pcm_to_wav_fn(window))
            if match is not None:
                return build_match_outputs(match, total_sec)
    log.info("music.recognize no match after %.1fs attempts=%s", total_sec, attempts)
    return build_failure_outputs(total_sec, heard_signal=heard_signal)


def _safe_provider_call(
    provider: Callable[[bytes], SongMatch | None],
    wav: bytes,
) -> SongMatch | None:
    try:
        return provider(wav)
    except ProviderError as e:
        raise MusicRecognizeError(str(e)) from e
