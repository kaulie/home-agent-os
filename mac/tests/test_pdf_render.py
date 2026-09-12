"""pdf_render — 共享 PDF 渲染底层：DPI 解析、页数读取、真实渲染（pymupdf 可用时）。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.plugins.pdf_render import (
    center_clip_for_zoom,
    render_page_region_png,
    DEFAULT_RENDER_DPI,
    PdfRenderError,
    clamp_dpi,
    pdf_page_count,
    pymupdf_available,
    render_dpi,
    render_page_png,
)


class DpiTests(unittest.TestCase):
    def test_default(self) -> None:
        with patch.dict(os.environ, {"MAC_EDGE_PDF_DISPLAY_DPI": ""}, clear=False):
            self.assertEqual(render_dpi(), DEFAULT_RENDER_DPI)

    def test_env_override_and_clamp(self) -> None:
        with patch.dict(os.environ, {"MAC_EDGE_PDF_DISPLAY_DPI": "300"}, clear=False):
            self.assertEqual(render_dpi(), 300)
        with patch.dict(os.environ, {"MAC_EDGE_PDF_DISPLAY_DPI": "9999"}, clear=False):
            self.assertEqual(render_dpi(), 400)
        with patch.dict(os.environ, {"MAC_EDGE_PDF_DISPLAY_DPI": "10"}, clear=False):
            self.assertEqual(render_dpi(), 72)
        with patch.dict(os.environ, {"MAC_EDGE_PDF_DISPLAY_DPI": "abc"}, clear=False):
            self.assertEqual(render_dpi(), DEFAULT_RENDER_DPI)

    def test_clamp_dpi_param(self) -> None:
        with patch.dict(os.environ, {"MAC_EDGE_PDF_DISPLAY_DPI": ""}, clear=False):
            self.assertEqual(clamp_dpi(None), DEFAULT_RENDER_DPI)
            self.assertEqual(clamp_dpi(""), DEFAULT_RENDER_DPI)
        self.assertEqual(clamp_dpi("150"), 150)
        self.assertEqual(clamp_dpi("10000"), 400)
        with self.assertRaises(PdfRenderError):
            clamp_dpi("高清")


class PageCountTests(unittest.TestCase):
    def test_missing_file_fails(self) -> None:
        if not pymupdf_available():
            self.skipTest("pymupdf not installed")
        with self.assertRaises(PdfRenderError):
            pdf_page_count(Path("/nonexistent/none.pdf"))

    def test_garbage_file_fails(self) -> None:
        if not pymupdf_available():
            self.skipTest("pymupdf not installed")
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.pdf"
            bad.write_bytes(b"not a pdf at all")
            with self.assertRaises(PdfRenderError):
                pdf_page_count(bad)


class RealRenderTests(unittest.TestCase):
    """本机有 pymupdf 时用 pypdf 造 fixture 真实渲染。"""

    def setUp(self) -> None:
        if not pymupdf_available():
            self.skipTest("pymupdf not installed")

    def _build_pdf(self, pages: int, dst: Path) -> Path:
        from pypdf import PdfWriter

        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=595, height=842)
        with open(dst, "wb") as fh:
            writer.write(fh)
        return dst

    def test_page_count_and_render(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pdf = self._build_pdf(3, Path(td) / "in.pdf")
            self.assertEqual(pdf_page_count(pdf), 3)
            out = Path(td) / "p2.png"
            produced = render_page_png(pdf, 1, dpi=150, out_path=out)
            self.assertEqual(produced, out)
            data = out.read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG"))
            # 150 DPI 的 A4 竖版约 1240×1754。
            self.assertGreater(len(data), 1000)

    def test_render_out_of_range_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pdf = self._build_pdf(1, Path(td) / "in.pdf")
            with self.assertRaises(PdfRenderError) as ctx:
                render_page_png(pdf, 5, dpi=150, out_path=Path(td) / "x.png")
            self.assertIn("越界", str(ctx.exception))

    def test_region_render_zoom_keeps_output_pixels(self) -> None:
        """zoom=2 中心区域 + dpi×2 → 输出像素尺寸与整页一致（放大不糊的关键）。"""
        with tempfile.TemporaryDirectory() as td:
            pdf = self._build_pdf(1, Path(td) / "in.pdf")
            full = Path(td) / "full.png"
            render_page_png(pdf, 0, dpi=150, out_path=full)
            zoomed = Path(td) / "z2.png"
            render_page_region_png(pdf, 0, zoom=2.0, dpi=300, out_path=zoomed)
            self.assertTrue(zoomed.read_bytes().startswith(b"\x89PNG"))

            import struct

            def _png_size(p: Path) -> tuple[int, int]:
                data = p.read_bytes()
                w, h = struct.unpack(">II", data[16:24])
                return w, h

            fw, fh = _png_size(full)
            zw, zh = _png_size(zoomed)
            # 裁剪矩形舍入允许 ≤2px 差
            self.assertLessEqual(abs(fw - zw), 2)
            self.assertLessEqual(abs(fh - zh), 2)

    def test_center_clip_math(self) -> None:
        class _Rect:
            x0, y0, x1, y1 = 0.0, 0.0, 400.0, 200.0
            width, height = 400.0, 200.0

        clip = center_clip_for_zoom(_Rect(), 2.0)
        self.assertEqual(clip, (100.0, 50.0, 300.0, 150.0))
        # zoom=1 → 整页
        self.assertEqual(center_clip_for_zoom(_Rect(), 1.0), (0.0, 0.0, 400.0, 200.0))


if __name__ == "__main__":
    unittest.main()
