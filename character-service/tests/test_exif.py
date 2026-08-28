"""EXIF orientation parser + decode_bgr (OpenCV tests skip if missing)."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hands import apply_exif_orientation, jpeg_exif_orientation  # noqa: E402


def _exif_app1(orientation: int) -> bytes:
    tiff = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)
    tiff += struct.pack("<H", 1)
    tiff += struct.pack("<HHI", 0x0112, 3, 1) + struct.pack("<H", orientation) + b"\x00\x00"
    tiff += struct.pack("<I", 0)
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def _exif_jpeg(orientation: int) -> bytes:
    return b"\xff\xd8" + _exif_app1(orientation) + b"\xff\xd9"


def _pixel_jpeg_with_exif(orientation: int, width: int, height: int) -> bytes:
    import cv2
    import numpy as np

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[: height // 2] = (0, 0, 255)
    ok, buf = cv2.imencode(".jpg", canvas)
    if not ok:
        raise RuntimeError("imencode failed")
    jpeg = bytes(buf)
    if jpeg[:2] != b"\xff\xd8":
        raise RuntimeError("not a JPEG")
    return b"\xff\xd8" + _exif_app1(orientation) + jpeg[2:]


class ExifTests(unittest.TestCase):
    def test_orientation_6(self) -> None:
        self.assertEqual(jpeg_exif_orientation(_exif_jpeg(6)), 6)

    def test_missing_is_1(self) -> None:
        self.assertEqual(jpeg_exif_orientation(b"\xff\xd8\xff\xd9"), 1)
        self.assertEqual(jpeg_exif_orientation(b"not-a-jpeg"), 1)

    def test_decode_bgr_orientation_6_not_double_rotated(self) -> None:
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV not installed")
        from hands import decode_bgr

        # Stored 20×40, EXIF=6 → one 90° CW → 40×20. Double-rotate would stay 20×40.
        data = _pixel_jpeg_with_exif(6, 20, 40)
        self.assertEqual(jpeg_exif_orientation(data), 6)
        img = decode_bgr(data)
        h, w = img.shape[:2]
        self.assertEqual((w, h), (40, 20))

        flags = cv2.IMREAD_COLOR
        ignore = getattr(cv2, "IMREAD_IGNORE_ORIENTATION", 0)
        raw = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), flags | ignore if ignore else flags)
        self.assertIsNotNone(raw)
        once = apply_exif_orientation(raw, 6)
        self.assertEqual(once.shape[:2], (20, 40))
        twice = apply_exif_orientation(once, 6)
        self.assertEqual(twice.shape[:2], (40, 20))
        self.assertEqual(img.shape[:2], once.shape[:2])


if __name__ == "__main__":
    unittest.main()
