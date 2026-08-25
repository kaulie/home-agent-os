"""Unit tests for mac_voice audio + STT helpers (no network)."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_voice.audio.segmenter import (
    _is_trailing_quiet,
    _looks_ambient,
    iter_utterances,
)
from mac_voice.audio.types import AudioUtterance, PCM_16K_MONO
from mac_voice.stt.volc_sauc import VolcengineSaucSTT, _text_from_payload


def _pcm_chunk(amp: int, ms: int = 100) -> bytes:
    n = 16 * ms  # 16 kHz
    return struct.pack(f"<{n}h", *([amp] * n))


class AudioUtteranceTests(unittest.TestCase):
    def test_roundtrip_wav(self) -> None:
        pcm = b"\x00\x01" * 1600
        utt = AudioUtterance.from_pcm(pcm, format=PCM_16K_MONO)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "t.wav"
            utt.materialize_wav(path)
            loaded = AudioUtterance.from_wav_path(path)
            self.assertEqual(loaded.format.sample_rate, 16000)
            self.assertEqual(loaded.format.channels, 1)
            self.assertEqual(loaded.ensure_pcm(), pcm)


class SaucTextExtractTests(unittest.TestCase):
    def test_result_text(self) -> None:
        self.assertEqual(
            _text_from_payload({"result": {"text": "打开客厅空调，退出。"}}),
            "打开客厅空调，退出。",
        )

    def test_empty(self) -> None:
        self.assertEqual(_text_from_payload({"result": {"text": ""}}), "")
        self.assertEqual(_text_from_payload(None), "")

    def test_utterances_when_result_text_empty(self) -> None:
        self.assertEqual(
            _text_from_payload(
                {
                    "result": {
                        "text": "",
                        "utterances": [
                            {"text": "面条，", "definite": True},
                            {"text": "面条。", "definite": True},
                        ],
                    }
                }
            ),
            "面条，面条。",
        )

    def test_ddc_off_so_repeated_wake_survives(self) -> None:
        stt = VolcengineSaucSTT(api_key="x", url="wss://x", resource_id="x")
        req = stt._payload(16000)
        self.assertFalse(req["request"]["enable_ddc"])
        self.assertTrue(req["request"]["enable_nonstream"])
        self.assertEqual(req["audio"]["format"], "pcm")


class SegmenterTests(unittest.TestCase):
    def test_silence_cut(self) -> None:
        loud = _pcm_chunk(12000)
        quiet = _pcm_chunk(0)
        chunks = [loud] * 5 + [quiet] * 10  # ~0.5s speech + 1s silence
        utts = list(
            iter_utterances(
                chunks,
                energy_threshold=100.0,
                start_threshold=300.0,
                silence_ms=500,
                min_speech_ms=200,
                max_speech_ms=8000,
                pre_roll_ms=0,
            )
        )
        self.assertEqual(len(utts), 1)
        self.assertGreater(len(utts[0].ensure_pcm()), 0)
        self.assertIsNotNone(utts[0].speech_start)
        self.assertIsNotNone(utts[0].speech_end)
        self.assertGreaterEqual(utts[0].speech_end, utts[0].speech_start)

    def test_floor_rumble_never_queued(self) -> None:
        rumble = _pcm_chunk(800)
        utts = list(
            iter_utterances(
                [rumble] * 20,
                energy_threshold=500.0,
                start_threshold=1500.0,
                silence_ms=500,
                min_speech_ms=200,
                max_speech_ms=8000,
                pre_roll_ms=0,
            )
        )
        self.assertEqual(utts, [])

    def test_mid_drone_dropped_before_max(self) -> None:
        drone = _pcm_chunk(1800)
        utts = list(
            iter_utterances(
                [drone] * 30,
                energy_threshold=500.0,
                start_threshold=1500.0,
                silence_ms=500,
                min_speech_ms=200,
                max_speech_ms=8000,
                ambient_abort_ms=700,
                pre_roll_ms=0,
            )
        )
        self.assertEqual(utts, [])

    def test_voice_peak_is_queued(self) -> None:
        voice = _pcm_chunk(8000)
        quiet = _pcm_chunk(0)
        utts = list(
            iter_utterances(
                [voice] * 6 + [quiet] * 8,
                energy_threshold=500.0,
                start_threshold=1500.0,
                silence_ms=500,
                min_speech_ms=200,
                max_speech_ms=8000,
                pre_roll_ms=0,
            )
        )
        self.assertEqual(len(utts), 1)

    def test_looks_ambient(self) -> None:
        self.assertTrue(_looks_ambient(800, 700, 1500))
        self.assertTrue(_looks_ambient(1800, 1700, 1500))
        self.assertFalse(_looks_ambient(5000, 1800, 1500))
        self.assertFalse(_looks_ambient(12000, 12000, 1500))

    def test_trailing_quiet_after_voice_peak(self) -> None:
        self.assertTrue(_is_trailing_quiet(170, 8536, 500.0, 1500.0))
        # 1892 is still above start_th — a follow-up 开灯, not HVAC.
        self.assertFalse(_is_trailing_quiet(1892, 8536, 500.0, 1500.0))
        self.assertTrue(_is_trailing_quiet(1892, 8536, 500.0, 1500.0, floor_rms=1700.0))
        self.assertFalse(_is_trailing_quiet(1892, 1892, 500.0, 1500.0))
        self.assertFalse(_is_trailing_quiet(5000, 8536, 500.0, 1500.0))
        self.assertTrue(_is_trailing_quiet(800, 2548, 500.0, 1000.0, floor_rms=700.0))
        # Loud TTS peak must not swallow a quieter command.
        self.assertFalse(_is_trailing_quiet(2500, 15948, 500.0, 1000.0))

    def test_short_loud_command_queued_above_hvac_floor(self) -> None:
        """开灯 ~1s at peak ~2200 with HVAC ~800 > energy_threshold=500 must queue."""
        hvac = _pcm_chunk(800)
        voice = _pcm_chunk(2200)
        chunks = [hvac] * 5 + [voice] * 10 + [hvac] * 12
        utts = list(
            iter_utterances(
                chunks,
                energy_threshold=500.0,
                start_threshold=1000.0,
                silence_ms=500,
                min_speech_ms=400,
                max_speech_ms=8000,
                pre_roll_ms=200,
            )
        )
        self.assertEqual(len(utts), 1)
        self.assertGreaterEqual(
            len(utts[0].ensure_pcm()) / (16000 * 2),
            0.4,
        )

    def test_short_command_after_ack_echo_energy_is_queued(self) -> None:
        """Same shape as live: echo already done, then one ~1s 开灯, HVAC floor."""
        hvac = _pcm_chunk(700)
        command = _pcm_chunk(2500)
        chunks = [hvac] * 8 + [command] * 9 + [hvac] * 10
        utts = list(
            iter_utterances(
                chunks,
                energy_threshold=500.0,
                start_threshold=1000.0,
                silence_ms=400,
                min_speech_ms=400,
                max_speech_ms=8000,
                pre_roll_ms=0,
            )
        )
        self.assertEqual(len(utts), 1)

    def test_one_second_command_queued_after_hvac_abort(self) -> None:
        rumble = _pcm_chunk(1800)
        voice = _pcm_chunk(8000)
        quiet = _pcm_chunk(0)
        chunks = [rumble] * 20 + [voice] * 10 + [quiet] * 12
        utts = list(
            iter_utterances(
                chunks,
                energy_threshold=500.0,
                start_threshold=1500.0,
                silence_ms=500,
                min_speech_ms=400,
                max_speech_ms=8000,
                ambient_abort_ms=700,
                pre_roll_ms=0,
            )
        )
        self.assertEqual(len(utts), 1)

    def test_loud_command_cut_when_back_to_hvac(self) -> None:
        rumble = _pcm_chunk(1800)
        voice = _pcm_chunk(8000)
        chunks = [rumble] * 2 + [voice] * 10 + [rumble] * 12
        utts = list(
            iter_utterances(
                chunks,
                energy_threshold=500.0,
                start_threshold=1500.0,
                silence_ms=500,
                min_speech_ms=400,
                max_speech_ms=8000,
                pre_roll_ms=0,
            )
        )
        self.assertEqual(len(utts), 1)

    def test_followup_command_after_loud_tts_peak_is_kept(self) -> None:
        """又咋了 ~16k then 关闭台灯 ~2500 must stay in the clip (or a second one)."""
        tts = _pcm_chunk(16000)
        command = _pcm_chunk(2500)
        quiet = _pcm_chunk(0)
        chunks = [tts] * 6 + [command] * 8 + [quiet] * 12
        utts = list(
            iter_utterances(
                chunks,
                energy_threshold=500.0,
                start_threshold=1000.0,
                silence_ms=500,
                min_speech_ms=400,
                max_speech_ms=8000,
                pre_roll_ms=0,
            )
        )
        self.assertGreaterEqual(len(utts), 1)
        total_s = sum(len(u.ensure_pcm()) for u in utts) / (16000 * 2)
        self.assertGreaterEqual(total_s, 1.0)

    def test_muted_drops_loud_speech(self) -> None:
        voice = _pcm_chunk(8000)
        quiet = _pcm_chunk(0)
        hold = {"on": True}

        def muted() -> bool:
            return hold["on"]

        utts = list(
            iter_utterances(
                [voice] * 8 + [quiet] * 8,
                energy_threshold=500.0,
                start_threshold=1500.0,
                silence_ms=500,
                min_speech_ms=200,
                max_speech_ms=8000,
                pre_roll_ms=0,
                muted=muted,
            )
        )
        self.assertEqual(utts, [])
        hold["on"] = False
        utts = list(
            iter_utterances(
                [voice] * 6 + [quiet] * 8,
                energy_threshold=500.0,
                start_threshold=1500.0,
                silence_ms=500,
                min_speech_ms=200,
                max_speech_ms=8000,
                pre_roll_ms=0,
                muted=muted,
            )
        )
        self.assertEqual(len(utts), 1)


class ResolveInputDeviceTests(unittest.TestCase):
    _devs = (
        {"name": "MacBook Pro麦克风", "max_input_channels": 1},
        {"name": "reSpeaker XVF3800 4-Mic Array", "max_input_channels": 2},
        {"name": "MacBook Pro扬声器", "max_input_channels": 0},
    )

    def test_exact_name_to_index(self) -> None:
        from mac_voice.audio.source import resolve_input_device

        self.assertEqual(
            resolve_input_device(
                "reSpeaker XVF3800 4-Mic Array",
                devices=list(self._devs),
            ),
            1,
        )

    def test_respeaker_name_mismatch_still_finds_usb(self) -> None:
        from mac_voice.audio.source import resolve_input_device

        self.assertEqual(
            resolve_input_device(
                "reSpeaker XVF3800 4 Mic Array",
                devices=list(self._devs),
            ),
            1,
        )

    def test_missing_raises_with_catalog(self) -> None:
        from mac_voice.audio.source import resolve_input_device

        with self.assertRaises(ValueError) as ctx:
            resolve_input_device("Ghost Mic", devices=list(self._devs))
        self.assertIn("MacBook Pro麦克风", str(ctx.exception))

    def test_empty_catalog_raises_none(self) -> None:
        from mac_voice.audio.source import resolve_input_device

        with self.assertRaises(ValueError) as ctx:
            resolve_input_device(
                "reSpeaker XVF3800 4-Mic Array",
                devices=[],
            )
        self.assertIn("(none)", str(ctx.exception))

    def test_empty_catalog_uses_fallback_index(self) -> None:
        from mac_voice.audio.source import resolve_input_device

        self.assertEqual(
            resolve_input_device(
                "reSpeaker XVF3800 4-Mic Array",
                devices=[],
                fallback_index=0,
            ),
            0,
        )

    def test_live_query_reinitializes_when_empty(self) -> None:
        from mac_voice.audio import source as src

        class _FakeSd:
            n = 0

            def query_devices(self):
                type(self).n += 1
                if type(self).n == 1:
                    return []
                return [
                    {
                        "name": "reSpeaker XVF3800 4-Mic Array",
                        "max_input_channels": 2,
                    }
                ]

            def _terminate(self) -> None:
                return

            def _initialize(self) -> None:
                return

        fake = _FakeSd()
        with patch.dict("sys.modules", {"sounddevice": fake}):
            catalog = src._input_catalog(None)
        self.assertEqual(catalog, [(0, "reSpeaker XVF3800 4-Mic Array")])


class MicLockTests(unittest.TestCase):
    def test_second_waiter_runs_after_release(self) -> None:
        import threading
        import time
        from pathlib import Path
        from tempfile import mkdtemp

        from mac_voice.mic_lock import acquire_listen_lock

        path = Path(mkdtemp()) / "listen.lock"
        first = acquire_listen_lock(path)
        got: list[str] = []

        def waiter() -> None:
            second = acquire_listen_lock(path)
            got.append("acquired")
            second.close()

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.15)
        self.assertEqual(got, [])
        first.close()
        t.join(timeout=2.0)
        self.assertEqual(got, ["acquired"])


if __name__ == "__main__":
    unittest.main()
