"""Thin Cast plugin: forward display.photo to external Cast HTTP service."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

log = logging.getLogger("mac_edge.cast")

DEFAULT_CAST_DISPLAY_URL = "http://127.0.0.1:9095/endpoint/display"


class CastError(Exception):
    pass


def cast_photo(
    photo_url: str,
    *,
    display_base_url: str = DEFAULT_CAST_DISPLAY_URL,
    timeout_sec: float = 60.0,
) -> str:
    """
    Ask the external Cast service to show photo_url:

      GET {display_base_url}?url={urlencoded_photo_url}
    """
    url = (photo_url or "").strip()
    if not url:
        raise CastError("photo_url is empty")

    base = (display_base_url or DEFAULT_CAST_DISPLAY_URL).strip().rstrip("?")
    # Avoid double ?url= if caller already appended query.
    sep = "&" if "?" in base else "?"
    request_url = f"{base}{sep}{urlencode({'url': url})}"

    log.info("GET cast service %s", request_url[:200])
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.get(request_url)
    except httpx.RequestError as e:
        raise CastError(
            f"cast service unreachable ({display_base_url}): {e}"
        ) from e

    body_preview = (resp.text or "")[:300]
    if resp.status_code >= 400:
        raise CastError(f"cast service HTTP {resp.status_code}: {body_preview}")

    log.info("cast service OK HTTP %s", resp.status_code)
    return f"cast ok HTTP {resp.status_code} → {body_preview or '(empty body)'}"
