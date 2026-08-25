"""Geometry unit tests — no MediaPipe / OpenCV / Paddle."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geometry import (  # noqa: E402
    INDEX_DIP,
    INDEX_TIP,
    decide,
    explode_blocks,
    finger_ray,
    rank_characters,
    split_block_to_chars,
    split_text_units,
)


class SplitTests(unittest.TestCase):
    def test_cjk_one_unit_each(self) -> None:
        self.assertEqual(split_text_units("我爱吃"), ["我", "爱", "吃"])

    def test_line_block_splits_equal_boxes(self) -> None:
        chars = split_block_to_chars({"text": "我爱吃苹果", "bbox": [0, 0, 500, 100]})
        self.assertEqual([c["text"] for c in chars], list("我爱吃苹果"))
        self.assertTrue(all(c["split"] for c in chars))
        self.assertEqual(chars[0]["bbox"], [0, 0, 100, 100])
        self.assertEqual(chars[-1]["bbox"], [400, 0, 500, 100])

    def test_single_char_not_split(self) -> None:
        chars = split_block_to_chars({"text": "吃", "bbox": [10, 10, 50, 60]})
        self.assertEqual(len(chars), 1)
        self.assertFalse(chars[0]["split"])

    def test_zero_bbox_dropped(self) -> None:
        chars = split_block_to_chars({"text": "吃", "bbox": [0, 0, 0, 0]})
        self.assertEqual(chars, [])

    def test_explode_mix(self) -> None:
        chars = explode_blocks(
            [
                {"text": "我爱", "bbox": [0, 0, 200, 80]},
                {"text": "吃", "bbox": [220, 0, 300, 80]},
            ]
        )
        self.assertEqual([c["text"] for c in chars], ["我", "爱", "吃"])


class RayTests(unittest.TestCase):
    def test_ray_from_dip_to_tip(self) -> None:
        ray = finger_ray({INDEX_DIP: (100.0, 200.0), INDEX_TIP: (100.0, 100.0)})
        self.assertIsNotNone(ray)
        origin, direction = ray
        self.assertEqual(origin, (100.0, 100.0))
        self.assertAlmostEqual(direction[0], 0.0, places=5)
        self.assertAlmostEqual(direction[1], -1.0, places=5)

    def test_picks_intersected_char_not_nearest(self) -> None:
        origin, direction = (200.0, 300.0), (0.0, -1.0)
        chars = [
            {"text": "近", "bbox": [260, 240, 310, 290]},
            {"text": "远", "bbox": [180, 40, 220, 80]},
        ]
        ranked = rank_characters(
            chars, origin, direction, max_angle_deg=18.0, max_distance=400.0
        )
        self.assertGreaterEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["text"], "远")

    def test_side_char_out_of_cone(self) -> None:
        origin, direction = (200.0, 300.0), (0.0, -1.0)
        chars = [{"text": "偏", "bbox": [350, 80, 400, 130]}]
        ranked = rank_characters(
            chars, origin, direction, max_angle_deg=18.0, max_distance=400.0
        )
        self.assertEqual(ranked, [])

    def test_contact_picks_glyph_under_nail(self) -> None:
        origin, direction = (205.0, 205.0), (1.0, 0.0)
        chars = [
            {"text": "找", "bbox": [100, 180, 180, 240]},
            {"text": "了", "bbox": [180, 180, 260, 240]},
            {"text": "刘", "bbox": [260, 180, 340, 240]},
            {"text": "niáng", "bbox": [190, 150, 250, 175]},
        ]
        ranked = rank_characters(
            chars, origin, direction, max_angle_deg=18.0, max_distance=400.0
        )
        self.assertGreaterEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["text"], "了")
        self.assertTrue(all("niáng" != r["text"] for r in ranked))

    def test_small_char_beats_title_box(self) -> None:
        origin, direction = (862.0, 1297.0), (-0.47, 0.88)
        chars = [
            {"text": "王", "bbox": [867, 1112, 1096, 1320]},
            {"text": "霸", "bbox": [840, 1275, 878, 1318]},
        ]
        ranked = rank_characters(
            chars, origin, direction, max_angle_deg=18.0, max_distance=400.0
        )
        self.assertGreaterEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["text"], "霸")

    def test_behind_finger_dropped(self) -> None:
        origin, direction = (200.0, 200.0), (0.0, -1.0)
        chars = [{"text": "后", "bbox": [180, 250, 220, 300]}]
        ranked = rank_characters(
            chars, origin, direction, max_angle_deg=25.0, max_distance=400.0
        )
        self.assertEqual(ranked, [])


class DecideTests(unittest.TestCase):
    def test_ok_when_margin_wide(self) -> None:
        ranked = [
            {"text": "吃", "score": 0.8, "bbox": [0, 0, 10, 10]},
            {"text": "苹", "score": 0.3, "bbox": [10, 0, 20, 10]},
        ]
        out = decide(ranked, min_score=0.28, min_margin=0.06)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["top"]["text"], "吃")

    def test_uncertain_close_scores(self) -> None:
        ranked = [
            {"text": "吃", "score": 0.51, "bbox": [0, 0, 10, 10]},
            {"text": "苹", "score": 0.50, "bbox": [10, 0, 20, 10]},
        ]
        out = decide(ranked, min_score=0.28, min_margin=0.06)
        self.assertEqual(out["status"], "ok_with_alternatives")
        self.assertEqual(out["top"]["text"], "吃")
        self.assertEqual(len(out["alternatives"]), 1)
        self.assertEqual(out["alternatives"][0]["text"], "苹")

    def test_uncertain_empty(self) -> None:
        out = decide([], min_score=0.28, min_margin=0.06)
        self.assertEqual(out["reason"], "no_candidate")


class PipelineInjectTests(unittest.TestCase):
    def test_selects_pointed_char(self) -> None:
        import pipeline

        class FakeImg:
            shape = (400, 400, 3)

            def __getitem__(self, _key):
                return self

        orig_crop = pipeline.crop_bbox
        pipeline.crop_bbox = lambda *a, **k: b"x"

        def detect(_img):
            return {INDEX_DIP: (300.0, 360.0), INDEX_TIP: (300.0, 300.0)}

        def ocr(data: bytes, **_kwargs):
            if data == b"x":
                return {"text": "吃", "blocks": [{"text": "吃", "bbox": [180, 40, 220, 90]}]}
            return {
                "text": "我爱吃",
                "blocks": [{"text": "我爱吃", "bbox": [100, 40, 340, 90]}],
            }

        try:
            result = pipeline.run_still(
                b"fake-bytes",
                detect_hand=detect,
                ocr=ocr,
                decode=lambda _b: FakeImg(),
            )
        finally:
            pipeline.crop_bbox = orig_crop
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["character"], "吃")
        self.assertTrue(result["split_from_line"])


if __name__ == "__main__":
    unittest.main()
