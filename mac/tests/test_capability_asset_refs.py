"""Advertised capability I/O uses AssetRef field names, not photo_url."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from mac_edge.services import default_services


def _caps(services: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for svc in services:
        for cap in svc.get("capabilities") or []:
            out[str(cap["capability_id"])] = cap
    return out


class AdvertisedAssetRefTests(unittest.TestCase):
    def test_laptop_image_caps_advertise_asset_refs(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            caps = _caps(default_services())

        photo = caps["display.photo"]
        self.assertIn("image_ref", photo["input_schema"])
        self.assertNotIn("photo_url", photo["input_schema"])

        show = caps["display.slideshow"]
        self.assertIn("image_refs", show["input_schema"])
        self.assertNotIn("photo_urls", show["input_schema"])

        perceive = caps["vision.perceive"]
        self.assertIn("image_ref", perceive["input_schema"])
        self.assertNotIn("photo_url", perceive["input_schema"])

        ask = caps["vision.ask"]
        self.assertIn("image_ref", ask["input_schema"])
        self.assertNotIn("photo_url", ask["input_schema"])

        query = caps["query.content"]
        self.assertIn("image_ref", query["output_schema"])
        self.assertNotIn("photo_url", query["output_schema"])

    def test_home_server_camera_advertises_capture_ref(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "home-server",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "xuanxuan",
            "MAC_EDGE_ADVERTISE_CAST": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            caps = _caps(default_services())
        capture = caps["camera.capture"]
        self.assertIn("capture_ref", capture["output_schema"])
        self.assertNotIn("photo_url", capture["output_schema"])
        self.assertNotIn("photo_local_path", capture["output_schema"])


class PluginCapAssetTests(unittest.TestCase):
    def test_capture_from_params_emits_capture_ref_only(self) -> None:
        from mac_edge.asset.sdk import CapAsset
        from mac_edge.asset.types import AssetRef
        from mac_edge.plugins.gopro_camera import capture_from_params

        mgr = MagicMock()
        mgr.register_storage_locator.return_value = AssetRef(
            asset_id="asset_cam", type="image", mime_type="image/jpeg"
        )
        asset = CapAsset(manager=mgr, intent_id="9", step_num=1)
        with patch(
            "mac_edge.plugins.gopro_camera.capture_photo_pipeline",
            return_value={
                "photo_url": "http://192.168.3.65:8080/a.jpg",
                "saved_as": "a.jpg",
                "photo_local_path": "/tmp/a.jpg",
            },
        ):
            _msg, outputs = capture_from_params({}, asset=asset)
        self.assertEqual(outputs["capture_ref"]["asset_id"], "asset_cam")
        self.assertNotIn("photo_url", outputs)
        self.assertNotIn("saved_as", outputs)
        self.assertNotIn("photo_local_path", outputs)


if __name__ == "__main__":
    unittest.main()
