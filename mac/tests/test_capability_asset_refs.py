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
        self.assertIn("asset_ref", photo["input_schema"])
        self.assertNotIn("photo_url", photo["input_schema"])
        self.assertNotIn("image_ref", photo["input_schema"])

        show = caps["display.slideshow"]
        self.assertIn("asset_refs", show["input_schema"])
        self.assertNotIn("photo_urls", show["input_schema"])
        self.assertNotIn("image_refs", show["input_schema"])

        perceive = caps["vision.perceive"]
        self.assertIn("asset_ref", perceive["input_schema"])
        self.assertNotIn("photo_url", perceive["input_schema"])
        self.assertNotIn("image_ref", perceive["input_schema"])

        ask = caps["vision.ask"]
        self.assertIn("asset_ref", ask["input_schema"])
        self.assertNotIn("photo_url", ask["input_schema"])
        self.assertNotIn("image_ref", ask["input_schema"])

        query = caps["query.content"]
        self.assertIn("asset_ref", query["output_schema"])
        self.assertNotIn("photo_url", query["output_schema"])
        self.assertNotIn("image_ref", query["output_schema"])

        search = caps["search.images"]
        self.assertIn("asset_refs", search["output_schema"])
        self.assertNotIn("photo_url", search["output_schema"])
        self.assertNotIn("photo_urls", search["output_schema"])

        trial = caps["voice_test.run_trial"]
        self.assertIn("asset_ref", trial["output_schema"])
        self.assertNotIn("photo_url", trial["output_schema"])
        self.assertNotIn("photo_url", trial["input_schema"])
        self.assertNotIn("verification_image", trial["output_schema"])

    def test_home_server_camera_advertises_asset_ref(self) -> None:
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
        self.assertNotIn("asset_ref", capture["output_schema"])
        self.assertNotIn("upload_dest", capture.get("input_schema") or {})
        self.assertTrue(
            any("上传" in x or "图床" in x for x in capture["do_not_dispatch"]),
            capture["do_not_dispatch"],
        )
        upload = caps["asset.upload"]
        self.assertIn("capture_ref", upload["input_schema"])
        self.assertTrue(
            any("传到云上" in t or "图床" in t for t in upload["typical_triggers"]),
            upload["typical_triggers"],
        )


class PluginCapAssetTests(unittest.TestCase):
    def test_capture_from_params_emits_capture_ref_only(self) -> None:
        from mac_edge.asset.sdk import CapAsset
        from mac_edge.plugins.gopro_camera import capture_from_params

        mgr = MagicMock()
        asset = CapAsset(manager=mgr, intent_id="9", step_num=1)
        cref = {
            "capture_id": "cap_" + "ab" * 12,
            "type": "image",
            "mime_type": "image/jpeg",
        }
        with patch(
            "mac_edge.plugins.gopro_camera.capture_photo_pipeline",
            return_value={
                "photo_local_path": "/tmp/a.jpg",
                "capture_ref": cref,
            },
        ) as pipeline, patch("mac_edge.asset.sdk.CapAsset.upload_to") as upload_to:
            _msg, outputs = capture_from_params({}, asset=asset)
            upload_to.assert_not_called()
        self.assertEqual(outputs["capture_ref"]["capture_id"], cref["capture_id"])
        self.assertNotIn("asset_ref", outputs)
        self.assertNotIn("photo_url", outputs)
        self.assertNotIn("saved_as", outputs)
        self.assertNotIn("photo_local_path", outputs)
        pipeline.assert_called_once()
        mgr.register_local_file.assert_not_called()
        mgr.register_storage_locator.assert_not_called()

    def test_hydrate_asset_ref_into_upload_params(self) -> None:
        from mac_edge.runtime_context import RuntimeContext, resolve_params

        ctx = RuntimeContext()
        ctx.publish(
            {"asset_ref": {"asset_id": "asset_cam", "type": "image", "mime_type": "image/jpeg"}},
            {"asset_ref": {"type": "object", "data_dest": "context"}},
        )
        params = resolve_params({"asset_ref": "$asset_ref", "dest": "img_server"}, ctx)
        raw = params["asset_ref"]
        if isinstance(raw, str):
            self.assertIn("asset_cam", raw)
        else:
            self.assertEqual(raw["asset_id"], "asset_cam")
        self.assertEqual(params["dest"], "img_server")

    def test_hydrate_capture_ref_into_upload_params(self) -> None:
        from mac_edge.runtime_context import RuntimeContext, resolve_params

        ctx = RuntimeContext()
        cref = {
            "capture_id": "cap_" + "cd" * 12,
            "type": "image",
            "mime_type": "image/jpeg",
        }
        ctx.publish(
            {"capture_ref": cref},
            {"capture_ref": {"type": "object", "data_dest": "context"}},
        )
        params = resolve_params({"capture_ref": "$capture_ref", "dest": "img_server"}, ctx)
        raw = params["capture_ref"]
        if isinstance(raw, str):
            self.assertIn(cref["capture_id"], raw)
        else:
            self.assertEqual(raw["capture_id"], cref["capture_id"])

    def test_capture_pipeline_does_not_call_upload(self) -> None:
        import tempfile
        from unittest.mock import patch

        from mac_edge.plugins.gopro_camera import capture_photo_pipeline

        class _Snap:
            ssid = "Home"
            device = "en0"

        with tempfile.TemporaryDirectory() as td:
            env = {"MAC_EDGE_DATA_DIR": td}
            with (
                patch.dict(os.environ, env, clear=False),
                patch("mac_edge.plugins.gopro_camera.wifi_snapshot", return_value=_Snap()),
                patch("mac_edge.plugins.gopro_camera._join_gopro"),
                patch("mac_edge.plugins.gopro_camera.wait_camera_reachable"),
                patch("mac_edge.plugins.gopro_camera.capture_shutter"),
                patch("mac_edge.plugins.gopro_camera._control_get", return_value=(200, b"{}")),
                patch("mac_edge.plugins.gopro_camera.time.sleep"),
                patch(
                    "mac_edge.plugins.gopro_camera.fetch_latest_still_bytes",
                    return_value=(b"jpeg-bytes", "GOPR0001.JPG"),
                ),
                patch("mac_edge.plugins.gopro_camera._restore_home"),
                patch("mac_edge.asset.img_upload.upload_image_file") as upload,
            ):
                out = capture_photo_pipeline()
            self.assertIn("capture_ref", out)
            cid = out["capture_ref"]["capture_id"]
            self.assertTrue(cid.startswith("cap_"))
            self.assertTrue(str(out.get("photo_local_path") or "").endswith(f"{cid}.jpg"))
            self.assertNotIn("photo_url", out)
            upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
