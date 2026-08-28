"""Runtime expands reading.point_to_character into local atomics."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from mac_edge.capability_ads import composition_of, decomposes_to
from mac_edge.executor import _execute_capability


class PointToCharacterCompositeTests(unittest.TestCase):
    def test_ads_mark_composite(self) -> None:
        self.assertEqual(composition_of("reading.point_to_character"), "composite")
        self.assertEqual(
            decomposes_to("reading.point_to_character"),
            ["reading.detect_finger", "reading.ocr_at_finger", "reading.rank_pointed"],
        )
        self.assertEqual(composition_of("reading.detect_finger"), "atomic")
        self.assertEqual(composition_of("reading.ocr_at_finger"), "atomic")
        self.assertEqual(composition_of("reading.rank_pointed"), "atomic")

    def test_hydrates_finger_and_chars_and_hides_intermediates(self) -> None:
        asset = MagicMock()
        config = MagicMock()
        config.display_http_timeout_sec = 30
        asset_ref = {"asset_id": "a1", "type": "image"}
        finger = {"tip": [10.0, 20.0], "direction": [-1.0, 0.0]}
        chars = [{"text": "崭", "bbox": [1, 2, 3, 4]}]
        with patch(
            "mac_edge.executor.reading_stage_from_params",
            side_effect=[
                ("detect ok", {"finger": finger, "status": "ok"}),
                ("ocr ok", {"chars": chars, "status": "ok"}),
                (
                    "rank ok",
                    {"character": "崭", "answer_text": "手指指的是「崭」。", "status": "ok"},
                ),
            ],
        ) as stage:
            ok, msg, outputs = _execute_capability(
                "reading.point_to_character",
                asset,
                params={"asset_ref": asset_ref},
                config=config,
            )
        self.assertTrue(ok)
        self.assertEqual(msg, "rank ok")
        self.assertEqual(outputs["character"], "崭")
        self.assertNotIn("finger", outputs)
        self.assertNotIn("chars", outputs)
        self.assertEqual(stage.call_count, 3)
        detect_cap = stage.call_args_list[0][0][0]
        ocr_cap = stage.call_args_list[1][0][0]
        rank_cap = stage.call_args_list[2][0][0]
        self.assertEqual(detect_cap, "reading.detect_finger")
        self.assertEqual(ocr_cap, "reading.ocr_at_finger")
        self.assertEqual(rank_cap, "reading.rank_pointed")
        ocr_params = stage.call_args_list[1][0][1]
        rank_params = stage.call_args_list[2][0][1]
        self.assertEqual(ocr_params["finger"], finger)
        self.assertEqual(ocr_params["asset_ref"], asset_ref)
        self.assertEqual(rank_params["finger"], finger)
        self.assertEqual(rank_params["chars"], chars)
        self.assertEqual(rank_params["asset_ref"], asset_ref)

    def test_detect_crop_overrides_asset_ref_for_downstream_atoms(self) -> None:
        """Through the REAL executor (not a manual sim): when detect emits a
        new asset_ref (the finger crop), ocr and rank must receive THAT crop,
        not the composite's original full-photo asset_ref. This is the bug
        where fill-if-None left ocr reading the full photo because params_in
        already carried asset_ref."""
        asset = MagicMock()
        config = MagicMock()
        config.display_http_timeout_sec = 30
        full_ref = {"asset_id": "full1", "type": "image"}
        crop_ref = {"asset_id": "crop1", "type": "image", "mime_type": "image/jpeg"}
        finger = {"tip": [3.0, 3.0], "direction": [0.0, -1.0]}
        chars = [{"text": "崭", "bbox": [1, 2, 3, 4]}]
        full_shape = [800, 600]
        with patch(
            "mac_edge.executor.reading_stage_from_params",
            side_effect=[
                # detect outputs a NEW asset_ref (the crop) + crop-relative finger
                ("detect ok", {"finger": finger, "asset_ref": crop_ref,
                               "full_image_shape": full_shape, "status": "ok"}),
                ("ocr ok", {"chars": chars, "status": "ok"}),
                ("rank ok", {"character": "崭", "answer_text": "手指指的是「崭」。", "status": "ok"}),
            ],
        ) as stage:
            ok, _msg, outputs = _execute_capability(
                "reading.point_to_character",
                asset,
                params={"asset_ref": full_ref},
                config=config,
            )
        self.assertTrue(ok)
        ocr_params = stage.call_args_list[1][0][1]
        rank_params = stage.call_args_list[2][0][1]
        # downstream atoms get the CROP, not the full photo
        self.assertEqual(ocr_params["asset_ref"], crop_ref)
        self.assertEqual(rank_params["asset_ref"], crop_ref)
        # and the propagated finger/chars/full_image_shape
        self.assertEqual(ocr_params["finger"], finger)
        self.assertEqual(rank_params["finger"], finger)
        self.assertEqual(rank_params["chars"], chars)
        self.assertEqual(rank_params["full_image_shape"], full_shape)

    def test_detect_without_crop_keeps_full_photo_for_downstream(self) -> None:
        """When detect does NOT emit a new asset_ref (old char-svc, no crop),
        ocr/rank keep reading the original full-photo asset_ref — backward
        compatible with the pre-crop behavior."""
        asset = MagicMock()
        config = MagicMock()
        config.display_http_timeout_sec = 30
        full_ref = {"asset_id": "full1", "type": "image"}
        finger = {"tip": [10.0, 20.0], "direction": [-1.0, 0.0]}
        chars = [{"text": "崭", "bbox": [1, 2, 3, 4]}]
        with patch(
            "mac_edge.executor.reading_stage_from_params",
            side_effect=[
                ("detect ok", {"finger": finger, "status": "ok"}),  # no asset_ref
                ("ocr ok", {"chars": chars, "status": "ok"}),
                ("rank ok", {"character": "崭", "answer_text": "手指指的是「崭」。", "status": "ok"}),
            ],
        ) as stage:
            ok, _msg, _outputs = _execute_capability(
                "reading.point_to_character",
                asset,
                params={"asset_ref": full_ref},
                config=config,
            )
        self.assertTrue(ok)
        self.assertEqual(stage.call_args_list[1][0][1]["asset_ref"], full_ref)
        self.assertEqual(stage.call_args_list[2][0][1]["asset_ref"], full_ref)

    def test_does_not_capture(self) -> None:
        asset = MagicMock()
        config = MagicMock()
        config.display_http_timeout_sec = 30
        with patch("mac_edge.executor.capture_from_params") as capture, patch(
            "mac_edge.executor.upload_from_params"
        ) as upload, patch(
            "mac_edge.executor.reading_stage_from_params",
            side_effect=[
                ("d", {"finger": {"tip": [1, 2], "direction": [0, -1]}}),
                ("o", {"chars": [{"text": "零", "bbox": [0, 0, 1, 1]}]}),
                ("r", {"character": "零", "answer_text": "手指指的是「零」。"}),
            ],
        ):
            ok, _msg, outputs = _execute_capability(
                "reading.point_to_character",
                asset,
                params={"asset_ref": {"asset_id": "a1", "type": "image"}},
                config=config,
            )
        self.assertTrue(ok)
        capture.assert_not_called()
        upload.assert_not_called()
        self.assertEqual(outputs["character"], "零")

    def test_detect_registers_finger_crop_and_translates_finger(self) -> None:
        """detect atom crops a finger region from char-svc, registers it as a
        local asset, and emits finger in the crop's coordinate space plus
        full_image_shape so ocr/rank read the small crop instead of the full
        photo and rank calibrates max_dist on the source diagonal."""
        import base64

        from mac_edge.plugins.point_to_character import reading_stage_from_params

        asset = MagicMock()
        crop_ref = {"asset_id": "crop1", "type": "image", "mime_type": "image/jpeg"}
        asset.register_local_file.return_value = crop_ref
        # full-image finger at (400, 500); crop origin (100, 200) → crop-relative (300, 300)
        detect_result = {
            "status": "ok",
            "finger": {"tip": [400.0, 500.0], "direction": [0.0, -1.0]},
            "finger_crop_b64": base64.b64encode(b"\xff\xd8\xff\xe0fakejpg").decode("ascii"),
            "crop_origin": [100, 200],
            "full_image_shape": [800, 600],
        }
        with patch(
            "mac_edge.plugins.point_to_character._image_b64_from_params",
            return_value="ZmFrZQ==",
        ), patch(
            "mac_edge.plugins.point_to_character._post_stage",
            return_value=detect_result,
        ) as post:
            msg, outputs = reading_stage_from_params(
                "reading.detect_finger",
                {"asset_ref": {"asset_id": "a1", "type": "image"}},
                asset=asset,
            )
        self.assertEqual(outputs["status"], "ok")
        # crop registered as a local file
        asset.register_local_file.assert_called_once()
        self.assertEqual(outputs["asset_ref"], crop_ref)
        # finger translated into crop space
        self.assertEqual(outputs["finger"]["tip"], [300.0, 300.0])
        self.assertEqual(outputs["finger"]["direction"], [0.0, -1.0])
        self.assertEqual(outputs["crop_origin"], [100, 200])
        self.assertEqual(outputs["full_image_shape"], [800, 600])
        # return_crop requested from char-svc via _post_stage extra body
        _cap, _image_b64, extra = post.call_args[0][:3]
        self.assertEqual(_cap, "reading.detect_finger")
        self.assertTrue(extra.get("return_crop"))

    def test_detect_without_crop_falls_back_to_full_image_finger(self) -> None:
        """Older char-svc that doesn't return a crop: detect keeps full-image
        finger and emits no asset_ref/crop fields (backward compatible)."""
        from mac_edge.plugins.point_to_character import reading_stage_from_params

        asset = MagicMock()
        detect_result = {
            "status": "ok",
            "finger": {"tip": [400.0, 500.0], "direction": [0.0, -1.0]},
        }
        with patch(
            "mac_edge.plugins.point_to_character._image_b64_from_params",
            return_value="ZmFrZQ==",
        ), patch(
            "mac_edge.plugins.point_to_character._post_stage",
            return_value=detect_result,
        ):
            _msg, outputs = reading_stage_from_params(
                "reading.detect_finger",
                {"asset_ref": {"asset_id": "a1", "type": "image"}},
                asset=asset,
            )
        self.assertEqual(outputs["finger"]["tip"], [400.0, 500.0])
        self.assertNotIn("asset_ref", outputs)
        self.assertNotIn("crop_origin", outputs)
        self.assertNotIn("full_image_shape", outputs)
        asset.register_local_file.assert_not_called()

    def test_rank_passes_full_image_shape_to_char_svc(self) -> None:
        """rank atom forwards full_image_shape (propagated from detect) so
        char-svc calibrates max_dist on the source diagonal, not the crop's."""
        from mac_edge.plugins.point_to_character import reading_stage_from_params

        asset = MagicMock()
        finger = {"tip": [300.0, 300.0], "direction": [0.0, -1.0]}
        chars = [{"text": "崭", "bbox": [1, 2, 3, 4], "score": 0.9}]
        with patch(
            "mac_edge.plugins.point_to_character._image_b64_from_params",
            return_value="ZmFrZQ==",
        ), patch(
            "mac_edge.plugins.point_to_character._post_stage",
            return_value={"character": "崭", "answer_text": "手指指的是「崭」。", "status": "ok"},
        ) as post:
            _msg, outputs = reading_stage_from_params(
                "reading.rank_pointed",
                {
                    "asset_ref": {"asset_id": "crop1", "type": "image"},
                    "finger": finger,
                    "chars": chars,
                    "full_image_shape": [800, 600],
                },
                asset=asset,
            )
        _cap, _image_b64, extra = post.call_args[0][:3]
        self.assertEqual(extra["full_image_shape"], [800, 600])
        self.assertEqual(extra["finger"], finger)
        self.assertEqual(extra["chars"], chars)
        self.assertEqual(outputs["character"], "崭")


if __name__ == "__main__":
    unittest.main()
