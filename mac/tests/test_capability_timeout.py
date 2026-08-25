"""Capability wall-clock timeout (default 5 minutes)."""

from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.asset.sdk import CapAsset
from mac_edge.config import Config, Identity
from mac_edge.executor import (
    STEP_FAILED,
    STEP_RUNNING,
    _advance_skipped_beats,
    _clear_step_started,
    _execute_capability_bounded,
    _mark_step_started,
    capability_timeout_msg,
    running_since_ms,
)


def _cfg(**kwargs) -> Config:
    base = dict(
        brain_base_url="http://example",
        interval_sec=3.0,
        identity=Identity(),
        data_dir=Path(tempfile.mkdtemp()),
        cast_display_url="http://127.0.0.1:9095/endpoint/display",
        capability_timeout_sec=300.0,
    )
    base.update(kwargs)
    return Config(**base)


class CapabilityTimeoutTests(unittest.TestCase):
    def tearDown(self) -> None:
        _clear_step_started("99", 1)
        _clear_step_started("111", 1)

    def test_timeout_message(self) -> None:
        self.assertIn("超时", capability_timeout_msg("camera.capture", 300))
        self.assertIn("300", capability_timeout_msg("camera.capture", 300))

    def test_running_since_prefers_local_tracker(self) -> None:
        _mark_step_started("99", 1, ts_ms=1000)
        intent = {
            "step_log": [{"step": 1, "status": STEP_RUNNING, "ts": 5000}],
        }
        self.assertEqual(running_since_ms(intent, "99", 1), 1000)

    def test_running_since_from_step_log(self) -> None:
        intent = {
            "step_log": [
                {"step": 1, "status": STEP_RUNNING, "ts": 111},
                {"step": 1, "status": STEP_RUNNING, "ts": 222},
                {"step": 2, "status": STEP_RUNNING, "ts": 999},
            ],
        }
        self.assertEqual(running_since_ms(intent, "99", 1), 222)

    def test_reclaim_stale_running_marks_failed(self) -> None:
        brain = MagicMock()
        now = 10_000_000
        started = now - 301_000  # > 300s
        plan = [
            {
                "step": 1,
                "status": STEP_RUNNING,
                "capability": "camera.capture",
                "assigned_edge_id": "edge-a",
            }
        ]
        intent = {
            "step_log": [
                {"step": 1, "status": STEP_RUNNING, "ts": started},
            ]
        }
        with patch("mac_edge.executor.BRAIN_CLOCK") as clock:
            clock.now_ms.return_value = now
            _advance_skipped_beats(
                plan,
                "111",
                "edge-a",
                brain=brain,
                intent=intent,
                config=_cfg(capability_timeout_sec=300.0),
            )
        self.assertEqual(plan[0]["status"], STEP_FAILED)
        self.assertIn("超时", plan[0]["msg"])
        brain.post_step_status.assert_called()
        self.assertEqual(
            brain.post_step_status.call_args.kwargs["step_status"], STEP_FAILED
        )

    def test_reclaim_skips_fresh_running(self) -> None:
        brain = MagicMock()
        now = 10_000_000
        started = now - 10_000  # 10s
        plan = [
            {
                "step": 1,
                "status": STEP_RUNNING,
                "capability": "camera.capture",
                "assigned_edge_id": "edge-a",
            }
        ]
        intent = {"step_log": [{"step": 1, "status": STEP_RUNNING, "ts": started}]}
        with patch("mac_edge.executor.BRAIN_CLOCK") as clock:
            clock.now_ms.return_value = now
            _advance_skipped_beats(
                plan,
                "111",
                "edge-a",
                brain=brain,
                intent=intent,
                config=_cfg(capability_timeout_sec=300.0),
            )
        self.assertEqual(plan[0]["status"], STEP_RUNNING)
        brain.post_step_status.assert_not_called()

    def test_bounded_execute_times_out(self) -> None:
        asset = CapAsset(manager=MagicMock(), intent_id="1", step_num=1)
        fut = MagicMock()
        fut.result.side_effect = FuturesTimeoutError()
        with patch("mac_edge.executor._CAP_EXEC_POOL") as pool:
            pool.submit.return_value = fut
            ok, msg, outputs = _execute_capability_bounded(
                "camera.capture",
                asset,
                params={},
                config=_cfg(capability_timeout_sec=300.0),
            )
        self.assertFalse(ok)
        self.assertIn("超时", msg)
        self.assertIn("camera.capture", msg)
        self.assertEqual(outputs, {})


if __name__ == "__main__":
    unittest.main()
