"""Tests for dev task usage period helpers."""

import unittest
from datetime import datetime, timezone, timedelta

from dev_task_usage_period import (
    VALID_PERIODS,
    bucket_for_timestamp,
    bucket_label,
    resolve_usage_period,
    time_section_label,
)

TZ = timezone(timedelta(hours=8))


class DevTaskUsagePeriodTests(unittest.TestCase):
    def test_valid_periods(self) -> None:
        self.assertEqual(VALID_PERIODS, {"day", "week", "month", "year", "all"})

    def test_resolve_calendar_period(self) -> None:
        week = resolve_usage_period(period="week")
        self.assertEqual(week["period_key"], "week")
        self.assertEqual(week["period_label"], "本周")
        self.assertEqual(week["time_granularity"], "day")
        self.assertIsNotNone(week["since"])

    def test_resolve_rolling_days(self) -> None:
        rolling = resolve_usage_period(days=30)
        self.assertEqual(rolling["period_key"], "days_30")
        self.assertEqual(rolling["period_label"], "近 30 天")

    def test_bucket_day(self) -> None:
        ts = datetime(2026, 8, 27, 15, 30, tzinfo=TZ).timestamp()
        key = bucket_for_timestamp(ts, "day")
        self.assertEqual(key, "2026-08-27")
        self.assertEqual(bucket_label(key, "day"), "8/27")

    def test_bucket_hour(self) -> None:
        ts = datetime(2026, 8, 27, 15, 30, tzinfo=TZ).timestamp()
        key = bucket_for_timestamp(ts, "hour")
        self.assertEqual(key, "2026-08-27T15")
        self.assertEqual(bucket_label(key, "hour"), "15:00")

    def test_time_section_label(self) -> None:
        self.assertEqual(time_section_label("hour"), "按小时")
        self.assertEqual(time_section_label("day"), "按天")
        self.assertEqual(time_section_label("month"), "按月")


if __name__ == "__main__":
    unittest.main()
