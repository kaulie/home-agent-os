"""Mac Edge capability: lock.status — 小米门锁 M30 只读状态 via Xiaomi cloud.

Never unlocks. Independent of other capabilities. This step only sees its
own resolved params (none required).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from mac_edge.plugins.xiaomi_cloud import (
    XiaomiCloud,
    XiaomiCloudError,
    connect_cloud,
    credentials_configured as xiaomi_credentials_configured,
    find_property,
    pick_device,
)

log = logging.getLogger("mac_edge.xiaomi_lock")

_LOCK_SPEC: dict[str, Any] = {
    "services": [
        {
            "iid": 2,
            "type": "urn:miot-spec-v2:service:lock:0000780F:xiaomi:1",
            "properties": [
                {"iid": 1, "type": "urn:miot-spec-v2:property:lock:00000006:xiaomi:1"},
                {
                    "iid": 2,
                    "type": "urn:miot-spec-v2:property:door-state:00000006:xiaomi:1",
                },
            ],
            "actions": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:action:unlock:00002801:xiaomi:1",
                }
            ],
        }
    ]
}

_DOOR_LABELS = {
    0: "closed",
    1: "open",
    2: "ajar",
    3: "unknown",
}


class XiaomiLockError(Exception):
    pass


class LockClient(Protocol):
    def get_properties(
        self, did: str, props: list[tuple[int, int]]
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class LockMap:
    did: str
    online: bool
    name: str
    lock: tuple[int, int] | None
    door_state: tuple[int, int] | None


def credentials_configured() -> bool:
    return xiaomi_credentials_configured()


def spec_for_model(model: str) -> dict[str, Any]:
    _ = model
    return _LOCK_SPEC


def map_from_spec(
    did: str,
    spec: dict[str, Any],
    *,
    online: bool,
    name: str,
) -> LockMap:
    return LockMap(
        did=did,
        online=online,
        name=name,
        lock=find_property(spec, ("lock", "locked")),
        door_state=find_property(spec, ("door-state", "door_state")),
    )


def _prop_value(rows: list[dict[str, Any]], pair: tuple[int, int] | None) -> Any:
    if pair is None:
        return None
    siid, piid = pair
    for row in rows:
        if row.get("siid") == siid and row.get("piid") == piid:
            if row.get("code") not in (0, "0", None):
                return None
            return row.get("value")
    return None


def _locked_from(value: Any) -> str | None:
    if value is True or value == 1 or value in ("locked", "lock"):
        return "locked"
    if value is False or value == 0 or value in ("unlocked", "unlock"):
        return "unlocked"
    return None


def _door_from(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        folded = value.strip().lower()
        if folded in {"open", "opened", "开", "打开"}:
            return "open"
        if folded in {"closed", "close", "关", "关闭"}:
            return "closed"
        if folded in {"ajar", "虚掩"}:
            return "ajar"
    if isinstance(value, (int, float)):
        return _DOOR_LABELS.get(int(value), "unknown")
    return None


def _status_text(outputs: dict[str, Any]) -> str:
    if outputs.get("online") is False:
        return "门锁不在线（需要蓝牙网关或门锁 Wi-Fi）"
    locked = outputs.get("locked")
    door = outputs.get("door")
    parts: list[str] = []
    if locked == "locked":
        parts.append("已上锁")
    elif locked == "unlocked":
        parts.append("未上锁")
    if door == "open":
        parts.append("门开着")
    elif door == "closed":
        parts.append("门关着")
    elif door == "ajar":
        parts.append("门虚掩")
    if not parts:
        return "已读到门锁，但没有锁状态或门状态"
    return "，".join(parts)


def outputs_from_props(
    rows: list[dict[str, Any]],
    mapping: LockMap,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "online": mapping.online,
        "device_name": mapping.name,
    }
    locked = _locked_from(_prop_value(rows, mapping.lock))
    if locked is not None:
        out["locked"] = locked
    door = _door_from(_prop_value(rows, mapping.door_state))
    if door is not None:
        out["door"] = door
    out["status_text"] = _status_text(out)
    return out


def status_from_client(client: LockClient, mapping: LockMap) -> dict[str, Any]:
    pairs = [item for item in (mapping.lock, mapping.door_state) if item is not None]
    if not mapping.online:
        return outputs_from_props([], mapping)
    if not pairs:
        raise XiaomiLockError("读门锁失败：这台锁没有可读的锁状态属性。")
    rows = client.get_properties(mapping.did, pairs)
    return outputs_from_props(rows, mapping)


def _connect_mapping(cloud: XiaomiCloud) -> LockMap:
    devices = cloud.list_devices()
    did = (os.environ.get("MAC_EDGE_XIAOMI_LOCK_DID") or "").strip()
    device = pick_device(
        devices,
        did=did,
        name_contains=("门锁",),
        model_contains=("lock.", ".lock.", "lock-"),
        label="读门锁",
    )
    mapping = map_from_spec(
        device.did,
        spec_for_model(device.model),
        online=device.online,
        name=device.name,
    )
    log.info(
        "xiaomi lock connect did=%s name=%s model=%s online=%s",
        device.did,
        device.name,
        device.model,
        device.online,
    )
    return mapping


def parse_lock_params(params: dict[str, Any] | None) -> None:
    raw = params if isinstance(params, dict) else {}
    for key in ("unlock", "lock", "action", "command"):
        value = raw.get(key)
        if value is None or value == "":
            continue
        folded = str(value).strip().lower().replace(" ", "")
        if folded in {"unlock", "open", "开", "开锁", "开门", "远程开锁"}:
            raise XiaomiLockError("读门锁失败：禁止远程开锁。")
        if folded in {"lock", "close", "关", "上锁"}:
            raise XiaomiLockError("读门锁失败：本能力只读状态，不能上锁。")


def status_from_params(
    params: dict[str, Any] | None = None,
    *,
    connect_fn: Callable[[], tuple[LockClient, LockMap]] | None = None,
) -> tuple[str, dict[str, Any]]:
    parse_lock_params(params)
    if connect_fn is not None:
        client, mapping = connect_fn()
        outputs = status_from_client(client, mapping)
    else:
        try:
            cloud = connect_cloud()
            mapping = _connect_mapping(cloud)
            outputs = status_from_client(cloud, mapping)
        except XiaomiLockError:
            raise
        except XiaomiCloudError as e:
            raise XiaomiLockError(str(e)) from e
    msg = f"lock.status {outputs['status_text']}"
    log.info("lock.status %s", outputs)
    return msg, outputs
