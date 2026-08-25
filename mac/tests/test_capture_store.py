"""Runtime-private GoPro inbox."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mac_edge.capture import store as capture_store
from mac_edge.capture.store import CaptureStoreError


class CaptureStoreTests(unittest.TestCase):
    def test_put_open_mark_unique_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"MAC_EDGE_DATA_DIR": td}):
                cref = capture_store.put(b"hello-jpeg", original_name="GOPR.JPG")
                cid = cref["capture_id"]
                self.assertTrue(cid.startswith("cap_"))
                self.assertEqual(cref["type"], "image")
                path = capture_store.open_jpeg(cid)
                self.assertEqual(path.read_bytes(), b"hello-jpeg")
                self.assertEqual(capture_store.unique_pending("img_server"), cid)
                capture_store.mark_uploaded(cid, "img_server")
                with self.assertRaises(CaptureStoreError):
                    capture_store.unique_pending("img_server")
                self.assertEqual(capture_store.unique_pending("cloud"), cid)
                jpeg = Path(td) / "captures" / "inbox" / f"{cid}.jpg"
                self.assertTrue(jpeg.is_file())


if __name__ == "__main__":
    unittest.main()
