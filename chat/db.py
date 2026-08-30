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

from chat.kinds import normalize_ack_type
from chat.mentions import (
    DISPLAY_NAMES,
    HANDLES,
    OWNER,
    SENDERS,
    audience_for,
    normalize_handle,
    parse_mention_roles,
    recipients_for,
    visible_to,
)
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
        CREATE TABLE IF NOT EXISTS message_acks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          message_id INTEGER NOT NULL,
          handle TEXT NOT NULL,
          ack_type TEXT NOT NULL DEFAULT 'ok',
          ts TEXT NOT NULL,
          created_at REAL NOT NULL,
          UNIQUE(message_id, handle)
        );
        CREATE INDEX IF NOT EXISTS idx_message_acks_message ON message_acks(message_id);
        CREATE INDEX IF NOT EXISTS idx_message_acks_created ON message_acks(created_at);
        CREATE TABLE IF NOT EXISTS ack_revisions (
          message_id INTEGER PRIMARY KEY,
          revised_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ack_revisions_at ON ack_revisions(revised_at);
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
    if "cc_json" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN cc_json TEXT NOT NULL DEFAULT '[]'")
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


def _acks_map(conn: sqlite3.Connection, msg_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {i: [] for i in msg_ids}
    if not msg_ids:
        return out
    placeholders = ",".join("?" * len(msg_ids))
    rows = conn.execute(
        f"""
        SELECT message_id, handle, ack_type, ts, created_at
        FROM message_acks
        WHERE message_id IN ({placeholders})
        ORDER BY created_at ASC, id ASC
        """,
        msg_ids,
    ).fetchall()
    for row in rows:
        out[int(row["message_id"])].append(
            {
                "handle": row["handle"],
                "ack_type": row["ack_type"],
                "ts": row["ts"],
                "created_at": float(row["created_at"] or 0),
            }
        )
    return out


def _with_reads(conn: sqlite3.Connection, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reads = _reads_map(conn, [m["id"] for m in messages])
    acks = _acks_map(conn, [m["id"] for m in messages])
    for msg in messages:
        entries = reads.get(msg["id"], [])
        msg["read"] = {handle: ts for handle, ts in entries if ts}
        msg["unread"] = [handle for handle, ts in entries if not ts]
        msg["acks"] = acks.get(msg["id"], [])
    return messages


def _latest_ack_at(conn: sqlite3.Connection) -> float:
    ack_raw = conn.execute("SELECT MAX(created_at) FROM message_acks").fetchone()[0]
    rev_raw = conn.execute("SELECT MAX(revised_at) FROM ack_revisions").fetchone()[0]
    return max(float(ack_raw or 0), float(rev_raw or 0))


def _touch_ack_revision(conn: sqlite3.Connection, message_id: int, *, at: float | None = None) -> float:
    ts = float(at if at is not None else time.time())
    conn.execute(
        """
        INSERT INTO ack_revisions (message_id, revised_at)
        VALUES (?, ?)
        ON CONFLICT(message_id) DO UPDATE SET revised_at = excluded.revised_at
        """,
        (int(message_id), ts),
    )
    return ts


def _get_message_row(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM messages WHERE id = ?", (int(message_id),)).fetchone()


def _get_message(conn: sqlite3.Connection, message_id: int) -> dict[str, Any]:
    row = _get_message_row(conn, message_id)
    if row is None:
        raise ValueError("message not found")
    return _with_reads(conn, [_row_message(row)])[0]


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
    mentions = _loads(row["mentions_json"]) or []
    if not isinstance(mentions, list):
        mentions = []
    cc: list[str] = []
    try:
        cc_raw = _loads(row["cc_json"]) or []
        if isinstance(cc_raw, list):
            cc = [str(x) for x in cc_raw]
    except (KeyError, IndexError):
        cc = []
    cc_set = set(cc)
    action = [h for h in mentions if h not in cc_set]
    if "all" in mentions:
        action = ["all"]
    return {
        "id": int(row["id"]),
        "ts": row["ts"],
        "from": row["from_handle"],
        "body": "" if recalled else row["body"],
        "attachments": [] if recalled else attachments_raw,
        "audience": _loads(row["audience_json"]) or [],
        "mentions": mentions,
        "action": action,
        "cc": cc,
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


def list_messages_page(*, since_id: int = 0, since_ack_at: float = 0.0) -> dict[str, Any]:
    """Page timeline + optional ack patches for incremental badge refresh."""
    messages = list_messages(since_id=since_id)
    patches, latest = ack_patches(since_ack_at=since_ack_at)
    return {
        "messages": messages,
        "ack_patches": patches,
        "latest_ack_at": latest,
    }


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
    roles = parse_mention_roles(text)
    mentions = roles.all_mentions
    cc = list(roles.cc)
    audience = audience_for(sender, mentions)
    ts = now_ts()
    created = time.time()
    with locked():
        conn = _connect()
        cur = conn.execute(
            """
            INSERT INTO messages (
              ts, from_handle, body, audience_json, mentions_json, created_at, attachments_json, cc_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, sender, text, _dumps(audience), _dumps(mentions), created, _dumps(rows), _dumps(cc)),
        )
        conn.commit()
        msg_id = int(cur.lastrowid)
        _insert_reads(conn, msg_id, sender, audience, mark_all_read=False)
        conn.commit()
        return _get_message(conn, msg_id)


def ack_patches(*, since_ack_at: float = 0.0) -> tuple[list[dict[str, Any]], float]:
    """Messages whose acks changed since a timestamp (add or remove)."""
    since = max(0.0, float(since_ack_at or 0))
    with locked():
        conn = _connect()
        latest = _latest_ack_at(conn)
        rows = conn.execute(
            """
            SELECT message_id FROM (
              SELECT DISTINCT message_id AS message_id
              FROM message_acks
              WHERE created_at > ?
              UNION
              SELECT message_id
              FROM ack_revisions
              WHERE revised_at > ?
            )
            ORDER BY message_id ASC
            """,
            (since, since),
        ).fetchall()
        patches: list[dict[str, Any]] = []
        for row in rows:
            msg_id = int(row["message_id"])
            if _get_message_row(conn, msg_id) is None:
                continue
            patches.append(
                {
                    "id": msg_id,
                    "acks": _acks_map(conn, [msg_id]).get(msg_id, []),
                }
            )
        return patches, latest


def ack_message(*, from_handle: str, message_id: int, ack_type: str = "got") -> dict[str, Any]:
    """Feishu-style reaction on a message (no new chat row).

    ack_type: recv=收到 (formal @ 签收), got=知道了 (cc 周知). Legacy ok → stored as ok, UI=知道了.
    """
    sender = normalize_handle(from_handle)
    if sender not in SENDERS:
        raise ValueError(f"unknown from handle: {from_handle}")
    kind = normalize_ack_type(ack_type)
    with locked():
        conn = _connect()
        parent = _get_message_row(conn, int(message_id))
        if parent is None:
            raise ValueError("message not found")
        if _recalled_at(parent) is not None:
            raise ValueError("message recalled")
        ts = time.time()
        conn.execute(
            """
            INSERT INTO message_acks (message_id, handle, ack_type, ts, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(message_id, handle) DO UPDATE SET
              ack_type = excluded.ack_type,
              ts = excluded.ts,
              created_at = excluded.created_at
            """,
            (int(message_id), sender, kind, now_ts(), ts),
        )
        _touch_ack_revision(conn, int(message_id), at=ts)
        conn.commit()
        return _get_message(conn, int(message_id))


def unack_message(*, from_handle: str, message_id: int) -> dict[str, Any]:
    """Remove only this handle's ack. Cannot remove anyone else's."""
    sender = normalize_handle(from_handle)
    if sender not in SENDERS:
        raise ValueError(f"unknown from handle: {from_handle}")
    with locked():
        conn = _connect()
        parent = _get_message_row(conn, int(message_id))
        if parent is None:
            raise ValueError("message not found")
        conn.execute(
            "DELETE FROM message_acks WHERE message_id = ? AND handle = ?",
            (int(message_id), sender),
        )
        _touch_ack_revision(conn, int(message_id))
        conn.commit()
        return _get_message(conn, int(message_id))


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


def work_board(*, max_messages: int = 120, max_age_sec: float = 12 * 3600) -> dict[str, Any]:
    """Open Chat work obligations per handle (formal @ awaiting ✅ recv).

    Used to align Fleet / Chat / execution: a formal @ without recv is still open work.
    cc-only (got) is not treated as open work.

    A message stops counting as open when:
    - the action handle ack'd with recv, or
    - a later message from that handle references ``#<id>`` (formal follow-up).
    System ``[dev-task]`` / ``[fleet]`` / ``[release]`` lines are ignored for workers
    (controller may still track boss asks separately via IDE hook).
    """
    import re

    now = time.time()
    cutoff = now - max(60.0, float(max_age_sec))
    messages = list_messages(since_id=0)
    if max_messages > 0 and len(messages) > max_messages:
        messages = messages[-max_messages:]

    # handle -> set of message ids they later referenced with #N
    replied_ids: dict[str, set[int]] = {}
    id_ref = re.compile(r"#(\d+)\b")
    for msg in messages:
        if msg.get("recalled"):
            continue
        sender = str(msg.get("from") or "")
        body = str(msg.get("body") or "")
        found = {int(x) for x in id_ref.findall(body)}
        if not found:
            continue
        replied_ids.setdefault(sender, set()).update(found)

    by_handle: dict[str, dict[str, Any]] = {
        h: {"awaiting_recv": [], "acked_open": []} for h in HANDLES
    }
    by_handle[OWNER] = {"awaiting_recv": [], "acked_open": []}

    system_tag = re.compile(r"\[(dev-task|fleet|release)\]", re.I)

    for msg in messages:
        if msg.get("recalled"):
            continue
        created = float(msg.get("created_at") or 0)
        if created and created < cutoff:
            continue
        body = str(msg.get("body") or "")
        if system_tag.search(body):
            continue
        action = list(msg.get("action") or [])
        if not action or "all" in action:
            continue
        acks = {
            str(a.get("handle") or ""): str(a.get("ack_type") or "").lower()
            for a in (msg.get("acks") or [])
            if isinstance(a, dict)
        }
        preview = body.strip().replace("\n", " ")[:120]
        sender = str(msg.get("from") or "")
        mid = int(msg.get("id") or 0)
        for handle in action:
            if handle not in by_handle:
                continue
            if handle == sender:
                continue
            if mid in replied_ids.get(handle, set()):
                continue
            ack_type = acks.get(handle, "")
            row = {
                "id": mid,
                "from": sender,
                "preview": preview,
                "created_at": created,
                "ack_type": ack_type or None,
            }
            if ack_type == "recv":
                by_handle[handle]["acked_open"].append(row)
            else:
                # missing, got, or legacy ok — formal @ still needs ✅ recv
                by_handle[handle]["awaiting_recv"].append(row)

    return {
        "generated_at": now,
        "max_age_sec": max_age_sec,
        "handles": by_handle,
    }

