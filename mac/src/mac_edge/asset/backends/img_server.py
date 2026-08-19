"""Resolve img-server storage locators to HTTP URLs."""

from __future__ import annotations

import os
from typing import Any

from mac_edge.asset.types import AssetStorageError, HttpUrlRepresentation

DEFAULT_LAN_PUBLIC_BASE = "http://192.168.3.65:8080"


def _lan_public_base() -> str:
    raw = (os.environ.get("MAC_EDGE_LAN_PUBLIC_BASE") or DEFAULT_LAN_PUBLIC_BASE).strip()
    return raw.rstrip("/")


def http_url_from_storage(storage: dict[str, Any]) -> HttpUrlRepresentation:
    backend = str(storage.get("backend") or storage.get("provider") or "").strip()
    key = str(storage.get("key") or storage.get("saved_as") or "").strip()
    if not key:
        raise AssetStorageError("img_server storage missing key")
    if backend and backend not in ("img_server", "local", "lan"):
        raise AssetStorageError(f"unsupported storage backend: {backend}")
    base = str(storage.get("public_base") or _lan_public_base()).rstrip("/")
    url = f"{base}/{key.lstrip('/')}"
    if not url.startswith("http://") and not url.startswith("https://"):
        raise AssetStorageError(f"refusing non-http url: {url}")
    return HttpUrlRepresentation(url=url, expires_at_ms=None)
