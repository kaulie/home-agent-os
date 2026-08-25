"""img_server locator: prefer original key, fallback to preview."""

from __future__ import annotations

import unittest

from mac_edge.asset.backends.img_server import (
    brain_content_http_url,
    http_url_from_storage,
    lan_facing_brain_base,
)
from mac_edge.asset.types import AssetStorageError


class ImgServerResolveTests(unittest.TestCase):
    def test_prefers_original_key(self) -> None:
        rep = http_url_from_storage(
            {
                "backend": "img_server",
                "key": "orig.jpg",
                "preview_key": "prev.jpg",
                "public_base": "http://192.168.3.65:8080",
            }
        )
        self.assertEqual(rep.url, "http://192.168.3.65:8080/orig.jpg")

    def test_fallback_preview_when_original_pending(self) -> None:
        rep = http_url_from_storage(
            {
                "backend": "img_server",
                "preview_key": "56a6b3fa_preview.JPG",
                "cloud_preview_key": "56a6b3fa_preview.JPG",
                "public_base": "http://115.190.153.53:8080",
                "cloud_public_base": "http://115.190.153.53:8080",
            }
        )
        self.assertEqual(
            rep.url, "http://115.190.153.53:8080/56a6b3fa_preview.JPG"
        )

    def test_cloud_key_when_lan_key_absent(self) -> None:
        rep = http_url_from_storage(
            {
                "backend": "img_server",
                "cloud_key": "cloud_orig.jpg",
                "cloud_preview_key": "cloud_prev.jpg",
                "cloud_public_base": "http://115.190.153.53:8080",
            }
        )
        self.assertEqual(rep.url, "http://115.190.153.53:8080/cloud_orig.jpg")

    def test_missing_all_keys_fails(self) -> None:
        with self.assertRaises(AssetStorageError) as ctx:
            http_url_from_storage({"backend": "img_server", "public_base": "http://x"})
        self.assertIn("missing key", str(ctx.exception))

    def test_lan_facing_brain_rewrites_loopback(self) -> None:
        self.assertEqual(
            lan_facing_brain_base("http://127.0.0.1:9527"),
            "http://192.168.3.73:9527",
        )
        self.assertEqual(
            lan_facing_brain_base("http://192.168.3.73:9527"),
            "http://192.168.3.73:9527",
        )

    def test_brain_content_http_url(self) -> None:
        url = brain_content_http_url(
            "http://127.0.0.1:9527",
            "asset_4747c813a26f8ba5d1a99a28",
            "168",
        )
        self.assertEqual(
            url,
            "http://192.168.3.73:9527/api/v1/assets/"
            "asset_4747c813a26f8ba5d1a99a28/content"
            "?intent_id=168&representation=original",
        )


if __name__ == "__main__":
    unittest.main()
