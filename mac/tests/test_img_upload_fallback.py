"""img-server upload with LAN → cloud fallback + pre-upload probe."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.asset.img_upload import (
    ImgUploadError,
    UploadResult,
    normalize_upload_dest,
    probe_reachable,
    upload_image_file,
)


class ImgUploadFallbackTests(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_upload_dest(None), "lan")
        self.assertEqual(normalize_upload_dest("cloud"), "cloud")
        self.assertEqual(normalize_upload_dest("local"), "lan")
        self.assertEqual(normalize_upload_dest("img_server"), "lan")

    def test_lan_ok_does_not_mirror_to_cloud(self) -> None:
        calls: list[str] = []

        def fake_once(path: Path, dest: str) -> UploadResult:
            calls.append(dest)
            if dest == "lan":
                return UploadResult(
                    photo_url="http://192.168.3.65:8080/a.jpg",
                    saved_as="a.jpg",
                    dest="lan",
                    public_base="http://192.168.3.65:8080",
                    local_path=str(path),
                )
            raise AssertionError("cloud must not be called after LAN success")

        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(b"jpeg")
            f.flush()
            path = Path(f.name)
            with patch(
                "mac_edge.asset.img_upload.probe_reachable", return_value=True
            ), patch("mac_edge.asset.img_upload._upload_once", side_effect=fake_once):
                out = upload_image_file(path, preferred_dest="lan")
        self.assertEqual(calls, ["lan"])
        self.assertEqual(out.dest, "lan")
        self.assertFalse(out.cloud_public_base)
        self.assertFalse(out.cloud_saved_as)

    def test_lan_ok_no_fallback(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(b"jpeg")
            f.flush()
            path = Path(f.name)
            with patch(
                "mac_edge.asset.img_upload.probe_reachable", return_value=True
            ), patch(
                "mac_edge.asset.img_upload._upload_once",
                return_value=UploadResult(
                    photo_url="http://192.168.3.65:8080/a.jpg",
                    saved_as="a.jpg",
                    dest="lan",
                    public_base="http://192.168.3.65:8080",
                    local_path=str(path),
                ),
            ) as once:
                out = upload_image_file(path, preferred_dest="lan")
        self.assertEqual(out.dest, "lan")
        self.assertEqual(once.call_count, 1)
        self.assertFalse(out.cloud_public_base)
    def test_lan_fail_falls_back_to_cloud(self) -> None:
        calls: list[str] = []

        def fake_once(path: Path, dest: str) -> UploadResult:
            calls.append(dest)
            if dest == "lan":
                raise ImgUploadError("upload failed: timed out")
            return UploadResult(
                photo_url="http://115.190.153.53:8080/b.jpg",
                saved_as="b.jpg",
                dest="cloud",
                public_base="http://115.190.153.53:8080",
                local_path=str(path),
            )

        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(b"jpeg")
            f.flush()
            path = Path(f.name)
            with patch(
                "mac_edge.asset.img_upload.probe_reachable", return_value=True
            ), patch("mac_edge.asset.img_upload._upload_once", side_effect=fake_once):
                out = upload_image_file(path, preferred_dest="lan")
        self.assertEqual(calls, ["lan", "cloud"])
        self.assertEqual(out.dest, "cloud")
        self.assertIn("115.190.153.53", out.photo_url)

    def test_lan_probe_unreachable_skips_straight_to_cloud(self) -> None:
        calls: list[str] = []

        def fake_probe(dest: str, **_kwargs) -> bool:
            return dest != "lan"

        def fake_once(path: Path, dest: str) -> UploadResult:
            calls.append(dest)
            self.assertEqual(dest, "cloud")
            return UploadResult(
                photo_url="http://115.190.153.53:8080/c.jpg",
                saved_as="c.jpg",
                dest="cloud",
                public_base="http://115.190.153.53:8080",
                local_path=str(path),
            )

        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(b"jpeg")
            f.flush()
            path = Path(f.name)
            with patch(
                "mac_edge.asset.img_upload.probe_reachable", side_effect=fake_probe
            ), patch("mac_edge.asset.img_upload._upload_once", side_effect=fake_once):
                out = upload_image_file(path, preferred_dest="lan")
        self.assertEqual(calls, ["cloud"])
        self.assertEqual(out.dest, "cloud")

    def test_explicit_cloud_does_not_retry_lan(self) -> None:
        calls: list[str] = []

        def fake_once(path: Path, dest: str) -> UploadResult:
            calls.append(dest)
            raise ImgUploadError("cloud down")

        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(b"jpeg")
            f.flush()
            path = Path(f.name)
            with patch(
                "mac_edge.asset.img_upload.probe_reachable", return_value=True
            ), patch("mac_edge.asset.img_upload._upload_once", side_effect=fake_once):
                with self.assertRaises(ImgUploadError):
                    upload_image_file(path, preferred_dest="cloud")
        self.assertEqual(calls, ["cloud"])

    def test_probe_tcp_unreachable(self) -> None:
        with patch(
            "mac_edge.asset.img_upload.socket.create_connection",
            side_effect=OSError("timed out"),
        ):
            self.assertFalse(probe_reachable("lan"))


if __name__ == "__main__":
    unittest.main()
