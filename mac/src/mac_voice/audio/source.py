"""AudioSource implementations — continuous USB mic via sounddevice (save_sound.py style)."""

from __future__ import annotations

import logging
import queue
from typing import Iterator

from mac_voice.audio.types import AudioFormat, PCM_16K_MONO

log = logging.getLogger("mac_voice.audio.source")

_RESPEAKER_MARKERS = ("respeaker", "xvf3800")


def _query_devices() -> list[dict]:
    """One PortAudio snapshot (may be a stale, process-lifetime cached view)."""
    import sounddevice as sd

    return list(sd.query_devices())


def _has_inputs(devices: list[dict]) -> bool:
    return any(int(d.get("max_input_channels") or 0) > 0 for d in devices)


def _reinit_host_api() -> bool:
    """Tear down + re-scan the host API so newly (un)plugged USB gear shows up.

    PortAudio caches the device list for the lifetime of the process, so a mic
    plugged in *after* startup is invisible here while ``system_profiler`` and
    fresh processes still see it. Returns False if the re-init failed.
    """
    import sounddevice as sd

    try:
        sd._terminate()
        sd._initialize()
    except Exception as e:
        log.warning("PortAudio re-init failed: %s", e)
        return False
    return True


def _live_device_list() -> list[dict]:
    """Query PortAudio; if the input catalog is empty, re-init the host API once.

    A second mac_voice (or a USB blip) can leave this process with a dead
    CoreAudio snapshot: ``query_devices()`` returns no inputs even though
    the array is still plugged in. Fresh processes still see the hardware.

    Note this only catches the *empty* snapshot. A snapshot that still lists
    other inputs never refreshes here — that case is handled in
    ``resolve_input_device`` (miss → re-scan → retry).
    """
    devices = _query_devices()
    if _has_inputs(devices):
        return devices
    log.warning("PortAudio listed no input devices; re-initializing host API")
    if not _reinit_host_api():
        return devices
    return _query_devices()


def _input_catalog(devices: list[dict] | None = None) -> list[tuple[int, str]]:
    if devices is None:
        devices = _live_device_list()
    out: list[tuple[int, str]] = []
    for i, dev in enumerate(devices):
        if int(dev.get("max_input_channels") or 0) > 0:
            out.append((i, str(dev.get("name") or "")))
    return out


def _looks_respeaker(name: str) -> bool:
    folded = name.casefold()
    return any(m in folded for m in _RESPEAKER_MARKERS)


def _guess_respeaker(catalog: list[tuple[int, str]]) -> int | None:
    for index, name in catalog:
        if _looks_respeaker(name):
            return index
    return None


def resolve_input_device(
    device: int | str | None,
    *,
    devices: list[dict] | None = None,
    fallback_index: int | None = None,
) -> int:
    """Map config name/index to a PortAudio index. Prefer index over name at open.

    ``InputStream(device='reSpeaker …')`` uses PortAudio string match, which
    fails if the USB array is not yet enumerated or the CoreAudio label drifts.

    PortAudio's device list is a snapshot taken when this process first asked
    for it, so a mic plugged in *after* startup is missing here even though
    ``system_profiler`` and fresh processes see it. When nothing matches we
    re-scan the host API once and retry — that is what lets a long-running
    mac_voice pick up a later-plugged USB mic without a restart.
    """

    def _attempt(catalog: list[tuple[int, str]]) -> int:
        listed = ", ".join(f"{i}:{n!r}" for i, n in catalog) or "(none)"
        if not catalog and fallback_index is not None:
            log.warning(
                "input catalog empty; retrying last resolved index %s",
                fallback_index,
            )
            return fallback_index

        if device is None or device == "":
            guessed = _guess_respeaker(catalog)
            if guessed is not None:
                return guessed
            raise ValueError(f"no input device; available: {listed}")

        if isinstance(device, int):
            for index, _name in catalog:
                if index == device:
                    return index
            raise ValueError(f"no input device {device}; available: {listed}")

        name = str(device).strip().strip("\"'")
        exact = [i for i, n in catalog if n == name]
        if exact:
            return exact[0]
        folded = name.casefold()
        ci = [i for i, n in catalog if n.casefold() == folded]
        if ci:
            return ci[0]
        sub = [
            i
            for i, n in catalog
            if folded in n.casefold() or n.casefold() in folded
        ]
        if sub:
            return sub[0]
        if _looks_respeaker(name):
            guessed = _guess_respeaker(catalog)
            if guessed is not None:
                log.warning(
                    "no input matching %r; using reSpeaker index %s (%s)",
                    name,
                    guessed,
                    dict(catalog).get(guessed, ""),
                )
                return guessed
        raise ValueError(f"No input device matching {name!r}; available: {listed}")

    catalog = _input_catalog(devices)
    try:
        return _attempt(catalog)
    except ValueError:
        if devices is not None:
            # Caller pinned the catalog (tests / injected devices) — judge by it.
            raise
        log.warning(
            "no input device matching %r among %s; re-scanning host API",
            device,
            ", ".join(f"{i}:{n!r}" for i, n in catalog) or "(none)",
        )
        if not _reinit_host_api():
            raise
        return _attempt(_input_catalog(None))


def pcm_chunk_bytes(fmt: AudioFormat = PCM_16K_MONO, chunk_ms: int = 100) -> int:
    return max(1, fmt.sample_rate * fmt.channels * fmt.sample_width * chunk_ms // 1000)


class NullAudioSource:
    """Placeholder when no device is configured."""

    def open(self) -> None:
        raise RuntimeError("No AudioSource configured; use --file WAV or --live")

    def close(self) -> None:
        return

    def iter_pcm(self, chunk_ms: int = 100) -> Iterator[bytes]:
        raise RuntimeError("No AudioSource configured")
        yield b""  # pragma: no cover


class SoundDeviceAudioSource:
    """Continuous InputStream → int16 PCM chunks (same stack as save_sound.py)."""

    def __init__(
        self,
        *,
        device: int | str | None = 0,
        format: AudioFormat = PCM_16K_MONO,
        block_ms: int = 100,
        queue_max: int = 200,
    ) -> None:
        self._device = device
        self._format = format
        self._block_ms = max(20, block_ms)
        self._q: queue.Queue[bytes | None] = queue.Queue(maxsize=queue_max)
        self._stream = None
        self._opened = False
        self._closed = False
        self._last_resolved: int | None = None

    def _drain_queue(self) -> None:
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    def open(self) -> None:
        if self._opened:
            return
        self._closed = False
        self._drain_queue()
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError as e:
            raise RuntimeError(
                "sounddevice/numpy required for --live; pip install sounddevice numpy"
            ) from e

        fmt = self._format
        blocksize = max(1, fmt.sample_rate * self._block_ms // 1000)

        def callback(indata, frames_, time_info, status) -> None:  # noqa: ANN001
            if status:
                log.warning("InputStream status=%s", status)
            if self._closed:
                return
            mono = indata[:, 0] if indata.ndim > 1 else indata.reshape(-1)
            pcm = (mono * 32767.0).clip(-32768, 32767).astype(np.int16).tobytes()
            try:
                self._q.put_nowait(pcm)
            except queue.Full:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._q.put_nowait(pcm)
                except queue.Full:
                    pass

        resolved = resolve_input_device(
            self._device,
            fallback_index=self._last_resolved,
        )
        log.info(
            "open mic device=%s resolved=%s rate=%s channels=%s block_ms=%s",
            self._device,
            resolved,
            fmt.sample_rate,
            fmt.channels,
            self._block_ms,
        )
        self._stream = sd.InputStream(
            device=resolved,
            samplerate=fmt.sample_rate,
            channels=fmt.channels,
            callback=callback,
            dtype="float32",
            blocksize=blocksize,
        )
        self._stream.start()
        self._last_resolved = resolved
        self._opened = True

    def close(self, *, retry: bool = False) -> None:
        if not retry:
            self._closed = True
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                log.warning("close stream: %s", e)
            self._stream = None
        if retry:
            self._drain_queue()
        else:
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
        self._opened = False

    def iter_pcm(self, chunk_ms: int = 100) -> Iterator[bytes]:
        """Yield int16 PCM; uses stream block_ms. Stops on close()."""
        if not self._opened:
            self.open()
        while not self._closed:
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            yield item
