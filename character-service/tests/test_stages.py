"""Pipeline stage unit tests — mocked detect / OCR, no MediaPipe."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geometry import AMBIGUOUS_FINGER_MSG, INDEX_DIP, INDEX_TIP  # noqa: E402
from pipeline import (  # noqa: E402
    PipelineError,
    detect_finger,
    finger_crop_bytes,
    parse_finger,
    rank_pointed,
    run_still,
)


class FakeImage:
    shape = (400, 400, 3)


class StageTests(unittest.TestCase):
    def test_parse_finger(self) -> None:
        origin, direction = parse_finger({"tip": [10, 20], "direction": [-3, 0]})
        self.assertEqual(origin, (10.0, 20.0))
        self.assertAlmostEqual(direction[0], -1.0)
        self.assertAlmostEqual(direction[1], 0.0)

    def test_parse_finger_missing(self) -> None:
        with self.assertRaises(PipelineError):
            parse_finger(None)

    def test_detect_finger_mocked(self) -> None:
        def fake_detect(_img):
            return {INDEX_DIP: (100.0, 200.0), INDEX_TIP: (100.0, 100.0)}

        out = detect_finger(b"fake", detect_hand=fake_detect, decode=lambda _: FakeImage())
        self.assertEqual(out["status"], "ok")
        finger = out["finger"]
        self.assertEqual(finger["tip"], [100.0, 100.0])
        self.assertAlmostEqual(finger["direction"][0], 0.0, places=3)
        self.assertLess(finger["direction"][1], 0)

    def test_detect_finger_ambiguous_when_two_digits(self) -> None:
        lm: dict[int, tuple[float, float]] = {0: (200.0, 400.0), 1: (170.0, 380.0)}
        lm[2], lm[3], lm[4] = (180.0, 390.0), (175.0, 400.0), (172.0, 408.0)
        for mcp, pip, dip, tip, x in (
            (5, 6, 7, 8, 210.0),
            (9, 10, 11, 12, 230.0),
            (13, 14, 15, 16, 250.0),
            (17, 18, 19, 20, 270.0),
        ):
            if mcp in (5, 9):  # index + middle both fully extended (similar reach)
                lm[mcp], lm[pip], lm[dip], lm[tip] = (x, 300.0), (x, 230.0), (x, 160.0), (x, 90.0)
            else:
                lm[mcp], lm[pip], lm[dip], lm[tip] = (x, 320.0), (x + 4, 350.0), (x + 6, 370.0), (x + 8, 385.0)

        def fake_detect(_img):
            return lm

        with self.assertRaises(PipelineError) as ctx:
            detect_finger(b"fake", detect_hand=fake_detect, decode=lambda _: FakeImage())
        self.assertEqual(ctx.exception.status, "ambiguous_finger")
        self.assertIn("多根手指", str(ctx.exception))
        self.assertIn(AMBIGUOUS_FINGER_MSG[:8], str(ctx.exception))

    def test_detect_finger_single_thumb(self) -> None:
        lm: dict[int, tuple[float, float]] = {0: (200.0, 400.0), 1: (170.0, 380.0)}
        lm[2], lm[3], lm[4] = (140.0, 340.0), (110.0, 300.0), (80.0, 250.0)
        for mcp, pip, dip, tip, x in (
            (5, 6, 7, 8, 210.0),
            (9, 10, 11, 12, 230.0),
            (13, 14, 15, 16, 250.0),
            (17, 18, 19, 20, 270.0),
        ):
            lm[mcp], lm[pip], lm[dip], lm[tip] = (x, 320.0), (x + 4, 350.0), (x + 6, 370.0), (x + 8, 385.0)

        def fake_detect(_img):
            return lm

        out = detect_finger(b"fake", detect_hand=fake_detect, decode=lambda _: FakeImage())
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["finger"]["digit"], "thumb")
        self.assertEqual(out["finger"]["tip"], [80.0, 250.0])
        self.assertLess(out["finger"]["direction"][0], 0)
        self.assertLess(out["finger"]["direction"][1], 0)

    def test_run_still_orchestrates_three_stages(self) -> None:
        finger = {"tip": [100.0, 100.0], "direction": [0.0, -1.0]}
        chars = [{"text": "力", "bbox": [90, 40, 110, 70], "score": 0.9}]
        ranked = {
            "status": "ok",
            "character": "力",
            "finger": finger,
            "candidates": [],
            "timing": {"geometry_ranking_s": 0.01, "ocr_vlm_s": 0.0},
        }
        with patch("pipeline.detect_finger", return_value={"finger": finger, "timing": {}}), patch(
            "pipeline.ocr_at_finger", return_value={"chars": chars, "timing": {}}
        ) as ocr, patch("pipeline.rank_pointed", return_value=ranked) as rank:
            out = run_still(b"img")
        self.assertEqual(out["engine"], "reading.point_to_character")
        self.assertEqual(out["character"], "力")
        ocr.assert_called_once()
        self.assertEqual(ocr.call_args[0][1], finger)
        rank.assert_called_once()
        self.assertEqual(rank.call_args[0][1], finger)
        self.assertEqual(rank.call_args[0][2], chars)

    def test_finger_crop_bytes_returns_origin_and_shape(self) -> None:
        try:
            import numpy as np
        except Exception:  # pragma: no cover
            self.skipTest("numpy unavailable")
        img = np.zeros((1000, 800, 3), dtype=np.uint8)
        out = finger_crop_bytes(img, (400.0, 500.0), half=300)
        self.assertIsNotNone(out)
        crop_bytes, origin, shape = out
        self.assertIsInstance(crop_bytes, (bytes, bytearray))
        self.assertTrue(len(crop_bytes) > 0)
        # crop origin is fingertip - half, clamped to >= 0
        self.assertEqual(origin, (100, 200))
        self.assertEqual(shape, (800, 1000))  # (w, h)

    def test_finger_crop_bytes_clamps_to_edges(self) -> None:
        try:
            import numpy as np
        except Exception:  # pragma: no cover
            self.skipTest("numpy unavailable")
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        out = finger_crop_bytes(img, (10.0, 10.0), half=300)
        self.assertIsNotNone(out)
        _b, origin, _s = out
        self.assertEqual(origin, (0, 0))

    def test_detect_finger_return_crop_emits_crop_fields(self) -> None:
        try:
            import numpy as np
        except Exception:  # pragma: no cover:
            self.skipTest("numpy unavailable")

        class RealImage:
            def __init__(self) -> None:
                self.shape = (600, 600, 3)
            def __getitem__(self, sl):
                return np.zeros((300, 300, 3), dtype=np.uint8)

        def fake_detect(_img):
            return {INDEX_DIP: (100.0, 200.0), INDEX_TIP: (100.0, 100.0)}

        out = detect_finger(
            b"fake",
            detect_hand=fake_detect,
            decode=lambda _: RealImage(),
            return_crop=True,
        )
        self.assertEqual(out["status"], "ok")
        self.assertIn("finger_crop_b64", out)
        self.assertIn("crop_origin", out)
        self.assertIn("full_image_shape", out)
        self.assertEqual(out["full_image_shape"], [600, 600])

    def test_detect_finger_without_return_crop_has_no_crop_fields(self) -> None:
        def fake_detect(_img):
            return {INDEX_DIP: (100.0, 200.0), INDEX_TIP: (100.0, 100.0)}

        out = detect_finger(b"fake", detect_hand=fake_detect, decode=lambda _: FakeImage())
        self.assertNotIn("finger_crop_b64", out)
        self.assertNotIn("crop_origin", out)

    def test_rank_pointed_uses_full_image_shape_for_max_dist(self) -> None:
        try:
            import numpy as np
        except Exception:  # pragma: no cover:
            self.skipTest("numpy unavailable")
        finger = {"tip": [100.0, 100.0], "direction": [0.0, -1.0]}
        chars = [{"text": "力", "bbox": [90, 40, 110, 70], "score": 0.9}]
        # crop image is small (300x300) but full_image_shape says 4000x3000.
        # max_dist must be calibrated on the full diagonal, not the crop's.
        crop_img = np.zeros((300, 300, 3), dtype=np.uint8)
        with patch("pipeline.rank_characters") as rk, patch("pipeline.crop_bbox") as cb, patch(
            "pipeline.ocr_recognize", side_effect=Exception("skip")
        ), patch("pipeline._ocr_fn") as ocrfn:
            ocrfn.return_value = (lambda _b, language="zh": {}, (Exception,))
            rk.return_value = []
            cb.return_value = b""
            rank_pointed(
                crop_img.tobytes(),
                finger,
                chars,
                full_image_shape=[4000, 3000],
                decode=lambda _b: crop_img,
            )
        _args, kwargs = rk.call_args
        # max_distance is the 5th positional arg (after chars, origin, direction, max_angle)
        max_dist = kwargs.get("max_distance")
        if max_dist is None:
            max_dist = rk.call_args[0][4]
        import math
        self.assertAlmostEqual(max_dist, 0.55 * math.hypot(4000, 3000), places=2)


if __name__ == "__main__":
    unittest.main()
