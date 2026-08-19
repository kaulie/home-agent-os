"""Edge Asset Manager — canonical catalog in Brain SQLite."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from mac_edge.asset.backends.img_server import http_url_from_storage
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
    ) -> AssetRef:
        aid = new_asset_id()
        storage: dict[str, Any] = {
            "backend": backend,
            "key": key,
            "edge_id": self._edge_id,
        }
        if public_base:
            storage["public_base"] = public_base.rstrip("/")
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

    @staticmethod
    def parse_ref(raw: Any) -> AssetRef | None:
        if isinstance(raw, AssetRef):
            return raw
        return AssetRef.from_dict(raw)
