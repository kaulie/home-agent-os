"""Mac Edge capability: clock.now — local wall clock, no LLM.

Independent of query.content. This step only sees its own resolved params.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("mac_edge.clock_now")


class ClockNowError(Exception):
    pass


def _offset_label(delta: timedelta | None) -> str:
    if delta is None:
        return "UTC"
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    if minutes:
        return f"UTC{sign}{hours:02d}:{minutes:02d}"
    return f"UTC{sign}{hours:02d}:00"


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


def clock_now(*, timezone_name: str | None = None) -> dict[str, str]:
    """Read the wall clock. Never calls an LLM."""
    dt = _resolve_now(timezone_name)
    tzinfo = dt.tzinfo
    tz_key = getattr(tzinfo, "key", None) or (dt.tzname() or "local")
    now_iso = dt.isoformat(timespec="seconds")
    time_text = (
        f"{dt.year}年{dt.month}月{dt.day}日 "
        f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"
        f"（{tz_key}，{_offset_label(dt.utcoffset())}）"
    )
    return {"now_iso": now_iso, "time_text": time_text}


def now_from_params(params: dict[str, Any] | None = None) -> tuple[str, dict[str, str]]:
    raw = params if isinstance(params, dict) else {}
    tz = raw.get("timezone") or raw.get("tz") or raw.get("time_zone")
    tz_name = str(tz).strip() if tz is not None and str(tz).strip() else None
    outputs = clock_now(timezone_name=tz_name)
    msg = f"clock.now {outputs['time_text']}"
    log.info("clock.now timezone=%s iso=%s", tz_name or "local", outputs["now_iso"])
    return msg, outputs
