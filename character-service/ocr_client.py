"""HTTP client for the existing ocr-service. Does not import Paddle."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class OcrClientError(Exception):
    pass


def ocr_url() -> str:
    return (os.environ.get("OCR_SERVICE_URL") or "http://127.0.0.1:9188").rstrip("/")


def recognize(
    image_bytes: bytes,
    *,
    language: str = "zh",
    timeout: float = 120.0,
) -> dict[str, Any]:
    if not image_bytes:
        raise OcrClientError("empty image")
    payload = json.dumps(
        {
            "image_base64": __import__("base64").b64encode(image_bytes).decode("ascii"),
            "language": language,
            "options": {"return_bbox": True, "return_confidence": True},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        ocr_url() + "/v1/ocr",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:400]
        raise OcrClientError(f"ocr-service HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise OcrClientError(f"ocr-service unreachable ({ocr_url()}): {e.reason}") from e
    except (TimeoutError, ConnectionError) as e:
        raise OcrClientError(f"ocr-service unreachable ({ocr_url()}): {e}") from e
    if not isinstance(body, dict):
        raise OcrClientError("ocr-service returned non-object JSON")
    return body


def blocks_from_ocr(result: dict[str, Any]) -> list[dict[str, Any]]:
    raw = result.get("blocks") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        bbox = item.get("bbox")
        if not text or not bbox:
            continue
        out.append(
            {
                "text": text,
                "bbox": bbox,
                "confidence": item.get("confidence"),
            }
        )
    return out
