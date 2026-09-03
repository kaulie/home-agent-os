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

    def _music_ic(self, text: str) -> dict:
        hit = intercept(text)
        assert hit is not None
        self.assertEqual(hit.kind, "plan")
        self.assertIsNone(hit.mode)
        self.assertEqual(hit.plan[0]["capability"], "music.play")
        self.assertEqual(hit.planner_meta.get("source"), "shortcut")
        timing = (hit.planner_meta or {}).get("timing") or {}
        self.assertIn("match", timing)
        return hit.plan[0]["input_constrict"]

    def test_music_play_keeps_full_remainder_as_song(self) -> None:
        ic = self._music_ic("播放陈奕迅的十年")
        self.assertEqual(ic["song"], "陈奕迅的十年")
        self.assertEqual(ic["user_input"], "播放陈奕迅的十年")
        self.assertNotIn("artist", ic)

    def test_music_play_xxx_de_ge_keeps_song_not_artist(self) -> None:
        ic = self._music_ic("播放张三的歌")
        self.assertEqual(ic["song"], "张三的歌")
        self.assertEqual(ic["user_input"], "播放张三的歌")
        self.assertNotIn("artist", ic)

        ic = self._music_ic("听听陈奕迅的歌")
        self.assertEqual(ic["song"], "陈奕迅的歌")
        self.assertNotIn("artist", ic)

        ic = self._music_ic("听一下周杰伦的歌曲")
        self.assertEqual(ic["song"], "周杰伦的歌曲")
        self.assertNotIn("artist", ic)

    def test_music_play_strips_leading_quantity(self) -> None:
        ic = self._music_ic("放几首周杰伦的歌")
        self.assertEqual(ic["song"], "周杰伦的歌")
        self.assertEqual(ic["count"], 5)
        self.assertEqual(ic["user_input"], "放几首周杰伦的歌")

        ic = self._music_ic("放3首五月天的歌")
        self.assertEqual(ic["song"], "五月天的歌")
        self.assertEqual(ic["count"], 3)

        ic = self._music_ic("听几首周杰伦的歌")
        self.assertEqual(ic["song"], "周杰伦的歌")
        self.assertEqual(ic["count"], 5)

    def test_music_play_without_de_particle(self) -> None:
        ic = self._music_ic("播放陈奕迅十年")
        self.assertEqual(ic["song"], "陈奕迅十年")
        self.assertEqual(ic["user_input"], "播放陈奕迅十年")

    def test_music_play_fang_prefix(self) -> None:
        ic = self._music_ic("放十年")
        self.assertEqual(ic["song"], "十年")
        self.assertEqual(ic["user_input"], "放十年")

    def test_music_listen_triggers_without_song(self) -> None:
        for text in (
            "听歌",
            "听听歌",
            "听会歌",
            "听下歌",
            "听听",
            "听下",
            "听一下",
            "听歌曲",
            "放歌曲",
            "播歌曲",
        ):
            with self.subTest(text=text):
                ic = self._music_ic(text)
                self.assertNotIn("song", ic)
                self.assertEqual(ic["user_input"], text)

    def test_music_short_verbs_xxx_de_ge(self) -> None:
        for text, song in (
            ("听张三的歌", "张三的歌"),
            ("播周杰伦的歌", "周杰伦的歌"),
            ("放陈奕迅的歌", "陈奕迅的歌"),
            ("听周杰伦的歌曲", "周杰伦的歌曲"),
            ("播张三的歌曲", "张三的歌曲"),
        ):
            with self.subTest(text=text):
                ic = self._music_ic(text)
                self.assertEqual(ic["song"], song)
                self.assertNotIn("artist", ic)

    def test_music_trailing_punct_playlist(self) -> None:
        ic = self._music_ic("听刘德华的歌。")
        self.assertEqual(ic["song"], "刘德华的歌")
        ic = self._music_ic("听歌曲。")
        self.assertNotIn("song", ic)
        ic = self._music_ic("播周杰伦的歌！")
        self.assertEqual(ic["song"], "周杰伦的歌")
        self.assertIsNone(intercept("听天气预报"))
        self.assertIsNone(intercept("听十年"))
        self.assertIsNone(intercept("播新闻"))

    def test_music_listen_yixia_with_remainder(self) -> None:
        ic = self._music_ic("听一下十年")
        self.assertEqual(ic["song"], "十年")
        self.assertEqual(ic["user_input"], "听一下十年")

    def test_music_excludes_slideshow_and_unrelated(self) -> None:
        self.assertIsNone(intercept("播放幻灯片"))
        self.assertIsNone(intercept("播放视频"))
        self.assertIsNone(intercept("开灯"))
        self.assertIsNone(intercept("这首歌曲叫什么"))

    def _music_ctrl(self, text: str, capability: str) -> dict:
        hit = intercept(text)
        assert hit is not None
        self.assertEqual(hit.kind, "plan")
        self.assertIsNone(hit.mode)
        self.assertEqual(hit.plan[0]["capability"], capability)
        self.assertEqual(hit.planner_meta.get("source"), "shortcut")
        timing = (hit.planner_meta or {}).get("timing") or {}
        self.assertIn("match", timing)
        return hit.plan[0]["input_constrict"]

    def test_music_control_before_play(self) -> None:
        cases = (
            ("暂停播放", "music.pause"),
            ("暂停歌曲", "music.pause"),
            ("继续播放", "music.resume"),
            ("恢复播放", "music.resume"),
            ("切歌", "music.next"),
            ("下一首歌", "music.next"),
            ("停止播放", "music.stop"),
            ("上一首", "music.previous"),
            ("上一首歌", "music.previous"),
        )
        for text, cap in cases:
            with self.subTest(text=text):
                ic = self._music_ctrl(text, cap)
                self.assertEqual(ic["user_input"], text)
                self.assertNotIn("song", ic)

    def test_music_control_collapses_asr_duplicate_chars(self) -> None:
        ic = self._music_ctrl("继继续播放。", "music.resume")
        self.assertEqual(ic["user_input"], "继继续播放。")
        self.assertNotIn("song", ic)

        ic = self._music_ctrl("继继续播放", "music.resume")
        self.assertEqual(ic["user_input"], "继继续播放")

    def test_music_control_skips_ambiguous_play(self) -> None:
        self.assertIsNone(intercept("播放"))

    def _music_cache(self, text: str) -> dict:
        hit = intercept(text)
        assert hit is not None
        self.assertEqual(hit.kind, "plan")
        self.assertIsNone(hit.mode)
        self.assertEqual(hit.plan[0]["capability"], "music.cache")
        self.assertEqual(hit.planner_meta.get("source"), "shortcut")
        timing = (hit.planner_meta or {}).get("timing") or {}
        self.assertIn("match", timing)
        return hit.plan[0]["input_constrict"]

    def test_music_cache_playlist_default_count_omitted(self) -> None:
        ic = self._music_cache("下载刘德华的歌")
        self.assertEqual(ic["song"], "刘德华的歌")
        self.assertEqual(ic["user_input"], "下载刘德华的歌")
        self.assertNotIn("count", ic)
        self.assertNotIn("artist", ic)

        ic = self._music_cache("请帮我下载刘德华的歌。")
        self.assertEqual(ic["song"], "刘德华的歌")

        ic = self._music_cache("缓存周杰伦的歌曲")
        self.assertEqual(ic["song"], "周杰伦的歌曲")
        self.assertNotIn("count", ic)

    def test_music_cache_playlist_count(self) -> None:
        ic = self._music_cache("下载刘德华的歌50首")
        self.assertEqual(ic["song"], "刘德华的歌")
        self.assertEqual(ic["count"], 50)
        ic = self._music_cache("缓存刘德华的歌 20 首")
        self.assertEqual(ic["song"], "刘德华的歌")
        self.assertEqual(ic["count"], 20)

    def test_music_cache_song_prefix(self) -> None:
        ic = self._music_cache("缓存歌曲冰雨")
        self.assertEqual(ic["song"], "冰雨")
        self.assertEqual(ic["user_input"], "缓存歌曲冰雨")
        self.assertNotIn("count", ic)
        ic = self._music_cache("下载歌曲十年")
        self.assertEqual(ic["song"], "十年")

    def test_music_cache_does_not_steal_play(self) -> None:
        ic = self._music_ic("听刘德华的歌")
        self.assertEqual(ic["song"], "刘德华的歌")

    def test_music_cache_rejects_bare_and_unrelated(self) -> None:
        self.assertIsNone(intercept("下载歌曲"))
        self.assertIsNone(intercept("缓存歌曲"))
        self.assertIsNone(intercept("下载"))
        self.assertIsNone(intercept("下载冰雨"))
        self.assertIsNone(intercept("下载天气预报"))
        self.assertIsNone(intercept("下载幻灯片"))

    def _rule_hit(self, text: str, *, rule: str, goal: str) -> list[dict]:
        hit = intercept(text)
        assert hit is not None
        self.assertEqual(hit.kind, "plan")
        self.assertIsNone(hit.mode)
        self.assertEqual(hit.planner_meta.get("source"), "shortcut")
        self.assertEqual(hit.planner_meta.get("rule"), rule)
        self.assertEqual(hit.planner_meta.get("goal"), goal)
        timing = (hit.planner_meta or {}).get("timing") or {}
        self.assertIn("match", timing)
        return hit.plan

    def test_clock_now_shortcut(self) -> None:
        for text in ("现在几点了", "几点了", "帮我报时"):
            with self.subTest(text=text):
                plan = self._rule_hit(text, rule="clock_now", goal="clock.now")
                self.assertEqual(plan[0]["capability"], "clock.now")
                self.assertEqual(plan[0]["output_constrict"], {"time_text": {}})
                hit = intercept(text)
                assert hit is not None
                self.assertEqual(hit.presentation, {"type": "audio", "from": "time_text"})

    def test_clock_now_skips_schedule_questions(self) -> None:
        self.assertIsNone(intercept("明天几点开会"))

    def test_climate_on_off_shortcut(self) -> None:
        plan = self._rule_hit("打开客厅空调", rule="climate_on", goal="climate.set")
        self.assertEqual(plan[0]["capability"], "climate.set")
        self.assertEqual(plan[0]["input_constrict"], {"power": "on", "appliance": "客厅空调"})

        plan = self._rule_hit("关掉儿童房空调", rule="climate_off_on", goal="climate.set")
        self.assertEqual(plan[0]["input_constrict"]["power"], "off")
        self.assertEqual(plan[0]["input_constrict"]["appliance"], "儿童房空调")

    def test_climate_skips_complex_adjustments(self) -> None:
        self.assertIsNone(intercept("打开客厅空调，风速调为最大"))

    def test_photo_latest_view_shortcut(self) -> None:
        plan = self._rule_hit("看最新照片", rule="photo_latest", goal="latest photo")
        self.assertEqual([s["capability"] for s in plan], ["asset.inventory"])
        inv = plan[0]["input_constrict"]
        self.assertEqual(inv.get("type"), "image")
        self.assertEqual(inv.get("order"), "newest_first")
        self.assertEqual(inv.get("index"), 1)
        hit = intercept("看最新照片")
        assert hit is not None
        self.assertEqual(hit.presentation, {"type": "image", "from": "asset_ref"})

    def test_photo_latest_cast_shortcut(self) -> None:
        plan = self._rule_hit(
            "把最新照片投到电视上",
            rule="photo_latest_cast",
            goal="latest photo",
        )
        self.assertEqual(
            [s["capability"] for s in plan],
            ["asset.inventory", "display.photo"],
        )
        self.assertEqual(plan[1]["input_constrict"]["asset_ref"], "$asset_ref")

    def test_photo_latest_defers_to_reading_pipeline(self) -> None:
        enter_mode("reading")
        hit = intercept("看下最新的一张照片里手指的那个字是什么")
        assert hit is not None
        self.assertEqual(hit.planner_meta.get("goal"), "reading existing photo pipeline")

        hit = intercept("最新照片里这个字怎么读")
        assert hit is not None
        self.assertEqual(hit.mode, "reading")
        self.assertEqual(hit.planner_meta.get("goal"), "reading existing photo pipeline")

    def test_photo_latest_skips_counting(self) -> None:
        self.assertIsNone(intercept("我今天拍了几张照片"))


if __name__ == "__main__":
    unittest.main()
