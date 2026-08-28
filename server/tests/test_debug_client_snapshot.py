"""Tests for debug client snapshot helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import debug_client_snapshot as dcs  # noqa: E402


class DebugClientSnapshotTests(unittest.TestCase):
    def test_merge_intent_context(self) -> None:
        merged = dcs.merge_intent_context(
            {"intent_id": 1, "intent_status": "failed"},
            {
                "primary_brain": {"mode": "lan", "base_url": "http://lan"},
                "heartbeat": {"primary_mode": "lan"},
            },
        )
        self.assertEqual(merged["intent_id"], 1)
        snap = merged["client_snapshot"]
        self.assertEqual(snap["primary_brain"]["mode"], "lan")
        self.assertEqual(snap["heartbeat"]["primary_mode"], "lan")


if __name__ == "__main__":
    unittest.main()
