"""Capability-facing Runtime SDK — Asset Manager session for one step.

Capabilities receive this as ``asset`` and call resolve/register themselves.
Executor must not secretly rewrite AssetRef ↔ photo_url.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mac_edge.asset.manager import AssetManager
from mac_edge.asset.types import AssetError, AssetRef


@dataclass(frozen=True)
class CapAsset:
    """Per-step Asset Manager handle (Runtime SDK surface for capabilities)."""

    manager: AssetManager
    intent_id: str
    step_num: int

    def parse_ref(self, raw: Any) -> AssetRef | None:
        if isinstance(raw, AssetRef):
            return raw
        if isinstance(raw, dict):
            return AssetRef.from_dict(raw)
        text = str(raw or "").strip()
        if not text.startswith("{"):
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return AssetRef.from_dict(parsed)

    def require_ref(self, params: dict[str, Any], key: str = "asset_ref") -> AssetRef:
        ref = self.parse_ref(params.get(key))
        if ref is None:
            raise AssetError(f"missing or invalid {key} (AssetRef required)")
        return ref

    def require_refs(self, params: dict[str, Any], key: str = "asset_refs") -> list[AssetRef]:
        raw = params.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise AssetError(f"missing {key} (AssetRef JSON array required)")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as e:
                raise AssetError(f"{key} must be AssetRef JSON array: {e}") from e
        else:
            parsed = raw
        if not isinstance(parsed, list) or not parsed:
            raise AssetError(f"{key} must be a non-empty AssetRef JSON array")
        refs: list[AssetRef] = []
        for i, item in enumerate(parsed):
            ref = self.parse_ref(item)
            if ref is None:
                raise AssetError(f"{key}[{i}] is not a valid AssetRef")
            refs.append(ref)
        return refs

    def http_url(self, ref: AssetRef) -> str:
        rep = self.manager.resolve_for_capability(
            ref,
            intent_id=self.intent_id,
            need="http_url",
        )
        return rep.url

    def materialize_file(self, ref: AssetRef) -> Path:
        """Local Path for this asset: edge_fs / local crop → direct, else download
        once (cached by asset_id). Capabilities read bytes from this path
        instead of re-fetching per atom."""
        return self.manager.materialize_file(ref, intent_id=self.intent_id)

    def register_local_file(
        self,
        path: str | Path,
        *,
        producer: str,
        mime_type: str = "image/jpeg",
        type: str = "image",
        metadata: dict[str, Any] | None = None,
    ) -> AssetRef:
        """Register a file already on this Edge. No img-server / cloud upload."""
        return self.manager.register_local_file(
            Path(path),
            type=type,
            mime_type=mime_type,
            producer=producer,
            intent_id=self.intent_id,
            step_num=self.step_num,
            metadata=metadata,
        )

    def register_img_server(
        self,
        *,
        key: str,
        public_base: str,
        producer: str,
        mime_type: str = "image/jpeg",
        type: str = "image",
        size_bytes: int | None = None,
        metadata: dict[str, Any] | None = None,
        cloud_public_base: str | None = None,
        cloud_key: str | None = None,
    ) -> AssetRef:
        return self.manager.register_storage_locator(
            backend="img_server",
            key=key,
            type=type,
            mime_type=mime_type,
            producer=producer,
            intent_id=self.intent_id,
            step_num=self.step_num,
            size_bytes=size_bytes,
            metadata=metadata,
            public_base=public_base.rstrip("/"),
            cloud_public_base=cloud_public_base,
            cloud_key=cloud_key,
        )

    def register_from_upload_url(
        self,
        *,
        photo_url: str,
        saved_as: str | None,
        producer: str,
        mime_type: str = "image/jpeg",
        cloud_public_base: str | None = None,
        cloud_saved_as: str | None = None,
    ) -> AssetRef:
        """Register blob already on img_server; returns AssetRef only (no URL identity)."""
        url = (photo_url or "").strip()
        saved = (saved_as or "").strip()
        if not url:
            raise AssetError(f"{producer}: missing upload url for asset registration")
        if not saved:
            path = urlparse(url).path.rstrip("/")
            saved = path.rsplit("/", 1)[-1] if path else ""
        if not saved:
            raise AssetError(f"{producer}: missing saved_as for asset registration")
        parsed = urlparse(url)
        public_base = f"{parsed.scheme}://{parsed.netloc}"
        return self.register_img_server(
            key=saved,
            public_base=public_base,
            producer=producer,
            mime_type=mime_type,
            cloud_public_base=cloud_public_base,
            cloud_key=cloud_saved_as,
        )

    def inventory(
        self,
        *,
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
        """Query Brain asset catalog via Brain HTTP only (no local DB / filesystem)."""
        return self.manager.inventory(
            intent_id=self.intent_id,
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

    def upload_to(self, ref: AssetRef, dest: str = "img_server") -> AssetRef:
        """Copy an existing Asset to the active Brain (dest stubs still fail)."""
        from mac_edge.asset.img_upload import require_implemented_dest

        require_implemented_dest(dest)
        path = self.manager.materialize_file(ref, intent_id=self.intent_id)
        return self.manager.upload_file(
            path,
            producer="asset.upload",
            intent_id=self.intent_id,
            mime_type=ref.mime_type or "image/jpeg",
            asset_type=ref.type or "image",
            filename=f"{ref.asset_id}.jpg",
        )

    def upload_local_file(
        self,
        path: str | Path,
        dest: str = "img_server",
        mime_type: str = "image/jpeg",
    ) -> AssetRef:
        """Upload a local jpeg to the active Brain's /api/v1/assets/upload."""
        from mac_edge.asset.img_upload import require_implemented_dest

        require_implemented_dest(dest)
        p = Path(path)
        return self.manager.upload_file(
            p,
            producer="asset.upload",
            intent_id=self.intent_id,
            mime_type=mime_type,
            asset_type="image",
            filename=p.name or "upload.jpg",
        )

    def upload_file(
        self,
        path: str | Path,
        *,
        producer: str,
        mime_type: str = "application/octet-stream",
        asset_type: str = "file",
        filename: str | None = None,
    ) -> AssetRef:
        """Upload any local file (not just image) to the active Brain's
        /api/v1/assets/upload and register it as an Asset of the given type.

        Unlike ``upload_local_file`` (hard-coded image/jpeg + type=image), this
        lets capabilities register document / pdf / audio outputs, e.g. the
        ``file.convert`` producer storing a generated PDF.
        """
        p = Path(path)
        return self.manager.upload_file(
            p,
            producer=producer,
            intent_id=self.intent_id,
            mime_type=mime_type,
            asset_type=asset_type,
            filename=filename or p.name,
        )
