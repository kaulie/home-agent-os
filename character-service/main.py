"""Still-image point-to-character HTTP service.

Does not know HomeAgent Asset / Brain / Planner.
Calls ocr-service for text boxes; MediaPipe for the index finger.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
from email import message_from_bytes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from pipeline import PipelineError, run_still

log = logging.getLogger("character_service")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9189
MAX_IMAGE_BYTES = 12 * 1024 * 1024


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    return int(raw)


def parse_bool(raw: Any, default: bool = False) -> bool:
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
        payload = json.loads(body.decode("utf-8"))
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


class Handler(BaseHTTPRequestHandler):
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
                    "engine": "reading.point_to_character",
                    "ocr_service_url": os.environ.get("OCR_SERVICE_URL") or "http://127.0.0.1:9188",
                },
            )
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path not in ("/v1/point_to_character", "/point_to_character"):
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
            return_debug = parse_bool(extra.get("return_debug"), False) or parse_bool(
                options.get("return_debug"), False
            )
            result = run_still(image, language=language, return_debug=return_debug)
        except ValueError as e:
            self._send(400, {"error": str(e)})
            return
        except PipelineError as e:
            self._send(
                200,
                {
                    "engine": "reading.point_to_character",
                    "status": e.status,
                    "character": None,
                    "reason": str(e),
                },
            )
            return
        except Exception as e:
            log.exception("point_to_character failed")
            self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return
        self._send(200, result)


def serve(host: str | None = None, port: int | None = None) -> None:
    bind = (host or os.environ.get("CHARACTER_HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST
    listen = port if port is not None else _env_int("CHARACTER_PORT", DEFAULT_PORT)
    httpd = ThreadingHTTPServer((bind, listen), Handler)
    log.info("character-service listening %s:%s", bind, listen)
    httpd.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    serve()
