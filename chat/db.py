"""Local SQLite for the agent chatbox. Not the Brain DB."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from chat.mentions import DISPLAY_NAMES, HANDLES, OWNER, SENDERS, audience_for, normalize_handle, parse_mentions, recipients_for, visible_to
from chat.attachments import normalize_attachments

TZ_EAST_8 = timezone(timedelta(hours=8))
RECALL_WINDOW_SEC = 60

_DEFAULT_DB = Path(__file__).resolve().parent / "data" / "agent_chat.sqlite3"

_lock = threading.RLock()
_connection: sqlite3.Connection | None = None
_path_override: Path | None = None


def db_path() -> Path:
    if _path_override is not None:
        return _path_override
    env = (os.environ.get("CHAT_DB_PATH") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _DEFAULT_DB


def reset(*, path: Path | None = None) -> None:
    global _connection, _path_override
    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None
        _path_override = path.resolve() if path is not None else None


def now_ts() -> str:
    return datetime.now(TZ_EAST_8).strftime("%Y-%m-%d %H:%M:%S")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)


@contextmanager
def locked() -> Iterator[None]:
    with _lock:
        yield


def _connect() -> sqlite3.Connection:
    global _connection
    if _connection is not None:
        return _connection
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    _connection = conn
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS agents (
          handle TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          last_pull_id INTEGER NOT NULL DEFAULT 0,
          last_seen_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          from_handle TEXT NOT NULL,
          body TEXT NOT NULL,
          audience_json TEXT NOT NULL,
          mentions_json TEXT NOT NULL,
          created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS message_reads (
          message_id INTEGER NOT NULL,
          handle TEXT NOT NULL,
          read_at TEXT,
          PRIMARY KEY (message_id, handle)
        );
        """
    )
    for handle in HANDLES:
        conn.execute(
            """
            INSERT OR IGNORE INTO agents (handle, display_name, last_pull_id, last_seen_at)
            VALUES (?, ?, 0, NULL)
            """,
            (handle, DISPLAY_NAMES[handle]),
        )
    _migrate_owner_to_boss(conn)
    _backfill_reads(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "recalled_at" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN recalled_at TEXT")
    if "attachments_json" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'")
    conn.commit()


def _rewrite_owner_tokens(raw: str | None) -> str | None:
    if not raw:
        return raw
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(value, list):
        return raw
    changed = False
    out: list[str] = []
    for item in value:
        if item in ("owner", "user"):
            item = OWNER
            changed = True
        if item not in out:
            out.append(item)
        else:
            changed = True
    return _dumps(out) if changed else raw


def _migrate_owner_to_boss(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE messages SET from_handle = ? WHERE from_handle IN ('owner', 'user')",
        (OWNER,),
    )
    rows = conn.execute("SELECT id, audience_json, mentions_json FROM messages").fetchall()
    for row in rows:
        audience = _rewrite_owner_tokens(row["audience_json"])
        mentions = _rewrite_owner_tokens(row["mentions_json"])
        if audience != row["audience_json"] or mentions != row["mentions_json"]:
            conn.execute(
                "UPDATE messages SET audience_json = ?, mentions_json = ? WHERE id = ?",
                (audience, mentions, int(row["id"])),
            )
    legacy = conn.execute(
        "SELECT message_id, handle, read_at FROM message_reads WHERE handle IN ('owner', 'user')"
    ).fetchall()
    for row in legacy:
        msg_id = int(row["message_id"])
        existing = conn.execute(
            "SELECT read_at FROM message_reads WHERE message_id = ? AND handle = ?",
            (msg_id, OWNER),
        ).fetchone()
        if existing is None:
            conn.execute(
                "UPDATE message_reads SET handle = ? WHERE message_id = ? AND handle = ?",
                (OWNER, msg_id, row["handle"]),
            )
            continue
        if existing["read_at"] is None and row["read_at"]:
            conn.execute(
                "UPDATE message_reads SET read_at = ? WHERE message_id = ? AND handle = ?",
                (row["read_at"], msg_id, OWNER),
            )
        conn.execute(
            "DELETE FROM message_reads WHERE message_id = ? AND handle = ?",
            (msg_id, row["handle"]),
        )


def _insert_reads(
    conn: sqlite3.Connection,
    msg_id: int,
    sender: str,
    audience: list[str],
    *,
    mark_all_read: bool,
) -> None:
    ts = now_ts()
    for handle in recipients_for(sender, audience):
        read_at = ts if mark_all_read or handle == sender else None
        conn.execute(
            """
            INSERT OR IGNORE INTO message_reads (message_id, handle, read_at)
            VALUES (?, ?, ?)
            """,
            (msg_id, handle, read_at),
        )


def _backfill_reads(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, from_handle, audience_json FROM messages").fetchall()
    for row in rows:
        exists = conn.execute(
            "SELECT 1 FROM message_reads WHERE message_id = ? LIMIT 1",
            (int(row["id"]),),
        ).fetchone()
        if exists:
            continue
        _insert_reads(
            conn,
            int(row["id"]),
            row["from_handle"],
            _loads(row["audience_json"]) or [],
            mark_all_read=True,
        )


def _reads_map(conn: sqlite3.Connection, msg_ids: list[int]) -> dict[int, list[tuple[str, str | None]]]:
    out: dict[int, list[tuple[str, str | None]]] = {i: [] for i in msg_ids}
    if not msg_ids:
        return out
    placeholders = ",".join("?" * len(msg_ids))
    rows = conn.execute(
        f"SELECT message_id, handle, read_at FROM message_reads WHERE message_id IN ({placeholders})",
        msg_ids,
    ).fetchall()
    for row in rows:
        out[int(row["message_id"])].append((row["handle"], row["read_at"]))
    return out


def _with_reads(conn: sqlite3.Connection, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reads = _reads_map(conn, [m["id"] for m in messages])
    for msg in messages:
        entries = reads.get(msg["id"], [])
        msg["read"] = {handle: ts for handle, ts in entries if ts}
        msg["unread"] = [handle for handle, ts in entries if not ts]
    return messages


def _unread_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT r.handle, COUNT(*) AS n
        FROM message_reads r
        JOIN messages m ON m.id = r.message_id
        WHERE r.read_at IS NULL AND IFNULL(m.recalled_at, '') = ''
        GROUP BY r.handle
        """
    ).fetchall()
    return {row["handle"]: int(row["n"]) for row in rows}


def _recalled_at(row: sqlite3.Row) -> str | None:
    try:
        raw = row["recalled_at"]
    except (KeyError, IndexError):
        return None
    if raw is None or raw == "":
        return None
    return str(raw)


def _row_message(row: sqlite3.Row) -> dict[str, Any]:
    recalled = _recalled_at(row) is not None
    attachments_raw = []
    try:
        attachments_raw = _loads(row["attachments_json"]) or []
    except (KeyError, IndexError):
        attachments_raw = []
    if not isinstance(attachments_raw, list):
        attachments_raw = []
    return {
        "id": int(row["id"]),
        "ts": row["ts"],
        "from": row["from_handle"],
        "body": "" if recalled else row["body"],
        "attachments": [] if recalled else attachments_raw,
        "audience": _loads(row["audience_json"]) or [],
        "mentions": _loads(row["mentions_json"]) or [],
        "created_at": float(row["created_at"] or 0),
        "recalled": recalled,
    }


def list_agents() -> list[dict[str, Any]]:
    with locked():
        conn = _connect()
        counts = _unread_counts(conn)
        rows = conn.execute(
            "SELECT handle, display_name, last_pull_id, last_seen_at FROM agents ORDER BY handle"
        ).fetchall()
        return [
            {
                "handle": row["handle"],
                "display_name": row["display_name"],
                "last_pull_id": int(row["last_pull_id"]),
                "last_seen_at": row["last_seen_at"],
                "unread": int(counts.get(row["handle"], 0)),
            }
            for row in rows
        ]


def boss_unread_count() -> int:
    with locked():
        conn = _connect()
        return int(_unread_counts(conn).get(OWNER, 0))


def owner_unread_count() -> int:
    return boss_unread_count()


def _max_message_id(conn: sqlite3.Connection) -> int:
    raw = conn.execute("SELECT MAX(id) FROM messages").fetchone()[0]
    return int(raw or 0)


def list_messages(*, since_id: int = 0) -> list[dict[str, Any]]:
    since_id = max(0, int(since_id))
    with locked():
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM messages WHERE id > ? ORDER BY id ASC",
            (since_id,),
        ).fetchall()
        return _with_reads(conn, [_row_message(row) for row in rows])


def push_message(
    *,
    from_handle: str,
    body: str,
    attachments: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    sender = normalize_handle(from_handle)
    if sender == "all" or sender not in SENDERS:
        raise ValueError(f"unknown from handle: {from_handle}")
    text = body if isinstance(body, str) else str(body)
    rows = normalize_attachments(attachments)
    if not text.strip() and not rows:
        raise ValueError("body or attachments required")
    mentions = parse_mentions(text)
    audience = audience_for(sender, mentions)
    ts = now_ts()
    created = time.time()
    with locked():
        conn = _connect()
        cur = conn.execute(
            """
            INSERT INTO messages (ts, from_handle, body, audience_json, mentions_json, created_at, attachments_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, sender, text, _dumps(audience), _dumps(mentions), created, _dumps(rows)),
        )
        conn.commit()
        msg_id = int(cur.lastrowid)
        _insert_reads(conn, msg_id, sender, audience, mark_all_read=False)
        conn.commit()
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
        return _with_reads(conn, [_row_message(row)])[0]


def pull_messages(*, handle: str, since_id: int = 0) -> dict[str, Any]:
    agent = normalize_handle(handle)
    if agent not in HANDLES:
        raise ValueError(f"unknown agent handle: {handle}")
    since_id = max(0, int(since_id or 0))
    with locked():
        conn = _connect()
        row = conn.execute(
            "SELECT last_pull_id FROM agents WHERE handle = ?", (agent,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown agent handle: {handle}")
        stored = int(row["last_pull_id"] or 0)
        cursor = max(since_id, stored)
        rows = conn.execute(
            "SELECT * FROM messages WHERE id > ? ORDER BY id ASC",
            (cursor,),
        ).fetchall()
        visible = _with_reads(
            conn,
            [
                _row_message(item)
                for item in rows
                if _recalled_at(item) is None
                and visible_to(_loads(item["audience_json"]) or [], agent)
            ],
        )
        if visible:
            placeholders = ",".join("?" * len(visible))
            conn.execute(
                f"""
                UPDATE message_reads
                SET read_at = ?
                WHERE handle = ? AND read_at IS NULL AND message_id IN ({placeholders})
                """,
                [now_ts(), agent, *[m["id"] for m in visible]],
            )
            visible = _with_reads(conn, visible)
        max_id = _max_message_id(conn)
        new_pull_id = max(stored, max_id)
        conn.execute(
            "UPDATE agents SET last_pull_id = ?, last_seen_at = ? WHERE handle = ?",
            (new_pull_id, now_ts(), agent),
        )
        conn.commit()
        return {
            "handle": agent,
            "last_id": new_pull_id,
            "messages": visible,
        }


def mark_read(*, handle: str, ids: list[int] | None = None) -> dict[str, Any]:
    who = normalize_handle(handle)
    if who not in SENDERS:
        raise ValueError(f"unknown handle: {handle}")
    with locked():
        conn = _connect()
        ts = now_ts()
        if ids:
            clean = [int(i) for i in ids]
            placeholders = ",".join("?" * len(clean))
            conn.execute(
                f"""
                UPDATE message_reads
                SET read_at = ?
                WHERE handle = ? AND read_at IS NULL AND message_id IN ({placeholders})
                """,
                [ts, who, *clean],
            )
        else:
            conn.execute(
                "UPDATE message_reads SET read_at = ? WHERE handle = ? AND read_at IS NULL",
                (ts, who),
            )
        conn.commit()
        remaining = int(_unread_counts(conn).get(who, 0))
        return {"handle": who, "unread": remaining}


def recall_message(*, from_handle: str, msg_id: int) -> dict[str, Any]:
    sender = normalize_handle(from_handle)
    if sender not in SENDERS:
        raise ValueError(f"unknown from handle: {from_handle}")
    with locked():
        conn = _connect()
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (int(msg_id),)).fetchone()
        if row is None:
            raise ValueError("消息不存在")
        if _recalled_at(row) is not None:
            raise ValueError("已经撤回")
        if row["from_handle"] != sender:
            raise ValueError("只能撤回自己发的消息")
        age = time.time() - float(row["created_at"] or 0)
        if age > RECALL_WINDOW_SEC:
            raise ValueError("超过 1 分钟不能撤回")
        seen = conn.execute(
            """
            SELECT handle FROM message_reads
            WHERE message_id = ? AND read_at IS NOT NULL AND handle != ?
            """,
            (int(msg_id), sender),
        ).fetchone()
        if seen:
            raise ValueError("已有人看过，不能撤回")
        conn.execute(
            "UPDATE messages SET recalled_at = ?, body = '' WHERE id = ?",
            (now_ts(), int(msg_id)),
        )
        conn.execute("DELETE FROM message_reads WHERE message_id = ?", (int(msg_id),))
        conn.commit()
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (int(msg_id),)).fetchone()
        return _with_reads(conn, [_row_message(row)])[0]

