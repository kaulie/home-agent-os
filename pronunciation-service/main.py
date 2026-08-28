"""Standalone pronunciation assessment HTTP service. No HomeAgent Asset / Brain / Runtime imports.

POST /v1/assess  multipart (reference, student audio files) → passage-level scores JSON
GET  /health     liveness + engine status

The /assess response contract is fixed (see engine.ASSESS_RESPONSE_KEYS); the internal
ML pipeline can iterate without changing the wire shape.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from engine import (
    ENGINE_NAME,
    MODEL_NAME,
    PronunciationEngine,
    PronunciationEngineError,
    assess,
    engine_status,
)

log = logging.getLogger("pronunciation_service")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9190
MAX_AUDIO_BYTES = 64 * 1024 * 1024  # 64 MiB per file

_ENGINE = PronunciationEngine()
_ASSESS_LOCK = threading.Lock()


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    return int(raw)


def _save_part(part: Any, dest_dir: str) -> str:
    """Write a multipart part's payload to dest_dir, return the path."""
    filename = part.get_filename() or "audio.bin"
    # Sanitize: keep an extension, drop path components.
    base = os.path.basename(filename) or "audio.bin"
    suffix = os.path.splitext(base)[1] or ".bin"
    fd, path = tempfile.mkstemp(suffix=suffix, dir=dest_dir)
    with os.fdopen(fd, "wb") as fh:
        data = part.get_payload(decode=True)
        if not data:
            raise ValueError("empty audio part")
        if len(data) > MAX_AUDIO_BYTES:
            raise ValueError(f"audio too large (>{MAX_AUDIO_BYTES} bytes)")
        fh.write(data)
    return path


def _extract_audio_files(content_type: str, body: bytes) -> tuple[str, str]:
    """Parse multipart body, return (reference_path, student_path)."""
    from email import message_from_bytes

    header = f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
    msg = message_from_bytes(header + body)
    if not msg.is_multipart():
        raise ValueError("expected multipart request with reference + student audio")
    tmp_dir = tempfile.mkdtemp(prefix="pronassess-")
    reference_path: str | None = None
    student_path: str | None = None
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        # Field name comes from Content-Disposition: name="reference" / name="student"
        disp = part.get("Content-Disposition") or ""
        name = ""
        for chunk in disp.split(";"):
            chunk = chunk.strip()
            if chunk.lower().startswith("name="):
                name = chunk.split("=", 1)[1].strip().strip('"').lower()
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        path = _save_part(part, tmp_dir)
        if name == "reference":
            reference_path = path
        elif name == "student":
            student_path = path
    if not reference_path:
        raise ValueError("missing 'reference' audio part")
    if not student_path:
        raise ValueError("missing 'student' audio part")
    return reference_path, student_path


class AssessHandler(BaseHTTPRequestHandler):
    engine: PronunciationEngine = _ENGINE

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
        if path in ("/health", "/healthz", "/v1/health"):
            self._send(200, {"status": "ok", "engine": ENGINE_NAME, "model": MODEL_NAME, **engine_status()})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path not in ("/v1/assess", "/assess"):
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        # Two audio files + multipart overhead.
        if length > 2 * MAX_AUDIO_BYTES + 256_000:
            self._send(413, {"error": "request too large"})
            return
        body = self.rfile.read(length) if length else b""
        content_type = str(self.headers.get("Content-Type") or "")
        try:
            if "multipart/" not in content_type.lower():
                raise ValueError("Content-Type must be multipart/form-data")
            reference_path, student_path = _extract_audio_files(content_type, body)
        except ValueError as e:
            self._send(400, {"error": str(e)})
            return
        try:
            with _ASSESS_LOCK:
                result = assess(self.engine, reference_path, student_path)
        except PronunciationEngineError as e:
            self._send(503, {"error": str(e)})
            return
        except Exception as e:  # noqa: BLE001
            log.exception("assess failed")
            self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return
        finally:
            for p in (reference_path, student_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass
            try:
                os.rmdir(os.path.dirname(reference_path))
            except OSError:
                pass
        self._send(200, result)


def serve(host: str | None = None, port: int | None = None) -> None:
    bind = (host or os.environ.get("PRON_HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST
    listen = port if port is not None else _env_int("PRON_PORT", DEFAULT_PORT)
    httpd = ThreadingHTTPServer((bind, listen), AssessHandler)
    log.info(
        "pronunciation-service listening %s:%s engine=%s model=%s",
        bind, listen, ENGINE_NAME, MODEL_NAME,
    )
    httpd.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    serve()
