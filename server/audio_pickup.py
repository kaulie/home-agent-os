"""LAN iPhone audio pickup: multiplexed TCP + heartbeat + JSON commands.

Wire frame (big-endian):
  magic b"HAP1" (4) | type u8 | flags u8 | length u32 | payload

Types:
  1 heartbeat (JSON, client -> server)
  2 pcm (s16le mono, client -> server)
  3 command (JSON, server -> client)
  4 hello (JSON, client -> server, first frame after connect)

Env:
  AUDIO_PICKUP_PORT (default 8791)
  AUDIO_PICKUP_HOST (default 0.0.0.0)
  AUDIO_PICKUP_HEARTBEAT_SEC (default 8)
  AUDIO_PICKUP_OFFLINE_AFTER (default 3 missed intervals)
  AUDIO_PICKUP_PCM_DIR (optional raw PCM dump directory)
  AUDIO_PICKUP_VOICE_RELAY (default 127.0.0.1:8792 — mac_voice home_mic ingest)
  AUDIO_PICKUP_VOICE_RELAY_ENABLE (default 1)
"""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("audio_pickup")

MAGIC = b"HAP1"
HEADER_SIZE = 10
FRAME_HEARTBEAT = 1
FRAME_PCM = 2
FRAME_COMMAND = 3
FRAME_HELLO = 4

DEFAULT_PORT = 8791
DEFAULT_HOST = "0.0.0.0"
DEFAULT_HEARTBEAT_SEC = 8.0
DEFAULT_OFFLINE_AFTER = 3
DEFAULT_VOICE_RELAY = "127.0.0.1:8792"


class _VoiceStreamRelay:
    """Forward Home Mic HAP1 hello/pcm frames to local mac_voice ingest."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._target = DEFAULT_VOICE_RELAY
        self._enabled = True
        self._hello_sent_for: str | None = None
        self._frames_ok = 0
        self._frames_fail = 0
        self._last_error = ""

    def configure(self, target: str, *, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled
            self._target = (target or DEFAULT_VOICE_RELAY).strip() or DEFAULT_VOICE_RELAY
            self._close_unlocked()
            self._hello_sent_for = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "target": self._target,
                "connected": self._sock is not None,
                "frames_ok": self._frames_ok,
                "frames_fail": self._frames_fail,
                "last_error": self._last_error,
                "hello_device": self._hello_sent_for or "",
            }

    def forward(self, frame_type: int, payload: bytes, *, device_id: str, hello: dict[str, Any]) -> None:
        if not self._enabled:
            return
        with self._lock:
            try:
                self._ensure_conn_unlocked()
                assert self._sock is not None
                if self._hello_sent_for != device_id:
                    hello_body = dict(hello or {})
                    hello_body.setdefault("type", "hello")
                    hello_body["device_id"] = device_id
                    self._sock.sendall(
                        pack_frame(FRAME_HELLO, json.dumps(hello_body, ensure_ascii=False).encode("utf-8"))
                    )
                    self._hello_sent_for = device_id
                    log.info("voice relay hello device=%s → %s", device_id, self._target)
                if frame_type == FRAME_PCM and payload:
                    self._sock.sendall(pack_frame(FRAME_PCM, payload))
                    self._frames_ok += 1
            except OSError as e:
                self._frames_fail += 1
                self._last_error = str(e)
                self._close_unlocked()
                if self._frames_fail <= 3 or self._frames_fail % 50 == 0:
                    log.warning("voice relay forward failed target=%s err=%s", self._target, e)

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def _ensure_conn_unlocked(self) -> None:
        if self._sock is not None:
            return
        host, _, port_raw = self._target.partition(":")
        host = host.strip() or "127.0.0.1"
        try:
            port = int(port_raw or "8792")
        except ValueError:
            port = 8792
        sock = socket.create_connection((host, port), timeout=2.0)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._hello_sent_for = None
        self._last_error = ""
        log.info("voice relay connected → %s:%s", host, port)

    def _close_unlocked(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._hello_sent_for = None


_voice_relay = _VoiceStreamRelay()


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def pack_frame(frame_type: int, payload: bytes, *, flags: int = 0) -> bytes:
    body = payload if isinstance(payload, (bytes, bytearray)) else b""
    return MAGIC + struct.pack(">BBI", frame_type, flags, len(body)) + body


def read_frame(sock: socket.socket) -> tuple[int, int, bytes] | None:
    header = _recv_exact(sock, HEADER_SIZE)
    if header is None:
        return None
    if header[:4] != MAGIC:
        raise ValueError("invalid frame magic")
    frame_type, flags, length = struct.unpack(">BBI", header[4:])
    if length < 0 or length > 8_000_000:
        raise ValueError("invalid frame length")
    payload = _recv_exact(sock, length) if length else b""
    if payload is None and length > 0:
        return None
    return frame_type, flags, payload or b""


def _recv_exact(sock: socket.socket, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        try:
            chunk = sock.recv(remaining)
        except socket.timeout:
            return None
        except OSError:
            return None
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _json_loads(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class PickupClient:
    device_id: str
    addr: str
    connected_at: float
    last_heartbeat_at: float
    hello: dict[str, Any] = field(default_factory=dict)
    pcm_bytes: int = 0
    online: bool = True
    recording: bool = True
    power_mode: str = "normal"
    _sock: socket.socket | None = None
    _send_lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "addr": self.addr,
            "online": self.online,
            "recording": self.recording,
            "power_mode": self.power_mode,
            "connected_at": self.connected_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "pcm_bytes": self.pcm_bytes,
            "hello": self.hello,
        }


class AudioPickupService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, PickupClient] = {}
        self._server_sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._watch_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._host = DEFAULT_HOST
        self._port = DEFAULT_PORT
        self._heartbeat_sec = DEFAULT_HEARTBEAT_SEC
        self._offline_after = DEFAULT_OFFLINE_AFTER
        self._pcm_sink_dir: str | None = None
        self._voice_relay = _voice_relay

    @property
    def listening(self) -> bool:
        return self._accept_thread is not None and self._accept_thread.is_alive()

    def configure_from_env(self) -> None:
        self._host = (os.environ.get("AUDIO_PICKUP_HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST
        self._port = _env_int("AUDIO_PICKUP_PORT", DEFAULT_PORT)
        self._heartbeat_sec = _env_float("AUDIO_PICKUP_HEARTBEAT_SEC", DEFAULT_HEARTBEAT_SEC)
        self._offline_after = _env_int("AUDIO_PICKUP_OFFLINE_AFTER", DEFAULT_OFFLINE_AFTER)
        raw_dir = (os.environ.get("AUDIO_PICKUP_PCM_DIR") or "").strip()
        self._pcm_sink_dir = raw_dir or None
        relay_raw = (os.environ.get("AUDIO_PICKUP_VOICE_RELAY") or DEFAULT_VOICE_RELAY).strip()
        relay_off = (os.environ.get("AUDIO_PICKUP_VOICE_RELAY_ENABLE") or "1").strip().lower() in (
            "0",
            "false",
            "no",
            "off",
        )
        self._voice_relay.configure(relay_raw, enabled=not relay_off)

    def start(self) -> None:
        if self.listening:
            return
        self.configure_from_env()
        self._stop.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._host, self._port))
        sock.listen(8)
        sock.settimeout(1.0)
        self._server_sock = sock
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="audio-pickup-accept",
            daemon=True,
        )
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            name="audio-pickup-watch",
            daemon=True,
        )
        self._accept_thread.start()
        self._watch_thread.start()
        log.info(
            "audio pickup listening %s:%s heartbeat=%ss offline_after=%s",
            self._host,
            self._port,
            self._heartbeat_sec,
            self._offline_after,
        )

    def stop(self) -> None:
        self._stop.set()
        self._voice_relay.close()
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None

    def list_clients(self) -> list[dict[str, Any]]:
        with self._lock:
            return [c.snapshot() for c in self._clients.values()]

    def status(self) -> dict[str, Any]:
        return {
            "listening": self.listening,
            "host": self._host,
            "port": self._port,
            "heartbeat_sec": self._heartbeat_sec,
            "offline_after_missed": self._offline_after,
            "clients": self.list_clients(),
            "voice_relay": self._voice_relay.snapshot(),
        }

    def send_command(
        self,
        device_id: str,
        command: str,
        *,
        branch: str | None = None,
    ) -> dict[str, Any]:
        cmd = str(command or "").strip()
        if cmd not in {"set_normal", "set_power_save", "stop", "exit"}:
            return {"ok": False, "error": f"unsupported command: {command}"}
        payload: dict[str, Any] = {"type": cmd}
        if cmd == "set_power_save":
            branch_text = str(branch or "A").strip().upper()
            if branch_text not in {"A", "B"}:
                branch_text = "A"
            payload["branch"] = branch_text
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        frame = pack_frame(FRAME_COMMAND, body)
        with self._lock:
            client = self._clients.get(device_id)
            if client is None or client._sock is None:
                return {"ok": False, "error": "device not connected"}
            sock = client._sock
            if cmd == "set_normal":
                client.power_mode = "normal"
                client.recording = True
            elif cmd == "set_power_save":
                client.power_mode = "power_save"
                if payload.get("branch") == "B":
                    client.recording = False
                else:
                    client.recording = True
            elif cmd == "stop":
                client.recording = False
            elif cmd == "exit":
                client.recording = False
        try:
            with client._send_lock:
                sock.sendall(frame)
        except OSError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "device_id": device_id, "command": cmd, "payload": payload}

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            sock = self._server_sock
            if sock is None:
                break
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self._stop.is_set():
                    log.exception("audio pickup accept failed")
                break
            threading.Thread(
                target=self._client_loop,
                args=(conn, addr),
                name=f"audio-pickup-{addr[0]}",
                daemon=True,
            ).start()

    def _watch_loop(self) -> None:
        while not self._stop.wait(self._heartbeat_sec):
            now = time.time()
            threshold = self._heartbeat_sec * self._offline_after
            with self._lock:
                for client in self._clients.values():
                    if now - client.last_heartbeat_at > threshold:
                        if client.online:
                            client.online = False
                            log.warning(
                                "audio pickup offline device=%s last_hb=%.0fs ago",
                                client.device_id,
                                now - client.last_heartbeat_at,
                            )

    def _client_loop(self, conn: socket.socket, addr: tuple[str, int]) -> None:
        conn.settimeout(self._heartbeat_sec * 2)
        peer = f"{addr[0]}:{addr[1]}"
        device_id = ""
        client: PickupClient | None = None
        pcm_file = None
        try:
            while not self._stop.is_set():
                frame = read_frame(conn)
                if frame is None:
                    break
                frame_type, _flags, payload = frame
                if frame_type == FRAME_HELLO:
                    hello = _json_loads(payload)
                    device_id = str(hello.get("device_id") or "").strip() or f"pickup-{peer}"
                    now = time.time()
                    client = PickupClient(
                        device_id=device_id,
                        addr=peer,
                        connected_at=now,
                        last_heartbeat_at=now,
                        hello=hello,
                        _sock=conn,
                    )
                    with self._lock:
                        old = self._clients.get(device_id)
                        if old and old._sock is not None and old._sock is not conn:
                            try:
                                old._sock.close()
                            except OSError:
                                pass
                        self._clients[device_id] = client
                    if self._pcm_sink_dir:
                        from pathlib import Path

                        path = Path(self._pcm_sink_dir) / f"{device_id}.pcm"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        pcm_file = path.open("ab")
                    log.info("audio pickup hello device=%s from=%s", device_id, peer)
                    continue
                if client is None:
                    log.warning("audio pickup frame before hello from=%s type=%s", peer, frame_type)
                    break
                if frame_type == FRAME_HEARTBEAT:
                    client.last_heartbeat_at = time.time()
                    if not client.online:
                        client.online = True
                        log.info("audio pickup back online device=%s", device_id)
                    continue
                if frame_type == FRAME_PCM:
                    client.pcm_bytes += len(payload)
                    if pcm_file is not None:
                        pcm_file.write(payload)
                    self._voice_relay.forward(
                        FRAME_PCM,
                        payload,
                        device_id=device_id,
                        hello=client.hello,
                    )
                    continue
                log.debug("audio pickup ignored frame type=%s from=%s", frame_type, device_id)
        except ValueError as e:
            log.warning("audio pickup protocol error device=%s: %s", device_id or peer, e)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            if pcm_file is not None:
                try:
                    pcm_file.close()
                except OSError:
                    pass
            if client is not None:
                with self._lock:
                    current = self._clients.get(device_id)
                    if current is client:
                        client.online = False
                        client._sock = None
                log.info("audio pickup disconnected device=%s", device_id)


audio_pickup_service = AudioPickupService()
