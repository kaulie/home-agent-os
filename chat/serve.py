#!/usr/bin/env python3
"""Agent chatbox HTTP server. Local Mac only; not Brain.

  python3 chat/serve.py
  open http://127.0.0.1:8787/
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT.parent))

from chat import db  # noqa: E402
from chat.mentions import DISPLAY_NAMES, HANDLES  # noqa: E402

HOST = (os.environ.get("CHAT_HOST") or "127.0.0.1").strip() or "127.0.0.1"
PORT = int((os.environ.get("CHAT_PORT") or "8787").strip() or "8787")
STATIC_DIR = ROOT / "static"


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    if not raw:
        return {}
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


class ChatHandler(BaseHTTPRequestHandler):
    server_version = "AgentChat/1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, status: int, payload: object, content_type: str = "application/json; charset=utf-8") -> None:
        if isinstance(payload, (bytes, bytearray)):
            body = bytes(payload)
        elif content_type.startswith("application/json"):
            body = _json_bytes(payload)
        else:
            body = str(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        try:
            if path == "/":
                self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                return
            if path == "/health":
                self._send(200, {"ok": True, "app": "agent-chat", "db": str(db.db_path())})
                return
            if path == "/api/v1/pull_msg":
                handle = (query.get("handle") or [""])[0]
                since_raw = (query.get("since_id") or ["0"])[0] or "0"
                result = db.pull_messages(handle=handle, since_id=int(since_raw))
                self._send(200, result)
                return
            if path == "/api/v1/messages":
                since_raw = (query.get("since_id") or ["0"])[0] or "0"
                messages = db.list_messages(since_id=int(since_raw))
                self._send(
                    200,
                    {
                        "messages": messages,
                        "agents": db.list_agents(),
                        "handles": list(HANDLES),
                        "display_names": DISPLAY_NAMES,
                        "boss_unread": db.boss_unread_count(),
                        "owner_unread": db.boss_unread_count(),
                    },
                )
                return
            self._send(404, {"error": "not found"})
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path == "/api/v1/push_msg":
                payload = _read_json(self)
                msg = db.push_message(
                    from_handle=str(payload.get("from") or ""),
                    body=str(payload.get("body") or ""),
                )
                self._send(200, {"ok": True, "message": msg})
                return
            if path == "/api/v1/mark_read":
                payload = _read_json(self)
                handle = str(payload.get("from") or payload.get("handle") or "")
                raw_ids = payload.get("ids")
                ids = None
                if isinstance(raw_ids, list):
                    ids = [int(i) for i in raw_ids]
                result = db.mark_read(handle=handle, ids=ids)
                self._send(200, {"ok": True, **result})
                return
            if path == "/api/v1/recall_msg":
                payload = _read_json(self)
                msg = db.recall_message(
                    from_handle=str(payload.get("from") or ""),
                    msg_id=int(payload["id"]),
                )
                self._send(200, {"ok": True, "message": msg})
                return
            self._send(404, {"error": "not found"})
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON"})
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"error": str(exc)})


def main() -> None:
    db.list_agents()
    httpd = ThreadingHTTPServer((HOST, PORT), ChatHandler)
    print(f"agent chat http://{HOST}:{PORT}/  db={db.db_path()}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
        httpd.server_close()


if __name__ == "__main__":
    main()
