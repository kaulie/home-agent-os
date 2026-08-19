"""query.content: independent of vision; honesty + optional image upload."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from mac_edge.plugins.query_content import (
    QueryContentError,
    query_content,
    query_from_params,
)
from mac_edge.plugins.query_providers import QueryProviderError


def _json_answer(**kwargs) -> str:
    payload = {
        "answer_text": "客厅朝南，白天适合看书。",
        "want_image": False,
        "image_prompt": "",
        "domain": "general",
        "refused": False,
        "citations": [],
    }
    payload.update(kwargs)
    return json.dumps(payload, ensure_ascii=False)


def _upload_ok(**kwargs):
    return patch(
        "mac_edge.plugins.query_content._upload_generated_image",
        return_value={
            "photo_url": kwargs.get("photo_url", "http://192.168.3.65:8080/q.png"),
            "saved_as": kwargs.get("saved_as", "q.png"),
        },
    )


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        text: str,
        image_bytes: bytes | None = b"\x89PNG",
    ) -> None:
        self.text = text
        self.image_bytes = image_bytes
        self.generate_calls = 0
        self.last_image_prompt = ""

    def complete(
        self,
        *,
        prompt: str,
        timeout_sec: float = 90.0,
        text_format: dict | None = None,
    ) -> dict:
        del prompt, timeout_sec, text_format
        return {
            "_provider_text": self.text,
            "raw_text": self.text,
            "model": "fake",
        }

    def generate_image(self, *, prompt: str, timeout_sec: float = 90.0) -> bytes:
        del timeout_sec
        self.generate_calls += 1
        self.last_image_prompt = prompt
        if self.image_bytes is None:
            raise QueryProviderError("no image")
        return self.image_bytes


class QueryContentTests(unittest.TestCase):
    def test_missing_query(self) -> None:
        with self.assertRaises(QueryContentError) as ctx:
            query_content(query="  ", provider=FakeProvider(_json_answer()))
        self.assertIn("missing query", str(ctx.exception))

    def test_invalid_json_fails(self) -> None:
        with self.assertRaises(QueryContentError) as ctx:
            query_content(query="你好", provider=FakeProvider("not json"))
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_text_only(self) -> None:
        prov = FakeProvider(_json_answer())
        out = query_content(query="客厅适合看书吗", provider=prov)
        self.assertEqual(out["answer_text"], "客厅朝南，白天适合看书。")
        self.assertEqual(out["citations"], "[]")
        self.assertNotIn("photo_url", out)
        self.assertEqual(prov.generate_calls, 0)

    def test_refused_does_not_generate_image(self) -> None:
        prov = FakeProvider(
            _json_answer(
                answer_text="我不知道明天会不会下雨。",
                refused=True,
                want_image=True,
                image_prompt="雨景",
            )
        )
        out = query_content(query="明天会下雨吗", provider=prov)
        self.assertIn("不知道", out["answer_text"])
        self.assertNotIn("photo_url", out)
        self.assertEqual(prov.generate_calls, 0)

    def test_refused_without_不知道_fails(self) -> None:
        with self.assertRaises(QueryContentError) as ctx:
            query_content(
                query="明天呢",
                provider=FakeProvider(
                    _json_answer(answer_text="无法确认。", refused=True)
                ),
            )
        self.assertIn("不知道", str(ctx.exception))

    def test_professional_with_citations_ok(self) -> None:
        out = query_content(
            query="WHO 怎么定义健康",
            provider=FakeProvider(
                _json_answer(
                    answer_text="据世界卫生组织，健康不仅是没有疾病。",
                    domain="health",
                    citations=[
                        {
                            "name": "世界卫生组织",
                            "url": "https://www.who.int/",
                        }
                    ],
                )
            ),
        )
        self.assertIn("世界卫生组织", out["answer_text"])
        self.assertIn("who.int", out["citations"])
        self.assertNotIn("photo_url", out)

    def test_professional_without_citations_fails(self) -> None:
        with self.assertRaises(QueryContentError) as ctx:
            query_content(
                query="阿司匹林怎么吃",
                provider=FakeProvider(
                    _json_answer(
                        answer_text="饭后一片。",
                        domain="medicine",
                        citations=[],
                    )
                ),
            )
        self.assertIn("citations", str(ctx.exception))

    def test_nested_json_in_answer_fails(self) -> None:
        with self.assertRaises(QueryContentError) as ctx:
            query_content(
                query="hi",
                provider=FakeProvider(
                    _json_answer(answer_text='{"answer_text":"nope"}')
                ),
            )
        self.assertIn("nested JSON", str(ctx.exception))

    def test_image_path_uploads_photo_url(self) -> None:
        prov = FakeProvider(
            _json_answer(
                want_image=True,
                image_prompt="一只猫坐在窗边",
            ),
            image_bytes=b"fake-png-bytes",
        )

        def fake_upload(image_bytes: bytes, *, upload_dest: str) -> dict[str, str]:
            self.assertEqual(image_bytes, b"fake-png-bytes")
            self.assertEqual(upload_dest, "lan")
            return {
                "photo_url": "http://192.168.3.65:8080/query.png",
                "saved_as": "query.png",
            }

        with patch(
            "mac_edge.plugins.query_content._upload_generated_image",
            side_effect=fake_upload,
        ):
            out = query_content(query="画一只猫", provider=prov)
        self.assertEqual(prov.generate_calls, 1)
        self.assertEqual(prov.last_image_prompt, "一只猫坐在窗边")
        self.assertEqual(out["photo_url"], "http://192.168.3.65:8080/query.png")
        self.assertEqual(out["saved_as"], "query.png")

    def test_image_generate_failure_fails_step(self) -> None:
        prov = FakeProvider(
            _json_answer(want_image=True, image_prompt="一只猫"),
            image_bytes=None,
        )
        with self.assertRaises(QueryContentError) as ctx:
            query_content(query="画一只猫", provider=prov)
        self.assertIn("no image", str(ctx.exception))
        self.assertEqual(prov.generate_calls, 1)

    def test_appearance_question_draws_even_if_model_skips(self) -> None:
        prov = FakeProvider(_json_answer(want_image=False, image_prompt=""))
        with _upload_ok():
            out = query_content(query="大象 长什么样子", provider=prov)
        self.assertEqual(prov.generate_calls, 1)
        self.assertIn("大象", prov.last_image_prompt)
        self.assertIn("photo_url", out)

    def test_user_asked_for_image_draws(self) -> None:
        prov = FakeProvider(_json_answer(want_image=False, image_prompt=""))
        with _upload_ok():
            out = query_content(query="请配图说明一下", provider=prov)
        self.assertEqual(prov.generate_calls, 1)
        self.assertIn("photo_url", out)

    def test_tv_display_request_draws_even_if_model_skips(self) -> None:
        prov = FakeProvider(_json_answer(want_image=False, image_prompt=""))
        with _upload_ok():
            out = query_content(
                query="英文单词“have”怎么拼写？请给出适合投到电视上展示的清晰拼写结果。",
                provider=prov,
            )
        self.assertEqual(prov.generate_calls, 1)
        self.assertIn("photo_url", out)
        self.assertIn("have", prov.last_image_prompt.lower())

    def test_cast_keyword_draws_even_if_model_skips(self) -> None:
        prov = FakeProvider(_json_answer(want_image=False, image_prompt=""))
        with _upload_ok():
            out = query_content(query="把 have 的拼写投屏", provider=prov)
        self.assertEqual(prov.generate_calls, 1)
        self.assertIn("photo_url", out)

    def test_empty_image_prompt_uses_query(self) -> None:
        prov = FakeProvider(_json_answer(want_image=True, image_prompt=""))
        with _upload_ok():
            query_content(query="画一张图", provider=prov)
        self.assertEqual(prov.last_image_prompt, "配图说明：画一张图")

    def test_stroke_order_without_image_still_draws(self) -> None:
        prov = FakeProvider(
            _json_answer(
                answer_text="晋字10画。",
                domain="professional",
                citations=[{"name": "汉典", "url": "https://www.zdic.net/"}],
            )
        )
        with _upload_ok(photo_url="http://192.168.3.65:8080/jin.png", saved_as="jin.png"):
            out = query_content(query="请告诉我“晋”字笔画怎么写", provider=prov)
        self.assertEqual(prov.generate_calls, 1)
        self.assertEqual(out["photo_url"], "http://192.168.3.65:8080/jin.png")

    def test_stroke_order_without_citations_fails(self) -> None:
        with self.assertRaises(QueryContentError) as ctx:
            query_content(
                query="晋字笔顺",
                provider=FakeProvider(
                    _json_answer(
                        answer_text="晋字10画。",
                        want_image=True,
                        image_prompt="晋字笔顺图",
                        domain="general",
                        citations=[],
                    )
                ),
            )
        self.assertIn("citations", str(ctx.exception))

    def test_stroke_order_with_image_and_dictionary_ok(self) -> None:
        prov = FakeProvider(
            _json_answer(
                answer_text="据汉典，「晋」字10画。",
                want_image=True,
                image_prompt="白底黑字，汉字晋的规范笔顺示意图",
                domain="professional",
                citations=[{"name": "汉典", "url": "https://www.zdic.net/"}],
            )
        )
        with patch(
            "mac_edge.plugins.query_content._upload_generated_image",
            return_value={
                "photo_url": "http://192.168.3.65:8080/jin.png",
                "saved_as": "jin.png",
            },
        ):
            out = query_content(query="请告诉我“晋”字笔画怎么写", provider=prov)
        self.assertEqual(prov.generate_calls, 1)
        self.assertEqual(out["photo_url"], "http://192.168.3.65:8080/jin.png")
        self.assertIn("汉典", out["citations"])

    def test_stroke_order_refused_skips_image(self) -> None:
        prov = FakeProvider(
            _json_answer(
                answer_text="我不知道这个字的规范笔顺，请查汉典。",
                refused=True,
                want_image=True,
                image_prompt="笔顺图",
                domain="professional",
            )
        )
        out = query_content(query="某字几画", provider=prov)
        self.assertEqual(prov.generate_calls, 0)
        self.assertNotIn("photo_url", out)

    def test_query_from_params(self) -> None:
        from mac_edge.asset.sdk import CapAsset

        prov = FakeProvider(_json_answer())
        asset = CapAsset(manager=MagicMock(), intent_id="1", step_num=1)
        with patch(
            "mac_edge.plugins.query_content.get_provider", return_value=prov
        ):
            msg, outputs = query_from_params(
                {"query": "客厅适合看书吗"}, asset=asset
            )
        self.assertIn("客厅朝南", outputs["answer_text"])
        self.assertIn("query:", msg)
        self.assertNotIn("photo_url", outputs)
        self.assertNotIn("image_ref", outputs)  # no draw in this fixture

    def test_query_from_params_registers_image_ref(self) -> None:
        from mac_edge.asset.sdk import CapAsset
        from mac_edge.asset.types import AssetRef

        prov = FakeProvider(
            _json_answer(want_image=True, image_prompt="一只猫"),
            image_bytes=b"png",
        )
        mgr = MagicMock()
        mgr.register_storage_locator.return_value = AssetRef(
            asset_id="asset_q", type="image", mime_type="image/png"
        )
        asset = CapAsset(manager=mgr, intent_id="7", step_num=1)

        def fake_upload(image_bytes: bytes, *, upload_dest: str) -> dict[str, str]:
            self.assertEqual(image_bytes, b"png")
            return {
                "photo_url": "http://192.168.3.65:8080/q.png",
                "saved_as": "q.png",
            }

        with patch(
            "mac_edge.plugins.query_content.get_provider", return_value=prov
        ), patch(
            "mac_edge.plugins.query_content._upload_generated_image",
            side_effect=fake_upload,
        ):
            _msg, outputs = query_from_params({"query": "画一只猫"}, asset=asset)
        self.assertNotIn("photo_url", outputs)
        self.assertNotIn("saved_as", outputs)
        self.assertEqual(outputs["image_ref"]["asset_id"], "asset_q")
        mgr.register_storage_locator.assert_called_once()


    def test_ark_timeout_does_not_collapse_read_to_connect(self) -> None:
        from mac_edge.plugins.query_providers.ark_sdk import ark_http_timeout

        timeout = ark_http_timeout(90.0)
        self.assertEqual(timeout.connect, 20.0)
        self.assertEqual(timeout.read, 90.0)

    def test_does_not_import_vision(self) -> None:
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src" / "mac_edge" / "plugins"
        files = [root / "query_content.py", *(root / "query_providers").glob("*.py")]
        self.assertTrue(files)
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.append(node.module)
                for mod in modules:
                    self.assertFalse(
                        mod.startswith("mac_edge.plugins.vision"),
                        f"{path.name} imports {mod}",
                    )
                    self.assertNotEqual(mod, "mac_edge.plugins.vision_perceive")
                    self.assertNotIn("gopro_camera", mod)


if __name__ == "__main__":
    unittest.main()
