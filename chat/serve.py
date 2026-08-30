#!/usr/bin/env python3
"""Agent chatbox HTTP server. Local Mac only; not Brain.

  python3 chat/serve.py
  open http://127.0.0.1:8787/
"""

from __future__ import annotations

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT.parent))

from chat import db  # noqa: E402
from chat import attachments as chat_attachments  # noqa: E402
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


def _read_multipart(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_type = str(handler.headers.get("Content-Type") or "")
    if "multipart/form-data" not in content_type.lower():
        raise ValueError("expected multipart/form-data")
    match = re.search(r"boundary=([^;]+)", content_type)
    if not match:
        raise ValueError("multipart boundary missing")
    boundary = match.group(1).strip().strip('"')
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length) if length > 0 else b""
    delim = ("--" + boundary).encode("utf-8")
    out: dict[str, Any] = {}
    for chunk in raw.split(delim):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        header_blob, _, body = chunk.partition(b"\r\n\r\n")
        body = body.rstrip(b"\r\n")
        header_text = header_blob.decode("utf-8", errors="replace")
        name_match = re.search(r'name="([^"]+)"', header_text)
        if not name_match:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', header_text)
        if filename_match:
            mime_match = re.search(r"Content-Type:\s*([^\r\n]+)", header_text, re.I)
            out[name] = {
                "filename": filename_match.group(1),
                "mime_type": (mime_match.group(1).strip() if mime_match else ""),
                "data": body,
            }
        else:
            out[name] = body.decode("utf-8", errors="replace")
    return out


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
            if path == "/api/v1/work_board":
                self._send(200, {"ok": True, **db.work_board()})
                return
            if path == "/api/v1/pull_msg":
                handle = (query.get("handle") or [""])[0]
                since_raw = (query.get("since_id") or ["0"])[0] or "0"
                result = db.pull_messages(handle=handle, since_id=int(since_raw))
                self._send(200, result)
                return
            if path == "/api/v1/messages":
                since_raw = (query.get("since_id") or ["0"])[0] or "0"
                since_ack_raw = (query.get("since_ack_at") or ["0"])[0] or "0"
                page = db.list_messages_page(
                    since_id=int(since_raw),
                    since_ack_at=float(since_ack_raw),
                )
                self._send(
                    200,
                    {
                        "messages": page["messages"],
                        "ack_patches": page["ack_patches"],
                        "latest_ack_at": page["latest_ack_at"],
                        "agents": db.list_agents(),
                        "handles": list(HANDLES),
                        "display_names": DISPLAY_NAMES,
                        "boss_unread": db.boss_unread_count(),
                        "owner_unread": db.boss_unread_count(),
                    },
                )
                return
            if path.startswith("/api/v1/attachments/") and path.endswith("/content"):
                aid = path[len("/api/v1/attachments/") : -len("/content")].strip("/")
                try:
                    data, mime = chat_attachments.read_attachment(aid)
                except (FileNotFoundError, ValueError):
                    self._send(404, {"error": "not found"})
                    return
                self._send(200, data, content_type=mime)
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
                    attachments=payload.get("attachments"),
                )
                self._send(200, {"ok": True, "message": msg})
                return
            if path == "/api/v1/attachment/upload":
                form = _read_multipart(self)
                file_field = form.get("file")
                if not isinstance(file_field, dict):
                    raise ValueError('expected multipart field name "file"')
                data = file_field.get("data") or b""
                if not data:
                    raise ValueError("empty file")
                mime_type = str(form.get("mime_type") or file_field.get("mime_type") or "image/jpeg")
                filename = str(file_field.get("filename") or "upload.jpg")
                row = chat_attachments.store_image(data, filename=filename, mime_type=mime_type)
                self._send(200, {"ok": True, "attachment": row})
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
            if path == "/api/v1/ack_msg":
                payload = _read_json(self)
                msg = db.ack_message(
                    from_handle=str(payload.get("from") or ""),
                    message_id=int(payload["message_id"]),
                    ack_type=str(payload.get("ack_type") or "ok"),
                )
                self._send(200, {"ok": True, "message": msg})
                return
            if path == "/api/v1/unack_msg":
                payload = _read_json(self)
                msg = db.unack_message(
                    from_handle=str(payload.get("from") or ""),
                    message_id=int(payload["message_id"]),
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
