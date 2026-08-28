"""Agent tasks for HomeAgent Admin — routed to agent-bridge, not Brain intents."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import agent_bridge_client as bridge
from agent_task_store import AgentTask, get_store
from dev_task_attachments import (
    attachment_scope,
    build_dev_task_agent_text,
    dev_task_attachment_asset_ids,
    grant_attachments_for_task,
    normalize_dev_task_attachments,
)
from dev_task_category import category_meta, list_categories, normalize_category
from token_usage import add_usage, empty_usage_summary, normalize_token_usage

log = logging.getLogger("dev_task")

try:
    from chat.push_client import push_msg as _chat_push
except ImportError:  # pragma: no cover
    _chat_push = None

_TERMINAL_STATUSES = frozenset({"succeeded", "success", "completed", "failed", "error", "cancelled"})

_active_lock = threading.Lock()
_active_task_ids: set[int] = set()
_poller_started = False


def _reconcile_active_tasks() -> None:
    """Re-track non-terminal tasks after Brain restart."""
    store = get_store()
    rows, _ = store.list_tasks(limit=500)
    tracked = 0
    with _active_lock:
        for task in rows:
            status = str(task.status or "").strip().lower()
            if status not in _TERMINAL_STATUSES:
                _active_task_ids.add(int(task.task_id))
                tracked += 1
    if tracked:
        log.info("reconciled %s active agent task(s) for polling", tracked)


def _notify_chat(event: str, *, task_id: int, text: str = "", detail: str = "", status: str = "") -> None:
    if _chat_push is None:
        return
    parts = ["@controller", "[dev-task]", event, f"task={task_id}"]
    if status:
        parts.append(f"status={status}")
    if text:
        parts.append(f"task={text[:200]}")
    if detail:
        parts.append(detail[:400])
    body = " ".join(p for p in parts if p)
    if not _chat_push("brain", body):
        log.debug("chat notify skipped")


def _extract_answer_text(run: dict[str, Any]) -> str:
    result = str(run.get("result") or "").strip()
    if result:
        return result
    events = run.get("events") or []
    if isinstance(events, list):
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            if event.get("type") == "assistant":
                text = str(event.get("text") or "").strip()
                if text:
                    return text
    return ""


def _thread_category(task: AgentTask | dict[str, Any]) -> str:
    row = task if isinstance(task, dict) else task.to_dict()
    store = get_store()
    root_id = int(row.get("thread_id") or row["task_id"])
    root = store.get(root_id)
    if root is not None:
        return normalize_category(root.category)
    return normalize_category(row.get("category"))


def _usage_from_run(run: dict[str, Any]) -> dict[str, int]:
    return normalize_token_usage(run.get("usage"))


def _apply_usage_update(task_id: int, run: dict[str, Any]) -> None:
    usage = _usage_from_run(run)
    if usage:
        get_store().update(task_id, token_usage=usage)


def _thread_token_usage(task_id: int) -> dict[str, int]:
    store = get_store()
    task = store.get(int(task_id))
    if task is None:
        return empty_usage_summary()
    thread_id = int(task.thread_id or task.task_id)
    messages, _ = store.list_tasks(thread_id=thread_id, limit=100)
    totals = empty_usage_summary()
    for row in messages:
        usage = normalize_token_usage(row.token_usage)
        if usage:
            add_usage(totals, usage)
    return totals


def task_to_api_view(task: AgentTask | dict[str, Any]) -> dict[str, Any]:
    row = task if isinstance(task, dict) else task.to_dict()
    task_id = int(row["task_id"])
    status = str(row.get("status") or "")
    result = str(row.get("result") or "").strip()
    error = str(row.get("error") or "").strip()
    cat = _thread_category(row)
    terminal = status in ("succeeded", "success", "completed", "failed", "error", "cancelled")
    finished_at = row.get("updated_at") if terminal else None
    token_usage = normalize_token_usage(row.get("token_usage"))
    thread_id = int(row.get("thread_id") or task_id)
    attachments = list(row.get("attachments") or [])
    return {
        "task_id": task_id,
        "intent_id": task_id,
        "task_kind": "dev_task",
        "text": row.get("text") or "",
        "attachments": attachments,
        "attachment_asset_ids": dev_task_attachment_asset_ids(attachments),
        "attachment_scope": attachment_scope(task_id),
        "status": status,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "finished_at": finished_at,
        "msg": error,
        "result_text": result,
        "status_log": row.get("status_log") or [],
        "thread_id": thread_id,
        "parent_task_id": row.get("parent_task_id"),
        "token_usage": token_usage or None,
        "thread_token_usage": _thread_token_usage(task_id),
        **category_meta(cat),
        "dev_task": {
            "bridge_run_id": row.get("bridge_run_id") or "",
            "bridge_url": row.get("bridge_url") or "",
            "bridge_status": row.get("bridge_status") or "",
            "queue_depth": row.get("queue_depth"),
            "events": row.get("events") or [],
            "result": result or None,
            "error": error or None,
            "token_usage": token_usage or None,
            "updated_at": int(float(row.get("updated_at") or time.time()) * 1000),
        },
    }


def submit_agent_task(
    text: str,
    *,
    parent_task_id: int | None = None,
    thread_id: int | None = None,
    category: str | None = None,
    attachments: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Create an agent task and forward it to agent-bridge."""
    store = get_store()
    normalized_attachments = normalize_dev_task_attachments(attachments)
    trimmed_text = str(text or "").strip()
    if not trimmed_text and not normalized_attachments:
        task = store.create("")
        store.append_status(task.task_id, "failed", msg="text or attachments required")
        store.update(task.task_id, status="failed", error="text or attachments required")
        return task_to_api_view(store.get(task.task_id) or task)
    if parent_task_id is not None:
        parent = store.get(int(parent_task_id))
        if parent is None:
            task = store.create(
                trimmed_text,
                attachments=normalized_attachments,
            )
            store.append_status(task.task_id, "failed", msg="parent task not found")
            store.update(task.task_id, status="failed", error="parent task not found")
            return task_to_api_view(store.get(task.task_id) or task)

    if not bridge.bridge_enabled():
        task = store.create(
            trimmed_text,
            thread_id=thread_id,
            parent_task_id=parent_task_id,
            category=category,
            attachments=normalized_attachments,
        )
        if normalized_attachments:
            grant_attachments_for_task(task.task_id, normalized_attachments)
        store.append_status(task.task_id, "failed", msg="agent-bridge 未启用")
        store.update(task.task_id, error="agent-bridge 未启用")
        return task_to_api_view(store.get(task.task_id) or task)

    task = store.create(
        trimmed_text,
        thread_id=thread_id,
        parent_task_id=parent_task_id,
        category=category,
        attachments=normalized_attachments,
    )
    if normalized_attachments:
        grant_attachments_for_task(task.task_id, normalized_attachments)
        store.update(task.task_id, attachments=normalized_attachments)
    agent_text = build_dev_task_agent_text(trimmed_text, normalized_attachments)
    try:
        accepted = bridge.submit_command(
            agent_text,
            attachments=normalized_attachments,
            task_id=task.task_id,
        )
    except bridge.AgentBridgeError as err:
        log.warning("agent_task submit failed task=%s: %s", task.task_id, err)
        store.append_status(task.task_id, "failed", msg=str(err))
        store.update(task.task_id, status="failed", error=str(err))
        return task_to_api_view(store.get(task.task_id) or task)

    run_id = str(accepted.get("run_id") or "").strip()
    bridge_status = str(accepted.get("status") or "queued").strip().lower()
    queue_depth = accepted.get("queue_depth")
    _notify_chat("queued", task_id=task.task_id, text=trimmed_text, status=bridge_status, detail=f"run={run_id}")
    store.update(
        task.task_id,
        bridge_run_id=run_id,
        bridge_url=bridge.bridge_base_url(),
        bridge_status=bridge_status,
        queue_depth=queue_depth,
        status="running" if bridge_status == "running" else "queued",
    )
    store.append_status(
        task.task_id,
        "running" if bridge_status == "running" else "queued",
    )
    _track_task(task.task_id)
    ensure_poller_started()
    log.info("agent_task submitted task=%s bridge_run_id=%s", task.task_id, run_id)
    got = store.get(task.task_id)
    return task_to_api_view(got or task)


def get_agent_task(task_id: int) -> dict[str, Any] | None:
    task = get_store().get(task_id)
    if task is None:
        return None
    view = task_to_api_view(task)
    thread_id = int(task.thread_id or task.task_id)
    messages, _ = get_store().list_tasks(thread_id=thread_id, limit=100)
    view["thread_messages"] = [task_to_api_view(t) for t in messages]
    return view


def list_agent_tasks(
    *,
    before_id: int | None = None,
    limit: int = 30,
    thread_id: int | None = None,
    roots_only: bool = False,
    category: str | None = None,
) -> dict[str, Any]:
    tasks, exhausted = get_store().list_tasks(
        before_id=before_id,
        limit=limit,
        thread_id=thread_id,
        roots_only=roots_only,
        category=category,
    )
    rows = [task_to_api_view(t) for t in tasks]
    next_before = rows[-1]["task_id"] if rows else None
    return {
        "tasks": rows,
        "limit": limit,
        "before_id": before_id,
        "next_before_id": next_before,
        "exhausted": exhausted,
    }


def get_dev_task_categories() -> list[dict[str, str]]:
    return list_categories()


def set_agent_task_category(task_id: int, category: str) -> dict[str, Any] | None:
    store = get_store()
    task = store.get(int(task_id))
    if task is None:
        return None
    root_id = int(task.thread_id or task.task_id)
    updated = store.set_thread_category(root_id, category)
    if updated is None:
        return None
    return get_agent_task(root_id)


def _track_task(task_id: int) -> None:
    with _active_lock:
        _active_task_ids.add(int(task_id))


def _untrack_task(task_id: int) -> None:
    with _active_lock:
        _active_task_ids.discard(int(task_id))


def _snapshot_active_tasks() -> list[int]:
    with _active_lock:
        return list(_active_task_ids)


def _apply_running_update(task_id: int, run: dict[str, Any]) -> None:
    store = get_store()
    run_status = str(run.get("status") or "running").strip().lower()
    store.update(
        task_id,
        bridge_status=run_status,
        events=run.get("events") or [],
        status="running" if run_status == "running" else "queued",
    )
    store.append_status(task_id, "running" if run_status == "running" else "queued")
    _apply_usage_update(task_id, run)


def get_agent_task_usage_stats(
    *,
    period: str | None = None,
    days: int | None = 7,
) -> dict[str, Any]:
    from dev_task_usage_period import resolve_usage_period, time_section_label

    store = get_store()
    resolved = resolve_usage_period(period=period, days=days)
    since = resolved.get("since")
    until = resolved.get("until")
    granularity = str(resolved.get("time_granularity") or "day")
    all_time = store.usage_summary()
    period_summary = store.usage_summary(since=since, until=until)
    by_time = store.usage_by_time(since=since, until=until, granularity=granularity)
    recent_tasks: list[dict[str, Any]] = []
    rows, _ = store.list_tasks(limit=100)
    for task in rows:
        usage = normalize_token_usage(task.token_usage)
        if not usage:
            continue
        ts = float(task.created_at or 0)
        if since is not None and ts < since:
            continue
        if until is not None and ts >= until:
            continue
        cat = normalize_category(task.category)
        recent_tasks.append(
            {
                "task_id": task.task_id,
                "thread_id": int(task.thread_id or task.task_id),
                "text": task.text,
                "status": task.status,
                "created_at": task.created_at,
                "token_usage": usage,
                **category_meta(cat),
            }
        )
        if len(recent_tasks) >= 20:
            break
    return {
        "period_key": resolved.get("period_key"),
        "period_label": resolved.get("period_label"),
        "period_days": resolved.get("period_days"),
        "time_granularity": granularity,
        "time_section_label": time_section_label(granularity),
        "period": period_summary,
        "all_time": all_time,
        "by_time": by_time,
        "recent_tasks": recent_tasks,
    }


def _cancel_task(task_id: int, *, error: str = "cancelled by user", events: list | None = None) -> None:
    store = get_store()
    current = store.get(task_id)
    store.update(
        task_id,
        status="cancelled",
        bridge_status="cancelled",
        error=error,
        events=events if events is not None else (current.events if current else []),
    )
    store.append_status(task_id, "cancelled", msg=error)
    _untrack_task(task_id)


def cancel_agent_task(task_id: int) -> dict[str, Any] | None:
    """Cancel a queued or running dev task via agent-bridge."""
    store = get_store()
    task = store.get(int(task_id))
    if task is None:
        return None

    status = str(task.status or "").strip().lower()
    if status in ("succeeded", "success", "completed", "failed", "error", "cancelled"):
        return task_to_api_view(task)

    run_id = str(task.bridge_run_id or "").strip()
    bridge_result: dict[str, Any] | None = None
    if run_id and bridge.bridge_enabled():
        try:
            bridge_result = bridge.cancel_run(run_id)
        except bridge.AgentBridgeError as err:
            log.warning("agent_task cancel failed task=%s: %s", task_id, err)
            _cancel_task(task_id, error=str(err))
            return task_to_api_view(store.get(task_id) or task)

    if bridge_result and str(bridge_result.get("status") or "") == "cancelled":
        _notify_chat("cancelled", task_id=task_id, status="cancelled")
        _cancel_task(task_id)
        return task_to_api_view(store.get(task_id) or task)

    if bridge_result and bridge_result.get("cancelling"):
        store.update(
            task_id,
            bridge_status="cancelling",
            status="running",
        )
        store.append_status(task_id, "running", msg="cancelling")
        _track_task(task_id)
        ensure_poller_started()
        got = store.get(task_id)
        return task_to_api_view(got or task)

    _notify_chat("cancelled", task_id=task_id, status="cancelled")
    _cancel_task(task_id)
    return task_to_api_view(store.get(task_id) or task)


def _finish_task(task_id: int, *, succeeded: bool, answer_text: str, error: str = "", events: list | None = None) -> None:
    store = get_store()
    if succeeded:
        current = store.get(task_id)
        store.update(
            task_id,
            status="succeeded",
            bridge_status="finished",
            result=answer_text,
            events=events if events is not None else (current.events if current else []),
        )
        store.append_status(task_id, "succeeded")
    else:
        store.update(
            task_id,
            status="failed",
            bridge_status="error",
            error=error or "dev task failed",
        )
        store.append_status(task_id, "failed", msg=error or "dev task failed")
    _untrack_task(task_id)


def poll_agent_tasks() -> None:
    store = get_store()
    for task_id in _snapshot_active_tasks():
        task = store.get(task_id)
        if task is None:
            _untrack_task(task_id)
            continue

        run_id = str(task.bridge_run_id or "").strip()
        if not run_id:
            _finish_task(task_id, succeeded=False, answer_text="", error="missing bridge_run_id")
            continue

        try:
            run = bridge.get_run(run_id)
        except bridge.AgentBridgeError as err:
            log.warning("agent_task poll failed task=%s: %s", task_id, err)
            _finish_task(task_id, succeeded=False, answer_text="", error=str(err))
            continue

        status = str(run.get("status") or "").strip().lower()
        if status in ("queued", "running"):
            _apply_running_update(task_id, run)
            continue

        if status == "finished":
            answer = _extract_answer_text(run)
            _notify_chat(
                "finished",
                task_id=task_id,
                status="succeeded",
                detail=answer[:400] if answer else "done",
            )
            _apply_usage_update(task_id, run)
            store.update(
                task_id,
                events=run.get("events") or [],
                result=str(run.get("result") or answer or ""),
            )
            _finish_task(task_id, succeeded=True, answer_text=answer, events=run.get("events") or [])
            continue

        if status == "cancelled":
            _notify_chat("cancelled", task_id=task_id, status="cancelled")
            _apply_usage_update(task_id, run)
            store.update(task_id, events=run.get("events") or [])
            _cancel_task(task_id, events=run.get("events") or [])
            continue

        error = str(run.get("error") or run.get("result") or "dev task failed").strip()
        _notify_chat("failed", task_id=task_id, status="failed", detail=error[:400])
        _apply_usage_update(task_id, run)
        _finish_task(task_id, succeeded=False, answer_text="", error=error)


def _poller_loop() -> None:
    interval = float(os.environ.get("AGENT_BRIDGE_POLL_SEC") or "2")
    log.info("agent_task poller started (interval=%ss)", interval)
    while True:
        try:
            if _snapshot_active_tasks():
                poll_agent_tasks()
        except Exception:
            log.exception("agent_task poller tick failed")
        time.sleep(max(0.5, interval))


def ensure_poller_started() -> None:
    global _poller_started
    if _poller_started:
        return
    if os.environ.get("BRAIN_SKIP_LLM_WORKER") == "1" and os.environ.get("BRAIN_ENABLE_DEV_TASK_POLLER") != "1":
        return
    _poller_started = True
    _reconcile_active_tasks()
    try:
        poll_agent_tasks()
    except Exception:
        log.exception("agent_task initial poll failed")
    thread = threading.Thread(target=_poller_loop, daemon=True, name="agent-task-poller")
    thread.start()


# Backward-compatible aliases for dispatch_intent(source=dev) if still used.
def dispatch_dev_task(intent_id: int, text: str) -> None:
    """Legacy hook: create a standalone agent task (ignores intent_id)."""
    submit_agent_task(text)


def poll_dev_tasks() -> None:
    poll_agent_tasks()
