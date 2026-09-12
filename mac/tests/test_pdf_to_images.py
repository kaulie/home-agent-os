"""pdf.to_images — PDF 每页渲染成高清图片（独立可复用能力）。

风格对齐 test_pdf_display.py / test_pdf_rotate.py：mock CapAsset + 假渲染，
断言页范围解析、asset_refs 顺序、上传次数、中文失败与广告门控。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.asset.types import AssetError, AssetRef
from mac_edge.plugins import pdf_to_images
from mac_edge.plugins.pdf_to_images import (
    MAX_RENDER_PAGES,
    PdfToImagesError,
    images_from_params,
    parse_page_range,
)
from mac_edge.services import default_services

DOC_REF = AssetRef(asset_id="doc_9", type="document", mime_type="application/pdf")


def _fake_render(pdf_path: Path, page_index: int, dpi: int, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([page_index % 256]))
    return out_path


def _uploads(count: int) -> list[AssetRef]:
    return [
        AssetRef(asset_id=f"asset_p{i}", type="image", mime_type="image/png")
        for i in range(1, count + 1)
    ]


def _asset_for(pdf_path: Path, *, pages: int = 3) -> MagicMock:
    asset = MagicMock()
    asset.require_ref.return_value = DOC_REF
    asset.materialize_file.return_value = pdf_path
    asset.upload_file.side_effect = _uploads(pages)
    return asset


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = {"MAC_EDGE_DATA_DIR": self._tmp.name, "MAC_EDGE_PDF_DISPLAY_DPI": ""}
        self._env = patch.dict(os.environ, env, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.pdf_path = Path(self._tmp.name) / "in.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4 fake")
        # 不接真 pymupdf：页数固定 3，渲染用假实现。
        self._pages = patch.object(pdf_to_images, "pdf_page_count", return_value=3)
        self._pages.start()
        self.addCleanup(self._pages.stop)


class PageRangeTests(unittest.TestCase):
    def test_defaults_to_whole_doc(self) -> None:
        self.assertEqual(parse_page_range(None, None, page_count=10), (1, 10))

    def test_explicit_range(self) -> None:
        self.assertEqual(parse_page_range("3", "5", page_count=10), (3, 5))

    def test_range_clamped_to_bounds(self) -> None:
        self.assertEqual(parse_page_range("1", "99", page_count=10), (1, 10))
        self.assertEqual(parse_page_range("7", "99", page_count=10), (7, 10))

    def test_invalid_inputs_fail(self) -> None:
        with self.assertRaises(PdfToImagesError):
            parse_page_range("abc", None, page_count=10)
        with self.assertRaises(PdfToImagesError):
            parse_page_range("0", None, page_count=10)
        with self.assertRaises(PdfToImagesError):
            parse_page_range("5", "3", page_count=10)

    def test_over_limit_fails(self) -> None:
        with self.assertRaises(PdfToImagesError) as ctx:
            parse_page_range(None, None, page_count=MAX_RENDER_PAGES + 50)
        self.assertIn("最多渲染", str(ctx.exception))


class ToImagesTests(_Base):
    def test_whole_doc_renders_all_pages_in_order(self) -> None:
        asset = _asset_for(self.pdf_path, pages=3)
        msg, outputs = images_from_params(
            {"asset_ref": DOC_REF.to_dict()}, asset=asset, render_fn=_fake_render
        )
        self.assertEqual(outputs["page_count"], 3)
        self.assertEqual(outputs["rendered_pages"], 3)
        refs = outputs["asset_refs"]
        self.assertEqual([r["asset_id"] for r in refs], ["asset_p1", "asset_p2", "asset_p3"])
        self.assertEqual(asset.upload_file.call_count, 3)
        # 上传文件名带页码，顺序=页码。
        names = [c.kwargs["filename"] for c in asset.upload_file.call_args_list]
        self.assertEqual(names, ["pdf-doc_9-p1.png", "pdf-doc_9-p2.png", "pdf-doc_9-p3.png"])
        self.assertIn("pdf.to_images", msg)
        self.assertIn("200", outputs["status_text"])  # 默认 DPI

    def test_page_range_subset(self) -> None:
        asset = _asset_for(self.pdf_path, pages=2)
        _msg, outputs = images_from_params(
            {"asset_ref": DOC_REF.to_dict(), "page_start": 2, "page_end": 3},
            asset=asset,
            render_fn=_fake_render,
        )
        self.assertEqual(outputs["rendered_pages"], 2)
        self.assertEqual(outputs["page_count"], 3)
        self.assertEqual(asset.upload_file.call_count, 2)

    def test_custom_dpi_and_name(self) -> None:
        asset = _asset_for(self.pdf_path, pages=1)
        _msg, outputs = images_from_params(
            {"asset_ref": DOC_REF.to_dict(), "page_start": 1, "page_end": 1,
             "dpi": 300, "name": "绘本"},
            asset=asset,
            render_fn=_fake_render,
        )
        name = asset.upload_file.call_args.kwargs["filename"]
        self.assertEqual(name, "绘本-p1.png")
        self.assertIn("300", outputs["status_text"])

    def test_rejects_non_document(self) -> None:
        asset = _asset_for(self.pdf_path)
        asset.require_ref.return_value = AssetRef(asset_id="img_1", type="image")
        with self.assertRaises(PdfToImagesError) as ctx:
            images_from_params(
                {"asset_ref": {"asset_id": "img_1", "type": "image"}},
                asset=asset,
                render_fn=_fake_render,
            )
        self.assertIn("document", str(ctx.exception))

    def test_missing_asset_ref_fails(self) -> None:
        asset = _asset_for(self.pdf_path)
        asset.require_ref.side_effect = AssetError("missing or invalid asset_ref")
        with self.assertRaises(PdfToImagesError):
            images_from_params({}, asset=asset, render_fn=_fake_render)

    def test_upload_failure_is_chinese(self) -> None:
        asset = _asset_for(self.pdf_path)
        asset.upload_file.side_effect = AssetError("HTTP 500")
        with self.assertRaises(PdfToImagesError) as ctx:
            images_from_params(
                {"asset_ref": DOC_REF.to_dict()}, asset=asset, render_fn=_fake_render
            )
        self.assertIn("上传登记失败", str(ctx.exception))


class RealRenderTests(_Base):
    """本机有 pymupdf 时真实渲染一遍（pypdf 造 fixture）。"""

    def setUp(self) -> None:
        super().setUp()
        from mac_edge.plugins.pdf_render import pymupdf_available

        if not pymupdf_available():
            self.skipTest("pymupdf not installed")

    def test_real_render_two_pages(self) -> None:
        from pypdf import PdfWriter

        real_pdf = Path(self._tmp.name) / "real.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=842, height=595)
        with open(real_pdf, "wb") as fh:
            writer.write(fh)

        self._pages.stop()
        try:
            asset = _asset_for(real_pdf, pages=2)
            _msg, outputs = images_from_params({"asset_ref": DOC_REF.to_dict()}, asset=asset)
            self.assertEqual(outputs["page_count"], 2)
            self.assertEqual(outputs["rendered_pages"], 2)
            self.assertEqual(len(outputs["asset_refs"]), 2)
            # 真实渲染产物已写到工作目录。
            work = Path(self._tmp.name) / "pdf-to-images" / "doc_9"
            self.assertTrue((work / "page-1.png").is_file())
            self.assertTrue(
                (work / "page-1.png").read_bytes().startswith(b"\x89PNG")
            )
        finally:
            self._pages.start()


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

    def test_advertised_when_pymupdf_available(self) -> None:
        with patch("mac_edge.plugins.pdf_render.pymupdf_available", return_value=True):
            services = self._services()
        svc = next((s for s in services if s["service_id"] == "local.pdf.images"), None)
        self.assertIsNotNone(svc)
        cap = svc["capabilities"][0]
        self.assertEqual(cap["capability_id"], "pdf.to_images")
        self.assertEqual(cap["group"] if "group" in cap else svc["group"], "convert")
        self.assertIn("asset_ref", cap["input_schema"])
        self.assertIn("asset_refs", cap["output_schema"])
        for key in ("kind", "composition", "role", "planner_recognize",
                    "typical_triggers", "do_not_dispatch"):
            self.assertIn(key, cap)

    def test_skipped_without_pymupdf(self) -> None:
        with patch("mac_edge.plugins.pdf_render.pymupdf_available", return_value=False):
            services = self._services()
        ids = [s["service_id"] for s in services]
        self.assertNotIn("local.pdf.images", ids)


class ExecutorDispatchTests(_Base):
    def test_executor_dispatches_pdf_to_images(self) -> None:
        from mac_edge.executor import _execute_capability

        asset = _asset_for(self.pdf_path)
        with patch(
            "mac_edge.executor.pdf_to_images_from_params",
            return_value=("ok", {"asset_refs": [], "rendered_pages": 0}),
        ) as fn:
            ok, _msg, outputs = _execute_capability(
                "pdf.to_images", asset, params={"asset_ref": DOC_REF.to_dict()},
                config=MagicMock(),
            )
        self.assertTrue(ok)
        fn.assert_called_once()

    def test_executor_surfaces_plugin_failure(self) -> None:
        from mac_edge.executor import _execute_capability

        asset = _asset_for(self.pdf_path)
        with patch(
            "mac_edge.executor.pdf_to_images_from_params",
            side_effect=PdfToImagesError("该 PDF 已加密，无法渲染"),
        ):
            ok, msg, _outputs = _execute_capability(
                "pdf.to_images", asset, params={}, config=MagicMock()
            )
        self.assertFalse(ok)
        self.assertIn("已加密", msg)


if __name__ == "__main__":
    unittest.main()
