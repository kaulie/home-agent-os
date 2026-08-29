"""Tests for Brain music linkage (Mac Runtime hints via heartbeat)."""

from __future__ import annotations

import unittest

from music_linkage import (
    apply_heartbeat_ack,
    heartbeat_payload,
    on_user_intent_text,
    status,
    text_suggests_music_mode,
)


class MusicLinkageKeywordTests(unittest.TestCase):
    def test_text_suggests_music_mode(self) -> None:
        self.assertTrue(text_suggests_music_mode("播放陈奕迅的十年"))
        self.assertTrue(text_suggests_music_mode("来一首歌曲"))
        self.assertFalse(text_suggests_music_mode("现在几点了"))
        self.assertFalse(text_suggests_music_mode(""))


class MusicLinkageFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        import music_linkage as ml

        with ml._lock:
            ml._pending_enter.clear()
            ml._active.clear()

    def test_intent_queues_hint_and_heartbeat_delivers_once(self) -> None:
        import music_linkage as ml

        edges = {
            "edge-mac-1": {
                "online_status": "online",
                "device_type": "mac",
                "services": [
                    {
                        "capabilities": [
                            {"capability_id": "music.play"},
                        ]
                    }
                ],
            }
        }

        class FakeDB:
            @staticmethod
            def list_heartbeats():
                return edges

        original = ml.brain_db
        ml.brain_db = FakeDB()  # type: ignore[assignment]
        try:
            targets = ml.on_user_intent_text("播放周杰伦的歌", intent_id=99)
            self.assertEqual(targets, ["edge-mac-1"])

            hint = ml.heartbeat_payload("edge-mac-1")
            self.assertIsNotNone(hint)
            assert hint is not None
            self.assertEqual(hint.get("command"), "enter_music_mode")
            self.assertEqual(hint.get("mode"), "enter")
            self.assertEqual(hint.get("intent_id"), "99")

            self.assertIsNone(ml.heartbeat_payload("edge-mac-1"))

            ml.apply_heartbeat_ack(
                "edge-mac-1",
                {"music_linkage": {"mode": "music", "intent_id": "99"}},
            )
            active = ml.heartbeat_payload("edge-mac-1")
            self.assertIsNotNone(active)
            assert active is not None
            self.assertEqual(active.get("command"), "music_mode_active")
            self.assertEqual(active.get("mode"), "music")
        finally:
            ml.brain_db = original
            with ml._lock:
                ml._pending_enter.clear()
                ml._active.clear()

    def test_status_shape(self) -> None:
        snap = status()
        self.assertIn("pending", snap)
        self.assertIn("active", snap)
        self.assertIn("keywords", snap)


if __name__ == "__main__":
    unittest.main()
