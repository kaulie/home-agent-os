"""Resolve img-server storage locators to HTTP URLs."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from mac_edge.asset.types import AssetStorageError, HttpUrlRepresentation

DEFAULT_LAN_PUBLIC_BASE = "http://192.168.3.73:8080"


def lan_facing_brain_base(brain_base_url: str) -> str:
    """TV/DLNA cannot fetch 127.0.0.1; rewrite Brain loopback to the LAN host."""
    explicit = (os.environ.get("MAC_EDGE_BRAIN_LAN_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    raw = (brain_base_url or "").strip()
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    host = (parsed.hostname or "").strip().lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return raw.rstrip("/")
    lan = (os.environ.get("MAC_EDGE_LAN_PUBLIC_BASE") or DEFAULT_LAN_PUBLIC_BASE).strip()
    lan_parsed = urlparse(lan if "://" in lan else f"http://{lan}")
    lan_host = lan_parsed.hostname or "192.168.3.73"
    port = parsed.port or 9527
    scheme = parsed.scheme or "http"
    return f"{scheme}://{lan_host}:{port}"


def brain_content_http_url(brain_base_url: str, asset_id: str, intent_id: str) -> str:
    aid = str(asset_id or "").strip()
    iid = str(intent_id or "").strip()
    if not aid or not iid:
        raise AssetStorageError("brain content url requires asset_id and intent_id")
    base = lan_facing_brain_base(brain_base_url)
    return f"{base}/api/v1/assets/{aid}/content?intent_id={iid}&representation=original"


def _lan_public_base() -> str:
    raw = (os.environ.get("MAC_EDGE_LAN_PUBLIC_BASE") or DEFAULT_LAN_PUBLIC_BASE).strip()
    return raw.rstrip("/")


def _pick_base(storage: dict[str, Any], *, prefer_cloud: bool) -> str:
    pub = str(storage.get("public_base") or "").strip().rstrip("/")
    cloud = str(storage.get("cloud_public_base") or "").strip().rstrip("/")
    if prefer_cloud:
        return cloud or pub or _lan_public_base()
    return pub or cloud or _lan_public_base()


def _locator_candidates(storage: dict[str, Any]) -> list[tuple[str, str]]:
    """(base, key) pairs: original first, then preview / cloud variants."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(*, prefer_cloud: bool, key: str) -> None:
        k = (key or "").strip()
        if not k:
            return
        base = _pick_base(storage, prefer_cloud=prefer_cloud)
        pair = (base, k)
        if pair not in seen:
            seen.add(pair)
            out.append(pair)

    # Original (prefer), then preview fallback — covers P0 preview-first register.
    add(prefer_cloud=False, key=str(storage.get("key") or storage.get("saved_as") or ""))
    add(prefer_cloud=True, key=str(storage.get("cloud_key") or ""))
    add(prefer_cloud=False, key=str(storage.get("preview_key") or ""))
    add(prefer_cloud=True, key=str(storage.get("cloud_preview_key") or ""))
    return out


def http_url_from_storage(storage: dict[str, Any]) -> HttpUrlRepresentation:
    backend = str(storage.get("backend") or storage.get("provider") or "").strip()
    if backend and backend not in ("img_server", "local", "lan"):
        raise AssetStorageError(f"unsupported storage backend: {backend}")
    candidates = _locator_candidates(storage)
    if not candidates:
        raise AssetStorageError("img_server storage missing key")
    base, key = candidates[0]
    url = f"{base}/{key.lstrip('/')}"
    if not url.startswith("http://") and not url.startswith("https://"):
        raise AssetStorageError(f"refusing non-http url: {url}")
    return HttpUrlRepresentation(url=url, expires_at_ms=None)
