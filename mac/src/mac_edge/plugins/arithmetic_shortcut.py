"""Deterministic arithmetic for math.calculate (no LLM)."""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any

class ArithmeticError(Exception):
    """Expression missing or not a supported pure arithmetic form."""


_CN_DIGIT = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "两": 2,
    "俩": 2,
}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_OP_CHARS = set("+-*/()")
_MATH_SYMBOL_MAP = (
    ("×", "*"),
    ("✕", "*"),
    ("⨯", "*"),
    ("·", "*"),
    ("÷", "/"),
)
_OP_CN = (
    ("除以", "/"),
    ("乘以", "*"),
    ("加", "+"),
    ("减", "-"),
    ("乘", "*"),
    ("除", "/"),
)
_QUESTION_SUFFIX = re.compile(
    r"(?:[，,。.!！？?\s]+|(?:等于|得|是)(?:几|多少|啥|什么)?[？?]?)+$"
)
_QUESTION_PREFIX = re.compile(r"^(?:请问|帮我|麻烦|算一下|计算|算算)\s*")
_NON_ARITH_MARKERS = (
    "笔顺",
    "笔画",
    "几画",
    "出图",
    "配图",
    "画一张",
    "投屏",
    "投到电视",
    "图片",
    "长什么样子",
    "怎么写",
)
_SAFE_BINOPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_SAFE_UNARYOPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _contains_non_arith_marker(query: str) -> bool:
    return any(m in query for m in _NON_ARITH_MARKERS)


def _cn_to_int(text: str) -> int | None:
    s = text.strip().replace("两", "二").replace("俩", "二")
    if not s:
        return None
    if re.fullmatch(r"\d+", s):
        return int(s)
    if not all(ch in _CN_DIGIT or ch in _CN_UNIT for ch in s):
        return None
    total = 0
    section = 0
    number = 0
    for ch in s:
        if ch in _CN_DIGIT:
            number = _CN_DIGIT[ch]
        elif ch == "十":
            section += (number or 1) * 10
            number = 0
        elif ch == "百":
            section += (number or 1) * 100
            number = 0
        elif ch == "千":
            section += (number or 1) * 1000
            number = 0
        elif ch == "万":
            section += number
            total += section * 10000
            section = 0
            number = 0
        else:
            return None
    return total + section + number


def _int_to_cn(n: int) -> str:
    if n == 0:
        return "零"
    if n < 0:
        return "负" + _int_to_cn(-n)
    if n < 10:
        return "零一二三四五六七八九"[n]
    if n < 20:
        return "十" + ("" if n == 10 else _int_to_cn(n - 10))
    if n < 100:
        tens, ones = divmod(n, 10)
        head = _int_to_cn(tens) + "十"
        return head if ones == 0 else head + _int_to_cn(ones)
    if n < 1000:
        hundreds, rem = divmod(n, 100)
        head = _int_to_cn(hundreds) + "百"
        if rem == 0:
            return head
        if rem < 10:
            return head + "零" + _int_to_cn(rem)
        return head + _int_to_cn(rem)
    if n < 10000:
        thousands, rem = divmod(n, 1000)
        head = _int_to_cn(thousands) + "千"
        if rem == 0:
            return head
        if rem < 100:
            return head + "零" + _int_to_cn(rem)
        return head + _int_to_cn(rem)
    return str(n)


def _normalize_display_expr(original: str, expr_ascii: str) -> str:
    core = _strip_question_wrapper(original).replace(" ", "")
    if re.search(r"[一二三四五六七八九十百千万两]", original):
        return core
    if any(op in original for op in ("加", "减", "乘", "除")):
        return core
    if any(sym in original for sym, _ in _MATH_SYMBOL_MAP):
        return core
    return expr_ascii.replace(" ", "")


def _strip_question_wrapper(query: str) -> str:
    q = query.strip()
    q = _QUESTION_PREFIX.sub("", q).strip()
    q = _QUESTION_SUFFIX.sub("", q).strip()
    return q


def _replace_cn_ops(text: str) -> str:
    out = text
    for src, dst in _MATH_SYMBOL_MAP:
        out = out.replace(src, dst)
    for src, dst in _OP_CN:
        out = out.replace(src, dst)
    return out


def _tokenize(expr: str) -> list[str] | None:
    tokens: list[str] = []
    buf: list[str] = []

    def flush_buf() -> bool:
        if not buf:
            return True
        raw = "".join(buf)
        buf.clear()
        if re.fullmatch(r"\d+", raw):
            tokens.append(raw)
            return True
        val = _cn_to_int(raw)
        if val is None:
            return False
        tokens.append(str(val))
        return True

    for ch in expr.replace(" ", ""):
        if ch in _OP_CHARS:
            if not flush_buf():
                return None
            tokens.append(ch)
        else:
            buf.append(ch)
    if not flush_buf():
        return None
    return tokens


def _safe_eval_expr(node: ast.expr) -> int | float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("unsupported constant")
        return node.value
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_BINOPS:
            raise ValueError("unsupported operator")
        left = _safe_eval_expr(node.left)
        right = _safe_eval_expr(node.right)
        if op_type in (ast.Div, ast.FloorDiv) and right == 0:
            raise ValueError("division by zero")
        return _SAFE_BINOPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_UNARYOPS:
            raise ValueError("unsupported unary operator")
        return _SAFE_UNARYOPS[op_type](_safe_eval_expr(node.operand))
    raise ValueError("unsupported expression")


def _eval_ascii_expr(expr_ascii: str) -> int | float:
    if not re.fullmatch(r"[\d+\-*/().\s]+", expr_ascii):
        raise ValueError("unsafe characters")
    tree = ast.parse(expr_ascii, mode="eval")
    return _safe_eval_expr(tree.body)


def _format_number(value: int | float, *, use_cn: bool) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and use_cn:
        return _int_to_cn(value)
    if isinstance(value, float):
        text = f"{value:.6g}"
        return text
    return str(value)


_MAX_POWER_EXP = 20

def _parse_scalar(raw: str) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+", s):
        return int(s)
    return _cn_to_int(s)


def _try_compute_power(q: str, core: str) -> tuple[str, str] | None:
    """Chinese power forms: 二的三次方、3的平方、二的立方."""
    compact = core.replace(" ", "")
    if "的" not in compact:
        return None
    base_part, _, rest = compact.partition("的")
    if not base_part or not rest:
        return None
    base = _parse_scalar(base_part)
    if base is None:
        return None
    if rest == "平方":
        exp = 2
    elif rest == "立方":
        exp = 3
    elif rest.endswith("次方"):
        exp = _parse_scalar(rest[:-2])
    elif rest.endswith("次幂"):
        exp = _parse_scalar(rest[:-2])
    else:
        return None
    if exp is None or exp < 0 or exp > _MAX_POWER_EXP:
        return None
    try:
        result = pow(base, exp)
    except (OverflowError, ValueError):
        return None
    if isinstance(result, float) and not result.is_integer():
        return None
    use_cn = bool(re.search(r"[一二三四五六七八九十百千万两]", q))
    result_text = _format_number(result, use_cn=use_cn)
    answer_text = f"{compact}等于{result_text}。"
    result_value = _format_number(result, use_cn=False)
    return answer_text, result_value


_SQRT_PATTERN = re.compile(
    r"^(?:根号(?:下)?|√)(?P<val>[\d一二三四五六七八九十百千万两]+)$"
)


def _try_compute_sqrt(q: str, core: str) -> tuple[str, str] | None:
    """Square root: 根号4、根号下四、√9."""
    compact = core.replace(" ", "")
    m = _SQRT_PATTERN.fullmatch(compact)
    if not m:
        return None
    n = _parse_scalar(m.group("val"))
    if n is None or n < 0:
        return None
    root = math.isqrt(n)
    result: int | float = root if root * root == n else math.sqrt(n)
    use_cn = bool(re.search(r"[一二三四五六七八九十百千万两]", q))
    result_text = _format_number(result, use_cn=use_cn)
    answer_text = f"{compact}等于{result_text}。"
    result_value = _format_number(result, use_cn=False)
    return answer_text, result_value


def _compute_arithmetic(text: str) -> tuple[str, str] | None:
    """Return (answer_text, result) when text is pure arithmetic, else None."""
    q = (text or "").strip()
    if not q or _contains_non_arith_marker(q):
        return None

    core = _strip_question_wrapper(q)
    if not core:
        return None

    powered = _try_compute_power(q, core)
    if powered is not None:
        return powered

    rooted = _try_compute_sqrt(q, core)
    if rooted is not None:
        return rooted

    normalized = _replace_cn_ops(core)
    if not re.search(r"[+\-*/]", normalized):
        return None

    tokens = _tokenize(normalized)
    if not tokens:
        return None
    expr_ascii = "".join(tokens)
    if not re.search(r"\d", expr_ascii):
        return None

    try:
        result = _eval_ascii_expr(expr_ascii)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError):
        return None

    use_cn = bool(re.search(r"[一二三四五六七八九十百千万两]", q))
    display = _normalize_display_expr(q, expr_ascii)
    result_text = _format_number(result, use_cn=use_cn)
    answer_text = f"{display}等于{result_text}。"
    result_value = _format_number(result, use_cn=False)
    return answer_text, result_value


def calculate(expression: str) -> dict[str, str]:
    """Evaluate a pure arithmetic expression. Raises ArithmeticError on failure."""
    expr = (expression or "").strip()
    if not expr:
        raise ArithmeticError("missing expression")
    computed = _compute_arithmetic(expr)
    if computed is None:
        raise ArithmeticError(f"无法计算：{expr}")
    answer_text, result = computed
    return {"answer_text": answer_text, "result": result}


def try_arithmetic_answer(query: str) -> str | None:
    """Legacy helper: answer_text only, or None when not arithmetic."""
    computed = _compute_arithmetic(query)
    return computed[0] if computed else None
