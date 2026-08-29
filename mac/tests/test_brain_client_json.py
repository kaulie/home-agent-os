"""BrainClient JSON error handling."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from mac_edge.brain_client import BrainClient, BrainError


class BrainClientJsonTests(unittest.TestCase):
    def test_json_or_raise_rejects_err_msg_on_http_200(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"err_msg": "intent not exist"}
        with self.assertRaises(BrainError) as ctx:
            BrainClient._json_or_raise(resp, "intent_status")
        self.assertIn("intent not exist", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
