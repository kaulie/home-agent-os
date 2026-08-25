"""lock.status is read-only and refuses unlock."""

from __future__ import annotations

import unittest
from typing import Any

from mac_edge.plugins.xiaomi_lock import (
    XiaomiLockError,
    map_from_spec,
    parse_lock_params,
    spec_for_model,
    status_from_client,
    status_from_params,
)


class FakeLock:
    def __init__(self, *, locked: bool = True, door: int = 0) -> None:
        self.locked = locked
        self.door = door

    def get_properties(self, did: str, props: list[tuple[int, int]]) -> list[dict[str, Any]]:
        table = {(2, 1): self.locked, (2, 2): self.door}
        return [
            {"did": did, "siid": siid, "piid": piid, "code": 0, "value": table[(siid, piid)]}
            for siid, piid in props
        ]


class LockStatusTests(unittest.TestCase):
    def test_rejects_unlock(self) -> None:
        with self.assertRaises(XiaomiLockError) as ctx:
            parse_lock_params({"unlock": "开锁"})
        self.assertIn("禁止远程开锁", str(ctx.exception))

    def test_reads_locked_closed(self) -> None:
        mapping = map_from_spec(
            "did-lock",
            spec_for_model("xiaomi.lock.m30fc"),
            online=True,
            name="大门",
        )
        outputs = status_from_client(FakeLock(), mapping)
        self.assertEqual(outputs["locked"], "locked")
        self.assertEqual(outputs["door"], "closed")
        self.assertIn("已上锁", outputs["status_text"])
        self.assertTrue(outputs["online"])

    def test_offline(self) -> None:
        mapping = map_from_spec(
            "did-lock",
            spec_for_model("xiaomi.lock.m30fc"),
            online=False,
            name="大门",
        )
        outputs = status_from_client(FakeLock(), mapping)
        self.assertFalse(outputs["online"])
        self.assertIn("不在线", outputs["status_text"])

    def test_status_from_params(self) -> None:
        mapping = map_from_spec(
            "did-lock",
            spec_for_model("xiaomi.lock.m30fc"),
            online=True,
            name="大门",
        )
        msg, outputs = status_from_params(
            {},
            connect_fn=lambda: (FakeLock(locked=False, door=1), mapping),
        )
        self.assertIn("lock.status", msg)
        self.assertEqual(outputs["locked"], "unlocked")
        self.assertEqual(outputs["door"], "open")


if __name__ == "__main__":
    unittest.main()
