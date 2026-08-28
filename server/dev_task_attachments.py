"""Dev Task attachments — shared scope, grants, and agent prompt helpers."""

from __future__ import annotations

from typing import Any

from debug_attachments import attachment_asset_ids, normalize_attachments

DEV_TASK_UPLOAD_INTENT = "dev_task.attachment"


def attachment_scope(task_id: int) -> str:
    return f"dev_task:{int(task_id)}"


def grant_attachments_for_task(task_id: int, attachments: list[dict[str, str]]) -> None:
    try:
        import db as brain_db
    except ImportError:  # pragma: no cover
        from server import db as brain_db  # type: ignore

    grant = getattr(brain_db, "put_asset_grant", None)
    if not callable(grant):
        return
    scope = attachment_scope(task_id)
    for row in attachments:
        aid = str(row.get("asset_id") or "").strip()
        if not aid:
            continue
        grant(
            {
                "asset_id": aid,
                "intent_id": scope,
                "execution_id": scope,
                "capability_id": DEV_TASK_UPLOAD_INTENT,
                "permission": "read",
            }
        )


def format_attachments_for_agent(
    attachments: list[dict[str, str]],
    *,
    local_paths: dict[str, str] | None = None,
) -> str:
    if not attachments:
        return ""
    lines = ["", "## Attachments"]
    paths = local_paths or {}
    for row in attachments:
        kind = row.get("kind") or "file"
        aid = row.get("asset_id") or "—"
        mime = row.get("mime_type") or ""
        name = row.get("filename") or ""
        detail = f"- {kind} {aid}"
        if mime:
            detail += f" mime={mime}"
        if name:
            detail += f" name={name}"
        local = paths.get(aid)
        if local:
            detail += f"\n  local_path={local}"
        lines.append(detail)
    lines.append(
        "Use local_path files when present. Image attachments are for visual analysis."
    )
    return "\n".join(lines)


def build_dev_task_agent_text(
    text: str,
    attachments: list[dict[str, str]] | None,
    *,
    local_paths: dict[str, str] | None = None,
) -> str:
    body = str(text or "").strip()
    rows = list(attachments or [])
    if not rows:
        return body
    section = format_attachments_for_agent(rows, local_paths=local_paths)
    if not body:
        return ("[Dev Task with attachments — analyze the attached files.]" + section).strip()
    return f"{body}{section}"


def normalize_dev_task_attachments(raw: Any) -> list[dict[str, str]]:
    return normalize_attachments(raw)


def dev_task_attachment_asset_ids(attachments: list[dict[str, str]]) -> list[str]:
    return attachment_asset_ids(attachments)
