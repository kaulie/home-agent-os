"""Bing Image Search v7 — first ImageSearchProvider. Does not download or register Assets."""

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
    bing_search_endpoint,
    bing_search_key,
)

log = logging.getLogger("mac_edge.image_search.bing")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "HomeAgent/search.images"
)
MIN_INTERVAL_SEC = 0.5

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
        if e.code in (401, 403):
            raise ImageSearchProviderError(
                "必应搜图密钥无效或无权访问，请检查 MAC_EDGE_BING_SEARCH_KEY"
            ) from e
        if e.code == 429:
            raise ImageSearchProviderError(
                "必应搜图调用过于频繁或免费额度用尽，请稍后再试"
            ) from e
        raise ImageSearchProviderError(f"搜图失败 HTTP {e.code}：{text}") from e
    except urllib.error.URLError as e:
        raise ImageSearchProviderError(f"搜图网络异常：{e.reason}") from e
    except TimeoutError as e:
        raise ImageSearchProviderError("搜图超时") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ImageSearchProviderError("搜图返回不是合法 JSON") from e
    if not isinstance(data, dict):
        raise ImageSearchProviderError("搜图返回 JSON 必须是对象")
    return data


def _hits_from_bing(data: dict[str, Any]) -> list[ImageSearchHit]:
    rows = data.get("value")
    if not isinstance(rows, list):
        return []
    out: list[ImageSearchHit] = []
    for item in rows:
        hit = ImageSearchHit.from_dict(item) if isinstance(item, dict) else None
        if hit:
            out.append(hit)
    return out


class BingImageSearchProvider:
    name = "bing"

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
        q = (query or "").strip()
        if not q:
            raise ImageSearchProviderError("缺少搜索关键词")
        key = bing_search_key()
        if not key:
            raise ImageSearchProviderError(
                "未配置必应搜图密钥。请在 mac/.env 设置 MAC_EDGE_BING_SEARCH_KEY 后重启 Mac Edge"
            )
        params: dict[str, str] = {
            "q": q,
            "count": str(max(1, int(count))),
            "mkt": "zh-CN",
            "safeSearch": "Moderate",
            "imageType": "Photo",
        }
        if size:
            params["size"] = size
        if freshness:
            params["freshness"] = freshness
        url = bing_search_endpoint() + "?" + urllib.parse.urlencode(params)
        _throttle()
        data = self._http_json(
            url,
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "User-Agent": USER_AGENT,
            },
            timeout_sec=timeout_sec,
        )
        hits = _hits_from_bing(data)
        log.info("bing search query=%r hits=%s", q[:80], len(hits))
        return hits
