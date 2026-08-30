"""Localhost HTTP bridge: Mac Edge → mac_voice HAP1 speak downlink.

mac_voice owns the phone TCP sockets; mac_edge is a separate process, so speak
for phone_hap1 intents is POSTed here and forwarded on the live HAP1 session.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from mac_voice.audio.pickup_ingest import get_active_ingest

log = logging.getLogger("mac_voice.audio.pickup_speak_bridge")

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8793

_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        log.debug("speak_bridge %s - " + fmt, self.address_string(), *args)

    def _json(self, code: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/v1/pickup/health"):
            ingest = get_active_ingest()
            self._json(
                200,
                {
                    "ok": True,
                    "ingest": ingest is not None,
                    "connected": int(ingest.connected_count) if ingest else 0,
                },
            )
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in ("/v1/pickup/speak", "/speak"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"ok": False, "error": "invalid json"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"ok": False, "error": "json object required"})
            return
        text = str(payload.get("text") or "").strip()
        participant_id = str(payload.get("participant_id") or "").strip()
        if not text:
            self._json(400, {"ok": False, "error": "missing text"})
            return
        ingest = get_active_ingest()
        if ingest is None:
            self._json(503, {"ok": False, "error": "pickup ingest not running"})
            return
        sent = ingest.send_speak(text, participant_id=participant_id)
        if sent <= 0:
            self._json(
                503,
                {
                    "ok": False,
                    "error": "no phone_hap1 client connected",
                    "sent": 0,
                },
            )
            return
        self._json(200, {"ok": True, "sent": sent})


def start_speak_bridge(
    *,
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
) -> None:
    """Idempotent: start once per process."""
    global _server, _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        try:
            server = ThreadingHTTPServer((host, port), _Handler)
        except OSError:
            log.exception("pickup speak bridge bind failed %s:%s", host, port)
            return
        _server = server
        _thread = threading.Thread(
            target=server.serve_forever,
            name="mac-voice-pickup-speak-bridge",
            daemon=True,
        )
        _thread.start()
        log.info("pickup speak bridge listening http://%s:%s/v1/pickup/speak", host, port)


def stop_speak_bridge() -> None:
    global _server, _thread
    with _lock:
        server = _server
        _server = None
        _thread = None
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass
