"""Agent Debug Gateway — User/Business Console → Issue → Dev Task → Dev Agent."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from debug_attachments import attachment_asset_ids, normalize_attachments
from debug_client_snapshot import merge_intent_context, normalize_client_snapshot
from debug_feedback_types import normalize_problem_type, problem_type_label
from debug_issue_store import DebugIssue, get_store
from dev_task import get_agent_task, submit_agent_task

log = logging.getLogger("debug_gateway")

_USER_MESSAGE = "已提交反馈，正在分析。"

GetIntentFn = Callable[[int], Optional[dict[str, Any]]]


def _json_preview(obj: Any, limit: int = 12000) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(obj)
    if len(text) > limit:
        return text[:limit] + "\n…(truncated)"
    return text


def build_intent_context(intent: dict[str, Any]) -> dict[str, Any]:
    """Collect execution现场 from a Brain intent/job record."""
    ident = intent.get("intent_id") or intent.get("id")
    ctx = intent.get("context") or intent.get("ctx_param") or {}
    if not isinstance(ctx, dict):
        ctx = {}
    return {
        "intent_id": ident,
        "session_id": str(intent.get("session_id") or ctx.get("session_id") or ""),
        "user_input": str(intent.get("text") or intent.get("utterance") or ""),
        "source": str(intent.get("source") or ""),
        "intent_status": str(intent.get("status") or intent.get("intent_status") or ""),
        "error": str(
            intent.get("error")
            or intent.get("msg")
            or intent.get("message")
            or ""
        ).strip(),
        "edge_id": str(intent.get("edge_id") or ""),
        "intent_origin": str(intent.get("intent_origin") or ""),
        "execution_plan": intent.get("execution_plan") or [],
        "step_log": intent.get("step_log") or intent.get("steps") or [],
        "status_log": intent.get("status_log") or [],
        "presentation": intent.get("presentation"),
        "context": ctx,
        "source_context": intent.get("source_context") or ctx.get("source_context"),
        "outputs": intent.get("outputs") or intent.get("exposed_outputs"),
        "missing_capabilities": intent.get("missing_capabilities") or [],
        "planner_cost_ms": intent.get("planner_cost_ms"),
        "created_at": intent.get("created_at") or intent.get("intent_base_time"),
    }


def build_agent_prompt(
    issue: DebugIssue,
    context: dict[str, Any],
    *,
    client_snapshot: dict[str, Any] | None = None,
) -> str:
    lines = [
        "@controller [debug-issue]",
        f"issue={issue.issue_id}",
        f"intent={issue.intent_id}",
        f"source={issue.source}",
        "",
        "[Dev Agent — Automated Debug Request]",
        "This request was created by Agent Debug Gateway from a User/Business Console report.",
        "Do NOT ask the reporter for more context; use the package below and Brain DB / logs / code.",
        "",
        f"issue_id={issue.issue_id}",
        f"intent_id={issue.intent_id}",
        f"session_id={issue.session_id or context.get('session_id') or '—'}",
        f"participant_id={issue.participant_id}",
        "",
        "## User Input",
        str(context.get("user_input") or "—"),
        "",
        "## Status / Error",
        f"status={context.get('intent_status') or '—'}",
        f"error={context.get('error') or '—'}",
        "",
        "## Execution Plan",
        _json_preview(context.get("execution_plan") or []),
        "",
        "## Step Log",
        _json_preview(context.get("step_log") or []),
        "",
        "## Status Timeline",
        _json_preview(context.get("status_log") or []),
    ]
    if issue.user_summary.strip():
        lines.extend(["", "## User Summary", issue.user_summary.strip()])
    problem_label = problem_type_label(issue.problem_type)
    if problem_label:
        lines.extend(["", "## Feedback Type", problem_label])
    if issue.attachments:
        lines.extend(["", "## User Attachments"])
        for row in issue.attachments:
            kind = row.get("kind") or "file"
            aid = row.get("asset_id") or "—"
            mime = row.get("mime_type") or ""
            name = row.get("filename") or ""
            detail = f"{kind} {aid}"
            if mime:
                detail += f" mime={mime}"
            if name:
                detail += f" name={name}"
            lines.append(f"- {detail}")
    if client_snapshot:
        snap = normalize_client_snapshot(client_snapshot)
        primary = snap.get("primary_brain")
        heartbeat = snap.get("heartbeat")
        runtime_log = snap.get("runtime_intent_log")
        if isinstance(primary, dict) and primary:
            lines.extend(["", "## Primary Brain", _json_preview(primary)])
        if isinstance(heartbeat, dict) and heartbeat:
            lines.extend(["", "## Heartbeat", _json_preview(heartbeat)])
        if isinstance(runtime_log, dict) and runtime_log:
            lines.extend(["", "## Runtime Intent Log", _json_preview(runtime_log)])
        elif snap:
            lines.extend(["", "## Client Snapshot", _json_preview(snap)])
    lines.extend(
        [
            "",
            "## Full Context JSON",
            _json_preview(context),
            "",
            "Respond in Chinese using exactly these two markdown sections (no extra top-level sections):",
            "",
            "## 根因分析",
            "(cite evidence from logs/context; explain the root cause only)",
            "",
            "## 修复建议",
            "List each fix as a separate item. Repeat this block for every item:",
            "",
            "### 建议 1：<short title>",
            "- 优先级：P0|P1|P2",
            "- 负责人：@brain|@runtime|@capability|@intent|@endpoint|@dba|@coordinator",
            "- 作用：<what this fix does>",
            "- 预期收益：<expected outcome after the fix>",
            "- 改法：<concrete steps or code changes>",
            "",
            "Do not repeat root-cause analysis here. Use one ### block per fix item.",
        ]
    )
    return "\n".join(lines)


def _participant_matches_intent(intent: dict[str, Any], participant_id: str) -> bool:
    pid = participant_id.strip()
    if not pid:
        return False
    edge = str(intent.get("edge_id") or "").strip()
    if edge and edge == pid:
        return True
    ctx = intent.get("context") or intent.get("ctx_param") or {}
    if isinstance(ctx, dict):
        for key in ("participant_id", "edge_id", "client_hint"):
            if str(ctx.get(key) or "").strip() == pid:
                return True
    return False


def issue_to_user_view(issue: DebugIssue) -> dict[str, Any]:
    return {
        "issue_id": issue.issue_id,
        "intent_id": issue.intent_id,
        "status": issue.status,
        "message": _USER_MESSAGE,
        "task_id": issue.task_id,
    }


def issue_to_admin_view(issue: DebugIssue, *, dev_task: dict[str, Any] | None = None) -> dict[str, Any]:
    view = {
        "issue_id": issue.issue_id,
        "intent_id": issue.intent_id,
        "session_id": issue.session_id,
        "source": issue.source,
        "participant_id": issue.participant_id,
        "status": issue.status,
        "user_summary": issue.user_summary,
        "problem_type": issue.problem_type,
        "problem_type_label": problem_type_label(issue.problem_type),
        "attachments": list(issue.attachments or []),
        "attachment_asset_ids": attachment_asset_ids(issue.attachments),
        "task_id": issue.task_id,
        "error": issue.error,
        "context": issue.context,
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
    }
    if dev_task:
        view["dev_task"] = dev_task
    return view


def submit_debug_report(
    *,
    intent_id: int,
    participant_id: str,
    source: str = "user_console",
    user_summary: str = "",
    problem_type: str = "",
    attachments: list[dict[str, str]] | None = None,
    client_snapshot: dict[str, Any] | None = None,
    get_intent: GetIntentFn,
) -> dict[str, Any]:
    """Create Issue + Dev Task from current intent execution现场."""
    intent = get_intent(intent_id)
    if not intent:
        return {"ok": False, "error": "intent not found"}

    pid = participant_id.strip()
    if not _participant_matches_intent(intent, pid):
        return {"ok": False, "error": "participant_id does not match intent issuer"}

    normalized_type = normalize_problem_type(problem_type)
    if problem_type.strip() and not normalized_type:
        return {"ok": False, "error": "invalid problem_type"}

    context = merge_intent_context(build_intent_context(intent), client_snapshot)
    summary = user_summary.strip()
    if not summary and normalized_type:
        summary = problem_type_label(normalized_type)
    store = get_store()
    issue = store.create(
        intent_id=intent_id,
        session_id=str(context.get("session_id") or ""),
        source=source.strip() or "user_console",
        participant_id=pid,
        user_summary=summary,
        problem_type=normalized_type,
        attachments=normalize_attachments(attachments),
        context=context,
    )

    prompt = build_agent_prompt(issue, context, client_snapshot=client_snapshot)
    task_view = submit_agent_task(prompt, category="bug_fix")
    task_id = task_view.get("task_id") or task_view.get("intent_id")
    try:
        task_id_int = int(task_id)
    except (TypeError, ValueError):
        task_id_int = None

    if task_id_int:
        store.update(issue.issue_id, task_id=task_id_int, status="analyzing")
        issue = store.get(issue.issue_id) or issue
    else:
        err = str(task_view.get("msg") or task_view.get("error") or "dev task not created")
        store.update(issue.issue_id, status="failed", error=err)
        issue = store.get(issue.issue_id) or issue
        return {
            "ok": False,
            "error": err,
            "issue_id": issue.issue_id,
            "intent_id": issue.intent_id,
        }

    log.info(
        "debug_report issue=%s intent=%s task=%s source=%s",
        issue.issue_id,
        issue.intent_id,
        task_id_int,
        issue.source,
    )
    return {"ok": True, **issue_to_user_view(issue)}


def get_debug_issue(issue_id: int) -> dict[str, Any] | None:
    issue = get_store().get(issue_id)
    if issue is None:
        return None
    dev_task = None
    if issue.task_id:
        dev_task = get_agent_task(issue.task_id)
    return issue_to_admin_view(issue, dev_task=dev_task)


def list_debug_issues(
    *,
    before_id: int | None = None,
    limit: int = 30,
    intent_id: int | None = None,
) -> dict[str, Any]:
    issues, exhausted = get_store().list_issues(
        before_id=before_id,
        limit=limit,
        intent_id=intent_id,
    )
    rows = []
    for issue in issues:
        dev_task = get_agent_task(issue.task_id) if issue.task_id else None
        rows.append(issue_to_admin_view(issue, dev_task=dev_task))
    next_before = rows[-1]["issue_id"] if rows else None
    return {
        "issues": rows,
        "limit": limit,
        "before_id": before_id,
        "next_before_id": next_before,
        "exhausted": exhausted,
    }
