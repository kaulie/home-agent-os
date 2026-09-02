"""Unit tests for the shared mDNS publish/discover module (server/mdns_service.py).

Runs with the mac venv (python-zeroconf installed) so the publish→discover
round-trip is a real localhost integration test.

The module is loaded by file path (importlib) so this test never mutates
sys.path and can run alongside the other `tests.test_*` modules.
"""

from __future__ import annotations

import importlib.util
import socket
import time
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "home_agent_mdns_service", _REPO / "server" / "mdns_service.py"
)
assert _SPEC is not None and _SPEC.loader is not None
mdns_service = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mdns_service)


class MdnsWellKnownTests(unittest.TestCase):
    def test_well_known_types_present(self) -> None:
        # Labels <= 15 bytes per RFC 6763 §7.1.
        for type_ in (
            mdns_service.BRAIN_TYPE,
            mdns_service.GATEWAY_TYPE,
            mdns_service.RUNTIME_TYPE,
            mdns_service.IMG_SERVER_TYPE,
        ):
            label = type_.split(".")[0].lstrip("_")
            self.assertLessEqual(len(label), 15, type_)
        self.assertEqual(mdns_service.BRAIN_TYPE, "_ha-brain._tcp")
        self.assertEqual(mdns_service.GATEWAY_TYPE, "_ha-gateway._tcp")
        self.assertEqual(mdns_service.RUNTIME_TYPE, "_ha-runtime._tcp")
        self.assertEqual(mdns_service.IMG_SERVER_TYPE, "_ha-img-server._tcp")

    def test_lan_ipv4_non_empty(self) -> None:
        self.assertTrue(mdns_service.lan_ipv4())

    def test_fq_type_normalizes(self) -> None:
        self.assertEqual(
            mdns_service._fq_type("_home-agent-brain._tcp"),
            "_home-agent-brain._tcp.local.",
        )
        self.assertEqual(
            mdns_service._fq_type("_home-agent-brain._tcp.local."),
            "_home-agent-brain._tcp.local.",
        )


class MdnsPublishDiscoverTests(unittest.TestCase):
    TYPE = "_ha-test._tcp"

    def test_roundtrip_publish_and_discover(self) -> None:
        if not mdns_service.HAS_ZEROCONF:
            self.skipTest("python-zeroconf not installed")
        # pick a free-ish UDP-ish port for the test service
        with socket.socket() as probe:
            probe.bind(("0.0.0.0", 0))
            port = probe.getsockname()[1]
        pub = mdns_service.publish_service(
            name="Unit Test Svc",
            type_=self.TYPE,
            port=port,
            txt={"hello": "world"},
            hostname="test.local",
        )
        try:
            found = mdns_service.discover_service(self.TYPE, timeout=4)
            self.assertTrue(found, "discover found nothing after publish")
            match = next((s for s in found if s["port"] == port), None)
            self.assertIsNotNone(match, f"service not discovered: {found}")
            self.assertEqual(match["port"], port)
            self.assertEqual(match["txt"].get("hello"), "world")
            self.assertEqual(match["host"], mdns_service.lan_ipv4())
        finally:
            pub.close()

    def test_discover_empty_for_unknown_type(self) -> None:
        start = time.time()
        found = mdns_service.discover_service("_home-agent-nope-xyz._tcp", timeout=1)
        self.assertEqual(found, [])
        self.assertLess(time.time() - start, 6)

    @mock.patch.object(mdns_service, "HAS_ZEROCONF", False)
    def test_dns_sd_backend_spawns_dns_sd(self) -> None:
        with mock.patch.object(
            mdns_service.subprocess, "Popen", return_value=mock.Mock()
        ) as popen:
            pub = mdns_service.MdnsPublisher()
            try:
                pub.publish(
                    name="Unit Test Svc",
                    type_=self.TYPE,
                    port=19999,
                    txt={"k": "v"},
                )
            finally:
                pub.close()
        self.assertTrue(popen.called)
        args = popen.call_args.args[0]
        self.assertEqual(args[:4], ["dns-sd", "-R", "Unit Test Svc", self.TYPE])
        self.assertIn("19999", args)
        self.assertIn("k=v", args)


if __name__ == "__main__":
    unittest.main()
