"""SQLite for HomeAgent Dev Console — separate from Brain business DB.

Single store for HomeAgent Dev app data: dev tasks (incl. agent replies/events),
debug issues, dev attachments, and Agent Chatbox messages. Brain intents/jobs
stay in brain.sqlite3.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_DEFAULT_DB = Path(__file__).resolve().parent / "data" / "dev_console.sqlite3"
_LEGACY_TASKS_JSON = Path(__file__).resolve().parent / "data" / "agent_tasks.json"
_LEGACY_ISSUES_JSON = Path(__file__).resolve().parent / "data" / "debug_issues.json"
_LEGACY_CHAT_DB = Path(__file__).resolve().parents[1] / "chat" / "data" / "agent_chat.sqlite3"

_lock = threading.RLock()
_connection: sqlite3.Connection | None = None
_path_override: Path | None = None


def db_path() -> Path:
    if _path_override is not None:
        return _path_override
    env = (os.environ.get("DEV_CONSOLE_DB_PATH") or "").strip()
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


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)


def _now() -> float:
    return time.time()


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
    migrate_legacy_json_once()
    migrate_legacy_chat_once()
    return conn


def init_chat_schema(conn: sqlite3.Connection) -> None:
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
          created_at REAL NOT NULL,
          recalled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS message_reads (
          message_id INTEGER NOT NULL,
          handle TEXT NOT NULL,
          read_at TEXT,
          PRIMARY KEY (message_id, handle)
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON messages(created_at);
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "recalled_at" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN recalled_at TEXT")
    if "kind" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'")
    if "reply_to_id" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN reply_to_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_reply_to ON messages(reply_to_id)")
    conn.executescript(
        """
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
    conn.commit()


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dev_tasks (
          task_id INTEGER PRIMARY KEY,
          text TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          thread_id INTEGER NOT NULL DEFAULT 0,
          parent_task_id INTEGER,
          category TEXT NOT NULL DEFAULT 'other',
          bridge_run_id TEXT NOT NULL DEFAULT '',
          bridge_url TEXT NOT NULL DEFAULT '',
          bridge_status TEXT NOT NULL DEFAULT '',
          target_handle TEXT NOT NULL DEFAULT '',
          queue_depth INTEGER,
          result TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '',
          closing_summary_draft TEXT NOT NULL DEFAULT '',
          closing_summary_md TEXT NOT NULL DEFAULT '',
          pending_close_status TEXT NOT NULL DEFAULT '',
          events_json TEXT NOT NULL DEFAULT '[]',
          status_log_json TEXT NOT NULL DEFAULT '[]',
          token_usage_json TEXT NOT NULL DEFAULT '{}',
          attachments_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS debug_issues (
          issue_id INTEGER PRIMARY KEY,
          intent_id INTEGER NOT NULL,
          session_id TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT 'user_console',
          participant_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'submitted',
          task_id INTEGER,
          user_summary TEXT NOT NULL DEFAULT '',
          problem_type TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          context_json TEXT NOT NULL DEFAULT '{}',
          attachments_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS assets (
          asset_id TEXT PRIMARY KEY,
          type TEXT NOT NULL,
          mime_type TEXT,
          status TEXT NOT NULL,
          producer_capability TEXT,
          size_bytes INTEGER,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          storage_json TEXT NOT NULL,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS asset_grants (
          asset_id TEXT NOT NULL,
          scope TEXT NOT NULL,
          capability_id TEXT,
          permission TEXT NOT NULL DEFAULT 'read',
          granted_at REAL NOT NULL,
          PRIMARY KEY (asset_id, scope)
        );
        CREATE INDEX IF NOT EXISTS idx_dev_tasks_thread ON dev_tasks(thread_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_debug_issues_intent ON debug_issues(intent_id);
        CREATE TABLE IF NOT EXISTS release_candidates (
          release_id INTEGER PRIMARY KEY,
          sha TEXT NOT NULL,
          sha_short TEXT NOT NULL,
          scope TEXT NOT NULL DEFAULT '',
          summary TEXT NOT NULL DEFAULT '',
          target TEXT NOT NULL DEFAULT 'cloud-brain',
          status TEXT NOT NULL DEFAULT 'in_progress',
          stages_json TEXT NOT NULL DEFAULT '[]',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          approved_by TEXT NOT NULL DEFAULT '',
          approved_at REAL,
          rejected_by TEXT NOT NULL DEFAULT '',
          rejected_at REAL,
          reject_note TEXT NOT NULL DEFAULT '',
          deploy_run_id TEXT NOT NULL DEFAULT '',
          last_chat_msg_id INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_release_sha_short ON release_candidates(sha_short);
        CREATE INDEX IF NOT EXISTS idx_release_updated ON release_candidates(updated_at DESC);
        """
    )
    init_chat_schema(conn)


def meta_get(key: str, default: str = "") -> str:
    with locked():
        conn = _connect()
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return str(row["value"])


def meta_set(key: str, value: str) -> None:
    with locked():
        conn = _connect()
        conn.execute(
            """
            INSERT INTO meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()


def meta_get_int(key: str, default: int = 1) -> int:
    raw = meta_get(key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def meta_set_int(key: str, value: int) -> None:
    meta_set(key, str(int(value)))


def clear_all() -> None:
    with locked():
        conn = _connect()
        conn.execute("DELETE FROM message_acks")
        conn.execute("DELETE FROM ack_revisions")
        conn.execute("DELETE FROM message_reads")
        conn.execute("DELETE FROM messages")
        conn.execute("UPDATE agents SET last_pull_id = 0, last_seen_at = NULL")
        conn.execute("DELETE FROM asset_grants")
        conn.execute("DELETE FROM assets")
        conn.execute("DELETE FROM debug_issues")
        conn.execute("DELETE FROM dev_tasks")
        conn.execute("DELETE FROM meta")
        conn.commit()


def _row_to_asset(row: sqlite3.Row) -> dict[str, Any]:
    out: dict[str, Any] = {
        "asset_id": row["asset_id"],
        "type": row["type"],
        "mime_type": row["mime_type"],
        "status": row["status"],
        "producer_capability": row["producer_capability"],
        "size_bytes": row["size_bytes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    meta = _loads(row["metadata_json"])
    if isinstance(meta, dict):
        out["metadata"] = meta
    storage = _loads(row["storage_json"])
    if isinstance(storage, dict):
        out["storage"] = storage
    return out


def put_asset(record: dict[str, Any]) -> str:
    aid = str(record.get("asset_id") or "").strip()
    if not aid:
        raise ValueError("put_asset requires asset_id")
    now = _now()
    created_at = float(record.get("created_at") or now)
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    storage = record.get("storage")
    if not isinstance(storage, dict):
        raise ValueError("put_asset requires storage object")
    with locked():
        conn = _connect()
        conn.execute(
            """
            INSERT INTO assets(
              asset_id, type, mime_type, status, producer_capability,
              size_bytes, metadata_json, storage_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
              type = excluded.type,
              mime_type = excluded.mime_type,
              status = excluded.status,
              producer_capability = excluded.producer_capability,
              size_bytes = excluded.size_bytes,
              metadata_json = excluded.metadata_json,
              storage_json = excluded.storage_json,
              updated_at = excluded.updated_at
            """,
            (
                aid,
                str(record.get("type") or "file"),
                str(record.get("mime_type") or "") or None,
                str(record.get("status") or "ready"),
                str(record.get("producer_capability") or record.get("producer") or "") or None,
                int(record.get("size_bytes") or 0) or None,
                _dumps(meta),
                _dumps(storage),
                created_at,
                now,
            ),
        )
        conn.commit()
    return aid


def get_asset(asset_id: str) -> dict[str, Any] | None:
    aid = str(asset_id or "").strip()
    if not aid:
        return None
    with locked():
        conn = _connect()
        row = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (aid,)).fetchone()
    if row is None:
        return None
    rec = _row_to_asset(row)
    if str(rec.get("status") or "").lower() == "deleted":
        return None
    return rec


def put_asset_grant(
    *,
    asset_id: str,
    scope: str,
    capability_id: str = "",
    permission: str = "read",
) -> None:
    aid = str(asset_id or "").strip()
    sc = str(scope or "").strip()
    if not aid or not sc:
        raise ValueError("put_asset_grant requires asset_id and scope")
    with locked():
        conn = _connect()
        conn.execute(
            """
            INSERT INTO asset_grants(asset_id, scope, capability_id, permission, granted_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(asset_id, scope) DO UPDATE SET
              capability_id = excluded.capability_id,
              permission = excluded.permission,
              granted_at = excluded.granted_at
            """,
            (aid, sc, capability_id or None, permission or "read", _now()),
        )
        conn.commit()


def has_asset_grant(asset_id: str, scope: str) -> bool:
    aid = str(asset_id or "").strip()
    sc = str(scope or "").strip()
    if not aid or not sc:
        return False
    with locked():
        conn = _connect()
        row = conn.execute(
            "SELECT 1 FROM asset_grants WHERE asset_id = ? AND scope = ?",
            (aid, sc),
        ).fetchone()
    return row is not None


def migrate_legacy_json_once() -> None:
    if meta_get("legacy_json_migrated") == "1":
        return
    if db_path().resolve() != _DEFAULT_DB.resolve():
        meta_set("legacy_json_migrated", "1")
        return
    with locked():
        conn = _connect()
        task_count = int(conn.execute("SELECT COUNT(*) FROM dev_tasks").fetchone()[0])
        issue_count = int(conn.execute("SELECT COUNT(*) FROM debug_issues").fetchone()[0])
    if task_count == 0 and _LEGACY_TASKS_JSON.is_file():
        try:
            raw = json.loads(_LEGACY_TASKS_JSON.read_text(encoding="utf-8"))
            rows = raw.get("tasks") or []
            if isinstance(rows, list) and rows:
                _import_dev_tasks(rows, int(raw.get("next_id") or 1))
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
    if issue_count == 0 and _LEGACY_ISSUES_JSON.is_file():
        try:
            raw = json.loads(_LEGACY_ISSUES_JSON.read_text(encoding="utf-8"))
            rows = raw.get("issues") or []
            if isinstance(rows, list) and rows:
                _import_debug_issues(rows, int(raw.get("next_id") or 1))
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
    meta_set("legacy_json_migrated", "1")


def migrate_legacy_chat_once() -> None:
    if meta_get("legacy_chat_migrated") == "1":
        return
    if db_path().resolve() != _DEFAULT_DB.resolve():
        meta_set("legacy_chat_migrated", "1")
        return
    with locked():
        conn = _connect()
        count = int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
    if count > 0 or not _LEGACY_CHAT_DB.is_file():
        meta_set("legacy_chat_migrated", "1")
        return
    if db_path().resolve() == _LEGACY_CHAT_DB.resolve():
        meta_set("legacy_chat_migrated", "1")
        return
    legacy = str(_LEGACY_CHAT_DB.resolve())
    with locked():
        conn = _connect()
        try:
            conn.execute("ATTACH DATABASE ? AS legacy_chat", (legacy,))
            conn.execute(
                """
                INSERT INTO messages (id, ts, from_handle, body, audience_json, mentions_json, created_at, recalled_at)
                SELECT id, ts, from_handle, body, audience_json, mentions_json, created_at, recalled_at
                FROM legacy_chat.messages
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO message_reads (message_id, handle, read_at)
                SELECT message_id, handle, read_at FROM legacy_chat.message_reads
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO agents (handle, display_name, last_pull_id, last_seen_at)
                SELECT handle, display_name, last_pull_id, last_seen_at FROM legacy_chat.agents
                """
            )
            conn.execute("DETACH DATABASE legacy_chat")
            conn.commit()
        except sqlite3.Error:
            try:
                conn.execute("DETACH DATABASE legacy_chat")
            except sqlite3.Error:
                pass
    meta_set("legacy_chat_migrated", "1")


def _import_dev_tasks(rows: list[dict[str, Any]], next_id: int) -> None:
    with locked():
        conn = _connect()
        max_id = 0
        for row in rows:
            if not isinstance(row, dict) or row.get("task_id") is None:
                continue
            tid = int(row["task_id"])
            max_id = max(max_id, tid)
            conn.execute(
                """
                INSERT OR REPLACE INTO dev_tasks(
                  task_id, text, status, created_at, updated_at, thread_id, parent_task_id,
                  category, bridge_run_id, bridge_url, bridge_status, target_handle,
                  queue_depth, result, error, closing_summary_draft, closing_summary_md,
                  pending_close_status, events_json, status_log_json, token_usage_json,
                  attachments_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    str(row.get("text") or ""),
                    str(row.get("status") or "queued"),
                    float(row.get("created_at") or _now()),
                    float(row.get("updated_at") or _now()),
                    int(row.get("thread_id") or 0),
                    int(row["parent_task_id"]) if row.get("parent_task_id") not in (None, "") else None,
                    str(row.get("category") or "other"),
                    str(row.get("bridge_run_id") or ""),
                    str(row.get("bridge_url") or ""),
                    str(row.get("bridge_status") or ""),
                    str(row.get("target_handle") or ""),
                    row.get("queue_depth"),
                    str(row.get("result") or ""),
                    str(row.get("error") or ""),
                    str(row.get("closing_summary_draft") or ""),
                    str(row.get("closing_summary_md") or ""),
                    str(row.get("pending_close_status") or ""),
                    _dumps(row.get("events") or []),
                    _dumps(row.get("status_log") or []),
                    _dumps(row.get("token_usage") or {}),
                    _dumps(row.get("attachments") or []),
                ),
            )
        if max_id:
            meta_set_int("dev_tasks_next_id", max(next_id, max_id + 1))
        conn.commit()


def _import_debug_issues(rows: list[dict[str, Any]], next_id: int) -> None:
    from debug_attachments import normalize_attachments

    with locked():
        conn = _connect()
        max_id = 0
        for row in rows:
            if not isinstance(row, dict) or row.get("issue_id") is None:
                continue
            iid = int(row["issue_id"])
            max_id = max(max_id, iid)
            attachments = normalize_attachments(row.get("attachments"))
            if not attachments:
                attachments = normalize_attachments(row.get("attachment_asset_ids"))
            task_raw = row.get("task_id")
            task_id = int(task_raw) if task_raw not in (None, "") else None
            conn.execute(
                """
                INSERT OR REPLACE INTO debug_issues(
                  issue_id, intent_id, session_id, source, participant_id, status, task_id,
                  user_summary, problem_type, error, created_at, updated_at,
                  context_json, attachments_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iid,
                    int(row.get("intent_id") or 0),
                    str(row.get("session_id") or ""),
                    str(row.get("source") or "user_console"),
                    str(row.get("participant_id") or ""),
                    str(row.get("status") or "submitted"),
                    task_id,
                    str(row.get("user_summary") or ""),
                    str(row.get("problem_type") or ""),
                    str(row.get("error") or ""),
                    float(row.get("created_at") or _now()),
                    float(row.get("updated_at") or _now()),
                    _dumps(row.get("context") or {}),
                    _dumps(attachments),
                ),
            )
        if max_id:
            meta_set_int("debug_issues_next_id", max(next_id, max_id + 1))
        conn.commit()
