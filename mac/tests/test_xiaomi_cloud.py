"""Xiaomi cloud helpers: RC4 roundtrip, device picking."""

from __future__ import annotations

import unittest

from mac_edge.plugins.xiaomi_cloud import (
    XiaomiCloudError,
    XiaomiDevice,
    decrypt_rc4,
    encrypt_rc4,
    find_action,
    find_property,
    gen_nonce,
    pick_device,
    signed_nonce,
    spec_short_name,
)


class Rc4Tests(unittest.TestCase):
    def test_encrypt_decrypt_roundtrip(self) -> None:
        nonce = gen_nonce()
        signed = signed_nonce("dGVzdHNlY3VyaXR5MTIzNA==", nonce)
        payload = '{"hello":"米家"}'
        encrypted = encrypt_rc4(signed, payload)
        raw = decrypt_rc4(signed, encrypted)
        self.assertEqual(raw.decode("utf-8"), payload)


class SpecNameTests(unittest.TestCase):
    def test_short_name(self) -> None:
        self.assertEqual(
            spec_short_name("urn:miot-spec-v2:property:water-pump:00000006:miot-v3:1"),
            "water-pump",
        )

    def test_find_property_and_action(self) -> None:
        spec = {
            "services": [
                {
                    "iid": 2,
                    "type": "urn:miot-spec-v2:service:fish-tank:000078A2:x:1",
                    "properties": [
                        {
                            "iid": 1,
                            "type": "urn:miot-spec-v2:property:on:00000006:x:1",
                        }
                    ],
                    "actions": [
                        {
                            "iid": 1,
                            "type": "urn:miot-spec-v2:action:pet-food-out:0000280B:x:1",
                        }
                    ],
                }
            ]
        }
        self.assertEqual(find_property(spec, ("on",)), (2, 1))
        self.assertEqual(find_action(spec, ("pet-food-out",)), (2, 1))


class PickDeviceTests(unittest.TestCase):
    def test_by_did(self) -> None:
        devices = [
            XiaomiDevice(did="1", name="缸", model="miot.fishbowl.v3", online=True),
            XiaomiDevice(did="2", name="锁", model="xiaomi.lock.m30fc", online=True),
        ]
        got = pick_device(devices, did="2", label="读门锁")
        self.assertEqual(got.did, "2")

    def test_by_model_token(self) -> None:
        devices = [
            XiaomiDevice(did="1", name="灯", model="yeelink.light.lamp", online=True),
            XiaomiDevice(did="2", name="缸", model="miot.fishbowl.v3", online=True),
        ]
        got = pick_device(
            devices,
            model_contains=("fishbowl",),
            name_contains=("鱼缸",),
            label="鱼缸控制",
        )
        self.assertEqual(got.did, "2")

    def test_no_match_does_not_fall_back_to_all(self) -> None:
        devices = [
            XiaomiDevice(did="1", name="灯", model="yeelink.light.lamp", online=True),
        ]
        with self.assertRaises(XiaomiCloudError) as ctx:
            pick_device(
                devices,
                model_contains=("fishbowl",),
                name_contains=("鱼缸",),
                label="鱼缸控制",
            )
        self.assertIn("没有匹配", str(ctx.exception))

    def test_multiple_matches_need_did(self) -> None:
        devices = [
            XiaomiDevice(did="1", name="大缸", model="miot.fishbowl.v3", online=True),
            XiaomiDevice(did="2", name="小缸", model="miot.fishbowl.v3", online=True),
        ]
        with self.assertRaises(XiaomiCloudError) as ctx:
            pick_device(devices, model_contains=("fishbowl",), label="鱼缸控制")
        self.assertIn("多台", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
