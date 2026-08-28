"""Parse ## 派单 from closing drafts and spawn follow-up Dev Tasks."""

from __future__ import annotations

import logging
import re
from typing import Any

try:
    from agent_bridge_client import FLEET_HANDLES, normalize_fleet_handle
except ImportError:  # pragma: no cover
    from server.agent_bridge_client import FLEET_HANDLES, normalize_fleet_handle  # type: ignore

log = logging.getLogger("dev_task")

_SECTION_RE = re.compile(
    r"^##\s*派单\s*$",
    re.MULTILINE,
)
_NEXT_SECTION_RE = re.compile(r"^##\s+\S+", re.MULTILINE)
_ITEM_RE = re.compile(
    r"^\s*(?:[-*]|\d+[.)])\s*@([A-Za-z_]+)\s*[:：]\s*(.+?)\s*$",
)

# Avoid accidental self-loops when controller investigates then "派单" to itself.
_SKIP_HANDLES = frozenset({"controller"})


def extract_dispatch_section(markdown: str) -> str:
    body = str(markdown or "")
    match = _SECTION_RE.search(body)
    if match is None:
        return ""
    start = match.end()
    nxt = _NEXT_SECTION_RE.search(body, start)
    end = nxt.start() if nxt is not None else len(body)
    return body[start:end].strip()


def parse_followup_dispatches(markdown: str) -> list[dict[str, str]]:
    """Return [{handle, text}, ...] from the ## 派单 section."""
    section = extract_dispatch_section(markdown)
    if not section:
        return []
    lowered = section.lower()
    if lowered in {"无", "无需派单", "不需要", "none", "n/a", "- 无", "* 无"}:
        return []
    if re.fullmatch(r"[-*]\s*无\s*", section.strip(), flags=re.IGNORECASE):
        return []

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if re.fullmatch(r"[-*]\s*无\s*", line, flags=re.IGNORECASE):
            continue
        m = _ITEM_RE.match(line)
        if m is None:
            continue
        handle = normalize_fleet_handle(m.group(1))
        text = str(m.group(2) or "").strip()
        if handle is None or not text:
            continue
        if handle in _SKIP_HANDLES:
            continue
        if handle not in FLEET_HANDLES:
            continue
        key = (handle, text)
        if key in seen:
            continue
        seen.add(key)
        out.append({"handle": handle, "text": text})
        if len(out) >= 8:
            break
    return out


def dispatch_followups_from_closing(
    *,
    parent_task_id: int,
    thread_id: int,
    category: str | None,
    draft: str,
    submit_fn: Any,
    append_status_fn: Any,
) -> list[dict[str, Any]]:
    """Create child Dev Tasks from ## 派单. Returns submitted API views."""
    items = parse_followup_dispatches(draft)
    if not items:
        return []
    submitted: list[dict[str, Any]] = []
    for item in items:
        handle = item["handle"]
        text = item["text"]
        try:
            view = submit_fn(
                text,
                parent_task_id=int(parent_task_id),
                thread_id=int(thread_id),
                category=category,
                target_handle=handle,
            )
        except Exception as err:  # pragma: no cover - defensive
            log.warning(
                "auto follow-up failed parent=%s handle=%s: %s",
                parent_task_id,
                handle,
                err,
            )
            append_status_fn(
                int(parent_task_id),
                "open",
                handle=handle,
                kind="dispatch",
                msg=f"派单失败 @{handle}: {err}",
            )
            continue
        child_id = int(view.get("task_id") or 0)
        append_status_fn(
            int(parent_task_id),
            "open",
            handle=handle,
            kind="dispatch",
            msg=f"已派单 @{handle} → task #{child_id}: {text[:180]}",
        )
        submitted.append(view)
        log.info(
            "auto follow-up parent=%s → #%s @%s",
            parent_task_id,
            child_id,
            handle,
        )
    return submitted
