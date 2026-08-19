"""OpenAI-compatible Chat Completions vision (extensibility sample).

Enable with:
  MAC_EDGE_VISION_PROVIDER=openai
  MAC_EDGE_VISION_API_BASE=https://api.openai.com/v1
  MAC_EDGE_VISION_API_KEY=...
  MAC_EDGE_VISION_MODEL=gpt-4o-mini

Image is passed as image_url in messages (public URL).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from mac_edge.plugins.vision_providers import VisionProviderError
from mac_edge.plugins.vision_providers.config import (
    vision_api_base,
    vision_api_key,
    vision_model,
)
from mac_edge.plugins.vision_providers.image_input import prepare_image_for_model

log = logging.getLogger("mac_edge.vision.openai")

DEFAULT_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIChatVisionProvider:
    name = "openai"

    def analyze(
        self,
        *,
        image_url: str,
        prompt: str,
        timeout_sec: float = 90.0,
        text_format: dict | None = None,
    ) -> dict[str, Any]:
        base = vision_api_base(DEFAULT_BASE)
        key = vision_api_key()
        model = vision_model(DEFAULT_MODEL)
        if not key:
            return {
                "summary": "（占位）未配置 MAC_EDGE_VISION_API_KEY（openai provider）。",
                "people": [],
                "spatial": "",
                "actions": "",
                "posture": "",
                "lighting": "",
                "raw_text": prompt,
                "model": "",
            }

        image_ref, prep_meta = prepare_image_for_model(
            image_url, timeout_sec=min(timeout_sec, 60.0)
        )
        endpoint = f"{base}/chat/completions"
        body = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_ref},
                        },
                    ],
                }
            ],
        }
        if text_format is not None:
            body["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        log.info(
            "openai chat vision model=%s endpoint=%s image_mode=%s",
            model,
            endpoint,
            prep_meta.get("mode"),
        )
        t_api0 = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.post(endpoint, json=body, headers=headers)
        except httpx.RequestError as e:
            raise VisionProviderError(f"openai vision request failed: {e}") from e
        api_ms = int((time.perf_counter() - t_api0) * 1000)
        if resp.status_code >= 400:
            raise VisionProviderError(
                f"openai vision HTTP {resp.status_code}: {resp.text[:400]}"
            )
        try:
            payload = resp.json()
        except Exception as e:
            raise VisionProviderError(f"openai vision invalid JSON: {e}") from e
        text = str(
            (((payload.get("choices") or [{}])[0].get("message") or {}).get("content"))
            or ""
        ).strip()
        if not text:
            raise VisionProviderError("openai vision empty content")
        log.info(
            "openai chat vision ok model=%s api_ms=%s download_ms=%s",
            model,
            api_ms,
            prep_meta.get("download_ms"),
        )
        return {
            "raw_text": text,
            "model": model,
            "_provider_text": text,
            "api_latency_ms": api_ms,
            "download_latency_ms": int(prep_meta.get("download_ms") or 0),
            "prepare_latency_ms": int(prep_meta.get("prepare_ms") or 0),
            "image_mode": str(prep_meta.get("mode") or ""),
        }
