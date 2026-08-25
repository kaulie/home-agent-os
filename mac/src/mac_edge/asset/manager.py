"""Edge Asset Manager — canonical catalog in Brain SQLite."""

from __future__ import annotations

import logging
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal

from mac_edge.asset.backends.img_server import (
    brain_content_http_url,
    http_url_from_storage,
)
from mac_edge.asset.id import new_asset_id
from mac_edge.asset.types import (
    AssetAccessDeniedError,
    AssetNotFoundError,
    AssetRef,
    AssetStorageError,
    HttpUrlRepresentation,
    LocalFileRepresentation,
    StorageLocator,
)
from mac_edge.brain_client import BrainClient, BrainError

log = logging.getLogger("mac_edge.asset")


class AssetManager:
    """Register assets in Brain and resolve representations for capabilities."""

    def __init__(self, *, brain: BrainClient, edge_id: str) -> None:
        self._brain = brain
        self._edge_id = edge_id.strip()

    def register_storage_locator(
        self,
        *,
        backend: str,
        key: str,
        type: str,
        mime_type: str | None,
        producer: str,
        intent_id: str,
        step_num: int | None = None,
        size_bytes: int | None = None,
        metadata: dict[str, Any] | None = None,
        public_base: str | None = None,
        cloud_public_base: str | None = None,
        cloud_key: str | None = None,
    ) -> AssetRef:
        aid = new_asset_id()
        storage: dict[str, Any] = {
            "backend": backend,
            "key": key,
            "edge_id": self._edge_id,
        }
        if public_base:
            storage["public_base"] = public_base.rstrip("/")
        # Cloud mirror for Intent Source / Brain content proxy (Cast still uses LAN).
        cbase = (cloud_public_base or "").strip().rstrip("/")
        ckey = (cloud_key or "").strip()
        if cbase:
            storage["cloud_public_base"] = cbase
        if ckey:
            storage["cloud_key"] = ckey
        body: dict[str, Any] = {
            "asset_id": aid,
            "type": type,
            "mime_type": mime_type,
            "size": size_bytes,
            "status": "available",
            "creator": producer,
            "producer": producer,
            "intent_id": str(intent_id),
            "execution_id": str(intent_id),
            "metadata": metadata or {},
            "storage": storage,
            "edge_id": self._edge_id,
        }
        if step_num is not None:
            body["step"] = int(step_num)
        self._brain.register_asset(body)
        log.info(
            "asset registered id=%s type=%s intent=%s producer=%s",
            aid,
            type,
            intent_id,
            producer,
        )
        return AssetRef(asset_id=aid, type=type, mime_type=mime_type)

    def register_local_file(
        self,
        path: Path,
        *,
        type: str,
        mime_type: str | None,
        producer: str,
        intent_id: str,
        step_num: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AssetRef:
        p = path.expanduser().resolve()
        if not p.is_file():
            raise AssetStorageError(f"local file missing: {p}")
        size = p.stat().st_size
        return self.register_storage_locator(
            backend="local",
            key=str(p),
            type=type,
            mime_type=mime_type,
            producer=producer,
            intent_id=intent_id,
            step_num=step_num,
            size_bytes=size,
            metadata=metadata,
        )

    def resolve_for_capability(
        self,
        ref: AssetRef,
        *,
        intent_id: str,
        need: Literal["http_url", "local_path"],
    ) -> HttpUrlRepresentation | LocalFileRepresentation:
        iid = str(intent_id).strip()
        record = self._brain.fetch_asset(
            ref.asset_id,
            edge_id=self._edge_id,
            intent_id=iid,
        )
        if record is None:
            raise AssetNotFoundError(ref.asset_id)
        storage = record.get("storage")
        if not isinstance(storage, dict):
            raise AssetStorageError(f"asset {ref.asset_id} has no storage locator")
        if need == "http_url":
            backend = str(storage.get("backend") or storage.get("provider") or "").strip()
            if backend == "local_upload":
                brain_base = str(
                    getattr(getattr(self._brain, "config", None), "brain_base_url", "")
                    or ""
                ).strip()
                if not brain_base:
                    raise AssetStorageError(
                        f"asset {ref.asset_id} is local_upload but Brain URL is missing"
                    )
                return HttpUrlRepresentation(
                    url=brain_content_http_url(brain_base, ref.asset_id, iid),
                    expires_at_ms=None,
                )
            return http_url_from_storage(storage)
        if need == "local_path":
            backend = str(storage.get("backend") or "").strip()
            key = str(storage.get("key") or "").strip()
            if backend == "local" and key:
                p = Path(key)
                if p.is_file():
                    return LocalFileRepresentation(path=p, mime_type=ref.mime_type)
            raise AssetStorageError(
                f"asset {ref.asset_id} has no local_path representation"
            )
        raise AssetStorageError(f"unknown representation need: {need}")

    def materialize_file(self, ref: AssetRef, *, intent_id: str) -> Path:
        """Local file for upload: edge_fs path, else download via http_url."""
        try:
            local = self.resolve_for_capability(
                ref, intent_id=intent_id, need="local_path"
            )
            if isinstance(local, LocalFileRepresentation) and local.path.is_file():
                return local.path
        except (AssetStorageError, AssetNotFoundError):
            pass
        http = self.resolve_for_capability(ref, intent_id=intent_id, need="http_url")
        url = str(http.url or "").strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            raise AssetStorageError(f"asset {ref.asset_id} has no fetchable representation")
        suffix = Path(url.split("?", 1)[0]).suffix or ".bin"
        root = Path(os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
        if root:
            staging = Path(root) / "upload"
        else:
            staging = Path(tempfile.gettempdir()) / "mac-edge-asset-upload"
        staging.mkdir(parents=True, exist_ok=True)
        dest = staging / f"{ref.asset_id}{suffix}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                dest.write_bytes(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise AssetStorageError(
                f"asset {ref.asset_id} download failed: {e}"
            ) from e
        if not dest.is_file() or dest.stat().st_size <= 0:
            raise AssetStorageError(f"asset {ref.asset_id} downloaded empty file")
        return dest

    def inventory(
        self,
        *,
        intent_id: str,
        asset_type: str | None = None,
        producer_capability: str | None = None,
        day: str | None = None,
        timezone: str | None = None,
        since: str | float | None = None,
        until: str | float | None = None,
        limit: int | None = None,
        offset: int | None = None,
        newest_first: bool = True,
    ) -> dict[str, Any]:
        """List assets via Brain GET /api/v1/assets only (never open Brain SQLite here)."""
        return self._brain.list_assets(
            edge_id=self._edge_id,
            intent_id=str(intent_id).strip(),
            asset_type=asset_type,
            producer_capability=producer_capability,
            day=day,
            timezone=timezone,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
            newest_first=newest_first,
        )

    @staticmethod
    def parse_ref(raw: Any) -> AssetRef | None:
        if isinstance(raw, AssetRef):
            return raw
        return AssetRef.from_dict(raw)
