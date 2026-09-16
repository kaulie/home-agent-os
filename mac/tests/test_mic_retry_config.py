"""MAC_VOICE_MIC_RETRY_SEC: mic-open retry backoff (default 10s, clamped 1–600)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mac_voice.config import DEFAULT_MIC_RETRY_SEC, VoiceConfig, load_config


def _env(**extra: str) -> dict[str, str]:
    # MAC_VOICE_WAKE_ACK keeps load_config offline (skips the Brain settings GET).
    base = {"MAC_VOICE_WAKE_ACK": "1"}
    base.update(extra)
    return base


class MicRetrySecTests(unittest.TestCase):
    def test_default_is_ten_seconds(self) -> None:
        self.assertEqual(DEFAULT_MIC_RETRY_SEC, 10.0)
        self.assertEqual(VoiceConfig.__dataclass_fields__["mic_retry_sec"].default, 10.0)

    def test_env_overrides_default(self) -> None:
        with patch.dict(os.environ, _env(MAC_VOICE_MIC_RETRY_SEC="30"), clear=False):
            self.assertEqual(load_config().mic_retry_sec, 30.0)

    def test_env_clamped_to_bounds(self) -> None:
        with patch.dict(os.environ, _env(MAC_VOICE_MIC_RETRY_SEC="0.1"), clear=False):
            self.assertEqual(load_config().mic_retry_sec, 1.0)
        with patch.dict(os.environ, _env(MAC_VOICE_MIC_RETRY_SEC="9999"), clear=False):
            self.assertEqual(load_config().mic_retry_sec, 600.0)

    def test_env_invalid_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, _env(MAC_VOICE_MIC_RETRY_SEC="abc"), clear=False):
            self.assertEqual(load_config().mic_retry_sec, DEFAULT_MIC_RETRY_SEC)


if __name__ == "__main__":
    unittest.main()
