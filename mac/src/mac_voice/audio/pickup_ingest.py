"""Home Mic (Brain audio_pickup) → local HAP1 ingest → 16k PCM for voice.stream."""

from __future__ import annotations

import json
import logging
import queue
import socket
import struct
import threading
from typing import Iterator

import numpy as np

from mac_voice.audio.types import PCM_16K_MONO

log = logging.getLogger("mac_voice.audio.pickup_ingest")

MAGIC = b"HAP1"
HEADER_SIZE = 10
FRAME_HEARTBEAT = 1
FRAME_PCM = 2
FRAME_HELLO = 4


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
    """Accept Brain-relayed Home Mic HAP1 and expose 16 kHz PCM chunks."""

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
        self._q: queue.Queue[bytes | None] = queue.Queue(maxsize=max(8, queue_max))
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._device_id = ""
        self._participant_id = ""
        self._sample_rate = 44_100
        self._pcm_bytes = 0
        self._lock = threading.Lock()

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
        log.info("phone_hap1 ingest listening %s:%s (→ voice.stream STT)", self._host, self._port)

    def stop(self) -> None:
        self._stop.set()
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

    def iter_pcm(self, chunk_ms: int = 100) -> Iterator[bytes]:
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

    def _push(self, pcm16k: bytes) -> None:
        if not pcm16k:
            return
        try:
            self._q.put_nowait(pcm16k)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(pcm16k)
            except queue.Full:
                pass

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
        sample_rate = 44_100
        pending = bytearray()
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
                        self._device_id = device_id or peer
                        if participant_id:
                            self._participant_id = participant_id
                        elif not self._participant_id:
                            self._participant_id = self._device_id
                        self._sample_rate = sample_rate
                    log.info(
                        "phone_hap1 hello participant=%s device=%s rate=%s from=%s",
                        self.participant_id,
                        self.device_id,
                        sample_rate,
                        peer,
                    )
                    continue
                if frame_type == FRAME_HEARTBEAT:
                    continue
                if frame_type != FRAME_PCM:
                    continue
                pcm16 = resample_s16le_mono(payload, sample_rate, PCM_16K_MONO.sample_rate)
                if not pcm16:
                    continue
                with self._lock:
                    self._pcm_bytes += len(payload)
                pending.extend(pcm16)
                while len(pending) >= self._chunk_bytes:
                    chunk = bytes(pending[: self._chunk_bytes])
                    del pending[: self._chunk_bytes]
                    self._push(chunk)
        except ValueError as e:
            log.warning("home_mic ingest protocol error from=%s: %s", peer, e)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            if pending:
                self._push(bytes(pending))
            log.info(
                "phone_hap1 disconnected from=%s participant=%s",
                peer,
                self.participant_id or device_id or "-",
            )
