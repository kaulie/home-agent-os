"""Resolve img-server storage locators to HTTP URLs."""

from __future__ import annotations

import os
import re
import socket
from typing import Any
from urllib.parse import urlparse

from mac_edge.asset.types import AssetStorageError, HttpUrlRepresentation


def detect_lan_ipv4() -> str:
    """Primary LAN IPv4 of this host — no hardcoded home-LAN IP.

    1. UDP "connect" picks the interface used for the default route (no packets
       are actually sent).
    2. If there is no default route, enumerate hostname-resolved IPv4 addresses
       and keep the first non-loopback one.
    3. Last resort is loopback — still better than a stale fixed LAN IP.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        try:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
        finally:
            sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    try:
        # macOS / Linux: enumerate every interface so a DHCP re-lease on an
        # interface that hostname does not resolve is still discovered.
        import subprocess

        out = subprocess.run(
            ["ifconfig"], capture_output=True, text=True, timeout=3.0
        )
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("inet "):
                continue
            ip = line.split()[1].split("%", 1)[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def default_lan_public_base(port: int = 8080) -> str:
    """LAN URL of this host's img-server (the address other devices fetch)."""
    return f"http://{detect_lan_ipv4()}:{port}"


# Backward-compatible name; computed once at import time.
DEFAULT_LAN_PUBLIC_BASE = default_lan_public_base()


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
    lan = (os.environ.get("MAC_EDGE_LAN_PUBLIC_BASE") or default_lan_public_base()).strip()
    lan_parsed = urlparse(lan if "://" in lan else f"http://{lan}")
    lan_host = lan_parsed.hostname or detect_lan_ipv4()
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
    raw = (os.environ.get("MAC_EDGE_LAN_PUBLIC_BASE") or default_lan_public_base()).strip()
    return raw.rstrip("/")


def _is_private_lan_base(base: str) -> bool:
    """True when base points at a loopback / RFC1918 private-LAN host.

    img-server's LAN IP is DHCP-assigned, so a stored private-LAN public_base
    may be stale (e.g. an old .x from a previous re-lease). Public/cloud hosts
    are stable and not subject to this.
    """
    try:
        host = (urlparse(base).hostname or "").strip().lower()
    except Exception:
        return False
    if host in ("localhost", "::1", "127.0.0.1"):
        return True
    return bool(re.match(r"^(10\.|192\.168\.|127\.|172\.(1[6-9]|2\d|3[01])\.)", host))


def _pick_base(storage: dict[str, Any], *, prefer_cloud: bool) -> str:
    pub = str(storage.get("public_base") or "").strip().rstrip("/")
    cloud = str(storage.get("cloud_public_base") or "").strip().rstrip("/")
    if prefer_cloud and cloud:
        return cloud
    # A stored non-private (public/cloud) base is stable — keep using it.
    if pub and not _is_private_lan_base(pub):
        return pub
    # A stored private-LAN/loopback public_base is DHCP-volatile and may be
    # stale; resolve the CURRENT LAN base at use time for the co-located
    # img-server (cloud mirror is kept as a fallback).
    if pub:
        return _lan_public_base() or cloud or pub
    # No stored public_base: prefer the cloud mirror if present, else the
    # current LAN base (co-located img-server).
    return cloud or _lan_public_base()


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
