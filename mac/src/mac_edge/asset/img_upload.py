"""Shared img-server upload (query.content / search_images).

asset.upload posts to the active Brain's /api/v1/assets/upload instead.
Do not LAN-then-cloud dual-upload: dest is dest. Cloud is used only when
preferred_dest is already cloud (or allow_cloud_fallback on LAN *failure*).
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("mac_edge.asset.img_upload")

# Mac uploads to loopback; public_base is the LAN URL other devices fetch.
DEFAULT_LAN_UPLOAD_URL = "http://127.0.0.1:8080/api/v1/photos/upload"
DEFAULT_LAN_PUBLIC_BASE = "http://192.168.3.73:8080"
DEFAULT_CLOUD_UPLOAD_URL = "http://127.0.0.1:9527/api/v1/photos/upload"
DEFAULT_CLOUD_PUBLIC_BASE = "http://115.190.153.53:8080"
STUB_DESTS = frozenset({"gdrive", "dropbox"})

# Fail LAN quickly so cloud fallback is useful (intent 123 waited ~120s).
LAN_UPLOAD_TIMEOUT_SEC = 20.0
CLOUD_UPLOAD_TIMEOUT_SEC = 120.0
# Pre-upload reachability: TCP connect then optional GET /health.
PROBE_TCP_TIMEOUT_SEC = 1.5
PROBE_HTTP_TIMEOUT_SEC = 2.0


class ImgUploadError(Exception):
    """Upload to img-server / photo API failed."""


@dataclass(frozen=True)
class UploadResult:
    photo_url: str
    saved_as: str
    dest: str  # lan | cloud
    public_base: str
    local_path: str = ""
    cloud_public_base: str = ""
    cloud_saved_as: str = ""
    cloud_photo_url: str = ""


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def normalize_upload_dest(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    if v in ("cloud",):
        return "cloud"
    if v in ("gdrive", "google_drive", "googledrive"):
        return "gdrive"
    if v in ("dropbox",):
        return "dropbox"
    if v in ("img_server", "lan", "local", "home", ""):
        return "lan"
    log.warning("unknown upload_dest=%r — using lan", raw)
    return "lan"


def display_upload_dest(dest: str) -> str:
    """Wire/capability dest name: lan aliases → img_server."""
    canonical = normalize_upload_dest(dest)
    if canonical == "lan":
        return "img_server"
    return canonical


def require_implemented_dest(dest: str) -> str:
    canonical = normalize_upload_dest(dest)
    if canonical in STUB_DESTS:
        raise ImgUploadError(
            f"dest={canonical} is not implemented yet "
            f"({'Google Drive' if canonical == 'gdrive' else 'Dropbox'} is a plugin slot only)"
        )
    return canonical


def upload_dest_from_params(params: dict[str, Any] | None) -> str:
    if isinstance(params, dict):
        raw = params.get("upload_dest") or params.get("uploadDest")
        if raw is not None and str(raw).strip():
            return normalize_upload_dest(str(raw))
    return normalize_upload_dest(_env("MAC_EDGE_PHOTO_UPLOAD_DEST") or "lan")


def upload_endpoints(dest: str) -> tuple[str, str, str]:
    """Return (upload_url, public_base, probe_url)."""
    if dest == "lan":
        upload = _env("MAC_EDGE_LAN_PHOTO_UPLOAD_URL") or DEFAULT_LAN_UPLOAD_URL
        public = _env("MAC_EDGE_LAN_PHOTO_PUBLIC_BASE") or DEFAULT_LAN_PUBLIC_BASE
        parsed = urlparse(upload)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else public.rstrip("/")
        probe = origin.rstrip("/") + "/health"
        return upload, public.rstrip("/"), probe
    upload = _env("MAC_EDGE_PHOTO_UPLOAD_URL") or DEFAULT_CLOUD_UPLOAD_URL
    public = _env("MAC_EDGE_PHOTO_PUBLIC_BASE") or DEFAULT_CLOUD_PUBLIC_BASE
    from mac_edge.config import parse_brain_url_env, primary_brain_url
    _urls, by_domain = parse_brain_url_env(_env("MAC_EDGE_BRAIN_URL"))
    brain = (
        by_domain.get("cloud")
        or primary_brain_url(_env("MAC_EDGE_BRAIN_URL"))
        or re.sub(r"/api/v1/photos/upload/?$", "", upload)
    )
    probe = brain.rstrip("/") + "/"
    return upload, public.rstrip("/"), probe


def _host_port_from_url(url: str) -> tuple[str, int] | None:
    parsed = urlparse((url or "").strip())
    host = parsed.hostname
    if not host:
        return None
    if parsed.port:
        port = int(parsed.port)
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80
    return host, port


def probe_reachable(
    dest: str,
    *,
    tcp_timeout_sec: float = PROBE_TCP_TIMEOUT_SEC,
    http_timeout_sec: float = PROBE_HTTP_TIMEOUT_SEC,
) -> bool:
    """True if dest host accepts TCP (and optional probe URL responds).

    Any HTTP response (including 404) counts as reachable — we only care that
    the path to the img-server / Brain is open.
    """
    upload_url, _public, probe_url = upload_endpoints(dest)
    target = _host_port_from_url(probe_url) or _host_port_from_url(upload_url)
    if target is None:
        log.warning("img probe dest=%s: cannot parse host from urls", dest)
        return False
    host, port = target
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=float(tcp_timeout_sec)):
            pass
    except OSError as e:
        log.info(
            "img probe dest=%s tcp %s:%s unreachable (%s) ms=%s",
            dest,
            host,
            port,
            e,
            int((time.perf_counter() - t0) * 1000),
        )
        return False
    # TCP ok — optional HTTP GET for a clearer health signal.
    url = (probe_url or "").strip()
    if not url:
        log.info(
            "img probe dest=%s tcp ok %s:%s ms=%s",
            dest,
            host,
            port,
            int((time.perf_counter() - t0) * 1000),
        )
        return True
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=float(http_timeout_sec)) as resp:
            _ = resp.getcode()
    except urllib.error.HTTPError:
        # 4xx/5xx still means the host is up.
        pass
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.info(
            "img probe dest=%s http %s failed after tcp ok (%s) ms=%s",
            dest,
            url,
            e,
            int((time.perf_counter() - t0) * 1000),
        )
        return False
    log.info(
        "img probe dest=%s ok %s:%s ms=%s",
        dest,
        host,
        port,
        int((time.perf_counter() - t0) * 1000),
    )
    return True


def multipart_upload(
    path: Path,
    upload_url: str,
    *,
    timeout_sec: float = CLOUD_UPLOAD_TIMEOUT_SEC,
    boundary_prefix: str = "MacEdgeImg",
) -> dict[str, Any]:
    boundary = f"----{boundary_prefix}{int(time.time() * 1000)}"
    filename = path.name
    file_bytes = path.read_bytes()
    parts: list[bytes] = [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode(),
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = urllib.request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = int(resp.getcode() or 0)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise ImgUploadError(f"upload HTTP {e.code}: {raw[:300]}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ImgUploadError(f"upload failed: {e}") from e

    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        raise ImgUploadError(
            f"upload response not JSON (http={code}): {raw[:200]}"
        ) from e
    if not isinstance(data, dict):
        raise ImgUploadError("upload response must be object")
    return data


def resolve_photo_url(
    upload_json: dict[str, Any],
    *,
    public_base: str,
) -> tuple[str, str]:
    saved_as = str(upload_json.get("saved_as") or "").strip()
    url = str(upload_json.get("url") or "").strip()
    base = public_base.rstrip("/")
    if url.startswith("http://") or url.startswith("https://"):
        if saved_as and url.startswith("http://127."):
            return f"{base}/{Path(saved_as).name}", saved_as
        return url, saved_as
    if saved_as:
        return f"{base}/{Path(saved_as).name}", saved_as
    raise ImgUploadError(f"upload ok but no photo_url/saved_as: {upload_json}")


def _upload_once(path: Path, dest: str) -> UploadResult:
    dest = require_implemented_dest(dest)
    upload_url, public_base, _probe = upload_endpoints(dest)
    timeout = LAN_UPLOAD_TIMEOUT_SEC if dest == "lan" else CLOUD_UPLOAD_TIMEOUT_SEC
    upload_json = multipart_upload(path, upload_url, timeout_sec=timeout)
    photo_url, saved_as = resolve_photo_url(upload_json, public_base=public_base)
    if not photo_url.startswith("http://") and not photo_url.startswith("https://"):
        raise ImgUploadError(f"refusing non-http photo_url: {photo_url}")
    return UploadResult(
        photo_url=photo_url,
        saved_as=saved_as,
        dest=dest,
        public_base=public_base,
        local_path=str(path),
    )


def upload_image_file(
    path: Path,
    *,
    preferred_dest: str = "lan",
    allow_cloud_fallback: bool = True,
) -> UploadResult:
    """Upload a local file to preferred_dest only (no LAN-then-cloud second hop).

    If preferred dest is lan and it is unreachable / the upload fails, optionally
    fall back to cloud. That fallback is for LAN *failure*, not a dual-upload.
    """
    dest = require_implemented_dest(preferred_dest)
    skip_lan = False
    if dest == "lan" and allow_cloud_fallback:
        if not probe_reachable("lan"):
            log.warning("lan img probe unreachable; skip lan upload → cloud")
            skip_lan = True
    if not skip_lan:
        try:
            result = _upload_once(path, dest)
            log.info(
                "img upload ok dest=%s url=%s saved_as=%s",
                result.dest,
                result.photo_url,
                result.saved_as,
            )
            return result
        except ImgUploadError as first_err:
            if dest != "lan" or not allow_cloud_fallback:
                raise
            log.warning(
                "lan img upload failed (%s); falling back to cloud",
                first_err,
            )
    else:
        if not allow_cloud_fallback:
            raise ImgUploadError("lan img probe unreachable and cloud fallback disabled")

    if not probe_reachable("cloud"):
        log.warning("cloud img probe unreachable; still attempting cloud upload")
    result = _upload_once(path, "cloud")
    log.info(
        "img upload ok dest=cloud (fallback) url=%s saved_as=%s",
        result.photo_url,
        result.saved_as,
    )
    return result


def upload_image_bytes(
    image_bytes: bytes,
    *,
    filename: str,
    preferred_dest: str = "lan",
    allow_cloud_fallback: bool = True,
    staging_dir: Path | None = None,
) -> UploadResult:
    if not image_bytes:
        raise ImgUploadError("generated image is empty")
    if staging_dir is None:
        root = Path(__file__).resolve().parents[3]
        staging_dir = Path(_env("MAC_EDGE_DATA_DIR") or str(root / "data")) / "upload"
    staging_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", filename) or "upload.bin"
    path = staging_dir / safe
    path.write_bytes(image_bytes)
    return upload_image_file(
        path,
        preferred_dest=preferred_dest,
        allow_cloud_fallback=allow_cloud_fallback,
    )
