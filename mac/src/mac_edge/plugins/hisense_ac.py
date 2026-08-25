"""Mac Edge capability: climate.set — living-room Hisense AC via 爱家 cloud.

Independent of notify.speak / query.content. This step only sees its own
resolved params. Cloud login and device selection are internal.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from mac_edge.plugins.hisense_cloud import (
    CMD_FAN,
    CMD_HVAC_MODE,
    CMD_SWING,
    CMD_TEMP,
    FAN_AUTO,
    FAN_DIFFUSE,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    HVAC_COOL,
    HVAC_FAN,
    HVAC_HEAT,
    ID_TO_FAN,
    ID_TO_MODE,
    ID_TO_SWING,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_ON,
    SWING_VERTICAL,
    HisenseAC,
    HisenseCloudError,
    HisenseDevice,
    HisenseHttp,
    HisenseSession,
)

log = logging.getLogger("mac_edge.hisense_ac")

TEMP_MIN = 16
TEMP_MAX = 32
POWER_ON_WAIT_SEC = 4.0

MODE_TO_ID = {
    "fan": HVAC_FAN,
    "heat": HVAC_HEAT,
    "cool": HVAC_COOL,
}
FAN_TO_ID = {
    "auto": FAN_AUTO,
    "diffuse": FAN_DIFFUSE,
    "low": FAN_LOW,
    "medium": FAN_MEDIUM,
    "high": FAN_HIGH,
}
SWING_TO_ID = {
    "off": SWING_OFF,
    "on": SWING_ON,
    "horizontal": SWING_HORIZONTAL,
    "vertical": SWING_VERTICAL,
}
MODE_LABELS = {
    "cool": "制冷",
    "heat": "制热",
    "fan": "送风",
    "dry": "除湿",
    "auto": "自动",
}
FAN_LABELS = {
    "auto": "风速自动",
    "diffuse": "柔风",
    "low": "风速低",
    "medium": "风速中",
    "high": "风速高",
}
SWING_LABELS = {
    "off": "扫风关",
    "on": "扫风开",
    "horizontal": "左右扫风",
    "vertical": "上下扫风",
}

_ON_ALIASES = frozenset({"on", "开", "打开", "开机", "开空调", "true", "1"})
_OFF_ALIASES = frozenset({"off", "关", "关闭", "关机", "关空调", "关掉", "false", "0"})
_MODE_ALIASES = {
    "cool": "cool",
    "制冷": "cool",
    "cold": "cool",
    "heat": "heat",
    "制热": "heat",
    "加热": "heat",
    "fan": "fan",
    "送风": "fan",
    "通风": "fan",
    "fan_only": "fan",
}
_FAN_ALIASES = {
    "auto": "auto",
    "自动": "auto",
    "自动风": "auto",
    "diffuse": "diffuse",
    "柔风": "diffuse",
    "散风": "diffuse",
    "low": "low",
    "低": "low",
    "低风": "low",
    "低速": "low",
    "小风": "low",
    "medium": "medium",
    "med": "medium",
    "中": "medium",
    "中风": "medium",
    "中速": "medium",
    "high": "high",
    "高": "high",
    "高风": "high",
    "高速": "high",
    "大风": "high",
}
_SWING_ALIASES = {
    "off": "off",
    "关": "off",
    "关闭": "off",
    "停止": "off",
    "停": "off",
    "关扫风": "off",
    "停止扫风": "off",
    "false": "off",
    "0": "off",
    "on": "on",
    "开": "on",
    "打开": "on",
    "开扫风": "on",
    "扫风": "on",
    "true": "on",
    "1": "on",
    "horizontal": "horizontal",
    "左右": "horizontal",
    "左右扫": "horizontal",
    "左右扫风": "horizontal",
    "水平": "horizontal",
    "vertical": "vertical",
    "上下": "vertical",
    "上下扫": "vertical",
    "上下扫风": "vertical",
    "垂直": "vertical",
}


class HisenseAcError(Exception):
    pass


class ClimateClient(Protocol):
    def turn_on(self) -> bool: ...
    def turn_off(self) -> bool: ...
    def send_logic_command(self, cmd_id: int, param: int) -> bool: ...
    def check_status(self) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ClimateRequest:
    power: str | None
    mode: str | None
    target_temp: int | None
    fan: str | None
    swing: str | None


_cached_cloud_label = ""


def credentials_configured() -> bool:
    user = (os.environ.get("MAC_EDGE_HISENSE_USERNAME") or "").strip()
    password = (os.environ.get("MAC_EDGE_HISENSE_PASSWORD") or "").strip()
    return bool(user and password)


def bound_hisense_devices() -> list[dict[str, str]]:
    """Bound Hisense units: MAC_EDGE_HISENSE_DEVICES JSON, else legacy single DEVICE_ID/LABEL."""
    raw = (os.environ.get("MAC_EDGE_HISENSE_DEVICES") or "").strip()
    devices: list[dict[str, str]] = []
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HisenseAcError(
                "空调控制失败：MAC_EDGE_HISENSE_DEVICES 不是合法 JSON 数组。"
            ) from e
        if not isinstance(parsed, list):
            raise HisenseAcError(
                "空调控制失败：MAC_EDGE_HISENSE_DEVICES 必须是 JSON 数组。"
            )
        for item in parsed:
            if not isinstance(item, dict):
                continue
            device_id = str(
                item.get("device_id") or item.get("deviceId") or ""
            ).strip()
            label = str(item.get("label") or item.get("display_name") or "").strip()
            home_id = str(item.get("home_id") or item.get("homeId") or "").strip()
            if not device_id and not label:
                continue
            devices.append(
                {"device_id": device_id, "label": label, "home_id": home_id}
            )
        return devices
    device_id = (os.environ.get("MAC_EDGE_HISENSE_DEVICE_ID") or "").strip()
    label = (os.environ.get("MAC_EDGE_HISENSE_LABEL") or "").strip()
    home_id = (os.environ.get("MAC_EDGE_HISENSE_HOME_ID") or "").strip()
    if device_id or label:
        return [{"device_id": device_id, "label": label, "home_id": home_id}]
    return []


def bound_appliance_label() -> str:
    """User-facing name for ads: first bound label, else last cloud label."""
    for item in bound_hisense_devices():
        name = str(item.get("label") or "").strip()
        if name:
            return name
    return str(_cached_cloud_label or "").strip()


def _bound_names() -> str:
    names = []
    seen = set()
    for item in bound_hisense_devices():
        name = str(item.get("label") or item.get("device_id") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return "、".join(names)


def resolve_bound_device(params: dict[str, Any] | None) -> dict[str, str]:
    """Pick one bound unit from this step's params. Does not read prior steps."""
    devices = bound_hisense_devices()
    raw = params if isinstance(params, dict) else {}
    appliance = str(
        raw.get("appliance") or raw.get("label") or raw.get("display_name") or ""
    ).strip()
    device_id = str(raw.get("device_id") or raw.get("deviceId") or "").strip()
    if device_id:
        for item in devices:
            if str(item.get("device_id") or "").strip() == device_id:
                return item
        return {"device_id": device_id, "label": appliance, "home_id": ""}
    if appliance:
        for item in devices:
            label = str(item.get("label") or "").strip()
            if not label:
                continue
            if appliance == label or appliance in label or label in appliance:
                return item
        listed = _bound_names() or "（无）"
        raise HisenseAcError(
            f"空调控制失败：未绑定「{appliance}」。已绑定：{listed}。"
        )
    if len(devices) == 1:
        return devices[0]
    if len(devices) > 1:
        listed = _bound_names() or "（未命名）"
        raise HisenseAcError(
            f"空调控制失败：未指定要控制哪台空调。请说名称。已绑定：{listed}。"
        )
    return {"device_id": "", "label": "", "home_id": ""}


def _normalize_power(raw: Any) -> str | None:
    if raw is None:
        return None
    folded = str(raw).strip().lower().replace(" ", "")
    if not folded:
        return None
    if folded in _ON_ALIASES:
        return "on"
    if folded in _OFF_ALIASES:
        return "off"
    raise HisenseAcError(
        f"空调控制失败：无法识别 power「{raw}」。请用 on 或 off。"
    )


def _normalize_mode(raw: Any) -> str | None:
    if raw is None:
        return None
    folded = str(raw).strip().lower().replace(" ", "")
    if not folded:
        return None
    mapped = _MODE_ALIASES.get(folded)
    if mapped is None:
        raise HisenseAcError(
            f"空调控制失败：无法识别 mode「{raw}」。请用 cool、heat 或 fan。"
        )
    return mapped


def _normalize_temp(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise HisenseAcError("空调控制失败：target_temp 必须是摄氏整数。")
    text = str(raw).strip().replace("℃", "").replace("°C", "").replace("度", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as e:
        raise HisenseAcError(
            f"空调控制失败：无法识别 target_temp「{raw}」。请用 16 到 32 的整数。"
        ) from e
    if value != int(value):
        raise HisenseAcError(
            f"空调控制失败：target_temp「{raw}」必须是整数。"
        )
    temp = int(value)
    if temp < TEMP_MIN or temp > TEMP_MAX:
        raise HisenseAcError(
            f"空调控制失败：温度 {temp} 超出范围（{TEMP_MIN}–{TEMP_MAX}）。"
        )
    return temp


def _normalize_fan(raw: Any) -> str | None:
    if raw is None:
        return None
    folded = str(raw).strip().lower().replace(" ", "")
    if not folded:
        return None
    mapped = _FAN_ALIASES.get(folded)
    if mapped is None:
        raise HisenseAcError(
            f"空调控制失败：无法识别 fan「{raw}」。请用 auto、diffuse、low、medium 或 high。"
        )
    return mapped


def _normalize_swing(raw: Any) -> str | None:
    if raw is None:
        return None
    folded = str(raw).strip().lower().replace(" ", "")
    if not folded:
        return None
    mapped = _SWING_ALIASES.get(folded)
    if mapped is None:
        raise HisenseAcError(
            f"空调控制失败：无法识别 swing「{raw}」。请用 off、on、horizontal 或 vertical。"
        )
    return mapped


def parse_climate_params(params: dict[str, Any] | None) -> ClimateRequest:
    raw = params if isinstance(params, dict) else {}
    power = _normalize_power(raw.get("power"))
    mode = _normalize_mode(raw.get("mode"))
    target_temp = _normalize_temp(raw.get("target_temp"))
    fan = _normalize_fan(raw.get("fan"))
    swing = _normalize_swing(raw.get("swing"))
    if (
        power is None
        and mode is None
        and target_temp is None
        and fan is None
        and swing is None
    ):
        raise HisenseAcError(
            "空调控制失败：缺少入参。请至少提供 power、mode、target_temp、fan 或 swing 之一。"
        )
    extras_on_off = (
        mode is not None
        or target_temp is not None
        or fan is not None
        or swing is not None
    )
    if power == "off" and extras_on_off:
        raise HisenseAcError(
            "空调控制失败：关机时不能同时设定模式、温度、风速或扫风。"
        )
    if mode == "fan" and target_temp is not None:
        raise HisenseAcError(
            "空调控制失败：送风模式不能设定温度。"
        )
    return ClimateRequest(
        power=power,
        mode=mode,
        target_temp=target_temp,
        fan=fan,
        swing=swing,
    )


def _pick_home(homes: list, home_id: str) -> Any:
    if not homes:
        raise HisenseAcError("空调控制失败：爱家账号下没有家庭。")
    wanted = home_id.strip()
    if wanted:
        for home in homes:
            if home.home_id == wanted:
                return home
        raise HisenseAcError(
            f"空调控制失败：找不到家庭 {wanted}。"
        )
    if len(homes) == 1:
        return homes[0]
    names = "、".join(f"{h.name}({h.home_id})" for h in homes)
    raise HisenseAcError(
        f"空调控制失败：账号下有多个家庭，请设置 MAC_EDGE_HISENSE_HOME_ID。候选：{names}"
    )


def _pick_device(devices: list[HisenseDevice], device_id: str) -> HisenseDevice:
    if not devices:
        raise HisenseAcError("空调控制失败：这个家庭里没有海信空调。")
    wanted = device_id.strip()
    if wanted:
        for device in devices:
            if device.device_id == wanted:
                return device
        raise HisenseAcError(
            f"空调控制失败：找不到空调 {wanted}。"
        )
    if len(devices) == 1:
        return devices[0]
    names = "、".join(f"{d.label}({d.device_id})" for d in devices)
    raise HisenseAcError(
        f"空调控制失败：有多台空调，请设置 MAC_EDGE_HISENSE_DEVICE_ID。候选：{names}"
    )


def connect_ac(
    device_id: str = "",
    home_id: str = "",
) -> HisenseAC:
    username = (os.environ.get("MAC_EDGE_HISENSE_USERNAME") or "").strip()
    password = (os.environ.get("MAC_EDGE_HISENSE_PASSWORD") or "").strip()
    if not username or not password:
        raise HisenseAcError(
            "空调控制失败：未配置 MAC_EDGE_HISENSE_USERNAME / MAC_EDGE_HISENSE_PASSWORD。"
        )
    home_id = str(home_id or "").strip() or (
        os.environ.get("MAC_EDGE_HISENSE_HOME_ID") or ""
    ).strip()
    device_id = str(device_id or "").strip() or (
        os.environ.get("MAC_EDGE_HISENSE_DEVICE_ID") or ""
    ).strip()
    global _cached_cloud_label
    http = HisenseHttp()
    session = HisenseSession(http)
    try:
        access, refresh = session.login(username, password)
        home = _pick_home(session.list_homes(access), home_id)
        device = _pick_device(session.list_ac_devices(access, home.home_id), device_id)
    except HisenseCloudError as e:
        raise HisenseAcError(str(e)) from e
    _cached_cloud_label = str(device.label or "").strip()
    log.info(
        "hisense connect home=%s device=%s label=%s",
        home.home_id,
        device.device_id,
        device.label,
    )
    return HisenseAC(
        http=http,
        wifi_id=device.wifi_id,
        device_id=device.device_id,
        access_token=access,
        refresh_token=refresh,
        refresher=session,
    )


def _mode_from_id(hvac_mode_id: Any) -> str:
    if isinstance(hvac_mode_id, int) and hvac_mode_id in ID_TO_MODE:
        return ID_TO_MODE[hvac_mode_id]
    return "auto"


def _fan_from_status(status: dict[str, Any]) -> str | None:
    named = status.get("fan")
    if isinstance(named, str) and named in FAN_TO_ID:
        return named
    fan_id = status.get("fan_mode_id")
    if isinstance(fan_id, int) and fan_id in ID_TO_FAN:
        return ID_TO_FAN[fan_id]
    return None


def _swing_from_status(status: dict[str, Any]) -> str | None:
    named = status.get("swing")
    if isinstance(named, str) and named in SWING_TO_ID:
        return named
    swing_id = status.get("swing_mode_id")
    if isinstance(swing_id, int) and swing_id in ID_TO_SWING:
        return ID_TO_SWING[swing_id]
    return None


def _status_text(
    *,
    power: str,
    mode: str,
    target_temp: int | None,
    fan: str | None,
    swing: str | None,
) -> str:
    if power == "off":
        return "空调已关"
    parts = ["空调已开"]
    mode_label = MODE_LABELS.get(mode, mode)
    if target_temp is not None and mode != "fan":
        parts.append(f"{mode_label} {target_temp}°C")
    else:
        parts.append(mode_label)
    if fan in FAN_LABELS:
        parts.append(FAN_LABELS[fan])
    if swing in SWING_LABELS:
        parts.append(SWING_LABELS[swing])
    return "，".join(parts)


def outputs_from_status(
    status: dict[str, Any],
    req: ClimateRequest | None = None,
) -> dict[str, Any]:
    """Announce the command we successfully sent. Cloud readback lags; do not TTS it."""
    power = "on" if status.get("power_on") else "off"
    mode = str(status.get("mode") or _mode_from_id(status.get("hvac_mode_id")) or "")
    fan = _fan_from_status(status)
    swing = _swing_from_status(status)
    target = status.get("desired_temperature")
    indoor = status.get("indoor_temperature")
    target_int = int(target) if isinstance(target, (int, float)) else None
    indoor_int = int(indoor) if isinstance(indoor, (int, float)) else None
    if req is not None:
        if req.power in ("on", "off"):
            power = req.power
        elif (
            req.mode is not None
            or req.target_temp is not None
            or req.fan is not None
            or req.swing is not None
        ):
            power = "on"
        if req.mode:
            mode = req.mode
        if req.target_temp is not None:
            target_int = req.target_temp
        if req.fan:
            fan = req.fan
        if req.swing:
            swing = req.swing
    if power == "off" or mode == "fan":
        shown_temp = None
    else:
        shown_temp = target_int
    out: dict[str, Any] = {
        "power": power,
        "mode": mode or "auto",
        "status_text": _status_text(
            power=power,
            mode=mode or "auto",
            target_temp=shown_temp,
            fan=fan,
            swing=swing,
        ),
    }
    if target_int is not None:
        out["target_temp"] = target_int
    if indoor_int is not None:
        out["indoor_temp"] = indoor_int
    if fan is not None:
        out["fan"] = fan
    if swing is not None:
        out["swing"] = swing
    return out


def apply_climate(
    req: ClimateRequest,
    ac: ClimateClient,
    *,
    sleep_fn: Callable[[float], None] | None = None,
    power_on_wait_sec: float = POWER_ON_WAIT_SEC,
) -> dict[str, Any]:
    sleeper = sleep_fn or time.sleep
    if req.power == "off":
        if not ac.turn_off():
            raise HisenseAcError("空调关闭失败：海信云端拒绝关机。")
        status = ac.check_status() or {}
        return outputs_from_status(status, req)

    status = ac.check_status()
    if status is None:
        raise HisenseAcError("空调控制失败：无法读取当前状态。")
    was_on = bool(status.get("power_on"))
    need_logic = (
        req.mode is not None
        or req.target_temp is not None
        or req.fan is not None
        or req.swing is not None
    )
    need_on = req.power == "on" or need_logic
    turned_on = False
    if need_on and not was_on:
        if not ac.turn_on():
            raise HisenseAcError("空调开启失败：海信云端拒绝开机。")
        turned_on = True

    if need_logic:
        if turned_on:
            sleeper(power_on_wait_sec)
        if req.mode is not None:
            if not ac.send_logic_command(CMD_HVAC_MODE, MODE_TO_ID[req.mode]):
                raise HisenseAcError("空调改模式失败：海信云端拒绝。")
        if req.target_temp is not None:
            if not ac.send_logic_command(CMD_TEMP, req.target_temp):
                raise HisenseAcError("空调设温失败：海信云端拒绝。")
        if req.fan is not None:
            if not ac.send_logic_command(CMD_FAN, FAN_TO_ID[req.fan]):
                raise HisenseAcError("空调改风速失败：海信云端拒绝。")
        if req.swing is not None:
            if not ac.send_logic_command(CMD_SWING, SWING_TO_ID[req.swing]):
                raise HisenseAcError("空调改扫风失败：海信云端拒绝。")

    final = ac.check_status() or {}
    return outputs_from_status(final, req)


def set_from_params(
    params: dict[str, Any] | None = None,
    *,
    connect_fn: Callable[[], ClimateClient] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> tuple[str, dict[str, Any]]:
    req = parse_climate_params(params)
    target = resolve_bound_device(params)
    if connect_fn is not None:
        connector = connect_fn
    else:
        wanted_id = str(target.get("device_id") or "").strip()
        wanted_home = str(target.get("home_id") or "").strip()

        def connector() -> ClimateClient:
            return connect_ac(device_id=wanted_id, home_id=wanted_home)
    ac: ClimateClient | None = None
    try:
        ac = connector()
        outputs = apply_climate(req, ac, sleep_fn=sleep_fn)
    except HisenseAcError:
        raise
    except HisenseCloudError as e:
        raise HisenseAcError(str(e)) from e
    finally:
        closer = getattr(getattr(ac, "http", None), "close", None)
        if callable(closer):
            closer()
    msg = f"climate.set {outputs['status_text']}"
    log.info("climate.set %s", outputs)
    return msg, outputs
