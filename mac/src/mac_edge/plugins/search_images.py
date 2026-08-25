"""Mac Edge capability: search.images — retrieve existing web photos.

Independent of query.content (AI 文生图). This step only sees its own params.
Providers return hits; this plugin downloads, uploads, and registers AssetRefs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from mac_edge.asset.img_upload import (
    ImgUploadError,
    normalize_upload_dest,
    upload_image_bytes,
)
from mac_edge.asset.sdk import CapAsset
from mac_edge.asset.types import AssetError, AssetRef
from mac_edge.plugins.image_search_providers import (
    ImageSearchHit,
    ImageSearchProvider,
    ImageSearchProviderError,
    get_provider,
    resolve_provider_name,
)

log = logging.getLogger("mac_edge.search_images")

DEFAULT_COUNT = 4
MAX_COUNT = 8
CACHE_TTL_SEC = 3600.0
DOWNLOAD_TIMEOUT_SEC = 15.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "HomeAgent/search.images"
)
SIZE_VALUES = frozenset({"small", "medium", "large", "wallpaper"})
FRESHNESS_VALUES = frozenset({"day", "week", "month"})
PROVIDER_VALUES = frozenset({"bing", "openverse", "azure_bing", "azure", "ov"})

_mem_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_mem_lock = threading.Lock()


class SearchImagesError(Exception):
    pass


def reset_cache_for_tests() -> None:
    with _mem_lock:
        _mem_cache.clear()


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _data_dir() -> Path:
    root = Path(__file__).resolve().parents[3]
    data = Path(_env("MAC_EDGE_DATA_DIR") or str(root / "data"))
    out = data / "search_images"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _as_count(raw: Any) -> int:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return DEFAULT_COUNT
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError) as e:
        raise SearchImagesError(f"count 必须是 1–{MAX_COUNT} 的整数，收到 {raw!r}") from e
    if n < 1 or n > MAX_COUNT:
        raise SearchImagesError(f"count 必须是 1–{MAX_COUNT}，收到 {n}")
    return n


def _optional_enum(raw: Any, allowed: frozenset[str], name: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    key = text.lower()
    if key not in allowed:
        raise SearchImagesError(
            f"{name} 无效（{text}）；可选：{', '.join(sorted(allowed))}"
        )
    if name == "provider":
        return key
    return key[:1].upper() + key[1:]


def _cache_key(
    provider: str, query: str, count: int, size: str, freshness: str
) -> str:
    blob = "|".join(
        [provider, query.lower(), str(count), size.lower(), freshness.lower()]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load_cache(
    key: str, cache_dir: Path, now: float
) -> list[ImageSearchHit] | None:
    with _mem_lock:
        hit = _mem_cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SEC:
            return [h for h in (ImageSearchHit.from_dict(x) for x in hit[1]) if h]
    path = cache_dir / f"{key}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ts = float(payload.get("ts") or 0)
    rows = payload.get("hits")
    if not isinstance(rows, list) or now - ts >= CACHE_TTL_SEC:
        return None
    hits = [h for h in (ImageSearchHit.from_dict(x) for x in rows) if h]
    with _mem_lock:
        _mem_cache[key] = (ts, [h.to_dict() for h in hits])
    return hits


def _store_cache(
    key: str, hits: list[ImageSearchHit], cache_dir: Path, now: float
) -> None:
    rows = [h.to_dict() for h in hits]
    with _mem_lock:
        _mem_cache[key] = (now, rows)
    try:
        (cache_dir / f"{key}.json").write_text(
            json.dumps({"ts": now, "hits": rows}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("search.images cache write failed: %s", e)


def _download_bytes(url: str, *, timeout_sec: float) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = resp.read()
            content_type = str(resp.headers.get("Content-Type") or "")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SearchImagesError(f"下载图片失败：{e}") from e
    if not data or len(data) < 32:
        raise SearchImagesError("下载的图片为空")
    if content_type.lower().startswith("text/"):
        raise SearchImagesError("下载结果不是图片")
    return data


def _mime_of(data: bytes, hint: str = "") -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    h = hint.lower()
    if "png" in h:
        return "image/png"
    if "gif" in h:
        return "image/gif"
    if "webp" in h:
        return "image/webp"
    return "image/jpeg"


def _ext_for(mime: str) -> str:
    return {
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
    }.get(mime, "jpg")


def _upload_photo(
    image_bytes: bytes,
    *,
    filename: str,
    upload_dest: str,
) -> dict[str, str]:
    dest = normalize_upload_dest(upload_dest)
    try:
        result = upload_image_bytes(
            image_bytes,
            filename=filename,
            preferred_dest=dest,
            allow_cloud_fallback=True,
            staging_dir=_data_dir(),
        )
    except ImgUploadError as e:
        raise SearchImagesError(str(e)) from e
    out = {"photo_url": result.photo_url, "saved_as": result.saved_as or ""}
    if result.cloud_public_base:
        out["cloud_public_base"] = result.cloud_public_base
    if result.cloud_saved_as:
        out["cloud_saved_as"] = result.cloud_saved_as
    return out


def search_images(
    *,
    query: str,
    count: int = DEFAULT_COUNT,
    size: str = "",
    freshness: str = "",
    upload_dest: str = "lan",
    timeout_sec: float = 30.0,
    asset: CapAsset,
    provider_name: str | None = None,
    provider: ImageSearchProvider | None = None,
    download: Callable[..., bytes] | None = None,
    upload: Callable[..., dict[str, str]] | None = None,
    now: float | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        raise SearchImagesError("缺少必填 query（搜索关键词）")
    if not isinstance(asset, CapAsset):
        raise SearchImagesError("search.images 需要 CapAsset（Runtime SDK）")

    pname = resolve_provider_name(provider_name)
    try:
        prov = provider if provider is not None else get_provider(pname)
    except ImageSearchProviderError as e:
        raise SearchImagesError(str(e)) from e

    fetch = download or _download_bytes
    put = upload or _upload_photo
    ts = time.time() if now is None else float(now)
    cache_root = cache_dir or _data_dir()
    cache_root.mkdir(parents=True, exist_ok=True)
    key = _cache_key(pname, q, count, size, freshness)

    hits = _load_cache(key, cache_root, ts)
    cache_hit = hits is not None
    if hits is None:
        try:
            hits = prov.search(
                query=q,
                count=count,
                size=size,
                freshness=freshness,
                timeout_sec=timeout_sec,
            )
        except ImageSearchProviderError as e:
            raise SearchImagesError(str(e)) from e
        _store_cache(key, hits, cache_root, ts)

    if not hits:
        raise SearchImagesError(f"没有找到「{q}」的实拍图")

    refs: list[AssetRef] = []
    sources: list[dict[str, str]] = []
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for i, hit in enumerate(hits):
        if len(refs) >= count:
            break
        urls = [u for u in (hit.content_url, hit.thumbnail_url) if u]
        image_bytes: bytes | None = None
        last_err = ""
        for url in urls:
            try:
                image_bytes = fetch(
                    url, timeout_sec=min(DOWNLOAD_TIMEOUT_SEC, timeout_sec)
                )
                break
            except SearchImagesError as e:
                last_err = str(e)
                continue
        if not image_bytes:
            log.warning("search.images skip hit %s: %s", i, last_err)
            continue
        mime = _mime_of(image_bytes, hit.encoding)
        filename = f"{stamp}_search_{len(refs)+1}.{_ext_for(mime)}"
        try:
            uploaded = put(
                image_bytes,
                filename=filename,
                upload_dest=upload_dest,
            )
            ref = asset.register_from_upload_url(
                photo_url=str(uploaded.get("photo_url") or ""),
                saved_as=str(uploaded.get("saved_as") or "") or None,
                producer="search.images",
                mime_type=mime,
                cloud_public_base=str(uploaded.get("cloud_public_base") or "") or None,
                cloud_saved_as=str(uploaded.get("cloud_saved_as") or "") or None,
            )
        except (SearchImagesError, AssetError, ImgUploadError) as e:
            log.warning("search.images register skip hit %s: %s", i, e)
            continue
        refs.append(ref)
        src = {"name": hit.name, "host_page": hit.host_page}
        if hit.license:
            src["license"] = hit.license
        if hit.license_url:
            src["license_url"] = hit.license_url
        sources.append(src)

    if not refs:
        raise SearchImagesError(f"搜到了「{q}」的候选，但图片下载或登记全部失败")

    log.info(
        "search.images ok provider=%s query=%r hits=%s cache=%s",
        getattr(prov, "name", pname),
        q[:80],
        len(refs),
        cache_hit,
    )
    return {
        "asset_refs": [r.to_dict() for r in refs],
        "query_used": q,
        "hit_count": str(len(refs)),
        "provider": getattr(prov, "name", pname),
        "sources": json.dumps(sources, ensure_ascii=False),
    }


def search_from_params(
    params: dict[str, Any],
    *,
    asset: CapAsset,
    timeout_sec: float = 30.0,
    **kwargs: Any,
) -> tuple[str, dict[str, Any]]:
    raw = params if isinstance(params, dict) else {}
    q = str(raw.get("query") or "").strip()
    count = _as_count(raw.get("count"))
    size = _optional_enum(raw.get("size"), SIZE_VALUES, "size")
    freshness = _optional_enum(raw.get("freshness"), FRESHNESS_VALUES, "freshness")
    dest = str(raw.get("upload_dest") or "lan").strip() or "lan"
    provider_name = _optional_enum(raw.get("provider"), PROVIDER_VALUES, "provider")
    outputs = search_images(
        query=q,
        count=count,
        size=size,
        freshness=freshness,
        upload_dest=dest,
        timeout_sec=timeout_sec,
        asset=asset,
        provider_name=provider_name or None,
        **kwargs,
    )
    n = outputs.get("hit_count") or "0"
    used = outputs.get("provider") or ""
    return f"search.images {used} {n} 张「{outputs.get('query_used') or q}」", outputs
