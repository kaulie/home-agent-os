"""资源服务器端口发现：端点文件 → mDNS → 已验证缓存 → 8080（每一层都过 /health 自校验）。

为什么专门测这块：端口从「四处硬编码 8080」改成「服务自己决定 + 消费方发现」之后，
**回退路径必须比发现路径更可靠** —— 发现失败时行为要跟改动前完全一致（8080）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import mdns_service as m  # noqa: E402


def _reset_state() -> None:
    m._img_server_state.update({"at": 0.0, "port": 0, "checked_at": 0.0})
    m._endpoint_cache.update({"path": "", "mtime": 0.0, "data": None})


class DiscoveryParsersTest(unittest.TestCase):
    def test_parse_dns_sd_lookup_line(self) -> None:
        line = (
            "23:37:41.775  Home\\032Agent\\032img-server._ha-img-server._tcp.local. "
            "can be reached at GaoLeideMacBook-Pro.local.:8080 (interface 5) Flags: 1"
        )
        got = m._parse_dns_sd_lookup(line)
        self.assertIsNotNone(got)
        self.assertEqual(got["host"], "GaoLeideMacBook-Pro.local")  # 末尾点要去掉
        self.assertEqual(got["port"], 8080)

    def test_parse_dns_sd_lookup_rejects_junk(self) -> None:
        for junk in ["Lookup Home Agent img-server._ha-img-server._tcp.local", "DATE: ---Fri---", ""]:
            self.assertIsNone(m._parse_dns_sd_lookup(junk))

    def test_parse_dns_sd_browse_line(self) -> None:
        # 真实 `dns-sd -B` 列：时间戳 A/R Flags if 域 服务类型 实例名（含空格，在最后）
        line = "23:38:02.456  Add        2   5  local.               _ha-img-server._tcp.  Home Agent img-server"
        self.assertEqual(m._parse_dns_sd_browse_line(line, "_ha-img-server._tcp"), "Home Agent img-server")
        # 表头 / Rmv / 无关行都不该被当成实例
        for junk in [
            "Timestamp     A/R  Flags  if Domain               Service Type         Instance Name",
            "DATE: ---Fri 18 Sep 2026---",
            "23:38:01.123  ...STARTING...",
            "23:39:00.001  Rmv        2   5  local.               _ha-img-server._tcp.  Home Agent img-server",
        ]:
            self.assertIsNone(m._parse_dns_sd_browse_line(junk, "_ha-img-server._tcp"))


class EndpointFileTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prev_env = {k: os.environ.get(k) for k in ("ASSET_HUB_ENDPOINT_FILE", "ASSET_HUB_DISCOVERY_DIR")}
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        for k, v in self.prev_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _write_endpoint(self, port: int, **extra: object) -> Path:
        path = Path(self.tmp.name) / "home-asset-hub.json"
        payload = {
            "service": "home-asset-hub",
            "port": port,
            "host": "0.0.0.0",
            "public_base": f"http://192.168.3.84:{port}",
            "health_path": "/health",
        }
        payload.update(extra)
        path.write_text(json.dumps(payload), encoding="utf-8")
        os.environ["ASSET_HUB_ENDPOINT_FILE"] = str(path)
        return path

    def test_endpoint_file_is_first_layer_and_verified(self) -> None:
        self._write_endpoint(18099)
        self.assertEqual(m.read_img_server_endpoint()["port"], 18099)
        m._img_server_health_ok = lambda port, timeout=0.6: True  # type: ignore[assignment]
        _reset_state()
        self.assertEqual(m.resolve_img_server_port(), 18099)
        self.assertEqual(m._img_server_state["source"], "endpoint-file")

    def test_endpoint_file_that_fails_health_is_ignored(self) -> None:
        """服务挂了/端点是旧的 → 必须回退到默认 8080（= 改动前的行为）。"""
        self._write_endpoint(18099)
        m._img_server_health_ok = lambda port, timeout=0.6: False  # type: ignore[assignment]
        m._lookup_known_instance = lambda timeout=2.0: None  # type: ignore[assignment]
        _reset_state()
        self.assertEqual(m.resolve_img_server_port(), 8080)

    def test_mdns_is_second_layer(self) -> None:
        os.environ["ASSET_HUB_ENDPOINT_FILE"] = str(Path(self.tmp.name) / "missing.json")
        m._lookup_known_instance = lambda timeout=2.0: {"port": 4242, "host": "mac.local", "txt": {}}  # type: ignore[assignment]
        m._img_server_health_ok = lambda port, timeout=0.6: True  # type: ignore[assignment]
        _reset_state()
        self.assertEqual(m.resolve_img_server_port(), 4242)
        self.assertEqual(m._img_server_state["source"], "mdns")

    def test_negative_cache_stops_repeat_probing(self) -> None:
        """发现失败后短时间内不再去问 Bonjour（否则每次上传都白等 2-5s）。"""
        os.environ["ASSET_HUB_ENDPOINT_FILE"] = str(Path(self.tmp.name) / "missing.json")
        calls = {"n": 0}

        def _fake_discover(timeout: float = 2.0):
            calls["n"] += 1
            return None

        m._lookup_known_instance = lambda timeout=2.0: None  # type: ignore[assignment]
        m.discover_img_server = _fake_discover  # type: ignore[assignment]
        _reset_state()
        self.assertEqual(m.resolve_img_server_port(blocking=True), 8080)
        self.assertEqual(m.resolve_img_server_port(blocking=True), 8080)
        self.assertEqual(calls["n"], 1, "第二次不该再探一次")

    def test_env_wins_in_brain(self) -> None:
        """显式 env 永远优先（配置 > 发现）。"""
        self._write_endpoint(18099)
        m._img_server_health_ok = lambda port, timeout=0.6: True  # type: ignore[assignment]
        _reset_state()
        os.environ["BRAIN_IMG_UPLOAD_URL"] = "http://127.0.0.1:9999/api/v1/photos/upload"
        self.addCleanup(lambda: os.environ.pop("BRAIN_IMG_UPLOAD_URL", None))
        import home_brain as hb  # noqa: E402

        self.assertEqual(hb._img_server_upload_url(), "http://127.0.0.1:9999/api/v1/photos/upload")
        self.assertEqual(hb._img_server_internal_base(), "http://127.0.0.1:9999")


if __name__ == "__main__":
    unittest.main()

