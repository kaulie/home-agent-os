"""Intent-scoped variable context (same model as iOS RuntimeContext / ParamResolver).

- Publish only keys listed in step `output_constrict` with `data_dest: "context"`.
- Resolve whole-value `$name` / `${name}` params from context.
"""

from __future__ import annotations

import re
from typing import Any

_DOLLAR_NAME = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")
_DOLLAR_BRACE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


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
            text = str(v).strip()
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
            value = str(raw).strip()
            if not value or value.startswith("$"):
                continue
            self._values[k] = value
            published.append(k)
        return published


def _publishes_to_context(meta: Any) -> bool:
    if not isinstance(meta, dict):
        return False
    dest = str(meta.get("data_dest") or "").strip().lower()
    return dest == "context"


def resolve_value(raw: str, context: RuntimeContext) -> str:
    value = (raw or "").strip()
    if "{{" in value or "}}" in value:
        raise ValueError(f"unsupported param template (use $var): {value}")
    name = _match_variable(value)
    if name is None:
        return raw
    resolved = context.get(name)
    if resolved is None:
        raise ValueError(f"unresolved context variable ${name}")
    return resolved


def resolve_params(params: dict[str, str], context: RuntimeContext) -> dict[str, str]:
    return {k: resolve_value(v, context) for k, v in params.items()}


def _match_variable(value: str) -> str | None:
    m = _DOLLAR_NAME.match(value) or _DOLLAR_BRACE.match(value)
    return m.group(1) if m else None


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
        "delay_sec",
    }
    for k, v in step.items():
        if k in skip:
            continue
        if isinstance(v, (str, int, float, bool)):
            params[str(k)] = str(v)
    nest = step.get("input_constrict")
    if isinstance(nest, dict):
        for k, v in nest.items():
            if isinstance(v, (str, int, float, bool)):
                params[str(k)] = str(v)
    return params
