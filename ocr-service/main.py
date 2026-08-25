"""Standalone OCR HTTP service. No HomeAgent Asset / Brain / Runtime imports.

POST /v1/ocr  image bytes → structured OCR
GET  /health
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import threading
from email import message_from_bytes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from cache import cache_key, load as cache_load, store as cache_store
from engine import (
    ENGINE_NAME,
    MODEL_NAME,
    OcrEngineError,
    PaddleOcrEngine,
    build_result,
    model_version,
)

log = logging.getLogger("ocr_service")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9188
MAX_IMAGE_BYTES = 12 * 1024 * 1024

ENGINE = PaddleOcrEngine()
_PREDICT_LOCK = threading.Lock()


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    return int(raw)


def parse_bool(raw: Any, default: bool = True) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def decode_image_from_json(payload: dict[str, Any]) -> bytes:
    b64 = str(payload.get("image_base64") or payload.get("image") or "").strip()
    if not b64:
        raise ValueError("missing image_base64")
    if "," in b64 and b64.lower().startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        data = base64.b64decode(b64, validate=False)
    except Exception as e:
        raise ValueError("image_base64 is not valid base64") from e
    if not data:
        raise ValueError("empty image")
    return data


def decode_multipart(body: bytes, content_type: str) -> bytes:
    header = f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
    msg = message_from_bytes(header + body)
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            data = part.get_payload(decode=True)
            if data:
                return data
    data = msg.get_payload(decode=True)
    if data:
        return data
    raise ValueError("multipart 里没有图片")


def extract_image(handler: BaseHTTPRequestHandler, body: bytes) -> tuple[bytes, dict[str, Any]]:
    ctype = str(handler.headers.get("Content-Type") or "").lower()
    if "application/json" in ctype:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("JSON 无效") from e
        if not isinstance(payload, dict):
            raise ValueError("JSON 必须是对象")
        return decode_image_from_json(payload), payload
    if "multipart/" in ctype:
        return decode_multipart(body, str(handler.headers.get("Content-Type") or "")), {}
    if ctype.startswith("image/") or ctype in (
        "application/octet-stream",
        "application/x-www-form-urlencoded",
    ):
        if not body:
            raise ValueError("empty image")
        return body, {}
    if body[:1] in (b"{", b"["):
        payload = json.loads(body.decode("utf-8"))
        if isinstance(payload, dict):
            return decode_image_from_json(payload), payload
    if body:
        return body, {}
    raise ValueError("需要 JSON image_base64、multipart 文件或原始图片字节")


def run_ocr(
    image_bytes: bytes,
    *,
    language: str,
    return_bbox: bool,
    return_confidence: bool,
    engine: PaddleOcrEngine | None = None,
) -> dict[str, Any]:
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError(f"图片过大（>{MAX_IMAGE_BYTES} bytes）")
    key = cache_key(
        image_bytes,
        language=language,
        return_bbox=return_bbox,
        return_confidence=return_confidence,
        model_version=model_version(),
    )
    hit = cache_load(key)
    if hit:
        return hit
    with _PREDICT_LOCK:
        hit = cache_load(key)
        if hit:
            return hit
        blocks = (engine or ENGINE).recognize(image_bytes)
        result = build_result(
            blocks,
            language=language,
            return_bbox=return_bbox,
            return_confidence=return_confidence,
        )
        cache_store(key, result)
        return result


class OcrHandler(BaseHTTPRequestHandler):
    engine: PaddleOcrEngine = ENGINE

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/health", "/v1/health"):
            self._send(
                200,
                {
                    "status": "ok",
                    "engine": ENGINE_NAME,
                    "model": MODEL_NAME,
                    "model_version": model_version(),
                },
            )
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path not in ("/v1/ocr", "/ocr"):
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_IMAGE_BYTES + 64_000:
            self._send(413, {"error": "request too large"})
            return
        body = self.rfile.read(length) if length else b""
        try:
            image, extra = extract_image(self, body)
            options = extra.get("options") if isinstance(extra.get("options"), dict) else {}
            language = str(extra.get("language") or options.get("language") or "zh").strip() or "zh"
            return_bbox = parse_bool(options.get("return_bbox"), True)
            return_confidence = parse_bool(options.get("return_confidence"), True)
            result = run_ocr(
                image,
                language=language,
                return_bbox=return_bbox,
                return_confidence=return_confidence,
                engine=self.engine,
            )
        except ValueError as e:
            self._send(400, {"error": str(e)})
            return
        except OcrEngineError as e:
            self._send(503, {"error": str(e)})
            return
        except Exception as e:
            log.exception("ocr failed")
            self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return
        self._send(200, result)


def serve(host: str | None = None, port: int | None = None) -> None:
    bind = (host or os.environ.get("OCR_HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST
    listen = port if port is not None else _env_int("OCR_PORT", DEFAULT_PORT)
    httpd = ThreadingHTTPServer((bind, listen), OcrHandler)
    log.info(
        "ocr-service listening %s:%s engine=%s model=%s",
        bind,
        listen,
        ENGINE_NAME,
        MODEL_NAME,
    )
    httpd.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    serve()
