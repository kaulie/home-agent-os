"""image.ocr: Brain wrapper over an independent OCR HTTP service."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

os.environ["BRAIN_SKIP_LLM_WORKER"] = "1"

from sdk.image_ocr import ImageOcrError, ocr_from_params, parse_asset_id  # noqa: E402
from system_capabilities import (  # noqa: E402
    SYSTEM_CAPABILITY_IDS,
    SystemCapabilityError,
    catalog_rows,
    is_system_capability,
    ocr_from_params as system_ocr,
    run_system_step,
)


class ParseAssetIdTests(unittest.TestCase):
    def test_json_ref(self) -> None:
        self.assertEqual(
            parse_asset_id({"asset_ref": json.dumps({"asset_id": "asset_1", "type": "image"})}),
            "asset_1",
        )

    def test_plain_id(self) -> None:
        self.assertEqual(parse_asset_id({"asset_ref": "asset_9"}), "asset_9")

    def test_missing(self) -> None:
        self.assertEqual(parse_asset_id({}), "")


class ImageOcrWrapperTests(unittest.TestCase):
    def test_missing_asset_ref(self) -> None:
        with self.assertRaises(ImageOcrError) as ctx:
            ocr_from_params({})
        self.assertIn("asset_ref", str(ctx.exception))

    def test_posts_bytes_not_url(self) -> None:
        posted: dict = {}

        def fetch(_aid: str):
            return b"\xff\xd8\xfffakejpeg", "image/jpeg"

        def post(image_bytes, **kwargs):
            posted["bytes"] = image_bytes
            posted["kwargs"] = kwargs
            return {
                "text": "小明",
                "blocks": [{"text": "小明", "bbox": [1, 2, 3, 4], "confidence": 0.9}],
                "language": "zh",
                "engine": "paddleocr",
                "model": "PP-OCRv5_server",
                "model_version": "PP-OCRv5",
            }

        msg, outputs = ocr_from_params(
            {"asset_ref": {"asset_id": "asset_ocr", "type": "image"}},
            fetch_bytes=fetch,
            post_ocr=post,
        )
        self.assertIn("小明", msg)
        self.assertEqual(outputs["text"], "小明")
        self.assertEqual(outputs["asset_id"], "asset_ocr")
        self.assertEqual(outputs["engine"], "paddleocr")
        blocks = json.loads(outputs["blocks"])
        self.assertEqual(blocks[0]["bbox"], [1, 2, 3, 4])
        self.assertEqual(posted["bytes"], b"\xff\xd8\xfffakejpeg")
        self.assertNotIn("asset_id", posted["kwargs"])

    def test_system_step_maps_error(self) -> None:
        with self.assertRaises(SystemCapabilityError):
            system_ocr({})
        with self.assertRaises(SystemCapabilityError):
            run_system_step("image.ocr", {})


class ImageOcrPresentationTests(unittest.TestCase):
    def test_assemble_uses_ocr_text(self) -> None:
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("flask not installed")
        import home_brain as hb

        pres = hb.assemble_presentation(
            {
                "text": "图上写了什么",
                "status": "succeeded",
                "execution_plan": [{"step": 1, "capability": "image.ocr"}],
                "step_outputs": {
                    "1": {
                        "text": "小明今天去公园玩。",
                        "blocks": "[]",
                        "asset_id": "asset_ocr",
                    }
                },
            }
        )
        self.assertEqual(pres["type"], "text")
        self.assertEqual(pres["from"], "text")
        self.assertEqual(pres["text"], "小明今天去公园玩。")


class ImageOcrCatalogTests(unittest.TestCase):
    def test_catalog_includes_system_ocr(self) -> None:
        self.assertIn("image.ocr", SYSTEM_CAPABILITY_IDS)
        self.assertTrue(is_system_capability("image.ocr"))
        rows = {r["capability_id"]: r for r in catalog_rows()}
        self.assertEqual(rows["image.ocr"]["kind"], "system")
        self.assertEqual(rows["image.ocr"]["assigned_edge_id"], "system")
        self.assertIn("asset_ref", rows["image.ocr"]["input_schema"])
        self.assertIn("text", rows["image.ocr"]["output_schema"])
        self.assertNotIn("image_url", rows["image.ocr"]["input_schema"])
        self.assertIn("OCR", rows["image.ocr"]["typical_triggers"])
        self.assertIn("看图理解", rows["image.ocr"]["do_not_dispatch"])


class OcrServiceNormalizeTests(unittest.TestCase):
    def test_service_normalize_independent(self) -> None:
        root = Path(__file__).resolve().parents[2] / "ocr-service"
        sys.path.insert(0, str(root))
        from engine import build_result, normalize_raw  # noqa: WPS433

        blocks = normalize_raw({"rec_texts": ["票"], "rec_scores": [1], "rec_boxes": [[0, 0, 2, 2]]})
        result = build_result(blocks, language="zh", return_bbox=True, return_confidence=True)
        self.assertEqual(result["text"], "票")
        self.assertEqual(result["engine"], "paddleocr")
        cache_mod = __import__("cache")
        tmp = tempfile.TemporaryDirectory()
        try:
            os.environ["OCR_CACHE_DIR"] = tmp.name
            key = cache_mod.cache_key(
                b"img",
                language="zh",
                return_bbox=True,
                return_confidence=True,
                model_version="PP-OCRv5",
            )
            cache_mod.store(key, result)
            self.assertEqual(cache_mod.load(key)["text"], "票")
        finally:
            tmp.cleanup()
            os.environ.pop("OCR_CACHE_DIR", None)


if __name__ == "__main__":
    unittest.main()
