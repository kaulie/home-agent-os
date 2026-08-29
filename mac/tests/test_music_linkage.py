"""Mac Edge music linkage with Brain heartbeat hints."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.music_linkage import (
    MusicLinkageMute,
    apply_brain_hint,
    enter,
    exit_mode,
    heartbeat_ack,
    is_active,
)


class MusicLinkageTests(unittest.TestCase):
    def setUp(self) -> None:
        import mac_edge.music_linkage as ml

        with ml._lock:
            ml._state.clear()
        try:
            ml.flag_path().unlink(missing_ok=True)
        except OSError:
            pass

    def test_enter_exit_and_ack(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = Path(td) / "music_mode"
            with patch("mac_edge.music_linkage.flag_path", return_value=flag):
                self.assertFalse(is_active())
                enter(intent_id="42", trigger_text="播放十年")
                self.assertTrue(is_active())
                ack = heartbeat_ack()
                self.assertIsNotNone(ack)
                assert ack is not None
                self.assertEqual(ack.get("mode"), "music")
                self.assertEqual(ack.get("intent_id"), "42")
                self.assertTrue(MusicLinkageMute()())  # flag on; listen does not mute STT
                exit_mode()
                self.assertFalse(is_active())
                self.assertEqual(heartbeat_ack(), {"mode": "idle"})

    def test_apply_brain_hint_enter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = Path(td) / "music_mode"
            with patch("mac_edge.music_linkage.flag_path", return_value=flag):
                changed = apply_brain_hint(
                    {
                        "command": "enter_music_mode",
                        "mode": "enter",
                        "intent_id": "99",
                        "trigger_text": "播放歌曲",
                    }
                )
                self.assertTrue(changed)
                self.assertTrue(is_active())
                data = json.loads(flag.read_text(encoding="utf-8"))
                self.assertEqual(data.get("intent_id"), "99")


if __name__ == "__main__":
    unittest.main()
