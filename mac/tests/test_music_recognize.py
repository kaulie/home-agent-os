"""music.recognize: capture-window orchestration, provider registry, wav helpers."""

from __future__ import annotations

import math
import os
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.plugins.music_recognize.config import (
    BYTES_PER_SEC,
    MusicRecognizeConfig,
    load_config,
    provider_name,
    provider_selected,
)
from mac_edge.plugins.music_recognize.errors import MusicRecognizeError
from mac_edge.plugins.music_recognize.orchestrate import (
    SILENT_MSG,
    TIMEOUT_MSG,
    run_session,
)
from mac_edge.plugins.music_recognize.providers import (
    ProviderNotConfiguredError,
    SongMatch,
    acr_signature,
    build_provider,
    recognize_mock,
)
from mac_edge.plugins.music_recognize.wav import has_signal, pcm_rms, pcm_to_wav


def tone_pcm(seconds: float, *, amplitude: int = 8000, freq: float = 440.0) -> bytes:
    """Raw int16 mono 16 kHz PCM of a sine tone (used to fake mic audio)."""
    n = int(seconds * BYTES_PER_SEC)
    buf = bytearray(n * 2)
    for i in range(n):
        v = int(amplitude * math.sin(2 * math.pi * freq * i / 16000.0))
        struct.pack_into("<h", buf, i * 2, max(-32768, min(32767, v)))
    return bytes(buf)


def silent_pcm(seconds: float) -> bytes:
    return bytes(int(seconds * BYTES_PER_SEC) * 2)


def chunk_iter(pcm: bytes, chunk: int = 3200):
    for i in range(0, len(pcm), chunk):
        yield pcm[i : i + chunk]


def make_cfg(**overrides) -> MusicRecognizeConfig:
    base = dict(
        provider="mock",
        min_sec=10.0,
        max_sec=30.0,
        retry_every_sec=5.0,
        input_device=None,
        data_dir=Path("/tmp/music_recognize_test"),
        keep_wav=False,
        wav_dir=None,
        signal_threshold=200.0,
        http_timeout_sec=10.0,
        audd_token="",
        acr_access_key="",
        acr_access_secret="",
        acr_host="",
        shazam_key="",
        shazam_host="",
    )
    base.update(overrides)
    return MusicRecognizeConfig(**base)


class WavHelperTests(unittest.TestCase):
    def test_tone_has_signal_and_silence_does_not(self) -> None:
        tone = tone_pcm(1.0)
        quiet = silent_pcm(1.0)
        self.assertGreater(pcm_rms(tone), 200.0)
        self.assertLess(pcm_rms(quiet), 200.0)
        self.assertTrue(has_signal(tone, 200.0))
        self.assertFalse(has_signal(quiet, 200.0))

    def test_pcm_to_wav_header(self) -> None:
        wav = pcm_to_wav(tone_pcm(0.5))
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertTrue(wav[8:12] == b"WAVE")


class ConfigTests(unittest.TestCase):
    def _clear_env(self) -> None:
        for key in list(os.environ):
            if key.startswith("MAC_EDGE_MUSIC_RECOGNIZE_") or key == "MAC_VOICE_INPUT_DEVICE":
                os.environ.pop(key, None)

    def test_provider_default_none(self) -> None:
        self._clear_env()
        self.assertEqual(provider_name(), "none")
        self.assertFalse(provider_selected())

    def test_mock_selected_when_enabled(self) -> None:
        self._clear_env()
        os.environ["MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER"] = "mock"
        self.assertEqual(provider_name(), "mock")
        self.assertTrue(provider_selected())

    def test_audd_needs_token(self) -> None:
        self._clear_env()
        os.environ["MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER"] = "audd"
        self.assertFalse(provider_selected())
        os.environ["MAC_EDGE_MUSIC_RECOGNIZE_AUDD_TOKEN"] = "tok"
        self.assertTrue(provider_selected())

    def test_load_config_defaults_faster_first_window(self) -> None:
        self._clear_env()
        os.environ["MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER"] = "mock"
        cfg = load_config()
        self.assertEqual(cfg.min_sec, 5.0)
        self.assertEqual(cfg.retry_every_sec, 3.0)

    def test_load_config_clamps_and_derives_device(self) -> None:
        self._clear_env()
        os.environ["MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER"] = "mock"
        os.environ["MAC_EDGE_MUSIC_RECOGNIZE_MIN_SEC"] = "8"
        os.environ["MAC_EDGE_MUSIC_RECOGNIZE_MAX_SEC"] = "99"
        os.environ["MAC_VOICE_INPUT_DEVICE"] = "reSpeaker XVF3800 4-Mic Array"
        cfg = load_config()
        self.assertGreaterEqual(cfg.min_sec, 5.0)
        self.assertLessEqual(cfg.max_sec, 60.0)
        self.assertEqual(cfg.input_device, "reSpeaker XVF3800 4-Mic Array")
        self.assertGreaterEqual(cfg.max_sec, cfg.min_sec)


class ProviderTests(unittest.TestCase):
    def test_mock_matches(self) -> None:
        match = recognize_mock(tone_pcm(10.0))
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.title, "测试歌曲")

    def test_build_provider_none_raises(self) -> None:
        cfg = make_cfg(provider="none")
        with self.assertRaises(ProviderNotConfiguredError):
            build_provider(cfg)

    def test_build_provider_audd_requires_token(self) -> None:
        cfg = make_cfg(provider="audd", audd_token="")
        with self.assertRaises(ProviderNotConfiguredError):
            build_provider(cfg)
        cfg = make_cfg(provider="audd", audd_token="tok")
        self.assertTrue(callable(build_provider(cfg)))

    def test_acr_signature_deterministic(self) -> None:
        sig = acr_signature("ak", "sk", "1700000000")
        self.assertEqual(sig, acr_signature("ak", "sk", "1700000000"))
        self.assertNotEqual(sig, acr_signature("ak", "sk2", "1700000000"))
        # Official protocol v1 string_to_sign (not the old buggy layout).
        self.assertEqual(sig, "KkjhsUc/r8rmyukgTnjY/xbpti8=")

    def test_acr_success_code_zero_not_treated_as_missing(self) -> None:
        """Regression: `status.code or -1` wrongly turns success (0) into -1."""
        from unittest.mock import MagicMock, patch

        from mac_edge.plugins.music_recognize.providers import recognize_acrcloud

        body = {
            "status": {"msg": "Success", "code": 0, "version": "1.0"},
            "metadata": {
                "music": [
                    {
                        "title": "十年",
                        "artists": [{"name": "陈奕迅"}],
                        "album": {"name": "黑白灰"},
                        "score": 100,
                    }
                ]
            },
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = body
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        with patch(
            "mac_edge.plugins.music_recognize.providers._import_httpx"
        ) as httpx_mod:
            httpx_mod.return_value.Client.return_value = mock_client
            match = recognize_acrcloud(
                b"RIFF" + b"\x00" * 100,
                access_key="ak",
                access_secret="sk",
                host="identify-ap-southeast-1.acrcloud.com",
                timeout_sec=5.0,
            )
        self.assertIsNotNone(match)
        self.assertEqual(match.title, "十年")
        self.assertEqual(match.artist, "陈奕迅")


class RunSessionTests(unittest.TestCase):
    def test_matches_at_min_window(self) -> None:
        cfg = make_cfg()
        calls: list[int] = []

        def provider(wav: bytes) -> SongMatch | None:
            calls.append(len(wav))
            return SongMatch(title="十年", artist="陈奕迅")

        out = run_session(cfg, iter_pcm=chunk_iter(tone_pcm(12.0)), provider=provider)
        self.assertTrue(out["matched"])
        self.assertEqual(out["song_title"], "十年")
        self.assertEqual(out["artist"], "陈奕迅")
        self.assertIn("《十年》", out["answer_text"])
        self.assertGreaterEqual(out["captured_sec"], 10.0)
        self.assertTrue(calls)

    def test_timeout_when_provider_never_matches(self) -> None:
        cfg = make_cfg(max_sec=13.0, retry_every_sec=5.0)
        calls: list[int] = []

        def provider(wav: bytes) -> SongMatch | None:
            calls.append(len(wav))
            return None

        out = run_session(cfg, iter_pcm=chunk_iter(tone_pcm(13.5)), provider=provider)
        self.assertFalse(out["matched"])
        self.assertEqual(out["answer_text"], TIMEOUT_MSG)
        self.assertGreaterEqual(len(calls), 1)

    def test_silence_skips_provider(self) -> None:
        cfg = make_cfg(max_sec=12.0)
        calls: list[int] = []

        def provider(wav: bytes) -> SongMatch | None:
            calls.append(len(wav))
            return SongMatch(title="x", artist="y")

        out = run_session(cfg, iter_pcm=chunk_iter(silent_pcm(12.5)), provider=provider)
        self.assertFalse(out["matched"])
        self.assertEqual(out["answer_text"], SILENT_MSG)
        self.assertEqual(calls, [])

    def test_keep_wav_writes_attempt_and_session(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            wav_dir = Path(tmp) / "wav"
            cfg = make_cfg(keep_wav=True, wav_dir=wav_dir, max_sec=12.0)

            def provider(wav: bytes) -> SongMatch | None:
                return None

            out = run_session(
                cfg,
                iter_pcm=chunk_iter(tone_pcm(12.5)),
                provider=provider,
                session_tag="intent647",
            )
            self.assertFalse(out["matched"])
            self.assertNotIn("kept_wav_paths", out)
            written = sorted(wav_dir.glob("*.wav"))
            self.assertTrue(written)
            self.assertTrue(any(p.name.startswith("intent647_attempt") for p in written))
            self.assertTrue(any(p.name == "intent647_session.wav" for p in written))
            for p in written:
                self.assertGreater(p.stat().st_size, 44)

    def test_matches_at_faster_default_window(self) -> None:
        """DEFAULT_MIN_SEC=5: first provider call around 5s, not 10s."""
        cfg = make_cfg(min_sec=5.0, max_sec=12.0, retry_every_sec=3.0)
        calls: list[float] = []

        def provider(wav: bytes) -> SongMatch | None:
            # window length ≈ min_sec of PCM
            calls.append(len(wav))
            return SongMatch(title="十年", artist="陈奕迅")

        out = run_session(cfg, iter_pcm=chunk_iter(tone_pcm(6.0)), provider=provider)
        self.assertTrue(out["matched"])
        self.assertGreaterEqual(out["captured_sec"], 5.0)
        self.assertLess(out["captured_sec"], 8.0)
        self.assertTrue(calls)

    def test_run_from_params_requires_provider(self) -> None:
        from mac_edge.plugins.music_recognize import run_from_params

        with patch.dict(
            os.environ,
            {
                "MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER": "none",
                "MAC_VOICE_INPUT_DEVICE": "",
                "MAC_EDGE_MUSIC_RECOGNIZE_MIN_SEC": "10",
                "MAC_EDGE_MUSIC_RECOGNIZE_MAX_SEC": "30",
            },
            clear=False,
        ):
            with self.assertRaises(MusicRecognizeError):
                run_from_params({})


if __name__ == "__main__":
    unittest.main()

