"""Calendar period helpers for Dev Task token usage stats."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

TZ = timezone(timedelta(hours=8))

VALID_PERIODS = frozenset({"day", "week", "month", "year", "all"})


def resolve_usage_period(
    *,
    period: str | None = None,
    days: int | None = 7,
) -> dict[str, Any]:
    key = (period or "").strip().lower()
    if key in VALID_PERIODS:
        return _calendar_period(key)
    if days is not None and int(days) > 0:
        since = time.time() - int(days) * 86400
        return {
            "period_key": f"days_{int(days)}",
            "period_label": f"近 {int(days)} 天",
            "period_days": int(days),
            "since": since,
            "until": None,
            "time_granularity": "day",
        }
    return _calendar_period("all")


def _calendar_period(key: str) -> dict[str, Any]:
    now = datetime.now(TZ)
    if key == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "period_key": "day",
            "period_label": "今日",
            "period_days": None,
            "since": start.timestamp(),
            "until": None,
            "time_granularity": "hour",
        }
    if key == "week":
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return {
            "period_key": "week",
            "period_label": "本周",
            "period_days": None,
            "since": start.timestamp(),
            "until": None,
            "time_granularity": "day",
        }
    if key == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return {
            "period_key": "month",
            "period_label": "本月",
            "period_days": None,
            "since": start.timestamp(),
            "until": None,
            "time_granularity": "day",
        }
    if key == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return {
            "period_key": "year",
            "period_label": "本年",
            "period_days": None,
            "since": start.timestamp(),
            "until": None,
            "time_granularity": "month",
        }
    return {
        "period_key": "all",
        "period_label": "全部",
        "period_days": None,
        "since": None,
        "until": None,
        "time_granularity": "month",
    }


def bucket_for_timestamp(ts: float, granularity: str) -> str:
    dt = datetime.fromtimestamp(ts, TZ)
    if granularity == "hour":
        return dt.strftime("%Y-%m-%dT%H")
    if granularity == "month":
        return dt.strftime("%Y-%m")
    if granularity == "year":
        return dt.strftime("%Y")
    return dt.strftime("%Y-%m-%d")


def bucket_label(bucket_key: str, granularity: str) -> str:
    if granularity == "hour":
        hour = bucket_key.rsplit("T", 1)[-1]
        return f"{hour}:00"
    if granularity == "month":
        year, month = bucket_key.split("-", 1)
        return f"{int(month)}月"
    if granularity == "year":
        return f"{bucket_key}年"
    _, month, day = bucket_key.split("-")
    return f"{int(month)}/{int(day)}"


def time_section_label(granularity: str) -> str:
    if granularity == "hour":
        return "按小时"
    if granularity == "month":
        return "按月"
    if granularity == "year":
        return "按年"
    return "按天"
