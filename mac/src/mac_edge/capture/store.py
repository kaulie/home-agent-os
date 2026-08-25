"""Runtime-private GoPro inbox. Capabilities do not readdir this folder.

Layout: ``{MAC_EDGE_DATA_DIR or mac/data}/captures/inbox/{capture_id}.jpg``
plus a ``.json`` sidecar. Files stay after upload so the same capture can
retry or go to another dest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^cap_[0-9a-f]{24}$")


class CaptureStoreError(Exception):
    pass


def inbox_dir() -> Path:
    raw = (os.environ.get("MAC_EDGE_DATA_DIR") or os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if raw:
        root = Path(raw)
    else:
        root = Path(__file__).resolve().parents[3] / "data"
    path = root / "captures" / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_capture_id() -> str:
    return "cap_" + secrets.token_hex(12)


def jpeg_path(capture_id: str) -> Path:
    cid = _require_id(capture_id)
    return inbox_dir() / f"{cid}.jpg"


def sidecar_path(capture_id: str) -> Path:
    cid = _require_id(capture_id)
    return inbox_dir() / f"{cid}.json"


def put(
    jpeg: bytes,
    *,
    original_name: str = "",
    source: str = "gopro",
) -> dict[str, str]:
    data = bytes(jpeg or b"")
    if not data:
        raise CaptureStoreError("empty jpeg")
    cid = new_capture_id()
    jpeg_path(cid).write_bytes(data)
    meta = {
        "capture_id": cid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "original_name": original_name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "uploaded_dests": [],
    }
    sidecar_path(cid).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return capture_ref(cid)


def capture_ref(capture_id: str) -> dict[str, str]:
    cid = _require_id(capture_id)
    return {
        "capture_id": cid,
        "type": "image",
        "mime_type": "image/jpeg",
    }


def open_jpeg(capture_id: str) -> Path:
    path = jpeg_path(capture_id)
    if not path.is_file() or path.stat().st_size <= 0:
        raise CaptureStoreError(f"本机 inbox 没有 {capture_id}")
    return path


def read_bytes(capture_id: str) -> bytes:
    data = open_jpeg(capture_id).read_bytes()
    if not data:
        raise CaptureStoreError(f"本机 inbox 没有 {capture_id}")
    return data


def mark_uploaded(capture_id: str, dest: str) -> None:
    cid = _require_id(capture_id)
    dest_name = str(dest or "").strip()
    if not dest_name:
        return
    meta = _read_meta(cid)
    dests = list(meta.get("uploaded_dests") or [])
    if dest_name not in dests:
        dests.append(dest_name)
    meta["uploaded_dests"] = dests
    sidecar_path(cid).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def unique_pending(dest: str) -> str:
    """Exactly one inbox item not yet uploaded to dest. Runtime-only listing."""
    dest_name = str(dest or "").strip()
    pending: list[str] = []
    for sidecar in sorted(inbox_dir().glob("cap_*.json")):
        cid = sidecar.stem
        if not _ID_RE.match(cid):
            continue
        if not jpeg_path(cid).is_file():
            continue
        meta = _read_meta(cid)
        dests = [str(x) for x in (meta.get("uploaded_dests") or [])]
        if dest_name and dest_name in dests:
            continue
        pending.append(cid)
    if not pending:
        raise CaptureStoreError("本机 inbox 没有待上传的 capture，请带 capture_id")
    if len(pending) > 1:
        raise CaptureStoreError("本机 inbox 有多条待上传，请带 capture_id")
    return pending[0]


def parse_capture_id(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        cid = str(raw.get("capture_id") or "").strip()
        return cid if _ID_RE.match(cid) else None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("$"):
        return None
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parse_capture_id(obj)
    return text if _ID_RE.match(text) else None


def _require_id(capture_id: str) -> str:
    cid = str(capture_id or "").strip()
    if not _ID_RE.match(cid):
        raise CaptureStoreError(f"invalid capture_id: {capture_id!r}")
    return cid


def _read_meta(capture_id: str) -> dict[str, Any]:
    path = sidecar_path(capture_id)
    if not path.is_file():
        return {"capture_id": capture_id, "uploaded_dests": []}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"capture_id": capture_id, "uploaded_dests": []}
    return obj if isinstance(obj, dict) else {"capture_id": capture_id, "uploaded_dests": []}
