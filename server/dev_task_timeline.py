"""Build a unified activity timeline for a Dev Task thread."""

from __future__ import annotations

from typing import Any

from agent_fleet import DISPLAY_NAMES

BOSS_HANDLE = "boss"
BOSS_LABEL = "你（Boss）"

_STATUS_LABELS: dict[str, str] = {
    "queued": "排队",
    "running": "执行中",
    "dispatched": "已派发",
    "open": "待关闭",
    "summary_pending": "待确认结项",
    "succeeded": "完成",
    "success": "完成",
    "completed": "完成",
    "failed": "失败",
    "error": "失败",
    "cancelled": "已中断",
    "cancelling": "中断中",
}

_KIND_LABELS: dict[str, str] = {
    "user_input": "下发任务",
    "dispatch": "派单",
    "status": "状态变更",
    "agent_output": "Agent 工作",
    "tool": "工具调用",
    "user_confirm": "确认结项",
    "system": "系统",
}


def _handle_label(handle: str) -> str:
    key = str(handle or "").strip().lower()
    if not key:
        return ""
    if key == BOSS_HANDLE:
        return BOSS_LABEL
    return DISPLAY_NAMES.get(key, f"@{key}")


def _status_label(status: str) -> str:
    key = str(status or "").strip().lower()
    return _STATUS_LABELS.get(key, key or "未知")


def _ts_ms(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            num = float(value)
            if num > 10_000_000_000:
                return int(num)
            return int(num * 1000)
    except (TypeError, ValueError):
        return None
    return None


def _entry(
    *,
    entry_id: str,
    ts_ms: int,
    kind: str,
    task_id: int,
    thread_id: int,
    title: str,
    detail: str = "",
    actor: str = "",
    actor_label: str = "",
    handle: str = "",
    status: str = "",
) -> dict[str, Any]:
    actor_key = str(actor or "").strip().lower()
    handle_key = str(handle or "").strip().lower()
    return {
        "id": entry_id,
        "ts": ts_ms / 1000.0,
        "ts_ms": ts_ms,
        "kind": kind,
        "kind_label": _KIND_LABELS.get(kind, kind),
        "task_id": task_id,
        "thread_id": thread_id,
        "actor": actor_key,
        "actor_label": actor_label or _handle_label(actor_key),
        "handle": handle_key,
        "handle_label": _handle_label(handle_key) if handle_key else "",
        "status": status,
        "status_label": _status_label(status) if status else "",
        "title": title,
        "detail": detail,
    }


def _task_rows(tasks: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        if isinstance(task, dict):
            rows.append(task)
        else:
            rows.append(task.to_dict())
    return sorted(rows, key=lambda row: (float(row.get("created_at") or 0), int(row["task_id"])))


def _append_status_entries(
    entries: list[dict[str, Any]],
    *,
    task: dict[str, Any],
    thread_id: int,
) -> None:
    task_id = int(task["task_id"])
    handle = str(task.get("target_handle") or "").strip().lower()
    for idx, row in enumerate(task.get("status_log") or []):
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower()
        if not status:
            continue
        ts_ms = _ts_ms(row.get("ts")) or _ts_ms(task.get("created_at")) or 0
        kind = str(row.get("kind") or "status").strip().lower() or "status"
        actor = str(row.get("actor") or "").strip().lower()
        msg = str(row.get("msg") or "").strip()
        entry_handle = str(row.get("handle") or handle).strip().lower()
        detail = msg
        if kind == "user_confirm":
            title = "确认结项"
            actor = actor or BOSS_HANDLE
            if not detail:
                closing_md = str(task.get("closing_summary_md") or "").strip()
                if closing_md:
                    detail = closing_md if len(closing_md) <= 400 else closing_md[:400].rstrip() + "…"
        elif kind == "dispatch":
            title = f"派给 {_handle_label(entry_handle) or entry_handle}"
        else:
            title = _status_label(status)
            if entry_handle and status in {
                "running",
                "queued",
                "open",
                "summary_pending",
                "succeeded",
                "failed",
                "cancelled",
            }:
                actor = actor or entry_handle
        if kind == "status" and not detail and entry_handle:
            detail = f"负责：{_handle_label(entry_handle)}"
        entries.append(
            _entry(
                entry_id=f"status:{task_id}:{idx}:{ts_ms}",
                ts_ms=ts_ms,
                kind=kind,
                task_id=task_id,
                thread_id=thread_id,
                title=title,
                detail=detail,
                actor=actor,
                handle=entry_handle,
                status=status,
            )
        )


def _append_agent_events(
    entries: list[dict[str, Any]],
    *,
    task: dict[str, Any],
    thread_id: int,
    max_per_task: int = 40,
) -> None:
    task_id = int(task["task_id"])
    handle = str(task.get("target_handle") or "").strip().lower()
    events = task.get("events") or []
    if not isinstance(events, list):
        return
    seen_text: set[str] = set()
    added = 0
    for idx, row in enumerate(events):
        if not isinstance(row, dict):
            continue
        etype = str(row.get("type") or "").strip().lower()
        text = str(row.get("text") or "").strip()
        name = str(row.get("name") or "").strip()
        if etype in {"tool", "tool_use", "tool_call"}:
            title = f"工具 {name}" if name else "工具调用"
            detail = text or name
            kind = "tool"
        elif etype in {"tool_result", "tool_output"}:
            title = f"工具结果 {name}" if name else "工具结果"
            detail = text or name
            kind = "tool"
        elif etype == "assistant":
            if not text:
                continue
            title = "Agent 输出"
            detail = text
            kind = "agent_output"
        else:
            continue
        if not detail:
            continue
        preview = detail if len(detail) <= 320 else detail[:320].rstrip() + "…"
        if preview in seen_text:
            continue
        seen_text.add(preview)
        ts_ms = _ts_ms(row.get("ts")) or _ts_ms(task.get("updated_at")) or _ts_ms(task.get("created_at")) or 0
        entries.append(
            _entry(
                entry_id=f"agent:{task_id}:{idx}:{ts_ms}",
                ts_ms=ts_ms,
                kind=kind,
                task_id=task_id,
                thread_id=thread_id,
                title=title,
                detail=preview,
                actor=handle,
                handle=handle,
            )
        )
        added += 1
        if added >= max_per_task:
            break


def build_thread_activity_timeline(tasks: list[Any]) -> dict[str, Any]:
    """Assemble chronological timeline + participant/role summaries for a thread."""
    rows = _task_rows(tasks)
    if not rows:
        return {
            "participants": [],
            "entries": [],
            "status_flow": [],
            "role_summaries": [],
        }

    thread_id = int(rows[0].get("thread_id") or rows[0]["task_id"])
    entries: list[dict[str, Any]] = []
    participants: dict[str, dict[str, Any]] = {
        BOSS_HANDLE: {
            "handle": BOSS_HANDLE,
            "role": "user",
            "label": BOSS_LABEL,
            "display_name": "Intent Source",
        }
    }

    for task in rows:
        task_id = int(task["task_id"])
        handle = str(task.get("target_handle") or "").strip().lower()
        if handle:
            participants[handle] = {
                "handle": handle,
                "role": "agent",
                "label": _handle_label(handle),
                "display_name": DISPLAY_NAMES.get(handle, handle),
            }

        created_ms = _ts_ms(task.get("created_at")) or 0
        text = str(task.get("text") or "").strip()
        if text:
            entries.append(
                _entry(
                    entry_id=f"user:{task_id}:{created_ms}",
                    ts_ms=created_ms,
                    kind="user_input",
                    task_id=task_id,
                    thread_id=thread_id,
                    title="下发任务" if task.get("parent_task_id") is None else "续聊追问",
                    detail=text,
                    actor=BOSS_HANDLE,
                )
            )

        _append_status_entries(entries, task=task, thread_id=thread_id)
        _append_agent_events(entries, task=task, thread_id=thread_id)

    entries.sort(key=lambda row: (int(row["ts_ms"]), str(row["id"])))

    status_flow: list[dict[str, Any]] = []
    seen_status: set[tuple[int, str, int]] = set()
    for row in entries:
        if row["kind"] not in {"status", "user_confirm"}:
            continue
        status = str(row.get("status") or "").strip().lower()
        if not status and row["kind"] == "user_confirm":
            status = "confirmed"
        if not status:
            continue
        key = (int(row["task_id"]), status, int(row["ts_ms"]))
        if key in seen_status:
            continue
        seen_status.add(key)
        status_flow.append(
            {
                "task_id": int(row["task_id"]),
                "status": status,
                "status_label": _status_label(status),
                "ts": row["ts"],
                "ts_ms": row["ts_ms"],
                "handle": row.get("handle") or "",
                "handle_label": row.get("handle_label") or "",
                "actor": row.get("actor") or "",
                "actor_label": row.get("actor_label") or "",
                "msg": row.get("detail") or "",
            }
        )

    role_summaries: list[dict[str, Any]] = []
    for handle, meta in sorted(participants.items(), key=lambda item: (item[1]["role"] != "user", item[0])):
        related = [row for row in entries if row.get("actor") == handle or row.get("handle") == handle]
        if handle == BOSS_HANDLE:
            work_kinds = {"user_input", "user_confirm", "dispatch"}
        else:
            work_kinds = {"agent_output", "status", "dispatch"}
        work_rows = [row for row in related if row["kind"] in work_kinds]
        outputs = [str(row.get("detail") or "").strip() for row in work_rows if row["kind"] == "agent_output"]
        output_joined = "\n".join(outputs).strip()
        if len(output_joined) > 500:
            output_joined = output_joined[:500].rstrip() + "…"
        statuses = []
        for row in work_rows:
            status = str(row.get("status") or "").strip().lower()
            if status and status not in statuses:
                statuses.append(status)
        role_summaries.append(
            {
                **meta,
                "task_ids": sorted({int(row["task_id"]) for row in related}),
                "entry_count": len(work_rows),
                "output_count": len(outputs),
                "statuses": statuses,
                "work_preview": output_joined,
            }
        )

    return {
        "thread_id": thread_id,
        "participants": list(participants.values()),
        "entries": entries,
        "status_flow": status_flow,
        "role_summaries": role_summaries,
    }
