"""Intent-scoped variable context (same model as iOS RuntimeContext / ParamResolver).

- Publish only keys listed in step `output_constrict` with `data_dest: "context"`.
- Resolve `$name` / `${name}` — whole-value or inline inside strings (e.g. speak text).
- Nested paths into JSON context values: `$lighting.whole`.
- Legacy: `$perception_json.summary` → `$summary` (flat vision outputs).
"""

from __future__ import annotations

import json
import re
from typing import Any

# Whole-value (legacy) and inline scans — allow dotted paths into JSON bags.
_INLINE_VAR = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_.]*)\}|\$([A-Za-z_][A-Za-z0-9_.]*)"
)


class RuntimeContext:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        k = (key or "").strip()
        if not k:
            return None
        v = (self._values.get(k) or "").strip()
        return v or None

    def snapshot(self) -> dict[str, str]:
        return dict(self._values)

    def load(self, values: dict[str, Any] | None) -> None:
        """Hydrate from Brain `ctx_param`."""
        if not isinstance(values, dict):
            return
        for k, v in values.items():
            key = str(k).strip()
            if not key or v is None:
                continue
            text = _context_text(v)
            if not text or text.startswith("$"):
                continue
            self._values[key] = text

    def publish(
        self,
        outputs: dict[str, Any] | None,
        constrict: dict[str, Any] | None,
    ) -> list[str]:
        """Register outputs into context per output_constrict data_dest=context."""
        if not isinstance(outputs, dict) or not isinstance(constrict, dict):
            return []
        if not outputs or not constrict:
            return []
        published: list[str] = []
        for key, meta in constrict.items():
            if not _publishes_to_context(meta):
                continue
            k = str(key).strip()
            if not k:
                continue
            raw = outputs.get(k)
            if raw is None:
                continue
            value = _context_text(raw)
            if not value or value.startswith("$"):
                continue
            self._values[k] = value
            published.append(k)
        return published


def _context_text(raw: Any) -> str:
    """String form for context: JSON for objects/arrays so `$presentation.image_url` hydrates."""
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False)
    return str(raw).strip()


def _publishes_to_context(meta: Any) -> bool:
    if not isinstance(meta, dict):
        return False
    dest = str(meta.get("data_dest") or "").strip().lower()
    return dest == "context"


def _camel_to_snake(name: str) -> str:
    """photoURL → photo_url; photo_url unchanged."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _json_path_get(root_text: str, path: list[str]) -> str | None:
    """Walk dotted path into a JSON object/array string; return stringified leaf."""
    try:
        cur: Any = json.loads(root_text)
    except json.JSONDecodeError:
        return None
    for part in path:
        if isinstance(cur, dict):
            if part not in cur:
                snake = _camel_to_snake(part)
                if snake in cur:
                    cur = cur[snake]
                else:
                    return None
            else:
                cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    if cur is None:
        return None
    if isinstance(cur, str):
        return cur.strip() or None
    if isinstance(cur, (dict, list)):
        return json.dumps(cur, ensure_ascii=False)
    return str(cur).strip() or None


def lookup_context(context: RuntimeContext, name: str) -> str | None:
    """Exact key, dotted JSON path, camelCase→snake_case, legacy perception_json."""
    # Legacy: $perception_json.summary → flat $summary / $lighting.whole
    if name == "perception_json" or name.startswith("perception_json."):
        rest = name[len("perception_json") :].lstrip(".")
        if not rest:
            return None
        return lookup_context(context, rest)

    resolved = context.get(name)
    if resolved is not None:
        return resolved

    # $lighting.whole / $people.0.id
    if "." in name:
        root, *rest = name.split(".")
        if not rest:
            return None
        root_val = context.get(root)
        if root_val is None:
            snake_root = _camel_to_snake(root)
            if snake_root != root:
                root_val = context.get(snake_root)
        if root_val is None:
            return None
        return _json_path_get(root_val, rest)

    snake = _camel_to_snake(name)
    if snake != name:
        resolved = context.get(snake)
        if resolved is not None:
            return resolved
    return None


def resolve_value(raw: str, context: RuntimeContext) -> str:
    value = raw or ""
    if "{{" in value or "}}" in value:
        raise ValueError(f"unsupported param template (use $var): {value}")
    if not _INLINE_VAR.search(value):
        return raw

    parts: list[str] = []
    last = 0
    for m in _INLINE_VAR.finditer(value):
        parts.append(value[last : m.start()])
        name = m.group(1) or m.group(2) or ""
        resolved = lookup_context(context, name)
        if resolved is None:
            raise ValueError(f"unresolved context variable ${name}")
        parts.append(resolved)
        last = m.end()
    parts.append(value[last:])
    return "".join(parts)


def resolve_params(params: dict[str, str], context: RuntimeContext) -> dict[str, str]:
    return {k: resolve_value(v, context) for k, v in params.items()}


def unresolved_var_name(exc: BaseException) -> str | None:
    """Parse `unresolved context variable $foo` from resolve_value errors."""
    text = str(exc or "")
    marker = "unresolved context variable $"
    if marker not in text:
        return None
    name = text.split(marker, 1)[1].strip()
    return name or None


def output_constrict_of(step: dict[str, Any]) -> dict[str, Any]:
    raw = step.get("output_constrict") or {}
    return raw if isinstance(raw, dict) else {}


def input_params_of(step: dict[str, Any]) -> dict[str, str]:
    """Flatten step fields + input_constrict into string params (like iOS makeCommand)."""
    params: dict[str, str] = {}
    skip = {
        "capability",
        "step",
        "reason",
        "status",
        "step_status",
        "input_constrict",
        "output_constrict",
        "assigned_edge_id",
        "outputs",
        "execution_timing",
    }
    for k, v in step.items():
        if k in skip or v is None:
            continue
        if isinstance(v, (dict, list)):
            continue
        params[str(k)] = str(v)
    constrict = step.get("input_constrict")
    if isinstance(constrict, dict):
        for k, v in constrict.items():
            if v is None:
                continue
            if isinstance(v, (dict, list)):
                params[str(k)] = json.dumps(v, ensure_ascii=False)
            else:
                params[str(k)] = str(v)
    return params
