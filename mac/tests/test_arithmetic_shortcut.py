"""Tests for math.calculate AST evaluation."""

from __future__ import annotations

import unittest

from mac_edge.plugins.arithmetic_shortcut import (
    ArithmeticError,
    calculate,
    try_arithmetic_answer,
)


class ArithmeticShortcutTests(unittest.TestCase):
    def test_cn_one_plus_one(self) -> None:
        self.assertEqual(calculate("一加一等于几")["answer_text"], "一加一等于二。")
        self.assertEqual(calculate("一加一等于几")["result"], "2")

    def test_arabic_one_plus_one(self) -> None:
        self.assertEqual(calculate("1+1等于几")["answer_text"], "1+1等于2。")
        self.assertEqual(calculate("1+1等于几")["result"], "2")

    def test_bare_expression(self) -> None:
        out = calculate("十二加五")
        self.assertEqual(out["answer_text"], "十二加五等于十七。")
        self.assertEqual(out["result"], "17")

    def test_multiplication(self) -> None:
        self.assertEqual(
            calculate("3乘以5是多少")["answer_text"],
            "3乘以5等于15。",
        )

    def test_unicode_times_sign(self) -> None:
        self.assertEqual(calculate("3×5等于几")["answer_text"], "3×5等于15。")
        self.assertEqual(calculate("3×5等于几")["result"], "15")

    def test_power_cube_cn(self) -> None:
        self.assertEqual(calculate("二的三次方")["answer_text"], "二的三次方等于八。")
        self.assertEqual(calculate("二的三次方")["result"], "8")

    def test_power_square_arabic(self) -> None:
        self.assertEqual(calculate("3的平方等于几")["answer_text"], "3的平方等于9。")

    def test_power_cube_alias(self) -> None:
        self.assertEqual(calculate("二的立方")["answer_text"], "二的立方等于八。")

    def test_sqrt_arabic(self) -> None:
        self.assertEqual(calculate("根号4等于几")["answer_text"], "根号4等于2。")
        self.assertEqual(calculate("根号4等于几")["result"], "2")

    def test_sqrt_cn(self) -> None:
        self.assertEqual(calculate("根号下九")["answer_text"], "根号下九等于三。")

    def test_parentheses(self) -> None:
        self.assertEqual(
            calculate("(2+3)*4等于多少")["answer_text"],
            "(2+3)*4等于20。",
        )

    def test_missing_expression_fails(self) -> None:
        with self.assertRaises(ArithmeticError) as ctx:
            calculate("  ")
        self.assertIn("missing expression", str(ctx.exception))

    def test_unsupported_expression_fails(self) -> None:
        with self.assertRaises(ArithmeticError) as ctx:
            calculate("客厅适合看书吗")
        self.assertIn("无法计算", str(ctx.exception))

    def test_try_arithmetic_answer_none_for_non_arith(self) -> None:
        self.assertIsNone(try_arithmetic_answer("晋字一共几画"))
        self.assertIsNone(try_arithmetic_answer("1+1等于几，再画张图"))


if __name__ == "__main__":
    unittest.main()
