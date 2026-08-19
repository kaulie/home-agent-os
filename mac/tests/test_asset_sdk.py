"""CapAsset Runtime SDK tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from mac_edge.asset.sdk import CapAsset
from mac_edge.asset.types import AssetError, AssetRef, HttpUrlRepresentation


def _cap(mgr: MagicMock | None = None) -> CapAsset:
    return CapAsset(manager=mgr or MagicMock(), intent_id="42", step_num=1)


class CapAssetTests(unittest.TestCase):
    def test_require_ref_and_http_url(self) -> None:
        mgr = MagicMock()
        mgr.resolve_for_capability.return_value = HttpUrlRepresentation(
            url="http://192.168.3.65:8080/a.jpg"
        )
        asset = _cap(mgr)
        ref = asset.require_ref(
            {"image_ref": json.dumps({"asset_id": "asset_x", "type": "image"})}
        )
        self.assertEqual(ref.asset_id, "asset_x")
        self.assertEqual(asset.http_url(ref), "http://192.168.3.65:8080/a.jpg")

    def test_require_refs_array(self) -> None:
        asset = _cap()
        refs = asset.require_refs(
            {
                "image_refs": json.dumps(
                    [
                        {"asset_id": "a1", "type": "image"},
                        {"asset_id": "a2", "type": "image"},
                    ]
                )
            }
        )
        self.assertEqual([r.asset_id for r in refs], ["a1", "a2"])

    def test_missing_image_ref_fails(self) -> None:
        asset = _cap()
        with self.assertRaises(AssetError):
            asset.require_ref({"query": "hi"})

    def test_register_from_upload_url(self) -> None:
        mgr = MagicMock()
        mgr.register_storage_locator.return_value = AssetRef(
            asset_id="asset_new", type="image", mime_type="image/jpeg"
        )
        asset = _cap(mgr)
        ref = asset.register_from_upload_url(
            photo_url="http://192.168.3.65:8080/foo.jpg",
            saved_as="foo.jpg",
            producer="camera.capture",
        )
        self.assertEqual(ref.asset_id, "asset_new")
        kwargs = mgr.register_storage_locator.call_args.kwargs
        self.assertEqual(kwargs["key"], "foo.jpg")
        self.assertEqual(kwargs["producer"], "camera.capture")


if __name__ == "__main__":
    unittest.main()
