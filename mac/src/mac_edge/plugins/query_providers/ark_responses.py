"""Volcengine Ark Responses API — text-only complete for query.content."""

from __future__ import annotations

import logging
import time
from typing import Any

from mac_edge.cloud_usage import record
from mac_edge.plugins.query_providers import QueryProviderError
from mac_edge.plugins.query_providers.ark_sdk import make_ark_client
from mac_edge.plugins.query_providers.config import (
    query_api_base,
    query_api_key,
    query_model,
)

log = logging.getLogger("mac_edge.query.ark")

DEFAULT_BASE = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seed-2-1-pro-260628"

QUERY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "answer_text",
        "want_image",
        "image_prompt",
        "domain",
        "refused",
        "citations",
    ],
    "properties": {
        "answer_text": {
            "type": "string",
            "description": "对用户问题的回答；不确定时必须直说「我不知道」",
        },
        "want_image": {
            "type": "boolean",
            "description": (
                "简单知识 false；外观/结构/步骤/笔顺等示意 true；"
                "用户要求出图则 true；拒答 false"
            ),
        },
        "image_prompt": {
            "type": "string",
            "description": (
                "出图时的画面描述；不出图可空。"
                "笔顺类须描述该字规范笔顺示意图（白底黑字、带笔画序号）"
            ),
        },
        "domain": {
            "type": "string",
            "enum": [
                "general",
                "science",
                "health",
                "medicine",
                "professional",
            ],
        },
        "refused": {
            "type": "boolean",
            "description": "不知道或不能答时为 true",
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "url"],
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                },
            },
        },
    },
}

TEXT_FORMAT_JSON_SCHEMA: dict[str, Any] = {
    "format": {
        "type": "json_schema",
        "name": "home_query_content",
        "strict": True,
        "schema": QUERY_JSON_SCHEMA,
    }
}
TEXT_FORMAT_JSON_OBJECT: dict[str, Any] = {
    "format": {"type": "json_object"},
}


def _extract_output_text(response: Any) -> str:
    if response is None:
        return ""

    direct = getattr(response, "output_text", None)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    if isinstance(response, dict):
        direct = response.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        output = response.get("output") or []
    else:
        output = getattr(response, "output", None) or []

    chunks: list[str] = []
    for item in output:
        if item is None:
            continue
        if isinstance(item, dict):
            content = item.get("content") or []
            item_text = item.get("text")
        else:
            content = getattr(item, "content", None) or []
            item_text = getattr(item, "text", None)

        if isinstance(content, list):
            for part in content:
                if part is None:
                    continue
                if isinstance(part, dict):
                    text = part.get("text") or part.get("output_text")
                else:
                    text = getattr(part, "text", None) or getattr(
                        part, "output_text", None
                    )
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        if isinstance(item_text, str) and item_text.strip():
            chunks.append(item_text.strip())

    if chunks:
        return chunks[-1]
    return ""


def _ark_client(*, timeout_sec: float):
    return make_ark_client(
        api_key=query_api_key(),
        base_url=query_api_base(DEFAULT_BASE),
        timeout_sec=timeout_sec,
    )


class ArkQueryProvider:
    """火山方舟 Responses text-only + Seedream 生图。"""

    name = "ark"

    def complete(
        self,
        *,
        prompt: str,
        timeout_sec: float = 90.0,
        text_format: dict | None = None,
    ) -> dict[str, Any]:
        key = query_api_key()
        if not key:
            raise QueryProviderError(
                "missing MAC_EDGE_QUERY_API_KEY / ARK_API_KEY"
            )
        model = query_model(DEFAULT_MODEL)
        client = _ark_client(timeout_sec=timeout_sec)

        formats: list[tuple[dict[str, Any], str]]
        if text_format:
            formats = [(text_format, "custom")]
        else:
            formats = [
                (TEXT_FORMAT_JSON_SCHEMA, "json_schema"),
                (TEXT_FORMAT_JSON_OBJECT, "json_object"),
            ]

        t_api0 = time.perf_counter()
        last_err: Exception | None = None
        response = None
        used_text_format = "json_schema"
        with record("ark.query"):
            for text_fmt, label in formats:
                try:
                    response = client.responses.create(
                        model=model,
                        input=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "input_text", "text": prompt},
                                ],
                            }
                        ],
                        text=text_fmt,
                    )
                    used_text_format = label
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    msg = str(e).lower()
                    if label == "json_schema" and (
                        "unknown field" in msg and "json_schema" in msg
                        or 'unknown field "schema"' in msg
                        or 'unknown field "name"' in msg
                    ):
                        log.warning(
                            "ark text.format json_schema unsupported, retry json_object: %s",
                            e,
                        )
                        continue
                    api_ms = int((time.perf_counter() - t_api0) * 1000)
                    log.warning(
                        "ark query responses.create failed after api_ms=%s: %s",
                        api_ms,
                        e,
                    )
                    raise QueryProviderError(
                        f"ark responses.create failed: {e}"
                    ) from e
            if response is None:
                api_ms = int((time.perf_counter() - t_api0) * 1000)
                raise QueryProviderError(
                    f"ark responses.create failed: {last_err}"
                ) from last_err

            api_ms = int((time.perf_counter() - t_api0) * 1000)
            text = _extract_output_text(response)
            if not text:
                raise QueryProviderError(
                    f"ark responses empty output_text (type={type(response).__name__})"
                )
        log.info(
            "ark query complete ok model=%s text_format=%s api_ms=%s",
            model,
            used_text_format,
            api_ms,
        )
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
        from mac_edge.plugins.query_providers.ark_images import generate_image

        return generate_image(prompt=prompt, timeout_sec=timeout_sec)
