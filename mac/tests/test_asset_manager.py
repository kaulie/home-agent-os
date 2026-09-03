"""Asset Manager unit tests."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

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
        # Stored private-LAN public_base may be stale (DHCP); resolve the current
        # LAN base at use time.
        with patch.dict(
            os.environ,
            {"MAC_EDGE_LAN_PUBLIC_BASE": "http://192.168.3.96:8080"},
            clear=False,
        ):
            rep = mgr.resolve_for_capability(
                AssetRef(asset_id="asset_x", type="image"),
                intent_id="42",
                need="http_url",
            )
        self.assertEqual(rep.url, "http://192.168.3.96:8080/a.jpg")

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
        with patch.dict(
            os.environ,
            {"MAC_EDGE_LAN_PUBLIC_BASE": "http://192.168.3.96:8080"},
            clear=False,
        ):
            rep = mgr.resolve_for_capability(
                AssetRef(asset_id="asset_iphone", type="image"),
                intent_id="168",
                need="http_url",
            )
        self.assertEqual(
            rep.url,
            "http://192.168.3.96:9527/api/v1/assets/asset_iphone/content"
            "?intent_id=168&representation=original",
        )

    def test_upload_file_posts_to_brain(self) -> None:
        import tempfile
        from pathlib import Path

        brain = MagicMock()
        brain.upload_asset.return_value = {
            "ok": True,
            "asset_id": "asset_up",
            "asset_ref": {"asset_id": "asset_up", "type": "image", "mime_type": "image/jpeg"},
        }
        mgr = AssetManager(brain=brain, edge_id="edge-a")
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(b"jpeg-bytes")
            f.flush()
            ref = mgr.upload_file(
                Path(f.name),
                producer="asset.upload",
                intent_id="71",
            )
        self.assertEqual(ref.asset_id, "asset_up")
        brain.upload_asset.assert_called_once()
        kwargs = brain.upload_asset.call_args.kwargs
        self.assertEqual(kwargs["upload_intent"], "asset.upload")
        self.assertEqual(kwargs["intent_id"], "71")
        self.assertEqual(kwargs["edge_id"], "edge-a")
        self.assertEqual(kwargs["file_bytes"], b"jpeg-bytes")

    def test_upload_file_empty_fails(self) -> None:
        import tempfile
        from pathlib import Path

        from mac_edge.asset.types import AssetStorageError

        mgr = AssetManager(brain=MagicMock(), edge_id="edge-a")
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.flush()
            with self.assertRaises(AssetStorageError):
                mgr.upload_file(Path(f.name), producer="asset.upload", intent_id="1")

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

    def test_materialize_file_caches_by_asset_id_no_redownload(self) -> None:
        """materialize_file downloads a remote asset once and caches the local
        path by asset_id; a second call for the same ref returns the cached file
        without re-downloading. This is what stops later composite atoms from
        re-fetching the full photo per atom."""
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        brain = MagicMock()
        brain.config.brain_base_url = ""
        brain.fetch_asset.return_value = {
            "asset_id": "asset_remote",
            "storage": {
                "backend": "img_server",
                "key": "p.jpg",
                "public_base": "http://photos.local:8080",
            },
        }
        mgr = AssetManager(brain=brain, edge_id="edge-a")
        with tempfile.TemporaryDirectory() as td:
            with patch.dict("os.environ", {"MAC_EDGE_DATA_DIR": td}):
                # first call downloads
                with patch(
                    "mac_edge.asset.manager.urllib.request.urlopen"
                ) as urlopen:
                    resp = urlopen.return_value
                    resp.__enter__.return_value.read.return_value = b"\xff\xd8jpeg"
                    p1 = mgr.materialize_file(
                        AssetRef(asset_id="asset_remote", type="image"),
                        intent_id="42",
                    )
                self.assertTrue(p1.is_file())
                self.assertEqual(p1.read_bytes(), b"\xff\xd8jpeg")
                # second call must NOT download again (no urlopen patch → would
                # raise if it tried network); returns same cached path
                with patch(
                    "mac_edge.asset.manager.urllib.request.urlopen",
                    side_effect=AssertionError("should not re-download"),
                ):
                    p2 = mgr.materialize_file(
                        AssetRef(asset_id="asset_remote", type="image"),
                        intent_id="42",
                    )
                self.assertEqual(p2, p1)

    def test_materialize_file_local_path_no_download(self) -> None:
        """A locally-registered crop (backend=local) resolves to its local path
        directly with no download — the path ocr/rank atoms read."""
        import tempfile
        from pathlib import Path

        brain = MagicMock()
        brain.fetch_asset.return_value = {
            "asset_id": "asset_crop",
            "storage": {"backend": "local", "key": ""},
        }
        mgr = AssetManager(brain=brain, edge_id="edge-a")
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"crop-bytes")
            name = f.name
        try:
            brain.fetch_asset.return_value["storage"]["key"] = name
            p = mgr.materialize_file(
                AssetRef(asset_id="asset_crop", type="image"),
                intent_id="42",
            )
            self.assertEqual(p, Path(name))
            self.assertEqual(p.read_bytes(), b"crop-bytes")
        finally:
            Path(name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
