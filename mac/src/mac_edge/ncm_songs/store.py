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


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    record = _loads(row["record_json"])
    if not isinstance(record, dict):
        record = {}
    return {
        "original_id": int(row["original_id"]),
        "encrypted_id": str(row["encrypted_id"]),
        "name": str(row["name"]),
        "name_norm": str(row["name_norm"]),
        "artist": str(row["artist"] or ""),
        "artist_norm": str(row["artist_norm"] or ""),
        "record": record,
        "record_json": str(row["record_json"]),
        "played_at": row["played_at"],
    }


def upsert_record(
    record: dict[str, Any],
    *,
    played_at: float | None = None,
) -> int:
    """Insert or replace by ``original_id``. Returns ``original_id``."""
    if not isinstance(record, dict) or not record:
        raise NcmSongsError("record must be a non-empty object")
    original_id = _original_id(record)
    encrypted_id = _encrypted_id(record)
    name = _song_name(record)
    artist = _artist_name(record)
    name_norm = normalize_text(name)
    artist_norm = normalize_text(artist)
    payload = _dumps(record)
    with _lock:
        init_db()
        conn = _connect()
        conn.execute(
            """
            INSERT INTO ncm_songs (
              original_id, encrypted_id, name, name_norm, artist, artist_norm,
              record_json, played_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(original_id) DO UPDATE SET
              encrypted_id = excluded.encrypted_id,
              name = excluded.name,
              name_norm = excluded.name_norm,
              artist = excluded.artist,
              artist_norm = excluded.artist_norm,
              record_json = excluded.record_json,
              played_at = COALESCE(excluded.played_at, ncm_songs.played_at)
            """,
            (
                original_id,
                encrypted_id,
                name,
                name_norm,
                artist or None,
                artist_norm,
                payload,
                played_at,
            ),
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


def find_by_norm(
    *,
    name_norm: str = "",
    artist_norm: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    name_key = normalize_text(name_norm)
    artist_key = normalize_text(artist_norm)
    clauses: list[str] = []
    params: list[Any] = []
    if name_key:
        clauses.append("name_norm = ?")
        params.append(name_key)
    if artist_key:
        clauses.append("artist_norm = ?")
        params.append(artist_key)
    if not clauses:
        return []
    sql = (
        "SELECT * FROM ncm_songs WHERE "
        + " AND ".join(clauses)
        + " ORDER BY COALESCE(played_at, 0) DESC, original_id DESC LIMIT ?"
    )
    params.append(max(1, int(limit)))
    with _lock:
        init_db()
        rows = _connect().execute(sql, params).fetchall()
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


def mark_played(original_id: int | str, *, at: float | None = None) -> None:
    try:
        oid = int(original_id)
    except (TypeError, ValueError) as exc:
        raise NcmSongsError("original_id required") from exc
    ts = _now() if at is None else float(at)
    with _lock:
        init_db()
        cur = _connect().execute(
            "UPDATE ncm_songs SET played_at = ? WHERE original_id = ?",
            (ts, oid),
        )
        if cur.rowcount <= 0:
            raise NcmSongsError(f"unknown original_id: {oid}")


def list_library(*, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    with _lock:
        init_db()
        rows = _connect().execute(
            """
            SELECT * FROM ncm_songs
            ORDER BY COALESCE(played_at, 0) DESC, original_id DESC
            LIMIT ? OFFSET ?
            """,
            (max(1, int(limit)), max(0, int(offset))),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_recent_played(*, limit: int = 20) -> list[dict[str, Any]]:
    with _lock:
        init_db()
        rows = _connect().execute(
            """
            SELECT * FROM ncm_songs
            WHERE played_at IS NOT NULL
            ORDER BY played_at DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


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
