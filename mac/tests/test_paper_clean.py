"""paper_clean — Original 模式的听觉清洗规则（纯函数，逐条正则一个 case）。"""

from __future__ import annotations

import unittest

from mac_edge.plugins import paper_clean as pc
from mac_edge.plugins.paper_structure import PaperStructure, Section


class NumberTests(unittest.TestCase):
    def test_cn_number(self) -> None:
        self.assertEqual(pc.cn_number(1), "一")
        self.assertEqual(pc.cn_number(9), "九")
        self.assertEqual(pc.cn_number(10), "十")
        self.assertEqual(pc.cn_number(11), "十一")
        self.assertEqual(pc.cn_number(21), "二十一")
        self.assertEqual(pc.cn_number(99), "九十九")
        self.assertEqual(pc.cn_number(100), "100")
        self.assertEqual(pc.cn_number("x"), "x")


class CleanBodyTests(unittest.TestCase):
    def test_dehyphenation(self) -> None:
        self.assertEqual(pc.clean_body("We use the meth-\nod described here."), "We use the method described here.")

    def test_continuation_line_is_joined(self) -> None:
        self.assertEqual(pc.clean_body("we propose a new\nmethod for reading"), "we propose a new method for reading")

    def test_urls_and_emails_removed(self) -> None:
        out = pc.clean_body("See https://example.com/paper and mail me at a@b.com now.")
        self.assertNotIn("http", out)
        self.assertNotIn("@", out)
        self.assertIn("See", out)

    def test_bracket_citations_removed(self) -> None:
        out = pc.clean_body("As shown before [12], [3-5] and [7, 9].")
        self.assertNotIn("[", out)
        self.assertNotIn("12", out)

    def test_named_citations_removed(self) -> None:
        out = pc.clean_body("Prior work [Smith et al. 2020] did this.")
        self.assertNotIn("Smith", out)
        self.assertIn("Prior work", out)

    def test_page_number_and_arxiv_stamp_lines_removed(self) -> None:
        body = "Real sentence.\n12\narXiv:2401.00001v1 [cs.CL] 1 Jan 2024\nPreprint. Under review.\nAnother sentence."
        out = pc.clean_body(body)
        self.assertEqual(out, "Real sentence.\nAnother sentence.")

    def test_display_math_becomes_the_word_formula(self) -> None:
        out = pc.clean_body("We minimize $$\\mathcal{L} = \\sum_i x_i$$ here.")
        self.assertIn("公式", out)
        self.assertNotIn("$", out)

    def test_inline_math_keeps_variable_name(self) -> None:
        out = pc.clean_body("Let $x$ be the input and $y_i$ the label.")
        self.assertNotIn("$", out)
        self.assertIn("x", out)
        self.assertIn("y", out)

    def test_inline_latex_command_becomes_readable_word(self) -> None:
        out = pc.clean_body("We pick $\\alpha = 0.5$ as the rate.")
        self.assertIn("alpha = 0.5", out)
        self.assertNotIn("\\", out)

    def test_figure_table_equation_references_naturalized(self) -> None:
        out = pc.clean_body(
            "Fig. 2 shows it, Table 3 lists it, Eq. (4) proves it, Section 2.1 explains it.",
            lang="zh",
        )
        self.assertIn("图二", out)
        self.assertIn("表三", out)
        self.assertIn("公式四", out)
        self.assertIn("第 2.1 节", out)

    def test_references_follow_english_body(self) -> None:
        """英文正文里不再冒出「图一」：引用话术跟着正文语言走。"""
        out = pc.clean_body(
            "Fig. 2 shows it, Table 3 lists it, Eq. (4) proves it, Section 2.1 explains it.",
            lang="en",
        )
        self.assertIn("Figure 2", out)
        self.assertIn("Table 3", out)
        self.assertIn("Equation 4", out)
        self.assertIn("Section 2.1", out)
        self.assertNotIn("图", out)
        self.assertNotIn("表", out)

    def test_whitespace_and_punctuation_tidied(self) -> None:
        out = pc.clean_body("Too   many    spaces , and , , dup punct .")
        self.assertNotIn("  ", out)
        self.assertNotIn(" ,", out)
        self.assertNotIn(", ,", out)

    def test_clean_body_is_idempotent(self) -> None:
        body = "We use meth-\nod [3] $$x$$ from https://a.b/c.\n12\nFinal line."
        once = pc.clean_body(body)
        self.assertEqual(pc.clean_body(once), once)

    def test_red_line_numbers_are_kept(self) -> None:
        """Original 不删实验结果：数字必须原样保留。"""
        out = pc.clean_body("Our model reaches 92.5 accuracy on 8 datasets.")
        self.assertIn("92.5", out)
        self.assertIn("8 datasets", out)


class HeadingTests(unittest.TestCase):
    def test_speakable_heading(self) -> None:
        self.assertEqual(pc.speakable_heading("3.2 Method"), "下面是 3.2 Method 部分。")
        self.assertEqual(pc.speakable_heading("  Introduction. "), "下面是 Introduction 部分。")
        self.assertEqual(pc.speakable_heading(""), "")

    def test_speakable_heading_english(self) -> None:
        self.assertEqual(pc.speakable_heading("3.2 Method", lang="en"), "Next, the 3.2 Method section.")
        self.assertEqual(pc.speakable_heading("Abstract", lang="en"), "Next, the Abstract section.")
        self.assertEqual(pc.speakable_heading("", lang="en"), "")


class ScriptTests(unittest.TestCase):
    def _structure(self) -> PaperStructure:
        return PaperStructure(
            title="Listening to Papers",
            pages=4,
            sections=[
                Section(type="abstract", heading="Abstract", paragraphs=["We listen. See [4]."], start_page=1, end_page=1),
                Section(type="method", heading="2 Method", paragraphs=["We read Fig. 1 aloud."], start_page=2, end_page=3),
            ],
        )

    def test_build_pieces_and_assemble(self) -> None:
        prefix, pieces = pc.build_original_pieces(self._structure())
        # 正文是英文 → 脚手架也走英文（否则英文里夹「下面是…部分。」）
        self.assertEqual(prefix, "Paper title: Listening to Papers.")
        self.assertEqual([p["type"] for p in pieces], ["abstract", "method"])
        self.assertEqual(pieces[0]["text"], "Next, the Abstract section.\nWe listen. See.")
        script = pc.assemble_script(prefix, pieces)
        self.assertTrue(script.startswith(prefix))
        self.assertIn("Next, the 2 Method section.", script)
        self.assertIn("Figure 1", script)

    def test_build_pieces_chinese_scaffolding(self) -> None:
        """中文论文仍走中文脚手架（显式 lang / 正文判定都认）。"""
        structure = PaperStructure(
            title="听读论文",
            pages=2,
            sections=[Section(type="abstract", heading="摘要", paragraphs=["我们听读。见图表。"], start_page=1, end_page=1)],
        )
        prefix, pieces = pc.build_original_pieces(structure)
        self.assertEqual(prefix, "论文标题：听读论文。")
        self.assertEqual(pieces[0]["text"], "下面是 摘要 部分。\n我们听读。见图表。")
        # 显式给英文正文指定中文 → 中文脚手架（用户说了算）
        zh_prefix, zh_pieces = pc.build_original_pieces(self._structure(), script_lang="zh")
        self.assertEqual(zh_prefix, "论文标题：Listening to Papers。")
        self.assertIn("下面是 Abstract 部分。", zh_pieces[0]["text"])

    def test_assemble_without_title(self) -> None:
        _prefix, pieces = pc.build_original_pieces(
            PaperStructure(title=None, pages=1, sections=[Section(type="full", heading="", paragraphs=["Body."])])
        )
        self.assertEqual(pc.assemble_script("", pieces), "Body.")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
