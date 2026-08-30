"""Volcengine Ark Responses API via official SDK.

Install on the Mac Edge host:

  pip install --upgrade "volcengine-python-sdk[ark]"

Uses:

  from volcenginesdkarkruntime import Ark
  client.responses.create(model=..., input=[{role, content:[input_image, input_text]}])
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mac_edge.cloud_usage import record
from mac_edge.plugins.vision_providers import VisionProviderError
from mac_edge.plugins.vision_providers.config import (
    vision_api_base,
    vision_api_key,
    vision_model,
)
from mac_edge.plugins.vision_providers.image_input import prepare_image_for_model

log = logging.getLogger("mac_edge.vision.ark")

DEFAULT_BASE = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seed-2-1-pro-260628"

# Force model raw output into the perception schema (no Edge-side unwrap/repair).
PERCEPTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "summary",
        "people",
        "spatial",
        "actions",
        "posture",
        "lighting",
    ],
    "properties": {
        "summary": {
            "type": "string",
            "description": "一句中文画面摘要；禁止以 { 开头；禁止把整段 JSON 放进本字段",
        },
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "description", "count", "position"],
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "count": {"type": "integer"},
                    "position": {"type": "string"},
                },
            },
        },
        "spatial": {"type": "string"},
        "actions": {
            "type": "string",
            "description": "中文短句；可用 p1/p2；禁止 JSON 数组字符串",
        },
        "posture": {"type": "string"},
        "lighting": {
            "type": "object",
            "additionalProperties": False,
            "required": ["whole", "region"],
            "properties": {
                "whole": {"type": "string"},
                "region": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["person_id", "lighting", "summary"],
                        "properties": {
                            "person_id": {"type": "string"},
                            "lighting": {"type": "string"},
                            "summary": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}

# Prefer OpenAI-style flat json_schema (name/schema/strict under format).
# Fall back to json_object if the endpoint rejects schema (some Ark models).
TEXT_FORMAT_JSON_SCHEMA: dict[str, Any] = {
    "format": {
        "type": "json_schema",
        "name": "home_perception",
        "strict": True,
        "schema": PERCEPTION_JSON_SCHEMA,
    }
}
TEXT_FORMAT_JSON_OBJECT: dict[str, Any] = {
    "format": {"type": "json_object"},
}


def _require_ark_sdk():
    try:
        from volcenginesdkarkruntime import Ark  # type: ignore
    except ImportError as e:
        raise VisionProviderError(
            'Ark SDK missing — run: pip install --upgrade "volcengine-python-sdk[ark]"'
        ) from e
    return Ark


def _extract_output_text(response: Any) -> str:
    """Normalize Ark SDK response object / dict → assistant text."""
    if response is None:
        return ""

    # SDK convenience attribute
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
            item_type = item.get("type")
            item_text = item.get("text")
        else:
            content = getattr(item, "content", None) or []
            item_type = getattr(item, "type", None)
            item_text = getattr(item, "text", None)

        # Prefer message-type blocks when present
        if item_type and str(item_type) not in ("message", "output_text", ""):
            # still try content below (some SDKs use reasoning + message)
            pass

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
        # Prefer the last message-like chunk (avoid joining reasoning + JSON).
        return chunks[-1]
    return ""


class ArkResponsesProvider:
    """Default provider: 火山方舟 Responses multimodal (official SDK)."""

    name = "ark"

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
                "summary": "（占位）未配置 MAC_EDGE_VISION_API_KEY / ARK_API_KEY。",
                "people": [],
                "spatial": "",
                "actions": "",
                "posture": "",
                "lighting": "",
                "raw_text": prompt,
                "model": "",
            }

        Ark = _require_ark_sdk()
        # timeout: SDK accepts timeout on client in recent versions
        try:
            client = Ark(base_url=base, api_key=key, timeout=timeout_sec)
        except TypeError:
            client = Ark(base_url=base, api_key=key)

        t_prep0 = time.perf_counter()
        image_ref, prep_meta = prepare_image_for_model(
            image_url, timeout_sec=min(timeout_sec, 60.0)
        )
        prep_wall_ms = int((time.perf_counter() - t_prep0) * 1000)

        log.info(
            "ark sdk responses.create model=%s base=%s image_mode=%s "
            "image=%s prep_wall_ms=%s",
            model,
            base,
            prep_meta.get("mode"),
            (image_url[:120] if not image_url.startswith("data:") else "data:…"),
            prep_wall_ms,
        )
        t_api0 = time.perf_counter()
        last_err: Exception | None = None
        response = None
        used_text_format = "json_schema"
        schema_fmt = text_format if text_format is not None else TEXT_FORMAT_JSON_SCHEMA
        with record("ark.vision"):
            for text_fmt, label in (
                (schema_fmt, "json_schema"),
                (TEXT_FORMAT_JSON_OBJECT, "json_object"),
            ):
                try:
                    response = client.responses.create(
                        model=model,
                        input=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "input_image", "image_url": image_ref},
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
                    # Only fall through when schema param unsupported; other errors fail loud.
                    if label == "json_schema" and (
                        "unknown field" in msg and "json_schema" in msg
                        or "unknown field \"schema\"" in msg
                        or "unknown field \"name\"" in msg
                    ):
                        log.warning(
                            "ark text.format json_schema unsupported, retry json_object: %s",
                            e,
                        )
                        continue
                    api_ms = int((time.perf_counter() - t_api0) * 1000)
                    log.warning(
                        "ark responses.create failed after api_ms=%s: %s", api_ms, e
                    )
                    raise VisionProviderError(f"ark responses.create failed: {e}") from e
            if response is None:
                api_ms = int((time.perf_counter() - t_api0) * 1000)
                log.warning(
                    "ark responses.create failed after api_ms=%s: %s", api_ms, last_err
                )
                raise VisionProviderError(
                    f"ark responses.create failed: {last_err}"
                ) from last_err
            api_ms = int((time.perf_counter() - t_api0) * 1000)

            text = _extract_output_text(response)
            if not text:
                raise VisionProviderError(
                    "ark responses empty output_text "
                    f"(type={type(response).__name__})"
                )
        log.info(
            "ark responses.create ok model=%s text_format=%s api_ms=%s download_ms=%s "
            "prepare_ms=%s bytes_in=%s bytes_out=%s",
            model,
            used_text_format,
            api_ms,
            prep_meta.get("download_ms"),
            prep_meta.get("prepare_ms"),
            prep_meta.get("bytes_in"),
            prep_meta.get("bytes_out"),
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
