"""vision.ask: image + question → answer_text; independent of vision.perceive schema."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.plugins.vision_ask import VisionAskError, ask, ask_from_params
from mac_edge.plugins.vision_providers import VisionProviderError


PHOTO = "http://192.168.3.65:8080/cover.jpg"


def _json_answer(**kwargs) -> str:
    payload = {
        "answer_text": "这个字是「喵」，读 miāo。",
        "refused": False,
    }
    payload.update(kwargs)
    return json.dumps(payload, ensure_ascii=False)


class FakeProvider:
    name = "fake"

    def __init__(self, text: str) -> None:
        self.text = text
        self.last_prompt = ""
        self.last_image_url = ""
        self.last_text_format: dict | None = None

    def analyze(
        self,
        *,
        image_url: str,
        prompt: str,
        timeout_sec: float = 90.0,
        text_format: dict | None = None,
    ) -> dict:
        del timeout_sec
        self.last_image_url = image_url
        self.last_prompt = prompt
        self.last_text_format = text_format
        if self.text == "__provider_error__":
            raise VisionProviderError("upstream down")
        return {
            "_provider_text": self.text,
            "raw_text": self.text,
            "model": "fake",
        }


class VisionAskTests(unittest.TestCase):
    def test_missing_photo_url(self) -> None:
        with self.assertRaises(VisionAskError) as ctx:
            ask(photo_url="  ", query="这个字读啥", provider=FakeProvider(_json_answer()))
        self.assertIn("missing photo_url", str(ctx.exception))

    def test_photo_url_must_be_http(self) -> None:
        with self.assertRaises(VisionAskError) as ctx:
            ask(
                photo_url="/tmp/cover.jpg",
                query="这个字读啥",
                provider=FakeProvider(_json_answer()),
            )
        self.assertIn("http", str(ctx.exception))

    def test_missing_query(self) -> None:
        with self.assertRaises(VisionAskError) as ctx:
            ask(photo_url=PHOTO, query="  ", provider=FakeProvider(_json_answer()))
        self.assertIn("missing query", str(ctx.exception))

    def test_invalid_json_fails(self) -> None:
        with self.assertRaises(VisionAskError) as ctx:
            ask(
                photo_url=PHOTO,
                query="这个字读啥",
                provider=FakeProvider("not json"),
            )
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_pointed_character(self) -> None:
        prov = FakeProvider(_json_answer())
        out = ask(photo_url=PHOTO, query="这个字读啥", provider=prov)
        self.assertEqual(out["answer_text"], "这个字是「喵」，读 miāo。")
        self.assertIn("这个字读啥", prov.last_prompt)
        self.assertEqual(prov.last_image_url, PHOTO)
        self.assertIsNotNone(prov.last_text_format)

    def test_nested_json_answer_fails(self) -> None:
        with self.assertRaises(VisionAskError) as ctx:
            ask(
                photo_url=PHOTO,
                query="这个字读啥",
                provider=FakeProvider(
                    _json_answer(answer_text='{"answer_text":"喵"}')
                ),
            )
        self.assertIn("nested JSON", str(ctx.exception))

    def test_object_answer_text_fails(self) -> None:
        with self.assertRaises(VisionAskError) as ctx:
            ask(
                photo_url=PHOTO,
                query="这个字读啥",
                provider=FakeProvider(
                    json.dumps(
                        {"answer_text": {"char": "喵"}, "refused": False},
                        ensure_ascii=False,
                    )
                ),
            )
        self.assertIn("plain string", str(ctx.exception))

    def test_refused_ok(self) -> None:
        out = ask(
            photo_url=PHOTO,
            query="这个字读啥",
            provider=FakeProvider(
                _json_answer(
                    answer_text="我不知道手指指的是哪一个字。",
                    refused=True,
                )
            ),
        )
        self.assertIn("不知道", out["answer_text"])

    def test_refused_without_不知道_fails(self) -> None:
        with self.assertRaises(VisionAskError) as ctx:
            ask(
                photo_url=PHOTO,
                query="这个字读啥",
                provider=FakeProvider(
                    _json_answer(answer_text="无法确认。", refused=True)
                ),
            )
        self.assertIn("不知道", str(ctx.exception))

    def test_from_params(self) -> None:
        from unittest.mock import MagicMock

        from mac_edge.asset.sdk import CapAsset
        from mac_edge.asset.types import HttpUrlRepresentation

        prov = FakeProvider(_json_answer())
        mgr = MagicMock()
        mgr.resolve_for_capability.return_value = HttpUrlRepresentation(url=PHOTO)
        asset = CapAsset(manager=mgr, intent_id="1", step_num=2)
        with patch(
            "mac_edge.plugins.vision_ask.get_provider", return_value=prov
        ):
            msg, outputs = ask_from_params(
                {
                    "image_ref": json.dumps(
                        {"asset_id": "asset_x", "type": "image"}
                    ),
                    "query": "这个字读啥",
                },
                asset=asset,
            )
        self.assertIn("喵", msg)
        self.assertEqual(outputs["answer_text"], "这个字是「喵」，读 miāo。")

    def test_from_params_missing_image_ref_fails(self) -> None:
        from unittest.mock import MagicMock

        from mac_edge.asset.sdk import CapAsset

        asset = CapAsset(manager=MagicMock(), intent_id="1", step_num=2)
        with self.assertRaises(VisionAskError) as ctx:
            ask_from_params({"query": "这个字读啥"}, asset=asset)
        self.assertIn("image_ref", str(ctx.exception))
        self.assertNotIn("photo_url", str(ctx.exception))

    def test_provider_error_is_ask_error(self) -> None:
        with self.assertRaises(VisionAskError) as ctx:
            ask(
                photo_url=PHOTO,
                query="这个字读啥",
                provider=FakeProvider("__provider_error__"),
            )
        self.assertIn("upstream down", str(ctx.exception))

    def test_does_not_import_vision_perceive(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src" / "mac_edge" / "plugins"
        src = (root / "vision_ask.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotEqual(node.module, "mac_edge.plugins.vision_perceive")
                self.assertFalse(
                    node.module.startswith("mac_edge.plugins.vision_perceive")
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("vision_perceive", alias.name)


if __name__ == "__main__":
    unittest.main()
