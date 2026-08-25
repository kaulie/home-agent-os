"""light.set wakes 小书, waits 2s, then speaks 开灯/关灯."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.plugins.livingroom_light import (
    COMMAND_OFF,
    COMMAND_ON,
    WAIT_AFTER_WAKE_SEC,
    WAKE_PHRASE,
    LivingRoomLightError,
    audio_dir,
    resolve_clip,
    set_from_params,
    set_light,
)
from mac_edge.plugins.notify_speak import NotifySpeakError


class LivingRoomLightTests(unittest.TestCase):
    def _run(self, params: dict, *, speak_err: Exception | None = None):
        spoken: list[str] = []
        slept: list[float] = []
        played: list[Path] = []

        def speak_fn(text: str, **kwargs: object) -> str:
            _ = kwargs
            if speak_err is not None:
                raise speak_err
            spoken.append(text)
            return "ok"

        def sleep_fn(sec: float) -> None:
            slept.append(sec)

        def play_clip_fn(path: Path) -> None:
            played.append(path)

        with patch("mac_edge.plugins.livingroom_light.resolve_clip", return_value=None):
            msg, outputs = set_from_params(
                params,
                speak_fn=speak_fn,
                play_clip_fn=play_clip_fn,
                sleep_fn=sleep_fn,
            )
        return msg, outputs, spoken, slept, played

    def test_on_wake_then_wait_then_open(self) -> None:
        msg, outputs, spoken, slept, _played = self._run({"state": "on"})
        self.assertEqual(outputs["state"], "on")
        self.assertEqual(spoken, [WAKE_PHRASE, COMMAND_ON])
        self.assertEqual(slept, [WAIT_AFTER_WAKE_SEC])
        self.assertEqual(WAIT_AFTER_WAKE_SEC, 2.0)
        self.assertIn("开灯", msg)

    def test_off_alias_guandeng(self) -> None:
        _, outputs, spoken, slept, _played = self._run({"state": "关灯"})
        self.assertEqual(outputs["state"], "off")
        self.assertEqual(spoken, [WAKE_PHRASE, COMMAND_OFF])
        self.assertEqual(slept, [2.0])

    def test_on_alias_kai(self) -> None:
        _, outputs, spoken, _slept, _played = self._run({"state": "开"})
        self.assertEqual(outputs["state"], "on")
        self.assertEqual(spoken[-1], COMMAND_ON)

    def test_missing_state_fails_without_speech(self) -> None:
        spoken: list[str] = []

        def speak_fn(text: str, **kwargs: object) -> str:
            spoken.append(text)
            return "ok"

        with self.assertRaises(LivingRoomLightError) as ctx:
            set_from_params({}, speak_fn=speak_fn, sleep_fn=lambda _: None)
        self.assertIn("缺少必填入参 state", str(ctx.exception))
        self.assertEqual(spoken, [])

    def test_invalid_state_fails(self) -> None:
        with self.assertRaises(LivingRoomLightError) as ctx:
            set_from_params(
                {"state": "dim"},
                speak_fn=lambda *a, **k: "ok",
                sleep_fn=lambda _: None,
            )
        self.assertIn("无法识别", str(ctx.exception))

    def test_tts_failure_is_chinese(self) -> None:
        with self.assertRaises(LivingRoomLightError) as ctx:
            self._run({"state": "off"}, speak_err=NotifySpeakError("say failed"))
        self.assertIn("语音没发出去", str(ctx.exception))

    def test_prefers_clip_over_tts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wake = root / "wake.wav"
            on = root / "on.wav"
            wake.write_bytes(b"RIFF" + b"\x00" * 40)
            on.write_bytes(b"RIFF" + b"\x00" * 40)
            spoken: list[str] = []
            played: list[Path] = []

            def speak_fn(text: str, **kwargs: object) -> str:
                spoken.append(text)
                return "ok"

            with patch.dict(
                "os.environ",
                {"MAC_EDGE_LIGHT_AUDIO_DIR": str(root)},
                clear=False,
            ):
                self.assertEqual(resolve_clip("wake"), wake)
                outputs = set_light(
                    "on",
                    speak_fn=speak_fn,
                    play_clip_fn=lambda p: played.append(p),
                    sleep_fn=lambda _: None,
                )
            self.assertEqual(outputs["state"], "on")
            self.assertEqual(played, [wake, on])
            self.assertEqual(spoken, [])

    def test_audio_dir_env(self) -> None:
        with patch.dict(
            "os.environ",
            {"MAC_EDGE_LIGHT_AUDIO_DIR": "/tmp/light-clips"},
            clear=False,
        ):
            self.assertEqual(audio_dir(), Path("/tmp/light-clips"))


if __name__ == "__main__":
    unittest.main()
