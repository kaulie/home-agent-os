"""Tests for STT WAV store path + retention."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mac_voice.audio.types import AudioUtterance, PCM_16K_MONO  # noqa: E402
from mac_voice.stt.wav_store import SttWavStore  # noqa: E402


class SttWavStoreTests(unittest.TestCase):
    def test_materialize_fixed_dir_and_prune_by_count(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SttWavStore(
                directory=root,
                keep=True,
                max_age_hours=0,
                max_files=2,
                max_mb=0,
            )
            for i in range(4):
                utt = AudioUtterance.from_pcm(
                    b"\x00\x01" * 80,
                    format=PCM_16K_MONO,
                    ingress="mac_usb",
                    input_participant_id=f"p{i}",
                )
                path, owned = store.materialize(utt)
                self.assertTrue(path.is_file())
                self.assertFalse(owned)
                time.sleep(0.01)
            left = list(root.glob("mac_voice_*.wav"))
            self.assertEqual(len(left), 2)

    def test_release_deletes_when_not_keep(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SttWavStore(
                directory=root,
                keep=False,
                max_age_hours=24,
                max_files=100,
                max_mb=200,
            )
            utt = AudioUtterance.from_pcm(b"\x00\x01" * 40, format=PCM_16K_MONO)
            path, owned = store.materialize(utt)
            self.assertTrue(owned)
            self.assertTrue(path.is_file())
            store.release(path, owned=True)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
