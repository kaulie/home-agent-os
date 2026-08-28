"""MediaPipe Hands on a still image. Import is lazy so unit tests skip it."""

from __future__ import annotations

import struct
from typing import Any

INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8
PAD_FRAC = 0.18
_DETECT_SCALES = (1600, 1200, 800, 2000)
_DETECT_CONFS = (0.35, 0.15, 0.05)
_DETECT_COMPLEXITIES = (1, 0)

_hands: dict[tuple[float, int], Any] = {}


class HandsError(Exception):
    pass


def jpeg_exif_orientation(data: bytes) -> int:
    """JPEG EXIF Orientation 1–8. Default 1 if missing."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return 1
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker in (0xDA, 0xD9):
            break
        seglen = int.from_bytes(data[i + 2 : i + 4], "big")
        if seglen < 2 or i + 2 + seglen > len(data):
            break
        payload = data[i + 4 : i + 2 + seglen]
        i += 2 + seglen
        if marker != 0xE1 or not payload.startswith(b"Exif\x00\x00"):
            continue
        tiff = payload[6:]
        if len(tiff) < 8:
            return 1
        endian = "<" if tiff[:2] == b"II" else ">" if tiff[:2] == b"MM" else None
        if endian is None:
            return 1
        off = struct.unpack(endian + "I", tiff[4:8])[0]
        if off + 2 > len(tiff):
            return 1
        ntags = struct.unpack(endian + "H", tiff[off : off + 2])[0]
        off += 2
        for _ in range(ntags):
            if off + 12 > len(tiff):
                break
            tag, typ, _count = struct.unpack(endian + "HHI", tiff[off : off + 8])
            val = tiff[off + 8 : off + 12]
            off += 12
            if tag != 0x0112:
                continue
            if typ == 3:
                return int(struct.unpack(endian + "H", val[:2])[0])
            if typ == 4:
                return int(struct.unpack(endian + "I", val[:4])[0])
        return 1
    return 1


def apply_exif_orientation(image_bgr: Any, orientation: int) -> Any:
    import cv2

    if orientation == 2:
        return cv2.flip(image_bgr, 1)
    if orientation == 3:
        return cv2.rotate(image_bgr, cv2.ROTATE_180)
    if orientation == 4:
        return cv2.flip(image_bgr, 0)
    if orientation == 5:
        return cv2.rotate(cv2.flip(image_bgr, 1), cv2.ROTATE_90_COUNTERCLOCKWISE)
    if orientation == 6:
        return cv2.rotate(image_bgr, cv2.ROTATE_90_CLOCKWISE)
    if orientation == 7:
        return cv2.rotate(cv2.flip(image_bgr, 1), cv2.ROTATE_90_CLOCKWISE)
    if orientation == 8:
        return cv2.rotate(image_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image_bgr


def _mp_hands(min_detection_confidence: float, model_complexity: int = 1) -> Any:
    key = (round(float(min_detection_confidence), 2), int(model_complexity))
    if key in _hands:
        return _hands[key]
    try:
        import mediapipe as mp
    except ImportError as e:
        raise HandsError("MediaPipe 未安装（应在 reading-service 容器内）") from e
    _hands[key] = mp.solutions.hands.Hands(
        static_image_mode=True,
        max_num_hands=2,
        model_complexity=model_complexity,
        min_detection_confidence=key[0],
        min_tracking_confidence=key[0],
    )
    return _hands[key]


def decode_bgr(image_bytes: bytes) -> Any:
    import cv2
    import numpy as np

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    # OpenCV 4.x IMREAD_COLOR already applies JPEG EXIF. Ignore it so
    # apply_exif_orientation is the only rotate (older OpenCV stays consistent).
    flags = cv2.IMREAD_COLOR
    ignore = getattr(cv2, "IMREAD_IGNORE_ORIENTATION", 0)
    if ignore:
        flags |= ignore
    img = cv2.imdecode(arr, flags)
    if img is None:
        raise HandsError("无法解码图片")
    return apply_exif_orientation(img, jpeg_exif_orientation(image_bytes))


def encode_jpeg(image_bgr: Any, quality: int = 92) -> bytes | None:
    try:
        import cv2

        ok, buf = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if ok:
            return buf.tobytes()
    except Exception:
        return None
    return None


def _landmarks_all_hands(result: Any, w: int, h: int) -> list[dict[int, tuple[float, float]]]:
    if not result.multi_hand_landmarks:
        return []
    out: list[dict[int, tuple[float, float]]] = []
    for hand in result.multi_hand_landmarks:
        lm = hand.landmark
        if len(lm) < 21:
            continue
        pts = {i: (lm[i].x * w, lm[i].y * h) for i in range(21)}
        out.append(pts)
    return out


def _detect_on(image_bgr: Any, conf: float, complexity: int = 1) -> list[dict[int, tuple[float, float]]]:
    import cv2

    h, w = image_bgr.shape[:2]
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    return _landmarks_all_hands(_mp_hands(conf, complexity).process(rgb), w, h)


def _rescale_hands(
    found: list[dict[int, tuple[float, float]]], scale: float, pad: int = 0
) -> list[dict[int, tuple[float, float]]]:
    return [
        {idx: ((x - pad) / scale, (y - pad) / scale) for idx, (x, y) in hand.items()}
        for hand in found
    ]


def detect_hands_landmarks(
    image_bgr: Any, max_dim: int = 1600
) -> list[dict[int, tuple[float, float]]]:
    """All MediaPipe hands (21 landmarks each) in original-image pixels, or []."""
    import cv2

    h, w = image_bgr.shape[:2]
    scales_tried: list[tuple[float, Any]] = []
    for md in _DETECT_SCALES:
        if max(h, w) > md:
            s = md / max(h, w)
            scales_tried.append((s, cv2.resize(image_bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)))
        elif not scales_tried:
            scales_tried.append((1.0, image_bgr))

    for scale, small in scales_tried:
        for complexity in _DETECT_COMPLEXITIES:
            for conf in _DETECT_CONFS:
                found = _detect_on(small, conf, complexity)
                if found:
                    return _rescale_hands(found, scale)

    for scale, small in scales_tried:
        pad = max(24, int(PAD_FRAC * max(small.shape[:2])))
        padded = cv2.copyMakeBorder(
            small, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0)
        )
        for complexity in _DETECT_COMPLEXITIES:
            for conf in _DETECT_CONFS:
                found = _detect_on(padded, conf, complexity)
                if found:
                    return _rescale_hands(found, scale, pad)
    return []


def detect_index_landmarks(image_bgr: Any, max_dim: int = 1600) -> dict[int, tuple[float, float]] | None:
    """First hand's index MCP/PIP/DIP/TIP, or None. Kept for eval dumps."""
    hands = detect_hands_landmarks(image_bgr, max_dim=max_dim)
    if not hands:
        return None
    lm = hands[0]
    if INDEX_TIP not in lm:
        return None
    return {
        INDEX_MCP: lm[INDEX_MCP],
        INDEX_PIP: lm[INDEX_PIP],
        INDEX_DIP: lm[INDEX_DIP],
        INDEX_TIP: lm[INDEX_TIP],
    }
