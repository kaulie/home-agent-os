"""Independent proof that TTS actually left the speakers.

afplay exit 0 is not enough (muted output, wrong device, volume 0).
This records the USB mic during playback and compares RMS to a short
ambient window. Same room as the lamp is the point.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from mac_edge.plugins.voice_test.timeline import iso_now

log = logging.getLogger("mac_edge.voice_test.loopback")

SAMPLE_RATE = 16000
AMBIENT_SEC = 0.35
RATIO_MIN = 2.5
RMS_PLAY_FLOOR = 0.01  # float32 abs RMS; silence is ~0.001


class LoopbackError(Exception):
    pass


@dataclass(frozen=True)
class LoopbackResult:
    heard: bool
    rms_ambient: float
    rms_play: float
    ratio: float
    wav_path: str = ""
    device: str = ""
    error_reason: str = ""
    play_started_at: str = ""
    play_ended_at: str = ""
    confirmed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mic_device() -> int | str | None:
    raw = (
        os.environ.get("MAC_EDGE_VOICE_TEST_MIC_DEVICE")
        or os.environ.get("MAC_VOICE_INPUT_DEVICE")
        or ""
    ).strip()
    if not raw:
        return _guess_respeaker()
    try:
        return int(raw)
    except ValueError:
        return raw


def _guess_respeaker() -> int | str | None:
    try:
        import sounddevice as sd
    except ImportError:
        return None
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    for i, dev in enumerate(devices):
        name = str(dev.get("name") or "")
        if "respeaker" in name.lower() or "xvf3800" in name.lower():
            if int(dev.get("max_input_channels") or 0) > 0:
                return i
    return None


def _rms(samples: Any) -> float:
    import numpy as np

    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return 0.0
    return float((arr * arr).mean() ** 0.5)


def heard_from_rms(
    rms_ambient: float,
    rms_play: float,
    *,
    ratio_min: float = RATIO_MIN,
    play_floor: float = RMS_PLAY_FLOOR,
) -> bool:
    if rms_play < play_floor:
        return False
    denom = max(rms_ambient, 1e-6)
    return (rms_play / denom) >= ratio_min


def _write_wav(path: Path, pcm_f32: Any, *, sample_rate: int = SAMPLE_RATE) -> Path:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(pcm_f32, dtype=np.float32).reshape(-1)
    pcm = (arr.clip(-1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return path


def record_seconds(
    duration_sec: float,
    *,
    wav_dest: Path,
    device: int | str | None = None,
) -> Path:
    """Record the mic for ``duration_sec``. Used to listen for 在呢 after wake TTS.

    Does not prove speakers played. That is confirm_play / RMS.
    """
    import numpy as np
    import sounddevice as sd

    dev = device if device is not None else _mic_device()
    if dev is None:
        raise LoopbackError("无法听台灯应答：找不到 USB 麦。")
    sec = max(0.05, float(duration_sec))
    chunks: list[Any] = []
    lock = threading.Lock()

    def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
        _ = (frames, time_info)
        if status:
            log.warning("record status=%s", status)
        with lock:
            chunks.append(indata.copy())

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=dev,
            callback=callback,
        ):
            time.sleep(sec)
    except Exception as e:
        raise LoopbackError(f"麦克风录音失败（device={dev}：{e}）") from e
    with lock:
        data = list(chunks)
    if not data:
        raise LoopbackError("麦克风录音失败：没有采到任何采样。")
    pcm = np.concatenate(data, axis=0)
    return _write_wav(wav_dest, pcm)


def confirm_play(
    play_fn: Callable[[], None],
    *,
    wav_dest: Path | None = None,
    device: int | str | None = None,
    required: bool = True,
    skip_ambient: bool = False,
) -> LoopbackResult:
    """Run play_fn while recording the mic. Raises if required and not heard."""
    dev = device if device is not None else _mic_device()
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as e:
        if required:
            raise LoopbackError(
                "无法确认扬声器出声：未安装 sounddevice/numpy。"
            ) from e
        log.warning("loopback skipped: sounddevice/numpy missing")
        return LoopbackResult(False, 0.0, 0.0, 0.0, error_reason="loopback_skipped")

    if dev is None:
        msg = "无法确认扬声器出声：找不到 USB 麦（设 MAC_EDGE_VOICE_TEST_MIC_DEVICE）。"
        if required:
            raise LoopbackError(msg)
        return LoopbackResult(False, 0.0, 0.0, 0.0, error_reason="no_mic")

    chunks: list[Any] = []
    lock = threading.Lock()
    mark = {"ambient_done": False, "split": 0}
    play_started_at = ""
    play_ended_at = ""

    def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
        _ = (frames, time_info)
        if status:
            log.warning("loopback status=%s", status)
        with lock:
            chunks.append(indata.copy())
            if not mark["ambient_done"]:
                mark["split"] = len(chunks)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=dev,
            callback=callback,
        ):
            if not skip_ambient:
                time.sleep(AMBIENT_SEC)
            with lock:
                mark["ambient_done"] = True
                mark["split"] = 0 if skip_ambient else len(chunks)
            play_started_at = iso_now()
            play_fn()
            play_ended_at = iso_now()
            time.sleep(0.08)
    except Exception as e:
        raise LoopbackError(f"麦克风回录失败（device={dev}：{e}）") from e

    with lock:
        split = int(mark["split"])
        data = list(chunks)
    if not data:
        raise LoopbackError("麦克风回录失败：没有采到任何采样。")

    ambient = np.concatenate(data[:split], axis=0) if split else np.zeros((1, 1), np.float32)
    played = np.concatenate(data[split:], axis=0) if split < len(data) else np.zeros((1, 1), np.float32)
    rms_a = _rms(ambient)
    rms_p = _rms(played)
    ratio = rms_p / max(rms_a, 1e-6)
    ok = heard_from_rms(rms_a, rms_p)
    wav_path = ""
    if wav_dest is not None:
        wav_path = str(_write_wav(wav_dest, played))
    confirmed_at = iso_now()
    result = LoopbackResult(
        heard=ok,
        rms_ambient=round(rms_a, 6),
        rms_play=round(rms_p, 6),
        ratio=round(ratio, 3),
        wav_path=wav_path,
        device=str(dev),
        error_reason="" if ok else "playback_not_heard",
        play_started_at=play_started_at,
        play_ended_at=play_ended_at,
        confirmed_at=confirmed_at,
    )
    log.info(
        "loopback heard=%s rms_ambient=%.5f rms_play=%.5f ratio=%.2f device=%s",
        ok,
        rms_a,
        rms_p,
        ratio,
        dev,
    )
    if required and not ok:
        raise LoopbackError(
            "扬声器没有被麦克风听到"
            f"（ambient_rms={result.rms_ambient} play_rms={result.rms_play} "
            f"ratio={result.ratio} device={dev}）。"
            "请检查音量、输出设备和 USB 麦。"
        )
    return result


def write_sidecar(audio_path: Path, result: LoopbackResult) -> Path:
    path = Path(str(audio_path) + ".loopback.json")
    path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
