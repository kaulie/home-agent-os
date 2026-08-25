#!/usr/bin/env python3
"""Local LAN img-server — HTTP blob store, not a capability.

  python3 img-server/serve.py

  POST /api/v1/photos/upload
  GET  /health
  GET  /{saved_as}          Cast-style inline
  GET  /img/{saved_as}
  GET  /latest
  GET  /api/v1/photos/<saved_as>
  GET  /api/v1/photos/download_latest

Env:
  PHOTO_UPLOAD_HOST   default 0.0.0.0
  PHOTO_UPLOAD_PORT   default 8080
  PHOTO_UPLOAD_DIR    default <this dir>/img
  PHOTO_PUBLIC_BASE   default http://<lan-ip>:8080 (fallback 192.168.3.73)
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import socket
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
HOST = "0.0.0.0"
PORT = 8080
UPLOAD_DIR = ROOT / "img"
PUBLIC_BASE = "http://192.168.3.73:8080"
UPLOAD_PATH = "/api/v1/photos/upload"
DOWNLOAD_LATEST_PATH = "/api/v1/photos/download_latest"
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}


def guess_lan_public_base(port: int) -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return f"http://{ip}:{port}"
    except OSError:
        pass
    return f"http://192.168.3.73:{port}"


def _load_env() -> None:
    global HOST, PORT, UPLOAD_DIR, PUBLIC_BASE
    HOST = (os.environ.get("PHOTO_UPLOAD_HOST") or HOST).strip() or HOST
    raw_port = (os.environ.get("PHOTO_UPLOAD_PORT") or "").strip()
    if raw_port:
        PORT = int(raw_port)
    raw_dir = (os.environ.get("PHOTO_UPLOAD_DIR") or "").strip()
    if raw_dir:
        UPLOAD_DIR = Path(raw_dir).expanduser()
    raw_base = (os.environ.get("PHOTO_PUBLIC_BASE") or "").strip().rstrip("/")
    PUBLIC_BASE = raw_base or guess_lan_public_base(PORT)


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _parse_multipart(content_type: str, body: bytes) -> tuple[str, bytes] | None:
    """Return (filename, file_bytes) for form field `file`."""
    m = re.search(r"boundary=(?P<b>[^;]+)", content_type, flags=re.I)
    if not m:
        return None
    boundary = m.group("b").strip().strip('"').encode("utf-8")
    marker = b"--" + boundary
    parts = body.split(marker)
    for part in parts:
        if b"Content-Disposition" not in part:
            continue
        chunk = part
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.startswith(b"--"):
            continue
        if chunk.endswith(b"--\r\n"):
            chunk = chunk[:-4]
        elif chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]

        header_blob, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = header_blob.decode("utf-8", errors="replace")
        if 'name="file"' not in headers and "name=file" not in headers:
            continue
        fname = "photo.jpg"
        fm = re.search(r'filename="([^"]+)"', headers)
        if fm:
            fname = fm.group(1) or fname
        if data.endswith(b"\r\n"):
            data = data[:-2]
        return fname, data
    return None


def _latest_image(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    candidates = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES and not p.name.startswith(".")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.name))


def _safe_upload_file(saved_as: str) -> Path | None:
    name = Path(unquote(saved_as)).name
    if not name or name.startswith("."):
        return None
    candidate = (UPLOAD_DIR / name).resolve()
    try:
        candidate.relative_to(UPLOAD_DIR.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _public_photo_url(saved_as: str) -> str:
    return f"{PUBLIC_BASE.rstrip('/')}/{Path(saved_as).name}"


def _send_file(
    handler: BaseHTTPRequestHandler,
    path: Path,
    *,
    as_attachment: bool,
) -> None:
    data = path.read_bytes()
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "image/jpeg"
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(data)))
    if as_attachment:
        handler.send_header(
            "Content-Disposition",
            f'attachment; filename="{path.name}"',
        )
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(data)


def _serve_named(handler: BaseHTTPRequestHandler, saved_as: str, *, as_attachment: bool) -> bool:
    file_path = _safe_upload_file(saved_as)
    if file_path is None:
        return False
    _send_file(handler, file_path, as_attachment=as_attachment)
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            _json(
                self,
                200,
                {
                    "ok": True,
                    "service": "img-server",
                    "capability": False,
                    "upload": UPLOAD_PATH,
                    "download_latest": DOWNLOAD_LATEST_PATH,
                    "download_by_name": "/api/v1/photos/<saved_as>",
                    "static": "/{saved_as}",
                    "img": "/img/{saved_as}",
                    "latest": "/latest",
                    "public_base": PUBLIC_BASE,
                },
            )
            return
        if path in (DOWNLOAD_LATEST_PATH.rstrip("/"), "/latest"):
            latest = _latest_image(UPLOAD_DIR)
            if latest is None:
                _json(self, 404, {"ok": False, "error": "no photos on server"})
                return
            _send_file(self, latest, as_attachment=path.startswith("/api/"))
            return
        prefix = "/api/v1/photos/"
        if path.startswith(prefix) and path not in (
            UPLOAD_PATH.rstrip("/"),
            DOWNLOAD_LATEST_PATH.rstrip("/"),
        ):
            saved_as = path[len(prefix) :]
            if not _serve_named(self, saved_as, as_attachment=True):
                _json(self, 404, {"ok": False, "error": "photo not found"})
            return
        if path.startswith("/img/"):
            saved_as = path[len("/img/") :]
            if saved_as and "/" not in saved_as:
                if _serve_named(self, saved_as, as_attachment=False):
                    return
            _json(self, 404, {"ok": False, "error": "photo not found"})
            return
        if path != "/" and "/" not in path.lstrip("/"):
            if _serve_named(self, path.lstrip("/"), as_attachment=False):
                return
        _json(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path.rstrip("/") != UPLOAD_PATH.rstrip("/"):
            _json(self, 404, {"ok": False, "error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_BYTES:
            _json(self, 413, {"ok": False, "error": "file too large"})
            return
        body = self.rfile.read(length) if length > 0 else b""
        content_type = self.headers.get("Content-Type", "")

        parsed = _parse_multipart(content_type, body)
        if not parsed:
            _json(
                self,
                400,
                {
                    "ok": False,
                    "error": 'expected multipart/form-data with field name "file"',
                },
            )
            return

        filename, data = parsed
        if not data:
            _json(self, 400, {"ok": False, "error": "empty file"})
            return

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe = Path(filename).name.replace("/", "_") or "photo.jpg"
        saved_as = f"{uuid.uuid4().hex[:8]}_{safe}"
        dest = UPLOAD_DIR / saved_as
        dest.write_bytes(data)

        _json(
            self,
            200,
            {
                "ok": True,
                "filename": safe,
                "saved_as": saved_as,
                "bytes": len(data),
                "path": str(dest),
                "url": _public_photo_url(saved_as),
            },
        )


def main() -> None:
    _load_env()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"img-server listening on http://{HOST}:{PORT}{UPLOAD_PATH}", flush=True)
    print(f"health GET http://{HOST}:{PORT}/health", flush=True)
    print(f"static GET http://{HOST}:{PORT}/{{saved_as}}", flush=True)
    print(f"public_base={PUBLIC_BASE}", flush=True)
    print(f"files -> {UPLOAD_DIR}", flush=True)
    print("not a capability — LAN HTTP blob store only", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
