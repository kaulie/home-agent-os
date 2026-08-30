"""Mac Edge cloud_usage counter."""

from __future__ import annotations

import unittest

from mac_edge.cloud_usage import drain, increment, record, snapshot


class CloudUsageTests(unittest.TestCase):
    def test_increment_snapshot_and_drain(self) -> None:
        drain()
        increment("ark.query", True)
        increment("ark.query", True)
        increment("ark.query", False)
        increment("bing.images", True)

        snap = snapshot()
        self.assertEqual(len(snap), 2)
        by_id = {row["service_id"]: row for row in snap}
        self.assertEqual(by_id["ark.query"], {"service_id": "ark.query", "ok": 2, "fail": 1})
        self.assertEqual(by_id["bing.images"], {"service_id": "bing.images", "ok": 1, "fail": 0})

        drained = drain()
        self.assertEqual(len(drained), 2)
        self.assertEqual(drain(), [])

    def test_snapshot_does_not_clear(self) -> None:
        drain()
        increment("volc.stt", True)
        snap1 = snapshot()
        snap2 = snapshot()
        self.assertEqual(snap1, snap2)
        self.assertEqual(drain(), snap1)

    def test_record_context_manager(self) -> None:
        drain()
        with record("ark.vision"):
            pass
        self.assertEqual(snapshot(), [{"service_id": "ark.vision", "ok": 1, "fail": 0}])
        drain()
        try:
            with record("ark.vision"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        self.assertEqual(snapshot(), [{"service_id": "ark.vision", "ok": 0, "fail": 1}])


if __name__ == "__main__":
    unittest.main()
