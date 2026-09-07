"""Mac Edge SQLite catalog for ncm-cli search records.

Database file: ``{MAC_EDGE_DATA_DIR or mac/data}/ncm_songs.sqlite3``
Not Brain ``brain.sqlite3``. Contract: ``docs/mac-ncm-songs-db.md``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("mac_edge.ncm_songs")

_SQL_DIR = Path(__file__).resolve().parents[3] / "sql"

_lock = threading.RLock()
_connection: sqlite3.Connection | None = None
_path_override: Path | None = None


class NcmSongsError(Exception):
    pass


def _project_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def data_dir() -> Path:
    raw = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _project_data_dir()


def db_path() -> Path:
    if _path_override is not None:
        return _path_override
    return data_dir() / "ncm_songs.sqlite3"


def connect() -> sqlite3.Connection:
    """Open (or reuse) the catalog connection after ``init_db()``."""
    return _connect()


def reset(*, path: Path | None = None) -> None:
    """Close connection (tests). Next call reopens."""
    global _connection, _path_override
    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None
        _path_override = path.resolve() if path is not None else None


def normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def _now() -> float:
    return time.time()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)


def _connect() -> sqlite3.Connection:
    global _connection
    if _connection is not None:
        return _connection
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    _connection = conn
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY,
          applied_at TEXT NOT NULL
        )
        """
    )
    applied = {int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations")}
    for sql_path in sorted(_SQL_DIR.glob("*.sql")):
        version = int(sql_path.name.split("_", 1)[0])
        if version in applied:
            continue
        conn.executescript(sql_path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )


def init_db() -> Path:
    with _lock:
        conn = _connect()
        _migrate(conn)
    return db_path()


def _song_name(record: dict[str, Any]) -> str:
    for key in ("name", "songName", "song_name", "title"):
        raw = record.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    raise NcmSongsError("search record missing name")


def _artist_name(record: dict[str, Any]) -> str:
    artists = record.get("artists")
    if isinstance(artists, list) and artists:
        first = artists[0]
        if isinstance(first, dict):
            return str(first.get("name") or "").strip()
        return str(first or "").strip()
    return ""


def _original_id(record: dict[str, Any]) -> int:
    raw = record.get("originalId")
    if raw is None:
        raw = record.get("original_id")
    if raw is None:
        raise NcmSongsError("search record missing originalId")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise NcmSongsError(f"invalid originalId: {raw!r}") from exc


def _encrypted_id(record: dict[str, Any]) -> str:
    raw = record.get("id")
    if raw is None or not str(raw).strip():
        raise NcmSongsError("search record missing id")
    return str(raw).strip()


def _row_int(row: sqlite3.Row, key: str) -> int | None:
    if key not in row.keys() or row[key] is None:
        return None
    try:
        return int(row[key])
    except (TypeError, ValueError):
        return None


def _optional_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _optional_text(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _duration_ms(record: dict[str, Any]) -> int | None:
    """ncm-cli search records store duration in milliseconds."""
    for key in ("duration", "durationMs", "duration_ms"):
        if key in record:
            return _optional_int(record.get(key))
    return None


def _album_fields(record: dict[str, Any]) -> tuple[int | None, str | None, str | None]:
    """Map album originalId / name / encrypted id. Missing → NULL, never invent."""
    album = record.get("album")
    if isinstance(album, dict):
        oid = album.get("originalId")
        if oid is None:
            oid = album.get("original_id")
        name = album.get("name") or album.get("album_name")
        enc = album.get("id") or album.get("encrypted_id") or album.get("encryptedId")
        return _optional_int(oid), _optional_text(name), _optional_text(enc)
    if isinstance(album, str) and album.strip():
        return None, album.strip(), None
    oid = record.get("album_original_id") or record.get("albumId") or record.get("albumOriginalId")
    name = record.get("album_name") or record.get("albumName")
    enc = record.get("album_encrypted_id") or record.get("albumEncryptedId")
    return _optional_int(oid), _optional_text(name), _optional_text(enc)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    record = _loads(row["record_json"])
    if not isinstance(record, dict):
        record = {}
    return {
        "id": _row_int(row, "id"),
        "original_id": int(row["original_id"]),
        "encrypted_id": str(row["encrypted_id"]),
        "name": str(row["name"]),
        "name_norm": str(row["name_norm"]),
        "artist": str(row["artist"] or ""),
        "artist_norm": str(row["artist_norm"] or ""),
        "record": record,
        "record_json": str(row["record_json"]),
        "played_at": row["played_at"],
        "create_time": row["create_time"] if "create_time" in row.keys() else None,
        "update_time": row["update_time"] if "update_time" in row.keys() else None,
    }


def _index_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    duration = row["duration"]
    album_oid = row["album_original_id"]
    return {
        "id": _row_int(row, "id"),
        "song_original_id": int(row["song_original_id"]),
        "song_name": str(row["song_name"]),
        "song_name_norm": str(row["song_name_norm"]),
        "song_encrypted_id": _optional_text(row["song_encrypted_id"]),
        "duration": int(duration) if duration is not None else None,
        "artist": str(row["artist"] or ""),
        "artist_norm": str(row["artist_norm"] or ""),
        "album_original_id": int(album_oid) if album_oid is not None else None,
        "album_name": _optional_text(row["album_name"]),
        "album_encrypted_id": _optional_text(row["album_encrypted_id"]),
        "create_time": row["create_time"] if "create_time" in row.keys() else None,
        "update_time": row["update_time"] if "update_time" in row.keys() else None,
    }


def _index_as_song_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Minimal ncm_songs-shaped row when backup table has no match."""
    idx = _index_row_to_dict(row)
    record: dict[str, Any] = {
        "originalId": idx["song_original_id"],
        "id": idx["song_encrypted_id"] or "",
        "name": idx["song_name"],
    }
    if idx["artist"]:
        record["artists"] = [{"name": idx["artist"]}]
    if idx["duration"] is not None:
        record["duration"] = idx["duration"]
    album: dict[str, Any] = {}
    if idx["album_original_id"] is not None:
        album["originalId"] = idx["album_original_id"]
    if idx["album_encrypted_id"]:
        album["id"] = idx["album_encrypted_id"]
    if idx["album_name"]:
        album["name"] = idx["album_name"]
    if album:
        record["album"] = album
    return {
        "id": idx.get("id"),
        "original_id": idx["song_original_id"],
        "encrypted_id": idx["song_encrypted_id"] or "",
        "name": idx["song_name"],
        "name_norm": idx["song_name_norm"],
        "artist": idx["artist"],
        "artist_norm": idx["artist_norm"],
        "record": record,
        "record_json": _dumps(record),
        "played_at": None,
        "create_time": idx.get("create_time"),
        "update_time": idx.get("update_time"),
    }


def _upsert_index(
    conn: sqlite3.Connection,
    record: dict[str, Any],
    *,
    original_id: int,
    encrypted_id: str,
    name: str,
    artist: str,
    name_norm: str,
    artist_norm: str,
    now: float,
) -> None:
    duration = _duration_ms(record)
    album_oid, album_name, album_enc = _album_fields(record)
    conn.execute(
        """
        INSERT INTO ncm_song_index (
          song_original_id, song_name, song_name_norm, song_encrypted_id,
          duration, artist, artist_norm,
          album_original_id, album_name, album_encrypted_id,
          create_time, update_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(song_original_id) DO NOTHING
        """,
        (
            original_id,
            name,
            name_norm,
            encrypted_id or None,
            duration,
            artist or None,
            artist_norm,
            album_oid,
            album_name,
            album_enc,
            now,
            now,
        ),
    )


def upsert_record(
    record: dict[str, Any],
    *,
    played_at: float | None = None,
) -> int:
    """Insert by ``original_id``. Existing rows are left unchanged. Returns ``original_id``."""
    del played_at  # play history lives in ncm_plays; catalog is insert-only
    if not isinstance(record, dict) or not record:
        raise NcmSongsError("record must be a non-empty object")
    original_id = _original_id(record)
    encrypted_id = _encrypted_id(record)
    name = _song_name(record)
    artist = _artist_name(record)
    name_norm = normalize_text(name)
    artist_norm = normalize_text(artist)
    payload = _dumps(record)
    ts = _now()
    with _lock:
        init_db()
        conn = _connect()
        conn.execute(
            """
            INSERT INTO ncm_songs (
              original_id, encrypted_id, name, name_norm, artist, artist_norm,
              record_json, played_at, create_time, update_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(original_id) DO NOTHING
            """,
            (
                original_id,
                encrypted_id,
                name,
                name_norm,
                artist or None,
                artist_norm,
                payload,
                None,
                ts,
                ts,
            ),
        )
        _upsert_index(
            conn,
            record,
            original_id=original_id,
            encrypted_id=encrypted_id,
            name=name,
            artist=artist,
            name_norm=name_norm,
            artist_norm=artist_norm,
            now=ts,
        )
    return original_id


def get_song(original_id: int | str) -> dict[str, Any] | None:
    try:
        oid = int(original_id)
    except (TypeError, ValueError):
        return None
    with _lock:
        init_db()
        row = _connect().execute(
            "SELECT * FROM ncm_songs WHERE original_id = ?",
            (oid,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def _index_lookup_rows(
    conn: sqlite3.Connection,
    *,
    name_key: str,
    artist_key: str,
    limit: int,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[Any] = []
    if name_key:
        clauses.append("i.song_name_norm = ?")
        params.append(name_key)
    if artist_key:
        clauses.append("i.artist_norm = ?")
        params.append(artist_key)
    if not clauses:
        return []
    sql = (
        "SELECT i.* FROM ncm_song_index i "
        "LEFT JOIN ncm_songs s ON s.original_id = i.song_original_id "
        "WHERE "
        + " AND ".join(clauses)
        + " ORDER BY i.song_original_id DESC LIMIT ?"
    )
    params.append(limit)
    return list(conn.execute(sql, params).fetchall())


def find_by_norm(
    *,
    name_norm: str = "",
    artist_norm: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    name_key = normalize_text(name_norm)
    artist_key = normalize_text(artist_norm)
    if not name_key and not artist_key:
        return []
    cap = max(1, int(limit))
    with _lock:
        init_db()
        conn = _connect()
        index_rows = _index_lookup_rows(
            conn, name_key=name_key, artist_key=artist_key, limit=cap
        )
        if index_rows:
            result: list[dict[str, Any]] = []
            for idx_row in index_rows:
                oid = int(idx_row["song_original_id"])
                song = conn.execute(
                    "SELECT * FROM ncm_songs WHERE original_id = ?",
                    (oid,),
                ).fetchone()
                result.append(_row_to_dict(song) if song else _index_as_song_dict(idx_row))
            return result
        clauses: list[str] = []
        params: list[Any] = []
        if name_key:
            clauses.append("name_norm = ?")
            params.append(name_key)
        if artist_key:
            clauses.append("artist_norm = ?")
            params.append(artist_key)
        sql = (
            "SELECT * FROM ncm_songs WHERE "
            + " AND ".join(clauses)
            + " ORDER BY original_id DESC LIMIT ?"
        )
        params.append(cap)
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def find_by_name_artist(
    *,
    name: str = "",
    artist: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    return find_by_norm(
        name_norm=normalize_text(name),
        artist_norm=normalize_text(artist),
        limit=limit,
    )


def get_index_song(original_id: int | str) -> dict[str, Any] | None:
    try:
        oid = int(original_id)
    except (TypeError, ValueError):
        return None
    with _lock:
        init_db()
        row = _connect().execute(
            "SELECT * FROM ncm_song_index WHERE song_original_id = ?",
            (oid,),
        ).fetchone()
    return _index_row_to_dict(row) if row else None


def find_index_by_norm(
    *,
    name_norm: str = "",
    artist_norm: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    name_key = normalize_text(name_norm)
    artist_key = normalize_text(artist_norm)
    if not name_key and not artist_key:
        return []
    with _lock:
        init_db()
        rows = _index_lookup_rows(
            _connect(),
            name_key=name_key,
            artist_key=artist_key,
            limit=max(1, int(limit)),
        )
    return [_index_row_to_dict(row) for row in rows]


def find_index_by_name_artist(
    *,
    name: str = "",
    artist: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    return find_index_by_norm(
        name_norm=normalize_text(name),
        artist_norm=normalize_text(artist),
        limit=limit,
    )


def _play_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": _row_int(row, "id"),
        "song_original_id": int(row["song_original_id"]),
        "participant_id": str(row["participant_id"] or ""),
        "intent_id": str(row["intent_id"] or "").strip() or None,
        "played_at": row["played_at"],
    }


def record_play(
    original_id: int | str,
    participant_id: str,
    *,
    intent_id: str | int | None = None,
    at: float | None = None,
) -> int | None:
    """Append one music.play hit. Does not update catalog rows."""
    try:
        oid = int(original_id)
    except (TypeError, ValueError) as exc:
        raise NcmSongsError("original_id required") from exc
    pid = str(participant_id or "").strip()
    if not pid:
        log.warning("ncm_plays skip: participant_id required original_id=%s", oid)
        return None
    ts = _now() if at is None else float(at)
    iid = str(intent_id or "").strip() or None
    with _lock:
        init_db()
        cur = _connect().execute(
            """
            INSERT INTO ncm_plays (
              song_original_id, participant_id, intent_id, played_at
            ) VALUES (?, ?, ?, ?)
            """,
            (oid, pid, iid, ts),
        )
    return int(cur.lastrowid) if cur.lastrowid else None


def list_library(*, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    with _lock:
        init_db()
        rows = _connect().execute(
            """
            SELECT * FROM ncm_songs
            ORDER BY original_id DESC
            LIMIT ? OFFSET ?
            """,
            (max(1, int(limit)), max(0, int(offset))),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_recent_played(*, limit: int = 20) -> list[dict[str, Any]]:
    """Recent music.play hits (one row per intent play, newest first)."""
    with _lock:
        init_db()
        rows = _connect().execute(
            """
            SELECT p.id, p.song_original_id, p.participant_id, p.intent_id, p.played_at
            FROM ncm_plays p
            ORDER BY p.played_at DESC, p.id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    return [_play_row_to_dict(row) for row in rows]


# --- ncm_recordings (BlackHole capture catalog) ---

STATUS_RECORDING = "recording"
STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"


def _recording_file_path(row: sqlite3.Row | dict[str, Any]) -> Path:
    """Join stored directory ``path`` + ``filename`` (legacy full path still works)."""
    if isinstance(row, sqlite3.Row):
        directory = str(row["path"] or "")
        name = ""
        try:
            name = str(row["filename"] or "")
        except (KeyError, IndexError):
            name = ""
    else:
        directory = str(row.get("path") or "")
        name = str(row.get("filename") or "")
    if name:
        return Path(directory) / name
    return Path(directory)


def _recording_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    filename = ""
    try:
        filename = str(row["filename"] or "")
    except (KeyError, IndexError):
        filename = ""
    directory = str(row["path"] or "")
    full = _recording_file_path(row)
    return {
        "id": _row_int(row, "id"),
        "song_original_id": int(row["song_original_id"]),
        "song_encrypted_id": _optional_text(row["song_encrypted_id"]),
        "song_name": str(row["song_name"]),
        "song_name_norm": str(row["song_name_norm"]),
        "artist": str(row["artist"] or ""),
        "artist_norm": str(row["artist_norm"] or ""),
        "duration_ms": _row_int(row, "duration_ms"),
        "path": directory,
        "filename": filename,
        "file_path": str(full),
        "status": str(row["status"]),
        "create_time": row["create_time"],
        "update_time": row["update_time"],
    }


def _try_original_id(record: dict[str, Any]) -> int | None:
    try:
        return _original_id(record)
    except NcmSongsError:
        return None


def get_recording(song_original_id: int) -> dict[str, Any] | None:
    with _lock:
        init_db()
        row = _connect().execute(
            "SELECT * FROM ncm_recordings WHERE song_original_id = ?",
            (int(song_original_id),),
        ).fetchone()
    return _recording_row_to_dict(row) if row is not None else None


def recording_is_complete(song_original_id: int) -> bool:
    """True when status=complete and the mp3 file still exists."""
    row = get_recording(song_original_id)
    if not row or row.get("status") != STATUS_COMPLETE:
        return False
    path = Path(str(row.get("file_path") or ""))
    return path.is_file() and path.stat().st_size > 0


def upsert_recording_started(record: dict[str, Any], path: str | Path) -> int | None:
    """Insert/update a row as recording. Returns original_id or None if unkeyed.

    ``path`` is the full output file; stored as directory ``path`` + ``filename``.
    """
    oid = _try_original_id(record)
    if oid is None:
        return None
    name = _song_name(record)
    artist = _artist_name(record)
    try:
        enc = _encrypted_id(record)
    except NcmSongsError:
        enc = None
    duration = _duration_ms(record)
    now = _now()
    full = Path(path)
    dir_s = str(full.parent)
    file_s = full.name
    with _lock:
        init_db()
        _connect().execute(
            """
            INSERT INTO ncm_recordings (
              song_original_id, song_encrypted_id, song_name, song_name_norm,
              artist, artist_norm, duration_ms, path, filename, status,
              create_time, update_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(song_original_id) DO UPDATE SET
              song_encrypted_id = excluded.song_encrypted_id,
              song_name = excluded.song_name,
              song_name_norm = excluded.song_name_norm,
              artist = excluded.artist,
              artist_norm = excluded.artist_norm,
              duration_ms = excluded.duration_ms,
              path = excluded.path,
              filename = excluded.filename,
              status = excluded.status,
              update_time = excluded.update_time
            """,
            (
                oid,
                enc,
                name,
                normalize_text(name),
                artist or None,
                normalize_text(artist),
                duration,
                dir_s,
                file_s,
                STATUS_RECORDING,
                now,
                now,
            ),
        )
    return oid


def mark_recording_status(song_original_id: int, status: str) -> None:
    if status not in (STATUS_RECORDING, STATUS_COMPLETE, STATUS_INCOMPLETE):
        raise NcmSongsError(f"invalid recording status: {status!r}")
    with _lock:
        init_db()
        _connect().execute(
            """
            UPDATE ncm_recordings
            SET status = ?, update_time = ?
            WHERE song_original_id = ?
            """,
            (status, _now(), int(song_original_id)),
        )


def mark_recording_complete(song_original_id: int) -> None:
    mark_recording_status(song_original_id, STATUS_COMPLETE)


def mark_recording_incomplete(song_original_id: int) -> None:
    mark_recording_status(song_original_id, STATUS_INCOMPLETE)


def abandon_stale_recordings() -> int:
    """Mark leftover ``recording`` rows as incomplete (Edge crash / orphan)."""
    with _lock:
        init_db()
        cur = _connect().execute(
            """
            UPDATE ncm_recordings
            SET status = ?, update_time = ?
            WHERE status = ?
            """,
            (STATUS_INCOMPLETE, _now(), STATUS_RECORDING),
        )
        return int(cur.rowcount or 0)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Mac Edge ncm_songs SQLite helper")
    parser.add_argument("cmd", choices=["init", "path"])
    args = parser.parse_args()
    if args.cmd == "init":
        print(init_db())
        return
    print(db_path())


if __name__ == "__main__":
    main()
