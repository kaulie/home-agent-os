"""Mac Edge: netease.music via ncm-cli (desktop 网易云 App / orpheus).

LLM extracts song/artist. This plugin only assembles ncm-cli argv and
reads/writes ``mac_edge.ncm_songs``. Keyword is one argv value.

「xxx的歌/歌曲」or artist-only: build a reusable cloud playlist then
``play --playlist`` (orpheus). Desktop ``queue add`` is a no-op under
orpheus (success:true + 「队列为空或无法读取」).

Empty song+artist (e.g. 「播放音乐」): try resume, else daily recommend
via the same playlist path.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
    normalize_text,
    record_play,
    upsert_record,
)
from mac_edge.ncm_songs.store import data_dir as ncm_data_dir
from mac_edge.plugins import ncm_play_record as play_rec

log = logging.getLogger("mac_edge.netease_music")

SEARCH_TIMEOUT_SEC = 30.0
SEARCH_LIMIT = 10
ARTIST_QUEUE_MAX = 20
DAILY_RECOMMEND_LIMIT = 20
FEW_SONGS_DEFAULT = 5
CACHE_PAGE = 20
CACHE_DEFAULT_COUNT = 100
CACHE_MAX_COUNT = 200
CACHE_PAGE_SLEEP_SEC = 10.0
PLAY_TIMEOUT_SEC = 20.0
CONTROL_TIMEOUT_SEC = 15.0

NO_SONG_MSG = "目前只支持按歌曲播放，请说出歌名"
BARE_PLAY_FAIL_MSG = "无法开播：没有可继续的播放，且每日推荐不可用"
NOW_PLAYING_PLAYLIST_NAME = "home-agent-now-playing"
NOW_PLAYING_META_FILE = "ncm_now_playing_playlist.json"
# orpheus ``queue add`` returns success:true with this message and does nothing.
_QUEUE_UNREADABLE_MARKERS = ("队列为空", "无法读取")

# Longer first: 「的歌曲」 before 「的歌」. Not play-verb prefixes.
_PLAYLIST_SUFFIXES = ("的歌曲", "的歌")
_TRAILING_PUNCT = "。．.！!？?，,、；;：:…~～"
# Leading quantity is not part of the artist/title (「几首周杰伦的歌」).
_LEADING_QUANTITY = re.compile(r"^(?:几首|几曲|一些|(\d+)\s*首)\s*")
_ORPHEUS_LINE = re.compile(r"\[orpheus\]\s*(orpheus://\S+)", re.IGNORECASE)

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


def strip_leading_quantity(text: str) -> tuple[str, int | None]:
    """Strip leading 「几首/几曲/一些/N首」. Returns (rest, count_hint).

    ``几首/几曲/一些`` → count ``FEW_SONGS_DEFAULT`` (5).
    Arabic ``N首`` → clamp(N, 1, ARTIST_QUEUE_MAX).
    Chinese numerals are out of scope.
    """
    raw = str(text or "").strip()
    if not raw:
        return "", None
    matched = _LEADING_QUANTITY.match(raw)
    if not matched:
        return raw, None
    rest = raw[matched.end() :].strip()
    if matched.group(1):
        n = int(matched.group(1))
        return rest, max(1, min(n, ARTIST_QUEUE_MAX))
    return rest, FEW_SONGS_DEFAULT


def clamp_play_queue_count(raw: Any, *, fallback: int = ARTIST_QUEUE_MAX) -> int:
    """Clamp music.play artist-queue size to 1..ARTIST_QUEUE_MAX."""
    if raw is None or raw == "":
        return max(1, min(int(fallback), ARTIST_QUEUE_MAX))
    if isinstance(raw, bool):
        return max(1, min(int(fallback), ARTIST_QUEUE_MAX))
    try:
        n = int(raw)
    except (TypeError, ValueError):
        try:
            n = int(float(str(raw).strip()))
        except (TypeError, ValueError):
            return max(1, min(int(fallback), ARTIST_QUEUE_MAX))
    return max(1, min(n, ARTIST_QUEUE_MAX))


def artist_from_playlist_remainder(remainder: str) -> str:
    """If remainder is 「xxx的歌/歌曲」, return xxx; else empty.

    Strips leading quantity first. Does not strip play verbs.
    Empty artist (remainder is only the suffix) is not this mode.
    """
    text = str(remainder or "").strip().rstrip(_TRAILING_PUNCT).strip()
    text, _qty = strip_leading_quantity(text)
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


def _orpheus_uri(text: str) -> str | None:
    matched = _ORPHEUS_LINE.search(str(text or ""))
    if not matched:
        return None
    return matched.group(1).rstrip()


def _queue_add_is_noop(payload: dict[str, Any]) -> bool:
    msg = str(payload.get("message") or "")
    return any(marker in msg for marker in _QUEUE_UNREADABLE_MARKERS)


def _run_ncm(
    args: list[str],
    *,
    timeout_sec: float,
    allow_orpheus_only: bool = False,
) -> dict[str, Any]:
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
        uri = _orpheus_uri(combined) if allow_orpheus_only else None
        if uri and proc.returncode == 0:
            return {
                "success": True,
                "message": "已唤起云音乐",
                "orpheus": uri,
            }
        tail = combined.strip()[-400:] or "(empty)"
        raise NeteaseMusicError(f"ncm-cli 未返回 JSON：{tail}") from None
    if proc.returncode != 0 and payload.get("success") is not True:
        msg = str(payload.get("message") or "").strip()
        raise NeteaseMusicError(msg or f"ncm-cli 退出码 {proc.returncode}")
    return payload


def _api_ok(payload: dict[str, Any]) -> bool:
    if payload.get("success") is True:
        return True
    code = payload.get("code")
    if code in (200, "200"):
        return True
    try:
        return int(code) == 200
    except (TypeError, ValueError):
        return False


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
    try:
        play_rec.start_recording(record)
    except Exception as e:  # noqa: BLE001 — recording must not fail play
        log.warning("ncm play record start failed: %s", e)
    return str(payload.get("message") or "").strip() or f"已唤起云音乐播放歌曲 {original}"


def queue_clear() -> None:
    payload = _run_ncm(["queue", "clear"], timeout_sec=CONTROL_TIMEOUT_SEC)
    if payload.get("success") is not True:
        msg = str(payload.get("message") or "").strip()
        raise NeteaseMusicError(msg or "网易云清空队列失败")


def queue_add(record: dict[str, Any], *, next_: bool = False) -> None:
    encrypted = str(record.get("id") or "").strip()
    original = record.get("originalId")
    if not encrypted or original in (None, ""):
        raise NeteaseMusicError("队列追加缺少 encrypted-id / original-id")
    argv = [
        "queue",
        "add",
        "--encrypted-id",
        encrypted,
        "--original-id",
        str(original),
    ]
    if next_:
        argv.append("--next")
    payload = _run_ncm(argv, timeout_sec=CONTROL_TIMEOUT_SEC)
    if payload.get("success") is not True or _queue_add_is_noop(payload):
        msg = str(payload.get("message") or "").strip()
        raise NeteaseMusicError(msg or "网易云队列追加失败")


def _now_playing_meta_path() -> Path:
    return ncm_data_dir() / NOW_PLAYING_META_FILE


def _load_now_playing_playlist() -> tuple[str, str] | None:
    path = _now_playing_meta_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    enc = str(raw.get("id") or "").strip()
    oid = raw.get("originalId")
    if not enc or oid in (None, ""):
        return None
    return enc, str(oid)


def _save_now_playing_playlist(*, encrypted_id: str, original_id: str) -> None:
    path = _now_playing_meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"id": encrypted_id, "originalId": original_id, "name": NOW_PLAYING_PLAYLIST_NAME},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def ensure_now_playing_playlist() -> tuple[str, str]:
    """Return (encrypted_id, original_id) for the reusable now-playing playlist."""
    cached = _load_now_playing_playlist()
    if cached:
        return cached
    payload = _run_ncm(
        ["playlist", "create", "--playlistName", NOW_PLAYING_PLAYLIST_NAME],
        timeout_sec=SEARCH_TIMEOUT_SEC,
    )
    if not _api_ok(payload):
        msg = str(payload.get("message") or "").strip()
        raise NeteaseMusicError(msg or "创建连播歌单失败")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    enc = str((data or {}).get("id") or "").strip()
    oid = (data or {}).get("originalId")
    if not enc or oid in (None, ""):
        raise NeteaseMusicError("创建连播歌单未返回 id")
    _save_now_playing_playlist(encrypted_id=enc, original_id=str(oid))
    return enc, str(oid)


def _playlist_track_encrypted_ids(playlist_encrypted_id: str) -> list[str]:
    payload = _run_ncm(
        [
            "playlist",
            "tracks",
            "--playlistId",
            playlist_encrypted_id,
            "--limit",
            "500",
            "--offset",
            "0",
        ],
        timeout_sec=SEARCH_TIMEOUT_SEC,
    )
    if not _api_ok(payload):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for rec in data:
        if not isinstance(rec, dict):
            continue
        enc = str(rec.get("id") or "").strip()
        if enc:
            out.append(enc)
    return out


def replace_playlist_tracks(
    *,
    playlist_encrypted_id: str,
    records: list[dict[str, Any]],
) -> list[str]:
    """Replace cloud playlist contents with ``records``. Returns encrypted song ids."""
    song_ids: list[str] = []
    for rec in records:
        enc = str(rec.get("id") or "").strip()
        if enc:
            song_ids.append(enc)
    if not song_ids:
        raise NeteaseMusicError("连播列表缺少 encrypted-id")
    existing = _playlist_track_encrypted_ids(playlist_encrypted_id)
    if existing:
        payload = _run_ncm(
            [
                "playlist",
                "remove",
                "--playlistId",
                playlist_encrypted_id,
                "--songIdList",
                json.dumps(existing, ensure_ascii=False),
            ],
            timeout_sec=SEARCH_TIMEOUT_SEC,
        )
        if not _api_ok(payload):
            msg = str(payload.get("message") or "").strip()
            log.warning("playlist remove old tracks: %s", msg or payload)
    payload = _run_ncm(
        [
            "playlist",
            "add",
            "--playlistId",
            playlist_encrypted_id,
            "--songIdList",
            json.dumps(song_ids, ensure_ascii=False),
        ],
        timeout_sec=SEARCH_TIMEOUT_SEC,
    )
    if not _api_ok(payload):
        msg = str(payload.get("message") or "").strip()
        raise NeteaseMusicError(msg or "写入连播歌单失败")
    return song_ids


def play_playlist(*, encrypted_id: str, original_id: str) -> str:
    payload = _run_ncm(
        [
            "play",
            "--playlist",
            "--encrypted-id",
            encrypted_id,
            "--original-id",
            str(original_id),
        ],
        timeout_sec=PLAY_TIMEOUT_SEC,
        allow_orpheus_only=True,
    )
    if payload.get("success") is not True and not _api_ok(payload):
        msg = str(payload.get("message") or "").strip()
        raise NeteaseMusicError(msg or "网易云歌单播放失败")
    if payload.get("orpheus"):
        return f"已唤起云音乐播放歌单 {original_id}"
    return (
        str(payload.get("message") or "").strip()
        or f"已唤起云音乐播放歌单 {original_id}"
    )


def _record_matches_artist(record: dict[str, Any], artist: str) -> bool:
    singer = str(artist or "").strip()
    if not singer:
        return False
    return any(_names_equal(name, singer) for name in _artist_names(record))


def filter_records_by_artist(
    records: list[Any],
    *,
    artist: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in records:
        if isinstance(rec, dict) and _record_matches_artist(rec, artist):
            out.append(rec)
    return out


def collect_artist_queue_records(
    *,
    artist: str,
    user_input: str | None = None,
    limit: int = ARTIST_QUEUE_MAX,
) -> list[dict[str, Any]]:
    """Up to ``limit`` songs whose primary artist matches ``artist``.

    Searches with keyword=artist only (ignores utterance ``user_input`` so
    phrases like 「播放刘德华的歌」 do not skew ncm-cli ``--userInput``).
    Pages until filled or search exhausted.
    """
    del user_input  # kept for call-site compat; must not bias artist search
    singer = str(artist or "").strip()
    if not singer:
        raise NeteaseMusicError(NO_SONG_MSG)
    want = max(1, min(int(limit), ARTIST_QUEUE_MAX))
    init_db()
    collected: list[dict[str, Any]] = []
    seen: set[Any] = set()
    indexed = find_index_by_name_artist(name="", artist=singer, limit=want)
    for row in indexed:
        rec = _record_from_index(row)
        if rec is None or not _record_matches_artist(rec, singer):
            continue
        oid = rec.get("originalId")
        if oid in seen:
            continue
        seen.add(oid)
        collected.append(rec)
        if len(collected) >= want:
            return collected
    offset = 0
    page = CACHE_PAGE
    while len(collected) < want:
        batch = search_records(
            keyword=singer,
            user_input=None,
            limit=page,
            offset=offset,
        )
        if not batch:
            break
        before = len(collected)
        for rec in filter_records_by_artist(batch, artist=singer):
            oid = rec.get("originalId")
            if oid in seen:
                continue
            seen.add(oid)
            collected.append(rec)
            if len(collected) >= want:
                break
        if len(collected) >= want:
            break
        if len(batch) < page or len(collected) == before:
            break
        offset += page
    if not collected:
        raise NeteaseMusicError(f"网易云未找到歌手「{singer}」的歌")
    return collected[:want]


def play_artist_queue(records: list[dict[str, Any]]) -> tuple[str, int]:
    """Play continuous list via cloud playlist (orpheus-safe).

    Desktop ``queue add`` is unreliable under player=orpheus (fake success).
    Multi-track: replace reusable playlist → ``play --playlist``.
    Single track: ``play --song`` (same as title play).
    """
    if not records:
        raise NeteaseMusicError("歌手连播列表为空")
    if len(records) == 1:
        try:
            queue_clear()
        except NeteaseMusicError as e:
            log.info("queue clear before single play skipped: %s", e)
        return play_record(records[0]), 0

    pl_enc, pl_oid = ensure_now_playing_playlist()
    song_ids = replace_playlist_tracks(
        playlist_encrypted_id=pl_enc,
        records=records,
    )
    msg = play_playlist(encrypted_id=pl_enc, original_id=pl_oid)
    added = max(0, len(song_ids) - 1)
    try:
        play_rec.start_playlist_session(records)
    except Exception as e:  # noqa: BLE001 — recording must not fail play
        log.warning("ncm playlist record start failed: %s", e)
    log.info(
        "ncm artist playlist play id=%s songs=%s",
        pl_oid,
        len(song_ids),
    )
    return msg, added


def is_artist_queue_mode(
    *,
    song: str,
    artist: str,
    playlist_artist: str,
) -> bool:
    if playlist_artist:
        return True
    return not str(song or "").strip() and bool(str(artist or "").strip())


def try_resume() -> str | None:
    """Return resume message on success; None when nothing to continue."""
    try:
        payload = _run_ncm(["resume"], timeout_sec=CONTROL_TIMEOUT_SEC)
    except NeteaseMusicError as e:
        log.info("music.play bare: resume skipped: %s", e)
        return None
    if payload.get("success") is not True:
        log.info(
            "music.play bare: resume not active: %s",
            payload.get("message"),
        )
        return None
    return str(payload.get("message") or "").strip() or "已继续播放"


def fetch_daily_recommend(
    *,
    limit: int = DAILY_RECOMMEND_LIMIT,
) -> list[dict[str, Any]]:
    """Daily songs from ``ncm-cli recommend daily`` (same id fields as search)."""
    want = max(1, min(int(limit), ARTIST_QUEUE_MAX))
    payload = _run_ncm(
        ["recommend", "daily", "--limit", str(want)],
        timeout_sec=SEARCH_TIMEOUT_SEC,
    )
    code = payload.get("code")
    if code not in (200, None, "200"):
        try:
            if int(code) != 200:
                msg = str(payload.get("message") or "").strip()
                raise NeteaseMusicError(msg or f"每日推荐失败 code={code}")
        except (TypeError, ValueError):
            msg = str(payload.get("message") or "").strip()
            raise NeteaseMusicError(msg or f"每日推荐失败 code={code}") from None
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise NeteaseMusicError("每日推荐为空")
    records: list[dict[str, Any]] = []
    for rec in data:
        if not isinstance(rec, dict):
            continue
        encrypted = str(rec.get("id") or "").strip()
        original = rec.get("originalId")
        if not encrypted or original in (None, ""):
            continue
        records.append(rec)
        if len(records) >= want:
            break
    if not records:
        raise NeteaseMusicError("每日推荐缺少可用歌曲")
    return records


def play_daily_recommend_queue(
    params: dict[str, Any] | None = None,
    *,
    trigger_text: str = "每日推荐",
    resume_ms: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Clear queue and play daily recommend. Used by bare play and resume fallback."""
    t0 = time.perf_counter()
    intent_id = _str_param(params, "intent_id") or "-"
    t_search = time.perf_counter()
    try:
        queue_records = fetch_daily_recommend(limit=DAILY_RECOMMEND_LIMIT)
    except NeteaseMusicError as e:
        log.info("daily recommend failed: %s", e)
        raise NeteaseMusicError(BARE_PLAY_FAIL_MSG) from e
    search_ms = int(round((time.perf_counter() - t_search) * 1000))
    t_play = time.perf_counter()
    msg, queue_added = play_artist_queue(queue_records)
    play_ms = int(round((time.perf_counter() - t_play) * 1000))
    record = queue_records[0]
    try:
        oid = upsert_record(record)
        record_play(
            oid,
            str(_str_param(params, "participant_id") or "").strip(),
            intent_id=_str_param(params, "intent_id") or None,
        )
        for extra in queue_records[1:]:
            try:
                upsert_record(extra)
            except NcmSongsError as e:
                log.warning("ncm_songs skip daily queue hit: %s", e)
    except NcmSongsError as e:
        log.warning("ncm_songs record_play failed: %s", e)
    enter_music_mode(trigger_text=trigger_text)
    total_ms = int(round((time.perf_counter() - t0) * 1000)) + int(resume_ms)
    log.info(
        "music daily intent=%s trigger=%s resume_ms=%s search_ms=%s "
        "play_ms=%s total_ms=%s queue=%s",
        intent_id,
        trigger_text,
        resume_ms,
        search_ms,
        play_ms,
        total_ms,
        len(queue_records),
    )
    return msg, {
        "bare_mode": "daily",
        "queue_count": len(queue_records),
        "queue_added": queue_added,
        "timing": {
            "resume": resume_ms,
            "search": search_ms,
            "play": play_ms,
            "total": total_ms,
        },
    }


def play_bare_default(
    params: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Empty song/artist: resume if possible, else daily-recommend queue."""
    t0 = time.perf_counter()
    intent_id = _str_param(params, "intent_id") or "-"
    t_resume = time.perf_counter()
    resumed = try_resume()
    resume_ms = int(round((time.perf_counter() - t_resume) * 1000))
    if resumed is not None:
        enter_music_mode(trigger_text="播放音乐")
        total_ms = int(round((time.perf_counter() - t0) * 1000))
        log.info(
            "music.play bare intent=%s mode=resume resume_ms=%s total_ms=%s",
            intent_id,
            resume_ms,
            total_ms,
        )
        return resumed, {
            "bare_mode": "resume",
            "timing": {"resume": resume_ms, "total": total_ms},
        }
    return play_daily_recommend_queue(
        params,
        trigger_text="每日推荐",
        resume_ms=resume_ms,
    )


def _is_empty_queue_error(exc: BaseException) -> bool:
    msg = str(exc or "")
    return "播放列表为空" in msg or "请先使用 play" in msg


def resume_from_params(
    params: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Continue playback; empty queue → daily recommend."""
    t0 = time.perf_counter()
    try:
        msg = _control("music.resume")
    except NeteaseMusicError as e:
        if not _is_empty_queue_error(e):
            raise
        log.info("music.resume empty queue → daily recommend: %s", e)
        resume_ms = int(round((time.perf_counter() - t0) * 1000))
        _msg, outputs = play_daily_recommend_queue(
            params,
            trigger_text="继续播放·每日推荐",
            resume_ms=resume_ms,
        )
        outputs = dict(outputs)
        outputs["resume_fallback"] = "daily"
        return "无可继续，已改播每日推荐", outputs
    enter_music_mode(trigger_text="继续播放")
    return msg or "已继续播放", {}


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
    raw = params if isinstance(params, dict) else {}
    song = str(_str_param(params, "song") or "").strip().rstrip(_TRAILING_PUNCT).strip()
    artist = str(_str_param(params, "artist") or "").strip().rstrip(_TRAILING_PUNCT).strip()
    user_input = _str_param(params, "user_input")
    intent_id = _str_param(params, "intent_id") or "-"
    song, qty_from_song = strip_leading_quantity(song)
    if not song and not artist:
        return play_bare_default(params)
    playlist_artist = artist_from_playlist_remainder(song)
    artist_queue = is_artist_queue_mode(
        song=song,
        artist=artist,
        playlist_artist=playlist_artist,
    )
    queue_artist = playlist_artist or artist
    queue_limit = ARTIST_QUEUE_MAX
    if artist_queue:
        if raw.get("count") not in (None, ""):
            queue_limit = clamp_play_queue_count(raw.get("count"))
        elif qty_from_song is not None:
            queue_limit = clamp_play_queue_count(qty_from_song)
    t_cache = time.perf_counter()
    if artist_queue:
        cached = None
    elif playlist_artist:
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
    queue_added = 0
    if artist_queue:
        t_search = time.perf_counter()
        queue_records = collect_artist_queue_records(
            artist=queue_artist,
            user_input=user_input or None,
            limit=queue_limit,
        )
        search_ms = int(round((time.perf_counter() - t_search) * 1000))
        cache_label = "artist-queue"
        record = queue_records[0]
    elif cached:
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
    if artist_queue:
        msg, queue_added = play_artist_queue(queue_records)
    else:
        msg = play_record(record)
    play_ms = int(round((time.perf_counter() - t_play) * 1000))
    try:
        oid = upsert_record(record)
        record_play(
            oid,
            str(_str_param(params, "participant_id") or "").strip(),
            intent_id=_str_param(params, "intent_id") or None,
        )
        if artist_queue:
            for extra in queue_records[1:]:
                try:
                    upsert_record(extra)
                except NcmSongsError as e:
                    log.warning("ncm_songs skip queue hit: %s", e)
    except NcmSongsError as e:
        log.warning("ncm_songs record_play failed: %s", e)
    enter_music_mode(trigger_text=f"{song} {artist}".strip())
    total_ms = int(round((time.perf_counter() - t0) * 1000))
    timing = {
        "cache": cache_ms,
        "search": search_ms,
        "play": play_ms,
        "total": total_ms,
    }
    outputs: dict[str, Any] = {"timing": timing}
    if artist_queue:
        outputs["queue_count"] = len(queue_records)
        outputs["queue_added"] = queue_added
    log.info(
        "music.play intent=%s cache_ms=%s search_ms=%s play_ms=%s total_ms=%s cache=%s%s",
        intent_id,
        cache_ms,
        search_ms,
        play_ms,
        total_ms,
        cache_label,
        f" queue={len(queue_records)}" if artist_queue else "",
    )
    return msg, outputs


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
    if cap == "music.resume":
        return resume_from_params(params)
    msg = _control(cap)
    try:
        if cap == "music.stop":
            play_rec.stop_recording(clear_playlist=True)
            exit_music_mode(reason="music.stop")
        elif cap == "music.pause":
            play_rec.stop_recording(clear_playlist=True)
        elif cap == "music.next":
            play_rec.on_next()
        elif cap == "music.previous":
            play_rec.on_previous()
    except Exception as e:  # noqa: BLE001 — recording must not fail transport
        log.warning("ncm play record control hook failed cap=%s: %s", cap, e)
        if cap == "music.stop":
            exit_music_mode(reason="music.stop")
    return msg, {}


dispatch = run_from_params
