"""Mac Edge: netease.music via ncm-cli (desktop 网易云 App / orpheus).

LLM extracts song/artist. This plugin only assembles ncm-cli argv and
reads/writes ``mac_edge.ncm_songs``. Keyword is one argv value.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from mac_edge.capability_availability import Availability
from mac_edge.music_linkage import enter as enter_music_mode
from mac_edge.music_linkage import exit_mode as exit_music_mode
from mac_edge.ncm_songs import (
    NcmSongsError,
    find_by_name_artist,
    init_db,
    mark_played,
    upsert_record,
)

log = logging.getLogger("mac_edge.netease_music")

SEARCH_TIMEOUT_SEC = 30.0
PLAY_TIMEOUT_SEC = 20.0
CONTROL_TIMEOUT_SEC = 15.0

NO_SONG_MSG = "目前只支持按歌曲播放，请说出歌名"

_MUSIC_CAPS = frozenset(
    {
        "music.play",
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


def _cached_record(*, song: str, artist: str) -> dict[str, Any] | None:
    init_db()
    hits = find_by_name_artist(name=song, artist=artist, limit=5)
    if not hits:
        return None
    rec = hits[0].get("record")
    return rec if isinstance(rec, dict) else None


def _unknown_user_input_flag(err: Exception) -> bool:
    msg = str(err or "").lower()
    return (
        "unknown option" in msg
        or "unknown argument" in msg
        or "unexpected argument" in msg
        or "未识别" in msg
        or "未返回 json" in msg
    )


def search_record(
    *,
    song: str,
    artist: str | None = None,
    user_input: str | None = None,
) -> dict[str, Any]:
    keyword = search_keyword(song=song, artist=artist)
    argv = ["search", "song"]
    used_user_input = bool(str(user_input or "").strip())
    if used_user_input:
        argv.extend(["--userInput", str(user_input).strip()])
    argv.extend(["--keyword", keyword, "--limit", "1"])
    try:
        payload = _run_ncm(argv, timeout_sec=SEARCH_TIMEOUT_SEC)
    except NeteaseMusicError as e:
        if used_user_input and _unknown_user_input_flag(e):
            log.info("ncm-cli --userInput unsupported; retry keyword only")
            payload = _run_ncm(
                ["search", "song", "--keyword", keyword, "--limit", "1"],
                timeout_sec=SEARCH_TIMEOUT_SEC,
            )
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
    if not records:
        label = f"「{song} - {artist}」" if artist else f"「{song}」"
        raise NeteaseMusicError(f"网易云未找到歌曲{label}")
    first = records[0]
    if not isinstance(first, dict):
        raise NeteaseMusicError("网易云搜索结果无效")
    return first


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
    song = _str_param(params, "song")
    artist = _str_param(params, "artist")
    user_input = _str_param(params, "user_input")
    intent_id = _str_param(params, "intent_id") or "-"
    if not song:
        raise NeteaseMusicError(NO_SONG_MSG)
    t_cache = time.perf_counter()
    cached = _cached_record(song=song, artist=artist)
    cache_ms = int(round((time.perf_counter() - t_cache) * 1000))
    search_ms = 0
    if cached:
        log.info("ncm_songs hit name=%s artist=%s", song, artist or "-")
        record = cached
        cache_label = "hit"
    else:
        t_search = time.perf_counter()
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
        log.warning("ncm_songs write failed: %s", e)
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


def run_from_params(
    capability_id: str,
    params: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    cap = str(capability_id or "").strip()
    if cap not in _MUSIC_CAPS:
        raise NeteaseMusicError(f"unsupported capability {cap}")
    if cap == "music.play":
        return play_from_params(params)
    msg = _control(cap)
    if cap == "music.stop":
        exit_music_mode(reason="music.stop")
    return msg, {}


dispatch = run_from_params
