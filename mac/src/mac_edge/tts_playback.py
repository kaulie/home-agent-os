"""Cross-process flag: Runtime is playing TTS; mac_voice must not STT the speaker."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger("mac_edge.tts_playback")

_FLAG_NAME = "tts_playing"
_STALE_SEC = 180.0
_HANGOVER_SEC = 0.7


def flag_path() -> Path:
    env = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if env:
        return Path(env).expanduser() / _FLAG_NAME
    return Path(__file__).resolve().parents[2] / "data" / _FLAG_NAME


def is_playing(path: Path | None = None, *, stale_s: float = _STALE_SEC) -> bool:
    p = path if path is not None else flag_path()
    try:
        st = p.stat()
    except OSError:
        return False
    return (time.time() - st.st_mtime) <= max(1.0, stale_s)


@contextmanager
def playback_session() -> Iterator[None]:
    path = flag_path()
    wrote = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1\n", encoding="utf-8")
        wrote = True
        log.info("tts playback start flag=%s", path)
    except OSError as e:
        log.warning("tts playback flag write failed: %s", e)
    try:
        yield
    finally:
        if wrote:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            log.info("tts playback end")


class PlaybackMute:
    """True while the flag file exists, plus a short hangover after it disappears."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        hangover_s: float = _HANGOVER_SEC,
        clock=time.monotonic,
    ) -> None:
        self._path = path if path is not None else flag_path()
        self._hangover_s = max(0.0, float(hangover_s))
        self._clock = clock
        self._was = False
        self._until = 0.0

    def __call__(self) -> bool:
        now = self._clock()
        on = is_playing(self._path)
        if on:
            if not self._was:
                log.info("tts playback mute on")
            self._was = True
            return True
        if self._was:
            self._until = now + self._hangover_s
            self._was = False
            log.info("tts playback mute hangover %.1fs", self._hangover_s)
        return now < self._until
