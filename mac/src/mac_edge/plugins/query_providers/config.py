"""Env helpers for query.content providers. Does not read MAC_EDGE_VISION_*."""

from __future__ import annotations

import os


def query_api_key() -> str:
    return (
        os.environ.get("MAC_EDGE_QUERY_API_KEY")
        or os.environ.get("ARK_API_KEY")
        or ""
    ).strip()


def query_api_base(default: str) -> str:
    return (os.environ.get("MAC_EDGE_QUERY_API_BASE") or default).strip().rstrip("/")


def query_model(default: str) -> str:
    return (os.environ.get("MAC_EDGE_QUERY_MODEL") or default).strip() or default


def query_image_model(default: str) -> str:
    return (
        os.environ.get("MAC_EDGE_QUERY_IMAGE_MODEL") or default
    ).strip() or default


def query_provider_name() -> str:
    raw = (os.environ.get("MAC_EDGE_QUERY_PROVIDER") or "ark").strip().lower()
    return raw or "ark"
