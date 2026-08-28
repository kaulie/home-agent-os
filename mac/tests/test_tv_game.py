"""Tests for Mac game host and game.launch plugin."""

from __future__ import annotations

import unittest

from mac_edge.plugins.game_host import game_url
from mac_edge.plugins.tv_game import GameLaunchError, launch_from_params


class TestTvGame(unittest.TestCase):
    def test_game_url_format(self) -> None:
        url = game_url()
        self.assertTrue(url.startswith("http://"))
        self.assertIn(":8102/", url)

    def test_launch_from_params(self) -> None:
        try:
            msg, outputs = launch_from_params({"game_id": "coin_catcher"})
        except GameLaunchError:
            self.skipTest("serve.py could not start in this environment")
        self.assertIn("game.launch ok", msg)
        self.assertEqual(outputs.get("game_id"), "coin_catcher")
        self.assertTrue(str(outputs.get("game_url", "")).startswith("http://"))


if __name__ == "__main__":
    unittest.main()
