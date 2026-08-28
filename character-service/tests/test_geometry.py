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
    pointing_fingers,
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


def _synthetic_hand(*, thumb_out: bool, index_out: bool, middle_out: bool = False) -> dict[int, tuple[float, float]]:
    """21 MediaPipe-style points. Wrist at bottom; extended digits go up."""
    lm: dict[int, tuple[float, float]] = {}
    wrist = (200.0, 400.0)
    lm[0] = wrist
    lm[1] = (170.0, 380.0)
    if thumb_out:
        lm[2], lm[3], lm[4] = (140.0, 340.0), (110.0, 300.0), (80.0, 250.0)
    else:
        lm[2], lm[3], lm[4] = (180.0, 390.0), (175.0, 400.0), (172.0, 408.0)
    columns = (
        (5, 6, 7, 8, 210.0),
        (9, 10, 11, 12, 230.0),
        (13, 14, 15, 16, 250.0),
        (17, 18, 19, 20, 270.0),
    )
    for mcp, pip, dip, tip, x in columns:
        if mcp == 5:
            extended = index_out
        elif mcp == 9:
            extended = middle_out
        else:
            extended = False
        if extended:
            lm[mcp], lm[pip], lm[dip], lm[tip] = (
                (x, 300.0),
                (x, 230.0),
                (x, 160.0),
                (x, 90.0),
            )
        else:
            lm[mcp], lm[pip], lm[dip], lm[tip] = (
                (x, 320.0),
                (x + 4, 350.0),
                (x + 6, 370.0),
                (x + 8, 385.0),
            )
    return lm


class PointingFingerTests(unittest.TestCase):
    def test_only_index_counts_as_one(self) -> None:
        found = pointing_fingers(_synthetic_hand(thumb_out=False, index_out=True))
        self.assertEqual([f["name"] for f in found], ["index"])

    def test_thumb_splayed_index_dominates(self) -> None:
        """Index pointing with thumb naturally splayed — index reach >> thumb,
        so index is the pointer, not ambiguous (intent 254 pattern)."""
        found = pointing_fingers(_synthetic_hand(thumb_out=True, index_out=True))
        self.assertEqual([f["name"] for f in found], ["index"])

    def test_index_and_middle_are_ambiguous(self) -> None:
        """Two fingers with similar reach (peace-sign) — genuinely ambiguous."""
        found = pointing_fingers(_synthetic_hand(thumb_out=False, index_out=True, middle_out=True))
        names = {f["name"] for f in found}
        self.assertGreaterEqual(len(found), 2)
        self.assertIn("index", names)
        self.assertIn("middle", names)

    def test_fist_has_no_pointing_digit(self) -> None:
        found = pointing_fingers(_synthetic_hand(thumb_out=False, index_out=False))
        self.assertEqual(found, [])

    def test_partial_index_dump_still_one_finger(self) -> None:
        found = pointing_fingers({INDEX_DIP: (100.0, 200.0), INDEX_TIP: (100.0, 100.0)})
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["name"], "index")

    def test_single_thumb_uses_thumb_ray(self) -> None:
        found = pointing_fingers(_synthetic_hand(thumb_out=True, index_out=False))
        self.assertEqual([f["name"] for f in found], ["thumb"])
        origin, direction = found[0]["origin"], found[0]["direction"]
        self.assertEqual(origin, (80.0, 250.0))
        # IP (110,300) → TIP (80,250)
        self.assertLess(direction[0], 0)
        self.assertLess(direction[1], 0)


class RayTests2(unittest.TestCase):
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

    def test_contact_near_tip_not_dropped_behind_ray(self) -> None:
        """Nail pressing just under a glyph that sits slightly behind the ray."""
        origin, direction = (240.0, 300.0), (-1.0, 0.0)
        chars = [
            {"text": "崭", "bbox": [205, 175, 280, 250]},
            {"text": "的", "bbox": [125, 175, 200, 250]},
            {"text": "力", "bbox": [125, 50, 200, 120]},
            {"text": "新", "bbox": [290, 175, 365, 250]},
        ]
        ranked = rank_characters(
            chars, origin, direction, max_angle_deg=30.0, max_distance=2200.0
        )
        texts = [r["text"] for r in ranked]
        self.assertIn("崭", texts)
        self.assertEqual(ranked[0]["text"], "崭")
        self.assertEqual(ranked[0]["mode"], "contact")

    def test_contact_does_not_steal_8025_di(self) -> None:
        origin, direction = (848.01, 2130.85), (-0.997256, -0.074025)
        chars = [
            {"text": "剧", "bbox": [688, 2127, 763, 2222]},
            {"text": "帝", "bbox": [688, 2037, 760, 2132]},
            {"text": "皇", "bbox": [688, 1942, 760, 2037]},
            {"text": "本", "bbox": [688, 2222, 763, 2318]},
        ]
        ranked = rank_characters(
            chars, origin, direction, max_angle_deg=30.0, max_distance=2772.0
        )
        self.assertGreaterEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["text"], "剧")


class ReplayEvalTests(unittest.TestCase):
    """Offline geometry replay against saved OCR boxes (no VLM)."""

    def _rank_replay(self, name: str) -> list[dict]:
        import json

        path = ROOT / "eval" / "q4" / "replay" / name
        data = json.loads(path.read_text(encoding="utf-8"))
        replay = data["replay"]
        return rank_characters(
            replay["chars"],
            tuple(replay["origin"]),
            tuple(replay["direction"]),
            max_angle_deg=float(replay["max_angle_deg"]),
            max_distance=float(replay["max_distance"]),
        )

    def test_q4_8022_yin_still_top1(self) -> None:
        ranked = self._rank_replay("IMG_8022_r1.json")
        self.assertGreaterEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["text"], "因")

    def test_q4_8024_ba_still_top1(self) -> None:
        ranked = self._rank_replay("IMG_8024_r1.json")
        self.assertGreaterEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["text"], "霸")
        self.assertNotEqual(ranked[0]["text"], "王")

    def test_q4_8025_ju_still_top1(self) -> None:
        ranked = self._rank_replay("IMG_8025_r1.json")
        self.assertGreaterEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["text"], "剧")
        self.assertNotEqual(ranked[0]["text"], "帝")

    def test_q4_7832_yuan_still_top1(self) -> None:
        for name in ("IMG_7832_r1.json", "IMG_7832_r2.json", "IMG_7832_r4.json"):
            ranked = self._rank_replay(name)
            self.assertGreaterEqual(len(ranked), 1, name)
            self.assertEqual(ranked[0]["text"], "渊", name)

    def test_intent201_scan_ranks_zhan(self) -> None:
        import json

        path = ROOT / "eval" / "intent201_capability_stages" / "00_live_replay.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        replay = data["replay"]
        ranked = rank_characters(
            replay["chars"],
            tuple(replay["origin"]),
            tuple(replay["direction"]),
            max_angle_deg=float(replay["max_angle_deg"]),
            max_distance=float(replay["max_distance"]),
        )
        texts = [r["text"] for r in ranked]
        self.assertIn("崭", texts)
        self.assertLess(texts.index("崭"), 3)
        self.assertEqual(ranked[0]["text"], "崭")


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
