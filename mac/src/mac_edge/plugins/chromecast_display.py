"""Thin Cast plugin: forward display.photo / display.slideshow to Cast HTTP."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any
from urllib.parse import unquote, urlencode, urlparse

import httpx

log = logging.getLogger("mac_edge.cast")

DEFAULT_CAST_DISPLAY_URL = "http://127.0.0.1:9095/endpoint/display"
DEFAULT_SLIDESHOW_INTERVAL_SEC = 5.0
CLOUD_PHOTO_HOST = "115.190.153.53:8080"

ORDER_ARRAY_ASC = "array_asc"
ORDER_ARRAY_DESC = "array_desc"
ORDER_ALPHABET_ASC = "alphabet_asc"
ORDER_ALPHABET_DESC = "alphabet_desc"
ORDER_RANDOM = "random"
SLIDESHOW_ORDERS = (
    ORDER_ARRAY_ASC,
    ORDER_ARRAY_DESC,
    ORDER_ALPHABET_ASC,
    ORDER_ALPHABET_DESC,
    ORDER_RANDOM,
)


class CastError(Exception):
    pass


def _filename_key(url: str) -> str:
    path = unquote(urlparse(url).path or "")
    name = path.rsplit("/", 1)[-1] if path else url
    return name.casefold()


def parse_photo_urls(raw: str | None) -> list[str]:
    """Require a JSON array of http(s) LAN URLs. Missing/empty/invalid → error."""
    text = (raw or "").strip()
    if not text:
        raise CastError("display.slideshow requires photo_urls")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise CastError(f"photo_urls must be a JSON array: {e}") from e
    if not isinstance(parsed, list) or not parsed:
        raise CastError("photo_urls must be a non-empty JSON array")
    urls: list[str] = []
    for item in parsed:
        url = str(item or "").strip()
        if not url:
            raise CastError("photo_urls contains an empty URL")
        if not url.startswith("http://") and not url.startswith("https://"):
            raise CastError(f"photo_urls entry is not http(s): {url[:80]}")
        if CLOUD_PHOTO_HOST in url:
            raise CastError(
                f"photo_urls must be LAN (not {CLOUD_PHOTO_HOST}): {url[:80]}"
            )
        urls.append(url)
    return urls


def order_photo_urls(urls: list[str], order: str) -> list[str]:
    mode = (order or ORDER_ARRAY_ASC).strip().lower() or ORDER_ARRAY_ASC
    if mode not in SLIDESHOW_ORDERS:
        raise CastError(
            f"unknown order={order!r}; want {', '.join(SLIDESHOW_ORDERS)}"
        )
    items = list(urls)
    if mode == ORDER_ARRAY_ASC:
        return items
    if mode == ORDER_ARRAY_DESC:
        items.reverse()
        return items
    if mode == ORDER_ALPHABET_ASC:
        return sorted(items, key=_filename_key)
    if mode == ORDER_ALPHABET_DESC:
        return sorted(items, key=_filename_key, reverse=True)
    random.shuffle(items)
    return items


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


def cast_slideshow(
    urls: list[str],
    *,
    interval_sec: float = DEFAULT_SLIDESHOW_INTERVAL_SEC,
    order: str = ORDER_ARRAY_ASC,
    display_base_url: str = DEFAULT_CAST_DISPLAY_URL,
    timeout_sec: float = 60.0,
) -> str:
    """Cast each URL in order; wait interval_sec between frames (not after the last)."""
    ordered = order_photo_urls(urls, order)
    if not ordered:
        raise CastError("display.slideshow requires photo_urls")
    hold = max(0.0, float(interval_sec))
    last = ""
    for i, url in enumerate(ordered):
        last = cast_photo(
            url,
            display_base_url=display_base_url,
            timeout_sec=timeout_sec,
        )
        if i + 1 < len(ordered) and hold > 0:
            time.sleep(hold)
    log.info(
        "slideshow done count=%s order=%s interval_sec=%s",
        len(ordered),
        order,
        hold,
    )
    return f"slideshow ok count={len(ordered)} order={order} {last}"


def photo_from_params(
    params: dict[str, str],
    *,
    asset: "CapAsset",
    display_base_url: str = DEFAULT_CAST_DISPLAY_URL,
    timeout_sec: float = 60.0,
) -> tuple[str, dict[str, Any]]:
    """Capability entry: resolve asset_ref via Asset Manager, then Cast (Mac :9095 legacy).

    Returns (message, outputs). Mac path is URL-only; Presentation Protocol V1 is iPhone Cast.
    See docs/chromecast-cast-protocol.md.
    """
    from mac_edge.asset.sdk import CapAsset
    from mac_edge.asset.types import AssetError

    if not isinstance(asset, CapAsset):
        raise CastError("display.photo requires CapAsset (Runtime SDK)")
    try:
        ref = asset.require_ref(params, "asset_ref")
        photo_url = asset.http_url(ref)
    except AssetError as e:
        raise CastError(str(e)) from e
    msg = cast_photo(
        photo_url,
        display_base_url=display_base_url,
        timeout_sec=timeout_sec,
    )
    outputs: dict[str, Any] = {
        "cast_transport": "mac_http_9095_legacy",
        "cast_status": "accepted",
        "protocol_version": 0,
        "asset_id": getattr(ref, "asset_id", None) or (ref.get("asset_id") if isinstance(ref, dict) else None),
        "note": "Mac :9095 is URL-only; use iPhone Cast Sender for Presentation Protocol V1",
    }
    return f"{msg} · cast_status=accepted (legacy Mac HTTP)", outputs


def slideshow_from_params(
    params: dict[str, str],
    *,
    asset: "CapAsset",
    display_base_url: str = DEFAULT_CAST_DISPLAY_URL,
    timeout_sec: float = 60.0,
) -> tuple[str, dict[str, Any]]:
    """Capability entry: resolve asset_refs via Asset Manager — no plan / predecessors."""
    from mac_edge.asset.sdk import CapAsset
    from mac_edge.asset.types import AssetError

    if not isinstance(asset, CapAsset):
        raise CastError("display.slideshow requires CapAsset (Runtime SDK)")
    try:
        refs = asset.require_refs(params, "asset_refs")
        urls = [asset.http_url(ref) for ref in refs]
    except AssetError as e:
        raise CastError(str(e)) from e
    interval = DEFAULT_SLIDESHOW_INTERVAL_SEC
    raw_interval = (params.get("interval_sec") or "").strip()
    if raw_interval:
        try:
            interval = float(raw_interval)
        except ValueError as e:
            raise CastError(f"interval_sec must be a number: {raw_interval}") from e
    order = (params.get("order") or ORDER_ARRAY_ASC).strip() or ORDER_ARRAY_ASC
    msg = cast_slideshow(
        urls,
        interval_sec=interval,
        order=order,
        display_base_url=display_base_url,
        timeout_sec=timeout_sec,
    )
    return (
        f"{msg} · cast_status=accepted (legacy Mac HTTP slideshow→sequential)",
        {
            "cast_transport": "mac_http_9095_legacy",
            "cast_status": "accepted",
            "protocol_version": 0,
            "count": len(urls),
        },
    )
