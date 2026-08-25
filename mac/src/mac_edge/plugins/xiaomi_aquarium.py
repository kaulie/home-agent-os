"""Mac Edge capability: aquarium.set — 米家智能鱼缸 via Xiaomi cloud.

Independent of notify.speak / query.content. This step only sees its own
resolved params. Cloud login and device selection are internal.
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
    find_action,
    find_property,
    pick_device,
)

log = logging.getLogger("mac_edge.xiaomi_aquarium")

# miot.fishbowl.v3 / 米家智能鱼缸 fallback when spec fetch is unavailable.
_FISHBOWL_SPEC: dict[str, Any] = {
    "services": [
        {
            "iid": 2,
            "type": "urn:miot-spec-v2:service:fish-tank:000078A2:miot-v3:1",
            "properties": [
                {"iid": 1, "type": "urn:miot-spec-v2:property:on:00000006:miot-v3:1"},
                {
                    "iid": 2,
                    "type": "urn:miot-spec-v2:property:water-pump:00000006:miot-v3:1",
                },
                {
                    "iid": 6,
                    "type": "urn:miot-spec-v2:property:automatic-feeding:00000006:miot-v3:1",
                },
                {
                    "iid": 7,
                    "type": "urn:miot-spec-v2:property:target-feeding-measure:00000006:miot-v3:1",
                },
                {
                    "iid": 9,
                    "type": "urn:miot-spec-v2:property:pump-flux:00000006:miot-v3:1",
                },
                {
                    "iid": 11,
                    "type": "urn:miot-spec-v2:property:temperature:00000006:miot-v3:1",
                },
            ],
            "actions": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:action:pet-food-out:0000280B:miot-v3:1",
                }
            ],
        },
        {
            "iid": 3,
            "type": "urn:miot-spec-v2:service:light:0000780A:miot-v3:1",
            "properties": [
                {"iid": 1, "type": "urn:miot-spec-v2:property:on:00000006:miot-v3:1"},
            ],
            "actions": [],
        },
    ]
}

_ON_ALIASES = frozenset({"on", "开", "打开", "开机", "true", "1"})
_OFF_ALIASES = frozenset({"off", "关", "关闭", "关机", "关掉", "false", "0"})


class XiaomiAquariumError(Exception):
    pass


class AquariumClient(Protocol):
    def get_properties(
        self, did: str, props: list[tuple[int, int]]
    ) -> list[dict[str, Any]]: ...

    def set_properties(
        self, did: str, props: list[tuple[int, int, Any]]
    ) -> list[dict[str, Any]]: ...

    def call_action(
        self,
        did: str,
        siid: int,
        aiid: int,
        ins: list[Any] | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class AquariumRequest:
    power: str | None
    light: str | None
    pump: str | None
    pump_flux: int | None
    feed: int | None


@dataclass(frozen=True)
class AquariumMap:
    did: str
    spec: dict[str, Any]
    power: tuple[int, int] | None
    light: tuple[int, int] | None
    pump: tuple[int, int] | None
    pump_flux: tuple[int, int] | None
    temperature: tuple[int, int] | None
    feed_action: tuple[int, int] | None
    feed_measure: tuple[int, int] | None


def credentials_configured() -> bool:
    return xiaomi_credentials_configured()


def _normalize_switch(raw: Any, field: str) -> str | None:
    if raw is None:
        return None
    folded = str(raw).strip().lower().replace(" ", "")
    if not folded:
        return None
    if folded in _ON_ALIASES:
        return "on"
    if folded in _OFF_ALIASES:
        return "off"
    raise XiaomiAquariumError(
        f"鱼缸控制失败：无法识别 {field}「{raw}」。请用 on 或 off。"
    )


def _normalize_flux(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise XiaomiAquariumError("鱼缸控制失败：pump_flux 必须是 1 到 10 的整数。")
    text = str(raw).strip()
    try:
        value = int(float(text))
    except ValueError as e:
        raise XiaomiAquariumError(
            f"鱼缸控制失败：无法识别 pump_flux「{raw}」。请用 1 到 10。"
        ) from e
    if value < 1 or value > 10:
        raise XiaomiAquariumError(
            f"鱼缸控制失败：水泵流量 {value} 超出范围（1–10）。"
        )
    return value


def _normalize_feed(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return 1 if raw else None
    folded = str(raw).strip().lower().replace(" ", "")
    if folded in {"true", "1", "喂", "喂食", "喂鱼", "feed"}:
        return 1
    if folded in {"false", "0"}:
        return None
    try:
        value = int(float(folded.replace("份", "")))
    except ValueError as e:
        raise XiaomiAquariumError(
            f"鱼缸控制失败：无法识别 feed「{raw}」。请用 true 或 1 到 10。"
        ) from e
    if value < 1 or value > 10:
        raise XiaomiAquariumError(
            f"鱼缸控制失败：出粮量 {value} 超出范围（1–10）。"
        )
    return value


def parse_aquarium_params(params: dict[str, Any] | None) -> AquariumRequest:
    raw = params if isinstance(params, dict) else {}
    power = _normalize_switch(raw.get("power"), "power")
    light = _normalize_switch(raw.get("light"), "light")
    pump = _normalize_switch(raw.get("pump"), "pump")
    pump_flux = _normalize_flux(raw.get("pump_flux"))
    feed = _normalize_feed(raw.get("feed"))
    if (
        power is None
        and light is None
        and pump is None
        and pump_flux is None
        and feed is None
    ):
        raise XiaomiAquariumError(
            "鱼缸控制失败：缺少入参。请至少提供 power、light、pump、pump_flux 或 feed 之一。"
        )
    return AquariumRequest(
        power=power,
        light=light,
        pump=pump,
        pump_flux=pump_flux,
        feed=feed,
    )


def spec_for_model(model: str) -> dict[str, Any]:
    _ = model
    return _FISHBOWL_SPEC


def map_from_spec(did: str, spec: dict[str, Any]) -> AquariumMap:
    tank = ("fish-tank", "fishbowl")
    return AquariumMap(
        did=did,
        spec=spec,
        power=find_property(spec, ("on",), service_names=tank)
        or find_property(spec, ("on",)),
        light=find_property(spec, ("on",), service_names=("light",)),
        pump=find_property(spec, ("water-pump", "pump")),
        pump_flux=find_property(spec, ("pump-flux",)),
        temperature=find_property(spec, ("temperature",)),
        feed_action=find_action(spec, ("pet-food-out", "food-out")),
        feed_measure=find_property(spec, ("target-feeding-measure", "feeding-measure")),
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


def _as_on(value: Any) -> str | None:
    if value is True or value == 1 or value == "on":
        return "on"
    if value is False or value == 0 or value == "off":
        return "off"
    return None


def _status_text(outputs: dict[str, Any]) -> str:
    parts: list[str] = []
    power = outputs.get("power")
    if power == "off":
        return "鱼缸已关"
    if power == "on":
        parts.append("鱼缸已开")
    light = outputs.get("light")
    if light == "on":
        parts.append("灯开")
    elif light == "off":
        parts.append("灯关")
    pump = outputs.get("pump")
    if pump == "on":
        flux = outputs.get("pump_flux")
        if isinstance(flux, int):
            parts.append(f"水泵开 流量{flux}")
        else:
            parts.append("水泵开")
    elif pump == "off":
        parts.append("水泵关")
    temp = outputs.get("water_temp")
    if isinstance(temp, (int, float)):
        parts.append(f"水温{temp:g}°C")
    fed = outputs.get("fed")
    if fed is True:
        parts.append("已喂食")
    return "，".join(parts) or "鱼缸状态已读取"


def outputs_from_props(
    rows: list[dict[str, Any]],
    mapping: AquariumMap,
    *,
    fed: bool = False,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    power = _as_on(_prop_value(rows, mapping.power))
    if power is not None:
        out["power"] = power
    light = _as_on(_prop_value(rows, mapping.light))
    if light is not None:
        out["light"] = light
    pump = _as_on(_prop_value(rows, mapping.pump))
    if pump is not None:
        out["pump"] = pump
    flux = _prop_value(rows, mapping.pump_flux)
    if isinstance(flux, (int, float)):
        out["pump_flux"] = int(flux)
    temp = _prop_value(rows, mapping.temperature)
    if isinstance(temp, (int, float)):
        out["water_temp"] = float(temp) if isinstance(temp, float) else int(temp)
    if fed:
        out["fed"] = True
    out["status_text"] = _status_text(out)
    return out


def _read_pairs(mapping: AquariumMap) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for item in (
        mapping.power,
        mapping.light,
        mapping.pump,
        mapping.pump_flux,
        mapping.temperature,
    ):
        if item is not None:
            pairs.append(item)
    return pairs


def apply_aquarium(
    req: AquariumRequest,
    client: AquariumClient,
    mapping: AquariumMap,
) -> dict[str, Any]:
    sets: list[tuple[int, int, Any]] = []
    if req.power is not None:
        if mapping.power is None:
            raise XiaomiAquariumError("鱼缸控制失败：这台鱼缸没有总开关。")
        sets.append((*mapping.power, req.power == "on"))
    if req.light is not None:
        if mapping.light is None:
            raise XiaomiAquariumError("鱼缸控制失败：这台鱼缸没有灯光开关。")
        sets.append((*mapping.light, req.light == "on"))
    if req.pump is not None:
        if mapping.pump is None:
            raise XiaomiAquariumError("鱼缸控制失败：这台鱼缸没有水泵开关。")
        sets.append((*mapping.pump, req.pump == "on"))
    if req.pump_flux is not None:
        if mapping.pump_flux is None:
            raise XiaomiAquariumError("鱼缸控制失败：这台鱼缸不能调水泵流量。")
        sets.append((*mapping.pump_flux, req.pump_flux))
    fed = False
    if sets:
        results = client.set_properties(mapping.did, sets)
        for row in results:
            if row.get("code") not in (0, "0", None):
                raise XiaomiAquariumError(
                    f"鱼缸控制失败：米家拒绝写入（code={row.get('code')}）。"
                )
    if req.feed is not None:
        if mapping.feed_action is None:
            raise XiaomiAquariumError("鱼缸控制失败：这台鱼缸没有喂食动作。")
        client.call_action(
            mapping.did,
            mapping.feed_action[0],
            mapping.feed_action[1],
            [req.feed],
        )
        fed = True
    rows = client.get_properties(mapping.did, _read_pairs(mapping))
    if not rows:
        raise XiaomiAquariumError("鱼缸指令已发出，但无法读取当前状态。")
    return outputs_from_props(rows, mapping, fed=fed)


def _connect_mapping(
    cloud: XiaomiCloud,
) -> AquariumMap:
    devices = cloud.list_devices()
    did = (os.environ.get("MAC_EDGE_XIAOMI_AQUARIUM_DID") or "").strip()
    device = pick_device(
        devices,
        did=did,
        name_contains=("鱼缸",),
        model_contains=("fishbowl", "fish-tank", "fishtank"),
        label="鱼缸控制",
    )
    mapping = map_from_spec(device.did, spec_for_model(device.model))
    log.info(
        "xiaomi aquarium connect did=%s name=%s model=%s",
        device.did,
        device.name,
        device.model,
    )
    return mapping


def set_from_params(
    params: dict[str, Any] | None = None,
    *,
    connect_fn: Callable[[], tuple[AquariumClient, AquariumMap]] | None = None,
) -> tuple[str, dict[str, Any]]:
    req = parse_aquarium_params(params)
    if connect_fn is not None:
        client, mapping = connect_fn()
        outputs = apply_aquarium(req, client, mapping)
    else:
        try:
            cloud = connect_cloud()
            mapping = _connect_mapping(cloud)
            outputs = apply_aquarium(req, cloud, mapping)
        except XiaomiAquariumError:
            raise
        except XiaomiCloudError as e:
            raise XiaomiAquariumError(str(e)) from e
    if "status_text" not in outputs:
        raise XiaomiAquariumError("鱼缸控制失败：没有可读状态。")
    msg = f"aquarium.set {outputs['status_text']}"
    log.info("aquarium.set %s", outputs)
    return msg, outputs
