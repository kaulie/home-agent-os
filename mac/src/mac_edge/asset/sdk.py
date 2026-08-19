"""Capability-facing Runtime SDK — Asset Manager session for one step.

Capabilities receive this as ``asset`` and call resolve/register themselves.
Executor must not secretly rewrite AssetRef ↔ photo_url.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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

    def require_ref(self, params: dict[str, Any], key: str = "image_ref") -> AssetRef:
        ref = self.parse_ref(params.get(key))
        if ref is None:
            raise AssetError(f"missing or invalid {key} (AssetRef required)")
        return ref

    def require_refs(self, params: dict[str, Any], key: str = "image_refs") -> list[AssetRef]:
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
        )

    def register_from_upload_url(
        self,
        *,
        photo_url: str,
        saved_as: str | None,
        producer: str,
        mime_type: str = "image/jpeg",
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
        )
