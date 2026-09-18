"""资源服务器端口发现（mac_edge 侧）：端点文件 → mDNS → 8080，全部过 /health 自校验。

关键点：发现失败时的行为必须与改动前**逐字一致**（硬编码 8080），
所以我们重点测「回退」与「显式配置优先」，而不是「发现成功」。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

MAC_SRC = Path(__file__).resolve().parents[1] / "src"
if str(MAC_SRC) not in sys.path:
    sys.path.insert(0, str(MAC_SRC))

from mac_edge.asset.backends import img_server as im  # noqa: E402


def _reset() -> None:
    im._state.update({"at": 0.0, "port": 0, "checked_at": 0.0})
    im._endpoint_cache.update({"path": "", "mtime": 0.0, "data": None})


class ImgServerDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        keys = ("MAC_EDGE_IMG_SERVER_PORT", "ASSET_HUB_ENDPOINT_FILE", "ASSET_HUB_DISCOVERY_DIR")
        self.prev = {k: os.environ.get(k) for k in keys}
        self.addCleanup(self._restore)
        # monkeypatch 也一并还原：否则会污染同进程里别的测试（踩过一次）
        for name in ("_health_ok", "_lookup_port_via_dns_sd", "detect_lan_ipv4"):
            original = getattr(im, name)
            self.addCleanup(setattr, im, name, original)

    def _restore(self) -> None:
        for k, v in self.prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _endpoint(self, port: int) -> Path:
        path = Path(self.tmp.name) / "home-asset-hub.json"
        path.write_text(
            json.dumps({"service": "home-asset-hub", "port": port, "public_base": f"http://192.168.3.84:{port}"}),
            encoding="utf-8",
        )
        os.environ["ASSET_HUB_ENDPOINT_FILE"] = str(path)
        return path

    def test_parse_dns_sd_lookup_takes_first_token(self) -> None:
        line = "23:37:41.775  Home\\032Agent\\img-server._ha-img-server._tcp.local. can be reached at GaoLeideMacBook-Pro.local.:8080 (interface 5) Flags: 1"
        self.assertEqual(im._parse_dns_sd_lookup(line), 8080)
        self.assertIsNone(im._parse_dns_sd_lookup("DATE: ---Fri 18 Sep 2026---"))

    def test_endpoint_file_used_when_health_ok(self) -> None:
        self._endpoint(18099)
        im._health_ok = lambda port, timeout=0.6: True  # type: ignore[assignment]
        self.assertEqual(im.resolve_img_server_port(), 18099)

    def test_falls_back_to_8080_when_nothing_verifies(self) -> None:
        """旧端点 + health 不通 + mDNS 也没有 → 8080（改动前的行为）。"""
        self._endpoint(18099)
        im._health_ok = lambda port, timeout=0.6: False  # type: ignore[assignment]
        im._lookup_port_via_dns_sd = lambda timeout=1.5: None  # type: ignore[assignment]
        self.assertEqual(im.resolve_img_server_port(), 8080)

    def test_explicit_env_wins(self) -> None:
        self._endpoint(18099)
        im._health_ok = lambda port, timeout=0.6: True  # type: ignore[assignment]
        os.environ["MAC_EDGE_IMG_SERVER_PORT"] = "15000"
        self.assertEqual(im.resolve_img_server_port(), 15000)

    def test_mdns_used_when_no_endpoint_file(self) -> None:
        os.environ["ASSET_HUB_ENDPOINT_FILE"] = str(Path(self.tmp.name) / "nope.json")
        im._lookup_port_via_dns_sd = lambda timeout=1.5: 4242  # type: ignore[assignment]
        im._health_ok = lambda port, timeout=0.6: True  # type: ignore[assignment]
        self.assertEqual(im.resolve_img_server_port(), 4242)

    def test_default_lan_public_base_follows_discovery(self) -> None:
        self._endpoint(18099)
        im._health_ok = lambda port, timeout=0.6: True  # type: ignore[assignment]
        im.detect_lan_ipv4 = lambda: "192.168.3.84"  # type: ignore[assignment]
        self.assertEqual(im.default_lan_public_base(), "http://192.168.3.84:18099")
        # 显式给端口时不被发现覆盖（老调用点语义不变）
        self.assertEqual(im.default_lan_public_base(8080), "http://192.168.3.84:8080")

    def test_upload_endpoints_follow_discovery(self) -> None:
        from mac_edge.asset import img_upload as iu  # noqa: E402

        self._endpoint(18099)
        im._health_ok = lambda port, timeout=0.6: True  # type: ignore[assignment]
        upload, public, probe = iu.upload_endpoints("lan")
        self.assertEqual(upload, "http://127.0.0.1:18099/api/v1/photos/upload")
        self.assertTrue(public.endswith(":18099"))
        self.assertEqual(probe, "http://127.0.0.1:18099/health")


if __name__ == "__main__":
    unittest.main()
