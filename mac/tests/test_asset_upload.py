"""asset.upload capability — dest backends, stubs, missing asset_ref."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.asset.img_upload import (
    DEFAULT_LAN_PUBLIC_BASE,
    DEFAULT_LAN_UPLOAD_URL,
    ImgUploadError,
    display_upload_dest,
    normalize_upload_dest,
    require_implemented_dest,
    upload_endpoints,
)
from mac_edge.asset.types import AssetError, AssetRef
from mac_edge.plugins.asset_upload import AssetUploadError, upload_from_params


class DestRegistryTests(unittest.TestCase):
    def test_aliases(self) -> None:
        self.assertEqual(normalize_upload_dest(None), "lan")
        self.assertEqual(normalize_upload_dest("img_server"), "lan")
        self.assertEqual(normalize_upload_dest("local"), "lan")
        self.assertEqual(normalize_upload_dest("cloud"), "cloud")
        self.assertEqual(normalize_upload_dest("gdrive"), "gdrive")
        self.assertEqual(normalize_upload_dest("dropbox"), "dropbox")
        self.assertEqual(display_upload_dest("lan"), "img_server")
        self.assertEqual(display_upload_dest("img_server"), "img_server")

    def test_default_lan_is_local_img_server(self) -> None:
        self.assertEqual(DEFAULT_LAN_UPLOAD_URL, "http://127.0.0.1:8080/api/v1/photos/upload")
        self.assertEqual(DEFAULT_LAN_PUBLIC_BASE, "http://192.168.3.73:8080")
        self.assertNotIn("192.168.3.65", DEFAULT_LAN_UPLOAD_URL)
        self.assertNotIn("192.168.3.65", DEFAULT_LAN_PUBLIC_BASE)
        with patch.dict(
            os.environ,
            {
                "MAC_EDGE_LAN_PHOTO_UPLOAD_URL": "",
                "MAC_EDGE_LAN_PHOTO_PUBLIC_BASE": "",
            },
            clear=False,
        ):
            upload, public, probe = upload_endpoints("lan")
        self.assertEqual(upload, DEFAULT_LAN_UPLOAD_URL)
        self.assertEqual(public, DEFAULT_LAN_PUBLIC_BASE)
        self.assertTrue(probe.startswith("http://127.0.0.1:8080/"))

    def test_gdrive_dropbox_fail(self) -> None:
        with self.assertRaises(ImgUploadError) as ctx:
            require_implemented_dest("gdrive")
        self.assertIn("not implemented", str(ctx.exception))
        with self.assertRaises(ImgUploadError) as ctx:
            require_implemented_dest("dropbox")
        self.assertIn("not implemented", str(ctx.exception))


class AssetUploadPluginTests(unittest.TestCase):
    def test_missing_asset_ref(self) -> None:
        import tempfile

        asset = MagicMock()
        asset.parse_ref.return_value = None
        asset.require_ref.side_effect = AssetError("missing or invalid asset_ref (AssetRef required)")
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"MAC_EDGE_DATA_DIR": td}):
            with self.assertRaises(AssetUploadError) as ctx:
                upload_from_params({}, asset=asset)
        msg = str(ctx.exception)
        self.assertTrue("capture" in msg.lower() or "asset_ref" in msg)
        asset.upload_to.assert_not_called()

    def test_uploads_inbox_capture(self) -> None:
        import tempfile

        from mac_edge.capture import store as capture_store

        dst = AssetRef(asset_id="asset_dst", type="image", mime_type="image/jpeg")
        asset = MagicMock()
        asset.parse_ref.return_value = None
        asset.upload_local_file.return_value = dst
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"MAC_EDGE_DATA_DIR": td}):
            cref = capture_store.put(b"jpeg-bytes", original_name="a.jpg")
            msg, out = upload_from_params(
                {"capture_ref": cref, "dest": "img_server"},
                asset=asset,
            )
        self.assertEqual(out["asset_ref"]["asset_id"], "asset_dst")
        self.assertEqual(out["dest"], "img_server")
        asset.upload_local_file.assert_called_once()
        asset.upload_to.assert_not_called()

    def test_uploads_via_capasset(self) -> None:
        asset = MagicMock()
        src = AssetRef(asset_id="asset_src", type="image", mime_type="image/jpeg")
        dst = AssetRef(asset_id="asset_dst", type="image", mime_type="image/jpeg")
        asset.require_ref.return_value = src
        asset.upload_to.return_value = dst
        msg, out = upload_from_params(
            {"asset_ref": src.to_dict(), "dest": "img_server"},
            asset=asset,
        )
        self.assertIn("img_server", msg)
        self.assertEqual(out["dest"], "img_server")
        self.assertEqual(out["asset_ref"]["asset_id"], "asset_dst")
        asset.upload_to.assert_called_once()
        self.assertEqual(asset.upload_to.call_args.kwargs["dest"], "lan")

    def test_stub_dest_surfaces_error(self) -> None:
        asset = MagicMock()
        asset.require_ref.return_value = AssetRef(asset_id="a", type="image")
        asset.upload_to.side_effect = ImgUploadError(
            "dest=gdrive is not implemented yet (Google Drive is a plugin slot only)"
        )
        with self.assertRaises(AssetUploadError) as ctx:
            upload_from_params({"asset_ref": {"asset_id": "a", "type": "image"}, "dest": "gdrive"}, asset=asset)
        self.assertIn("gdrive", str(ctx.exception))
        self.assertIn("not implemented", str(ctx.exception))


class CapAssetUploadToTests(unittest.TestCase):
    def test_upload_to_posts_to_brain_assets_upload(self) -> None:
        from mac_edge.asset.sdk import CapAsset

        manager = MagicMock()
        manager.materialize_file.return_value = Path("/tmp/a.jpg")
        new_ref = AssetRef(asset_id="asset_new", type="image", mime_type="image/jpeg")
        manager.upload_file.return_value = new_ref
        cap = CapAsset(manager=manager, intent_id="1", step_num=2)
        out = cap.upload_to(
            AssetRef(asset_id="asset_old", type="image", mime_type="image/jpeg"),
            dest="img_server",
        )
        self.assertEqual(out.asset_id, "asset_new")
        manager.materialize_file.assert_called_once()
        manager.upload_file.assert_called_once()
        kwargs = manager.upload_file.call_args.kwargs
        self.assertEqual(kwargs["producer"], "asset.upload")
        self.assertEqual(kwargs["intent_id"], "1")
        manager.register_storage_locator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
