"""execution_timing + base_time protocol helpers (Brain stub + shared semantics).

Wire rules (locked):
- Times are Unix epoch milliseconds (int).
- Never emit delay_sec on the wire.
- delay: absolute exec_time only.
- interval: interval_sec + first_exec_time; beats = first + n * interval.
- cron: cron_expr + timezone + first_exec_time; scheduler expands next fires.
- Miss window covers only "past planned start, not yet started".
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

ONE_SHOT_MISS_MS = 15 * 60 * 1000
PERIODIC_MISS_CAP_MS = 15 * 60 * 1000
CLOCK_SKEW_REJECT_MS = 5 * 60 * 1000

MODE_IMMEDIATE = "immediate"
MODE_DELAY = "delay"
MODE_INTERVAL = "interval"
MODE_CRON = "cron"


def now_ms() -> int:
    return int(time.time() * 1000)


def as_ms(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    # Accidental seconds → ms
    if 0 < n < 10_000_000_000:
        n *= 1000
    return n if n > 0 else None


@dataclass(frozen=True)
class ExecutionTiming:
    mode: str
    exec_time: int | None = None
    first_exec_time: int | None = None
    interval_sec: int | None = None
    cron_expr: str | None = None
    timezone: str | None = None
    end_time: int | None = None
    count: int | None = None

    @property
    def is_recurring(self) -> bool:
        return self.mode in (MODE_INTERVAL, MODE_CRON)


def parse_execution_timing(step: dict[str, Any] | None) -> ExecutionTiming:
    if not isinstance(step, dict):
        return ExecutionTiming(mode=MODE_IMMEDIATE)
    raw = step.get("execution_timing")
    if not isinstance(raw, dict):
        return ExecutionTiming(mode=MODE_IMMEDIATE)
    mode = str(raw.get("mode") or MODE_IMMEDIATE).strip().lower() or MODE_IMMEDIATE
    if mode not in (MODE_IMMEDIATE, MODE_DELAY, MODE_INTERVAL, MODE_CRON):
        mode = MODE_IMMEDIATE
    interval = raw.get("interval_sec")
    try:
        interval_sec = int(interval) if interval is not None else None
    except (TypeError, ValueError):
        interval_sec = None
    if interval_sec is not None and interval_sec <= 0:
        interval_sec = None
    count_raw = raw.get("count")
    try:
        count = int(count_raw) if count_raw is not None else None
    except (TypeError, ValueError):
        count = None
    if count is not None and count <= 0:
        count = None
    cron_expr = str(raw.get("cron_expr") or raw.get("cron") or "").strip() or None
    return ExecutionTiming(
        mode=mode,
        exec_time=as_ms(raw.get("exec_time")),
        first_exec_time=as_ms(raw.get("first_exec_time")),
        interval_sec=interval_sec,
        cron_expr=cron_expr,
        timezone=str(raw.get("timezone") or "").strip() or None,
        end_time=as_ms(raw.get("end_time")) or as_ms(raw.get("end_exec_time")),
        count=count,
    )


def normalize_execution_timing_dict(raw: Any) -> dict[str, Any] | None:
    """Normalize / strip illegal fields. Returns None for implicit immediate."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return {"mode": MODE_IMMEDIATE}
    out = dict(raw)
    out.pop("delay_sec", None)
    out.pop("delaySec", None)
    mode = str(out.get("mode") or MODE_IMMEDIATE).strip().lower() or MODE_IMMEDIATE
    if mode not in (MODE_IMMEDIATE, MODE_DELAY, MODE_INTERVAL, MODE_CRON):
        mode = MODE_IMMEDIATE
    out["mode"] = mode
    for key in ("exec_time", "first_exec_time", "end_time"):
        if key in out:
            ms = as_ms(out.get(key))
            if ms is None:
                out.pop(key, None)
            else:
                out[key] = ms
    if "interval_sec" in out:
        try:
            sec = int(out["interval_sec"])
            if sec > 0:
                out["interval_sec"] = sec
            else:
                out.pop("interval_sec", None)
        except (TypeError, ValueError):
            out.pop("interval_sec", None)
    # Wire field is cron_expr; accept legacy "cron" then rewrite.
    legacy_cron = out.pop("cron", None)
    if "cron_expr" not in out and legacy_cron is not None:
        out["cron_expr"] = legacy_cron
    if "cron_expr" in out:
        expr = str(out.get("cron_expr") or "").strip()
        if expr:
            out["cron_expr"] = expr
        else:
            out.pop("cron_expr", None)
    # Alias end_exec_time → end_time
    if "end_time" not in out and "end_exec_time" in out:
        out["end_time"] = out.pop("end_exec_time")
    else:
        out.pop("end_exec_time", None)
    if mode == MODE_IMMEDIATE and len(out) == 1:
        return out
    return out


def planned_start_ms(timing: ExecutionTiming, beat_index: int) -> int | None:
    """Plan start time for beat n (0-based)."""
    if beat_index < 0:
        return None
    if timing.mode == MODE_IMMEDIATE:
        return None
    if timing.mode == MODE_DELAY:
        return timing.exec_time
    if timing.mode == MODE_INTERVAL:
        if timing.first_exec_time is None or timing.interval_sec is None:
            return None
        return timing.first_exec_time + beat_index * timing.interval_sec * 1000
    if timing.mode == MODE_CRON:
        if timing.first_exec_time is None:
            return None
        if beat_index == 0:
            return timing.first_exec_time
        t = timing.first_exec_time
        for _ in range(beat_index):
            nxt = cron_next_after(timing.cron_expr or "", t, timing.timezone)
            if nxt is None:
                return None
            t = nxt
        return t
    return None


def next_planned_after(timing: ExecutionTiming, planned_start: int) -> int | None:
    if timing.mode == MODE_INTERVAL:
        if timing.interval_sec is None:
            return None
        return planned_start + timing.interval_sec * 1000
    if timing.mode == MODE_CRON:
        return cron_next_after(timing.cron_expr or "", planned_start, timing.timezone)
    return None


def miss_window_ms(timing: ExecutionTiming, planned_start: int) -> int:
    if timing.mode in (MODE_IMMEDIATE, MODE_DELAY) or not timing.is_recurring:
        return ONE_SHOT_MISS_MS
    nxt = next_planned_after(timing, planned_start)
    if nxt is None or nxt <= planned_start:
        return PERIODIC_MISS_CAP_MS
    half = max(0, (nxt - planned_start) // 2)
    return min(half, PERIODIC_MISS_CAP_MS)


@dataclass(frozen=True)
class TimingGate:
    """Result of timingDue for one beat."""

    due: bool
    skip_beat: bool  # past miss window → advance without running
    terminal: bool  # series finished / one-shot expired
    reason: str
    planned_start: int | None = None


def timing_gate(timing: ExecutionTiming, now_ms: int, beat_index: int = 0) -> TimingGate:
    if timing.mode == MODE_IMMEDIATE:
        return TimingGate(due=True, skip_beat=False, terminal=False, reason="immediate")

    if timing.count is not None and beat_index >= timing.count:
        return TimingGate(
            due=False, skip_beat=False, terminal=True, reason="count exhausted"
        )

    planned = planned_start_ms(timing, beat_index)
    if planned is None:
        return TimingGate(
            due=False,
            skip_beat=False,
            terminal=False,
            reason="missing planned start",
        )

    if timing.end_time is not None and planned > timing.end_time:
        return TimingGate(
            due=False,
            skip_beat=False,
            terminal=True,
            reason="past end_time",
            planned_start=planned,
        )

    if now_ms < planned:
        return TimingGate(
            due=False,
            skip_beat=False,
            terminal=False,
            reason=f"wait until {planned}",
            planned_start=planned,
        )

    late = now_ms - planned
    window = miss_window_ms(timing, planned)
    if late > window:
        if timing.is_recurring:
            return TimingGate(
                due=False,
                skip_beat=True,
                terminal=False,
                reason=f"miss window exceeded ({late}>{window})",
                planned_start=planned,
            )
        return TimingGate(
            due=False,
            skip_beat=False,
            terminal=True,
            reason=f"one-shot expired ({late}>{window})",
            planned_start=planned,
        )

    return TimingGate(
        due=True,
        skip_beat=False,
        terminal=False,
        reason="due",
        planned_start=planned,
    )


def clock_skew_ms(client_time_ms: int | None, brain_time_ms: int | None = None) -> int | None:
    if client_time_ms is None:
        return None
    brain = brain_time_ms if brain_time_ms is not None else now_ms()
    return abs(int(client_time_ms) - int(brain))


def schedule_eligible_for_client(client_time_ms: int | None, brain_time_ms: int | None = None) -> bool:
    skew = clock_skew_ms(client_time_ms, brain_time_ms)
    if skew is None:
        # No client clock → allow (legacy heartbeats) but prefer clients that send it.
        return True
    return skew <= CLOCK_SKEW_REJECT_MS


# --- cron (5-field) minimal expander -------------------------------------------------

_FIELD_RE = re.compile(r"^(\*|\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)(?:/(\d+))?$")


def _parse_cron_field(field: str, min_v: int, max_v: int) -> set[int]:
    field = field.strip()
    m = _FIELD_RE.match(field)
    if not m:
        raise ValueError(f"bad cron field: {field}")
    base, step_s = m.group(1), m.group(2)
    step = int(step_s) if step_s else 1
    if step <= 0:
        raise ValueError("cron step must be > 0")
    values: set[int] = set()
    if base == "*":
        values = set(range(min_v, max_v + 1))
    else:
        for part in base.split(","):
            if "-" in part:
                a_s, b_s = part.split("-", 1)
                a, b = int(a_s), int(b_s)
                values.update(range(a, b + 1))
            else:
                values.add(int(part))
    out = {v for v in values if min_v <= v <= max_v and (v - min_v) % step == 0}
    # For */n, (v - min) % step; for list with step, filter by step from min of set
    if step > 1 and base != "*":
        ordered = sorted(values)
        if not ordered:
            return set()
        start = ordered[0]
        out = {v for v in values if min_v <= v <= max_v and (v - start) % step == 0}
    return out


def _tz(name: str | None):
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def cron_next_after(expr: str, after_ms: int, tz_name: str | None = None) -> int | None:
    """Next fire strictly after after_ms for standard 5-field cron (min hour dom mon dow)."""
    parts = (expr or "").strip().split()
    if len(parts) != 5:
        return None
    try:
        minutes = sorted(_parse_cron_field(parts[0], 0, 59))
        hours = sorted(_parse_cron_field(parts[1], 0, 23))
        doms = _parse_cron_field(parts[2], 1, 31)
        months = _parse_cron_field(parts[3], 1, 12)
        dows = _parse_cron_field(parts[4], 0, 6)  # 0=Sunday
    except ValueError:
        return None
    if not minutes or not hours or not months:
        return None

    tz = _tz(tz_name)
    start = datetime.fromtimestamp(after_ms / 1000.0, tz=tz) + timedelta(minutes=1)
    start = start.replace(second=0, microsecond=0)
    dom_star = parts[2] == "*" or parts[2].startswith("*/")
    dow_star = parts[4] == "*" or parts[4].startswith("*/")

    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(400):
        if day.month in months:
            py_wd = day.weekday()
            cron_wd = (py_wd + 1) % 7
            dom_ok = day.day in doms
            dow_ok = cron_wd in dows
            if dom_star and dow_star:
                day_ok = True
            elif dom_star:
                day_ok = dow_ok
            elif dow_star:
                day_ok = dom_ok
            else:
                day_ok = dom_ok or dow_ok
            if day_ok:
                for hour in hours:
                    for minute in minutes:
                        cand = day.replace(hour=hour, minute=minute)
                        if cand >= start:
                            return int(cand.timestamp() * 1000)
        day += timedelta(days=1)
    return None


def apply_timing_to_step(step: dict[str, Any], timing: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(step)
    if timing is None:
        out.pop("execution_timing", None)
        return out
    normalized = normalize_execution_timing_dict(timing)
    if normalized is None:
        out.pop("execution_timing", None)
    else:
        out["execution_timing"] = normalized
    out.pop("delay_sec", None)
    return out


def stamp_base_time(intent: dict[str, Any], base: int | None = None) -> int:
    ms = base if base is not None else now_ms()
    intent["base_time"] = int(ms)
    return int(ms)


def delay_timing(base_time_ms: int, delay_ms: int) -> dict[str, Any]:
    return {
        "mode": MODE_DELAY,
        "exec_time": int(base_time_ms) + int(delay_ms),
    }


def interval_timing(
    base_time_ms: int,
    interval_sec: int,
    *,
    offset_ms: int = 0,
    end_time: int | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "mode": MODE_INTERVAL,
        "interval_sec": int(interval_sec),
        "first_exec_time": int(base_time_ms) + int(offset_ms),
    }
    if end_time is not None:
        out["end_time"] = int(end_time)
    return out


def cron_timing(
    first_exec_time_ms: int,
    cron_expr: str,
    *,
    timezone_name: str = "Asia/Shanghai",
    end_time: int | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "mode": MODE_CRON,
        "cron_expr": cron_expr,
        "timezone": timezone_name,
        "first_exec_time": int(first_exec_time_ms),
    }
    if end_time is not None:
        out["end_time"] = int(end_time)
    return out


_DELAY_RE = re.compile(
    r"(?:(\d+)\s*(?:个)?\s*(秒|分钟|分|小时|小时钟|小时整|hour|min|minute|minutes|sec|seconds)"
    r"|(\d+)\s*(s|m|h))\s*后",
    re.I,
)
_INTERVAL_RE = re.compile(
    r"每\s*(\d+)\s*(秒|分钟|分|小时|s|m|h|sec|min|hour)",
    re.I,
)
_DURATION_RE = re.compile(
    r"(?:做|持续|一共|总共|共)?\s*(\d+)\s*(秒|分钟|分|小时|s|m|h|sec|min|hour)",
    re.I,
)
_DAILY_RE = re.compile(r"每天\s*(\d{1,2})\s*[点:：](?:\s*(\d{1,2})\s*分?)?")


def _unit_to_ms(n: int, unit: str) -> int:
    u = unit.lower()
    if u in ("秒", "s", "sec", "seconds"):
        return n * 1000
    if u in ("分钟", "分", "m", "min", "minute", "minutes"):
        return n * 60_000
    if u in ("小时", "小时钟", "小时整", "h", "hour"):
        return n * 3_600_000
    return n * 1000


def _unit_to_sec(n: int, unit: str) -> int:
    return max(1, _unit_to_ms(n, unit) // 1000)


def _infer_duration_ms(text: str, interval_sec: int | None = None) -> int | None:
    """Pick a duration distinct from the interval phrase when possible."""
    matches = list(_DURATION_RE.finditer(text or ""))
    if not matches:
        return None
    for m in matches:
        n = int(m.group(1))
        sec = _unit_to_sec(n, m.group(2))
        # Skip the same span that is the "每 N 秒" interval.
        if interval_sec is not None and sec == interval_sec:
            # Prefer longer durations elsewhere in the sentence.
            continue
        return sec * 1000
    # Fallback: if only one duration and it equals interval, no end_time.
    if len(matches) == 1 and interval_sec is not None:
        n = int(matches[0].group(1))
        sec = _unit_to_sec(n, matches[0].group(2))
        if sec == interval_sec:
            return None
    if matches:
        n = int(matches[0].group(1))
        return _unit_to_sec(n, matches[0].group(2)) * 1000
    return None


def infer_timing_from_text(text: str, base_time_ms: int) -> dict[str, Any] | None:
    """Brain semantic stub: map Chinese time phrases → execution_timing (no delay_sec)."""
    t = (text or "").strip()
    if not t:
        return None

    m_daily = _DAILY_RE.search(t)
    if m_daily:
        hour = int(m_daily.group(1))
        minute = int(m_daily.group(2) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            cron = f"{minute} {hour} * * *"
            # first fire = next occurrence after base
            first = cron_next_after(cron, base_time_ms - 1, "Asia/Shanghai")
            if first is None:
                first = base_time_ms
            return cron_timing(first, cron, timezone_name="Asia/Shanghai")

    m_int = _INTERVAL_RE.search(t)
    if m_int:
        n = int(m_int.group(1))
        sec = _unit_to_sec(n, m_int.group(2))
        # First beat shortly after base (e.g. +interval) unless text implies immediate.
        first_offset = sec * 1000
        duration_ms = _infer_duration_ms(t, interval_sec=sec)
        end_time = None
        if duration_ms is not None:
            end_time = int(base_time_ms) + int(duration_ms)
        return interval_timing(base_time_ms, sec, offset_ms=first_offset, end_time=end_time)

    m_delay = _DELAY_RE.search(t)
    if m_delay:
        if m_delay.group(1):
            n = int(m_delay.group(1))
            unit = m_delay.group(2)
        else:
            n = int(m_delay.group(3))
            unit = m_delay.group(4)
        return delay_timing(base_time_ms, _unit_to_ms(n, unit))

    return None
