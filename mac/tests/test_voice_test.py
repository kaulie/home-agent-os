"""voice_test.run_trial: play is not SUCCESS; SUCCESS comes from verifier."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.plugins.voice_test.brain_capture import _asset_ref_from_intent
from mac_edge.plugins.voice_test.loopback import heard_from_rms
from mac_edge.plugins.voice_test.profile import VoiceProfile, build_profile
from mac_edge.plugins.voice_test.series import summarize_records
from mac_edge.plugins.voice_test.trial import TrialHooks, playback_spec, run_trial, run_trial_from_params
from mac_edge.plugins.voice_test.tts import generate_speech
from mac_edge.plugins.voice_test.verify import VisionAskVerifier, parse_lamp_answer
from mac_edge.plugins.voice_test.wake_reply import finish_wake_reply_stt, parse_wake_reply


class ParseLampAnswerTests(unittest.TestCase):
    def test_on_off_unknown(self) -> None:
        self.assertEqual(parse_lamp_answer("亮"), "on")
        self.assertEqual(parse_lamp_answer("灭"), "off")
        self.assertEqual(parse_lamp_answer("我不知道"), "unknown")
        self.assertEqual(parse_lamp_answer("不亮"), "off")
        self.assertEqual(parse_lamp_answer("开着"), "on")
        self.assertEqual(parse_lamp_answer(""), "unknown")


class BrainCaptureParseTests(unittest.TestCase):
    def test_reads_asset_ref_from_step_outputs(self) -> None:
        ref = _asset_ref_from_intent(
            {
                "step_outputs": {
                    "1": {
                        "asset_ref": {
                            "asset_id": "asset_abc",
                            "type": "image",
                            "mime_type": "image/jpeg",
                        }
                    }
                }
            }
        )
        self.assertEqual(ref["asset_id"], "asset_abc")


class LoopbackRmsTests(unittest.TestCase):
    def test_play_louder_than_ambient_is_heard(self) -> None:
        self.assertTrue(heard_from_rms(0.002, 0.08))

    def test_same_as_ambient_is_not_heard(self) -> None:
        self.assertFalse(heard_from_rms(0.02, 0.021))

    def test_near_silence_is_not_heard(self) -> None:
        self.assertFalse(heard_from_rms(0.0, 0.001))


class VoiceProfileTests(unittest.TestCase):
    def test_params_override_speed_volume(self) -> None:
        profile = build_profile(
            params={"voice": "Tingting", "speed": "0.9", "volume": "0.6"},
            use_env=False,
        )
        self.assertEqual(profile.voice, "Tingting")
        self.assertEqual(profile.speed, 0.9)
        self.assertEqual(profile.volume, 0.6)
        self.assertEqual(profile.command, "打开台灯")

    def test_load_yaml_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write("voice: Sinji\nspeed: 1.1\nvolume: 1.0\ncommand: 打开台灯\n")
            path = Path(fh.name)
        try:
            profile = build_profile(file_path=path, params={}, use_env=False)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(profile.voice, "Sinji")
        self.assertEqual(profile.speed, 1.1)
        self.assertEqual(profile.volume, 1.0)


class GenerateSpeechTests(unittest.TestCase):
    def test_say_writes_aiff(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "phrase"
            profile = VoiceProfile(backend="say", voice="Tingting", speed=1.0)
            out = generate_speech("语音测试", dest, profile=profile, timeout_sec=15.0)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 1000)
            self.assertEqual(out.suffix, ".aiff")


class RunTrialTests(unittest.TestCase):
    def _hooks(self, answers: list[str], tmp: Path) -> tuple[TrialHooks, dict]:
        spoken: list[str] = []
        captured: list[str] = []
        slept: list[float] = []
        persisted: list[dict] = []
        answer_iter = iter(answers)

        def utter(text: str, dest: Path, *, profile: VoiceProfile, clip_path: str = "") -> Path:
            _ = (profile, clip_path)
            spoken.append(text)
            dest = dest.with_suffix(".aiff")
            dest.write_bytes(b"AIFF")
            return dest

        def capture(dest: Path, *, device: str = "0") -> Path:
            _ = device
            dest.write_bytes(b"\xff\xd8fakejpeg")
            captured.append(str(dest))
            aid = "asset_before" if dest.stem == "before" else "asset_after"
            dest.with_suffix(".asset.json").write_text(
                json.dumps(
                    {
                        "asset_ref": {
                            "asset_id": aid,
                            "type": "image",
                            "mime_type": "image/jpeg",
                        },
                        "content_url": f"http://example.test/{dest.name}",
                    }
                ),
                encoding="utf-8",
            )
            return dest

        def upload(path: Path, **_kwargs: object) -> dict[str, str]:
            return {"photo_url": f"http://example.test/{path.name}", "saved_as": path.name}

        def persist(record: dict) -> Path:
            persisted.append(record)
            out = tmp / "trials.jsonl"
            out.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
            return out

        verifier = VisionAskVerifier(
            ask_fn=lambda **kwargs: {"answer_text": next(answer_iter)}
        )
        hooks = TrialHooks(
            utter=utter,
            capture=capture,
            sleep=slept.append,
            verifier=verifier,
            upload=upload,
            persist=persist,
        )
        bag = {"spoken": spoken, "captured": captured, "slept": slept, "persisted": persisted}
        return hooks, bag

    def test_success_when_after_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            with patch.dict(os.environ, {"MAC_EDGE_VOICE_TEST_DIR": str(tmp)}, clear=False):
                hooks, bag = self._hooks(["灭", "亮"], tmp)
                profile = VoiceProfile(capture_before=True, wake_word_pause_ms=2000, settle_ms=1500)
                record = run_trial(
                    profile=profile,
                    experiment_id="exp1",
                    trial_id="t1",
                    hooks=hooks,
                )
        self.assertEqual(record["result"], "SUCCESS")
        self.assertEqual(record["error_reason"], "")
        self.assertIsNone(record["wake_reply_heard"])
        self.assertEqual(record["wake_word_pause_ms"], 2000)
        self.assertEqual(bag["spoken"], ["小书小书", "打开台灯"])
        self.assertEqual(bag["slept"], [2.0, 1.5])
        self.assertEqual(len(bag["captured"]), 2)
        self.assertEqual(bag["persisted"][0]["result"], "SUCCESS")
        self.assertIn("t1", bag["persisted"][0]["trial_id"])
        text = record["timeline_text"]
        self.assertIn("试验开始", text)
        self.assertIn("拍 before 触发", text)
        self.assertIn("看 before 图", text)
        self.assertIn("第一句", text)
        self.assertIn("第二句", text)
        self.assertIn("拍 after 触发", text)
        self.assertIn("看 after 图", text)
        self.assertIn("最终结果 SUCCESS", text)
        events = [e["event"] for e in record["timeline"]["events"]]
        self.assertIn("judged", events)
        self.assertEqual(record["before_asset_id"], "asset_before")
        self.assertEqual(record["after_asset_id"], "asset_after")
        self.assertEqual(record["playback"]["wake"]["kind"], "tts")
        self.assertEqual(record["playback"]["command"]["label"], "标准人声 TTS")
        self.assertEqual(record["speed"], 1.0)
        self.assertEqual(record["volume"], 0.8)
        self.assertEqual(record["knobs"]["speed"], 1.0)
        self.assertEqual(record["knobs"]["voice"], "Tingting")
        self.assertEqual(record["knobs"]["settle_ms"], 1500)
        self.assertIn("pause_window", record["pickup_text"])

    def test_fail_when_lamp_stays_off(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            with patch.dict(os.environ, {"MAC_EDGE_VOICE_TEST_DIR": str(tmp)}, clear=False):
                hooks, bag = self._hooks(["灭", "灭"], tmp)
                msg, outputs = run_trial_from_params(
                    {"experiment_id": "exp2", "capture_before": "true"},
                    hooks=hooks,
                )
        self.assertEqual(outputs["result"], "FAIL")
        self.assertEqual(outputs["error_reason"], "lamp_not_on")
        self.assertIn("FAIL", msg)
        self.assertEqual(bag["spoken"], ["小书小书", "打开台灯"])

    def test_invalid_when_already_on_skips_play(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            with patch.dict(os.environ, {"MAC_EDGE_VOICE_TEST_DIR": str(tmp)}, clear=False):
                hooks, bag = self._hooks(["亮"], tmp)
                record = run_trial(
                    profile=VoiceProfile(capture_before=True),
                    hooks=hooks,
                )
        self.assertEqual(record["result"], "INVALID")
        self.assertEqual(record["error_reason"], "lamp_already_on")
        self.assertEqual(bag["spoken"], [])
        self.assertEqual(len(bag["captured"]), 1)
        self.assertIn("最终结果 INVALID", record["timeline_text"])
        self.assertIn("拍 before 触发", record["timeline_text"])
        self.assertNotIn("第一句", record["timeline_text"])

    def test_play_is_not_success_without_verify(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            with patch.dict(os.environ, {"MAC_EDGE_VOICE_TEST_DIR": str(tmp)}, clear=False):
                hooks, _bag = self._hooks([], tmp)
                record = run_trial(
                    profile=VoiceProfile(capture_before=False),
                    skip_verify=True,
                    hooks=hooks,
                )
        self.assertNotEqual(record["result"], "SUCCESS")
        self.assertEqual(record["error_reason"], "verify_skipped")


class SeriesSummaryTests(unittest.TestCase):
    def test_success_rate_ignores_invalid(self) -> None:
        summary = summarize_records(
            [
                {"result": "FAIL", "latency_ms": 10, "command_loopback": {"heard": True}, "voice_profile": {"wake_word_pause_ms": 2000, "speed": 1.0, "volume": 0.8}},
                {"result": "SUCCESS", "latency_ms": 30, "wake_loopback": {"heard": True}, "voice_profile": {"wake_word_pause_ms": 2000, "speed": 1.0, "volume": 0.8}},
                {"result": "INVALID", "error_reason": "lamp_already_on", "voice_profile": {"wake_word_pause_ms": 2000, "speed": 1.0, "volume": 0.8}},
            ]
        )
        self.assertEqual(summary["success_over_valid"], "1/2")
        self.assertEqual(summary["success"], 1)
        self.assertEqual(summary["fail"], 1)
        self.assertEqual(summary["invalid"], 1)
        self.assertEqual(summary["loopback_heard"], "2/2")
        self.assertEqual(summary["mean_latency_ms"], 20)
        self.assertEqual(summary["by_pause_ms"]["2000"]["success_over_valid"], "1/2")

    def test_by_pause_splits_success_rate(self) -> None:
        summary = summarize_records(
            [
                {
                    "result": "FAIL",
                    "voice_profile": {
                        "wake_word_pause_ms": 800,
                        "speed": 0.8,
                        "volume": 0.6,
                        "voice": "Tingting",
                        "backend": "say",
                        "pitch": "",
                        "settle_ms": 1500,
                    },
                    "wake_reply_heard": False,
                },
                {
                    "result": "SUCCESS",
                    "voice_profile": {
                        "wake_word_pause_ms": 3000,
                        "speed": 1.2,
                        "volume": 1.0,
                        "voice": "Mei-Jia",
                        "backend": "edge",
                        "pitch": "+10Hz",
                        "settle_ms": 2000,
                    },
                    "wake_reply_heard": True,
                },
                {
                    "result": "SUCCESS",
                    "voice_profile": {
                        "wake_word_pause_ms": 3000,
                        "speed": 1.2,
                        "volume": 1.0,
                        "voice": "Mei-Jia",
                        "backend": "edge",
                        "pitch": "+10Hz",
                        "settle_ms": 2000,
                    },
                    "wake_reply_heard": False,
                },
            ]
        )
        self.assertEqual(summary["by_pause_ms"]["800"]["success_over_valid"], "0/1")
        self.assertEqual(summary["by_pause_ms"]["800"]["pause_risk"], "ok")
        self.assertEqual(summary["by_pause_ms"]["3000"]["success_over_valid"], "2/2")
        self.assertEqual(summary["by_pause_ms"]["3000"]["pause_risk"], "high_risk")
        self.assertEqual(summary["by_pause_ms"]["800"]["wake_reply_over_n"], "0/1")
        self.assertEqual(summary["by_pause_ms"]["3000"]["wake_reply_over_n"], "1/2")
        self.assertEqual(summary["by_speed"]["0.8"]["success_over_valid"], "0/1")
        self.assertEqual(summary["by_speed"]["1.2"]["success_over_valid"], "2/2")
        self.assertEqual(summary["by_volume"]["0.6"]["success_over_valid"], "0/1")
        self.assertEqual(summary["by_volume"]["1.0"]["success_over_valid"], "2/2")
        self.assertEqual(summary["by_voice"]["Tingting"]["success_over_valid"], "0/1")
        self.assertEqual(summary["by_voice"]["Mei-Jia"]["success_over_valid"], "2/2")
        self.assertEqual(summary["by_backend"]["say"]["success_over_valid"], "0/1")
        self.assertEqual(summary["by_backend"]["edge"]["success_over_valid"], "2/2")
        self.assertEqual(summary["by_pitch"]["default"]["success_over_valid"], "0/1")
        self.assertEqual(summary["by_pitch"]["+10Hz"]["success_over_valid"], "2/2")
        self.assertEqual(summary["by_settle_ms"]["1500"]["success_over_valid"], "0/1")
        self.assertEqual(summary["by_settle_ms"]["2000"]["success_over_valid"], "2/2")

    def test_parse_pause_list(self) -> None:
        from mac_edge.plugins.voice_test.series import (
            parse_csv_list,
            parse_float_list,
            parse_pause_ms_list,
        )

        self.assertEqual(parse_pause_ms_list("800,1500,2000"), [800, 1500, 2000])
        self.assertEqual(parse_pause_ms_list("2000,2000,800"), [2000, 800])
        self.assertEqual(parse_float_list("0.8,1.0,1.2", name="speed", lo=0.5, hi=2.0), [0.8, 1.0, 1.2])
        self.assertEqual(parse_csv_list("Tingting,Mei-Jia", name="voice"), ["Tingting", "Mei-Jia"])


class WakeReplyParseTests(unittest.TestCase):
    def test_zai_ne_is_not_lamp_success(self) -> None:
        self.assertTrue(parse_wake_reply("在呢"))
        self.assertTrue(parse_wake_reply("我在呢。"))
        self.assertTrue(parse_wake_reply("嗯我在呢"))
        self.assertFalse(parse_wake_reply(""))
        self.assertFalse(parse_wake_reply("小书小书"))
        self.assertFalse(parse_wake_reply("打开台灯"))

    def test_stt_deferred_until_finish(self) -> None:
        recorded = {
            "source": "recorded",
            "wav": "/no-such-wake-reply.wav",
            "heard": None,
            "text": "",
        }
        out = finish_wake_reply_stt(recorded)
        self.assertEqual(out["source"], "recorded")
        self.assertIsNone(out["heard"])


class PlaybackSpecTests(unittest.TestCase):
    def test_tts_vs_clip(self) -> None:
        tts = playback_spec(VoiceProfile(backend="say", voice="Tingting"), clip_path="")
        self.assertEqual(tts["kind"], "tts")
        self.assertEqual(tts["label"], "标准人声 TTS")
        clip = playback_spec(VoiceProfile(), clip_path="/tmp/wake.wav")
        self.assertEqual(clip["kind"], "clip")
        self.assertEqual(clip["label"], "录音")
        self.assertEqual(clip["clip_path"], "/tmp/wake.wav")


if __name__ == "__main__":
    unittest.main()
