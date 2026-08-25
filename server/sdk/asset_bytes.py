"""Resolve Image Asset bytes from Brain catalog. Capability never sees filesystem paths."""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import db as brain_db
except ImportError:  # pragma: no cover
    from server import db as brain_db  # type: ignore


class AssetFetchError(Exception):
    pass


def _upload_assets_dir() -> Path:
    raw = (os.environ.get("BRAIN_UPLOAD_DIR") or "").strip()
    if raw:
        return Path(raw) / "assets"
    here = Path(__file__).resolve().parents[1]
    default = here.parent / "gopropics"
    if not default.is_dir():
        default = here / "uploads" / "gopro"
    return default / "assets"


def _add_url(urls: list[str], seen: set[str], url: str) -> None:
    text = (url or "").strip()
    if text and text not in seen:
        seen.add(text)
        urls.append(text)


def _add_base_key(urls: list[str], seen: set[str], base: Any, key: Any) -> None:
    b = str(base or "").strip().rstrip("/")
    k = str(key or "").strip()
    if not k:
        return
    if k.startswith("http://") or k.startswith("https://"):
        _add_url(urls, seen, k)
        return
    if not b:
        return
    path = k if k.startswith("/") else f"/{k}"
    _add_url(urls, seen, b + path)


def media_urls(storage: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    _add_base_key(
        urls, seen, storage.get("cloud_public_base"), storage.get("cloud_key") or storage.get("key")
    )
    _add_base_key(
        urls, seen, storage.get("public_base"), storage.get("key") or storage.get("saved_as")
    )
    return urls


def fetch_asset_image_bytes(
    asset_id: str,
    *,
    timeout_sec: float = 30.0,
    http_get: Any = None,
) -> tuple[bytes, str]:
    aid = str(asset_id or "").strip()
    if not aid:
        raise AssetFetchError("missing asset_id")
    rec = brain_db.get_asset(aid)
    if rec is None or str(rec.get("status") or "").lower() == "deleted":
        raise AssetFetchError(f"找不到图片 Asset {aid}")
    typ = str(rec.get("type") or "").strip().lower()
    mime = str(rec.get("mime_type") or "").strip() or "image/jpeg"
    if typ and typ not in ("image", "photo") and not mime.startswith("image/"):
        raise AssetFetchError("image.ocr 只接受图片 Asset")
    storage = rec.get("storage") if isinstance(rec.get("storage"), dict) else {}
    backend = str(storage.get("backend") or "").strip().lower()
    if backend == "local_upload":
        key = str(storage.get("key") or storage.get("saved_as") or "").strip()
        if key and ".." not in key and not key.startswith("/"):
            path = _upload_assets_dir() / Path(key).name
            if path.is_file():
                return path.read_bytes(), mime
        raise AssetFetchError("local_upload file missing")
    getter = http_get or urllib.request.urlopen
    last = "no storage locator"
    for url in media_urls(storage):
        try:
            with getter(url, timeout=timeout_sec) as resp:
                data = resp.read()
            if data:
                return data, mime
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(e)
            continue
    raise AssetFetchError(f"无法读取 Asset 图片：{last}")
