"""OpenAI-compatible Chat Completions text-only for query.content."""

from __future__ import annotations

import logging
import time
from typing import Any

from mac_edge.plugins.query_providers import QueryProviderError
from mac_edge.plugins.query_providers.config import (
    query_api_base,
    query_api_key,
    query_model,
)

log = logging.getLogger("mac_edge.query.openai")

DEFAULT_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIChatQueryProvider:
    name = "openai"

    def complete(
        self,
        *,
        prompt: str,
        timeout_sec: float = 90.0,
        text_format: dict | None = None,
    ) -> dict[str, Any]:
        del text_format  # OpenAI json_object below; unused Ark format.
        key = query_api_key()
        if not key:
            raise QueryProviderError(
                "missing MAC_EDGE_QUERY_API_KEY / ARK_API_KEY (openai provider)"
            )
        base = query_api_base(DEFAULT_BASE)
        model = query_model(DEFAULT_MODEL)
        endpoint = f"{base}/chat/completions"
        body = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        log.info("openai query complete model=%s endpoint=%s", model, endpoint)
        try:
            import httpx  # type: ignore
        except ImportError as e:
            raise QueryProviderError(
                "httpx missing — run: pip install httpx"
            ) from e
        t_api0 = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.post(endpoint, json=body, headers=headers)
        except httpx.RequestError as e:
            raise QueryProviderError(f"openai query request failed: {e}") from e
        api_ms = int((time.perf_counter() - t_api0) * 1000)
        if resp.status_code >= 400:
            raise QueryProviderError(
                f"openai query HTTP {resp.status_code}: {resp.text[:400]}"
            )
        try:
            payload = resp.json()
        except Exception as e:
            raise QueryProviderError(f"openai query invalid JSON: {e}") from e
        text = str(
            (((payload.get("choices") or [{}])[0].get("message") or {}).get("content"))
            or ""
        ).strip()
        if not text:
            raise QueryProviderError("openai query empty content")
        log.info("openai query complete ok model=%s api_ms=%s", model, api_ms)
        return {
            "raw_text": text,
            "model": model,
            "_provider_text": text,
            "api_latency_ms": api_ms,
        }

    def generate_image(
        self,
        *,
        prompt: str,
        timeout_sec: float = 90.0,
    ) -> bytes:
        del prompt, timeout_sec
        raise QueryProviderError("openai provider does not generate images")
