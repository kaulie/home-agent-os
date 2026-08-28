"""Canonical Dev Task thread categories (labels for Dev Console)."""

from __future__ import annotations

from typing import Any

DEFAULT_CATEGORY = "other"

_CATEGORIES: tuple[dict[str, str], ...] = (
    {"id": "bug_fix", "label": "Issue 跟进"},
    {"id": "feature", "label": "功能开发"},
    {"id": "tech_discuss", "label": "技术探讨"},
    {"id": "ops", "label": "运维部署"},
    {"id": "chat", "label": "闲聊"},
    {"id": "other", "label": "其他"},
)

_CATEGORY_IDS = frozenset(c["id"] for c in _CATEGORIES)


def list_categories() -> list[dict[str, str]]:
    return [dict(c) for c in _CATEGORIES]


def normalize_category(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in _CATEGORY_IDS:
        return raw
    aliases = {
        "bug": "bug_fix",
        "fix": "bug_fix",
        "debug": "bug_fix",
        "discuss": "tech_discuss",
        "tech": "tech_discuss",
        "deploy": "ops",
        "operation": "ops",
    }
    if raw in aliases:
        return aliases[raw]
    return DEFAULT_CATEGORY


def category_label(category_id: str | None) -> str:
    cid = normalize_category(category_id)
    for row in _CATEGORIES:
        if row["id"] == cid:
            return row["label"]
    return "其他"


def category_meta(category_id: str | None) -> dict[str, Any]:
    cid = normalize_category(category_id)
    return {
        "category": cid,
        "category_label": category_label(cid),
    }
