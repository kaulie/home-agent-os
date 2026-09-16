"""paper_structure — PDF → PaperStructure（双栏 / 页眉页码 / 章节切分 / References）。

不碰真 PDF：直接喂合成 ``PageBlocks``（``structure_from_pages`` 是纯函数），
只对 ``extract_structure`` 的缺依赖路径做 patch。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from mac_edge.plugins import paper_structure as ps
from mac_edge.plugins.pdf_render import PdfRenderError


def _block(
    text: str,
    *,
    x0: float = 50.0,
    x1: float = 280.0,
    y0: float = 100.0,
    y1: float | None = None,
    size: float = 10.0,
    bold: bool = False,
) -> ps.Block:
    return ps.Block(
        text=text,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y0 + 20.0 if y1 is None else y1,
        size=size,
        bold=bold,
    )


def _page(
    no: int, blocks: list[ps.Block], *, width: float = 600.0, height: float = 800.0
) -> ps.PageBlocks:
    return ps.PageBlocks(page=no, width=width, height=height, blocks=blocks)


def _right(text: str, *, y0: float, size: float = 10.0) -> ps.Block:
    return _block(text, x0=320.0, x1=550.0, y0=y0, size=size)


class TwoColumnTests(unittest.TestCase):
    def test_two_column_reading_order_is_left_then_right(self) -> None:
        blocks = [
            _block("1 Introduction", y0=90.0, size=12.0),
            _block("Left one.", y0=130.0),
            _right("Right one.", y0=140.0),
            _block("Left two.", y0=200.0),
            _right("Right two.", y0=210.0),
            _block("Left three.", y0=270.0),
            _right("Right three.", y0=280.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=1, detect_title=False)
        self.assertEqual(len(structure.sections), 1)
        self.assertEqual(structure.sections[0].type, "introduction")
        self.assertEqual(
            structure.sections[0].paragraphs,
            [
                "Left one.",
                "Left two.",
                "Left three.",
                "Right one.",
                "Right two.",
                "Right three.",
            ],
        )

    def test_single_column_keeps_y_order(self) -> None:
        blocks = [
            _block("Abstract", y0=90.0, size=12.0, x1=560.0),
            _block("First sentence.", y0=140.0, x1=560.0),
            _block("Second sentence.", y0=200.0, x1=560.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=1, detect_title=False)
        self.assertEqual(structure.sections[0].paragraphs, ["First sentence.", "Second sentence."])


class MarginCleanupTests(unittest.TestCase):
    def test_page_number_dropped_from_footer(self) -> None:
        blocks = [
            _block("Abstract", y0=90.0, size=12.0),
            _block("Some body text.", y0=140.0),
            _block("12", y0=780.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=1, detect_title=False)
        self.assertEqual(structure.sections[0].paragraphs, ["Some body text."])

    def test_repeated_running_header_dropped(self) -> None:
        header = (
            "Proceedings of the 41st International Conference on Machine Learning, Vienna"
        )  # > 60 字符：只有跨页重复才会被去掉
        pages = [
            _page(
                no,
                [
                    _block(header, y0=10.0, y1=30.0),
                    _block(f"Body of page {no}.", y0=200.0),
                ],
            )
            for no in (1, 2, 3)
        ]
        structure = ps.structure_from_pages(pages, total_pages=3, detect_title=False)
        flat = [p for s in structure.sections for p in s.paragraphs]
        self.assertEqual(flat, ["Body of page 1.", "Body of page 2.", "Body of page 3."])
        self.assertNotIn(header, flat)


class SectionSplitTests(unittest.TestCase):
    def test_references_truncates_everything_after(self) -> None:
        blocks = [
            _block("Abstract", y0=90.0, size=12.0),
            _block("We study listening.", y0=130.0),
            _block("1 Introduction", y0=200.0, size=12.0),
            _block("Papers are long.", y0=240.0),
            _block("References", y0=330.0, size=12.0),
            _block("[1] Smith. A paper. 2020.", y0=370.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=1, detect_title=False)
        self.assertTrue(structure.references_dropped)
        self.assertEqual([s.type for s in structure.sections], ["abstract", "introduction"])
        self.assertNotIn("[1] Smith. A paper. 2020.", structure.sections[1].paragraphs)

    def test_caption_recorded_but_not_read(self) -> None:
        blocks = [
            _block("1 Introduction", y0=90.0, size=12.0),
            _block("Body sentence.", y0=130.0),
            _block("Figure 2: The overall architecture of our system.", y0=220.0, size=8.0),
            _block("Table 1: Results on the benchmark.", y0=300.0, size=8.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=1, detect_title=False)
        self.assertEqual(structure.sections[0].paragraphs, ["Body sentence."])
        self.assertEqual([c.kind for c in structure.captions], ["figure", "table"])
        self.assertEqual([c.page for c in structure.captions], [1, 1])

    def test_table_reference_sentence_is_not_treated_as_caption(self) -> None:
        """正文句「Table 3 lists … on 8 datasets」必须留下（数字是红线）。"""
        blocks = [
            _block("1 Introduction", y0=90.0, size=12.0),
            _block("Table 3 lists the results on 8 datasets.", y0=130.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=1, detect_title=False)
        self.assertEqual(structure.captions, [])
        self.assertEqual(
            structure.sections[0].paragraphs, ["Table 3 lists the results on 8 datasets."]
        )

    def test_missing_headings_falls_back_to_single_full_section(self) -> None:
        blocks = [
            _block("A plain paragraph without any heading.", y0=140.0),
            _block("Another plain paragraph.", y0=200.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=1, detect_title=False)
        self.assertEqual(len(structure.sections), 1)
        self.assertEqual(structure.sections[0].type, "full")
        self.assertEqual(len(structure.sections[0].paragraphs), 2)

    def test_heading_types_cover_numbered_and_caps(self) -> None:
        blocks = [
            _block("3.2 Experimental Setup", y0=90.0, size=12.0),
            _block("We use 8 GPUs.", y0=130.0),
            _block("IV. CONCLUSION", y0=220.0, size=12.0),
            _block("We conclude.", y0=260.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=1, detect_title=False)
        self.assertEqual([s.type for s in structure.sections], ["experiment", "conclusion"])
        self.assertEqual(structure.sections[0].heading, "3.2 Experimental Setup")


class MetaTests(unittest.TestCase):
    def test_title_detected_from_largest_first_block(self) -> None:
        blocks = [
            _block("Listening to Papers End-to-End", y0=60.0, size=20.0, x1=560.0),
            _block("Ada Lovelace, Alan Turing", y0=110.0, size=11.0, x1=560.0),
            _block("Abstract", y0=180.0, size=12.0, x1=560.0),
            _block("We propose a reader.", y0=220.0, size=10.0, x1=560.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=1)
        self.assertEqual(structure.title, "Listening to Papers End-to-End")
        self.assertEqual([s.type for s in structure.sections], ["front", "abstract"])

    def test_title_not_repeated_in_front_section(self) -> None:
        blocks = [
            _block("Listening to Papers End-to-End", y0=60.0, size=20.0, x1=560.0),
            _block("Ada Lovelace, Alan Turing", y0=110.0, size=11.0, x1=560.0),
            _block("Abstract", y0=180.0, size=12.0, x1=560.0),
            _block("We propose a reader.", y0=220.0, size=10.0, x1=560.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=1)
        front = next(s for s in structure.sections if s.type == "front")
        self.assertEqual(front.paragraphs, ["Ada Lovelace, Alan Turing"])

    def test_empty_pages_report_warning_and_no_chars(self) -> None:
        structure = ps.structure_from_pages([_page(1, [])], total_pages=1, detect_title=False)
        self.assertEqual(structure.chars, 0)
        self.assertEqual(structure.sections, [])
        self.assertTrue(structure.warnings)

    def test_meta_stats(self) -> None:
        blocks = [
            _block("1 Introduction", y0=90.0, size=12.0),
            _block("Body.", y0=130.0),
            _block("Figure 1: Demo.", y0=200.0, size=8.0),
        ]
        structure = ps.structure_from_pages([_page(1, blocks)], total_pages=2, detect_title=False)
        meta = structure.to_meta()
        self.assertEqual(meta["pages"], 2)
        self.assertEqual(meta["sections"], 1)
        self.assertEqual(meta["chars"], len("Body."))
        self.assertEqual(meta["figures"], 1)
        self.assertEqual(meta["tables"], 0)

    def test_extract_structure_missing_dependency(self) -> None:
        with patch.object(ps, "_fitz", side_effect=PdfRenderError("本机未安装 PyMuPDF")):
            with self.assertRaises(ps.PaperStructureError) as ctx:
                ps.extract_structure("/tmp/none.pdf")
        self.assertIn("PyMuPDF", str(ctx.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

