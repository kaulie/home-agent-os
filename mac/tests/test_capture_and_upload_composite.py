"""Runtime expands camera.capture_and_upload into two local atomic plugins."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from mac_edge.executor import _execute_capability


class CaptureAndUploadCompositeTests(unittest.TestCase):
    def test_success_returns_asset_ref_not_capture_ref(self) -> None:
        asset = MagicMock()
        config = MagicMock()
        with patch(
            "mac_edge.executor.capture_from_params",
            return_value=("cap ok", {"capture_ref": {"capture_id": "c1", "type": "image"}}),
        ):
            with patch(
                "mac_edge.executor.upload_from_params",
                return_value=(
                    "up ok",
                    {"asset_ref": {"asset_id": "a1", "type": "image"}, "dest": "img_server"},
                ),
            ) as upload:
                ok, msg, outputs = _execute_capability(
                    "camera.capture_and_upload",
                    asset,
                    params={},
                    config=config,
                )
        self.assertTrue(ok)
        self.assertEqual(msg, "up ok")
        self.assertEqual(outputs["asset_ref"]["asset_id"], "a1")
        self.assertNotIn("capture_ref", outputs)
        args, kwargs = upload.call_args
        params = kwargs["params"] if "params" in kwargs else args[0]
        self.assertEqual(params["capture_ref"]["capture_id"], "c1")

    def test_upload_failure_keeps_capture_success_msg(self) -> None:
        from mac_edge.plugins.asset_upload import AssetUploadError

        asset = MagicMock()
        config = MagicMock()
        with patch(
            "mac_edge.executor.capture_from_params",
            return_value=("cap ok", {"capture_ref": {"capture_id": "c1"}}),
        ):
            with patch(
                "mac_edge.executor.upload_from_params",
                side_effect=AssetUploadError("图床 503"),
            ):
                ok, msg, outputs = _execute_capability(
                    "camera.capture_and_upload",
                    asset,
                    params={},
                    config=config,
                )
        self.assertFalse(ok)
        self.assertIn("拍照成功", msg)
        self.assertIn("图床 503", msg)
        self.assertEqual(outputs, {})

    def test_capture_failure_is_not_upload_msg(self) -> None:
        from mac_edge.plugins.gopro_camera import GoProCameraError

        asset = MagicMock()
        config = MagicMock()
        with patch(
            "mac_edge.executor.capture_from_params",
            side_effect=GoProCameraError("连不上 GoPro"),
        ):
            ok, msg, outputs = _execute_capability(
                "camera.capture_and_upload",
                asset,
                params={},
                config=config,
            )
        self.assertFalse(ok)
        self.assertNotIn("拍照成功", msg)
        self.assertIn("GoPro", msg)
        self.assertEqual(outputs, {})


if __name__ == "__main__":
    unittest.main()
