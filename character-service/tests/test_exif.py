"""EXIF orientation parser — no OpenCV / MediaPipe."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hands import jpeg_exif_orientation  # noqa: E402


def _exif_jpeg(orientation: int) -> bytes:
    tiff = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)
    tiff += struct.pack("<H", 1)
    tiff += struct.pack("<HHI", 0x0112, 3, 1) + struct.pack("<H", orientation) + b"\x00\x00"
    tiff += struct.pack("<I", 0)
    payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return b"\xff\xd8" + app1 + b"\xff\xd9"


class ExifTests(unittest.TestCase):
    def test_orientation_6(self) -> None:
        self.assertEqual(jpeg_exif_orientation(_exif_jpeg(6)), 6)

    def test_missing_is_1(self) -> None:
        self.assertEqual(jpeg_exif_orientation(b"\xff\xd8\xff\xd9"), 1)
        self.assertEqual(jpeg_exif_orientation(b"not-a-jpeg"), 1)


if __name__ == "__main__":
    unittest.main()
