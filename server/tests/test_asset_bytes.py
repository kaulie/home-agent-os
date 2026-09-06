"""asset_bytes media_urls: fresh local img-server resolution, not stored base."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from sdk.asset_bytes import _img_server_local_base, media_urls  # noqa: E402


def _clear_upload_env() -> None:
    os.environ.pop("BRAIN_IMG_UPLOAD_URL", None)
    os.environ.pop("PHOTO_UPLOAD_URL", None)


class AssetBytesMediaUrlsTests(unittest.TestCase):
    def test_local_base_defaults_to_loopback(self) -> None:
        _clear_upload_env()
        self.assertEqual(_img_server_local_base(), "http://127.0.0.1:8080")

    def test_local_base_honors_upload_url_override(self) -> None:
        prev = os.environ.get("BRAIN_IMG_UPLOAD_URL")
        os.environ["BRAIN_IMG_UPLOAD_URL"] = "http://127.0.0.1:18080/api/v1/photos/upload"
        try:
            self.assertEqual(_img_server_local_base(), "http://127.0.0.1:18080")
        finally:
            if prev is None:
                os.environ.pop("BRAIN_IMG_UPLOAD_URL", None)
            else:
                os.environ["BRAIN_IMG_UPLOAD_URL"] = prev

    def test_media_urls_local_first_then_stored_legacy(self) -> None:
        _clear_upload_env()
        # A stale stored public_base must never be tried before the co-located
        # (loopback) img-server, so materialization stays DHCP-immune.
        urls = media_urls(
            {
                "backend": "img_server",
                "key": "a.png",
                "public_base": "http://192.168.3.73:8080",
            }
        )
        self.assertEqual(urls[0], "http://127.0.0.1:8080/a.png")
        self.assertIn("http://192.168.3.73:8080/a.png", urls)

    def test_media_urls_cloud_mirror_first(self) -> None:
        _clear_upload_env()
        urls = media_urls(
            {
                "backend": "img_server",
                "key": "a.png",
                "cloud_public_base": "http://115.190.153.53:8080",
                "cloud_key": "a.png",
                "public_base": "http://192.168.3.73:8080",
            }
        )
        self.assertEqual(urls[0], "http://115.190.153.53:8080/a.png")
        self.assertIn("http://127.0.0.1:8080/a.png", urls)

    def test_media_urls_percent_encodes_non_ascii_keys(self) -> None:
        """id=639: Chinese PDF filenames must be percent-encoded for urllib."""
        _clear_upload_env()
        key = "f1103a10_当前Agent编排平台现状分析和创业空间.pdf"
        urls = media_urls({"backend": "img_server", "key": key})
        self.assertTrue(urls)
        self.assertIn("%E5%BD%93%E5%89%8D", urls[0])
        self.assertNotIn("当前", urls[0])
        self.assertTrue(urls[0].startswith("http://127.0.0.1:8080/f1103a10_"))


if __name__ == "__main__":
    unittest.main()
