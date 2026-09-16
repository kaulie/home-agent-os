"""pdf.reader — PDF 文字朗读成可播放 TTS 音频（audio Asset）。

风格对齐 test_pdf_to_images.py：mock CapAsset + 假抽字 / 假合成，断言页范围、
字数截断、audio AssetRef 上传、明确中文失败、执行器分发与广告门控。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.asset.types import AssetError, AssetRef
from mac_edge.plugins import pdf_reader
from mac_edge.plugins.pdf_reader import (
    MAX_READ_PAGES,
    PdfReaderError,
    read_from_params,
)
from mac_edge.plugins.tts_file import TtsFileError, TtsResult
from mac_edge.services import default_services

DOC_REF = AssetRef(asset_id="doc_9", type="document", mime_type="application/pdf")
AUDIO_REF = AssetRef(asset_id="asset_audio1", type="audio", mime_type="audio/mpeg")

PAGES = ["第一页的文字内容。", "第二页的文字内容。", "第三页的文字内容。"]


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = {"MAC_EDGE_DATA_DIR": self._tmp.name, "MAC_EDGE_PDF_READER_MAX_CHARS": ""}
        self._env = patch.dict(os.environ, env, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.pdf_path = Path(self._tmp.name) / "in.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4 fake")
        # 不接真 pymupdf：页数固定 3，抽字用假实现。
        self._pages = patch.object(pdf_reader, "pdf_page_count", return_value=3)
        self._pages.start()
        self.addCleanup(self._pages.stop)

    def _asset(
        self,
        *,
        upload: AssetRef | None = None,
        upload_error: BaseException | None = None,
    ) -> MagicMock:
        asset = MagicMock()
        asset.require_ref.return_value = DOC_REF
        asset.materialize_file.return_value = self.pdf_path
        asset.upload_file.return_value = AUDIO_REF if upload is None else upload
        if upload_error is not None:
            asset.upload_file.side_effect = upload_error
        return asset

    def _extract(self, pages: list[str] | None = None):
        def _fn(pdf_path, *, start, end):  # noqa: ANN001
            self.extract_args = {"start": start, "end": end, "path": Path(pdf_path)}
            source = PAGES if pages is None else pages
            return list(source)

        return _fn

    def _synth(self, *, engine: str = "edge", duration: float | None = 12.5, fallback: str = ""):
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

class ReadTests(_Base):
    def test_whole_doc_produces_audio_asset(self) -> None:
        asset = self._asset()
        msg, outputs = read_from_params(
            {"asset_ref": DOC_REF.to_dict()},
            asset=asset,
            extract_fn=self._extract(),
            synthesize_fn=self._synth(),
        )
        self.assertIn("pdf.reader", msg)
        self.assertEqual(outputs["asset_ref"], AUDIO_REF.to_dict())
        self.assertEqual(outputs["page_count"], 3)
        self.assertEqual((outputs["page_start"], outputs["page_end"]), (1, 3))
        self.assertEqual(outputs["engine"], "edge")
        self.assertFalse(outputs["truncated"])
        self.assertEqual(self.extract_args["start"], 1)
        self.assertEqual(self.extract_args["end"], 3)
        kwargs = asset.upload_file.call_args.kwargs
        self.assertEqual(kwargs["asset_type"], "audio")
        self.assertEqual(kwargs["mime_type"], "audio/mpeg")
        self.assertEqual(kwargs["producer"], "pdf.reader")
        self.assertEqual(kwargs["filename"], "pdf-doc_9.mp3")
        self.assertIn("audio", outputs["status_text"])

    def test_page_range_is_forwarded_and_clamped(self) -> None:
        asset = self._asset()
        _msg, outputs = read_from_params(
            {"asset_ref": DOC_REF.to_dict(), "page_start": 2, "page_end": 99},
            asset=asset,
            extract_fn=self._extract(),
            synthesize_fn=self._synth(),
        )
        self.assertEqual((self.extract_args["start"], self.extract_args["end"]), (2, 3))
        self.assertEqual((outputs["page_start"], outputs["page_end"]), (2, 3))

    def test_page_limit_fails(self) -> None:
        asset = self._asset()
        with patch.object(pdf_reader, "pdf_page_count", return_value=MAX_READ_PAGES + 5):
            with self.assertRaises(PdfReaderError) as ctx:
                read_from_params(
                    {"asset_ref": DOC_REF.to_dict()},
                    asset=asset,
                    extract_fn=self._extract(),
                    synthesize_fn=self._synth(),
                )
        self.assertIn("最多朗读", str(ctx.exception))
        asset.upload_file.assert_not_called()

    def test_invalid_page_range_fails(self) -> None:
        with self.assertRaises(PdfReaderError) as ctx:
            read_from_params(
                {"asset_ref": DOC_REF.to_dict(), "page_start": 3, "page_end": 2},
                asset=self._asset(),
                extract_fn=self._extract(),
                synthesize_fn=self._synth(),
            )
        self.assertIn("页范围无效", str(ctx.exception))

    def test_rejects_non_document(self) -> None:
        asset = self._asset()
        asset.require_ref.return_value = AssetRef(asset_id="img_1", type="image")
        with self.assertRaises(PdfReaderError) as ctx:
            read_from_params(
                {"asset_ref": {"asset_id": "img_1", "type": "image"}},
                asset=asset,
                extract_fn=self._extract(),
                synthesize_fn=self._synth(),
            )
        self.assertIn("document", str(ctx.exception))

    def test_missing_asset_ref_fails(self) -> None:
        asset = self._asset()
        asset.require_ref.side_effect = AssetError("missing or invalid asset_ref")
        with self.assertRaises(PdfReaderError):
            read_from_params(
                {}, asset=asset, extract_fn=self._extract(), synthesize_fn=self._synth()
            )

    def test_scanned_pdf_without_text_fails(self) -> None:
        with self.assertRaises(PdfReaderError) as ctx:
            read_from_params(
                {"asset_ref": DOC_REF.to_dict()},
                asset=self._asset(),
                extract_fn=self._extract(["", "   \n"]),
                synthesize_fn=self._synth(),
            )
        message = str(ctx.exception)
        self.assertIn("没有可提取的文字", message)
        self.assertIn("OCR", message)

class TruncateTests(_Base):
    def test_truncates_and_marks_status(self) -> None:
        long_pages = ["甲" * 100 + "。", "乙" * 100 + "。"]
        _msg, outputs = read_from_params(
            {"asset_ref": DOC_REF.to_dict(), "max_chars": 30},
            asset=self._asset(),
            extract_fn=self._extract(long_pages),
            synthesize_fn=self._synth(),
        )
        self.assertTrue(outputs["truncated"])
        self.assertEqual(outputs["chars"], 30)
        self.assertEqual(outputs["chars_total"], len("甲" * 100 + "。\n" + "乙" * 100 + "。"))
        self.assertEqual(len(self.synth_text), 30)
        self.assertIn("截断", outputs["status_text"])

    def test_zero_max_chars_reads_everything(self) -> None:
        long_pages = ["甲" * 500 + "。"]
        _msg, outputs = read_from_params(
            {"asset_ref": DOC_REF.to_dict(), "max_chars": 0},
            asset=self._asset(),
            extract_fn=self._extract(long_pages),
            synthesize_fn=self._synth(),
        )
        self.assertFalse(outputs["truncated"])
        self.assertEqual(outputs["chars"], outputs["chars_total"])

    def test_env_default_max_chars_applies(self) -> None:
        with patch.dict(os.environ, {"MAC_EDGE_PDF_READER_MAX_CHARS": "5"}, clear=False):
            _msg, outputs = read_from_params(
                {"asset_ref": DOC_REF.to_dict()},
                asset=self._asset(),
                extract_fn=self._extract(),
                synthesize_fn=self._synth(),
            )
        self.assertTrue(outputs["truncated"])
        self.assertEqual(outputs["chars"], 5)

    def test_invalid_max_chars_fails(self) -> None:
        with self.assertRaises(PdfReaderError):
            read_from_params(
                {"asset_ref": DOC_REF.to_dict(), "max_chars": "一点点"},
                asset=self._asset(),
                extract_fn=self._extract(),
                synthesize_fn=self._synth(),
            )

    def test_fallback_engine_is_reported(self) -> None:
        _msg, outputs = read_from_params(
            {"asset_ref": DOC_REF.to_dict()},
            asset=self._asset(),
            extract_fn=self._extract(),
            synthesize_fn=self._synth(engine="say", duration=None, fallback="edge 挂了"),
        )
        self.assertEqual(outputs["engine"], "say")
        self.assertIsNone(outputs["duration_sec"])
        self.assertIn("回退本机语音", outputs["status_text"])
        self.assertIn("时长未知", outputs["status_text"])


class FailureTests(_Base):
    def test_synthesis_failure_is_chinese_and_uploads_nothing(self) -> None:
        asset = self._asset()

        def _boom(text, work_dir, **kwargs):  # noqa: ANN001
            raise TtsFileError("edge-tts 合成第 1/2 段失败：网络不可达")

        with self.assertRaises(PdfReaderError) as ctx:
            read_from_params(
                {"asset_ref": DOC_REF.to_dict()},
                asset=asset,
                extract_fn=self._extract(),
                synthesize_fn=_boom,
            )
        self.assertIn("网络不可达", str(ctx.exception))
        asset.upload_file.assert_not_called()

    def test_upload_failure_is_chinese(self) -> None:
        with self.assertRaises(PdfReaderError) as ctx:
            read_from_params(
                {"asset_ref": DOC_REF.to_dict()},
                asset=self._asset(upload_error=AssetError("HTTP 500")),
                extract_fn=self._extract(),
                synthesize_fn=self._synth(),
            )
        self.assertIn("上传登记失败", str(ctx.exception))

    def test_voice_and_speed_are_forwarded(self) -> None:
        _msg, outputs = read_from_params(
            {
                "asset_ref": DOC_REF.to_dict(),
                "voice": "zh-CN-YunxiNeural",
                "speed": 1.5,
                "name": "说明书",
            },
            asset=self._asset(),
            extract_fn=self._extract(),
            synthesize_fn=self._synth(),
        )
        self.assertEqual(outputs["voice"], "zh-CN-YunxiNeural")
        self.assertEqual(self.synth_kwargs["speed"], 1.5)
        self.assertEqual(self.synth_kwargs["voice"], "zh-CN-YunxiNeural")


class ExecutorDispatchTests(_Base):
    def test_executor_dispatches_pdf_reader(self) -> None:
        from mac_edge.executor import _execute_capability

        with patch(
            "mac_edge.executor.pdf_reader_from_params",
            return_value=("ok", {"asset_ref": AUDIO_REF.to_dict()}),
        ) as fn:
            ok, _msg, outputs = _execute_capability(
                "pdf.reader",
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
            "mac_edge.executor.pdf_reader_from_params",
            side_effect=PdfReaderError("PDF 第 1–3 页没有可提取的文字（可能是扫描件）"),
        ):
            ok, msg, _outputs = _execute_capability(
                "pdf.reader", self._asset(), params={}, config=MagicMock()
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
        with patch("mac_edge.plugins.pdf_reader.pdf_reader_available", return_value=True):
            services = self._services()
        svc = next((s for s in services if s["service_id"] == "local.pdf.reader"), None)
        self.assertIsNotNone(svc)
        cap = svc["capabilities"][0]
        self.assertEqual(cap["capability_id"], "pdf.reader")
        self.assertEqual(cap["kind"], "action")
        self.assertEqual(svc["group"], "convert")
        self.assertIn("asset_ref", cap["input_schema"])
        self.assertIn("asset_ref", cap["output_schema"])
        for key in ("kind", "composition", "role", "planner_recognize",
                    "typical_triggers", "do_not_dispatch"):
            self.assertIn(key, cap)

    def test_skipped_without_dependencies(self) -> None:
        with patch("mac_edge.plugins.pdf_reader.pdf_reader_available", return_value=False):
            services = self._services()
        ids = [s["service_id"] for s in services]
        self.assertNotIn("local.pdf.reader", ids)


class RealExtractTests(_Base):
    """本机有 pymupdf 时，用真 PDF 走一遍默认抽字路径（不合成：假合成）。"""

    def setUp(self) -> None:
        super().setUp()
        from mac_edge.plugins.pdf_render import pymupdf_available

        if not pymupdf_available():
            self.skipTest("pymupdf not installed")

    def test_real_pdf_text_is_read(self) -> None:
        import pymupdf

        from mac_edge.plugins.pdf_render import pdf_page_count as real_page_count

        real_pdf = Path(self._tmp.name) / "real.pdf"
        doc = pymupdf.open()
        first = doc.new_page()
        first.insert_text((72, 100), "Hello PDF reader, page one.", fontsize=14)
        second = doc.new_page()
        second.insert_text((72, 100), "这是第二页的中文。", fontname="china-s", fontsize=14)
        doc.save(str(real_pdf))
        doc.close()

        asset = self._asset()
        asset.materialize_file.return_value = real_pdf
        with patch.object(pdf_reader, "pdf_page_count", side_effect=real_page_count):
            _msg, outputs = read_from_params(
                {"asset_ref": DOC_REF.to_dict()}, asset=asset, synthesize_fn=self._synth()
            )
        self.assertEqual(outputs["page_count"], 2)
        self.assertIn("Hello PDF reader", outputs["text_preview"])
        self.assertIn("page one", self.synth_text)
        self.assertIn("第二页", self.synth_text)

