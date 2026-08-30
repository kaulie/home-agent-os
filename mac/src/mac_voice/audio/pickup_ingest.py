"""Home Mic (phone HAP1) → local ingest → 16k PCM for voice.stream + speak downlink."""

from __future__ import annotations

import json
import logging
import queue
import socket
import struct
import threading
import time
from typing import Any, Iterator

import numpy as np

from mac_voice.audio.types import PCM_16K_MONO

log = logging.getLogger("mac_voice.audio.pickup_ingest")

MAGIC = b"HAP1"
HEADER_SIZE = 10
FRAME_HEARTBEAT = 1
FRAME_PCM = 2
FRAME_COMMAND = 3
FRAME_HELLO = 4

_active_lock = threading.Lock()
_active_server: "PickupIngestServer | None" = None


def get_active_ingest() -> "PickupIngestServer | None":
    with _active_lock:
        return _active_server


def pack_frame(frame_type: int, payload: bytes = b"") -> bytes:
    body = payload or b""
    return MAGIC + struct.pack(">BBI", frame_type & 0xFF, 0, len(body)) + body


def resample_s16le_mono(pcm: bytes, src_rate: int, dst_rate: int = 16_000) -> bytes:
    if not pcm or src_rate <= 0:
        return b""
    if src_rate == dst_rate:
        return pcm
    usable = len(pcm) - (len(pcm) % 2)
    if usable < 2:
        return b""
    x = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float32)
    n_dst = int(round(len(x) * float(dst_rate) / float(src_rate)))
    if n_dst <= 0:
        return b""
    t_src = np.linspace(0.0, 1.0, num=len(x), endpoint=False)
    t_dst = np.linspace(0.0, 1.0, num=n_dst, endpoint=False)
    y = np.interp(t_dst, t_src, x)
    return np.clip(y, -32768, 32767).astype("<i2").tobytes()


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


def read_frame(sock: socket.socket) -> tuple[int, bytes] | None:
    header = _recv_exact(sock, HEADER_SIZE)
    if header is None:
        return None
    if header[:4] != MAGIC:
        raise ValueError("invalid HAP1 magic")
    frame_type, _flags, length = struct.unpack(">BBI", header[4:])
    if length < 0 or length > 8_000_000:
        raise ValueError("invalid frame length")
    payload = _recv_exact(sock, length) if length else b""
    if payload is None and length > 0:
        return None
    return frame_type, payload or b""


class PickupIngestServer:
    """Accept phone HAP1; expose 16 kHz PCM; downlink speak commands on same TCP."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8792,
        chunk_ms: int = 100,
        queue_max: int = 200,
    ) -> None:
        self._host = host
        self._port = port
        self._chunk_bytes = int(
            PCM_16K_MONO.sample_rate * (chunk_ms / 1000.0) * PCM_16K_MONO.sample_width
        )
        self._q: queue.Queue[tuple[bytes, str] | None] = queue.Queue(maxsize=max(8, queue_max))
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._device_id = ""
        self._participant_id = ""
        self._sample_rate = 44_100
        self._pcm_bytes = 0
        self._lock = threading.Lock()
        # peer -> {conn, participant_id, device_id}
        self._clients: dict[str, dict[str, Any]] = {}
        # After HAP1 speak: mute ack bleed, then command-listen endpoint profile.
        self._segment_break = threading.Event()
        self._segment_mute_until = 0.0
        self._command_onset_deadline = 0.0
        self._command_utt_active = False
        self._phone_wake_silence_ms = 500
        self._phone_wake_max_ms = 3500
        self._phone_cmd_silence_ms = 2000
        self._phone_cmd_max_ms = 12_000
        self._command_window_ms = 5000

    def configure_phone_endpoint(
        self,
        *,
        wake_silence_ms: int,
        wake_max_speech_ms: int,
        command_silence_ms: int,
        command_max_speech_ms: int,
        command_window_ms: int,
    ) -> None:
        self._phone_wake_silence_ms = max(200, int(wake_silence_ms))
        self._phone_wake_max_ms = max(800, int(wake_max_speech_ms))
        self._phone_cmd_silence_ms = max(400, int(command_silence_ms))
        self._phone_cmd_max_ms = max(2000, int(command_max_speech_ms))
        self._command_window_ms = max(500, int(command_window_ms))

    def begin_command_listen(
        self,
        *,
        window_ms: int | None = None,
        hold_ms: float = 1100.0,
    ) -> None:
        """After「我在呢」: drop current clip, mute hold, open command onset window."""
        now = time.monotonic()
        hold = max(0.0, float(hold_ms)) / 1000.0
        window = max(0.5, float(window_ms if window_ms is not None else self._command_window_ms) / 1000.0)
        self._segment_break.set()
        self._segment_mute_until = now + hold
        self._command_onset_deadline = now + hold + window
        self._command_utt_active = False
        log.info(
            "phone_hap1 command listen window=%.1fs after hold=%.1fs silence_ms=%s max_ms=%s",
            window,
            hold,
            self._phone_cmd_silence_ms,
            self._phone_cmd_max_ms,
        )

    def note_segment_activity(self, state: str) -> None:
        """Track whether a command-profile utterance is in progress."""
        if state == "speech":
            now = time.monotonic()
            if now <= self._command_onset_deadline or self._command_utt_active:
                if not self._command_utt_active and now <= self._command_onset_deadline:
                    log.info("phone_hap1 command utterance started")
                self._command_utt_active = True
            return
        if state == "idle" and self._command_utt_active:
            self._command_utt_active = False
            self._command_onset_deadline = 0.0
            log.info("phone_hap1 command utterance ended → wake endpoint")

    def in_command_endpoint(self) -> bool:
        if self._command_utt_active:
            return True
        return time.monotonic() <= self._command_onset_deadline

    def phone_silence_ms(self) -> int:
        if self.in_command_endpoint():
            return self._phone_cmd_silence_ms
        return self._phone_wake_silence_ms

    def phone_max_speech_ms(self) -> int:
        if self.in_command_endpoint():
            return self._phone_cmd_max_ms
        return self._phone_wake_max_ms

    def request_segment_break(self, *, hold_ms: float = 1000.0) -> None:
        """Drop in-progress phone clip and hold mute briefly (wake-ack playback)."""
        self._segment_break.set()
        self._segment_mute_until = time.monotonic() + max(0.0, hold_ms) / 1000.0

    def should_mute_segmenter(self) -> bool:
        if self._segment_break.is_set():
            self._segment_break.clear()
            return True
        return time.monotonic() < self._segment_mute_until

    @property
    def device_id(self) -> str:
        with self._lock:
            return self._device_id

    @property
    def participant_id(self) -> str:
        """Runtime participant_id from HAP1 hello (iPhone Edge identity)."""
        with self._lock:
            return self._participant_id or self._device_id

    @property
    def pcm_bytes(self) -> int:
        with self._lock:
            return self._pcm_bytes

    @property
    def connected_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._host, self._port))
        sock.listen(4)
        sock.settimeout(1.0)
        self._sock = sock
        self._thread = threading.Thread(
            target=self._accept_loop,
            name="mac-voice-pickup-ingest",
            daemon=True,
        )
        self._thread.start()
        global _active_server
        with _active_lock:
            _active_server = self
        log.info("phone_hap1 ingest listening %s:%s (→ voice.stream STT)", self._host, self._port)

    def stop(self) -> None:
        self._stop.set()
        global _active_server
        with _active_lock:
            if _active_server is self:
                _active_server = None
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for meta in clients:
            conn = meta.get("conn")
            if isinstance(conn, socket.socket):
                try:
                    conn.close()
                except OSError:
                    pass
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def send_speak(self, text: str, *, participant_id: str = "") -> int:
        """Downlink HAP1 speak command. Returns number of phones notified."""
        body = (text or "").strip()
        if not body:
            return 0
        want = (participant_id or "").strip()
        payload = json.dumps(
            {"type": "speak", "text": body},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        frame = pack_frame(FRAME_COMMAND, payload)
        sent = 0
        with self._lock:
            targets = list(self._clients.items())
        # One phone can leave a stale TCP while reconnecting — only speak to the
        # newest socket per participant/device (peer = "ip:port", port rises).
        latest_by_key: dict[str, tuple[str, dict[str, Any]]] = {}
        for peer, meta in targets:
            pid = str(meta.get("participant_id") or "").strip()
            did = str(meta.get("device_id") or "").strip()
            if want and pid and pid != want and did != want:
                continue
            key = pid or did or peer
            prev = latest_by_key.get(key)
            if prev is None or peer > prev[0]:
                latest_by_key[key] = (peer, meta)
        for peer, meta in latest_by_key.values():
            pid = str(meta.get("participant_id") or "").strip()
            conn = meta.get("conn")
            if not isinstance(conn, socket.socket):
                continue
            try:
                conn.sendall(frame)
                sent += 1
                log.info(
                    "phone_hap1 speak → %s participant=%s text=%r",
                    peer,
                    pid or "-",
                    body[:80],
                )
            except OSError as e:
                log.warning("phone_hap1 speak failed peer=%s: %s", peer, e)
        if sent > 0:
            self.begin_command_listen(hold_ms=1100.0)
        return sent

    def iter_pcm(self, chunk_ms: int = 100) -> Iterator[bytes]:
        """Yield 16 kHz PCM only (legacy). Prefer iter_pcm_tagged for multi-phone."""
        for pcm, _pid in self.iter_pcm_tagged(chunk_ms=chunk_ms):
            yield pcm

    def iter_pcm_tagged(self, chunk_ms: int = 100) -> Iterator[tuple[bytes, str]]:
        del chunk_ms
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                if self._stop.is_set():
                    break
                continue
            yield item

    def _push(self, pcm16k: bytes, participant_id: str = "") -> None:
        if not pcm16k:
            return
        pid = (participant_id or "").strip()
        item = (pcm16k, pid)
        try:
            self._q.put_nowait(item)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(item)
            except queue.Full:
                pass

    def _register_client(
        self,
        peer: str,
        conn: socket.socket,
        *,
        participant_id: str,
        device_id: str,
    ) -> None:
        with self._lock:
            self._clients[peer] = {
                "conn": conn,
                "participant_id": participant_id,
                "device_id": device_id,
            }
            if device_id:
                self._device_id = device_id
            if participant_id:
                self._participant_id = participant_id
            elif not self._participant_id and device_id:
                self._participant_id = device_id

    def _unregister_client(self, peer: str) -> None:
        with self._lock:
            self._clients.pop(peer, None)

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                break
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self._stop.is_set():
                    log.exception("home_mic ingest accept failed")
                break
            threading.Thread(
                target=self._client_loop,
                args=(conn, addr),
                name=f"home-mic-ingest-{addr[0]}",
                daemon=True,
            ).start()

    def _client_loop(self, conn: socket.socket, addr: tuple[str, int]) -> None:
        conn.settimeout(30.0)
        peer = f"{addr[0]}:{addr[1]}"
        device_id = ""
        participant_id = ""
        sample_rate = 44_100
        pending = bytearray()
        registered = False
        log.info("home_mic ingest relay connected from=%s", peer)
        try:
            while not self._stop.is_set():
                frame = read_frame(conn)
                if frame is None:
                    break
                frame_type, payload = frame
                if frame_type == FRAME_HELLO:
                    hello: dict = {}
                    try:
                        parsed = json.loads(payload.decode("utf-8"))
                        if isinstance(parsed, dict):
                            hello = parsed
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        hello = {}
                    device_id = str(hello.get("device_id") or "").strip() or device_id
                    participant_id = str(
                        hello.get("participant_id")
                        or hello.get("edge_id")
                        or hello.get("input_participant_id")
                        or ""
                    ).strip()
                    try:
                        sample_rate = int(hello.get("sample_rate") or sample_rate)
                    except (TypeError, ValueError):
                        sample_rate = 44_100
                    with self._lock:
                        self._sample_rate = sample_rate
                    self._register_client(
                        peer,
                        conn,
                        participant_id=participant_id or device_id or peer,
                        device_id=device_id or peer,
                    )
                    registered = True
                    log.info(
                        "phone_hap1 hello participant=%s device=%s rate=%s from=%s",
                        participant_id or device_id or "-",
                        device_id or "-",
                        sample_rate,
                        peer,
                    )
                    continue
                if frame_type == FRAME_HEARTBEAT:
                    # Echo so the phone can detect half-open TCP after Mac restart.
                    try:
                        conn.sendall(pack_frame(FRAME_HEARTBEAT, b"{}"))
                    except OSError:
                        break
                    continue
                if frame_type != FRAME_PCM:
                    continue
                if not registered:
                    self._register_client(
                        peer,
                        conn,
                        participant_id=device_id or peer,
                        device_id=device_id or peer,
                    )
                    registered = True
                pcm16 = resample_s16le_mono(payload, sample_rate, PCM_16K_MONO.sample_rate)
                if not pcm16:
                    continue
                with self._lock:
                    self._pcm_bytes += len(payload)
                pending.extend(pcm16)
                owner = participant_id or device_id or peer
                while len(pending) >= self._chunk_bytes:
                    chunk = bytes(pending[: self._chunk_bytes])
                    del pending[: self._chunk_bytes]
                    self._push(chunk, owner)
        except ValueError as e:
            log.warning("home_mic ingest protocol error from=%s: %s", peer, e)
        except OSError:
            pass
        finally:
            self._unregister_client(peer)
            try:
                conn.close()
            except OSError:
                pass
            if pending:
                self._push(bytes(pending), participant_id or device_id or peer)
            log.info(
                "phone_hap1 disconnected from=%s participant=%s",
                peer,
                participant_id or device_id or "-",
            )
