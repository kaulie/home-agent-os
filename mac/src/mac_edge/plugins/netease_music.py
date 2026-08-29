"""Mac Edge netease.music via ncm-cli + local ``ncm_songs`` catalog.

Contract: search/play use ncm-cli; catalog reads/writes only through
``mac_edge.ncm_songs``. Does not touch Brain SQLite.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any

from mac_edge.config import Config
from mac_edge.music_linkage import enter as music_mode_enter
from mac_edge.ncm_songs import (
    NcmSongsError,
    find_by_name_artist,
    get_song,
    init_db,
    mark_played,
    upsert_record,
)
from mac_edge.capability_availability import Availability

log = logging.getLogger("mac_edge.netease_music")

_DEFAULT_TIMEOUT_SEC = 90.0
_TRANSPORT_TIMEOUT_SEC = 30.0


class NeteaseMusicError(Exception):
    pass


def _ncm_bin() -> str:
    raw = (os.environ.get("MAC_EDGE_NCM_CLI") or os.environ.get("NCM_CLI") or "").strip()
    if raw:
        return raw
    found = shutil.which("ncm-cli")
    if not found:
        raise NeteaseMusicError("ncm-cli not found (install or set MAC_EDGE_NCM_CLI)")
    return found


def netease_configured() -> bool:
    try:
        _ncm_bin()
        return True
    except NeteaseMusicError:
        return False


def is_available(_config: Config | None = None) -> Availability:
    if netease_configured():
        return Availability.available("ncm-cli")
    return Availability.unavailable("ncm-cli not installed (brew install ncm-cli)")


def _param_str(params: dict[str, Any], key: str) -> str:
    raw = params.get(key)
    if raw is None:
        return ""
    return str(raw).strip()


def _run_ncm(
    args: list[str],
    *,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    cmd = [_ncm_bin(), *args, "--output", "json"]
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
        raise NeteaseMusicError(f"ncm-cli timeout after {timeout_sec}s: {args[0]}") from e
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        detail = stderr or stdout or f"exit {proc.returncode}"
        raise NeteaseMusicError(f"ncm-cli failed: {detail}")
    if not stdout:
        raise NeteaseMusicError("ncm-cli returned empty output")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise NeteaseMusicError(f"ncm-cli invalid JSON: {stdout[:240]}") from e
    if not isinstance(data, dict):
        raise NeteaseMusicError("ncm-cli JSON must be an object")
    if data.get("success") is False:
        msg = str(data.get("message") or data.get("error") or "ncm-cli error")
        raise NeteaseMusicError(msg)
    code = data.get("code")
    if code is not None and int(code) != 200:
        msg = str(data.get("message") or f"ncm-cli code={code}")
        raise NeteaseMusicError(msg)
    return data


def _songs_from_search_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    songs = data.get("songs")
    if not isinstance(songs, list):
        return []
    out: list[dict[str, Any]] = []
    for item in songs:
        if isinstance(item, dict):
            out.append(item)
    return out


def _search_songs(keyword: str, *, limit: int = 10) -> list[dict[str, Any]]:
    key = str(keyword or "").strip()
    if not key:
        return []
    payload = _run_ncm(
        ["search", "song", "--keyword", key, "--limit", str(max(1, int(limit)))],
    )
    return _songs_from_search_payload(payload)


def _artist_names(record: dict[str, Any]) -> str:
    artists = record.get("artists") or record.get("fullArtists") or []
    if not isinstance(artists, list):
        return ""
    names: list[str] = []
    for item in artists:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            names.append(name)
    return " / ".join(names)


def _pick_best(
    hits: list[dict[str, Any]],
    *,
    song: str = "",
    artist: str = "",
) -> dict[str, Any] | None:
    if not hits:
        return None
    song_key = song.strip().casefold()
    artist_key = artist.strip().casefold()
    if song_key and artist_key:
        for hit in hits:
            name = str(hit.get("name") or "").strip().casefold()
            artists = _artist_names(hit).casefold()
            if song_key in name or name in song_key:
                if artist_key in artists:
                    return hit
        for hit in hits:
            name = str(hit.get("name") or "").strip().casefold()
            artists = _artist_names(hit).casefold()
            if song_key in name or name in song_key:
                return hit
    if song_key:
        for hit in hits:
            name = str(hit.get("name") or "").strip().casefold()
            if song_key in name or name in song_key:
                return hit
    if artist_key:
        for hit in hits:
            artists = _artist_names(hit).casefold()
            if artist_key in artists:
                return hit
    return hits[0]


def _resolve_from_catalog(
    *,
    song: str,
    artist: str,
) -> dict[str, Any] | None:
    if song and artist:
        rows = find_by_name_artist(name=song, artist=artist, limit=5)
        if rows:
            return rows[0]
    if song:
        rows = find_by_name_artist(name=song, limit=5)
        if rows:
            if artist:
                artist_key = artist.casefold()
                for row in rows:
                    if artist_key in str(row.get("artist") or "").casefold():
                        return row
            return rows[0]
    if artist and not song:
        rows = find_by_name_artist(artist=artist, limit=5)
        if rows:
            return rows[0]
    return None


def _catalog_row_ids(row: dict[str, Any]) -> tuple[str, str]:
    enc = str(row.get("encrypted_id") or "").strip()
    oid = row.get("original_id")
    if not enc or oid is None:
        record = row.get("record")
        if isinstance(record, dict):
            enc = str(record.get("id") or record.get("encryptedId") or enc).strip()
            oid = record.get("originalId") or record.get("original_id") or oid
    if not enc or oid is None:
        raise NeteaseMusicError("catalog row missing encrypted_id/original_id")
    return enc, str(int(oid))


def _play_ids(encrypted_id: str, original_id: str) -> str:
    payload = _run_ncm(
        [
            "play",
            "--song",
            "--encrypted-id",
            encrypted_id,
            "--original-id",
            original_id,
        ],
    )
    msg = str(payload.get("message") or "playing")
    return msg


def _play_row(row: dict[str, Any], *, label: str) -> tuple[str, dict[str, Any]]:
    enc, oid = _catalog_row_ids(row)
    play_msg = _play_ids(enc, oid)
    mark_played(int(oid))
    music_mode_enter(trigger_text=label)
    outputs = {
        "song": str(row.get("name") or ""),
        "artist": str(row.get("artist") or ""),
        "original_id": int(oid),
    }
    return f"music.play {label}: {play_msg}", outputs


def _play_hit(hit: dict[str, Any], *, label: str) -> tuple[str, dict[str, Any]]:
    init_db()
    oid = upsert_record(hit)
    row = get_song(oid)
    if row is None:
        raise NeteaseMusicError(f"catalog upsert failed for original_id={oid}")
    return _play_row(row, label=label)


def _search_keyword(song: str, artist: str, album: str) -> str:
    if song:
        return f"{song} {artist}".strip() if artist else song
    if album:
        return f"{album} {artist}".strip() if artist else album
    return artist


def play_from_params(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    song = _param_str(params, "song")
    artist = _param_str(params, "artist")
    album = _param_str(params, "album")
    if not song and not artist and not album:
        raise NeteaseMusicError(
            "music.play requires song, artist, or album",
        )
    init_db()
    label = ""
    if song:
        label = f"「{song}」" if not artist else f"「{song} - {artist}」"
    elif album:
        label = f"专辑「{album}」"
    else:
        label = f"歌手「{artist}」"

    cached = _resolve_from_catalog(song=song, artist=artist)
    if cached is not None:
        return _play_row(cached, label=label)

    keyword = _search_keyword(song, artist, album)
    hits = _search_songs(keyword)
    if not hits:
        raise NeteaseMusicError(f"未搜到歌曲: {keyword}")
    for hit in hits:
        upsert_record(hit)
    best = _pick_best(hits, song=song, artist=artist)
    if best is None:
        raise NeteaseMusicError(f"未搜到歌曲: {keyword}")
    return _play_hit(best, label=label)


def _transport(command: str) -> str:
    payload = _run_ncm([command], timeout_sec=_TRANSPORT_TIMEOUT_SEC)
    return str(payload.get("message") or command)


def pause_from_params(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    del params
    return f"music.pause: {_transport('pause')}", {}


def resume_from_params(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    del params
    return f"music.resume: {_transport('resume')}", {}


def stop_from_params(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    del params
    return f"music.stop: {_transport('stop')}", {}


def next_from_params(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    del params
    return f"music.next: {_transport('next')}", {}


def previous_from_params(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    del params
    return f"music.previous: {_transport('prev')}", {}


def dispatch(capability_id: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    cap = str(capability_id or "").strip()
    if cap == "music.play":
        return play_from_params(params)
    if cap == "music.pause":
        return pause_from_params(params)
    if cap == "music.resume":
        return resume_from_params(params)
    if cap == "music.stop":
        return stop_from_params(params)
    if cap == "music.next":
        return next_from_params(params)
    if cap == "music.previous":
        return previous_from_params(params)
    raise NeteaseMusicError(f"unsupported capability: {cap}")


def run_from_params(
    capability_id: str,
    params: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    return dispatch(capability_id, params)


ncm_cli_configured = netease_configured
