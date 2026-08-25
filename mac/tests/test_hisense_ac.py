"""climate.set parses params locally and drives a mocked Hisense AC client."""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import patch

from mac_edge.plugins.hisense_ac import (
    POWER_ON_WAIT_SEC,
    HisenseAcError,
    apply_climate,
    connect_ac,
    parse_climate_params,
    set_from_params,
)
from mac_edge.plugins.hisense_cloud import CMD_FAN, CMD_HVAC_MODE, CMD_SWING, CMD_TEMP
from mac_edge.services import default_services


class FakeAC:
    def __init__(
        self,
        *,
        power_on: bool = False,
        mode: str = "cool",
        hvac_mode_id: int = 2,
        target: int = 26,
        indoor: int = 28,
        fan: str = "auto",
        fan_mode_id: int = 0,
        swing: str = "off",
        swing_mode_id: int = 0,
    ) -> None:
        self.power_on = power_on
        self.mode = mode
        self.hvac_mode_id = hvac_mode_id
        self.target = target
        self.indoor = indoor
        self.fan = fan
        self.fan_mode_id = fan_mode_id
        self.swing = swing
        self.swing_mode_id = swing_mode_id
        self.calls: list[tuple[Any, ...]] = []

    def turn_on(self) -> bool:
        self.calls.append(("turn_on",))
        self.power_on = True
        return True

    def turn_off(self) -> bool:
        self.calls.append(("turn_off",))
        self.power_on = False
        return True

    def send_logic_command(self, cmd_id: int, param: int) -> bool:
        self.calls.append(("logic", cmd_id, param))
        if cmd_id == CMD_HVAC_MODE:
            self.hvac_mode_id = param
            self.mode = {0: "fan", 1: "heat", 2: "cool"}.get(param, "auto")
        if cmd_id == CMD_TEMP:
            self.target = param
        if cmd_id == CMD_FAN:
            self.fan_mode_id = param
            self.fan = {0: "auto", 1: "diffuse", 2: "low", 3: "medium", 4: "high"}.get(
                param, "auto"
            )
        if cmd_id == CMD_SWING:
            self.swing_mode_id = param
            self.swing = {
                0: "off",
                1: "on",
                2: "horizontal",
                3: "vertical",
            }.get(param, "off")
        return True

    def check_status(self) -> dict[str, Any]:
        self.calls.append(("check_status",))
        return {
            "power_on": self.power_on,
            "mode": self.mode,
            "hvac_mode_id": self.hvac_mode_id,
            "desired_temperature": self.target,
            "indoor_temperature": self.indoor,
            "fan": self.fan,
            "fan_mode_id": self.fan_mode_id,
            "swing": self.swing,
            "swing_mode_id": self.swing_mode_id,
        }


class ParseParamsTests(unittest.TestCase):
    def test_missing_all_fails(self) -> None:
        with self.assertRaises(HisenseAcError) as ctx:
            parse_climate_params({})
        self.assertIn("缺少入参", str(ctx.exception))

    def test_power_aliases(self) -> None:
        self.assertEqual(parse_climate_params({"power": "打开"}).power, "on")
        self.assertEqual(parse_climate_params({"power": "关掉"}).power, "off")
        self.assertEqual(parse_climate_params({"power": "关"}).power, "off")

    def test_mode_aliases(self) -> None:
        self.assertEqual(parse_climate_params({"mode": "制冷"}).mode, "cool")
        self.assertEqual(parse_climate_params({"mode": "制热"}).mode, "heat")
        self.assertEqual(parse_climate_params({"mode": "送风"}).mode, "fan")

    def test_temp_strips_unit(self) -> None:
        self.assertEqual(parse_climate_params({"target_temp": "26度"}).target_temp, 26)
        self.assertEqual(parse_climate_params({"target_temp": 26}).target_temp, 26)

    def test_fan_aliases(self) -> None:
        self.assertEqual(parse_climate_params({"fan": "高"}).fan, "high")
        self.assertEqual(parse_climate_params({"fan": "柔风"}).fan, "diffuse")
        self.assertEqual(parse_climate_params({"fan": "自动"}).fan, "auto")

    def test_swing_aliases(self) -> None:
        self.assertEqual(parse_climate_params({"swing": "左右扫风"}).swing, "horizontal")
        self.assertEqual(parse_climate_params({"swing": "上下"}).swing, "vertical")
        self.assertEqual(parse_climate_params({"swing": "关扫风"}).swing, "off")

    def test_off_with_temp_fails(self) -> None:
        with self.assertRaises(HisenseAcError) as ctx:
            parse_climate_params({"power": "off", "target_temp": 26})
        self.assertIn("关机", str(ctx.exception))

    def test_off_with_fan_fails(self) -> None:
        with self.assertRaises(HisenseAcError) as ctx:
            parse_climate_params({"power": "off", "fan": "high"})
        self.assertIn("关机", str(ctx.exception))

    def test_fan_with_temp_fails(self) -> None:
        with self.assertRaises(HisenseAcError) as ctx:
            parse_climate_params({"mode": "fan", "target_temp": 26})
        self.assertIn("送风", str(ctx.exception))

    def test_temp_out_of_range_fails(self) -> None:
        with self.assertRaises(HisenseAcError):
            parse_climate_params({"target_temp": 10})
        with self.assertRaises(HisenseAcError):
            parse_climate_params({"target_temp": 33})

    def test_missing_params_does_not_connect(self) -> None:
        def boom() -> FakeAC:
            raise AssertionError("must not connect")

        with self.assertRaises(HisenseAcError):
            set_from_params({}, connect_fn=boom)


class ApplyClimateTests(unittest.TestCase):
    def test_off_only_turns_off(self) -> None:
        ac = FakeAC(power_on=True)
        slept: list[float] = []
        outputs = apply_climate(
            parse_climate_params({"power": "off"}),
            ac,
            sleep_fn=slept.append,
        )
        self.assertEqual(outputs["power"], "off")
        self.assertEqual(outputs["status_text"], "空调已关")
        self.assertEqual(ac.calls[0], ("turn_off",))
        self.assertEqual(slept, [])

    def test_fan_when_off_turns_on_then_sets_fan(self) -> None:
        ac = FakeAC(power_on=False)
        slept: list[float] = []
        outputs = apply_climate(
            parse_climate_params({"fan": "高"}),
            ac,
            sleep_fn=slept.append,
        )
        self.assertEqual(slept, [POWER_ON_WAIT_SEC])
        self.assertIn(("turn_on",), ac.calls)
        self.assertIn(("logic", CMD_FAN, 4), ac.calls)
        self.assertEqual(outputs["fan"], "high")
        self.assertIn("风速高", outputs["status_text"])

    def test_swing_when_already_on(self) -> None:
        ac = FakeAC(power_on=True)
        slept: list[float] = []
        outputs = apply_climate(
            parse_climate_params({"swing": "左右扫风"}),
            ac,
            sleep_fn=slept.append,
        )
        self.assertEqual(slept, [])
        self.assertNotIn(("turn_on",), ac.calls)
        self.assertIn(("logic", CMD_SWING, 2), ac.calls)
        self.assertEqual(outputs["swing"], "horizontal")
        self.assertIn("左右扫风", outputs["status_text"])

    def test_set_temp_when_off_turns_on_then_waits(self) -> None:
        ac = FakeAC(power_on=False)
        slept: list[float] = []
        outputs = apply_climate(
            parse_climate_params({"target_temp": 26}),
            ac,
            sleep_fn=slept.append,
        )
        self.assertEqual(slept, [POWER_ON_WAIT_SEC])
        self.assertIn(("turn_on",), ac.calls)
        self.assertIn(("logic", CMD_TEMP, 26), ac.calls)
        self.assertEqual(outputs["power"], "on")
        self.assertEqual(outputs["target_temp"], 26)
        self.assertIn("26°C", outputs["status_text"])

    def test_mode_and_temp_when_already_on_no_wait(self) -> None:
        ac = FakeAC(power_on=True)
        slept: list[float] = []
        apply_climate(
            parse_climate_params({"mode": "cool", "target_temp": 24}),
            ac,
            sleep_fn=slept.append,
        )
        self.assertEqual(slept, [])
        self.assertNotIn(("turn_on",), ac.calls)
        self.assertIn(("logic", CMD_HVAC_MODE, 2), ac.calls)
        self.assertIn(("logic", CMD_TEMP, 24), ac.calls)

    def test_power_on_announces_on_even_if_cloud_lags(self) -> None:
        ac = FakeAC(power_on=False)
        slept: list[float] = []

        def accept_on_keep_cloud_off() -> bool:
            ac.calls.append(("turn_on",))
            return True

        ac.turn_on = accept_on_keep_cloud_off  # type: ignore[method-assign]
        outputs = apply_climate(
            parse_climate_params({"power": "on"}),
            ac,
            sleep_fn=slept.append,
        )
        self.assertEqual(slept, [])
        self.assertEqual(outputs["power"], "on")
        self.assertTrue(str(outputs["status_text"]).startswith("空调已开"))

    def test_power_off_announces_off_even_if_cloud_lags(self) -> None:
        ac = FakeAC(power_on=True)

        def accept_off_keep_cloud_on() -> bool:
            ac.calls.append(("turn_off",))
            return True

        ac.turn_off = accept_off_keep_cloud_on  # type: ignore[method-assign]
        outputs = apply_climate(
            parse_climate_params({"power": "off"}),
            ac,
            sleep_fn=lambda _: None,
        )
        self.assertEqual(outputs["power"], "off")
        self.assertEqual(outputs["status_text"], "空调已关")

    def test_set_from_params_uses_connect_fn(self) -> None:
        ac = FakeAC(power_on=False)
        msg, outputs = set_from_params(
            {"power": "on"},
            connect_fn=lambda: ac,
            sleep_fn=lambda _: None,
        )
        self.assertIn("climate.set", msg)
        self.assertEqual(outputs["power"], "on")
        self.assertIn(("turn_on",), ac.calls)


class ServiceAdvertiseClimateTests(unittest.TestCase):
    def test_laptop_advertises_climate_when_creds_set(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "13800000000",
            "MAC_EDGE_HISENSE_PASSWORD": "secret",
            "MAC_EDGE_HISENSE_LABEL": "客厅空调",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV": "",
        }
        with patch.dict(os.environ, env, clear=False):
            services = default_services()
        ids = [s["service_id"] for s in services]
        self.assertIn("climate.living_room", ids)
        climate = next(s for s in services if s["service_id"] == "climate.living_room")
        self.assertEqual(climate["display_name"], "客厅空调")
        caps = [c["capability_id"] for c in climate["capabilities"]]
        self.assertIn("climate.set", caps)
        cap = climate["capabilities"][0]
        self.assertEqual(cap["role"], "客厅空调控制器")
        self.assertEqual(cap["typical_triggers"][0], "打开客厅空调")
        self.assertIn("关掉客厅空调", cap["typical_triggers"])
        self.assertIn("风速高", cap["typical_triggers"])
        self.assertIn("新风", cap["do_not_dispatch"])
        self.assertNotIn("风速/扫风/新风", cap["do_not_dispatch"])

    def test_home_server_never_advertises_climate_even_with_creds(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "home-server",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "xuanxuan",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "13800000000",
            "MAC_EDGE_HISENSE_PASSWORD": "secret",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV": "",
        }
        with patch.dict(os.environ, env, clear=False):
            ids = [s["service_id"] for s in default_services()]
        self.assertNotIn("livingroom.climate", ids)
        self.assertNotIn("climate.living_room", ids)
        self.assertNotIn("climate.kids_room", ids)

    def test_two_bound_labels_advertise_two_climate_services(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "13800000000",
            "MAC_EDGE_HISENSE_PASSWORD": "secret",
            "MAC_EDGE_HISENSE_DEVICES": (
                '[{"device_id":"dev-living","label":"客厅空调"},'
                '{"device_id":"dev-kids","label":"儿童房空调"}]'
            ),
            "MAC_EDGE_HISENSE_DEVICE_ID": "",
            "MAC_EDGE_HISENSE_LABEL": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV": "",
        }
        with patch.dict(os.environ, env, clear=False):
            services = default_services()
        climate = [s for s in services if s.get("group") == "climate"]
        ids = [s["service_id"] for s in climate]
        self.assertEqual(ids.count("climate.living_room"), 1)
        self.assertEqual(ids.count("climate.kids_room"), 1)
        living = next(s for s in climate if s["service_id"] == "climate.living_room")
        kids = next(s for s in climate if s["service_id"] == "climate.kids_room")
        self.assertEqual(living["display_name"], "客厅空调")
        self.assertEqual(kids["display_name"], "儿童房空调")
        self.assertEqual(living["capabilities"][0]["typical_triggers"][0], "打开客厅空调")
        self.assertEqual(kids["capabilities"][0]["typical_triggers"][0], "打开儿童房空调")
        self.assertIn("appliance", living["capabilities"][0]["input_schema"])

    def test_plugin_routes_appliance_to_bound_device_id(self) -> None:
        env = {
            "MAC_EDGE_HISENSE_USERNAME": "13800000000",
            "MAC_EDGE_HISENSE_PASSWORD": "secret",
            "MAC_EDGE_HISENSE_DEVICES": (
                '[{"device_id":"dev-living","label":"客厅空调"},'
                '{"device_id":"dev-kids","label":"儿童房空调"}]'
            ),
        }
        seen: list[str] = []
        living_ac = FakeAC(power_on=False)
        kids_ac = FakeAC(power_on=True)

        def fake_connect(device_id: str = "", home_id: str = "") -> FakeAC:
            seen.append(device_id)
            if device_id == "dev-kids":
                return kids_ac
            return living_ac

        with patch.dict(os.environ, env, clear=False):
            with patch(
                "mac_edge.plugins.hisense_ac.connect_ac",
                side_effect=fake_connect,
            ):
                set_from_params(
                    {"power": "off", "appliance": "儿童房空调"},
                    sleep_fn=lambda _: None,
                )
                with self.assertRaises(HisenseAcError) as ctx:
                    set_from_params({"power": "on"}, sleep_fn=lambda _: None)
        self.assertEqual(seen, ["dev-kids"])
        self.assertIn(("turn_off",), kids_ac.calls)
        self.assertIn("客厅空调", str(ctx.exception))
        self.assertIn("儿童房空调", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
