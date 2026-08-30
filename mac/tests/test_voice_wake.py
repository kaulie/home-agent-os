"""Wake-word matching and session gate (no mic / STT)."""

from __future__ import annotations

import os
import queue
import unittest
from unittest.mock import patch

from mac_voice.audio.types import AudioUtterance
from mac_voice.listen import _CaptureActivity, _gate_transcript
from mac_voice.intent_poster import wake_echo_is_done
from mac_voice.wake import (
    WakeGate,
    WakeGatePool,
    command_after_ack_prefix,
    contains_ack_echo,
    extract_wake,
    looks_like_ack_echo,
    looks_like_light_command_echo,
    normalize,
    strip_ack_echo,
    wake_pool_key,
)


class NormalizeTests(unittest.TestCase):
    def test_spaces_punct_case(self) -> None:
        self.assertEqual(normalize("Mian Tiao!"), "miantiao")
        self.assertEqual(normalize("面条，开灯"), "面条开灯")


class ExtractWakeTests(unittest.TestCase):
    def test_two_pinyin_with_command(self) -> None:
        hits, remainder = extract_wake("面条 面条 开灯")
        self.assertEqual(hits, 2)
        self.assertEqual(remainder, "开灯")

    def test_glued_pinyin(self) -> None:
        hits, remainder = extract_wake("面条面条开灯")
        self.assertEqual(hits, 2)
        self.assertEqual(remainder, "开灯")

    def test_chinese_alias_four_chars(self) -> None:
        hits, remainder = extract_wake("棉条棉条")
        self.assertEqual(hits, 2)
        self.assertEqual(remainder, "")

    def test_mixed_alias_and_pinyin(self) -> None:
        hits, remainder = extract_wake("棉条 面条 现在几点")
        self.assertEqual(hits, 2)
        self.assertEqual(remainder, "现在几点")

    def test_one_is_not_enough(self) -> None:
        hits, remainder = extract_wake("面条")
        self.assertEqual(hits, 1)
        self.assertEqual(remainder, "")

    def test_chatter_zero_hits(self) -> None:
        hits, remainder = extract_wake("把灯打开")
        self.assertEqual(hits, 0)
        self.assertEqual(remainder, "把灯打开")

    def test_contains_two_with_filler(self) -> None:
        hits, remainder = extract_wake("面条，你听着，面条")
        self.assertEqual(hits, 2)
        self.assertIn("听", remainder)

    def test_contains_two_pinyin_with_filler(self) -> None:
        hits, remainder = extract_wake("先说 面条 然后再 面条")
        self.assertEqual(hits, 2)
        self.assertIn("先说", remainder)

    def test_mian_tiao_spaced(self) -> None:
        hits, remainder = extract_wake("mian tiao mian tiao")
        self.assertEqual(hits, 2)
        self.assertEqual(remainder, "")


class WakeGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = WakeGate(command_window_ms=3000, partial_wake_ms=2500)

    def _arm(self, t: float = 1.0) -> None:
        self.assertEqual(self.gate.state, "acking")
        self.gate.arm_after_ack(now=t)
        self.assertEqual(self.gate.state, "listening")

    def test_same_utterance_does_not_post_remainder(self) -> None:
        self.assertIsNone(self.gate.feed("面条 面条 开灯", now=0.0))
        self.assertEqual(self.gate.state, "acking")
        self.assertTrue(self.gate.should_ack)

    def test_alias_same_utterance_does_not_post(self) -> None:
        self.assertIsNone(self.gate.feed("棉条棉条关灯", now=0.0))
        self.assertEqual(self.gate.state, "acking")
        self.assertTrue(self.gate.should_ack)

    def test_filler_between_two_wakes_does_not_post(self) -> None:
        self.assertIsNone(self.gate.feed("面条你听着面条", now=0.0))
        self.assertEqual(self.gate.state, "acking")
        self.assertTrue(self.gate.should_ack)

    def test_command_during_ack_is_posted(self) -> None:
        """几点了 while 又咋了 is still playing / Brain is polling must POST."""
        self.assertIsNone(
            self.gate.feed("面条 面条", speech_start=0.0, speech_end=0.8)
        )
        self.assertEqual(self.gate.state, "acking")
        self.assertEqual(
            self.gate.feed("几点了？", speech_start=1.0, speech_end=2.0),
            "几点了？",
        )
        self.assertEqual(self.gate.state, "idle")

    def test_command_before_ack_is_posted(self) -> None:
        self.assertIsNone(
            self.gate.feed("面条 面条", speech_start=0.0, speech_end=0.8)
        )
        self.assertEqual(
            self.gate.feed("开灯", speech_start=1.0, speech_end=1.4),
            "开灯",
        )

    def test_next_utterance_within_3s_of_ack_is_command(self) -> None:
        self.assertIsNone(
            self.gate.feed(
                "面条 面条",
                now=0.0,
                speech_start=0.0,
                speech_end=0.8,
            )
        )
        self.assertTrue(self.gate.should_ack)
        self._arm(2.0)
        self.assertEqual(
            self.gate.feed(
                "开灯",
                now=10.0,
                speech_start=4.9,
                speech_end=5.2,
            ),
            "开灯",
        )
        self.assertEqual(self.gate.state, "idle")

    def test_next_utterance_after_3s_of_ack_is_dropped(self) -> None:
        self.assertIsNone(
            self.gate.feed(
                "面条 面条",
                now=0.0,
                speech_start=0.0,
                speech_end=0.0,
            )
        )
        self._arm(0.0)
        self.assertIsNone(
            self.gate.feed(
                "开灯",
                now=10.0,
                speech_start=3.1,
                speech_end=3.4,
            )
        )
        self.assertEqual(self.gate.state, "idle")

    def test_late_utterance_can_start_new_wake(self) -> None:
        self.assertIsNone(
            self.gate.feed("面条 面条", speech_start=0.0, speech_end=0.0)
        )
        self.assertIsNone(
            self.gate.feed(
                "面条 面条",
                speech_start=3.1,
                speech_end=3.5,
            )
        )
        self.assertEqual(self.gate.state, "acking")
        self.assertTrue(self.gate.should_ack)

    def test_two_utterances_then_command(self) -> None:
        self.assertIsNone(self.gate.feed("面条", now=0.0))
        self.assertEqual(self.gate.state, "partial")
        self.assertFalse(self.gate.should_ack)
        self.assertIsNone(self.gate.feed("面条", now=1.0))
        self.assertEqual(self.gate.state, "acking")
        self.assertTrue(self.gate.should_ack)
        self._arm(1.5)
        self.assertEqual(self.gate.feed("把空调打开", now=2.0), "把空调打开")
        self.assertEqual(self.gate.state, "idle")
        self.assertFalse(self.gate.should_ack)

    def test_two_wakes_one_utterance_acks(self) -> None:
        self.assertIsNone(self.gate.feed("面条 面条", now=0.0))
        self.assertEqual(self.gate.state, "acking")
        self.assertTrue(self.gate.should_ack)

    def test_stt_collapsed_double_wake_by_duration(self) -> None:
        self.assertIsNone(
            self.gate.feed(
                "面条。",
                now=0.0,
                speech_start=0.0,
                speech_end=2.1,
            )
        )
        self.assertEqual(self.gate.state, "acking")
        self.assertEqual(self.gate.last_hits, 2)
        self.assertTrue(self.gate.should_ack)

    def test_short_single_wake_stays_partial(self) -> None:
        self.assertIsNone(
            self.gate.feed(
                "面条。",
                now=0.0,
                speech_start=0.0,
                speech_end=0.5,
            )
        )
        self.assertEqual(self.gate.state, "partial")
        self.assertEqual(self.gate.last_hits, 1)
        self.assertFalse(self.gate.should_ack)

    def test_long_wake_plus_command_does_not_count_as_two(self) -> None:
        self.assertIsNone(
            self.gate.feed(
                "面条 开灯",
                now=0.0,
                speech_start=0.0,
                speech_end=2.5,
            )
        )
        self.assertEqual(self.gate.state, "partial")
        self.assertEqual(self.gate.last_hits, 1)

    def test_ack_echo_extends_listen_window_without_consuming(self) -> None:
        """又又咋了 is not a command; window restarts from when STT recognizes it."""
        self.assertIsNone(
            self.gate.feed("面条 面条", now=0.0, speech_start=0.0, speech_end=0.0)
        )
        self._arm(1.0)
        early = self.gate._deadline
        self.assertIsNone(
            self.gate.feed(
                "又又咋了？",
                now=1.4,
                speech_start=1.05,
                speech_end=1.4,
            )
        )
        self.assertEqual(self.gate.state, "listening")
        self.assertFalse(self.gate.should_ack)
        self.assertGreater(self.gate._deadline, early)
        self.assertAlmostEqual(self.gate._deadline, 1.4 + 3.0)
        self.assertEqual(
            self.gate.feed("开灯", now=4.6, speech_start=4.2, speech_end=4.6),
            "开灯",
        )

    def test_ack_echo_stt_latency_does_not_shrink_window(self) -> None:
        """STT of 又咋了 returns late; user still gets a full window from then."""
        self.assertIsNone(
            self.gate.feed("面条 面条", now=0.8, speech_start=0.0, speech_end=0.8)
        )
        self._arm(1.0)
        self.assertIsNone(
            self.gate.feed(
                "又又咋了？",
                now=2.8,
                speech_start=1.05,
                speech_end=1.4,
            )
        )
        self.assertAlmostEqual(self.gate._deadline, 2.8 + 3.0)
        self.assertEqual(
            self.gate.feed(
                "关闭台灯",
                now=5.5,
                speech_start=5.0,
                speech_end=5.8,
            ),
            "关闭台灯",
        )

    def test_late_stt_after_deadline_posts_if_speech_start_in_window(self) -> None:
        self.assertIsNone(
            self.gate.feed("面条 面条", speech_start=0.0, speech_end=0.8)
        )
        self._arm(1.0)
        self.assertEqual(self.gate.expire_if_needed(now=4.1), "command_window_expired")
        self.assertEqual(self.gate.state, "idle")
        self.assertEqual(
            self.gate.feed(
                "开灯",
                now=10.0,
                speech_start=3.5,
                speech_end=4.4,
            ),
            "开灯",
        )
        self.assertEqual(self.gate.state, "idle")

    def test_expire_held_during_in_progress_speech(self) -> None:
        self.assertIsNone(
            self.gate.feed("面条 面条", speech_start=0.0, speech_end=0.8)
        )
        self._arm(1.0)
        self.assertIsNone(self.gate.expire_if_needed(now=4.1, hold=True))
        self.assertEqual(self.gate.state, "listening")
        self.assertEqual(
            self.gate.feed("开灯", now=10.0, speech_start=3.8, speech_end=4.7),
            "开灯",
        )

    def test_arm_after_ack_does_not_shrink_echo_window(self) -> None:
        self.assertIsNone(
            self.gate.feed("面条 面条", now=0.8, speech_start=0.0, speech_end=0.8)
        )
        self.assertEqual(self.gate.state, "acking")
        self.assertIsNone(
            self.gate.feed("又咋了", now=1.5, speech_start=1.0, speech_end=1.5)
        )
        self.assertEqual(self.gate.state, "listening")
        opened = self.gate._window_open_at
        self.gate.arm_after_ack(now=1.2)
        self.assertEqual(self.gate._window_open_at, opened)
        self.assertEqual(
            self.gate.feed("开灯", now=4.4, speech_start=4.0, speech_end=4.4),
            "开灯",
        )

    def test_stt_doubled_ack_echo_never_posts(self) -> None:
        self.assertIsNone(
            self.gate.feed("面条 面条", now=0.8, speech_start=0.0, speech_end=0.8)
        )
        self._arm(1.0)
        self.assertIsNone(
            self.gate.feed(
                "又又咋了？",
                now=1.4,
                speech_start=1.05,
                speech_end=1.4,
            )
        )
        self.assertEqual(self.gate.state, "listening")
        self.assertEqual(
            self.gate.feed("关闭台灯", now=2.4, speech_start=1.6, speech_end=2.4),
            "关闭台灯",
        )

    def test_expire_if_needed_logs_empty_window(self) -> None:
        self.assertIsNone(
            self.gate.feed("面条 面条", speech_start=0.0, speech_end=0.8)
        )
        self._arm(1.0)
        self.assertIsNone(self.gate.expire_if_needed(now=3.9))
        self.assertEqual(self.gate.state, "listening")
        self.assertEqual(self.gate.expire_if_needed(now=4.1), "command_window_expired")
        self.assertEqual(self.gate.state, "idle")
        self.assertIsNone(self.gate.expire_if_needed(now=4.2))

    def test_tts_echo_misheard_as_command_is_dropped(self) -> None:
        """1392: Tingting「又咋了」被听成「拍照。」，开口在回复结束前，不能 POST。"""
        self.assertIsNone(
            self.gate.feed("面条 面条", speech_start=0.0, speech_end=0.8)
        )
        self._arm(2.0)
        self.assertIsNone(
            self.gate.feed(
                "拍照。",
                now=10.0,
                speech_start=1.2,
                speech_end=2.4,
            )
        )
        self.assertEqual(self.gate.state, "listening")
        self.assertEqual(
            self.gate.feed("开灯", speech_start=2.5, speech_end=2.9),
            "开灯",
        )

    def test_idle_hears_ack_echo_then_command(self) -> None:
        """STT missed 面条 but mic heard TTS 又咋了 mixed in; next 几点了 is the command."""
        self.assertIsNone(
            self.gate.feed(
                "他在他在家干嘛？又咋了？",
                now=1.2,
                speech_start=0.0,
                speech_end=1.2,
            )
        )
        self.assertEqual(self.gate.state, "listening")
        self.assertEqual(
            self.gate.feed(
                "几点几点了？",
                now=2.5,
                speech_start=1.5,
                speech_end=2.5,
            ),
            "几点几点了？",
        )

    def test_idle_standalone_ack_then_command(self) -> None:
        """TTS echo 又咋了 while idle still opens a window for 关闭台灯."""
        self.assertIsNone(
            self.gate.feed(
                "又又咋了？",
                now=1.0,
                speech_start=0.0,
                speech_end=0.8,
            )
        )
        self.assertEqual(self.gate.state, "listening")
        self.assertEqual(
            self.gate.feed(
                "关闭台灯",
                now=2.5,
                speech_start=1.6,
                speech_end=2.4,
            ),
            "关闭台灯",
        )

    def test_idle_same_clip_ack_then_command_posts(self) -> None:
        """又咋了 and 关闭台灯 in one STT line must POST the command."""
        self.assertEqual(
            self.gate.feed(
                "又又咋了？关闭台灯",
                now=2.0,
                speech_start=0.0,
                speech_end=2.0,
            ),
            "关闭台灯",
        )
        self.assertEqual(self.gate.state, "idle")

    def test_strips_trailing_ack_echo_from_command(self) -> None:
        self.assertIsNone(
            self.gate.feed("面条 面条", speech_start=0.0, speech_end=0.8)
        )
        self._arm(2.0)
        self.assertEqual(
            self.gate.feed("几点了？又咋了", speech_start=2.1, speech_end=3.0),
            "几点了",
        )

    def test_command_started_during_ack_but_finished_after_is_posted(self) -> None:
        """几点了 overlapping the last bit of 又咋了 must still POST."""
        self.assertIsNone(
            self.gate.feed("面条 面条", speech_start=0.0, speech_end=0.8)
        )
        self._arm(2.0)
        self.assertEqual(
            self.gate.feed(
                "几点了？",
                now=10.0,
                speech_start=1.8,
                speech_end=3.2,
            ),
            "几点了？",
        )

    def test_cross_utterance_wake_then_wait_for_command(self) -> None:
        self.assertIsNone(self.gate.feed("面条", now=0.0))
        self.assertIsNone(self.gate.feed("面条 开灯", now=1.0))
        self.assertEqual(self.gate.state, "acking")
        self.assertTrue(self.gate.should_ack)
        self._arm(1.5)
        self.assertEqual(self.gate.feed("开灯", now=2.0), "开灯")

    def test_partial_timeout(self) -> None:
        self.assertIsNone(self.gate.feed("面条", now=0.0))
        self.assertIsNone(self.gate.feed("面条", now=3.0))
        self.assertEqual(self.gate.state, "partial")
        self.assertIsNone(self.gate.feed("开灯", now=3.1))
        self.assertEqual(self.gate.state, "idle")

    def test_partial_non_wake_resets(self) -> None:
        self.assertIsNone(self.gate.feed("面条", now=0.0))
        self.assertIsNone(self.gate.feed("今天天气怎么样", now=0.5))
        self.assertEqual(self.gate.state, "idle")

    def test_chatter_never_posts(self) -> None:
        self.assertIsNone(self.gate.feed("电视声音真大", now=0.0))
        self.assertIsNone(self.gate.feed("帮我开灯", now=1.0))
        self.assertEqual(self.gate.state, "idle")

    def test_rewake_in_window(self) -> None:
        self.assertIsNone(self.gate.feed("面条 面条", now=0.0))
        self.assertIsNone(self.gate.feed("面条 面条", now=1.0))
        self.assertEqual(self.gate.state, "acking")
        self.assertTrue(self.gate.should_ack)
        self._arm(2.0)
        self.assertEqual(self.gate.feed("现在几点", now=2.5), "现在几点")

    def test_empty_stt_does_not_repeat_ack(self) -> None:
        self.assertIsNone(
            _gate_transcript(self.gate, "面条 面条", speech_start=0.0, speech_end=0.8)
        )
        self.assertTrue(self.gate.should_ack)
        self.assertTrue(self.gate.consume_ack())
        self.assertFalse(self.gate.should_ack)
        self.assertIsNone(_gate_transcript(self.gate, "", speech_start=1.5, speech_end=2.0))
        self.assertFalse(self.gate.should_ack)
        self.assertFalse(self.gate.consume_ack())
        self.assertEqual(self.gate.state, "acking")

    def test_gate_transcript_always_on(self) -> None:
        self.assertEqual(_gate_transcript(None, "随便说"), "随便说")
        self.assertIsNone(_gate_transcript(None, "  "))

    def test_gate_transcript_wake_mode(self) -> None:
        self.assertIsNone(_gate_transcript(self.gate, "闲聊"))
        self.assertIsNone(
            _gate_transcript(self.gate, "面条 面条", speech_end=0.0)
        )
        self._arm(0.5)
        self.assertEqual(
            _gate_transcript(self.gate, "开灯", speech_start=1.0, speech_end=1.4),
            "开灯",
        )


class WakeGatePoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = WakeGatePool(scope="participant", command_window_ms=3000)

    def _arm(self, gate: WakeGate, t: float = 1.0) -> None:
        self.assertEqual(gate.state, "acking")
        gate.arm_after_ack(now=t)
        self.assertEqual(gate.state, "listening")

    def test_key_prefers_participant(self) -> None:
        self.assertEqual(
            wake_pool_key(participant_id="phone-a", ingress="phone_hap1"),
            "pid:phone-a",
        )
        self.assertEqual(
            wake_pool_key(participant_id="", ingress="mac_usb"),
            "ingress:mac_usb",
        )
        self.assertEqual(wake_pool_key(scope="global"), "_global")

    def test_home_mic_cannot_ride_usb_window(self) -> None:
        usb = self.pool.get(participant_id="mac-1", ingress="mac_usb")
        phone = self.pool.get(participant_id="iphone-1", ingress="phone_hap1")
        self.assertIsNot(usb, phone)
        self.assertIsNone(usb.feed("面条面条", now=0.0, speech_start=0.0, speech_end=1.2))
        self._arm(usb, 1.5)
        # Phone speaks command inside USB's 5s window without waking.
        self.assertIsNone(
            phone.feed("开灯", now=2.0, speech_start=2.0, speech_end=2.4)
        )
        self.assertEqual(phone.state, "idle")
        self.assertEqual(
            usb.feed("开灯", now=2.0, speech_start=2.0, speech_end=2.4),
            "开灯",
        )

    def test_phone_own_wake_then_command(self) -> None:
        phone = self.pool.get(participant_id="iphone-1", ingress="phone_hap1")
        self.assertIsNone(phone.feed("面条面条", now=0.0, speech_start=0.0, speech_end=1.2))
        self._arm(phone, 1.5)
        self.assertEqual(
            phone.feed("几点了", now=2.0, speech_start=2.0, speech_end=2.5),
            "几点了",
        )

    def test_global_scope_shares_window(self) -> None:
        pool = WakeGatePool(scope="global", command_window_ms=3000)
        a = pool.get(participant_id="mac-1", ingress="mac_usb")
        b = pool.get(participant_id="iphone-1", ingress="phone_hap1")
        self.assertIs(a, b)
        self.assertIsNone(a.feed("面条面条", now=0.0, speech_start=0.0, speech_end=1.2))
        self._arm(a, 1.5)
        self.assertEqual(
            b.feed("开灯", now=2.0, speech_start=2.0, speech_end=2.4),
            "开灯",
        )

    def test_empty_participant_falls_back_to_ingress(self) -> None:
        usb = self.pool.get(participant_id="", ingress="mac_usb")
        phone = self.pool.get(participant_id="", ingress="phone_hap1")
        self.assertIsNot(usb, phone)
        self.assertEqual(
            self.pool.key_for(participant_id="", ingress="mac_usb"),
            "ingress:mac_usb",
        )


class ConfigDefaultTests(unittest.TestCase):
    def test_default_listen_mode_is_wake_word(self) -> None:
        from mac_voice.config import load_config

        env = {k: v for k, v in os.environ.items() if not k.startswith("MAC_VOICE_")}
        with patch("mac_voice.config._load_dotenv"), patch.dict("os.environ", env, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.listen_mode, "wake_word")
        self.assertEqual(cfg.wake_word, "面条")
        self.assertEqual(cfg.wake_repeat, 2)
        self.assertIn("棉条", cfg.wake_aliases)
        self.assertEqual(cfg.wake_ack, "我在呢")
        self.assertEqual(cfg.command_window_ms, 5000)
        self.assertEqual(cfg.double_wake_ms, 1100)
        self.assertEqual(cfg.wake_scope, "participant")
        self.assertEqual(cfg.phone_wake_silence_ms, 350)
        self.assertEqual(cfg.phone_wake_max_speech_ms, 2800)
        self.assertEqual(cfg.phone_command_silence_ms, 2000)
        self.assertEqual(cfg.phone_command_max_speech_ms, 12_000)

    def test_load_config_fetches_wake_ack_from_brain_when_env_unset(self) -> None:
        from mac_voice.config import load_config

        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("MAC_VOICE_")
        }
        env["MAC_VOICE_BRAIN_URL"] = "http://brain.test:9527"
        with patch("mac_voice.config._load_dotenv"), patch.dict("os.environ", env, clear=True):
            with patch(
                "mac_voice.config._brain_wake_ack",
                return_value="来了",
            ):
                cfg = load_config()
        self.assertEqual(cfg.wake_ack, "来了")


class PipelineWakeAckTests(unittest.TestCase):
    def test_handle_transcript_skips_ack_phrase(self) -> None:
        from mac_voice.pipeline import handle_transcript

        cfg = object()
        with patch("mac_voice.pipeline.post_intent") as posted:
            self.assertIsNone(handle_transcript(cfg, "又咋了", post=True))  # type: ignore[arg-type]
            self.assertIsNone(handle_transcript(cfg, "又咋了？", post=True))  # type: ignore[arg-type]
            self.assertIsNone(handle_transcript(cfg, "又又咋了？", post=True))  # type: ignore[arg-type]
            posted.assert_not_called()

    def test_handle_transcript_posts_real_command(self) -> None:
        from mac_voice.pipeline import handle_transcript

        cfg = object()
        with patch("mac_voice.pipeline.require_parent_edge_id", return_value="mac-1"):
            with patch(
                "mac_voice.pipeline.post_intent",
                return_value={"ok": True, "intent_id": 9},
            ) as posted:
                out = handle_transcript(cfg, "几点了", post=True)  # type: ignore[arg-type]
        self.assertEqual(out["intent_id"], 9)
        posted.assert_called_once()

    def test_handle_wake_is_local_echo_not_an_intent(self) -> None:
        from mac_voice.pipeline import handle_wake

        cfg = type("Cfg", (), {"wake_ack": "又咋了"})()
        with patch("mac_edge.plugins.voicewakeup_echo.echo", return_value="又咋了") as echoed:
            with patch("mac_voice.pipeline.post_intent") as posted:
                out = handle_wake(cfg, post=True)  # type: ignore[arg-type]
        self.assertEqual(out, {"ok": True, "echo_text": "又咋了", "local": True})
        echoed.assert_called_once_with("又咋了")
        posted.assert_not_called()

    def test_handle_wake_phone_hap1_speaks_on_phone(self) -> None:
        from mac_voice.pipeline import handle_wake

        cfg = type("Cfg", (), {"wake_ack": "我在呢"})()

        class FakeIngest:
            def send_speak(self, text: str, participant_id: str = "") -> int:
                return 1

        with patch("mac_voice.pipeline.get_active_ingest", return_value=FakeIngest()):
            with patch("mac_edge.plugins.voicewakeup_echo.echo") as echoed:
                out = handle_wake(
                    cfg, post=True, ingress="phone_hap1", participant_id="phone-1"
                )  # type: ignore[arg-type]
        self.assertEqual(out.get("phone_hap1"), True)
        self.assertFalse(out.get("local"))
        echoed.assert_not_called()


class WakeEchoDoneTests(unittest.TestCase):
    def test_intent_succeeded(self) -> None:
        self.assertTrue(wake_echo_is_done({"status": "succeeded"}))
        self.assertTrue(wake_echo_is_done({"intent_status": "failed"}))
        self.assertFalse(wake_echo_is_done({"status": "running"}))

    def test_echo_step_status(self) -> None:
        self.assertTrue(
            wake_echo_is_done(
                {"execution_plan": [{"capability": "voicewakeup.echo", "status": 2}]}
            )
        )
        self.assertFalse(
            wake_echo_is_done(
                {"execution_plan": [{"capability": "voicewakeup.echo", "status": 1}]}
            )
        )


class AckEchoTests(unittest.TestCase):
    def test_variants(self) -> None:
        self.assertTrue(looks_like_ack_echo("又咋了"))
        self.assertTrue(looks_like_ack_echo("又又咋了？"))
        self.assertTrue(looks_like_ack_echo("又又咋了"))
        self.assertTrue(looks_like_ack_echo("我在呢"))
        self.assertTrue(looks_like_ack_echo("在呢。"))
        self.assertTrue(looks_like_ack_echo("咋了"))
        self.assertFalse(looks_like_ack_echo("开灯"))
        self.assertFalse(looks_like_ack_echo("关闭台灯"))
        self.assertFalse(looks_like_ack_echo("拍照。"))
        self.assertFalse(looks_like_ack_echo("他在他在家干嘛？又咋了？"))

    def test_light_command_echo(self) -> None:
        self.assertTrue(looks_like_light_command_echo("关灯"))
        self.assertTrue(looks_like_light_command_echo("开灯"))
        self.assertTrue(looks_like_light_command_echo("小书小书"))
        self.assertFalse(looks_like_light_command_echo("关闭台灯"))
        self.assertFalse(looks_like_light_command_echo("咱们去睡觉"))
        self.assertTrue(contains_ack_echo("他在他在家干嘛？又咋了？"))
        self.assertEqual(strip_ack_echo("他在他在家干嘛？又咋了？"), "他在他在家干嘛")
        self.assertEqual(strip_ack_echo("几点了？又咋了"), "几点了")
        self.assertEqual(command_after_ack_prefix("又又咋了？关闭台灯"), "关闭台灯")
        self.assertEqual(command_after_ack_prefix("又咋了"), "")
        self.assertEqual(command_after_ack_prefix("他在他在家干嘛？又咋了？"), "")


class ListenQueueTests(unittest.TestCase):
    def test_put_latest_keeps_newest_on_overflow(self) -> None:
        from mac_voice.listen import _put_latest

        q: queue.Queue = queue.Queue(maxsize=2)
        a = AudioUtterance.from_pcm(b"\x00\x00" * 8)
        b = AudioUtterance.from_pcm(b"\x01\x00" * 8)
        c = AudioUtterance.from_pcm(b"\x02\x00" * 16)
        _put_latest(q, a)
        _put_latest(q, b)
        _put_latest(q, c)
        self.assertEqual(q.qsize(), 1)
        kept = q.get_nowait()
        self.assertIs(kept, c)

    def test_stale_uses_speech_end(self) -> None:
        from mac_voice.listen import _is_stale

        fresh = AudioUtterance.from_pcm(b"\x00\x00", speech_end=10.0)
        old = AudioUtterance.from_pcm(b"\x00\x00", speech_end=1.0)
        self.assertFalse(_is_stale(fresh, 10.5))
        self.assertTrue(_is_stale(old, 10.0))
        self.assertFalse(_is_stale(AudioUtterance.from_pcm(b"\x00\x00"), 99.0))

    def test_hold_outlasts_silence_cut(self) -> None:
        activity = _CaptureActivity()
        activity.last_high_mono = 10.0
        self.assertTrue(activity.should_hold(10.9, silence_s=1.0))
        self.assertTrue(activity.should_hold(11.3, silence_s=1.0))
        self.assertFalse(activity.should_hold(11.4, silence_s=1.0))
        activity.in_speech = True
        self.assertTrue(activity.should_hold(20.0, silence_s=1.0))
        activity.in_speech = False
        self.assertTrue(activity.should_hold(11.0, queued=1, silence_s=1.0))


if __name__ == "__main__":
    unittest.main()
