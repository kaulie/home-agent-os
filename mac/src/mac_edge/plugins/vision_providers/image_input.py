"""Prepare image refs for vision providers (URL → optional local data URL).

Ark often times out downloading large/slow public photo hosts. Edge downloads
(and may shrink) then passes a data URL so the model call is reliable.
"""

from __future__ import annotations

import base64
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from mac_edge.plugins.vision_providers import VisionProviderError

log = logging.getLogger("mac_edge.vision.image_input")

# Above this size (bytes), try to shrink before base64 inline.
_INLINE_SOFT_LIMIT = 800_000
_MAX_LONG_EDGE = 1280


def prepare_image_for_model(
    image_url: str,
    *,
    timeout_sec: float = 90.0,
) -> tuple[str, dict[str, Any]]:
    """Return (image_ref, timing_meta).

    - Already a data: URL → pass through (download_ms=0, mode=passthrough)
    - http(s) → download; if large, shrink (sips on macOS) then data URL
    """
    url = (image_url or "").strip()
    if not url:
        raise VisionProviderError("empty image_url")
    if url.startswith("data:"):
        return url, {
            "mode": "passthrough",
            "download_ms": 0,
            "prepare_ms": 0,
            "bytes_in": 0,
            "bytes_out": 0,
        }

    if not (url.startswith("http://") or url.startswith("https://")):
        raise VisionProviderError("image_url must be http(s) or data:")

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
            resp = client.get(url)
    except httpx.RequestError as e:
        raise VisionProviderError(f"download image failed: {e}") from e
    download_ms = int((time.perf_counter() - t0) * 1000)
    if resp.status_code >= 400:
        raise VisionProviderError(
            f"download image HTTP {resp.status_code}: {url[:120]}"
        )
    raw = resp.content
    ctype = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
    if not ctype.startswith("image/"):
        ctype = "image/jpeg"

    t1 = time.perf_counter()
    out = raw
    mode = "inline"
    if len(raw) > _INLINE_SOFT_LIMIT:
        shrunk = _shrink_jpeg(raw, max_edge=_MAX_LONG_EDGE)
        if shrunk and len(shrunk) < len(raw):
            out = shrunk
            ctype = "image/jpeg"
            mode = "inline_resized"
    prepare_ms = int((time.perf_counter() - t1) * 1000)

    b64 = base64.b64encode(out).decode("ascii")
    data_url = f"data:{ctype};base64,{b64}"
    meta = {
        "mode": mode,
        "download_ms": download_ms,
        "prepare_ms": prepare_ms,
        "bytes_in": len(raw),
        "bytes_out": len(out),
        "source_url": url[:200],
    }
    log.info(
        "vision image prepared mode=%s download_ms=%s prepare_ms=%s "
        "bytes_in=%s bytes_out=%s",
        mode,
        download_ms,
        prepare_ms,
        len(raw),
        len(out),
    )
    return data_url, meta


def _shrink_jpeg(raw: bytes, *, max_edge: int) -> bytes | None:
    """Best-effort resize via macOS sips; None if unavailable."""
    try:
        with tempfile.TemporaryDirectory(prefix="vision_img_") as td:
            src = Path(td) / "in.jpg"
            dst = Path(td) / "out.jpg"
            src.write_bytes(raw)
            proc = subprocess.run(
                [
                    "sips",
                    "-Z",
                    str(max_edge),
                    "-s",
                    "format",
                    "jpeg",
                    str(src),
                    "--out",
                    str(dst),
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
            if proc.returncode != 0 or not dst.is_file():
                return None
            return dst.read_bytes()
    except (OSError, subprocess.SubprocessError):
        return None
