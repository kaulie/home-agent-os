"""OCR service normalizer — no Paddle / no Brain."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import _as_xyxy, build_result, normalize_raw  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_v3_mapping(self) -> None:
        blocks = normalize_raw(
            {
                "rec_texts": ["小明", "今天"],
                "rec_scores": [0.98, 0.99],
                "rec_boxes": [[120, 80, 260, 140], [[280, 80], [420, 80], [420, 140], [280, 140]]],
            }
        )
        self.assertEqual([b["text"] for b in blocks], ["小明", "今天"])
        self.assertEqual(blocks[0]["bbox"], [120, 80, 260, 140])
        self.assertEqual(blocks[1]["bbox"], [280, 80, 420, 140])
        result = build_result(blocks, language="zh", return_bbox=True, return_confidence=True)
        self.assertEqual(result["text"], "小明今天")
        self.assertEqual(result["engine"], "paddleocr")
        self.assertEqual(result["model"], "PP-OCRv5_server")
        self.assertEqual(len(result["blocks"]), 2)

    def test_legacy_lines(self) -> None:
        blocks = normalize_raw(
            [
                [[[10, 10], [40, 10], [40, 20], [10, 20]], ("Hello", 0.9)],
            ]
        )
        self.assertEqual(blocks[0]["text"], "Hello")
        self.assertEqual(blocks[0]["bbox"], [10, 10, 40, 20])
        self.assertAlmostEqual(blocks[0]["confidence"], 0.9)

    def test_numpy_like_xyxy_and_poly(self) -> None:
        class Arr:
            def __init__(self, data: object) -> None:
                self._data = data

            def tolist(self):
                return self._data

        self.assertEqual(_as_xyxy(Arr([120, 80, 260, 140])), [120, 80, 260, 140])
        self.assertEqual(
            _as_xyxy(Arr([10, 20, 40, 20, 40, 50, 10, 50])),
            [10, 20, 40, 50],
        )
        self.assertEqual(
            _as_xyxy(Arr([Arr([10, 20]), Arr([40, 20]), Arr([40, 50]), Arr([10, 50])])),
            [10, 20, 40, 50],
        )

    def test_v3_mapping_numpy_like_boxes(self) -> None:
        class Arr:
            def __init__(self, data: object) -> None:
                self._data = data

            def tolist(self):
                return self._data

            def __iter__(self):
                return iter(self._data)

        blocks = normalize_raw(
            {
                "rec_texts": ["小明"],
                "rec_scores": [0.98],
                "rec_boxes": Arr([Arr([120, 80, 260, 140])]),
            }
        )
        self.assertEqual(blocks[0]["bbox"], [120, 80, 260, 140])

    def test_hide_bbox_when_asked(self) -> None:
        blocks = [{"text": "A", "bbox": [0, 0, 1, 1], "confidence": 1.0}]
        result = build_result(
            blocks, language="zh", return_bbox=False, return_confidence=False
        )
        self.assertNotIn("bbox", result["blocks"][0])
        self.assertNotIn("confidence", result["blocks"][0])


if __name__ == "__main__":
    unittest.main()
