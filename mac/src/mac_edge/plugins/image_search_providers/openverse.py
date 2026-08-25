"""Openverse image search — Creative Commons / openly licensed photos.

Does not download or register Assets. Attribution fields stay on the hit.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from mac_edge.plugins.image_search_providers import (
    ImageSearchHit,
    ImageSearchProviderError,
)
from mac_edge.plugins.image_search_providers.config import (
    openverse_access_token,
    openverse_endpoint,
    openverse_user_agent,
)

log = logging.getLogger("mac_edge.image_search.openverse")

# Anonymous Openverse asks for a descriptive User-Agent and is rate-limited.
MIN_INTERVAL_SEC = 1.0

_rate_lock = threading.Lock()
_last_call_mono = 0.0


def _throttle() -> None:
    global _last_call_mono
    with _rate_lock:
        wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_call_mono)
        if wait > 0:
            time.sleep(wait)
        _last_call_mono = time.monotonic()


def _http_json(
    url: str,
    *,
    headers: dict[str, str],
    timeout_sec: float,
) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read() if e.fp else b""
        except Exception:
            pass
        text = body.decode("utf-8", errors="replace")[:240]
        if e.code == 429:
            raise ImageSearchProviderError(
                "Openverse 调用过于频繁，请稍后再试"
            ) from e
        if e.code in (401, 403):
            raise ImageSearchProviderError(
                f"Openverse 拒绝访问 HTTP {e.code}"
            ) from e
        raise ImageSearchProviderError(f"Openverse 搜图失败 HTTP {e.code}：{text}") from e
    except urllib.error.URLError as e:
        raise ImageSearchProviderError(f"Openverse 网络异常：{e.reason}") from e
    except TimeoutError as e:
        raise ImageSearchProviderError("Openverse 搜图超时") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ImageSearchProviderError("Openverse 返回不是合法 JSON") from e
    if not isinstance(data, dict):
        raise ImageSearchProviderError("Openverse 返回 JSON 必须是对象")
    return data


def _license_text(item: dict[str, Any]) -> str:
    lic = str(item.get("license") or "").strip()
    ver = str(item.get("license_version") or "").strip()
    url = str(item.get("license_url") or "").strip()
    parts = [p for p in (lic, ver) if p]
    label = " ".join(parts)
    if url and label:
        return f"{label} {url}"
    return label or url


def _hits_from_openverse(data: dict[str, Any]) -> list[ImageSearchHit]:
    rows = data.get("results")
    if not isinstance(rows, list):
        return []
    out: list[ImageSearchHit] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        content = str(item.get("url") or "").strip()
        thumb = str(item.get("thumbnail") or "").strip()
        if not content and not thumb:
            continue
        out.append(
            ImageSearchHit(
                content_url=content,
                thumbnail_url=thumb,
                host_page=str(item.get("foreign_landing_url") or "").strip(),
                name=str(item.get("title") or "").strip(),
                encoding=str(item.get("filetype") or "").strip(),
                license=_license_text(item),
                license_url=str(item.get("license_url") or "").strip(),
            )
        )
    return out


class OpenverseImageSearchProvider:
    name = "openverse"

    def __init__(
        self,
        *,
        http_json: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._http_json = http_json or _http_json

    def search(
        self,
        *,
        query: str,
        count: int,
        size: str = "",
        freshness: str = "",
        timeout_sec: float = 30.0,
    ) -> list[ImageSearchHit]:
        del size, freshness  # Openverse has no Bing-style size/freshness filters
        q = (query or "").strip()
        if not q:
            raise ImageSearchProviderError("缺少搜索关键词")
        page_size = max(1, min(20, int(count)))
        params = {
            "q": q,
            "page": "1",
            "page_size": str(page_size),
            "mature": "false",
        }
        url = openverse_endpoint().rstrip("/") + "/?" + urllib.parse.urlencode(params)
        headers = {
            "User-Agent": openverse_user_agent(),
            "Accept": "application/json",
        }
        token = openverse_access_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        _throttle()
        data = self._http_json(url, headers=headers, timeout_sec=timeout_sec)
        hits = _hits_from_openverse(data)
        log.info("openverse search query=%r hits=%s", q[:80], len(hits))
        return hits
