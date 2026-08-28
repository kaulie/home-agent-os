"""Normalized user attachments on Debug Issues (extensible beyond images)."""

from __future__ import annotations

from typing import Any

ATTACHMENT_KINDS = frozenset({"image", "file", "audio", "video", "other"})


def normalize_attachments(raw: Any) -> list[dict[str, str]]:
    """Parse attachments from API/store. Accepts legacy string asset_id lists."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        parsed = _parse_attachment_item(item)
        if parsed is None:
            continue
        aid = parsed["asset_id"]
        if aid in seen:
            continue
        seen.add(aid)
        out.append(parsed)
    return out


def _parse_attachment_item(item: Any) -> dict[str, str] | None:
    if isinstance(item, str):
        aid = item.strip()
        if not aid:
            return None
        return {"asset_id": aid, "kind": "image"}
    if not isinstance(item, dict):
        return None
    aid = str(item.get("asset_id") or item.get("id") or "").strip()
    if not aid:
        return None
    kind = str(item.get("kind") or item.get("type") or "image").strip().lower()
    if kind not in ATTACHMENT_KINDS:
        kind = "other"
    entry: dict[str, str] = {"asset_id": aid, "kind": kind}
    mime = str(item.get("mime_type") or item.get("mime") or "").strip()
    if mime:
        entry["mime_type"] = mime
    filename = str(item.get("filename") or item.get("name") or "").strip()
    if filename:
        entry["filename"] = filename
    return entry


def attachment_asset_ids(attachments: list[dict[str, str]]) -> list[str]:
    return [row["asset_id"] for row in attachments if row.get("asset_id")]
