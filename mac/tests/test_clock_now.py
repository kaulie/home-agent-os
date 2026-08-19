"""clock.now reads the wall clock; no LLM."""

from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone

from mac_edge.plugins.clock_now import ClockNowError, clock_now, now_from_params


class ClockNowTests(unittest.TestCase):
    def test_local_outputs_required_fields(self) -> None:
        msg, outputs = now_from_params({})
        self.assertIn("now_iso", outputs)
        self.assertIn("time_text", outputs)
        self.assertTrue(outputs["now_iso"])
        self.assertIn("年", outputs["time_text"])
        self.assertIn("UTC", outputs["time_text"])
        self.assertIn("clock.now", msg)
        datetime.fromisoformat(outputs["now_iso"])

    def test_utc_timezone(self) -> None:
        outputs = clock_now(timezone_name="UTC")
        dt = datetime.fromisoformat(outputs["now_iso"])
        self.assertEqual(dt.utcoffset(), timezone.utc.utcoffset(dt))
        self.assertTrue(re.search(r"UTC[+-]00:00", outputs["time_text"]))

    def test_unknown_timezone_fails(self) -> None:
        with self.assertRaises(ClockNowError) as ctx:
            now_from_params({"timezone": "Not/AZone"})
        self.assertIn("未知时区", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
