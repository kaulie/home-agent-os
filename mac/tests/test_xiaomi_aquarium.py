"""aquarium.set parses params and drives a mocked MIoT client."""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import patch

from mac_edge.plugins.xiaomi_aquarium import (
    XiaomiAquariumError,
    apply_aquarium,
    map_from_spec,
    parse_aquarium_params,
    set_from_params,
    spec_for_model,
)
from mac_edge.services import default_services


class FakeTank:
    def __init__(self) -> None:
        self.power = True
        self.light = False
        self.pump = True
        self.flux = 5
        self.temp = 26.5
        self.calls: list[tuple[Any, ...]] = []

    def get_properties(self, did: str, props: list[tuple[int, int]]) -> list[dict[str, Any]]:
        self.calls.append(("get", did, tuple(props)))
        table = {
            (2, 1): self.power,
            (3, 1): self.light,
            (2, 2): self.pump,
            (2, 9): self.flux,
            (2, 11): self.temp,
        }
        return [
            {"did": did, "siid": siid, "piid": piid, "code": 0, "value": table[(siid, piid)]}
            for siid, piid in props
            if (siid, piid) in table
        ]

    def set_properties(
        self, did: str, props: list[tuple[int, int, Any]]
    ) -> list[dict[str, Any]]:
        self.calls.append(("set", did, tuple(props)))
        for siid, piid, value in props:
            if (siid, piid) == (2, 1):
                self.power = bool(value)
            if (siid, piid) == (3, 1):
                self.light = bool(value)
            if (siid, piid) == (2, 2):
                self.pump = bool(value)
            if (siid, piid) == (2, 9):
                self.flux = int(value)
        return [{"did": did, "siid": s, "piid": p, "code": 0} for s, p, _ in props]

    def call_action(
        self, did: str, siid: int, aiid: int, ins: list[Any] | None = None
    ) -> Any:
        self.calls.append(("action", did, siid, aiid, tuple(ins or [])))
        return {"code": 0}


class ParseAquariumTests(unittest.TestCase):
    def test_missing_all_fails(self) -> None:
        with self.assertRaises(XiaomiAquariumError) as ctx:
            parse_aquarium_params({})
        self.assertIn("缺少入参", str(ctx.exception))

    def test_aliases(self) -> None:
        self.assertEqual(parse_aquarium_params({"power": "打开"}).power, "on")
        self.assertEqual(parse_aquarium_params({"light": "关"}).light, "off")
        self.assertEqual(parse_aquarium_params({"feed": "喂鱼"}).feed, 1)
        self.assertEqual(parse_aquarium_params({"feed": 3}).feed, 3)
        self.assertEqual(parse_aquarium_params({"pump_flux": "8"}).pump_flux, 8)


class ApplyAquariumTests(unittest.TestCase):
    def test_feed_and_light(self) -> None:
        tank = FakeTank()
        mapping = map_from_spec("did-1", spec_for_model("miot.fishbowl.v3"))
        req = parse_aquarium_params({"light": "on", "feed": 2})
        outputs = apply_aquarium(req, tank, mapping)
        self.assertTrue(tank.light)
        self.assertIn(("action", "did-1", 2, 1, (2,)), tank.calls)
        self.assertEqual(outputs["light"], "on")
        self.assertTrue(outputs["fed"])
        self.assertIn("水温", outputs["status_text"])

    def test_set_from_params_uses_connect_fn(self) -> None:
        tank = FakeTank()
        mapping = map_from_spec("did-1", spec_for_model("miot.fishbowl.v3"))
        msg, outputs = set_from_params(
            {"power": "off"},
            connect_fn=lambda: (tank, mapping),
        )
        self.assertIn("aquarium.set", msg)
        self.assertEqual(outputs["power"], "off")
        self.assertIn("已关", outputs["status_text"])


class AdvertiseAquariumTests(unittest.TestCase):
    def test_laptop_advertises_when_creds_set(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "13800000000",
            "MAC_EDGE_XIAOMI_PASSWORD": "secret",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            services = default_services()
        ids = [s["service_id"] for s in services]
        self.assertIn("livingroom.aquarium", ids)
        self.assertIn("entry.lock", ids)
        aqua = next(s for s in services if s["service_id"] == "livingroom.aquarium")
        caps = [c["capability_id"] for c in aqua["capabilities"]]
        self.assertIn("aquarium.set", caps)
        cap = aqua["capabilities"][0]
        self.assertEqual(cap["role"], "鱼缸控制器")
        self.assertIn("喂鱼", cap["typical_triggers"])

    def test_home_server_never_advertises(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "home-server",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "xuanxuan",
            "MAC_EDGE_XIAOMI_USERNAME": "13800000000",
            "MAC_EDGE_XIAOMI_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            ids = [s["service_id"] for s in default_services()]
        self.assertNotIn("livingroom.aquarium", ids)
        self.assertNotIn("entry.lock", ids)


if __name__ == "__main__":
    unittest.main()
