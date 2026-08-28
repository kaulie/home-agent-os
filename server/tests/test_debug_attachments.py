"""Tests for debug attachment normalization."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from debug_attachments import attachment_asset_ids, normalize_attachments  # noqa: E402


class DebugAttachmentTests(unittest.TestCase):
    def test_normalize_object_attachments(self) -> None:
        rows = normalize_attachments(
            [
                {"asset_id": "asset_a", "kind": "image", "mime_type": "image/jpeg"},
                {"asset_id": "asset_b", "kind": "file", "filename": "x.log"},
            ]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["kind"], "image")
        self.assertEqual(rows[1]["filename"], "x.log")

    def test_legacy_string_ids_become_image_attachments(self) -> None:
        rows = normalize_attachments(["asset_a", "asset_a", "asset_b"])
        self.assertEqual(rows, [{"asset_id": "asset_a", "kind": "image"}, {"asset_id": "asset_b", "kind": "image"}])
        self.assertEqual(attachment_asset_ids(rows), ["asset_a", "asset_b"])


if __name__ == "__main__":
    unittest.main()
