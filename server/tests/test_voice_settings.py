"""Tests for Brain voice wake reply settings."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import db as brain_db  # noqa: E402
import voice_settings as vs  # noqa: E402


class VoiceSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db = Path(self._tmpdir.name) / "brain.sqlite3"
        brain_db.reset(path=self._db)
        brain_db.init_db()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmpdir.cleanup()

    def test_default_wake_ack(self) -> None:
        self.assertEqual(vs.get_wake_ack(), "我在呢")

    def test_set_and_get_wake_ack(self) -> None:
        saved = vs.set_wake_ack("来了")
        self.assertEqual(saved, "来了")
        self.assertEqual(vs.get_wake_ack(), "来了")

    def test_rejects_empty_wake_ack(self) -> None:
        with self.assertRaises(ValueError):
            vs.set_wake_ack("   ")

    def test_wake_ack_utterances_include_legacy_and_current(self) -> None:
        vs.set_wake_ack("来了")
        utterances = vs.wake_ack_utterances()
        self.assertIn("来了", utterances)
        self.assertIn("又咋了", utterances)
        self.assertIn("我在呢", utterances)

    def test_public_settings(self) -> None:
        vs.set_wake_ack("好的")
        payload = vs.public_settings()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["wake_ack"], "好的")


if __name__ == "__main__":
    unittest.main()
