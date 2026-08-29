"""Listen / play-song / transport shortcut: strip prefixes, do not split artist vs title."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .matcher import matches_any

# Exact utterances after courtesy strip. Longer tokens first.
# Must run before play: 停止播放 / 暂停播放 contain 播放.
_CONTROL_EXACT = (
    ("暂停播放", "music.pause"),
    ("暂停歌曲", "music.pause"),
    ("下一首歌", "music.next"),
    ("停止播放", "music.stop"),
    ("切歌", "music.next"),
)

# Strong music talk — intercept even when remainder is empty (Mac then asks for a title).
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


@dataclass(frozen=True)
class MusicControlHit:
    capability: str
    user_input: str
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


def match_control(text: str) -> MusicControlHit | None:
    t0 = time.perf_counter()
    utterance = str(text or "").strip()
    if not utterance:
        return None
    stripped = _rstrip_punct(_lstrip_courtesy(utterance))
    if not stripped:
        return None
    for phrase, capability in _CONTROL_EXACT:
        if stripped == phrase:
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

    match_ms = int(round((time.perf_counter() - t0) * 1000))
    return MusicPlayHit(song=song, user_input=utterance, match_ms=match_ms)
