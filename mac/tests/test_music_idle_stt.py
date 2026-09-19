"""Music idle STT skip (Volc cost control during playback)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_voice.audio.types import AudioUtterance, PCM_16K_MONO
from mac_voice.config import VoiceConfig, load_config
from mac_voice.listen import should_skip_music_idle_stt
from mac_voice.wake import WakeGate


def _cfg(**kwargs) -> VoiceConfig:
    root = Path(tempfile.mkdtemp())
    data = root / "data"
    data.mkdir()
    base = dict(
        brain_url="http://example.test",
        client_hint="living-room-mac",
        display_name="t",
        device_type="mac",
        room="living-room",
        app_version="0",
        data_dir=data / "mac_voice",
        edge_id_path=data / "edge_id.json",
        listen_mode="wake_word",
        stt_provider="volc_sauc",
        sauc_api_key="",
        sauc_app_key="",
        sauc_access_key="",
        sauc_url="",
        sauc_resource_id="",
        sauc_seg_duration_ms=200,
        input_device=0,
        energy_threshold=500.0,
        silence_ms=800,
        min_speech_ms=400,
        max_speech_ms=8000,
        usb_wake_silence_ms=400,
        usb_wake_max_speech_ms=2800,
        wake_word="面条",
        wake_repeat=2,
        wake_aliases=("miantiao", "棉条", "面跳", "免条"),
        command_window_ms=3000,
        partial_wake_ms=2500,
        double_wake_ms=1100,
        wake_ack="又咋了",
        pickup_ingest_enabled=False,
        pickup_ingest_host="0.0.0.0",
        pickup_ingest_port=8792,
        pickup_speak_bridge_port=8793,
        phone_wake_silence_ms=350,
        phone_wake_max_speech_ms=2800,
        phone_command_silence_ms=1500,
        phone_command_max_speech_ms=12_000,
        stt_wav_dir=None,
        stt_wav_keep=False,
        stt_wav_max_age_hours=24.0,
        stt_wav_max_files=100,
        stt_wav_max_mb=200.0,
        music_idle_stt="skip_long",
        music_idle_stt_max_ms=2500,
        wake_scope="participant",
    )
    base.update(kwargs)
    return VoiceConfig(**base)


def _utt_ms(ms: int, *, ingress: str = "") -> AudioUtterance:
    bytes_per_ms = PCM_16K_MONO.sample_rate * PCM_16K_MONO.channels * PCM_16K_MONO.sample_width // 1000
    pcm = b"\x00\x01" * (ms * bytes_per_ms // 2)
    utt = AudioUtterance.from_pcm(pcm)
    utt.ingress = ingress
    return utt


class MusicIdleSttTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = WakeGate(command_window_ms=3000)

    @patch("mac_edge.music_linkage.is_active", return_value=True)
    def test_skip_long_skips_8s_clip(self, _active) -> None:
        cfg = _cfg(music_idle_stt="skip_long")
        self.assertTrue(should_skip_music_idle_stt(cfg, self.gate, _utt_ms(8000)))

    @patch("mac_edge.music_linkage.is_active", return_value=True)
    def test_skip_long_allows_short_wake_clip(self, _active) -> None:
        cfg = _cfg(music_idle_stt="skip_long")
        self.assertFalse(should_skip_music_idle_stt(cfg, self.gate, _utt_ms(1200)))

    @patch("mac_edge.music_linkage.is_active", return_value=True)
    def test_all_keeps_long_clip(self, _active) -> None:
        cfg = _cfg(music_idle_stt="all")
        self.assertFalse(should_skip_music_idle_stt(cfg, self.gate, _utt_ms(8000)))

    @patch("mac_edge.music_linkage.is_active", return_value=True)
    def test_none_skips_short_idle_clip(self, _active) -> None:
        cfg = _cfg(music_idle_stt="none")
        self.assertTrue(should_skip_music_idle_stt(cfg, self.gate, _utt_ms(1200)))

    @patch("mac_edge.music_linkage.is_active", return_value=True)
    def test_max_ms_threshold(self, _active) -> None:
        cfg = _cfg(music_idle_stt="skip_long", music_idle_stt_max_ms=1500)
        self.assertTrue(should_skip_music_idle_stt(cfg, self.gate, _utt_ms(2000)))
        self.assertFalse(should_skip_music_idle_stt(cfg, self.gate, _utt_ms(1200)))

    @patch("mac_edge.music_linkage.is_active", return_value=True)
    def test_listening_never_skips(self, _active) -> None:
        cfg = _cfg(music_idle_stt="none")
        self.gate.state = "listening"
        self.assertFalse(should_skip_music_idle_stt(cfg, self.gate, _utt_ms(8000)))

    @patch("mac_edge.music_linkage.is_active", return_value=False)
    def test_no_music_never_skips(self, _inactive) -> None:
        cfg = _cfg(music_idle_stt="none")
        self.assertFalse(should_skip_music_idle_stt(cfg, self.gate, _utt_ms(8000)))

    @patch("mac_edge.music_linkage.is_active", return_value=True)
    def test_phone_hap1_never_skipped(self, _active) -> None:
        cfg = _cfg(music_idle_stt="skip_long")
        self.assertFalse(
            should_skip_music_idle_stt(
                cfg, self.gate, _utt_ms(8000, ingress="phone_hap1")
            )
        )

    def test_invalid_music_idle_stt_raises(self) -> None:
        with patch.dict("os.environ", {"MAC_VOICE_MUSIC_IDLE_STT": "bogus"}, clear=False):
            with self.assertRaises(ValueError):
                load_config()


if __name__ == "__main__":
    unittest.main()
