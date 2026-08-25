"""Thin Brain wrapper: AssetRef → OCR HTTP service → OCRResult.

Planner / capability contract is image.ocr. This helper does not import
PaddleOCR. The OCR service never sees asset_id.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from sdk.asset_bytes import AssetFetchError, fetch_asset_image_bytes

log = logging.getLogger("sdk.image_ocr")

DEFAULT_OCR_URL = "http://127.0.0.1:9188"
MAX_TEXT_PREVIEW = 80


class ImageOcrError(Exception):
    pass


def ocr_service_url() -> str:
    return (os.environ.get("OCR_SERVICE_URL") or DEFAULT_OCR_URL).strip().rstrip("/")


def parse_asset_id(params: dict[str, Any] | None) -> str:
    raw = params if isinstance(params, dict) else {}
    value = raw.get("asset_ref")
    if value is None or value == "":
        value = raw.get("asset_id")
    if isinstance(value, dict):
        return str(value.get("asset_id") or "").strip()
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise ImageOcrError("asset_ref 不是合法 JSON") from e
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        if isinstance(parsed, dict):
            return str(parsed.get("asset_id") or "").strip()
        raise ImageOcrError("asset_ref JSON 必须是 AssetRef 对象")
    return text


def _as_bool(raw: Any, default: bool = True) -> bool:
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def _post_ocr(
    image_bytes: bytes,
    *,
    language: str,
    return_bbox: bool,
    return_confidence: bool,
    timeout_sec: float,
    url: str,
) -> dict[str, Any]:
    payload = json.dumps(
        {
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            "language": language,
            "options": {
                "return_bbox": return_bbox,
                "return_confidence": return_confidence,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/ocr",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read() if e.fp else b""
        except Exception:
            pass
        detail = body.decode("utf-8", errors="replace")[:240]
        raise ImageOcrError(f"OCR 服务失败 HTTP {e.code}：{detail}") from e
    except urllib.error.URLError as e:
        raise ImageOcrError(
            f"OCR 服务连不上（{url}）：{e.reason}。请确认云上 ocr-service 已启动"
        ) from e
    except TimeoutError as e:
        raise ImageOcrError("OCR 服务超时") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ImageOcrError("OCR 服务返回不是合法 JSON") from e
    if not isinstance(data, dict):
        raise ImageOcrError("OCR 服务返回必须是对象")
    if data.get("error"):
        raise ImageOcrError(str(data["error"]))
    text = str(data.get("text") or "")
    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        raise ImageOcrError("OCR 服务缺少 blocks 数组")
    return {
        "text": text,
        "blocks": blocks,
        "language": str(data.get("language") or language),
        "engine": str(data.get("engine") or ""),
        "model": str(data.get("model") or ""),
        "model_version": str(data.get("model_version") or ""),
    }


def ocr_from_params(
    params: dict[str, Any] | None,
    *,
    fetch_bytes: Callable[..., tuple[bytes, str]] | None = None,
    post_ocr: Callable[..., dict[str, Any]] | None = None,
    timeout_sec: float = 60.0,
) -> tuple[str, dict[str, Any]]:
    aid = parse_asset_id(params)
    if not aid:
        raise ImageOcrError("缺少必填 asset_ref（图片 Asset）")
    raw = params if isinstance(params, dict) else {}
    language = str(raw.get("language") or "zh").strip() or "zh"
    return_bbox = _as_bool(raw.get("return_bbox"), True)
    return_confidence = _as_bool(raw.get("return_confidence"), True)

    getter = fetch_bytes or fetch_asset_image_bytes
    try:
        image_bytes, _mime = getter(aid)
    except AssetFetchError as e:
        raise ImageOcrError(str(e)) from e
    except ImageOcrError:
        raise
    except Exception as e:
        raise ImageOcrError(f"读取图片失败：{e}") from e

    poster = post_ocr or _post_ocr
    result = poster(
        image_bytes,
        language=language,
        return_bbox=return_bbox,
        return_confidence=return_confidence,
        timeout_sec=timeout_sec,
        url=ocr_service_url(),
    )
    outputs: dict[str, Any] = {
        "text": result["text"],
        "blocks": json.dumps(result["blocks"], ensure_ascii=False),
        "language": result["language"],
        "engine": result.get("engine") or "",
        "model": result.get("model") or "",
        "model_version": result.get("model_version") or "",
        "asset_id": aid,
    }
    preview = str(outputs["text"])[:MAX_TEXT_PREVIEW]
    log.info("image.ocr asset=%s chars=%s engine=%s", aid, len(outputs["text"]), outputs["engine"])
    return f"image.ocr {preview or 'ok'}", outputs
