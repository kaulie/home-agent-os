"""pdf_render — 共享 PDF 渲染底层：DPI 解析、页数读取、真实渲染（pymupdf 可用时）。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.plugins.pdf_render import (
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


if __name__ == "__main__":
    unittest.main()
