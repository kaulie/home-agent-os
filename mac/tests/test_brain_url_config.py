"""MAC_EDGE_BRAIN_URL: single URL, JSON {lan, cloud}, and legacy URLS list."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mac_edge.config import (
    colocated_lan_brain_url,
    parse_brain_url_env,
    primary_brain_url,
    _resolve_brain_urls,
)


class ParseBrainUrlTests(unittest.TestCase):
    def test_single_url(self) -> None:
        urls, by_domain = parse_brain_url_env("http://127.0.0.1:9527")
        self.assertEqual(urls, ("http://127.0.0.1:9527",))
        self.assertEqual(by_domain, {})
        self.assertEqual(primary_brain_url("http://127.0.0.1:9527"), "http://127.0.0.1:9527")

    def test_json_object_lan_cloud(self) -> None:
        raw = '{"lan": "http://127.0.0.1:9527", "cloud": "http://115.190.153.53:9527"}'
        urls, by_domain = parse_brain_url_env(raw)
        self.assertEqual(
            urls,
            ("http://127.0.0.1:9527", "http://115.190.153.53:9527"),
        )
        self.assertEqual(
            by_domain,
            {
                "lan": "http://127.0.0.1:9527",
                "cloud": "http://115.190.153.53:9527",
            },
        )
        self.assertEqual(primary_brain_url(raw), "http://127.0.0.1:9527")

    def test_json_cloud_first_still_orders_lan_primary(self) -> None:
        raw = '{"cloud": "http://115.190.153.53:9527", "lan": "http://127.0.0.1:9527"}'
        urls, _ = parse_brain_url_env(raw)
        self.assertEqual(urls[0], "http://127.0.0.1:9527")
        self.assertEqual(urls[1], "http://115.190.153.53:9527")

    def test_json_object_wins_over_legacy_urls_list(self) -> None:
        env = {
            "MAC_EDGE_BRAIN_URL": '{"lan": "http://127.0.0.1:9527", "cloud": "http://115.190.153.53:9527"}',
            "MAC_EDGE_BRAIN_URLS": "http://example.invalid:1,http://example.invalid:2",
        }
        with patch.dict(os.environ, env, clear=False):
            urls, by_domain = _resolve_brain_urls()
        self.assertEqual(urls[0], "http://127.0.0.1:9527")
        self.assertEqual(by_domain["cloud"], "http://115.190.153.53:9527")

    def test_legacy_comma_list_when_single_url(self) -> None:
        env = {
            "MAC_EDGE_BRAIN_URL": "http://127.0.0.1:9527",
            "MAC_EDGE_BRAIN_URLS": "http://127.0.0.1:9527,http://115.190.153.53:9527",
        }
        with patch.dict(os.environ, env, clear=False):
            urls, by_domain = _resolve_brain_urls()
        self.assertEqual(
            urls,
            ("http://127.0.0.1:9527", "http://115.190.153.53:9527"),
        )
        self.assertEqual(by_domain, {})


class ColocatedLanBrainTests(unittest.TestCase):
    def test_brain_local_becomes_loopback(self) -> None:
        self.assertEqual(
            colocated_lan_brain_url("http://brain.local:9527"),
            "http://127.0.0.1:9527",
        )

    def test_keeps_explicit_ipv4(self) -> None:
        self.assertEqual(
            colocated_lan_brain_url("http://192.168.1.20:9527"),
            "http://192.168.1.20:9527",
        )

    def test_keeps_loopback(self) -> None:
        self.assertEqual(
            colocated_lan_brain_url("http://127.0.0.1:9527"),
            "http://127.0.0.1:9527",
        )


if __name__ == "__main__":
    unittest.main()
