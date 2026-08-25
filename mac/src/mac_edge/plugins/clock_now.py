"""Mac Edge capability: clock.now — local wall clock, no LLM.

Independent of query.content. This step only sees its own resolved params.
time_text is for speaking/reading; machine timezone lives on now_iso.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("mac_edge.clock_now")


class ClockNowError(Exception):
    pass


def _resolve_now(timezone_name: str | None) -> datetime:
    name = (timezone_name or "").strip()
    if not name:
        return datetime.now().astimezone()
    try:
        return datetime.now(ZoneInfo(name))
    except ZoneInfoNotFoundError as e:
        raise ClockNowError(
            f"报时失败：未知时区「{name}」。请用 IANA 名称，例如 Asia/Shanghai。"
        ) from e
    except Exception as e:
        raise ClockNowError(f"报时失败：无法使用时区「{name}」（{e}）") from e


def _day_period(hour: int) -> tuple[str, int]:
    if hour == 0:
        return "凌晨", 0
    if hour < 6:
        return "凌晨", hour
    if hour < 12:
        return "上午", hour
    if hour == 12:
        return "中午", 12
    if hour < 18:
        return "下午", hour - 12
    return "晚上", hour - 12


def _spoken_zone(dt: datetime) -> str:
    if dt.utcoffset() == timedelta(0):
        return "，世界时"
    return ""


def spoken_time_text(dt: datetime) -> str:
    """Chinese wall-clock line meant for TTS. No IANA names, slashes, or UTC+HH:MM."""
    period, hour12 = _day_period(dt.hour)
    if dt.minute == 0:
        clock = f"{hour12}点整"
    else:
        clock = f"{hour12}点{dt.minute}分"
    return (
        f"现在是{dt.year}年{dt.month}月{dt.day}日"
        f"{period}{clock}"
        f"{_spoken_zone(dt)}"
    )


def clock_now(*, timezone_name: str | None = None) -> dict[str, str]:
    """Read the wall clock. Never calls an LLM."""
    dt = _resolve_now(timezone_name)
    now_iso = dt.isoformat(timespec="seconds")
    time_text = spoken_time_text(dt)
    return {"now_iso": now_iso, "time_text": time_text}


def now_from_params(params: dict[str, Any] | None = None) -> tuple[str, dict[str, str]]:
    raw = params if isinstance(params, dict) else {}
    tz = raw.get("timezone") or raw.get("tz") or raw.get("time_zone")
    tz_name = str(tz).strip() if tz is not None and str(tz).strip() else None
    outputs = clock_now(timezone_name=tz_name)
    msg = f"clock.now {outputs['time_text']}"
    log.info("clock.now timezone=%s iso=%s", tz_name or "local", outputs["now_iso"])
    return msg, outputs
