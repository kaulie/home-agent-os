"""Hisense 爱家 cloud helpers — no live network."""

from __future__ import annotations

import unittest

from mac_edge.plugins.hisense_cloud import (
    HisenseAC,
    HisenseCloudError,
    HisenseHttp,
    HisenseSession,
    parse_status_csv,
    portal_encrypt,
    portal_sign,
)


def status_csv(
    *,
    power: int = 1,
    mode: int = 2,
    temp: int = 26,
    indoor: int = 28,
    fan: int = 0,
    swing: int = 0,
) -> str:
    values = [0] * 210
    values[0] = fan
    values[4] = mode
    values[5] = power
    values[9] = temp
    values[10] = indoor
    values[209] = swing
    return ",".join(str(v) for v in values)


class FakeHttp:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, dict]] = []
        self.login_ok = True
        self.command_result_code = 0
        self.status_payload = status_csv()
        self.refresh_ok = True

    def post(self, url: str, **kwargs):
        self.posts.append((url, kwargs))
        if "signon" in url:
            if not self.login_ok:
                return {"data": {"resultCode": 1}}
            return {
                "data": {
                    "resultCode": 0,
                    "tokenInfo": {"token": "access-1", "refreshToken": "refresh-1"},
                }
            }
        if "refresh_token" in url:
            if not self.refresh_ok:
                return []
            return [{"token": "access-2"}]
        return {
            "response": {
                "resultCode": self.command_result_code,
                "preStatus": self.status_payload,
            }
        }

    def get(self, url: str, **kwargs):
        self.gets.append((url, kwargs))
        if "getHomeList" in url:
            return {
                "response": {
                    "resultCode": 0,
                    "homeList": [{"homeId": "home-1", "homeName": "我家"}],
                }
            }
        return {
            "response": {
                "resultCode": 0,
                "deviceList": [
                    {
                        "deviceId": "ac-1",
                        "wifiId": "wifi-1",
                        "deviceTypeName": "空调",
                        "deviceNickName": "客厅空调",
                        "roomName": "客厅",
                    }
                ],
            }
        }


class PortalCryptoTests(unittest.TestCase):
    def test_encrypt_is_stable(self) -> None:
        self.assertEqual(portal_encrypt("123456"), portal_encrypt("123456"))
        self.assertNotEqual(portal_encrypt("123456"), "123456")

    def test_sign_is_stable(self) -> None:
        body = '{"loginName":"x"}'
        self.assertEqual(portal_sign(body), portal_sign(body))


class StatusParseTests(unittest.TestCase):
    def test_parse_core_fields(self) -> None:
        status = parse_status_csv(status_csv(power=1, mode=2, temp=26, indoor=29))
        self.assertTrue(status["power_on"])
        self.assertEqual(status["mode"], "cool")
        self.assertEqual(status["desired_temperature"], 26)
        self.assertEqual(status["indoor_temperature"], 29)
        self.assertEqual(status["fan"], "auto")
        self.assertEqual(status["swing"], "off")

    def test_parse_fan_and_swing(self) -> None:
        status = parse_status_csv(status_csv(fan=4, swing=2))
        self.assertEqual(status["fan"], "high")
        self.assertEqual(status["fan_mode_id"], 4)
        self.assertEqual(status["swing"], "horizontal")
        self.assertEqual(status["swing_mode_id"], 2)

    def test_unknown_fan_fails(self) -> None:
        with self.assertRaises(HisenseCloudError) as ctx:
            parse_status_csv(status_csv(fan=9))
        self.assertIn("风速", str(ctx.exception))

    def test_short_payload_fails(self) -> None:
        with self.assertRaises(HisenseCloudError):
            parse_status_csv("1,2,3")


class SessionTests(unittest.TestCase):
    def test_login_success(self) -> None:
        http = FakeHttp()
        access, refresh = HisenseSession(http).login("user", "pass")
        self.assertEqual(access, "access-1")
        self.assertEqual(refresh, "refresh-1")
        url, kwargs = http.posts[0]
        self.assertIn("signon", url)
        self.assertIn("X-Sign-For", kwargs["headers"])

    def test_login_failure(self) -> None:
        http = FakeHttp()
        http.login_ok = False
        with self.assertRaises(HisenseCloudError):
            HisenseSession(http).login("user", "bad")

    def test_list_home_and_ac(self) -> None:
        http = FakeHttp()
        session = HisenseSession(http)
        homes = session.list_homes("access-1")
        self.assertEqual(homes[0].home_id, "home-1")
        devices = session.list_ac_devices("access-1", "home-1")
        self.assertEqual(devices[0].device_id, "ac-1")
        self.assertIn("客厅", devices[0].label)


class ACCommandTests(unittest.TestCase):
    def test_turn_on_posts_power_command(self) -> None:
        http = FakeHttp()
        ac = HisenseAC(
            http=http,
            wifi_id="wifi-1",
            device_id="ac-1",
            access_token="access-1",
            refresh_token="refresh-1",
            refresher=HisenseSession(http),
        )
        self.assertTrue(ac.turn_on())
        url, kwargs = http.posts[-1]
        self.assertIn("sendDeviceModelCmd", url)
        self.assertIn("On", kwargs["json_body"]["attributes"])
        self.assertTrue(ac.status["power_on"])

    def test_logic_command_posts_cmd_list(self) -> None:
        http = FakeHttp()
        ac = HisenseAC(
            http=http,
            wifi_id="wifi-1",
            device_id="ac-1",
            access_token="access-1",
            refresh_token="refresh-1",
            refresher=HisenseSession(http),
        )
        self.assertTrue(ac.send_logic_command(6, 26))
        url, kwargs = http.posts[-1]
        self.assertIn("uploadRemoteLogicCmd", url)
        self.assertEqual(kwargs["json_body"]["cmdList"][0]["cmdId"], 6)
        self.assertEqual(kwargs["json_body"]["cmdList"][0]["cmdParm"], 26)

    def test_token_refresh_on_failure(self) -> None:
        http = FakeHttp()
        http.command_result_code = 1
        ac = HisenseAC(
            http=http,
            wifi_id="wifi-1",
            device_id="ac-1",
            access_token="access-1",
            refresh_token="refresh-1",
            refresher=HisenseSession(http),
        )

        def post_once(url, **kwargs):
            if "refresh_token" in url:
                return [{"token": "access-2"}]
            if ac.access_token == "access-2":
                http.command_result_code = 0
                return {
                    "response": {
                        "resultCode": 0,
                        "preStatus": status_csv(),
                    }
                }
            return {"response": {"resultCode": 1}}

        http.post = post_once  # type: ignore[method-assign]
        self.assertTrue(ac.turn_on())
        self.assertEqual(ac.access_token, "access-2")


class HttpTypeGuardTests(unittest.TestCase):
    def test_hisense_http_type(self) -> None:
        self.assertTrue(hasattr(HisenseHttp, "post"))


if __name__ == "__main__":
    unittest.main()
