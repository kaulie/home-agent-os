"""Runtime Asset Manager — design: docs/asset-manager-design.md."""

from mac_edge.asset.id import new_asset_id
from mac_edge.asset.manager import AssetManager
from mac_edge.asset.sdk import CapAsset
from mac_edge.asset.types import (
    AssetAccessDeniedError,
    AssetAccessPendingError,
    AssetError,
    AssetNotFoundError,
    AssetRecord,
    AssetRef,
    AssetStorageError,
    HttpUrlRepresentation,
    LocalFileRepresentation,
    StorageLocator,
)

__all__ = [
    "AssetAccessDeniedError",
    "AssetAccessPendingError",
    "AssetError",
    "AssetManager",
    "AssetNotFoundError",
    "AssetRecord",
    "AssetRef",
    "AssetStorageError",
    "CapAsset",
    "HttpUrlRepresentation",
    "LocalFileRepresentation",
    "StorageLocator",
    "new_asset_id",
]
