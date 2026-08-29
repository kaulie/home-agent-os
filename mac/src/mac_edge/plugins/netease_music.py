"""Mac Edge: netease.music via ncm-cli (desktop 网易云 App / orpheus).

LLM extracts song/artist. This plugin only assembles ncm-cli argv and
reads/writes ``mac_edge.ncm_songs``. Keyword is one argv value.

「xxx的歌/歌曲」: exact title search first; if no same-name hit, search
keyword=xxx and pick by ``artists`` (NetEase order).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

from mac_edge.capability_availability import Availability
from mac_edge.music_linkage import enter as enter_music_mode
from mac_edge.music_linkage import exit_mode as exit_music_mode
from mac_edge.ncm_songs import (
    NcmSongsError,
    find_by_name_artist,
    find_index_by_name_artist,
    init_db,
    mark_played,
    normalize_text,
    upsert_record,
)

log = logging.getLogger("mac_edge.netease_music")

SEARCH_TIMEOUT_SEC = 30.0
SEARCH_LIMIT = 10
CACHE_PAGE = 20
CACHE_DEFAULT_COUNT = 100
CACHE_MAX_COUNT = 200
CACHE_PAGE_SLEEP_SEC = 10.0
PLAY_TIMEOUT_SEC = 20.0
CONTROL_TIMEOUT_SEC = 15.0

NO_SONG_MSG = "目前只支持按歌曲播放，请说出歌名"

# Longer first: 「的歌曲」 before 「的歌」. Not play-verb prefixes.
_PLAYLIST_SUFFIXES = ("的歌曲", "的歌")
_TRAILING_PUNCT = "。．.！!？?，,、；;：:…~～"

_MUSIC_CAPS = frozenset(
    {
        "music.play",
        "music.cache",
        "music.pause",
        "music.resume",
        "music.stop",
        "music.next",
        "music.previous",
    }
)

_CONTROL_CMD = {
    "music.pause": ("pause",),
    "music.resume": ("resume",),
    "music.stop": ("stop",),
    "music.next": ("next",),
    "music.previous": ("prev",),
}

_COMMON_BINS = (
    "/usr/local/bin/ncm-cli",
    "/opt/homebrew/bin/ncm-cli",
    str(Path.home() / ".npm-global" / "bin" / "ncm-cli"),
)


class NeteaseMusicError(Exception):
    pass


def ncm_cli_bin() -> str | None:
    override = (os.environ.get("MAC_EDGE_NCM_CLI") or os.environ.get("NCM_CLI") or "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return str(path)
        which = shutil.which(override)
        return which
    found = shutil.which("ncm-cli")
    if found:
        return found
    for raw in _COMMON_BINS:
        path = Path(raw).expanduser()
        if path.is_file():
            return str(path)
    return None


def ncm_cli_configured() -> bool:
    return bool(ncm_cli_bin())


netease_configured = ncm_cli_configured


def is_available(_config: Any = None) -> Availability:
    if ncm_cli_bin():
        return Availability.available()
    return Availability.unavailable("网易云不可用：本机找不到 ncm-cli")


def search_keyword(*, song: str, artist: str | None = None) -> str:
    title = str(song or "").strip()
    singer = str(artist or "").strip()
    if singer:
        return f"{title} {singer}"
    return title


def artist_from_playlist_remainder(remainder: str) -> str:
    """If remainder is 「xxx的歌/歌曲」, return xxx; else empty.

    Does not strip play verbs. Empty artist (remainder is only the suffix) is not this mode.
    """
    text = str(remainder or "").strip().rstrip(_TRAILING_PUNCT).strip()
    if not text:
        return ""
    for suffix in _PLAYLIST_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    return ""


def last_json_object(text: str) -> dict[str, Any]:
    """Last *top-level* JSON object in CLI output (skip [orpheus] lines).

    Nested ``{`` inside an already-decoded object are not candidates.
    Search envelopes therefore stay intact (``data.records``), while play
    still ignores the orpheus prefix and takes the trailing success JSON.
    """
    blob = str(text or "")
    decoder = json.JSONDecoder()
    last: dict[str, Any] | None = None
    i = 0
    n = len(blob)
    while i < n:
        if blob[i] != "{":
            i += 1
            continue
        try:
            obj, consumed = decoder.raw_decode(blob[i:])
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            last = obj
        i += max(1, consumed)
    if last is None:
        raise NeteaseMusicError("ncm-cli 未返回 JSON")
    return last


def _rate_limited(text: str) -> bool:
    return "请求总量超限" in (text or "")


def _run_ncm(args: list[str], *, timeout_sec: float) -> dict[str, Any]:
    bin_path = ncm_cli_bin()
    if not bin_path:
        raise NeteaseMusicError("网易云不可用：本机找不到 ncm-cli")
    cmd = [bin_path, *args]
    log.info("ncm-cli %s", " ".join(args))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(5.0, float(timeout_sec)),
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise NeteaseMusicError(f"ncm-cli 超时（>{int(timeout_sec)}s）") from e
    except OSError as e:
        raise NeteaseMusicError(f"ncm-cli 无法启动：{e}") from e
    combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    if _rate_limited(combined):
        raise NeteaseMusicError("请求总量超限")
    try:
        payload = last_json_object(combined)
    except NeteaseMusicError:
        tail = combined.strip()[-400:] or "(empty)"
        raise NeteaseMusicError(f"ncm-cli 未返回 JSON：{tail}") from None
    if proc.returncode != 0 and payload.get("success") is not True:
        msg = str(payload.get("message") or "").strip()
        raise NeteaseMusicError(msg or f"ncm-cli 退出码 {proc.returncode}")
    return payload


def _str_param(params: dict[str, Any] | None, *keys: str) -> str:
    raw = params if isinstance(params, dict) else {}
    for key in keys:
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _truthy(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in ("1", "true", "yes", "y")


def clamp_cache_count(raw: Any) -> int:
    if raw is None or raw == "":
        return CACHE_DEFAULT_COUNT
    if isinstance(raw, bool):
        return CACHE_DEFAULT_COUNT
    try:
        n = int(raw)
    except (TypeError, ValueError):
        try:
            n = int(float(str(raw).strip()))
        except (TypeError, ValueError):
            return CACHE_DEFAULT_COUNT
    return max(1, min(CACHE_MAX_COUNT, n))


def _record_from_index(row: dict[str, Any]) -> dict[str, Any] | None:
    enc = str(row.get("song_encrypted_id") or "").strip()
    oid = row.get("song_original_id")
    if not enc or oid in (None, ""):
        return None
    rec: dict[str, Any] = {
        "id": enc,
        "originalId": oid,
        "name": row.get("song_name") or "",
    }
    if row.get("artist"):
        rec["artists"] = [{"name": row["artist"]}]
    if row.get("duration") is not None:
        rec["duration"] = row["duration"]
    album: dict[str, Any] = {}
    if row.get("album_original_id") is not None:
        album["originalId"] = row["album_original_id"]
    if row.get("album_encrypted_id"):
        album["id"] = row["album_encrypted_id"]
    if row.get("album_name"):
        album["name"] = row["album_name"]
    if album:
        rec["album"] = album
    return rec


def _cached_record(*, song: str, artist: str) -> dict[str, Any] | None:
    init_db()
    indexed = find_index_by_name_artist(name=song, artist=artist, limit=5)
    if indexed:
        rec = _record_from_index(indexed[0])
        if rec is not None:
            return rec
    hits = find_by_name_artist(name=song, artist=artist, limit=5)
    if not hits:
        return None
    rec = hits[0].get("record")
    return rec if isinstance(rec, dict) else None


def _record_name(record: dict[str, Any]) -> str:
    return str(record.get("name") or "").strip()


def _names_equal(left: str, right: str) -> bool:
    key = normalize_text(left)
    return bool(key) and key == normalize_text(right)


def _artist_names(record: dict[str, Any]) -> tuple[str, ...]:
    raw = record.get("artists")
    if not isinstance(raw, list):
        return ()
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            names.append(name)
    return tuple(names)


def find_exact_title(records: list[Any], title: str) -> dict[str, Any] | None:
    """First record whose name equals title (normalized)."""
    for rec in records:
        if isinstance(rec, dict) and _names_equal(_record_name(rec), title):
            return rec
    return None


def _overlap_keys(*, song: str, keyword: str) -> tuple[str, ...]:
    keys: list[str] = []
    for raw in (song, keyword):
        text = str(raw or "").strip()
        if text and text not in keys:
            keys.append(text)
    return tuple(keys) or ("",)


def char_overlap_score(name: str, keyword: str) -> int:
    """How many characters are shared (multiset), ignoring whitespace."""
    left = "".join(str(name or "").split())
    right = "".join(str(keyword or "").split())
    if not left or not right:
        return 0
    return int(sum((Counter(left) & Counter(right)).values()))


def pick_search_record(
    records: list[Any],
    *,
    keyword: str,
    song: str = "",
) -> dict[str, Any]:
    """Exact name == keyword/song first; else highest character-overlap score."""
    dicts = [r for r in records if isinstance(r, dict)]
    if not dicts:
        raise NeteaseMusicError("网易云搜索结果无效")
    keys = _overlap_keys(song=song, keyword=keyword)
    for rec in dicts:
        name = _record_name(rec)
        if name and name in keys:
            return rec
    best: dict[str, Any] | None = None
    best_score = -1
    for rec in dicts:
        name = _record_name(rec)
        score = max(char_overlap_score(name, key) for key in keys)
        if score > best_score:
            best = rec
            best_score = score
    if best is None:
        raise NeteaseMusicError("网易云搜索结果无效")
    return best


def pick_search_record_by_artist(
    records: list[Any],
    *,
    artist: str,
    song: str = "",
) -> dict[str, Any]:
    """Exact artists[].name first in NetEase order; else max artist char-overlap.

    All-zero artist scores fall back to title pick.
    """
    dicts = [r for r in records if isinstance(r, dict)]
    if not dicts:
        raise NeteaseMusicError("网易云搜索结果无效")
    singer = str(artist or "").strip()
    if singer:
        for rec in dicts:
            if any(_names_equal(name, singer) for name in _artist_names(rec)):
                return rec
        best: dict[str, Any] | None = None
        best_score = -1
        for rec in dicts:
            names = _artist_names(rec)
            score = max((char_overlap_score(n, singer) for n in names), default=0)
            if score > best_score:
                best = rec
                best_score = score
        if best is not None and best_score > 0:
            return best
    return pick_search_record(dicts, keyword=singer or song, song=song)


def cache_search_records(records: list[Any]) -> int:
    """Upsert every search hit into ncm_songs + ncm_song_index. Returns stored count."""
    stored = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        try:
            upsert_record(rec)
            stored += 1
        except NcmSongsError as e:
            log.warning("ncm_songs skip search hit: %s", e)
    return stored


def _unknown_user_input_flag(err: Exception) -> bool:
    msg = str(err or "").lower()
    return (
        "unknown option" in msg
        or "unknown argument" in msg
        or "unexpected argument" in msg
        or "未识别" in msg
        or "未返回 json" in msg
    )


def search_records(
    *,
    keyword: str,
    user_input: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    keyword = str(keyword or "").strip()
    if not keyword:
        return []
    use_limit = SEARCH_LIMIT if limit is None else max(1, int(limit))
    use_offset = 0 if offset is None else max(0, int(offset))
    argv = ["search", "song"]
    used_user_input = bool(str(user_input or "").strip())
    if used_user_input:
        argv.extend(["--userInput", str(user_input).strip()])
    argv.extend(["--keyword", keyword, "--limit", str(use_limit)])
    if offset is not None:
        argv.extend(["--offset", str(use_offset)])

    def _keyword_only_argv() -> list[str]:
        out = ["search", "song", "--keyword", keyword, "--limit", str(use_limit)]
        if offset is not None:
            out.extend(["--offset", str(use_offset)])
        return out

    try:
        payload = _run_ncm(argv, timeout_sec=SEARCH_TIMEOUT_SEC)
    except NeteaseMusicError as e:
        if used_user_input and _unknown_user_input_flag(e):
            log.info("ncm-cli --userInput unsupported; retry keyword only")
            payload = _run_ncm(_keyword_only_argv(), timeout_sec=SEARCH_TIMEOUT_SEC)
        else:
            raise
    code = payload.get("code")
    if code not in (200, None, "200") and code != 200:
        try:
            if int(code) != 200:
                msg = str(payload.get("message") or "").strip()
                raise NeteaseMusicError(msg or f"网易云搜索失败 code={code}")
        except (TypeError, ValueError, NeteaseMusicError):
            msg = str(payload.get("message") or "").strip()
            raise NeteaseMusicError(msg or f"网易云搜索失败 code={code}") from None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list) or not records:
        songs = data.get("songs") if isinstance(data, dict) else None
        records = songs if isinstance(songs, list) else []
    dicts = [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []
    stored = cache_search_records(dicts)
    log.info("ncm search keyword=%r hits=%s cached=%s", keyword, len(dicts), stored)
    return dicts


def search_record(
    *,
    song: str,
    artist: str | None = None,
    user_input: str | None = None,
) -> dict[str, Any]:
    keyword = search_keyword(song=song, artist=artist)
    records = search_records(keyword=keyword, user_input=user_input)
    if not records:
        label = f"「{song} - {artist}」" if artist else f"「{song}」"
        raise NeteaseMusicError(f"网易云未找到歌曲{label}")
    picked = pick_search_record(records, keyword=keyword, song=song)
    log.info(
        "ncm search picked=%r id=%s keyword=%r",
        _record_name(picked),
        picked.get("originalId"),
        keyword,
    )
    return picked


def search_title_then_artist(
    *,
    song: str,
    artist: str,
    user_input: str | None = None,
) -> dict[str, Any]:
    """Exact song title first; if none, search keyword=artist and pick by artists."""
    title = str(song or "").strip()
    singer = str(artist or "").strip()
    records = search_records(keyword=title, user_input=user_input)
    exact = find_exact_title(records, title)
    if exact is not None:
        log.info(
            "ncm exact title hit name=%r id=%s",
            _record_name(exact),
            exact.get("originalId"),
        )
        return exact
    records2 = search_records(keyword=singer, user_input=user_input)
    if not records2:
        raise NeteaseMusicError(f"网易云未找到歌曲「{title}」")
    picked = pick_search_record_by_artist(records2, artist=singer, song=title)
    log.info(
        "ncm artist pick name=%r artist=%r id=%s",
        _record_name(picked),
        singer,
        picked.get("originalId"),
    )
    return picked


def search_artist_only(
    *,
    artist: str,
    user_input: str | None = None,
) -> dict[str, Any]:
    singer = str(artist or "").strip()
    if not singer:
        raise NeteaseMusicError(NO_SONG_MSG)
    records = search_records(keyword=singer, user_input=user_input)
    if not records:
        raise NeteaseMusicError(f"网易云未找到歌手「{singer}」的歌")
    picked = pick_search_record_by_artist(records, artist=singer, song="")
    log.info(
        "ncm artist-only pick name=%r artist=%r id=%s",
        _record_name(picked),
        singer,
        picked.get("originalId"),
    )
    return picked


def play_record(record: dict[str, Any]) -> str:
    encrypted = str(record.get("id") or "").strip()
    original = record.get("originalId")
    if not encrypted or original in (None, ""):
        raise NeteaseMusicError("搜索结果缺少 encrypted-id / original-id")
    payload = _run_ncm(
        [
            "play",
            "--song",
            "--encrypted-id",
            encrypted,
            "--original-id",
            str(original),
        ],
        timeout_sec=PLAY_TIMEOUT_SEC,
    )
    if payload.get("success") is not True:
        msg = str(payload.get("message") or "").strip()
        raise NeteaseMusicError(msg or "网易云播放失败")
    return str(payload.get("message") or "").strip() or f"已唤起云音乐播放歌曲 {original}"


def _control(cap: str) -> str:
    argv = _CONTROL_CMD.get(cap)
    if not argv:
        raise NeteaseMusicError(f"unsupported capability {cap}")
    t0 = time.perf_counter()
    payload = _run_ncm(list(argv), timeout_sec=CONTROL_TIMEOUT_SEC)
    total_ms = int(round((time.perf_counter() - t0) * 1000))
    log.info("%s ncm_cli_ms=%s total_ms=%s", cap, total_ms, total_ms)
    if payload.get("success") is not True:
        msg = str(payload.get("message") or "").strip()
        raise NeteaseMusicError(msg or f"{cap} 失败")
    msg = str(payload.get("message") or "").strip()
    return msg or cap


def play_from_params(params: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    t0 = time.perf_counter()
    song = str(_str_param(params, "song") or "").strip().rstrip(_TRAILING_PUNCT).strip()
    artist = str(_str_param(params, "artist") or "").strip().rstrip(_TRAILING_PUNCT).strip()
    user_input = _str_param(params, "user_input")
    intent_id = _str_param(params, "intent_id") or "-"
    if not song and not artist:
        raise NeteaseMusicError(NO_SONG_MSG)
    playlist_artist = artist_from_playlist_remainder(song)
    t_cache = time.perf_counter()
    if playlist_artist:
        cached = _cached_record(song=song, artist="")
        if cached and not _names_equal(_record_name(cached), song):
            cached = None
        if cached is None:
            cached = _cached_record(song="", artist=playlist_artist)
    elif song:
        cached = _cached_record(song=song, artist=artist)
    else:
        cached = _cached_record(song="", artist=artist)
    cache_ms = int(round((time.perf_counter() - t_cache) * 1000))
    search_ms = 0
    if cached:
        log.info("ncm_songs hit name=%s artist=%s", song or "-", artist or "-")
        record = cached
        cache_label = "hit"
    else:
        t_search = time.perf_counter()
        if playlist_artist:
            record = search_title_then_artist(
                song=song,
                artist=playlist_artist,
                user_input=user_input or None,
            )
        elif not song and artist:
            record = search_artist_only(
                artist=artist,
                user_input=user_input or None,
            )
        else:
            record = search_record(
                song=song,
                artist=artist or None,
                user_input=user_input or None,
            )
        search_ms = int(round((time.perf_counter() - t_search) * 1000))
        cache_label = "miss"
    t_play = time.perf_counter()
    msg = play_record(record)
    play_ms = int(round((time.perf_counter() - t_play) * 1000))
    try:
        oid = upsert_record(record)
        mark_played(oid)
    except NcmSongsError as e:
        log.warning("ncm_songs mark_played failed: %s", e)
    enter_music_mode(trigger_text=f"{song} {artist}".strip())
    total_ms = int(round((time.perf_counter() - t0) * 1000))
    timing = {
        "cache": cache_ms,
        "search": search_ms,
        "play": play_ms,
        "total": total_ms,
    }
    log.info(
        "music.play intent=%s cache_ms=%s search_ms=%s play_ms=%s total_ms=%s cache=%s",
        intent_id,
        cache_ms,
        search_ms,
        play_ms,
        total_ms,
        cache_label,
    )
    return msg, {"timing": timing}


def paged_search_records(
    *,
    keyword: str,
    user_input: str | None = None,
    target: int,
    sleep_fn: Any = None,
) -> list[dict[str, Any]]:
    """Cache-only paging: always --limit 20 + --offset. Sleep between pages."""
    sleeper = time.sleep if sleep_fn is None else sleep_fn
    want = max(1, int(target))
    collected: list[dict[str, Any]] = []
    seen: set[Any] = set()
    offset = 0
    page_i = 0
    while len(collected) < want:
        if page_i > 0:
            sleeper(CACHE_PAGE_SLEEP_SEC)
        batch = search_records(
            keyword=keyword,
            user_input=user_input if page_i == 0 else None,
            limit=CACHE_PAGE,
            offset=offset,
        )
        if not batch:
            break
        before = len(collected)
        for rec in batch:
            oid = rec.get("originalId")
            if oid in seen:
                continue
            seen.add(oid)
            collected.append(rec)
            if len(collected) >= want:
                break
        if len(collected) == before:
            break
        if len(batch) < CACHE_PAGE:
            break
        offset += CACHE_PAGE
        page_i += 1
    return collected[:want]


def cache_from_params(params: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Write ncm_songs index only. Does not play or download audio this round."""
    t0 = time.perf_counter()
    raw = params if isinstance(params, dict) else {}
    song = str(_str_param(raw, "song") or "").strip().rstrip(_TRAILING_PUNCT).strip()
    artist = str(_str_param(raw, "artist") or "").strip().rstrip(_TRAILING_PUNCT).strip()
    user_input = _str_param(raw, "user_input")
    intent_id = _str_param(raw, "intent_id") or "-"
    if not song and not artist:
        raise NeteaseMusicError(NO_SONG_MSG)
    count = clamp_cache_count(raw.get("count"))
    fetch_audio = _truthy(raw.get("fetch_audio"))
    playlist_artist = artist_from_playlist_remainder(song)
    sleeper = time.sleep

    if playlist_artist:
        search_records(
            keyword=song,
            user_input=user_input or None,
            limit=CACHE_PAGE,
            offset=0,
        )
        sleeper(CACHE_PAGE_SLEEP_SEC)
        collected = paged_search_records(
            keyword=playlist_artist,
            user_input=user_input or None,
            target=count,
            sleep_fn=sleeper,
        )
        label = playlist_artist
    elif not song and artist:
        collected = paged_search_records(
            keyword=artist,
            user_input=user_input or None,
            target=count,
            sleep_fn=sleeper,
        )
        label = artist
    else:
        keyword = search_keyword(song=song, artist=artist or None)
        collected = paged_search_records(
            keyword=keyword,
            user_input=user_input or None,
            target=count,
            sleep_fn=sleeper,
        )
        label = song or keyword

    cached_n = len(collected)
    total_ms = int(round((time.perf_counter() - t0) * 1000))
    audio_note = "本轮未下载音频" if fetch_audio else "未下载音频"
    msg = f"已缓存 {cached_n} 首「{label}」索引（{audio_note}）"
    log.info(
        "music.cache intent=%s label=%s cached=%s count=%s fetch_audio=%s total_ms=%s",
        intent_id,
        label,
        cached_n,
        count,
        fetch_audio,
        total_ms,
    )
    return msg, {
        "cached": cached_n,
        "fetch_audio": False,
        "timing": {"total": total_ms},
    }


def run_from_params(
    capability_id: str,
    params: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    cap = str(capability_id or "").strip()
    if cap not in _MUSIC_CAPS:
        raise NeteaseMusicError(f"unsupported capability {cap}")
    if cap == "music.play":
        return play_from_params(params)
    if cap == "music.cache":
        return cache_from_params(params)
    msg = _control(cap)
    if cap == "music.stop":
        exit_music_mode(reason="music.stop")
    return msg, {}


dispatch = run_from_params
