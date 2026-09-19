"""Phone HAP1 endpointing: quiet frames + stream stalls become wall-clock silence.

Regression: the phone's energy gate only uploads speech, so the Mac segmenter —
which counts silence in *received bytes* — never endpointed and 100/117 phone
clips ran to max_speech (2.8s) before STT, delaying「面条面条 → 我在呢」by ~1.4s
(agent_plans/phone_wake_latency_v1.md).
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
import unittest

from mac_voice.audio.pickup_ingest import (
    DEFAULT_GAP_CAP_MS,
    FRAME_HELLO,
    FRAME_PCM,
    FRAME_QUIET,
    PickupIngestServer,
    _parse_quiet_ms,
    pack_frame,
    read_frame,
)
from mac_voice.audio.segmenter import iter_utterances
from mac_voice.audio.types import PCM_16K_MONO

_BYTES_PER_MS = 16000 * 2 // 1000


def _speech(ms: int, amp: int = 9000) -> bytes:
    n = 16 * ms
    return struct.pack(f"<{n}h", *([amp] * n))


class QuietFrameCodecTests(unittest.TestCase):
    def test_parse_quiet_ms(self) -> None:
        self.assertEqual(_parse_quiet_ms(json.dumps({"ms": 400}).encode()), 400.0)
        self.assertEqual(_parse_quiet_ms(json.dumps({"quiet_ms": 250}).encode()), 250.0)
        self.assertEqual(_parse_quiet_ms(b"{}"), 0.0)
        self.assertEqual(_parse_quiet_ms(b"nope"), 0.0)
        self.assertEqual(_parse_quiet_ms(json.dumps({"ms": -5}).encode()), 0.0)

    def test_quiet_frame_roundtrip(self) -> None:
        payload = json.dumps({"ms": 400}, separators=(",", ":")).encode()
        packed = pack_frame(FRAME_QUIET, payload)
        sock_r, sock_w = socket.socketpair()
        try:
            sock_w.sendall(packed)
            sock_r.settimeout(1.0)
            frame = read_frame(sock_r)
            assert frame is not None
            self.assertEqual(frame[0], FRAME_QUIET)
            self.assertEqual(_parse_quiet_ms(frame[1]), 400.0)
        finally:
            sock_r.close()
            sock_w.close()


class InjectedSilenceTests(unittest.TestCase):
    def _server(self, **kwargs: int) -> PickupIngestServer:
        return PickupIngestServer(host="127.0.0.1", port=0, **kwargs)

    def test_inject_quiet_queues_zero_pcm(self) -> None:
        svc = self._server()
        self.assertEqual(svc.inject_quiet(400, participant_id="pid-1"), 400)
        pcm, pid = svc.iter_pcm_tagged().__next__()
        self.assertEqual(pid, "pid-1")
        self.assertEqual(len(pcm), 400 * _BYTES_PER_MS)
        self.assertEqual(pcm.strip(b"\x00"), b"")

    def test_inject_quiet_is_capped_below_command_silence(self) -> None:
        svc = self._server(gap_cap_ms=900)
        self.assertEqual(svc.inject_quiet(5000), 900)
        self.assertLess(DEFAULT_GAP_CAP_MS, 1500)
        self.assertGreater(DEFAULT_GAP_CAP_MS, 350)

    def test_zero_gap_cap_disables_injection(self) -> None:
        svc = self._server(gap_cap_ms=0)
        self.assertEqual(svc.inject_quiet(400), 0)
        self.assertEqual(svc.gap_stats()["count"], 0.0)

    def test_stall_injects_elapsed_silence(self) -> None:
        svc = self._server(stream_gap_ms=300, gap_cap_ms=900)
        sock_r, sock_w = socket.socketpair()
        try:
            svc._register_client(
                "127.0.0.1:1", sock_w, participant_id="pid-1", device_id="dev-1"
            )
            svc._mark_pcm_arrival("pid-1")
            svc._last_pcm_at -= 0.5  # 500ms with no uploads
            pcm, pid = svc.iter_pcm_tagged().__next__()
            self.assertEqual(pid, "pid-1")
            self.assertGreaterEqual(len(pcm) / _BYTES_PER_MS, 300)
            self.assertLessEqual(len(pcm) / _BYTES_PER_MS, 900)
            self.assertGreaterEqual(svc.gap_stats()["count"], 1.0)
        finally:
            sock_r.close()
            sock_w.close()

    def test_stall_skipped_without_client(self) -> None:
        svc = self._server(stream_gap_ms=300)
        svc._mark_pcm_arrival("pid-1")
        svc._last_pcm_at -= 5.0
        self.assertIsNone(svc._due_stream_gap())

    def test_stall_stops_after_active_window(self) -> None:
        svc = self._server(stream_gap_ms=300, active_window_s=30.0)
        sock_r, sock_w = socket.socketpair()
        try:
            svc._register_client("p", sock_w, participant_id="pid", device_id="dev")
            svc._mark_pcm_arrival("pid")
            svc._last_pcm_at -= 60.0
            self.assertIsNone(svc._due_stream_gap())
        finally:
            sock_r.close()
            sock_w.close()


class SocketQuietFrameTests(unittest.TestCase):
    """Fake phone → real ingest socket: PCM, then a quiet frame."""

    def test_quiet_frame_reaches_segmenter_queue(self) -> None:
        svc = PickupIngestServer(host="127.0.0.1", port=0, stream_gap_ms=0, gap_cap_ms=900)
        svc.start()
        frames: list[tuple[bytes, str]] = []
        try:
            assert svc._sock is not None
            port = svc._sock.getsockname()[1]
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect(("127.0.0.1", port))
            client.sendall(
                pack_frame(
                    FRAME_HELLO,
                    json.dumps(
                        {
                            "type": "hello",
                            "device_id": "fake-phone",
                            "participant_id": "fake-phone",
                            "sample_rate": 16000,
                        }
                    ).encode(),
                )
            )
            # 400ms of speech, then the phone's gate closes for 400ms.
            client.sendall(pack_frame(FRAME_PCM, _speech(400)))
            client.sendall(pack_frame(FRAME_QUIET, b'{"ms":400}'))

            def drain() -> None:
                for item in svc.iter_pcm_tagged():
                    frames.append(item)

            threading.Thread(target=drain, daemon=True).start()
            deadline = time.monotonic() + 5.0
            wanted = 800 * _BYTES_PER_MS
            while time.monotonic() < deadline:
                if sum(len(pcm) for pcm, _pid in frames) >= wanted:
                    break
                time.sleep(0.02)
            client.close()
            self.assertTrue(frames, "no PCM reached the segmenter queue")
            self.assertEqual({pid for _pcm, pid in frames}, {"fake-phone"})
            self.assertGreaterEqual(sum(len(pcm) for pcm, _pid in frames), wanted)
            self.assertGreaterEqual(svc.gap_stats()["count"], 1.0)
        finally:
            svc.stop()


class PhoneEndpointIntegrationTests(unittest.TestCase):
    """The injected silence must actually endpoint the shared segmenter."""

    def test_wake_silence_cuts_clip(self) -> None:
        # 1.2s「面条面条」+400ms quiet, well under the 2.8s wake max: a clip can
        # only appear here if the silence endpointed it.
        chunks = [_speech(100)] * 12 + [PickupIngestServer._silence_pcm(400)]
        utts = list(
            iter_utterances(
                chunks,
                format=PCM_16K_MONO,
                energy_threshold=1500.0,
                start_threshold=2200.0,
                silence_ms=350,
                min_speech_ms=280,
                max_speech_ms=2800,
                pre_roll_ms=250,
                voice_drop_ratio=0.5,
                allow_peak_drop_above_start=True,
            )
        )
        self.assertEqual(len(utts), 1)
        clip_ms = len(utts[0].ensure_pcm()) / _BYTES_PER_MS
        self.assertGreaterEqual(clip_ms, 1000)
        self.assertLess(clip_ms, 2000)

    def test_command_silence_glues_short_pause(self) -> None:
        chunks = [
            _speech(600),
            PickupIngestServer._silence_pcm(400),  # 400ms pause mid-command
            _speech(600),
            PickupIngestServer._silence_pcm(1500),
        ]
        utts = list(
            iter_utterances(
                chunks,
                format=PCM_16K_MONO,
                energy_threshold=1500.0,
                start_threshold=2200.0,
                silence_ms=1500,
                min_speech_ms=280,
                max_speech_ms=12000,
                pre_roll_ms=250,
                voice_drop_ratio=0.5,
                allow_peak_drop_above_start=True,
            )
        )
        self.assertEqual(len(utts), 1, "400ms pause must not split a command clip")


if __name__ == "__main__":
    unittest.main()
