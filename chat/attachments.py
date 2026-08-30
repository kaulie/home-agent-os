"""Chat image storage — separate from Brain user assets (gopropics/assets)."""

from __future__ import annotations

import mimetypes
import os
import re
import secrets
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^chatimg_[0-9a-f]{24}$")
_DEFAULT_UPLOAD_ROOT = Path(__file__).resolve().parent / "data" / "uploads"
_MAX_BYTES = 12 * 1024 * 1024


def upload_root() -> Path:
    raw = (os.environ.get("CHAT_UPLOAD_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _DEFAULT_UPLOAD_ROOT


def reset_upload_root(path: Path | None = None) -> None:
    """Test helper: point uploads at a temp directory."""
    global _test_upload_root
    _test_upload_root = path.resolve() if path is not None else None


_test_upload_root: Path | None = None


def _active_root() -> Path:
    if _test_upload_root is not None:
        return _test_upload_root
    return upload_root()


def normalize_attachment_id(raw: str) -> str:
    aid = str(raw or "").strip()
    if not _ID_RE.match(aid):
        raise ValueError("invalid chat attachment id")
    return aid


def _guess_ext(filename: str, mime_type: str) -> str:
    name = str(filename or "").strip()
    if name and "." in name:
        ext = Path(name).suffix
        if ext:
            return ext
    mime = str(mime_type or "").strip().lower()
    if mime:
        ext = mimetypes.guess_extension(mime, strict=False)
        if ext:
            return ext
    return ".jpg"


def store_image(
    data: bytes,
    *,
    filename: str = "",
    mime_type: str = "image/jpeg",
) -> dict[str, str]:
    if not data:
        raise ValueError("empty file")
    if len(data) > _MAX_BYTES:
        raise ValueError(f"file too large (max {_MAX_BYTES // (1024 * 1024)}MB)")
    mime = str(mime_type or "image/jpeg").strip() or "image/jpeg"
    if not mime.lower().startswith("image/"):
        raise ValueError("only image uploads are supported")
    aid = "chatimg_" + secrets.token_hex(12)
    ext = _guess_ext(filename, mime)
    root = _active_root()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{aid}{ext}"
    dest.write_bytes(data)
    return {
        "attachment_id": aid,
        "kind": "image",
        "mime_type": mime,
        "filename": str(filename or dest.name).strip() or dest.name,
    }


def attachment_path(attachment_id: str) -> Path:
    aid = normalize_attachment_id(attachment_id)
    root = _active_root()
    matches = sorted(root.glob(f"{aid}.*"))
    if not matches:
        raise FileNotFoundError(aid)
    return matches[0]


def read_attachment(attachment_id: str) -> tuple[bytes, str]:
    path = attachment_path(attachment_id)
    data = path.read_bytes()
    mime, _ = mimetypes.guess_type(path.name)
    return data, str(mime or "application/octet-stream")


def normalize_attachments(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("attachment_id") or item.get("id") or "").strip()
        if not aid:
            continue
        row = {
            "attachment_id": aid,
            "kind": str(item.get("kind") or "image").strip() or "image",
        }
        mime = str(item.get("mime_type") or item.get("mime") or "").strip()
        if mime:
            row["mime_type"] = mime
        name = str(item.get("filename") or item.get("name") or "").strip()
        if name:
            row["filename"] = name
        out.append(row)
    return out
