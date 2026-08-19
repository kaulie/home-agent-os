"""Asset type parsing — design scaffold."""

from __future__ import annotations

import unittest

from mac_edge.asset.types import AssetRef


class AssetRefTests(unittest.TestCase):
    def test_round_trip_dict(self) -> None:
        ref = AssetRef(asset_id="asset_01JTEST", type="image", mime_type="image/jpeg")
        got = AssetRef.from_dict(ref.to_dict())
        assert got is not None
        self.assertEqual(got.asset_id, ref.asset_id)
        self.assertEqual(got.type, ref.type)
        self.assertEqual(got.mime_type, ref.mime_type)

    def test_from_dict_rejects_missing_id(self) -> None:
        self.assertIsNone(AssetRef.from_dict({"type": "image"}))


if __name__ == "__main__":
    unittest.main()
