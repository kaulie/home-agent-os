"""Mac Edge capability: math.calculate — deterministic arithmetic, no LLM.

Planner routing: see plugins/math-calculate/capability.md and heartbeat
description (能/不能). Unsupported forms must go to query.content, not here.
"""

from __future__ import annotations

import logging
from typing import Any

from mac_edge.plugins.arithmetic_shortcut import ArithmeticError, calculate

log = logging.getLogger("mac_edge.math_calculate")


class MathCalculateError(Exception):
    pass


def math_calculate(*, expression: str) -> dict[str, str]:
    """Evaluate a pure arithmetic expression. Never calls an LLM."""
    try:
        return calculate(expression)
    except ArithmeticError as e:
        raise MathCalculateError(str(e)) from e


def calculate_from_params(
    params: dict[str, Any] | None = None,
) -> tuple[str, dict[str, str]]:
    raw = params if isinstance(params, dict) else {}
    expr = raw.get("expression")
    expr_s = str(expr).strip() if expr is not None else ""
    if not expr_s:
        raise MathCalculateError("math.calculate 缺少必填 expression")
    outputs = math_calculate(expression=expr_s)
    msg = f"math.calculate {outputs['answer_text'][:80]}"
    log.info(
        "math.calculate expression=%r result=%s",
        expr_s[:80],
        outputs.get("result"),
    )
    return msg, outputs
