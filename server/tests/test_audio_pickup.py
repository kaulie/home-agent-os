"""Tests for LAN iPhone audio pickup TCP service."""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
import unittest

from audio_pickup import (
    FRAME_COMMAND,
    FRAME_HEARTBEAT,
    FRAME_HELLO,
    FRAME_PCM,
    AudioPickupService,
    pack_frame,
    read_frame,
)


class FrameCodecTests(unittest.TestCase):
    def test_pack_and_read_roundtrip(self) -> None:
        payload = b"hello"
        packed = pack_frame(FRAME_PCM, payload)
        sock_r, sock_w = socket.socketpair()
        try:
            sock_w.sendall(packed)
            sock_r.settimeout(1.0)
            frame = read_frame(sock_r)
            self.assertIsNotNone(frame)
            assert frame is not None
            ftype, flags, body = frame
            self.assertEqual(ftype, FRAME_PCM)
            self.assertEqual(flags, 0)
            self.assertEqual(body, payload)
        finally:
            sock_r.close()
            sock_w.close()


class AudioPickupServiceTests(unittest.TestCase):
    def test_hello_heartbeat_and_command(self) -> None:
        svc = AudioPickupService()
        svc._heartbeat_sec = 0.2
        svc._offline_after = 2
        svc._port = 0
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(1)
        svc._server_sock = sock
        svc._stop.clear()
        accept_t = threading.Thread(target=svc._accept_loop, daemon=True)
        accept_t.start()

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        hello = json.dumps(
            {
                "type": "hello",
                "device_id": "test-pickup-1",
                "sample_rate": 44100,
                "channels": 1,
                "sample_format": "s16le",
            }
        ).encode()
        client.sendall(pack_frame(FRAME_HELLO, hello))
        time.sleep(0.05)
        clients = svc.list_clients()
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]["device_id"], "test-pickup-1")
        self.assertTrue(clients[0]["online"])

        hb = json.dumps({"type": "heartbeat", "device_id": "test-pickup-1"}).encode()
        client.sendall(pack_frame(FRAME_HEARTBEAT, hb))
        client.sendall(pack_frame(FRAME_PCM, b"\x00\x01" * 100))

        out = svc.send_command("test-pickup-1", "set_power_save", branch="B")
        self.assertTrue(out["ok"])
        client.settimeout(1.0)
        frame = read_frame(client)
        self.assertIsNotNone(frame)
        assert frame is not None
        ftype, _flags, body = frame
        self.assertEqual(ftype, FRAME_COMMAND)
        cmd = json.loads(body.decode())
        self.assertEqual(cmd["type"], "set_power_save")
        self.assertEqual(cmd["branch"], "B")

        svc.stop()
        client.close()
        sock.close()

    def test_reject_unknown_command(self) -> None:
        svc = AudioPickupService()
        out = svc.send_command("missing", "nope")
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
