"""Shortcut / Mode intercept unit tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import db as brain_db  # noqa: E402
from shortcut_mode import intercept  # noqa: E402
from shortcut_mode.state import enter_mode, exit_mode, get_active_mode  # noqa: E402


class ShortcutModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def test_enter_and_exit_triggers(self) -> None:
        hit = intercept("帮我开启阅读模式")
        assert hit is not None
        self.assertEqual(hit.kind, "enter_mode")
        self.assertEqual(hit.mode, "reading")
        self.assertEqual(hit.plan[0]["capability"], "notify.speak")

        hit = intercept("关闭阅读模式吧")
        assert hit is not None
        self.assertEqual(hit.kind, "exit_mode")

    def test_reading_pipeline_requires_active_mode(self) -> None:
        self.assertIsNone(intercept("这个字怎么读"))
        enter_mode("reading")
        hit = intercept("这个字怎么读")
        assert hit is not None
        self.assertEqual(hit.kind, "plan")
        caps = [s["capability"] for s in hit.plan]
        self.assertEqual(
            caps,
            [
                "camera.capture_and_upload",
                "reading.point_to_character",
                "notify.speak",
            ],
        )

    def test_reading_existing_photo_skips_capture(self) -> None:
        enter_mode("reading")
        hit = intercept("看下最新的一张照片里手指的那个字是什么")
        assert hit is not None
        self.assertEqual(hit.kind, "plan")
        caps = [s["capability"] for s in hit.plan]
        self.assertEqual(
            caps,
            [
                "asset.inventory",
                "reading.point_to_character",
                "notify.speak",
            ],
        )
        inv = hit.plan[0]["input_constrict"]
        self.assertEqual(inv.get("type"), "image")
        self.assertEqual(inv.get("order"), "newest_first")
        self.assertEqual(inv.get("index"), 1)
        oc = hit.plan[0]["output_constrict"]["asset_ref"]
        self.assertEqual(oc.get("data_dest"), "context")

    def test_unrelated_utterance_in_reading_mode_returns_none(self) -> None:
        enter_mode("reading")
        self.assertIsNone(intercept("开一下灯"))

    def test_prepare_shortcut_plan_keeps_notify_speak(self) -> None:
        import home_brain as hb
        from shortcut_mode import reading

        intent = {"text": "开启阅读模式", "source": "voice", "edge_id": "mac-edge"}
        plan = hb._prepare_shortcut_execution_plan(reading.READING_ENTER_PLAN, intent)
        self.assertEqual([s["capability"] for s in plan], ["notify.speak"])
        self.assertEqual(plan[0]["input_constrict"]["text"], "好的，已进入阅读模式。")

    def test_exit_clears_active_mode(self) -> None:
        enter_mode("reading")
        self.assertEqual(get_active_mode(), "reading")
        exit_mode("reading")
        self.assertIsNone(get_active_mode())


if __name__ == "__main__":
    unittest.main()
