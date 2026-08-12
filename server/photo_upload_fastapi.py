"""GoPro photo upload + download — FastAPI variant.

  POST /api/v1/photos/upload
  GET  /api/v1/photos/download_latest
  GET  /api/v1/photos/{saved_as}
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads" / "gopro"
UPLOAD_PATH = "/api/v1/photos/upload"
DOWNLOAD_LATEST_PATH = "/api/v1/photos/download_latest"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}

router = APIRouter(tags=["photos"])


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


def _public_photo_url(request: Request, saved_as: str) -> str:
    # Production static host (nginx): http://115.190.153.53:8080/{saved_as}
    return f"http://115.190.153.53:8080/{Path(saved_as).name}"


def _file_response(path: Path) -> FileResponse:
    mime, _ = mimetypes.guess_type(path.name)
    return FileResponse(
        path=path,
        media_type=mime or "image/jpeg",
        filename=path.name,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.post(UPLOAD_PATH)
async def upload_photo(
    request: Request,
    file: UploadFile = File(..., description='multipart field name must be "file"'),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    original = Path(file.filename or "photo.jpg").name.replace("/", "_") or "photo.jpg"
    saved_as = f"{uuid.uuid4().hex[:8]}_{original}"
    dest = UPLOAD_DIR / saved_as
    dest.write_bytes(data)

    return JSONResponse(
        {
            "ok": True,
            "filename": original,
            "saved_as": saved_as,
            "bytes": len(data),
            "path": str(dest),
            "url": _public_photo_url(request, saved_as),
        }
    )


@router.get(DOWNLOAD_LATEST_PATH)
async def download_latest_photos():
    latest = _latest_image(UPLOAD_DIR)
    if latest is None:
        raise HTTPException(status_code=404, detail="no photos on server")
    return _file_response(latest)


@router.get("/api/v1/photos/{saved_as}")
async def download_photo_by_name(saved_as: str):
    if saved_as in ("upload", "download_latest"):
        raise HTTPException(status_code=404, detail="not found")
    path = _safe_upload_file(saved_as)
    if path is None:
        raise HTTPException(status_code=404, detail="photo not found")
    return _file_response(path)


@router.get("/health")
async def health():
    return {
        "ok": True,
        "upload": UPLOAD_PATH,
        "download_latest": DOWNLOAD_LATEST_PATH,
        "download_by_name": "/api/v1/photos/<saved_as>",
    }


app = FastAPI(title="GoPro photo upload")
app.include_router(router)
