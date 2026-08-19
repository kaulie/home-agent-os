"""Brain SQLite: schema migrate, jobs, pull queue, participants.

Phase 1 replaces in-memory dicts in the Flask stubs. Nested wire payloads stay JSON.
"""

from __future__ import annotations

import json
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

_SQL_DIR = Path(__file__).resolve().parent / "sql"
_DEFAULT_DB = Path(__file__).resolve().parent / "data" / "brain.sqlite3"

_lock = threading.RLock()
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


_JOB_TEXT_COLS = (
    "job_id",
    "text",
    "source",
    "edge_id",
    "assigned_edge_id",
    "edge_node_id",
    "scheduler_node",
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
)


def _opt_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


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


def _job_identity(intent_id: str) -> Any:
    return int(intent_id) if intent_id.isdigit() else intent_id


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    iid = str(row["intent_id"])
    ident = _job_identity(iid)
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
        raw = row[col]
        if raw is None or raw == "":
            if col == "execution_plan":
                job[col] = []
            continue
        parsed = _loads(raw) if isinstance(raw, str) else raw
        if parsed is not None:
            job[col] = deepcopy(parsed) if isinstance(parsed, (dict, list)) else parsed
    return job


def put_job(job: dict[str, Any]) -> None:
    iid = _intent_key(job.get("intent_id") or job.get("id") or "")
    if not iid:
        raise ValueError("put_job requires intent_id")
    status = str(job.get("status") or job.get("intent_status") or "").strip()
    assigned = str(job.get("assigned_edge_id") or "").strip() or None
    created = _unix_seconds(job.get("created_at"))
    updated = _unix_seconds(job.get("updated_at"))
    values = (
        iid,
        _opt_text(job.get("job_id") or iid),
        status,
        _opt_text(job.get("text")),
        _opt_text(job.get("source")),
        _opt_text(job.get("edge_id")),
        assigned,
        _opt_text(job.get("edge_node_id")),
        _opt_text(job.get("scheduler_node")),
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
    )
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO jobs(
              intent_id, job_id, status, text, source, edge_id, assigned_edge_id,
              edge_node_id, scheduler_node, error, msg, detail, command_id,
              base_time, intent_base_time, created_at, updated_at,
              execution_plan, steps, step_log, status_log, ctx_param, context,
              outputs, step_outputs, presentation, pending_delivery
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(intent_id) DO UPDATE SET
              job_id = excluded.job_id,
              status = excluded.status,
              text = excluded.text,
              source = excluded.source,
              edge_id = excluded.edge_id,
              assigned_edge_id = excluded.assigned_edge_id,
              edge_node_id = excluded.edge_node_id,
              scheduler_node = excluded.scheduler_node,
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
              pending_delivery = excluded.pending_delivery
            """,
            values,
        )


def get_job(intent_id: str | int) -> dict[str, Any] | None:
    iid = _intent_key(intent_id)
    if not iid:
        return None
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
            "SELECT * FROM jobs ORDER BY CAST(intent_id AS INTEGER) DESC"
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
            sql += " AND CAST(intent_id AS INTEGER) < ?"
            params.append(before)
    sql += " ORDER BY CAST(intent_id AS INTEGER) DESC LIMIT ?"
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
            ORDER BY created_at ASC, CAST(intent_id AS INTEGER) ASC
            """
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def get_queue_item(intent_id: str | int) -> dict[str, Any] | None:
    return get_job(intent_id)


def upsert_queue(item: dict[str, Any]) -> dict[str, Any]:
    iid = _intent_key(item.get("id") or item.get("intent_id") or "")
    if not iid:
        raise ValueError("upsert_queue requires item.id")
    existing = get_job(iid)
    stored: dict[str, Any] = dict(existing) if existing else {}
    stored.update(item)
    ident = _job_identity(iid)
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
    if row["cost_ms"] is not None:
        out["cost_ms"] = int(row["cost_ms"])
    parsed = _load_json_col(row["parsed_json"])
    if parsed is not None:
        out["parsed_json"] = parsed
    plan = _load_json_col(row["execution_plan"])
    if plan is not None:
        out["execution_plan"] = plan
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
              raw_response, parsed_json, execution_plan, error, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def _row_to_participant(row: sqlite3.Row, *, include_heartbeat: bool) -> dict[str, Any]:
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
    services = _load_json_col(row["services"])
    out["services"] = services if isinstance(services, list) else []
    for col in ("intent_sources", "endpoints"):
        parsed = _load_json_col(row[col])
        if parsed is not None:
            out[col] = parsed
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
    else:
        if row["server_received_at"] is not None:
            out["server_received_at"] = row["server_received_at"]
        if row["schedule_eligible"] is not None:
            out["schedule_eligible"] = bool(row["schedule_eligible"])
    return out


def put_registration(record: dict[str, Any]) -> None:
    pid = str(record.get("participant_id") or record.get("edge_id") or "").strip()
    if not pid:
        raise ValueError("put_registration requires participant_id")
    roles = _roles_from_record(record)
    now = _now()
    registered_at = float(record.get("registered_at") or now)
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO participants(
              participant_id, client_hint, display_name, device_type, location, app_version,
              status, registered_at, updated_at,
              role_intent_source, role_runtime, role_endpoint, role_observer,
              services, intent_sources, endpoints
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
              endpoints = excluded.endpoints
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
            ),
        )


def get_registration(edge_id: str) -> dict[str, Any] | None:
    pid = str(edge_id or "").strip()
    if not pid:
        return None
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM participants WHERE participant_id = ?", (pid,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_participant(row, include_heartbeat=False)


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


def put_heartbeat(edge_id: str, info: dict[str, Any]) -> None:
    pid = str(edge_id or "").strip()
    if not pid:
        raise ValueError("put_heartbeat requires participant_id")
    eligible = info.get("schedule_eligible")
    if eligible is None:
        eligible_int = None
    else:
        eligible_int = 1 if eligible else 0
    with _lock:
        conn = _connect()
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
                float(info["reported_at"]) if info.get("reported_at") is not None else None,
                float(info["server_received_at"])
                if info.get("server_received_at") is not None
                else None,
                _opt_json(info.get("services")),
                _now(),
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


def list_heartbeats() -> dict[str, dict[str, Any]]:
    with _lock:
        conn = _connect()
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


def list_assets(*, include_deleted: bool = False) -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        if include_deleted:
            rows = conn.execute(
                "SELECT * FROM assets ORDER BY created_at ASC, asset_id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM assets
                WHERE lower(status) != 'deleted'
                ORDER BY created_at ASC, asset_id ASC
                """
            ).fetchall()
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
