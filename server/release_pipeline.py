"""Release / deploy pipeline: git → test → approve → deploy, with audit trail.

Ingests Chatbox `[release]` events and exposes Deploy Authority actions for Dev Console.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

import agent_chat
import dev_console_db
from agent_fleet import wake_fleet_agent

log = logging.getLogger("release_pipeline")

STAGES = (
    "committed",
    "test_requested",
    "tested",
    "deploy_requested",
    "deployed",
    "skipped",
    "approved",
    "rejected",
)

PIPELINE_NODES = ("committed", "tested", "approved", "deployed")

_STAGE_RE = re.compile(
    r"\[release\][^\n]*?\bstage\s*=\s*([a-z_]+)",
    re.IGNORECASE,
)
_SHA_RE = re.compile(r"\bsha\s*=\s*([0-9a-fA-F]{7,40})\b")
_SCOPE_RE = re.compile(r"\bscope\s*=\s*([^\s]+)")
_SUMMARY_RE = re.compile(r"\bsummary\s*=\s*(.+?)(?:\s+\w+=|$)", re.DOTALL)
_TARGET_RE = re.compile(r"\btarget\s*=\s*([^\s]+)")
_RESULT_RE = re.compile(r"\bresult\s*=\s*(pass|fail|ok|failed)\b", re.IGNORECASE)
_NOTE_RE = re.compile(r"\bnote\s*=\s*(.+?)(?:\s+\w+=|$)", re.DOTALL)


def _now() -> float:
    return time.time()


def _connect() -> sqlite3.Connection:
    return dev_console_db._connect()


def ensure_schema() -> None:
    conn = _connect()
    conn.executescript(
        """
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
    conn.commit()


def _next_id() -> int:
    n = dev_console_db.meta_get_int("release_candidates_next_id", 1)
    dev_console_db.meta_set_int("release_candidates_next_id", n + 1)
    return n


@dataclass
class ReleaseEvent:
    stage: str
    sha: str
    scope: str = ""
    summary: str = ""
    target: str = ""
    result: str = ""
    note: str = ""
    by_handle: str = ""
    at: float = 0.0
    chat_msg_id: int = 0
    raw: str = ""


def parse_release_body(
    body: str,
    *,
    from_handle: str = "",
    at: float = 0.0,
    msg_id: int = 0,
) -> ReleaseEvent | None:
    text = str(body or "").strip()
    if "[release]" not in text.lower():
        return None
    stage_m = _STAGE_RE.search(text)
    sha_m = _SHA_RE.search(text)
    if not stage_m or not sha_m:
        return None
    stage = stage_m.group(1).strip().lower()
    if stage not in STAGES:
        return None
    sha = sha_m.group(1).strip().lower()
    scope = _SCOPE_RE.search(text).group(1).strip() if _SCOPE_RE.search(text) else ""
    summary = ""
    sm = _SUMMARY_RE.search(text)
    if sm:
        summary = sm.group(1).strip()
    target = _TARGET_RE.search(text).group(1).strip() if _TARGET_RE.search(text) else ""
    result = ""
    rm = _RESULT_RE.search(text)
    if rm:
        result = rm.group(1).strip().lower()
        if result in ("ok", "pass"):
            result = "pass"
        elif result == "failed":
            result = "fail"
    note = ""
    nm = _NOTE_RE.search(text)
    if nm:
        note = nm.group(1).strip()
    return ReleaseEvent(
        stage=stage,
        sha=sha,
        scope=scope,
        summary=summary,
        target=target,
        result=result,
        note=note,
        by_handle=str(from_handle or "").strip(),
        at=float(at or _now()),
        chat_msg_id=int(msg_id or 0),
        raw=text[:2000],
    )


def _sha_short(sha: str) -> str:
    s = str(sha or "").strip().lower()
    return s[:7] if len(s) >= 7 else s


def _loads_stages(raw: str | None) -> list[dict[str, Any]]:
    try:
        stages = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(stages, list):
        return []
    return [s for s in stages if isinstance(s, dict)]


def _status_from_stages(stages: list[dict[str, Any]], *, rejected: bool = False) -> str:
    if rejected:
        return "rejected"
    names = {str(s.get("stage") or "") for s in stages}
    if "deployed" in names:
        return "deployed"
    if "skipped" in names:
        return "skipped"
    if "rejected" in names:
        return "rejected"
    if "deploy_requested" in names:
        return "deploying"
    if "approved" in names:
        return "approved"
    failed = any(
        str(s.get("stage")) == "tested" and str(s.get("result") or "") == "fail"
        for s in stages
    )
    if failed:
        return "test_failed"
    if "tested" in names:
        return "awaiting_approval"
    if "committed" in names or "test_requested" in names:
        return "in_progress"
    return "in_progress"


def _row_to_view(data: dict[str, Any]) -> dict[str, Any]:
    stages = _loads_stages(str(data.get("stages_json") or "[]"))
    stage_names = [str(s.get("stage") or "") for s in stages]
    pipeline = []
    for node in PIPELINE_NODES:
        if node == "tested":
            done = "tested" in stage_names and not any(
                str(s.get("stage")) == "tested" and str(s.get("result") or "") == "fail"
                for s in stages
            )
        elif node == "approved":
            done = (
                "approved" in stage_names
                or "deploy_requested" in stage_names
                or "deployed" in stage_names
            )
        else:
            done = node in stage_names
        pipeline.append({"node": node, "done": done})
    status = str(data.get("status") or "")
    can_approve = status == "awaiting_approval"
    can_reject = status not in ("deployed", "rejected", "skipped")
    return {
        "release_id": int(data["release_id"]),
        "sha": str(data.get("sha") or ""),
        "sha_short": str(data.get("sha_short") or ""),
        "scope": str(data.get("scope") or ""),
        "summary": str(data.get("summary") or ""),
        "target": str(data.get("target") or "cloud-brain"),
        "status": status,
        "stages": stages,
        "pipeline": pipeline,
        "created_at": float(data.get("created_at") or 0),
        "updated_at": float(data.get("updated_at") or 0),
        "approved_by": str(data.get("approved_by") or ""),
        "approved_at": data.get("approved_at"),
        "rejected_by": str(data.get("rejected_by") or ""),
        "rejected_at": data.get("rejected_at"),
        "reject_note": str(data.get("reject_note") or ""),
        "deploy_run_id": str(data.get("deploy_run_id") or ""),
        "can_approve": can_approve,
        "can_reject": can_reject,
    }


def _find_by_sha(conn: sqlite3.Connection, sha: str) -> dict[str, Any] | None:
    short = _sha_short(sha)
    full = str(sha or "").strip().lower()
    row = conn.execute(
        """
        SELECT * FROM release_candidates
        WHERE sha = ? OR sha_short = ? OR sha LIKE ?
        ORDER BY updated_at DESC LIMIT 1
        """,
        (full, short, f"{short}%"),
    ).fetchone()
    return dict(row) if row else None


def apply_event(event: ReleaseEvent) -> dict[str, Any]:
    ensure_schema()
    with dev_console_db.locked():
        conn = _connect()
        existing = _find_by_sha(conn, event.sha)
        now = event.at or _now()
        stage_entry = {
            "stage": event.stage,
            "at": now,
            "by": event.by_handle,
            "result": event.result,
            "note": event.note,
            "chat_msg_id": event.chat_msg_id,
        }
        if existing:
            stages = _loads_stages(str(existing.get("stages_json") or "[]"))
            if event.chat_msg_id:
                for s in stages:
                    if (
                        int(s.get("chat_msg_id") or 0) == event.chat_msg_id
                        and str(s.get("stage") or "") == event.stage
                    ):
                        return _row_to_view(existing)
            stages.append(stage_entry)
            scope = event.scope or str(existing.get("scope") or "")
            summary = event.summary or str(existing.get("summary") or "")
            target = event.target or str(existing.get("target") or "cloud-brain")
            prev_sha = str(existing.get("sha") or "")
            sha = event.sha if len(event.sha) >= len(prev_sha) else prev_sha
            status = _status_from_stages(stages, rejected=bool(existing.get("rejected_at")))
            if event.stage == "rejected":
                status = "rejected"
            msg_id = max(
                int(existing.get("last_chat_msg_id") or 0),
                int(event.chat_msg_id or 0),
            )
            conn.execute(
                """
                UPDATE release_candidates SET
                  sha=?, sha_short=?, scope=?, summary=?, target=?, status=?,
                  stages_json=?, updated_at=?, last_chat_msg_id=?
                WHERE release_id=?
                """,
                (
                    sha,
                    _sha_short(sha),
                    scope,
                    summary,
                    target,
                    status,
                    json.dumps(stages, ensure_ascii=False),
                    now,
                    msg_id,
                    int(existing["release_id"]),
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM release_candidates WHERE release_id=?",
                (int(existing["release_id"]),),
            ).fetchone()
            return _row_to_view(dict(row) if row else existing)

        rid = _next_id()
        stages = [stage_entry]
        status = _status_from_stages(stages)
        conn.execute(
            """
            INSERT INTO release_candidates(
              release_id, sha, sha_short, scope, summary, target, status,
              stages_json, created_at, updated_at, last_chat_msg_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rid,
                event.sha,
                _sha_short(event.sha),
                event.scope,
                event.summary,
                event.target or "cloud-brain",
                status,
                json.dumps(stages, ensure_ascii=False),
                now,
                now,
                int(event.chat_msg_id or 0),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM release_candidates WHERE release_id=?",
            (rid,),
        ).fetchone()
        return _row_to_view(dict(row) if row else {"release_id": rid, "stages_json": "[]"})


def sync_from_chat(*, since_id: int | None = None) -> dict[str, Any]:
    """Pull Chatbox messages and ingest `[release]` events."""
    ensure_schema()
    conn = _connect()
    if since_id is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(last_chat_msg_id), 0) AS m FROM release_candidates"
        ).fetchone()
        watermark = int(row["m"] if row else 0)
        watermark = max(watermark, dev_console_db.meta_get_int("release_chat_since_id", 0))
    else:
        watermark = max(0, int(since_id))

    view = agent_chat.get_chat_view(since_id=watermark)
    messages = view.get("messages") or []
    ingested = 0
    max_id = watermark
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        msg_id = int(msg.get("id") or 0)
        if msg_id > max_id:
            max_id = msg_id
        body = str(msg.get("body") or "")
        if "[release]" not in body.lower():
            continue
        sender = str(msg.get("from") or msg.get("from_handle") or "")
        created = msg.get("created_at")
        try:
            at = float(created) if created is not None else _now()
        except (TypeError, ValueError):
            at = _now()
        event = parse_release_body(body, from_handle=sender, at=at, msg_id=msg_id)
        if not event:
            continue
        apply_event(event)
        ingested += 1
    dev_console_db.meta_set_int("release_chat_since_id", max_id)
    return {
        "ok": True,
        "chat_ok": bool(view.get("chat_ok")),
        "ingested": ingested,
        "since_id": watermark,
        "last_id": max_id,
        "chat_error": view.get("error") or "",
    }


def list_releases(*, limit: int = 50, status: str = "") -> dict[str, Any]:
    ensure_schema()
    sync = sync_from_chat()
    lim = max(1, min(int(limit or 50), 200))
    conn = _connect()
    if status.strip():
        rows = conn.execute(
            """
            SELECT * FROM release_candidates
            WHERE status = ?
            ORDER BY updated_at DESC LIMIT ?
            """,
            (status.strip(), lim),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM release_candidates
            ORDER BY updated_at DESC LIMIT ?
            """,
            (lim,),
        ).fetchall()
    items = [_row_to_view(dict(r)) for r in rows]
    awaiting = sum(1 for r in items if r.get("status") == "awaiting_approval")
    in_flight = sum(
        1
        for r in items
        if r.get("status") in ("in_progress", "approved", "deploying", "test_failed")
    )
    return {
        "ok": True,
        "releases": items,
        "counts": {
            "awaiting_approval": awaiting,
            "in_flight": in_flight,
            "total": len(items),
        },
        "pipeline_nodes": list(PIPELINE_NODES),
        "sync": sync,
    }


def get_release(release_id: int) -> dict[str, Any] | None:
    ensure_schema()
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM release_candidates WHERE release_id=?",
        (int(release_id),),
    ).fetchone()
    if not row:
        return None
    return _row_to_view(dict(row))


def approve_release(release_id: int, *, by: str = "boss", note: str = "") -> dict[str, Any]:
    """Deploy Authority: approve → record + wake @deploy with sha."""
    ensure_schema()
    with dev_console_db.locked():
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM release_candidates WHERE release_id=?",
            (int(release_id),),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "release not found"}
        data = dict(row)
        view = _row_to_view(data)
        if not view.get("can_approve"):
            return {
                "ok": False,
                "error": f"cannot approve status={view.get('status')}",
                "release": view,
            }
        now = _now()
        stages = _loads_stages(str(data.get("stages_json") or "[]"))
        stages.append(
            {
                "stage": "approved",
                "at": now,
                "by": by,
                "note": note,
                "result": "",
                "chat_msg_id": 0,
            }
        )
        sha = str(data.get("sha") or "")
        target = str(data.get("target") or "cloud-brain")
        summary = str(data.get("summary") or "")
        wake_text = (
            "Deploy Authority approved release.\n"
            f"sha={sha}\n"
            f"target={target}\n"
            f"summary={summary or '—'}\n"
            "Follow cloud-deploy.mdc. After deploy, push_msg "
            f"@controller [release] stage=deployed sha={_sha_short(sha)} target={target}"
        )
        wake = wake_fleet_agent("deploy", text=wake_text)
        run_id = str(wake.get("run_id") or "")
        stages.append(
            {
                "stage": "deploy_requested",
                "at": now,
                "by": by,
                "note": f"wake @deploy run={run_id}",
                "result": "",
                "chat_msg_id": 0,
            }
        )
        conn.execute(
            """
            UPDATE release_candidates SET
              status=?, stages_json=?, updated_at=?,
              approved_by=?, approved_at=?, deploy_run_id=?
            WHERE release_id=?
            """,
            (
                "deploying",
                json.dumps(stages, ensure_ascii=False),
                now,
                by,
                now,
                run_id,
                int(release_id),
            ),
        )
        conn.commit()

    chat_body = (
        f"@controller @deploy [release] stage=deploy_requested "
        f"sha={_sha_short(sha)} target={target} "
        f"summary=approved-by-{by}"
    )
    try:
        agent_chat.send_boss_message(chat_body)
    except agent_chat.AgentChatError as err:
        log.warning("release approve chat notify failed: %s", err)

    return {
        "ok": True,
        "release": get_release(release_id),
        "wake": wake,
    }


def reject_release(release_id: int, *, by: str = "boss", note: str = "") -> dict[str, Any]:
    ensure_schema()
    with dev_console_db.locked():
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM release_candidates WHERE release_id=?",
            (int(release_id),),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "release not found"}
        data = dict(row)
        view = _row_to_view(data)
        if view.get("status") in ("deployed", "rejected", "skipped"):
            return {
                "ok": False,
                "error": f"cannot reject status={view.get('status')}",
                "release": view,
            }
        now = _now()
        stages = _loads_stages(str(data.get("stages_json") or "[]"))
        stages.append(
            {
                "stage": "rejected",
                "at": now,
                "by": by,
                "note": note,
                "result": "",
                "chat_msg_id": 0,
            }
        )
        conn.execute(
            """
            UPDATE release_candidates SET
              status='rejected', stages_json=?, updated_at=?,
              rejected_by=?, rejected_at=?, reject_note=?
            WHERE release_id=?
            """,
            (
                json.dumps(stages, ensure_ascii=False),
                now,
                by,
                now,
                note,
                int(release_id),
            ),
        )
        conn.commit()
        sha = str(data.get("sha_short") or data.get("sha") or "")

    try:
        agent_chat.send_boss_message(
            f"@controller [release] stage=rejected sha={sha} note={note or 'rejected-by-boss'}"
        )
    except agent_chat.AgentChatError as err:
        log.warning("release reject chat notify failed: %s", err)

    return {"ok": True, "release": get_release(release_id)}
