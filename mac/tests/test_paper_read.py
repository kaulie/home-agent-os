"""paper.read — 论文听读（v1：original 原文模式）。

风格对齐 test_pdf_reader.py：mock CapAsset + 假结构 / 假合成，断言页范围、section 索引、
字数截断、audio AssetRef 上传、explain 明确失败、执行器分发与广告门控。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.asset.types import AssetError, AssetRef
from mac_edge.plugins import paper_read
from mac_edge.plugins.paper_explain import PaperExplainError, explain_script
from mac_edge.plugins.paper_read import MAX_READ_PAGES, PaperReadError, read_from_params
from mac_edge.plugins.paper_structure import PaperStructure, Section
from mac_edge.plugins.tts_file import TtsFileError, TtsResult
from mac_edge.services import default_services

DOC_REF = AssetRef(asset_id="doc_paper", type="document", mime_type="application/pdf")
AUDIO_REF = AssetRef(asset_id="asset_audio9", type="audio", mime_type="audio/mpeg")


def _structure(*, title: str | None = "Listening to Papers", chars: int = 20) -> PaperStructure:
    body = "字" * chars
    return PaperStructure(
        title=title,
        pages=4,
        sections=[
            Section(type="abstract", heading="Abstract", paragraphs=[body], start_page=1, end_page=1),
            Section(type="method", heading="2 Method", paragraphs=[body], start_page=2, end_page=3),
        ],
        references_dropped=True,
    )


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = {"MAC_EDGE_DATA_DIR": self._tmp.name, "MAC_EDGE_PAPER_READ_MAX_CHARS": ""}
        self._env = patch.dict(os.environ, env, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.pdf_path = Path(self._tmp.name) / "in.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4 fake")
        self._pages = patch.object(paper_read, "pdf_page_count", return_value=4)
        self._pages.start()
        self.addCleanup(self._pages.stop)

    def _asset(
        self, *, ref: AssetRef = DOC_REF, upload_error: BaseException | None = None
    ) -> MagicMock:
        asset = MagicMock()
        asset.require_ref.return_value = ref
        asset.materialize_file.return_value = self.pdf_path
        asset.upload_file.return_value = AUDIO_REF
        if upload_error is not None:
            asset.upload_file.side_effect = upload_error
        return asset

    def _structure_fn(self, structure: PaperStructure | None = None):
        def _fn(pdf_path, *, start, end):  # noqa: ANN001
            self.structure_args = {"start": start, "end": end, "path": Path(pdf_path)}
            return structure if structure is not None else _structure()

        return _fn

    def _synth(self, *, engine: str = "edge", duration: float | None = 30.0, fallback: str = ""):
        def _fn(text, work_dir, **kwargs):  # noqa: ANN001
            out = Path(work_dir) / "out.mp3"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\xff\xfb" + b"M" * 1000)
            self.synth_text = text
            self.synth_kwargs = kwargs
            return TtsResult(
                path=out,
                mime_type="audio/mpeg" if engine == "edge" else "audio/mp4",
                engine=engine,
                voice=kwargs.get("voice") or "zh-CN-XiaoxiaoNeural",
                duration_sec=duration,
                chunks=2,
                fallback_reason=fallback,
            )

        return _fn


class ReadOriginalTests(_Base):
    def test_original_mode_produces_audio_asset_and_sections(self) -> None:
        asset = self._asset()
        msg, outputs = read_from_params(
            {"asset_ref": DOC_REF.to_dict()},
            asset=asset,
            structure_fn=self._structure_fn(),
            synthesize_fn=self._synth(),
        )
        self.assertIn("paper.read", msg)
        self.assertEqual(outputs["mode"], "original")
        self.assertIsNone(outputs["depth"])
        self.assertEqual(outputs["title"], "Listening to Papers")
        self.assertEqual(outputs["asset_ref"], AUDIO_REF.to_dict())
        self.assertEqual((outputs["page_start"], outputs["page_end"]), (1, 4))
        self.assertEqual(outputs["sections_count"], 2)
        self.assertEqual([s["type"] for s in outputs["sections"]], ["abstract", "method"])
        # est_offset_sec 用「字符占比 × 总时长」估算：第一节在标题朗读之后，故 > 0 且递增
        offsets = [s["est_offset_sec"] for s in outputs["sections"]]
        self.assertGreater(offsets[0], 0.0)
        self.assertLess(offsets[0], offsets[1])
        self.assertLess(offsets[1], outputs["duration_sec"])
        self.assertEqual(outputs["engine"], "edge")
        self.assertFalse(outputs["truncated"])
        kwargs = asset.upload_file.call_args.kwargs
        self.assertEqual(kwargs["asset_type"], "audio")
        self.assertEqual(kwargs["producer"], "paper.read")
        self.assertEqual(kwargs["filename"], "Listening-to-Papers.mp3")
        self.assertIn("原文模式", outputs["status_text"])
        self.assertIn("References", outputs["status_text"])
        self.assertIn("下面", self.synth_text)
        self.assertEqual(self.structure_args["path"], self.pdf_path)

    def test_page_range_is_forwarded_and_clamped(self) -> None:
        _msg, outputs = read_from_params(
            {"asset_ref": DOC_REF.to_dict(), "page_start": 2, "page_end": 99},
            asset=self._asset(),
            structure_fn=self._structure_fn(),
            synthesize_fn=self._synth(),
        )
        self.assertEqual((self.structure_args["start"], self.structure_args["end"]), (2, 4))
        self.assertEqual((outputs["page_start"], outputs["page_end"]), (2, 4))

    def test_page_limit_fails(self) -> None:
        asset = self._asset()
        with patch.object(paper_read, "pdf_page_count", return_value=MAX_READ_PAGES + 5):
            with self.assertRaises(PaperReadError) as ctx:
                read_from_params(
                    {"asset_ref": DOC_REF.to_dict()},
                    asset=asset,
                    structure_fn=self._structure_fn(),
                    synthesize_fn=self._synth(),
                )
        self.assertIn("最多听读", str(ctx.exception))
        asset.upload_file.assert_not_called()

    def test_invalid_page_range_fails(self) -> None:
        with self.assertRaises(PaperReadError):
            read_from_params(
                {"asset_ref": DOC_REF.to_dict(), "page_start": 3, "page_end": 1},
                asset=self._asset(),
                structure_fn=self._structure_fn(),
                synthesize_fn=self._synth(),
            )

    def test_scanned_pdf_without_text_fails(self) -> None:
        asset = self._asset()
        empty = PaperStructure(title=None, pages=2, sections=[])
        with self.assertRaises(PaperReadError) as ctx:
            read_from_params(
                {"asset_ref": DOC_REF.to_dict()},
                asset=asset,
                structure_fn=self._structure_fn(empty),
                synthesize_fn=self._synth(),
            )
        self.assertIn("扫描件", str(ctx.exception))
        asset.upload_file.assert_not_called()

    def test_non_document_asset_fails(self) -> None:
        with self.assertRaises(PaperReadError) as ctx:
            read_from_params(
                {"asset_ref": DOC_REF.to_dict()},
                asset=self._asset(ref=AssetRef(asset_id="a1", type="image")),
                structure_fn=self._structure_fn(),
                synthesize_fn=self._synth(),
            )
        self.assertIn("type=document", str(ctx.exception))

    def test_max_chars_truncates_script_and_reports(self) -> None:
        _msg, outputs = read_from_params(
            {"asset_ref": DOC_REF.to_dict(), "max_chars": 30},
            asset=self._asset(),
            structure_fn=self._structure_fn(),
            synthesize_fn=self._synth(),
        )
        self.assertTrue(outputs["truncated"])
        self.assertLessEqual(outputs["chars"], 30)
        self.assertGreater(outputs["chars_total"], outputs["chars"])
        self.assertIn("截断", outputs["status_text"])
        self.assertLessEqual(sum(s["chars"] for s in outputs["sections"]), outputs["chars_total"])

    def test_synthesis_failure_is_explicit_chinese_error(self) -> None:
        asset = self._asset()

        def _boom(text, work_dir, **kwargs):  # noqa: ANN001
            raise TtsFileError("朗读失败：没有可合成的文字")

        with self.assertRaises(PaperReadError) as ctx:
            read_from_params(
                {"asset_ref": DOC_REF.to_dict()},
                asset=asset,
                structure_fn=self._structure_fn(),
                synthesize_fn=_boom,
            )
        self.assertIn("朗读失败", str(ctx.exception))
        asset.upload_file.assert_not_called()

    def test_upload_failure_is_explicit(self) -> None:
        asset = self._asset(upload_error=AssetError("brain 500"))
        with self.assertRaises(PaperReadError) as ctx:
            read_from_params(
                {"asset_ref": DOC_REF.to_dict()},
                asset=asset,
                structure_fn=self._structure_fn(),
                synthesize_fn=self._synth(),
            )
        self.assertIn("上传登记失败", str(ctx.exception))



class ExplainModeTests(_Base):
    def test_explain_mode_fails_explicitly_and_uploads_nothing(self) -> None:
        asset = self._asset()
        with self.assertRaises(PaperReadError) as ctx:
            read_from_params(
                {"asset_ref": DOC_REF.to_dict(), "mode": "explain"},
                asset=asset,
                structure_fn=self._structure_fn(),
                synthesize_fn=self._synth(),
            )
        self.assertIn("尚未交付", str(ctx.exception))
        self.assertIn("original", str(ctx.exception))
        asset.upload_file.assert_not_called()

    def test_invalid_mode_fails(self) -> None:
        with self.assertRaises(PaperReadError) as ctx:
            read_from_params(
                {"asset_ref": DOC_REF.to_dict(), "mode": "summary"},
                asset=self._asset(),
                structure_fn=self._structure_fn(),
                synthesize_fn=self._synth(),
            )
        self.assertIn("mode 只能是", str(ctx.exception))

    def test_explain_contract_is_reserved(self) -> None:
        with self.assertRaises(PaperExplainError) as ctx:
            explain_script(MagicMock(), depth="overview")
        self.assertIn("尚未交付", str(ctx.exception))
        with self.assertRaises(PaperExplainError) as bad:
            explain_script(MagicMock(), depth="everything")
        self.assertIn("depth 只能是", str(bad.exception))


class ExecutorDispatchTests(_Base):
    def test_executor_dispatches_paper_read(self) -> None:
        from mac_edge.executor import _execute_capability

        with patch(
            "mac_edge.executor.paper_read_from_params",
            return_value=("ok", {"asset_ref": AUDIO_REF.to_dict()}),
        ) as fn:
            ok, _msg, outputs = _execute_capability(
                "paper.read",
                self._asset(),
                params={"asset_ref": DOC_REF.to_dict()},
                config=MagicMock(),
            )
        self.assertTrue(ok)
        self.assertEqual(outputs["asset_ref"], AUDIO_REF.to_dict())
        fn.assert_called_once()

    def test_executor_surfaces_plugin_failure(self) -> None:
        from mac_edge.executor import _execute_capability

        with patch(
            "mac_edge.executor.paper_read_from_params",
            side_effect=PaperReadError("PDF 第 1–4 页没有可听读的正文（可能是扫描件）"),
        ):
            ok, msg, _outputs = _execute_capability(
                "paper.read", self._asset(), params={}, config=MagicMock()
            )
        self.assertFalse(ok)
        self.assertIn("扫描件", msg)


class AdvertiseTests(unittest.TestCase):
    _ENV = {
        "MAC_EDGE_ROLE": "laptop",
        "MAC_EDGE_SERVICE_WHITELIST": "",
        "MAC_EDGE_GOPRO_SSID": "",
        "MAC_EDGE_ADVERTISE_CAST": "0",
        "MAC_EDGE_HISENSE_USERNAME": "",
        "MAC_EDGE_HISENSE_PASSWORD": "",
        "MAC_EDGE_XIAOMI_USERNAME": "",
        "MAC_EDGE_XIAOMI_PASSWORD": "",
        "MAC_EDGE_DISPLAY_BACKEND": "",
        "MAC_EDGE_XIAOMI_TV": "",
        "MAC_EDGE_XIAOMI_TV_HOST": "",
    }

    def _services(self) -> list[dict]:
        with patch.dict(os.environ, self._ENV, clear=False):
            return default_services()

    def test_advertised_when_pymupdf_and_tts_available(self) -> None:
        with patch("mac_edge.plugins.paper_read.paper_read_available", return_value=True):
            services = self._services()
        svc = next((s for s in services if s["service_id"] == "local.paper.read"), None)
        self.assertIsNotNone(svc)
        cap = svc["capabilities"][0]
        self.assertEqual(cap["capability_id"], "paper.read")
        self.assertEqual(cap["kind"], "action")
        self.assertEqual(svc["group"], "read")
        self.assertIn("asset_ref", cap["input_schema"])
        self.assertIn("mode", cap["input_schema"])
        self.assertIn("sections", cap["output_schema"])
        for key in (
            "kind",
            "composition",
            "role",
            "planner_recognize",
            "typical_triggers",
            "do_not_dispatch",
        ):
            self.assertIn(key, cap)
        # 与 pdf.reader 的分工写进了广告：pdf.reader 管通用短文档
        self.assertIn("pdf.reader", cap["planner_recognize"])

    def test_skipped_without_dependencies(self) -> None:
        with patch("mac_edge.plugins.paper_read.paper_read_available", return_value=False):
            services = self._services()
        ids = [s["service_id"] for s in services]
        self.assertNotIn("local.paper.read", ids)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

