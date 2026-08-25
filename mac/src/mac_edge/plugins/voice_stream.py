"""Mac Edge capability: voice.stream — long-running input; not plan-step executed.

STT + POST /intent live in the supervised mac_voice process (kind=input).
If Brain mistakenly schedules this capability as a plan step, refuse clearly.
"""

from __future__ import annotations

from typing import Any


class VoiceStreamError(Exception):
    pass


def run_from_params(_params: dict[str, Any]) -> tuple[str, dict[str, str]]:
    raise VoiceStreamError(
        "voice.stream 是常驻语音输入入口（kind=input），由自身策略开麦；"
        "不由计划逐步执行"
    )
