"""Volcengine Ark Seedream images.generate for query.content."""

from __future__ import annotations

import base64
import logging
import time
from typing import Any
from urllib.request import Request, urlopen

from mac_edge.plugins.query_providers import QueryProviderError
from mac_edge.plugins.query_providers.ark_sdk import make_ark_client
from mac_edge.plugins.query_providers.config import (
    query_api_base,
    query_api_key,
    query_image_model,
)

log = logging.getLogger("mac_edge.query.ark_images")

DEFAULT_BASE = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_IMAGE_MODEL = "ep-20260814163146-9nwqb"


def _item_get(item: Any, key: str) -> Any:
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _download_url(url: str, *, timeout_sec: float) -> bytes:
    req = Request(url, method="GET")
    with urlopen(req, timeout=timeout_sec) as resp:
        data = resp.read()
    if not data:
        raise QueryProviderError("seedream image url returned empty body")
    return data


def _first_image_bytes(response: Any, *, timeout_sec: float) -> bytes:
    if response is None:
        raise QueryProviderError("seedream empty response")
    data = _item_get(response, "data")
    if not data:
        raise QueryProviderError("seedream empty data")
    item = data[0]
    b64 = _item_get(item, "b64_json")
    if isinstance(b64, str) and b64.strip():
        try:
            return base64.b64decode(b64)
        except Exception as e:
            raise QueryProviderError(f"seedream invalid b64_json: {e}") from e
    url = _item_get(item, "url")
    if isinstance(url, str) and url.strip():
        return _download_url(url.strip(), timeout_sec=min(timeout_sec, 60.0))
    raise QueryProviderError("seedream no b64_json or url")


def generate_image(*, prompt: str, timeout_sec: float = 90.0) -> bytes:
    text = (prompt or "").strip()
    if not text:
        raise QueryProviderError("missing image prompt")
    key = query_api_key()
    if not key:
        raise QueryProviderError("missing MAC_EDGE_QUERY_API_KEY / ARK_API_KEY")
    model = query_image_model(DEFAULT_IMAGE_MODEL)
    base = query_api_base(DEFAULT_BASE)
    client = make_ark_client(api_key=key, base_url=base, timeout_sec=timeout_sec)

    log.info("ark images.generate model=%s prompt=%s", model, text[:80])
    t0 = time.perf_counter()
    try:
        try:
            response = client.images.generate(
                model=model,
                prompt=text,
                sequential_image_generation="disabled",
                response_format="url",
                size="2K",
                stream=False,
                watermark=True,
            )
        except TypeError:
            response = client.images.generate(
                model=model,
                prompt=text,
                size="2K",
                response_format="url",
                watermark=True,
            )
    except Exception as e:
        api_ms = int((time.perf_counter() - t0) * 1000)
        log.warning("ark images.generate failed after api_ms=%s: %s", api_ms, e)
        raise QueryProviderError(f"ark images.generate failed: {e}") from e
    api_ms = int((time.perf_counter() - t0) * 1000)
    image_bytes = _first_image_bytes(response, timeout_sec=timeout_sec)
    log.info(
        "ark images.generate ok model=%s api_ms=%s bytes=%s",
        model,
        api_ms,
        len(image_bytes),
    )
    return image_bytes
