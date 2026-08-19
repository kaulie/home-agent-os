"""Mac Edge capability: light.set — living-room ceiling light via speaker wake.

Independent of notify.speak as a plan step. This step only sees its own
resolved params. Voice protocol is internal: wake → wait → command.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from mac_edge.plugins.notify_speak import NotifySpeakError, speak

log = logging.getLogger("mac_edge.livingroom_light")

WAKE_PHRASE = "小书小书"
WAIT_AFTER_WAKE_SEC = 2.0
COMMAND_ON = "开灯"
COMMAND_OFF = "关灯"

_ON_ALIASES = frozenset({"on", "开", "开灯", "true", "1"})
_OFF_ALIASES = frozenset({"off", "关", "关灯", "false", "0"})


class LivingRoomLightError(Exception):
    pass


def _normalize_state(raw: Any) -> str:
    folded = str(raw or "").strip().lower().replace(" ", "")
    if not folded:
        raise LivingRoomLightError("灯控失败：缺少必填入参 state（on 或 off）。")
    if folded in _ON_ALIASES:
        return "on"
    if folded in _OFF_ALIASES:
        return "off"
    raise LivingRoomLightError(
        f"灯控失败：无法识别 state「{raw}」。请用 on 或 off。"
    )


def set_light(
    state: str,
    *,
    speak_fn: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> dict[str, str]:
    """Wake 小书, wait, then speak 开灯/关灯. Does not listen for 在呢."""
    speaker = speak_fn or speak
    sleeper = sleep_fn or time.sleep
    command = COMMAND_ON if state == "on" else COMMAND_OFF
    try:
        speaker(WAKE_PHRASE, lang="zh_CN")
        sleeper(WAIT_AFTER_WAKE_SEC)
        speaker(command, lang="zh_CN")
    except NotifySpeakError as e:
        raise LivingRoomLightError(f"灯控失败：本机语音没发出去（{e}）") from e
    except LivingRoomLightError:
        raise
    except Exception as e:
        raise LivingRoomLightError(f"灯控失败：{e}") from e
    log.info("light.set state=%s wake=%s command=%s", state, WAKE_PHRASE, command)
    return {"state": state}


def set_from_params(
    params: dict[str, Any] | None = None,
    *,
    speak_fn: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> tuple[str, dict[str, str]]:
    raw = params if isinstance(params, dict) else {}
    state_raw = raw.get("state")
    if state_raw is None or str(state_raw).strip() == "":
        raise LivingRoomLightError("灯控失败：缺少必填入参 state（on 或 off）。")
    state = _normalize_state(state_raw)
    outputs = set_light(state, speak_fn=speak_fn, sleep_fn=sleep_fn)
    msg = f"light.set {COMMAND_ON if state == 'on' else COMMAND_OFF}"
    return msg, outputs
