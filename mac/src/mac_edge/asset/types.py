"""Asset Manager core types — see docs/asset-manager-design.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AssetRef:
    """Public reference passed in context / step_outputs."""

    asset_id: str
    type: str
    mime_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"asset_id": self.asset_id, "type": self.type}
        if self.mime_type:
            out["mime_type"] = self.mime_type
        return out

    @classmethod
    def from_dict(cls, raw: Any) -> AssetRef | None:
        if not isinstance(raw, dict):
            return None
        aid = str(raw.get("asset_id") or "").strip()
        if not aid:
            return None
        typ = str(raw.get("type") or "other").strip() or "other"
        mime = str(raw.get("mime_type") or "").strip() or None
        return cls(asset_id=aid, type=typ, mime_type=mime)


@dataclass(frozen=True)
class StorageLocator:
    backend: str
    key: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssetRecord:
    asset_id: str
    type: str
    status: str
    created_at_ms: int
    edge_id: str
    producer: str
    storage: StorageLocator
    mime_type: str | None = None
    expires_at_ms: int | None = None
    intent_id: str | None = None
    step_num: int | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalFileRepresentation:
    path: Path
    mime_type: str | None = None


@dataclass(frozen=True)
class HttpUrlRepresentation:
    url: str
    expires_at_ms: int | None = None


class AssetError(Exception):
    """Base for asset layer failures."""


class AssetNotFoundError(AssetError):
    pass


class AssetAccessDeniedError(AssetError):
    pass


class AssetAccessPendingError(AssetError):
    """Cross-edge / user confirm — step should wait, not fail."""


class AssetStorageError(AssetError):
    pass
