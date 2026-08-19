"""Shared env helpers for vision providers."""

from __future__ import annotations

import os


def vision_api_key() -> str:
    return (
        os.environ.get("MAC_EDGE_VISION_API_KEY")
        or os.environ.get("ARK_API_KEY")
        or ""
    ).strip()


def vision_api_base(default: str) -> str:
    return (os.environ.get("MAC_EDGE_VISION_API_BASE") or default).strip().rstrip("/")


def vision_model(default: str) -> str:
    return (os.environ.get("MAC_EDGE_VISION_MODEL") or default).strip() or default


def vision_provider_name() -> str:
    """ark (default) | openai — extend registry when adding backends."""
    raw = (os.environ.get("MAC_EDGE_VISION_PROVIDER") or "ark").strip().lower()
    return raw or "ark"
