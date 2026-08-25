"""Asset Manager unit tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from mac_edge.asset.manager import AssetManager
from mac_edge.asset.types import AssetNotFoundError, AssetRef


class AssetManagerTests(unittest.TestCase):
    def test_register_storage_locator_returns_ref(self) -> None:
        brain = MagicMock()
        brain.register_asset.return_value = {"ok": True, "asset_id": "asset_x"}
        mgr = AssetManager(brain=brain, edge_id="edge-a")
        ref = mgr.register_storage_locator(
            backend="img_server",
            key="photo.jpg",
            type="image",
            mime_type="image/jpeg",
            producer="camera.capture",
            intent_id="42",
            step_num=1,
        )
        self.assertTrue(ref.asset_id.startswith("asset_"))
        self.assertEqual(ref.type, "image")
        brain.register_asset.assert_called_once()
        body = brain.register_asset.call_args.args[0]
        self.assertEqual(body["intent_id"], "42")
        self.assertEqual(body["storage"]["key"], "photo.jpg")

    def test_resolve_http_url(self) -> None:
        brain = MagicMock()
        brain.fetch_asset.return_value = {
            "asset_id": "asset_x",
            "storage": {
                "backend": "img_server",
                "key": "a.jpg",
                "public_base": "http://192.168.3.65:8080",
            },
        }
        mgr = AssetManager(brain=brain, edge_id="edge-a")
        rep = mgr.resolve_for_capability(
            AssetRef(asset_id="asset_x", type="image"),
            intent_id="42",
            need="http_url",
        )
        self.assertEqual(rep.url, "http://192.168.3.65:8080/a.jpg")

    def test_resolve_local_upload_uses_brain_content_url(self) -> None:
        brain = MagicMock()
        brain.config.brain_base_url = "http://127.0.0.1:9527"
        brain.fetch_asset.return_value = {
            "asset_id": "asset_iphone",
            "storage": {
                "backend": "local_upload",
                "key": "8a3adf809f01_photo.jpg",
            },
        }
        mgr = AssetManager(brain=brain, edge_id="edge-mac")
        rep = mgr.resolve_for_capability(
            AssetRef(asset_id="asset_iphone", type="image"),
            intent_id="168",
            need="http_url",
        )
        self.assertEqual(
            rep.url,
            "http://192.168.3.73:9527/api/v1/assets/asset_iphone/content"
            "?intent_id=168&representation=original",
        )

    def test_resolve_missing_asset(self) -> None:
        brain = MagicMock()
        brain.fetch_asset.return_value = None
        mgr = AssetManager(brain=brain, edge_id="edge-a")
        with self.assertRaises(AssetNotFoundError):
            mgr.resolve_for_capability(
                AssetRef(asset_id="asset_missing", type="image"),
                intent_id="42",
                need="http_url",
            )


if __name__ == "__main__":
    unittest.main()
