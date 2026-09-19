"""voice.stream + parent edge_id (no self-register)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.plugins.voice_stream import VoiceStreamError, run_from_params
from mac_voice.config import VoiceConfig
from mac_voice.edge_id import require_parent_edge_id, resolve_parent_edge_id


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
        listen_mode="always_on",
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


class VoiceStreamTests(unittest.TestCase):
    def test_plan_step_refused(self) -> None:
        with self.assertRaises(VoiceStreamError) as ctx:
            run_from_params({})
        self.assertIn("常驻", str(ctx.exception))

    def test_resolve_from_env(self) -> None:
        cfg = _cfg()
        with patch.dict("os.environ", {"MAC_EDGE_EDGE_ID": "edge-node-TEST"}, clear=False):
            self.assertEqual(resolve_parent_edge_id(cfg), "edge-node-TEST")

    def test_resolve_from_file(self) -> None:
        cfg = _cfg()
        cfg.edge_id_path.write_text(
            json.dumps({"edge_id": "edge-node-FILE"}) + "\n", encoding="utf-8"
        )
        with patch.dict("os.environ", {"MAC_EDGE_EDGE_ID": ""}, clear=False):
            self.assertEqual(require_parent_edge_id(cfg), "edge-node-FILE")

    def test_file_wins_over_stale_env(self) -> None:
        cfg = _cfg()
        cfg.edge_id_path.write_text(
            json.dumps({"edge_id": "edge-node-NEW"}) + "\n", encoding="utf-8"
        )
        with patch.dict(
            "os.environ", {"MAC_EDGE_EDGE_ID": "edge-node-STALE"}, clear=False
        ):
            self.assertEqual(resolve_parent_edge_id(cfg), "edge-node-NEW")

    def test_require_missing(self) -> None:
        cfg = _cfg()
        with patch.dict("os.environ", {"MAC_EDGE_EDGE_ID": ""}, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                require_parent_edge_id(cfg)
            self.assertIn("will not self-register", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
