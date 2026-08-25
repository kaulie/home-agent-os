"""Local USB / built-in webcam still capture via ffmpeg AVFoundation.

Not GoPro ``camera.capture``: that capability switches Wi-Fi and is too slow
for a voice-trial loop.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("mac_edge.voice_test.webcam")

FFMPEG_BIN = "/usr/local/bin/ffmpeg"


class WebcamError(Exception):
    pass


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg") or FFMPEG_BIN
    if not path or not Path(path).exists():
        raise WebcamError("摄像头拍照失败：本机找不到 ffmpeg。")
    return path


def capture_still(
    dest: Path,
    *,
    device: str = "0",
    timeout_sec: float = 12.0,
) -> Path:
    """Grab a still from the Mac camera. Last of a short burst (auto-exposure)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    dev = (device or "0").strip() or "0"
    ffmpeg = _ffmpeg()
    # Overwrite the same JPEG so the last frame (better exposure) remains.
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "avfoundation",
        "-pixel_format",
        "uyvy422",
        "-framerate",
        "30",
        "-video_size",
        "1280x720",
        "-i",
        f"{dev}:none",
        "-frames:v",
        "8",
        "-update",
        "1",
        "-y",
        str(dest),
    ]
    log.info("webcam capture device=%s dest=%s", dev, dest)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise WebcamError(f"摄像头拍照超时（device={dev}）。") from e
    except OSError as e:
        raise WebcamError(f"摄像头拍照失败（{e}）。") from e
    err = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0:
        raise WebcamError(
            f"摄像头拍照失败（device={dev}，{err or f'exit {proc.returncode}'}）。"
            "请检查系统设置 → 隐私与安全性 → 摄像头，以及 MAC_EDGE_WEBCAM_DEVICE。"
        )
    if not dest.is_file() or dest.stat().st_size < 128:
        raise WebcamError(
            f"摄像头拍照失败：输出为空（device={dev}）。"
            "请检查 MAC_EDGE_WEBCAM_DEVICE，以及系统设置 → 隐私与安全性 → 摄像头。"
        )
    return dest
