"""GoPro photo upload + download — copy into your Flask app.

Contracts (matches iOS GoProController / AssetHTTPTransport):

  POST /api/v1/photos/upload
    multipart/form-data, field name = "file"
    JSON: ok, filename, saved_as, bytes, path, url
    url = http://115.190.153.53:8080/{saved_as}  (static host for Cast)

  GET  /api/v1/photos/<saved_as>
    returns that image by server filename (API fallback)

  GET  /api/v1/photos/download_latest
    returns newest image bytes from UPLOAD_DIR (by mtime)

App defaults:
  upload  http://115.190.153.53:9527/api/v1/photos/upload
  public  http://115.190.153.53:8080/{saved_as}

curl:
  curl -F "file=@a.jpg" http://127.0.0.1:9527/api/v1/photos/upload
  curl -OJ http://127.0.0.1:9527/api/v1/photos/download_latest
  curl -OJ http://127.0.0.1:9527/api/v1/photos/<saved_as>
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from flask import Blueprint, Flask, jsonify, request, send_file

# Change on your server, e.g. Path("/root/chat-gateway/gopropics")
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads" / "gopro"
UPLOAD_PATH = "/api/v1/photos/upload"
DOWNLOAD_LATEST_PATH = "/api/v1/photos/download_latest"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}

bp = Blueprint("gopro_photos", __name__)


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
    # Newest by mtime; tie-break on name (uploads use uuid prefix + original).
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.name))


def _safe_upload_file(saved_as: str) -> Path | None:
    """Resolve saved_as under UPLOAD_DIR; reject path traversal."""
    name = Path(saved_as).name
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
    # Production static host (nginx): http://115.190.153.53:8080/{saved_as}
    return f"http://115.190.153.53:8080/{Path(saved_as).name}"


def _send_image(path: Path):
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "image/jpeg"
    resp = send_file(
        path,
        mimetype=mime,
        as_attachment=True,
        download_name=path.name,
        conditional=False,
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@bp.route(UPLOAD_PATH, methods=["POST"])
def upload_photo():
    """Accept one image from Edge; save under UPLOAD_DIR."""
    if "file" not in request.files:
        return jsonify(ok=False, error='expected multipart field name "file"'), 400

    f = request.files["file"]
    data = f.read()
    if not data:
        return jsonify(ok=False, error="empty file"), 400

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    original = Path(f.filename or "photo.jpg").name.replace("/", "_") or "photo.jpg"
    saved_as = f"{uuid.uuid4().hex[:8]}_{original}"
    dest = UPLOAD_DIR / saved_as
    dest.write_bytes(data)

    return jsonify(
        ok=True,
        filename=original,
        saved_as=saved_as,
        bytes=len(data),
        path=str(dest),
        url=_public_photo_url(saved_as),
    )


@bp.route(DOWNLOAD_LATEST_PATH, methods=["GET"])
def download_latest_photos():
    """Return the newest image file in UPLOAD_DIR (by modification time)."""
    latest = _latest_image(UPLOAD_DIR)
    if latest is None:
        return jsonify(ok=False, error="no photos on server"), 404
    return _send_image(latest)


@bp.route("/api/v1/photos/<path:saved_as>", methods=["GET"])
def download_photo_by_name(saved_as: str):
    """Return a previously uploaded image by its `saved_as` filename."""
    if saved_as in ("upload", "download_latest"):
        return jsonify(ok=False, error="not found"), 404
    path = _safe_upload_file(saved_as)
    if path is None:
        return jsonify(ok=False, error="photo not found"), 404
    return _send_image(path)


@bp.route("/health", methods=["GET"])
def health():
    return jsonify(
        ok=True,
        upload=UPLOAD_PATH,
        download_latest=DOWNLOAD_LATEST_PATH,
        download_by_name="/api/v1/photos/<saved_as>",
    )


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
    app.register_blueprint(bp)
    return app


app = create_app()


if __name__ == "__main__":
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    print(f"upload  POST http://0.0.0.0:9527{UPLOAD_PATH}")
    print(f"latest  GET  http://0.0.0.0:9527{DOWNLOAD_LATEST_PATH}")
    print(f"files -> {UPLOAD_DIR}")
    print("routes:", [str(r) for r in app.url_map.iter_rules()])
    app.run(host="0.0.0.0", port=9527, threaded=True)
