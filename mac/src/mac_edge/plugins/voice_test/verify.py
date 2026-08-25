"""Independent lamp-state verification.

SUCCESS must come from this module, never from 'audio played'.
Default backend reuses vision.ask. Swap in API / current sensors later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

log = logging.getLogger("mac_edge.voice_test.verify")

LampState = str  # on | off | unknown


@dataclass(frozen=True)
class VerifyResult:
    state: LampState
    answer_text: str
    source: str
    error_reason: str = ""

    @property
    def is_on(self) -> bool:
        return self.state == "on"

    @property
    def is_off(self) -> bool:
        return self.state == "off"


class LampVerifier(Protocol):
    def verify(self, *, photo_url: str, query: str) -> VerifyResult:
        """Return on/off/unknown from an independent observation."""


def parse_lamp_answer(answer_text: str) -> LampState:
    raw = (answer_text or "").strip()
    if not raw:
        return "unknown"
    folded = raw.lower().replace(" ", "").replace("。", "").replace(".", "")
    if "不知道" in folded or "看不清" in folded or "无法判断" in folded:
        return "unknown"
    if folded in {"亮", "开", "开着", "已开", "on", "lit", "yes"}:
        return "on"
    if folded in {"灭", "关", "关着", "已关", "off", "dark", "no"}:
        return "off"
    if "不亮" in folded or "没亮" in folded or "未亮" in folded:
        return "off"
    off_markers = ("灭", "关着", "已关", "off", "dark")
    on_markers = ("亮着", "开着", "已开", "点亮", "lit")
    off_hit = any(m in folded for m in off_markers)
    on_hit = any(m in folded for m in on_markers) or folded == "亮"
    if off_hit and not on_hit:
        return "off"
    if on_hit and not off_hit:
        return "on"
    return "unknown"


class VisionAskVerifier:
    """Adapter: vision.ask(photo_url, query) → on/off/unknown."""

    def __init__(
        self,
        ask_fn: Callable[..., dict] | None = None,
        *,
        timeout_sec: float = 90.0,
    ) -> None:
        self._ask_fn = ask_fn
        self._timeout_sec = timeout_sec

    def verify(self, *, photo_url: str, query: str) -> VerifyResult:
        url = (photo_url or "").strip()
        q = (query or "").strip()
        if not url:
            return VerifyResult("unknown", "", "vision.ask", "missing_photo_url")
        if not q:
            return VerifyResult("unknown", "", "vision.ask", "missing_query")
        ask = self._ask_fn
        if ask is None:
            from mac_edge.plugins.vision_ask import ask as default_ask

            ask = default_ask
        try:
            outputs = ask(photo_url=url, query=q, timeout_sec=self._timeout_sec)
        except Exception as e:
            log.warning("vision.ask verifier failed: %s", e)
            return VerifyResult("unknown", str(e), "vision.ask", "vision_ask_failed")
        answer = str((outputs or {}).get("answer_text") or "").strip()
        state = parse_lamp_answer(answer)
        reason = "" if state != "unknown" else "verify_unknown"
        return VerifyResult(state, answer, "vision.ask", reason)
