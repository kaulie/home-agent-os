"""clock.now reads the wall clock; no LLM."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from mac_edge.plugins.clock_now import (
    ClockNowError,
    clock_now,
    now_from_params,
    spoken_time_text,
)


class ClockNowTests(unittest.TestCase):
    def test_local_outputs_required_fields(self) -> None:
        msg, outputs = now_from_params({})
        self.assertIn("now_iso", outputs)
        self.assertIn("time_text", outputs)
        self.assertTrue(outputs["now_iso"])
        self.assertIn("年", outputs["time_text"])
        self.assertTrue(outputs["time_text"].startswith("现在是"))
        self.assertIn("点", outputs["time_text"])
        self.assertNotIn("UTC", outputs["time_text"])
        self.assertNotIn("/", outputs["time_text"])
        self.assertNotIn("Asia", outputs["time_text"])
        self.assertNotIn(":", outputs["time_text"])
        self.assertIn("clock.now", msg)
        datetime.fromisoformat(outputs["now_iso"])

    def test_spoken_text_is_tts_friendly(self) -> None:
        dt = datetime(2026, 8, 23, 9, 25, 52, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(
            spoken_time_text(dt),
            "现在是2026年8月23日上午9点25分",
        )
        eight = datetime(2026, 8, 23, 8, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(
            spoken_time_text(eight),
            "现在是2026年8月23日上午8点整",
        )
        evening = datetime(2026, 8, 23, 21, 5, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(
            spoken_time_text(evening),
            "现在是2026年8月23日晚上9点5分",
        )

    def test_utc_timezone_says_world_time_not_offset(self) -> None:
        outputs = clock_now(timezone_name="UTC")
        dt = datetime.fromisoformat(outputs["now_iso"])
        self.assertEqual(dt.utcoffset(), timezone.utc.utcoffset(dt))
        self.assertIn("世界时", outputs["time_text"])
        self.assertNotIn("UTC", outputs["time_text"])
        self.assertNotIn("+00", outputs["time_text"])
        noon = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(
            spoken_time_text(noon),
            "现在是2026年8月23日中午12点整，世界时",
        )

    def test_unknown_timezone_fails(self) -> None:
        with self.assertRaises(ClockNowError) as ctx:
            now_from_params({"timezone": "Not/AZone"})
        self.assertIn("未知时区", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
