"""math.calculate evaluates locally; no LLM."""

from __future__ import annotations

import unittest

from mac_edge.plugins.math_calculate import (
    MathCalculateError,
    calculate_from_params,
    math_calculate,
)


class MathCalculateTests(unittest.TestCase):
    def test_outputs_required_fields(self) -> None:
        msg, outputs = calculate_from_params({"expression": "1+1等于几"})
        self.assertIn("answer_text", outputs)
        self.assertIn("result", outputs)
        self.assertEqual(outputs["answer_text"], "1+1等于2。")
        self.assertEqual(outputs["result"], "2")
        self.assertIn("math.calculate", msg)

    def test_cn_expression(self) -> None:
        outputs = math_calculate(expression="一加一")
        self.assertEqual(outputs["answer_text"], "一加一等于二。")
        self.assertEqual(outputs["result"], "2")

    def test_missing_expression_fails(self) -> None:
        with self.assertRaises(MathCalculateError) as ctx:
            calculate_from_params({})
        self.assertIn("expression", str(ctx.exception))

    def test_invalid_expression_fails(self) -> None:
        with self.assertRaises(MathCalculateError) as ctx:
            math_calculate(expression="大象加猫")
        self.assertIn("无法计算", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
