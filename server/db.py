"""Brain SQLite: schema migrate, jobs, pull queue, participants.

Phase 1 replaces in-memory dicts in the Flask stubs. Nested wire payloads stay JSON.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("brain_db")

_SQL_DIR = Path(__file__).resolve().parent / "sql"
_DEFAULT_DB = Path(__file__).resolve().parent / "data" / "brain.sqlite3"

_lock = threading.RLock()
# Bumped on every heartbeat/registration write. home_brain's capability-map
# cache uses this to detect staleness without a time-based TTL (so concurrent
# dispatches coalesce, and tests that put_heartbeat then rebuild see fresh data).
_heartbeat_version = 0


def heartbeat_version() -> int:
    return _heartbeat_version
_connection: sqlite3.Connection | None = None
_path_override: Path | None = None


def db_path() -> Path:
    if _path_override is not None:
        return _path_override
    env = (os.environ.get("BRAIN_DB_PATH") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    canonical = _DEFAULT_DB
    legacy = Path(__file__).resolve().parent.parent / "data" / "brain.sqlite3"
    if not canonical.exists() and legacy.exists():
        return legacy.resolve()
    return canonical


def reset(*, path: Path | None = None) -> None:
    """Close the process connection (tests / path switch). Next call reopens."""
    global _connection, _path_override
    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None
        _path_override = path.resolve() if path is not None else None


@contextmanager
def locked() -> Iterator[None]:
    with _lock:
        yield


def meta_get(key: str, default: str = "") -> str:
    k = str(key or "").strip()
    if not k:
        return default
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (k,)).fetchone()
    if not row:
        return default
    return str(row[0] if not isinstance(row, sqlite3.Row) else row["value"] or default)


def meta_set(key: str, value: str) -> None:
    k = str(key or "").strip()
    if not k:
        raise ValueError("meta key required")
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (k, str(value)),
        )
        conn.commit()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)


def _now() -> float:
    return time.time()


def _unix_seconds(value: Any) -> float:
    if value is None or value == "":
        return _now()
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    try:
        return float(raw)
    except ValueError:
        pass
    iso = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return _now()


_PULLABLE_WHERE = """
lower(status) NOT IN ('succeeded', 'failed', 'intent_waiting')
OR (
  lower(status) = 'succeeded'
  AND json_extract(pending_delivery, '$.edge_id') IS NOT NULL
  AND trim(json_extract(pending_delivery, '$.edge_id')) != ''
)
"""


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


# ALTER TABLE ... DROP COLUMN needs SQLite 3.35+. Cloud Python 3.9 ships 3.34.1.
_ALTER_DROP_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+[A-Za-z_][\w]*\s+DROP\s+COLUMN\s+[A-Za-z_][\w]*\s*;",
    re.IGNORECASE,
)


def _sqlite_supports_drop_column(version: str | None = None) -> bool:
    raw = version or sqlite3.sqlite_version
    parts = tuple(int(p) for p in raw.split(".")[:3])
    return parts >= (3, 35, 0)


def _prepare_migration_sql(sql: str, *, sqlite_version: str | None = None) -> str:
    """Leave unused columns on SQLite < 3.35; do not rewrite @dba SQL files."""
    if _sqlite_supports_drop_column(sqlite_version):
        return sql
    return _ALTER_DROP_COLUMN.sub(
        "-- skipped DROP COLUMN (SQLite < 3.35)\n",
        sql,
    )


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
        # executescript() commits first; keep DDL + version insert sequential.
        sql = _prepare_migration_sql(sql_path.read_text(encoding="utf-8"))
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )


def init_db() -> Path:
    with _lock:
        conn = _connect()
        _migrate(conn)
        _reconcile_intent_sequence_locked()
    return db_path()


def _max_numeric_intent_id(conn: sqlite3.Connection, table: str) -> int:
    if table == "jobs":
        row = conn.execute("SELECT MAX(intent_id) AS m FROM jobs").fetchone()
        return int(row["m"] or 0)
    highest = 0
    for row in conn.execute(f"SELECT intent_id FROM {table}"):
        raw = str(row["intent_id"] or "").strip()
        try:
            highest = max(highest, int(raw))
        except ValueError:
            continue
    return highest


def _reconcile_intent_sequence_locked() -> int:
    """Keep next_intent_id strictly above any persisted job or queue row.

    Restart must not reuse ids even if meta was stale or missing.
    """
    conn = _connect()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'next_intent_id'"
        ).fetchone()
        current = int(row["value"]) if row else 1
        nxt = max(
            current,
            _max_numeric_intent_id(conn, "jobs") + 1,
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('next_intent_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(nxt),),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return nxt


def reconcile_intent_sequence() -> int:
    with _lock:
        _connect()
        return _reconcile_intent_sequence_locked()


def next_intent_id() -> int:
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'next_intent_id'"
            ).fetchone()
            current = int(row["value"]) if row else 1
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('next_intent_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(current + 1),),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return current


def notice_intent_id(seen: int) -> None:
    """Keep the sequence strictly above any explicitly supplied id."""
    if seen < 1:
        return
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'next_intent_id'"
            ).fetchone()
            current = int(row["value"]) if row else 1
            nxt = max(current, seen + 1)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('next_intent_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(nxt),),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _intent_key(intent_id: str | int) -> str:
    return str(intent_id).strip()


_DEAD_JOB_KEYS = ("assigned_edge_id", "scheduler_node")

_JOB_TEXT_COLS = (
    "job_id",
    "text",
    "source",
    "intent_origin",
    "edge_id",
    "edge_node_id",
    "error",
    "msg",
    "detail",
    "command_id",
)
_JOB_INT_COLS = ("base_time", "intent_base_time")
_JOB_JSON_COLS = (
    "execution_plan",
    "steps",
    "step_log",
    "status_log",
    "ctx_param",
    "context",
    "outputs",
    "step_outputs",
    "presentation",
    "pending_delivery",
    "available_capabilities",
)


def _opt_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _opt_intent_origin(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in ("lan", "cloud"):
        return raw
    return None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_json(value: Any) -> str | None:
    if value is None:
        return None
    return _dumps(value)


def _job_identity(intent_id: str | int) -> int:
    if isinstance(intent_id, int):
        return intent_id
    raw = str(intent_id or "").strip()
    if not raw.isdigit():
        raise ValueError(f"jobs.intent_id must be numeric: {intent_id!r}")
    return int(raw)


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    ident = int(row["intent_id"])
    status = str(row["status"] or "")
    job: dict[str, Any] = {
        "intent_id": ident,
        "id": ident,
        "status": status,
        "intent_status": status,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    job_id = row["job_id"]
    job["job_id"] = str(job_id) if job_id is not None else str(ident)
    for col in _JOB_TEXT_COLS:
        if col == "job_id":
            continue
        val = row[col]
        if val is not None:
            if col == "command_id" and str(val).isdigit():
                job[col] = int(val)
            else:
                job[col] = val
    for col in _JOB_INT_COLS:
        val = row[col]
        if val is not None:
            job[col] = int(val)
    for col in _JOB_JSON_COLS:
        try:
            raw = row[col]
        except (IndexError, KeyError):
            continue
        if raw is None or raw == "":
            if col == "execution_plan":
                job[col] = []
            continue
        parsed = _loads(raw) if isinstance(raw, str) else raw
        if parsed is not None:
            job[col] = deepcopy(parsed) if isinstance(parsed, (dict, list)) else parsed
    for dead in _DEAD_JOB_KEYS:
        job.pop(dead, None)
    return job


def put_job(job: dict[str, Any]) -> None:
    raw_id = job.get("intent_id") if job.get("intent_id") is not None else job.get("id")
    if raw_id is None or str(raw_id).strip() == "":
        create_job(job)
        return
    iid = _job_identity(raw_id)
    status = str(job.get("status") or job.get("intent_status") or "").strip()
    created = _unix_seconds(job.get("created_at"))
    updated = _unix_seconds(job.get("updated_at"))
    values = (
        iid,
        _opt_text(job.get("job_id") or str(iid)),
        status,
        _opt_text(job.get("text")),
        _opt_text(job.get("source")),
        _opt_intent_origin(job.get("intent_origin")),
        _opt_text(job.get("edge_id")),
        _opt_text(job.get("edge_node_id")),
        _opt_text(job.get("error")),
        _opt_text(job.get("msg")),
        _opt_text(job.get("detail")),
        _opt_text(job.get("command_id")),
        _opt_int(job.get("base_time")),
        _opt_int(job.get("intent_base_time")),
        created,
        updated,
        _dumps(job["execution_plan"]) if "execution_plan" in job else "[]",
        _opt_json(job.get("steps")),
        _opt_json(job.get("step_log")),
        _opt_json(job.get("status_log")),
        _opt_json(job.get("ctx_param")),
        _opt_json(job.get("context")),
        _opt_json(job.get("outputs")),
        _opt_json(job.get("step_outputs")),
        _opt_json(job.get("presentation")),
        _opt_json(job.get("pending_delivery")),
        _opt_json(job.get("available_capabilities")),
    )
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO jobs(
              intent_id, job_id, status, text, source, intent_origin, edge_id,
              edge_node_id, error, msg, detail, command_id,
              base_time, intent_base_time, created_at, updated_at,
              execution_plan, steps, step_log, status_log, ctx_param, context,
              outputs, step_outputs, presentation, pending_delivery,
              available_capabilities
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(intent_id) DO UPDATE SET
              job_id = excluded.job_id,
              status = excluded.status,
              text = COALESCE(excluded.text, jobs.text),
              source = COALESCE(excluded.source, jobs.source),
              intent_origin = excluded.intent_origin,
              edge_id = COALESCE(excluded.edge_id, jobs.edge_id),
              edge_node_id = excluded.edge_node_id,
              error = excluded.error,
              msg = excluded.msg,
              detail = excluded.detail,
              command_id = excluded.command_id,
              base_time = excluded.base_time,
              intent_base_time = excluded.intent_base_time,
              updated_at = excluded.updated_at,
              execution_plan = excluded.execution_plan,
              steps = excluded.steps,
              step_log = excluded.step_log,
              status_log = excluded.status_log,
              ctx_param = excluded.ctx_param,
              context = excluded.context,
              outputs = excluded.outputs,
              step_outputs = excluded.step_outputs,
              presentation = excluded.presentation,
              pending_delivery = excluded.pending_delivery,
              available_capabilities = COALESCE(
                excluded.available_capabilities, jobs.available_capabilities
              )
            """,
            values,
        )


def create_job(job: dict[str, Any]) -> int:
    """Insert a new job; intent_id assigned by INTEGER PRIMARY KEY AUTOINCREMENT."""
    status = str(job.get("status") or job.get("intent_status") or "").strip()
    created = _unix_seconds(job.get("created_at"))
    updated = _unix_seconds(job.get("updated_at"))
    values = (
        _opt_text(job.get("job_id")),
        status,
        _opt_text(job.get("text")),
        _opt_text(job.get("source")),
        _opt_intent_origin(job.get("intent_origin")),
        _opt_text(job.get("edge_id")),
        _opt_text(job.get("edge_node_id")),
        _opt_text(job.get("error")),
        _opt_text(job.get("msg")),
        _opt_text(job.get("detail")),
        _opt_text(job.get("command_id")),
        _opt_int(job.get("base_time")),
        _opt_int(job.get("intent_base_time")),
        created,
        updated,
        _dumps(job["execution_plan"]) if "execution_plan" in job else "[]",
        _opt_json(job.get("steps")),
        _opt_json(job.get("step_log")),
        _opt_json(job.get("status_log")),
        _opt_json(job.get("ctx_param")),
        _opt_json(job.get("context")),
        _opt_json(job.get("outputs")),
        _opt_json(job.get("step_outputs")),
        _opt_json(job.get("presentation")),
        _opt_json(job.get("pending_delivery")),
        _opt_json(job.get("available_capabilities")),
    )
    with _lock:
        conn = _connect()
        cur = conn.execute(
            """
            INSERT INTO jobs(
              job_id, status, text, source, intent_origin, edge_id,
              edge_node_id, error, msg, detail, command_id,
              base_time, intent_base_time, created_at, updated_at,
              execution_plan, steps, step_log, status_log, ctx_param, context,
              outputs, step_outputs, presentation, pending_delivery,
              available_capabilities
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        iid = int(cur.lastrowid)
        if not job.get("job_id"):
            conn.execute(
                "UPDATE jobs SET job_id = ? WHERE intent_id = ?",
                (str(iid), iid),
            )
    notice_intent_id(iid)
    return iid


def get_job(intent_id: str | int) -> dict[str, Any] | None:
    if intent_id in (None, ""):
        return None
    iid = _job_identity(intent_id)
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT * FROM jobs WHERE intent_id = ?", (iid,)).fetchone()
    if row is None:
        return None
    return _row_to_job(row)


def job_count() -> int:
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
        return int(row["n"])


def list_jobs() -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY intent_id DESC"
        ).fetchall()
    return [_row_to_job(row) for row in rows]


INTENTS_LIST_MAX = 5


def list_jobs_for_participant(
    participant_id: str,
    *,
    before_id: int | None = None,
    limit: int = INTENTS_LIST_MAX,
) -> list[dict[str, Any]]:
    """Issuer history: jobs whose edge_id is this participant_id, newest first."""
    pid = str(participant_id or "").strip()
    if not pid:
        return []
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        lim = INTENTS_LIST_MAX
    lim = max(1, min(lim, INTENTS_LIST_MAX))
    sql = "SELECT * FROM jobs WHERE edge_id = ?"
    params: list[Any] = [pid]
    if before_id is not None:
        try:
            before = int(before_id)
        except (TypeError, ValueError):
            before = 0
        if before >= 1:
            sql += " AND intent_id < ?"
            params.append(before)
    sql += " ORDER BY intent_id DESC LIMIT ?"
    params.append(lim)
    with _lock:
        conn = _connect()
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_job(row) for row in rows]


ADMIN_JOBS_PAGE_MAX = 200


def list_jobs_page(
    *,
    before_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Newest-first page of all jobs. Used by admin event stream, not issuer history."""
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        lim = 50
    lim = max(1, min(lim, ADMIN_JOBS_PAGE_MAX))
    sql = "SELECT * FROM jobs"
    params: list[Any] = []
    if before_id is not None:
        try:
            before = int(before_id)
        except (TypeError, ValueError):
            before = 0
        if before >= 1:
            sql += " WHERE intent_id < ?"
            params.append(before)
    sql += " ORDER BY intent_id DESC LIMIT ?"
    params.append(lim)
    with _lock:
        conn = _connect()
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_job(row) for row in rows]


def list_queue() -> list[dict[str, Any]]:
    """In-flight jobs for Edge pull, oldest first. Terminal rows stay in jobs."""
    with _lock:
        conn = _connect()
        rows = conn.execute(
            f"""
            SELECT * FROM jobs
            WHERE {_PULLABLE_WHERE}
            ORDER BY created_at ASC, intent_id ASC
            """
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def get_queue_item(intent_id: str | int) -> dict[str, Any] | None:
    return get_job(intent_id)


def upsert_queue(item: dict[str, Any]) -> dict[str, Any]:
    raw_id = item.get("id") if item.get("id") is not None else item.get("intent_id")
    if raw_id is None or str(raw_id).strip() == "":
        raise ValueError("upsert_queue requires item.id")
    iid = _job_identity(raw_id)
    existing = get_job(iid)
    stored: dict[str, Any] = dict(existing) if existing else {}
    stored.update(item)
    ident = iid
    stored["intent_id"] = ident
    stored["id"] = ident
    if "status" in item:
        stored["intent_status"] = stored["status"]
    elif "intent_status" in item:
        stored["status"] = stored["intent_status"]
    stored["updated_at"] = _now()
    put_job(stored)
    out = get_job(iid)
    if out is None:
        raise RuntimeError(f"upsert_queue failed to persist {iid}")
    return out


def remove_queue(intent_id: str | int) -> bool:
    """Pull no longer deletes rows. Job stays; status decides visibility."""
    return get_job(intent_id) is not None


def delete_queue_ids(intent_ids: list[str]) -> None:
    return


def queue_count() -> int:
    with _lock:
        conn = _connect()
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM jobs WHERE {_PULLABLE_WHERE}"
        ).fetchone()
        return int(row["n"])


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _row_to_review(row: sqlite3.Row) -> dict[str, Any]:
    iid = str(row["intent_id"])
    out: dict[str, Any] = {
        "review_id": int(row["review_id"]),
        "intent_id": _job_identity(iid),
        "created_at": row["created_at"],
    }
    for col in ("session_id", "text", "source", "edge_id", "planner", "model", "error", "raw_response"):
        val = row[col]
        if val is not None:
            out[col] = val
    cost_ms = _row_value(row, "cost_ms")
    if cost_ms is not None:
        out["cost_ms"] = int(cost_ms)
    parsed = _load_json_col(row["parsed_json"])
    if parsed is not None:
        out["parsed_json"] = parsed
    plan = _load_json_col(row["execution_plan"])
    if plan is not None:
        out["execution_plan"] = plan
    request_payload = _load_json_col(_row_value(row, "request_payload"))
    if request_payload is not None:
        out["request_payload"] = request_payload
    response_json = _load_json_col(_row_value(row, "response_json"))
    if response_json is not None:
        out["response_json"] = response_json
    return out


def put_intent_review(record: dict[str, Any]) -> int:
    iid = _intent_key(record.get("intent_id") or record.get("id") or "")
    if not iid:
        raise ValueError("put_intent_review requires intent_id")
    now = _unix_seconds(record.get("created_at"))
    with _lock:
        conn = _connect()
        cur = conn.execute(
            """
            INSERT INTO intent_reviews(
              intent_id, session_id, text, source, edge_id, planner, model, cost_ms,
              raw_response, parsed_json, execution_plan, error, created_at,
              request_payload, response_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                iid,
                _opt_text(record.get("session_id")),
                _opt_text(record.get("text")),
                _opt_text(record.get("source")),
                _opt_text(record.get("edge_id")),
                _opt_text(record.get("planner")),
                _opt_text(record.get("model")),
                _opt_int(record.get("cost_ms")),
                _opt_text(record.get("raw_response")),
                _opt_json(record.get("parsed_json")),
                _opt_json(record.get("execution_plan")),
                _opt_text(record.get("error")),
                now,
                _opt_json(record.get("request_payload")),
                _opt_json(record.get("response_json")),
            ),
        )
        return int(cur.lastrowid)


def get_intent_review(review_id: int) -> dict[str, Any] | None:
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM intent_reviews WHERE review_id = ?",
            (int(review_id),),
        ).fetchone()
    if row is None:
        return None
    return _row_to_review(row)


def list_intent_reviews(
    intent_id: str | int | None = None,
    *,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        if session_id is not None and str(session_id).strip() != "":
            rows = conn.execute(
                "SELECT * FROM intent_reviews WHERE session_id = ? ORDER BY review_id ASC",
                (str(session_id).strip(),),
            ).fetchall()
        elif intent_id is None or str(intent_id).strip() == "":
            rows = conn.execute(
                "SELECT * FROM intent_reviews ORDER BY review_id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM intent_reviews WHERE intent_id = ? ORDER BY review_id ASC",
                (_intent_key(intent_id),),
            ).fetchall()
    return [_row_to_review(row) for row in rows]


_CLASSIFICATIONS = frozenset({"SIMPLE", "MEDIUM", "COMPLEX"})
_FEATURE_MEAN_KEYS = (
    "capability_candidate_count",
    "action_count",
    "condition_count",
    "sequence_count",
    "parallel_count",
    "temporal_count",
    "context_reference_count",
    "ambiguity",
    "character_count",
    "token_count",
    "text_length_factor",
)


def _row_to_classification_event(row: sqlite3.Row) -> dict[str, Any]:
    features = _load_json_col(row["features"])
    candidates = _load_json_col(row["candidates"])
    out: dict[str, Any] = {
        "event_id": int(row["event_id"]),
        "classifier_version": row["classifier_version"],
        "score": row["score"],
        "classification": row["classification"],
        "created_at": row["created_at"],
    }
    if row["intent_id"] is not None and str(row["intent_id"]).strip() != "":
        out["intent_id"] = row["intent_id"]
    if row["text"] is not None:
        out["text"] = row["text"]
    if isinstance(features, dict):
        out["features"] = features
    if isinstance(candidates, list):
        out["candidates"] = candidates
    return out


def put_intent_classification_event(record: dict[str, Any]) -> int:
    iid_raw = record.get("intent_id")
    iid = None
    if iid_raw is not None and str(iid_raw).strip() != "":
        iid = _intent_key(iid_raw)
    classification = str(record.get("classification") or "").strip().upper()
    if classification not in _CLASSIFICATIONS:
        raise ValueError("classification must be SIMPLE, MEDIUM, or COMPLEX")
    score_raw = record.get("score")
    score = None
    if score_raw is not None and score_raw != "":
        try:
            score = float(score_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("score must be a number") from exc
    now = _unix_seconds(record.get("created_at"))
    with _lock:
        conn = _connect()
        cur = conn.execute(
            """
            INSERT INTO intent_classification_events(
              intent_id, text, classifier_version, score, classification,
              features, candidates, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                iid,
                _opt_text(record.get("text")),
                _opt_text(record.get("classifier_version")),
                score,
                classification,
                _opt_json(record.get("features")),
                _opt_json(record.get("candidates")),
                now,
            ),
        )
        return int(cur.lastrowid)


def list_intent_classification_events(
    intent_id: str | int | None = None,
) -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        try:
            if intent_id is None or str(intent_id).strip() == "":
                rows = conn.execute(
                    "SELECT * FROM intent_classification_events ORDER BY event_id ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM intent_classification_events
                    WHERE intent_id = ?
                    ORDER BY event_id ASC
                    """,
                    (_intent_key(intent_id),),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_row_to_classification_event(row) for row in rows]


def list_intent_classification_stats() -> dict[str, Any]:
    empty = {
        "n": 0,
        "simple_count": 0,
        "medium_count": 0,
        "complex_count": 0,
        "simple_rate": 0.0,
        "medium_rate": 0.0,
        "complex_rate": 0.0,
        "mean_score": None,
        "feature_means": {},
        "mean_plan_steps_by_class": {
            "SIMPLE": None,
            "MEDIUM": None,
            "COMPLEX": None,
        },
    }
    feature_select = ",\n              ".join(
        f"AVG(json_extract(features, '$.{key}')) AS mean_{key}"
        for key in _FEATURE_MEAN_KEYS
    )
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                f"""
                SELECT
                  COUNT(*) AS n,
                  SUM(CASE WHEN classification = 'SIMPLE' THEN 1 ELSE 0 END) AS simple_count,
                  SUM(CASE WHEN classification = 'MEDIUM' THEN 1 ELSE 0 END) AS medium_count,
                  SUM(CASE WHEN classification = 'COMPLEX' THEN 1 ELSE 0 END) AS complex_count,
                  AVG(score) AS mean_score,
                  {feature_select}
                FROM intent_classification_events
                """
            ).fetchone()
            step_rows = conn.execute(
                """
                SELECT
                  e.classification AS classification,
                  AVG(
                    CASE
                      WHEN j.execution_plan IS NULL OR trim(j.execution_plan) = '' THEN NULL
                      ELSE json_array_length(j.execution_plan)
                    END
                  ) AS mean_steps
                FROM intent_classification_events e
                LEFT JOIN jobs j ON CAST(j.intent_id AS TEXT) = e.intent_id
                GROUP BY e.classification
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return empty
    n = int(row["n"] or 0) if row is not None else 0
    if n <= 0 or row is None:
        return empty
    simple_count = int(row["simple_count"] or 0)
    medium_count = int(row["medium_count"] or 0)
    complex_count = int(row["complex_count"] or 0)

    def _rate(count: int) -> float:
        return round(count / n, 4)

    def _mean(value: Any) -> float | None:
        if value is None:
            return None
        return round(float(value), 4)

    feature_means = {
        key: _mean(row[f"mean_{key}"]) for key in _FEATURE_MEAN_KEYS
    }
    steps = {"SIMPLE": None, "MEDIUM": None, "COMPLEX": None}
    for step_row in step_rows:
        label = str(step_row["classification"] or "").strip().upper()
        if label in steps:
            steps[label] = _mean(step_row["mean_steps"])
    return {
        "n": n,
        "simple_count": simple_count,
        "medium_count": medium_count,
        "complex_count": complex_count,
        "simple_rate": _rate(simple_count),
        "medium_rate": _rate(medium_count),
        "complex_rate": _rate(complex_count),
        "mean_score": _mean(row["mean_score"]),
        "feature_means": feature_means,
        "mean_plan_steps_by_class": steps,
    }


_UNDERSTANDING_VALUES = frozenset({"accurate", "inaccurate"})
_RESPONSE_SPEED_VALUES = frozenset({"fast", "normal", "slow"})


def _row_to_intent_user_feedback(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "feedback_id": int(row["feedback_id"]),
        "intent_id": int(row["intent_id"]),
        "participant_id": row["participant_id"],
        "understanding": row["understanding"],
        "response_speed": row["response_speed"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def upsert_intent_user_feedback(record: dict[str, Any]) -> dict[str, Any]:
    try:
        intent_id = int(record.get("intent_id"))
    except (TypeError, ValueError):
        raise ValueError("intent_id must be an integer") from None
    if intent_id < 1:
        raise ValueError("intent_id must be >= 1")
    participant_id = str(record.get("participant_id") or record.get("edge_id") or "").strip()
    if not participant_id:
        raise ValueError("participant_id is required")
    understanding = str(record.get("understanding") or "").strip().lower()
    if understanding not in _UNDERSTANDING_VALUES:
        raise ValueError("understanding must be accurate or inaccurate")
    response_speed = str(record.get("response_speed") or "").strip().lower()
    if response_speed not in _RESPONSE_SPEED_VALUES:
        raise ValueError("response_speed must be fast, normal, or slow")
    now = _now()
    created_at = _unix_seconds(record.get("created_at"))
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO intent_user_feedback(
              intent_id, participant_id, understanding, response_speed, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(intent_id, participant_id) DO UPDATE SET
              understanding = excluded.understanding,
              response_speed = excluded.response_speed,
              updated_at = excluded.updated_at
            """,
            (intent_id, participant_id, understanding, response_speed, created_at, now),
        )
        row = conn.execute(
            """
            SELECT * FROM intent_user_feedback
            WHERE intent_id = ? AND participant_id = ?
            """,
            (intent_id, participant_id),
        ).fetchone()
    if row is None:
        raise RuntimeError("upsert_intent_user_feedback failed to read back row")
    return _row_to_intent_user_feedback(row)


def get_intent_user_feedback(
    intent_id: str | int,
    participant_id: str,
) -> dict[str, Any] | None:
    try:
        iid = int(intent_id)
    except (TypeError, ValueError):
        return None
    pid = str(participant_id or "").strip()
    if not pid:
        return None
    with _lock:
        conn = _connect()
        row = conn.execute(
            """
            SELECT * FROM intent_user_feedback
            WHERE intent_id = ? AND participant_id = ?
            """,
            (iid, pid),
        ).fetchone()
    if row is None:
        return None
    return _row_to_intent_user_feedback(row)


_ROLE_KEYS = ("intent_source", "runtime", "endpoint", "observer")
_ROLE_ALIASES = {
    "intent_source": "intent_source",
    "intent-source": "intent_source",
    "intentsource": "intent_source",
    "runtime": "runtime",
    "runtime_agent": "runtime",
    "endpoint": "endpoint",
    "observer": "observer",
}


def _truthy_role(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _roles_from_record(record: dict[str, Any]) -> dict[str, int]:
    flags = {key: 0 for key in _ROLE_KEYS}
    raw_roles = record.get("roles")
    if isinstance(raw_roles, (list, tuple)):
        for item in raw_roles:
            key = _ROLE_ALIASES.get(str(item or "").strip().lower())
            if key:
                flags[key] = 1
    for key in _ROLE_KEYS:
        if _truthy_role(record.get(f"role_{key}")):
            flags[key] = 1
    if flags["runtime"] == 0 and isinstance(record.get("services"), list) and record["services"]:
        flags["runtime"] = 1
    if flags["intent_source"] == 0 and isinstance(record.get("intent_sources"), list) and record["intent_sources"]:
        flags["intent_source"] = 1
    if flags["endpoint"] == 0 and isinstance(record.get("endpoints"), list) and record["endpoints"]:
        flags["endpoint"] = 1
    return flags


def _load_json_col(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    parsed = _loads(raw) if isinstance(raw, str) else raw
    return deepcopy(parsed) if isinstance(parsed, (dict, list)) else parsed


def _row_to_participant(row: sqlite3.Row, *, include_heartbeat: bool = True) -> dict[str, Any]:
    pid = str(row["participant_id"])
    roles = [key for key in _ROLE_KEYS if int(row[f"role_{key}"] or 0)]
    out: dict[str, Any] = {
        "participant_id": pid,
        "edge_id": pid,
        "status": str(row["status"] or "approved"),
        "registered_at": row["registered_at"],
        "updated_at": row["updated_at"],
        "roles": roles,
        "role_intent_source": bool(row["role_intent_source"]),
        "role_runtime": bool(row["role_runtime"]),
        "role_endpoint": bool(row["role_endpoint"]),
        "role_observer": bool(row["role_observer"]),
    }
    for col in ("client_hint", "display_name", "device_type", "app_version"):
        val = row[col]
        if val is not None:
            out[col] = val
    loc = row["location"]
    if loc is not None:
        out["location"] = loc
        out["room"] = loc
    services_decl = _load_json_col(row["services"])
    out["services"] = services_decl if isinstance(services_decl, list) else []
    for col in ("intent_sources", "endpoints"):
        parsed = _load_json_col(row[col])
        if parsed is not None:
            out[col] = parsed
    for col in ("domain", "runtime_id"):
        try:
            val = row[col]
        except (IndexError, KeyError):
            val = None
        if val is not None:
            out[col] = val
    try:
        exposure_raw = row["exposure_policy"]
    except (IndexError, KeyError):
        exposure_raw = None
    exposure = _load_json_col(exposure_raw)
    if exposure is not None:
        out["exposure_policy"] = exposure
    if include_heartbeat:
        if row["online_status"] is not None:
            out["online_status"] = row["online_status"]
        health = _load_json_col(row["health"])
        if health is not None:
            out["health"] = health
        for col in ("client_time_ms", "brain_time_ms", "clock_skew_ms"):
            if row[col] is not None:
                out[col] = int(row[col])
        if row["schedule_eligible"] is not None:
            out["schedule_eligible"] = bool(row["schedule_eligible"])
        if row["schedule_reject_reason"]:
            out["schedule_reject_reason"] = row["schedule_reject_reason"]
        if row["reported_at"] is not None:
            out["reported_at"] = row["reported_at"]
        if row["server_received_at"] is not None:
            out["server_received_at"] = row["server_received_at"]
        try:
            snap_raw = row["services_snapshot"]
        except (IndexError, KeyError):
            snap_raw = None
        snap = _load_json_col(snap_raw)
        if isinstance(snap, list):
            out["services"] = snap
    else:
        if row["server_received_at"] is not None:
            out["server_received_at"] = row["server_received_at"]
        if row["schedule_eligible"] is not None:
            out["schedule_eligible"] = bool(row["schedule_eligible"])
    return out


def _registrations_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='registrations'"
    ).fetchone()
    return row is not None


def _participant_domain(conn: sqlite3.Connection, pid: str) -> str | None:
    try:
        row = conn.execute(
            "SELECT domain FROM participants WHERE participant_id = ?", (pid,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    val = row["domain"]
    return str(val) if val is not None else None


def _participant_select_with_heartbeat() -> str:
    return """
        SELECT
          p.participant_id AS participant_id,
          p.client_hint AS client_hint,
          p.display_name AS display_name,
          p.device_type AS device_type,
          p.location AS location,
          p.app_version AS app_version,
          p.status AS status,
          p.registered_at AS registered_at,
          p.updated_at AS updated_at,
          p.role_intent_source AS role_intent_source,
          p.role_runtime AS role_runtime,
          p.role_endpoint AS role_endpoint,
          p.role_observer AS role_observer,
          p.services AS services,
          p.intent_sources AS intent_sources,
          p.endpoints AS endpoints,
          p.domain AS domain,
          p.exposure_policy AS exposure_policy,
          p.runtime_id AS runtime_id,
          r.online_status AS online_status,
          r.health AS health,
          r.client_time_ms AS client_time_ms,
          r.brain_time_ms AS brain_time_ms,
          r.clock_skew_ms AS clock_skew_ms,
          r.schedule_eligible AS schedule_eligible,
          r.schedule_reject_reason AS schedule_reject_reason,
          r.reported_at AS reported_at,
          r.server_received_at AS server_received_at,
          r.services_snapshot AS services_snapshot
        FROM participants p
        LEFT JOIN registrations r ON r.participant_id = p.participant_id
    """


def put_registration(record: dict[str, Any], *, domain: str | None = None) -> None:
    pid = str(record.get("participant_id") or record.get("edge_id") or "").strip()
    if not pid:
        raise ValueError("put_registration requires participant_id")
    roles = _roles_from_record(record)
    now = _now()
    registered_at = float(record.get("registered_at") or now)
    exposure = record.get("exposure_policy")
    runtime_id = str(record.get("runtime_id") or pid).strip() or pid
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO participants(
              participant_id, client_hint, display_name, device_type, location, app_version,
              status, registered_at, updated_at,
              role_intent_source, role_runtime, role_endpoint, role_observer,
              services, intent_sources, endpoints,
              domain, exposure_policy, runtime_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(participant_id) DO UPDATE SET
              client_hint = excluded.client_hint,
              display_name = excluded.display_name,
              device_type = excluded.device_type,
              location = excluded.location,
              app_version = excluded.app_version,
              status = excluded.status,
              updated_at = excluded.updated_at,
              role_intent_source = excluded.role_intent_source,
              role_runtime = excluded.role_runtime,
              role_endpoint = excluded.role_endpoint,
              role_observer = excluded.role_observer,
              services = excluded.services,
              intent_sources = excluded.intent_sources,
              endpoints = excluded.endpoints,
              domain = COALESCE(excluded.domain, participants.domain),
              exposure_policy = COALESCE(excluded.exposure_policy, participants.exposure_policy),
              runtime_id = COALESCE(excluded.runtime_id, participants.runtime_id)
            """,
            (
                pid,
                _opt_text(record.get("client_hint")),
                _opt_text(record.get("display_name")),
                _opt_text(record.get("device_type")),
                _opt_text(
                    record["location"] if "location" in record else record.get("room")
                ),
                _opt_text(record.get("app_version")),
                str(record.get("status") or "approved").strip() or "approved",
                registered_at,
                now,
                roles["intent_source"],
                roles["runtime"],
                roles["endpoint"],
                roles["observer"],
                _opt_json(record.get("services")),
                _opt_json(record.get("intent_sources")),
                _opt_json(record.get("endpoints")),
                _opt_text(domain),
                _opt_json(exposure),
                runtime_id,
            ),
        )
        if _registrations_exists(conn):
            dom = (domain or _participant_domain(conn, pid) or "lan").strip() or "lan"
            conn.execute(
                """
                INSERT INTO registrations(
                  participant_id, domain, registered_at, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(participant_id, domain) DO UPDATE SET
                  updated_at = excluded.updated_at
                """,
                (pid, dom, registered_at, now),
            )
        global _heartbeat_version
        _heartbeat_version += 1


def get_registration(edge_id: str) -> dict[str, Any] | None:
    pid = str(edge_id or "").strip()
    if not pid:
        return None
    with _lock:
        conn = _connect()
        if _registrations_exists(conn):
            row = conn.execute(
                _participant_select_with_heartbeat() + " WHERE p.participant_id = ?",
                (pid,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM participants WHERE participant_id = ?", (pid,)
            ).fetchone()
    if row is None:
        return None
    return _row_to_participant(row, include_heartbeat=True)


def registration_ids() -> list[str]:
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT participant_id FROM participants ORDER BY participant_id"
        ).fetchall()
    return [str(r["participant_id"]) for r in rows]


def registration_count() -> int:
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT COUNT(*) AS n FROM participants").fetchone()
    return int(row["n"])


def put_registration_row(
    participant_id: str, domain: str, *, registered_at: float | None = None
) -> None:
    pid = str(participant_id or "").strip()
    dom = str(domain or "").strip()
    if not pid or not dom:
        raise ValueError("put_registration_row requires participant_id and domain")
    now = _now()
    ts = float(registered_at) if registered_at is not None else now
    with _lock:
        conn = _connect()
        if not _registrations_exists(conn):
            return
        conn.execute(
            """
            INSERT INTO registrations(
              participant_id, domain, registered_at, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(participant_id, domain) DO UPDATE SET
              updated_at = excluded.updated_at
            """,
            (pid, dom, ts, now),
        )


def get_registration_row(
    participant_id: str, domain: str
) -> dict[str, Any] | None:
    pid = str(participant_id or "").strip()
    dom = str(domain or "").strip()
    if not pid or not dom:
        return None
    with _lock:
        conn = _connect()
        if not _registrations_exists(conn):
            return None
        row = conn.execute(
            "SELECT * FROM registrations WHERE participant_id = ? AND domain = ?",
            (pid, dom),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_registrations(domain: str | None = None) -> dict[str, dict[str, Any]]:
    with _lock:
        conn = _connect()
        if not _registrations_exists(conn):
            return {}
        if domain:
            rows = conn.execute(
                "SELECT * FROM registrations WHERE domain = ? ORDER BY participant_id",
                (str(domain),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM registrations ORDER BY participant_id, domain"
            ).fetchall()
    return {str(r["participant_id"]): dict(r) for r in rows}


def put_heartbeat(
    edge_id: str,
    info: dict[str, Any],
    *,
    domain: str | None = None,
) -> None:
    pid = str(edge_id or "").strip()
    if not pid:
        raise ValueError("put_heartbeat requires participant_id")
    eligible = info.get("schedule_eligible")
    eligible_int = None if eligible is None else (1 if eligible else 0)
    now = _now()
    reported = float(info["reported_at"]) if info.get("reported_at") is not None else None
    received = (
        float(info["server_received_at"])
        if info.get("server_received_at") is not None
        else None
    )
    dom = "lan"
    with _lock:
        conn = _connect()
        if not _registrations_exists(conn):
            cur = conn.execute(
                """
                UPDATE participants SET
                  online_status = ?,
                  health = ?,
                  client_time_ms = ?,
                  brain_time_ms = ?,
                  clock_skew_ms = ?,
                  schedule_eligible = ?,
                  schedule_reject_reason = ?,
                  reported_at = ?,
                  server_received_at = ?,
                  services = COALESCE(?, services),
                  updated_at = ?
                WHERE participant_id = ?
                """,
                (
                    _opt_text(info.get("online_status")),
                    _opt_json(info.get("health")),
                    _opt_int(info.get("client_time_ms")),
                    _opt_int(info.get("brain_time_ms")),
                    _opt_int(info.get("clock_skew_ms")),
                    eligible_int,
                    _opt_text(info.get("schedule_reject_reason")),
                    reported,
                    received,
                    _opt_json(info.get("services")),
                    now,
                    pid,
                ),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown participant_id: {pid}")
            if info.get("services"):
                conn.execute(
                    "UPDATE participants SET role_runtime = 1 WHERE participant_id = ?",
                    (pid,),
                )
            return
        dom = (domain or _participant_domain(conn, pid) or "lan").strip() or "lan"
        cur = conn.execute(
            """
            INSERT INTO registrations(
              participant_id, domain, registered_at, updated_at,
              online_status, health, client_time_ms, brain_time_ms, clock_skew_ms,
              schedule_eligible, schedule_reject_reason, reported_at,
              server_received_at, services_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(participant_id, domain) DO UPDATE SET
              updated_at = excluded.updated_at,
              online_status = excluded.online_status,
              health = excluded.health,
              client_time_ms = excluded.client_time_ms,
              brain_time_ms = excluded.brain_time_ms,
              clock_skew_ms = excluded.clock_skew_ms,
              schedule_eligible = excluded.schedule_eligible,
              schedule_reject_reason = excluded.schedule_reject_reason,
              reported_at = excluded.reported_at,
              server_received_at = excluded.server_received_at,
              services_snapshot = COALESCE(excluded.services_snapshot, registrations.services_snapshot)
            """,
            (
                pid,
                dom,
                now,
                now,
                _opt_text(info.get("online_status")),
                _opt_json(info.get("health")),
                _opt_int(info.get("client_time_ms")),
                _opt_int(info.get("brain_time_ms")),
                _opt_int(info.get("clock_skew_ms")),
                eligible_int,
                _opt_text(info.get("schedule_reject_reason")),
                reported,
                received,
                _opt_json(info.get("services")),
            ),
        )
        if cur.rowcount == 0:
            row = conn.execute(
                "SELECT 1 FROM participants WHERE participant_id = ?", (pid,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown participant_id: {pid}")
        if info.get("services"):
            conn.execute(
                "UPDATE participants SET role_runtime = 1 WHERE participant_id = ?",
                (pid,),
            )
        global _heartbeat_version
        _heartbeat_version += 1

    snap = info.get("services")
    log.info(
        "heartbeat_timeline participant_id=%s domain=%s observed_at=%s "
        "online_status=%s capabilities_snapshot=%s",
        pid,
        dom,
        received if received is not None else now,
        info.get("online_status"),
        _dumps(snap) if snap is not None else "null",
    )


def list_heartbeats() -> dict[str, dict[str, Any]]:
    with _lock:
        conn = _connect()
        if _registrations_exists(conn):
            rows = conn.execute(
                _participant_select_with_heartbeat()
                + " WHERE r.server_received_at IS NOT NULL OR r.online_status IS NOT NULL "
                "ORDER BY p.participant_id"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM participants
                WHERE server_received_at IS NOT NULL OR online_status IS NOT NULL
                ORDER BY participant_id
                """
            ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = _row_to_participant(row, include_heartbeat=True)
        out[str(row["participant_id"])] = payload
    return out


def heartbeat_count() -> int:
    with _lock:
        conn = _connect()
        if _registrations_exists(conn):
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM registrations
                WHERE server_received_at IS NOT NULL OR online_status IS NOT NULL
                """
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM participants
                WHERE server_received_at IS NOT NULL OR online_status IS NOT NULL
                """
            ).fetchone()
        return int(row["n"])


_ASSET_TYPES = ("image", "video", "audio", "document", "text", "other")
_ASSET_STATUSES = ("available", "pending", "expired", "deleted")
_ASSET_URL_KEYS = {
    "url",
    "path",
    "file_path",
    "internal_path",
    "s3_bucket",
    "permanent_url",
    "photo_url",
    "image_url",
    "photo_urls",
}


def _strip_url_keys(value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if not isinstance(value, dict):
        raise ValueError("must be a JSON object")
    return {str(k): v for k, v in value.items() if str(k) not in _ASSET_URL_KEYS}


def _norm_asset_type(value: Any) -> str:
    raw = str(value or "other").strip().lower() or "other"
    return raw if raw in _ASSET_TYPES else "other"


def _norm_asset_status(value: Any) -> str:
    raw = str(value or "available").strip().lower() or "available"
    aliases = {"created": "available", "in_use": "available", "archived": "expired"}
    raw = aliases.get(raw, raw)
    return raw if raw in _ASSET_STATUSES else "available"


def _asset_ref(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    getter = row.get if isinstance(row, dict) else row.__getitem__
    out: dict[str, Any] = {
        "asset_id": str(getter("asset_id")),
        "type": str(getter("type")),
    }
    mime = getter("mime_type")
    if mime:
        out["mime_type"] = str(mime)
    return out


def _row_to_asset(row: sqlite3.Row) -> dict[str, Any]:
    out: dict[str, Any] = {
        "asset_id": str(row["asset_id"]),
        "type": str(row["type"]),
        "status": str(row["status"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "asset_ref": _asset_ref(row),
    }
    if row["mime_type"] is not None:
        out["mime_type"] = row["mime_type"]
    if row["size_bytes"] is not None:
        out["size_bytes"] = int(row["size_bytes"])
    if row["origin_step"] is not None:
        out["origin_step"] = int(row["origin_step"])
    if row["expires_at"] is not None:
        out["expires_at"] = row["expires_at"]
    for col in ("producer_capability", "producer_edge_id", "origin_intent_id"):
        val = row[col]
        if val is not None:
            out[col] = val
    meta = _load_json_col(row["metadata"])
    if isinstance(meta, dict):
        out["metadata"] = meta
    storage = _load_json_col(row["storage"])
    if isinstance(storage, dict):
        out["storage"] = storage
    return out


def put_asset(record: dict[str, Any]) -> str:
    aid = str(record.get("asset_id") or "").strip()
    if not aid:
        raise ValueError("put_asset requires asset_id")
    now = _now()
    created_at = _unix_seconds(record.get("created_at"))
    expires_at = record.get("expires_at")
    expires_val = None if expires_at in (None, "") else _unix_seconds(expires_at)
    try:
        meta = _strip_url_keys(record.get("metadata"))
        storage = _strip_url_keys(record.get("storage"))
    except ValueError as exc:
        raise ValueError(f"asset {exc}") from exc
    origin = _opt_text(
        record.get("origin_intent_id") or record.get("intent_id")
    )
    producer = _opt_text(
        record.get("producer_capability")
        or record.get("producer")
        or record.get("creator")
    )
    edge = _opt_text(
        record.get("producer_edge_id") or record.get("edge_id") or record.get("owner")
    )
    size = _opt_int(record.get("size_bytes") if "size_bytes" in record else record.get("size"))
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO assets(
              asset_id, type, mime_type, status, producer_capability, producer_edge_id,
              origin_intent_id, origin_step, size_bytes, metadata, storage,
              created_at, updated_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
              type = excluded.type,
              mime_type = excluded.mime_type,
              status = excluded.status,
              producer_capability = excluded.producer_capability,
              producer_edge_id = excluded.producer_edge_id,
              origin_intent_id = excluded.origin_intent_id,
              origin_step = excluded.origin_step,
              size_bytes = excluded.size_bytes,
              metadata = excluded.metadata,
              storage = excluded.storage,
              updated_at = excluded.updated_at,
              expires_at = excluded.expires_at
            """,
            (
                aid,
                _norm_asset_type(record.get("type")),
                _opt_text(record.get("mime_type")),
                _norm_asset_status(record.get("status")),
                producer,
                edge,
                origin,
                _opt_int(record.get("origin_step")),
                size,
                _opt_json(meta),
                _opt_json(storage),
                created_at,
                now,
                expires_val,
            ),
        )
    if origin:
        put_asset_grant({"asset_id": aid, "intent_id": origin})
    return aid


def get_asset(asset_id: str) -> dict[str, Any] | None:
    aid = str(asset_id or "").strip()
    if not aid:
        return None
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM assets WHERE asset_id = ?", (aid,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_asset(row)


def _assets_filter_sql(
    *,
    include_deleted: bool = False,
    asset_type: str | None = None,
    producer_capability: str | None = None,
    created_since: float | None = None,
    created_until: float | None = None,
) -> tuple[str, list[Any]]:
    """Build WHERE clause + bind args for asset inventory queries."""
    clauses: list[str] = []
    args: list[Any] = []
    if not include_deleted:
        clauses.append("lower(status) != 'deleted'")
    type_raw = str(asset_type or "").strip().lower()
    if type_raw:
        clauses.append("lower(type) = ?")
        args.append(type_raw)
    producer = str(producer_capability or "").strip()
    if producer:
        clauses.append("producer_capability = ?")
        args.append(producer)
    if created_since is not None:
        clauses.append("created_at >= ?")
        args.append(float(created_since))
    if created_until is not None:
        clauses.append("created_at < ?")
        args.append(float(created_until))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, args


def count_assets(
    *,
    include_deleted: bool = False,
    asset_type: str | None = None,
    producer_capability: str | None = None,
    created_since: float | None = None,
    created_until: float | None = None,
) -> int:
    where, args = _assets_filter_sql(
        include_deleted=include_deleted,
        asset_type=asset_type,
        producer_capability=producer_capability,
        created_since=created_since,
        created_until=created_until,
    )
    with _lock:
        conn = _connect()
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM assets{where}",
            args,
        ).fetchone()
    return int(row["n"] if row is not None else 0)


def list_assets(
    *,
    include_deleted: bool = False,
    asset_type: str | None = None,
    producer_capability: str | None = None,
    created_since: float | None = None,
    created_until: float | None = None,
    limit: int | None = None,
    offset: int = 0,
    newest_first: bool = True,
) -> list[dict[str, Any]]:
    where, args = _assets_filter_sql(
        include_deleted=include_deleted,
        asset_type=asset_type,
        producer_capability=producer_capability,
        created_since=created_since,
        created_until=created_until,
    )
    order = "created_at DESC, asset_id DESC" if newest_first else "created_at ASC, asset_id ASC"
    sql = f"SELECT * FROM assets{where} ORDER BY {order}"
    bind = list(args)
    if limit is not None:
        lim = max(0, int(limit))
        off = max(0, int(offset))
        sql += " LIMIT ? OFFSET ?"
        bind.extend([lim, off])
    with _lock:
        conn = _connect()
        rows = conn.execute(sql, bind).fetchall()
    return [_row_to_asset(row) for row in rows]


def delete_asset(asset_id: str) -> bool:
    aid = str(asset_id or "").strip()
    if not aid:
        return False
    existing = get_asset(aid)
    if existing is None:
        return False
    existing["status"] = "deleted"
    put_asset(existing)
    return True


# --- Entity Registry (V1: type=device only) ---------------------------------


_ENTITY_TYPES_V1 = frozenset({"device"})


def _json_object(raw: Any, *, field: str) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"{field} must be a JSON object") from e
        if not isinstance(data, dict):
            raise ValueError(f"{field} must be a JSON object")
        return data
    raise ValueError(f"{field} must be a JSON object")


def _row_to_entity(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "entity_id": str(row["entity_id"]),
        "type": str(row["type"]),
        "name": str(row["name"]),
        "metadata": _json_object(row["metadata_json"], field="metadata"),
        "state": _json_object(row["state_json"], field="state"),
        "references": _json_object(row["references_json"], field="references"),
        "created_at_ms": int(row["created_at_ms"]),
        "updated_at_ms": int(row["updated_at_ms"]),
    }


def get_entity(entity_id: str) -> dict[str, Any] | None:
    eid = str(entity_id or "").strip()
    if not eid:
        return None
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM entities WHERE entity_id = ?", (eid,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_entity(row)


def list_entities(
    *,
    entity_type: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    et = str(entity_type or "").strip().lower()
    if et:
        clauses.append("type = ?")
        args.append(et)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM entities{where} ORDER BY name ASC, entity_id ASC"
    bind = list(args)
    if limit is not None:
        lim = max(0, int(limit))
        off = max(0, int(offset))
        sql += " LIMIT ? OFFSET ?"
        bind.extend([lim, off])
    with _lock:
        conn = _connect()
        rows = conn.execute(sql, bind).fetchall()
    return [_row_to_entity(row) for row in rows]


def upsert_entity(record: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace an entity. V1: type must be device."""
    if not isinstance(record, dict):
        raise ValueError("entity record must be an object")
    eid = str(record.get("entity_id") or "").strip()
    if not eid:
        raise ValueError("entity_id required")
    et = str(record.get("type") or "").strip().lower()
    if et not in _ENTITY_TYPES_V1:
        raise ValueError("type must be 'device' in Entity V1")
    name = str(record.get("name") or "").strip()
    if not name:
        raise ValueError("name required")
    metadata = _json_object(record.get("metadata"), field="metadata")
    state = _json_object(record.get("state"), field="state")
    references = _json_object(record.get("references"), field="references")
    now_ms = int(time.time() * 1000)
    existing = get_entity(eid)
    created_ms = int(record.get("created_at_ms") or 0) or (
        int(existing["created_at_ms"]) if existing else now_ms
    )
    updated_ms = int(record.get("updated_at_ms") or 0) or now_ms
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO entities(
              entity_id, type, name, metadata_json, state_json, references_json,
              created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
              type = excluded.type,
              name = excluded.name,
              metadata_json = excluded.metadata_json,
              state_json = excluded.state_json,
              references_json = excluded.references_json,
              updated_at_ms = excluded.updated_at_ms
            """,
            (
                eid,
                et,
                name,
                json.dumps(metadata, ensure_ascii=False),
                json.dumps(state, ensure_ascii=False),
                json.dumps(references, ensure_ascii=False),
                created_ms,
                updated_ms,
            ),
        )
    out = get_entity(eid)
    if out is None:
        raise RuntimeError(f"upsert_entity failed for {eid}")
    return out


def _row_to_grant(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "asset_id": str(row["asset_id"]),
        "intent_id": _job_identity(str(row["intent_id"])),
        "granted_at": row["granted_at"],
    }


def put_asset_grant(record: dict[str, Any]) -> None:
    aid = str(record.get("asset_id") or "").strip()
    iid = str(record.get("intent_id") or record.get("origin_intent_id") or "").strip()
    if not aid or not iid:
        raise ValueError("put_asset_grant requires asset_id and intent_id")
    now = _unix_seconds(record.get("granted_at") or record.get("created_at"))
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO asset_grants(asset_id, intent_id, granted_at)
            VALUES (?, ?, ?)
            ON CONFLICT(asset_id, intent_id) DO UPDATE SET
              granted_at = excluded.granted_at
            """,
            (aid, _intent_key(iid), now),
        )


def has_asset_grant(asset_id: str, intent_id: str | int) -> bool:
    aid = str(asset_id or "").strip()
    iid = _intent_key(intent_id)
    if not aid or not iid:
        return False
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT 1 FROM asset_grants WHERE asset_id = ? AND intent_id = ?",
            (aid, iid),
        ).fetchone()
    return row is not None


def list_asset_grants(
    asset_id: str | None = None,
    *,
    intent_id: str | int | None = None,
) -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        if asset_id is not None and str(asset_id).strip() != "":
            rows = conn.execute(
                "SELECT * FROM asset_grants WHERE asset_id = ? ORDER BY granted_at ASC",
                (str(asset_id).strip(),),
            ).fetchall()
        elif intent_id is not None and str(intent_id).strip() != "":
            rows = conn.execute(
                "SELECT * FROM asset_grants WHERE intent_id = ? ORDER BY granted_at ASC",
                (_intent_key(intent_id),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM asset_grants ORDER BY granted_at ASC, asset_id ASC"
            ).fetchall()
    return [_row_to_grant(row) for row in rows]


def list_participants(*, include_heartbeat: bool = True) -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        if include_heartbeat and _registrations_exists(conn):
            rows = conn.execute(
                _participant_select_with_heartbeat() + " ORDER BY p.participant_id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM participants ORDER BY participant_id"
            ).fetchall()
    return [_row_to_participant(row, include_heartbeat=include_heartbeat) for row in rows]


_POLICY_KINDS = frozenset({"role", "capability"})
_POLICY_ROLES = frozenset(_ROLE_KEYS)


def _policy_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "participant_id": str(row["participant_id"]),
        "target_kind": str(row["target_kind"]),
        "target_id": str(row["target_id"]),
        "enabled": bool(int(row["enabled"] or 0)),
        "updated_at": float(row["updated_at"] or 0),
    }


def _normalize_policy_target(target_kind: str, target_id: str) -> tuple[str, str]:
    kind = str(target_kind or "").strip().lower()
    tid = str(target_id or "").strip()
    if kind not in _POLICY_KINDS:
        raise ValueError("target_kind must be role or capability")
    if kind == "role":
        tid = _ROLE_ALIASES.get(tid.lower(), tid.lower())
        if tid not in _POLICY_ROLES:
            raise ValueError("target_id must be a registered role name")
    elif not tid:
        raise ValueError("target_id required")
    return kind, tid


def list_edge_control_policies(
    *, participant_id: str | None = None
) -> list[dict[str, Any]]:
    pid = str(participant_id or "").strip()
    with _lock:
        conn = _connect()
        if pid:
            rows = conn.execute(
                """
                SELECT * FROM edge_control_policy
                WHERE participant_id = ?
                ORDER BY target_kind, target_id
                """,
                (pid,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM edge_control_policy
                ORDER BY participant_id, target_kind, target_id
                """
            ).fetchall()
    return [_policy_row(row) for row in rows]


def load_control_policy_index() -> dict[tuple[str, str, str], bool]:
    out: dict[tuple[str, str, str], bool] = {}
    for row in list_edge_control_policies():
        out[(row["participant_id"], row["target_kind"], row["target_id"])] = bool(
            row["enabled"]
        )
    return out


def control_policy_allows(
    participant_id: str,
    target_kind: str,
    target_id: str,
    *,
    index: dict[tuple[str, str, str], bool] | None = None,
) -> bool:
    pid = str(participant_id or "").strip()
    if not pid:
        return False
    kind, tid = _normalize_policy_target(target_kind, target_id)
    table = index if index is not None else load_control_policy_index()
    key = (pid, kind, tid)
    if key not in table:
        return True
    return bool(table[key])


def put_edge_control_policy(
    *,
    participant_id: str,
    target_kind: str,
    target_id: str,
    enabled: bool,
) -> dict[str, Any]:
    pid = str(participant_id or "").strip()
    if not pid:
        raise ValueError("participant_id required")
    kind, tid = _normalize_policy_target(target_kind, target_id)
    now = _now()
    flag = 1 if enabled else 0
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO edge_control_policy(
              participant_id, target_kind, target_id, enabled, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(participant_id, target_kind, target_id) DO UPDATE SET
              enabled = excluded.enabled,
              updated_at = excluded.updated_at
            """,
            (pid, kind, tid, flag, now),
        )
    return {
        "participant_id": pid,
        "target_kind": kind,
        "target_id": tid,
        "enabled": bool(flag),
        "updated_at": now,
    }


def delete_edge_control_policy(
    *, participant_id: str, target_kind: str, target_id: str
) -> None:
    pid = str(participant_id or "").strip()
    kind, tid = _normalize_policy_target(target_kind, target_id)
    with _lock:
        conn = _connect()
        conn.execute(
            """
            DELETE FROM edge_control_policy
            WHERE participant_id = ? AND target_kind = ? AND target_id = ?
            """,
            (pid, kind, tid),
        )


def replace_edge_control_policies(
    participant_id: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pid = str(participant_id or "").strip()
    if not pid:
        raise ValueError("participant_id required")
    normalized: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        kind, tid = _normalize_policy_target(
            str(raw.get("target_kind") or ""),
            str(raw.get("target_id") or ""),
        )
        key = (kind, tid)
        if key in seen:
            continue
        seen.add(key)
        enabled = raw.get("enabled")
        if enabled is None:
            continue
        normalized.append((kind, tid, 1 if enabled else 0))
    now = _now()
    with _lock:
        conn = _connect()
        conn.execute(
            "DELETE FROM edge_control_policy WHERE participant_id = ?", (pid,)
        )
        for kind, tid, flag in normalized:
            conn.execute(
                """
                INSERT INTO edge_control_policy(
                  participant_id, target_kind, target_id, enabled, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (pid, kind, tid, flag, now),
            )
    return list_edge_control_policies(participant_id=pid)


def insert_admin_op_log(
    *,
    actor: str = "",
    action: str,
    participant_id: str = "",
    target_kind: str = "",
    target_id: str = "",
    extra: dict[str, Any] | list[Any] | None = None,
    result: str = "ok",
    summary: str = "",
) -> dict[str, Any]:
    act = str(action or "").strip()
    if not act:
        raise ValueError("action required")
    outcome = str(result or "").strip().lower() or "ok"
    if outcome not in ("ok", "error"):
        raise ValueError("result must be ok or error")
    now = _now()
    extra_raw = _dumps(extra) if extra is not None else None
    with _lock:
        conn = _connect()
        cur = conn.execute(
            """
            INSERT INTO admin_op_log(
              ts, actor, action, participant_id, target_kind, target_id,
              extra, result, summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                str(actor or ""),
                act,
                str(participant_id or "").strip(),
                str(target_kind or "").strip(),
                str(target_id or "").strip(),
                extra_raw,
                outcome,
                str(summary or ""),
            ),
        )
        row_id = int(cur.lastrowid or 0)
    return {
        "id": row_id,
        "ts": now,
        "actor": str(actor or ""),
        "action": act,
        "participant_id": str(participant_id or "").strip(),
        "target_kind": str(target_kind or "").strip(),
        "target_id": str(target_id or "").strip(),
        "extra": extra,
        "result": outcome,
        "summary": str(summary or ""),
    }


def list_admin_op_logs(*, limit: int = 100) -> list[dict[str, Any]]:
    try:
        cap = int(limit)
    except (TypeError, ValueError):
        cap = 100
    cap = max(1, min(cap, 200))
    with _lock:
        conn = _connect()
        rows = conn.execute(
            """
            SELECT * FROM admin_op_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (cap,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        extra = _loads(row["extra"]) if row["extra"] else None
        out.append(
            {
                "id": int(row["id"]),
                "ts": float(row["ts"] or 0),
                "actor": str(row["actor"] or ""),
                "action": str(row["action"] or ""),
                "participant_id": str(row["participant_id"] or ""),
                "target_kind": str(row["target_kind"] or ""),
                "target_id": str(row["target_id"] or ""),
                "extra": extra,
                "result": str(row["result"] or ""),
                "summary": str(row["summary"] or ""),
            }
        )
    return out


def _row_to_global_event(row: sqlite3.Row) -> dict[str, Any]:
    payload = _load_json_col(row["payload"])
    out: dict[str, Any] = {
        "event_id": int(row["event_id"]),
        "kind": str(row["kind"] or ""),
        "action": str(row["action"] or ""),
        "created_at": float(row["created_at"] or 0),
    }
    if row["subject"] is not None and str(row["subject"]).strip():
        out["subject"] = str(row["subject"])
    if isinstance(payload, dict):
        out["payload"] = payload
    elif row["payload"]:
        out["payload"] = row["payload"]
    if row["edge_id"] is not None and str(row["edge_id"]).strip():
        out["edge_id"] = str(row["edge_id"])
    if row["intent_id"] is not None and str(row["intent_id"]).strip():
        out["intent_id"] = str(row["intent_id"])
    return out


def append_global_event(record: dict[str, Any]) -> int:
    kind = str(record.get("kind") or "").strip()
    action = str(record.get("action") or "").strip()
    if not kind:
        raise ValueError("kind is required")
    if not action:
        raise ValueError("action is required")
    now = _unix_seconds(record.get("created_at"))
    with _lock:
        conn = _connect()
        cur = conn.execute(
            """
            INSERT INTO global_events(
              kind, action, subject, payload, edge_id, intent_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind,
                action,
                _opt_text(record.get("subject")),
                _opt_json(record.get("payload")),
                _opt_text(record.get("edge_id")),
                _opt_text(record.get("intent_id")),
                now,
            ),
        )
        return int(cur.lastrowid)


def list_global_events(
    *,
    kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    try:
        cap = int(limit)
    except (TypeError, ValueError):
        cap = 50
    cap = max(1, min(cap, 500))
    kind_s = str(kind or "").strip()
    with _lock:
        conn = _connect()
        try:
            if kind_s:
                rows = conn.execute(
                    """
                    SELECT * FROM global_events
                    WHERE kind = ?
                    ORDER BY event_id DESC
                    LIMIT ?
                    """,
                    (kind_s, cap),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM global_events
                    ORDER BY event_id DESC
                    LIMIT ?
                    """,
                    (cap,),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
    rows = list(reversed(rows))
    return [_row_to_global_event(row) for row in rows]


def resolve_active_mode() -> str | None:
    """Derive current household mode from append-only mode events."""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT action, subject FROM global_events
                WHERE kind = 'mode'
                ORDER BY event_id DESC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return None
    for row in rows:
        action = str(row["action"] or "").strip().lower()
        subject = str(row["subject"] or "").strip()
        if action == "activate" and subject:
            return subject
        if action == "deactivate":
            return None
    return None


def backup(dest: Path) -> Path:
    dest = dest.expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        src = _connect()
        with sqlite3.connect(str(dest)) as dst:
            src.backup(dst)
    return dest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Brain SQLite helper")
    parser.add_argument("cmd", choices=["init", "backup"])
    parser.add_argument("dest", nargs="?", help="backup destination path")
    args = parser.parse_args()
    if args.cmd == "init":
        path = init_db()
        print(path)
        return
    if not args.dest:
        raise SystemExit("backup requires a destination path")
    print(backup(Path(args.dest)))


if __name__ == "__main__":
    main()
