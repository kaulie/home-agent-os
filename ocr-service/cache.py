"""Disk cache keyed by image hash + OCR config + model version."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def cache_dir() -> Path:
    raw = (os.environ.get("OCR_CACHE_DIR") or "").strip()
    if raw:
        path = Path(raw)
    else:
        path = Path(__file__).resolve().parent / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_key(
    image_bytes: bytes,
    *,
    language: str,
    return_bbox: bool,
    return_confidence: bool,
    model_version: str,
) -> str:
    h = hashlib.sha256()
    h.update(image_bytes)
    h.update(b"|")
    h.update(language.encode("utf-8"))
    h.update(b"|")
    h.update(b"1" if return_bbox else b"0")
    h.update(b"|")
    h.update(b"1" if return_confidence else b"0")
    h.update(b"|")
    h.update(model_version.encode("utf-8"))
    h.update(b"|bbox-v2")
    return h.hexdigest()


def load(key: str) -> dict[str, Any] | None:
    path = cache_dir() / f"{key}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def store(key: str, payload: dict[str, Any]) -> None:
    path = cache_dir() / f"{key}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
