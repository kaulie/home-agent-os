"""Listen / play-song / transport shortcut: strip prefixes, do not split artist vs title."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .matcher import matches_any

# Exact utterances after courtesy strip. Longer tokens first.
# Must run before play: 停止播放 / 暂停播放 contain 播放.
_CONTROL_EXACT = (
    ("暂停播放", "music.pause"),
    ("暂停歌曲", "music.pause"),
    ("继续播放", "music.resume"),
    ("恢复播放", "music.resume"),
    ("接着播放", "music.resume"),
    ("下一首歌", "music.next"),
    ("上一首歌", "music.previous"),
    ("停止播放", "music.stop"),
    ("切歌", "music.next"),
    ("上一首", "music.previous"),
)

# Strong music talk — intercept even when remainder is empty
# (Mac: resume if possible, else daily recommend queue).
# Longer tokens first. 听歌曲 before 听歌 so 「听歌曲」 is not song=「曲」.
STRONG_TRIGGERS = (
    "听听歌",
    "听会歌",
    "听下歌",
    "听一下",
    "播放歌曲",
    "播放音乐",
    "听歌曲",
    "播歌曲",
    "放歌曲",
    "放音乐",
    "放一首",
    "来一首",
    "来首",
    "听听",
    "听下",
    "听歌",
    "放歌",
)

# Longer tokens first so 听听歌 / 听一下 / 听歌曲 win over 听歌 / 听.
_PLAY_PREFIXES = (
    "播放歌曲",
    "播放音乐",
    "听歌曲",
    "播歌曲",
    "放歌曲",
    "放音乐",
    "听听歌",
    "听会歌",
    "听下歌",
    "听一下",
    "放一首",
    "来一首",
    "来首",
    "听听",
    "听下",
    "听歌",
    "放歌",
    "播放",
    "播",
    "放",
    "听",
)

# 「听」/「播」太短，只收 「xxx的歌/歌曲」，避免「听天气预报」误伤。
_PLAYLIST_SUFFIXES = ("的歌曲", "的歌")
_BARE_VERBS_ANY_REMAINDER = ("播放", "放")
_BARE_VERBS_PLAYLIST_ONLY = ("听", "播")
_TRAILING_PUNCT = "。．.！!？?，,、；;：:…~～"

# Longer first: 下载歌曲 before 下载. Empty remainder after 下载歌曲 must not intercept.
_CACHE_SONG_PREFIXES = ("下载歌曲", "缓存歌曲")
_CACHE_BARE_PREFIXES = ("下载", "缓存")
_COUNT_TAIL = re.compile(r"(\d+)\s*首$")
# Leading quantity is not part of the artist/title (「几首周杰伦的歌」).
_LEADING_QUANTITY = re.compile(r"^(?:几首|几曲|一些|(\d+)\s*首)\s*")
_PLAY_QUEUE_MAX = 20
_FEW_SONGS_DEFAULT = 5


_COURTESY_PREFIXES = (
    "请帮我",
    "请给我",
    "麻烦帮我",
    "帮我",
    "给我",
    "麻烦",
    "请",
)

_EXCLUDE = (
    "幻灯片",
    "幻灯",
    "视频",
    "直播",
    "投屏",
    "照片",
    "图片",
    "电影",
    "电视剧",
)


@dataclass(frozen=True)
class MusicPlayHit:
    song: str
    user_input: str
    match_ms: int
    count: int | None = None


@dataclass(frozen=True)
class MusicControlHit:
    capability: str
    user_input: str
    match_ms: int


@dataclass(frozen=True)
class MusicCacheHit:
    song: str
    user_input: str
    count: int | None
    match_ms: int


def _lstrip_first(text: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if prefix and text.startswith(prefix):
            return text[len(prefix) :].lstrip()
    return text


def _lstrip_courtesy(text: str) -> str:
    rest = text
    while True:
        nxt = _lstrip_first(rest, _COURTESY_PREFIXES)
        if nxt == rest:
            return rest
        rest = nxt


def _remainder_after_play_prefix(text: str) -> tuple[str, str]:
    """Return (matched_prefix, remainder). Prefix is empty if none matched."""
    for prefix in _PLAY_PREFIXES:
        if prefix and text.startswith(prefix):
            return prefix, text[len(prefix) :].lstrip()
    return "", text


def _rstrip_punct(text: str) -> str:
    return str(text or "").strip().rstrip(_TRAILING_PUNCT).strip()


def _playlist_remainder(remainder: str) -> bool:
    """True when remainder is 「xxx的歌/歌曲」 with a non-empty xxx."""
    text = str(remainder or "").strip()
    if not text:
        return False
    for suffix in _PLAYLIST_SUFFIXES:
        if text.endswith(suffix) and text[: -len(suffix)].strip():
            return True
    return False


def _split_trailing_count(remainder: str) -> tuple[str, int | None]:
    """Strip trailing Arabic 「N首」. Chinese numerals are out of scope."""
    text = str(remainder or "").strip()
    matched = _COUNT_TAIL.search(text)
    if not matched:
        return text, None
    rest = text[: matched.start()].strip()
    return rest, int(matched.group(1))


def strip_leading_quantity(text: str) -> tuple[str, int | None]:
    """Strip leading 「几首/几曲/一些/N首」. Returns (rest, count_hint)."""
    raw = str(text or "").strip()
    if not raw:
        return "", None
    matched = _LEADING_QUANTITY.match(raw)
    if not matched:
        return raw, None
    rest = raw[matched.end() :].strip()
    if matched.group(1):
        n = int(matched.group(1))
        return rest, max(1, min(n, _PLAY_QUEUE_MAX))
    return rest, _FEW_SONGS_DEFAULT


def _collapse_duplicate_chars(text: str) -> str:
    """Collapse consecutive identical chars (ASR: 「继继续播放」→「继续播放」)."""
    raw = str(text or "")
    if not raw:
        return raw
    out: list[str] = [raw[0]]
    for ch in raw[1:]:
        if ch != out[-1]:
            out.append(ch)
    return "".join(out)


def match_control(text: str) -> MusicControlHit | None:
    t0 = time.perf_counter()
    utterance = str(text or "").strip()
    if not utterance:
        return None
    stripped = _rstrip_punct(_lstrip_courtesy(utterance))
    if not stripped:
        return None
    normalized = _collapse_duplicate_chars(stripped)
    for phrase, capability in _CONTROL_EXACT:
        if stripped == phrase or normalized == phrase:
            match_ms = int(round((time.perf_counter() - t0) * 1000))
            return MusicControlHit(
                capability=capability,
                user_input=utterance,
                match_ms=match_ms,
            )
    return None


def match_play(text: str) -> MusicPlayHit | None:
    t0 = time.perf_counter()
    utterance = str(text or "").strip()
    if not utterance:
        return None
    if matches_any(utterance, _EXCLUDE):
        return None

    stripped = _rstrip_punct(_lstrip_courtesy(utterance))
    if not stripped:
        return None

    strong = matches_any(utterance, STRONG_TRIGGERS)
    prefix, remainder = _remainder_after_play_prefix(stripped)
    remainder = _rstrip_punct(remainder)

    if prefix in _BARE_VERBS_ANY_REMAINDER:
        if not remainder:
            return None
        song = remainder
    elif prefix in _BARE_VERBS_PLAYLIST_ONLY:
        if not _playlist_remainder(remainder):
            return None
        song = remainder
    elif prefix:
        song = remainder
    elif strong:
        song = ""
    else:
        return None

    count: int | None = None
    if song:
        song, count = strip_leading_quantity(song)

    match_ms = int(round((time.perf_counter() - t0) * 1000))
    return MusicPlayHit(
        song=song,
        user_input=utterance,
        match_ms=match_ms,
        count=count,
    )


def match_cache(text: str) -> MusicCacheHit | None:
    """下载/缓存 index prefetch. Must run before match_play."""
    t0 = time.perf_counter()
    utterance = str(text or "").strip()
    if not utterance:
        return None
    if matches_any(utterance, _EXCLUDE):
        return None

    stripped = _rstrip_punct(_lstrip_courtesy(utterance))
    if not stripped:
        return None

    for prefix in _CACHE_SONG_PREFIXES:
        if stripped.startswith(prefix):
            remainder, count = _split_trailing_count(
                _rstrip_punct(stripped[len(prefix) :].lstrip())
            )
            if not remainder:
                return None
            match_ms = int(round((time.perf_counter() - t0) * 1000))
            return MusicCacheHit(
                song=remainder,
                user_input=utterance,
                count=count,
                match_ms=match_ms,
            )

    for prefix in _CACHE_BARE_PREFIXES:
        if stripped.startswith(prefix):
            remainder, count = _split_trailing_count(
                _rstrip_punct(stripped[len(prefix) :].lstrip())
            )
            if not _playlist_remainder(remainder):
                return None
            match_ms = int(round((time.perf_counter() - t0) * 1000))
            return MusicCacheHit(
                song=remainder,
                user_input=utterance,
                count=count,
                match_ms=match_ms,
            )
    return None
