"""Hisense Connect / 爱家 cloud client (sync httpx).

Protocol aligned with the MIT project HisenseHA (Jiaxin, 2024):
https://github.com/manymuch/HisenseHA

Not a Home Assistant integration. No background polling.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

log = logging.getLogger("mac_edge.hisense_cloud")

PORTAL_LOGIN_URL = "https://portal-account.hismarttv.com/mobile/se/signon"
HOME_LIST_URL = "https://api-wg.hismarttv.com/wg/dm/getHomeList"
DEVICE_LIST_URL = "https://api-wg.hismarttv.com/wg/dm/getHomeDeviceList"
OUTER_HEAD = "https://api-wg.hismarttv.com/agw/dsg/outer"
POWER_PATH = "/sendDeviceModelCmd?accessToken="
COMMAND_PATH = "/uploadRemoteLogicCmd?accessToken="
STATUS_PATH = "/getDeviceLogicalStatusArray?accessToken="
REFRESH_URL = "https://bas-wg.hismarttv.com/aaa/refresh_token2"

_PORTAL_APP_KEY = "commonweb"
_PORTAL_APP_SECRET = "MORZRbkuiWxjp+SM4vR_GxY4pZxLZ6rn"
_PORTAL_AES_IV = _PORTAL_APP_SECRET[:16].encode("ascii")

_APP_UA = "%E6%B5%B7%E4%BF%A1%E6%99%BA%E6%85%A7%E5%AE%B6/4 CFNetwork/1492.0.1 Darwin/23.3.0"

CMD_FAN = 1
CMD_HVAC_MODE = 3
CMD_TEMP = 6
CMD_SWING = 62

HVAC_FAN = 0
HVAC_HEAT = 1
HVAC_COOL = 2
HVAC_DRY = 3
HVAC_AUTO = 4

FAN_AUTO = 0
FAN_DIFFUSE = 1
FAN_LOW = 2
FAN_MEDIUM = 3
FAN_HIGH = 4

SWING_OFF = 0
SWING_ON = 1
SWING_HORIZONTAL = 2
SWING_VERTICAL = 3

ID_TO_MODE = {
    HVAC_FAN: "fan",
    HVAC_HEAT: "heat",
    HVAC_COOL: "cool",
    HVAC_DRY: "dry",
    HVAC_AUTO: "auto",
}

ID_TO_FAN = {
    FAN_AUTO: "auto",
    FAN_DIFFUSE: "diffuse",
    FAN_LOW: "low",
    FAN_MEDIUM: "medium",
    FAN_HIGH: "high",
}

ID_TO_SWING = {
    SWING_OFF: "off",
    SWING_ON: "on",
    SWING_HORIZONTAL: "horizontal",
    SWING_VERTICAL: "vertical",
}

_STATUS_FAN_MODES = set(ID_TO_FAN)
_STATUS_SWING_MODES = set(ID_TO_SWING)
_MIN_STATUS_VALUES = 210
_DEFAULT_TIMEOUT = 20.0


class HisenseCloudError(Exception):
    pass


def portal_encrypt(value: str) -> str:
    """AES-CBC encrypt a portal login field the way the account web client does."""
    raw = value.encode("utf-8")
    padding = 16 - (len(raw) % 16)
    padded = raw + bytes([padding]) * padding
    cipher = Cipher(
        algorithms.AES(_PORTAL_APP_SECRET.encode("ascii")),
        modes.CBC(_PORTAL_AES_IV),
    )
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("ascii")


def portal_sign(body: str) -> str:
    digest = hashlib.md5(
        (body + _PORTAL_APP_SECRET).encode("utf-8"), usedforsecurity=False
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


def _json_body(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _device_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def device_label(device: dict[str, Any], device_id: str) -> str:
    room = _device_text(device.get("roomName"))
    nick = _device_text(device.get("deviceNickName"))
    if room and nick:
        return f"{room}-{nick}"
    if room:
        return room
    if nick:
        return nick
    name = _device_text(device.get("deviceName"))
    return name or device_id


def parse_status_csv(payload: str) -> dict[str, Any]:
    values = [int(part.strip()) for part in payload.split(",")]
    if len(values) < _MIN_STATUS_VALUES:
        raise HisenseCloudError(
            f"空调状态解析失败：云端返回 {len(values)} 项，期望至少 {_MIN_STATUS_VALUES} 项。"
        )
    fan_mode_id = values[0]
    hvac_mode_id = values[4]
    swing_mode_id = values[209]
    if hvac_mode_id not in ID_TO_MODE:
        raise HisenseCloudError(f"空调状态解析失败：未知模式 id {hvac_mode_id}。")
    if fan_mode_id not in _STATUS_FAN_MODES:
        raise HisenseCloudError(f"空调状态解析失败：未知风速 id {fan_mode_id}。")
    if swing_mode_id not in _STATUS_SWING_MODES:
        raise HisenseCloudError(f"空调状态解析失败：未知扫风 id {swing_mode_id}。")
    return {
        "power_on": values[5] == 1,
        "hvac_mode_id": hvac_mode_id,
        "mode": ID_TO_MODE[hvac_mode_id],
        "desired_temperature": values[9],
        "indoor_temperature": values[10],
        "fan_mode_id": fan_mode_id,
        "fan": ID_TO_FAN[fan_mode_id],
        "swing_mode_id": swing_mode_id,
        "swing": ID_TO_SWING[swing_mode_id],
    }


def _extract_status_payload(result: dict[str, Any]) -> str:
    response = result.get("response")
    if not isinstance(response, dict):
        raise HisenseCloudError("空调云端响应缺少 response。")
    pre_status = response.get("preStatus")
    if isinstance(pre_status, str) and pre_status:
        return pre_status
    status_list = response.get("deviceStatusList")
    if isinstance(status_list, list) and status_list:
        first = status_list[0]
        if isinstance(first, dict):
            device_status = first.get("deviceStatus")
            if isinstance(device_status, str) and device_status:
                return device_status
    raise HisenseCloudError("空调云端响应缺少状态字段。")


@dataclass(frozen=True)
class HisenseHome:
    home_id: str
    name: str


@dataclass(frozen=True)
class HisenseDevice:
    device_id: str
    wifi_id: str
    label: str


class HisenseHttp:
    """Thin wrapper so tests can inject a fake transport."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owned = client is None
        self._client = client or httpx.Client(timeout=_DEFAULT_TIMEOUT)

    def close(self) -> None:
        if self._owned:
            self._client.close()

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
    ) -> Any:
        try:
            resp = self._client.post(
                url,
                headers=headers,
                params=params,
                content=content,
                json=json_body,
                data=data,
            )
            resp.raise_for_status()
            return resp.json()
        except HisenseCloudError:
            raise
        except Exception as e:
            raise HisenseCloudError(f"海信云端请求失败：{e}") from e

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        try:
            resp = self._client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()
        except HisenseCloudError:
            raise
        except Exception as e:
            raise HisenseCloudError(f"海信云端请求失败：{e}") from e


class HisenseSession:
    def __init__(self, http: HisenseHttp | None = None) -> None:
        self.http = http or HisenseHttp()

    def login(self, username: str, password: str) -> tuple[str, str]:
        data = {
            "loginName": portal_encrypt(username),
            "signature": portal_encrypt(password),
            "serverCode": "9501",
            "distributeId": "2001",
            "termType": 2,
        }
        body = _json_body(data)
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "appKey": _PORTAL_APP_KEY,
            "X-Sign-For": portal_sign(body),
        }
        params = {
            "lastUpdateTime": "0",
            "version": "1.0",
            "deviceType": "2",
            "appType": "100",
            "versionCode": "101",
            "adaptertRank": "720",
            "_": str(_timestamp_ms()),
        }
        result = self.http.post(
            PORTAL_LOGIN_URL,
            headers=headers,
            params=params,
            content=body.encode("utf-8"),
        )
        payload = result.get("data") if isinstance(result, dict) else None
        if not isinstance(payload, dict) or payload.get("resultCode") != 0:
            raise HisenseCloudError("海信爱家登录失败：用户名或密码不对。")
        token_info = payload.get("tokenInfo") or {}
        access = token_info.get("token")
        refresh = token_info.get("refreshToken")
        if not access or not refresh:
            raise HisenseCloudError("海信爱家登录失败：响应里没有 token。")
        return str(access), str(refresh)

    def list_homes(self, access_token: str) -> list[HisenseHome]:
        params = {
            "sign": "",
            "languageId": "0",
            "version": "8.0",
            "accessToken": access_token,
            "timezone": "28800",
            "format": "1",
            "timeStamp": str(_timestamp_ms()),
        }
        result = self.http.get(HOME_LIST_URL, params=params)
        response = result.get("response") if isinstance(result, dict) else None
        if not isinstance(response, dict) or response.get("resultCode") != 0:
            raise HisenseCloudError("海信爱家列出家庭失败。")
        homes: list[HisenseHome] = []
        for item in response.get("homeList") or []:
            if not isinstance(item, dict):
                continue
            hid = str(item.get("homeId") or "").strip()
            if not hid:
                continue
            name = str(item.get("homeName") or "").strip() or hid
            homes.append(HisenseHome(home_id=hid, name=name))
        return homes

    def list_ac_devices(self, access_token: str, home_id: str) -> list[HisenseDevice]:
        params = {
            "sign": "",
            "languageId": "0",
            "version": "8.0",
            "accessToken": access_token,
            "homeId": home_id,
            "timezone": "28800",
            "format": "1",
            "timeStamp": str(_timestamp_ms()),
        }
        result = self.http.get(DEVICE_LIST_URL, params=params)
        response = result.get("response") if isinstance(result, dict) else None
        if not isinstance(response, dict) or response.get("resultCode") != 0:
            raise HisenseCloudError("海信爱家列出设备失败。")
        devices: list[HisenseDevice] = []
        for item in response.get("deviceList") or []:
            if not isinstance(item, dict):
                continue
            type_name = item.get("deviceTypeName")
            if not isinstance(type_name, str) or "空调" not in type_name:
                continue
            did = str(item.get("deviceId") or "").strip()
            wifi_id = str(item.get("wifiId") or "").strip()
            if not did or not wifi_id:
                continue
            devices.append(
                HisenseDevice(
                    device_id=did,
                    wifi_id=wifi_id,
                    label=device_label(item, did),
                )
            )
        return devices

    def refresh_access_token(self, refresh_token: str) -> str:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": _APP_UA,
            "Accept": "*/*",
        }
        data = {
            "refreshToken": refresh_token,
            "appKey": "1234567890",
            "format": "1",
        }
        result = self.http.post(REFRESH_URL, headers=headers, data=data)
        if not isinstance(result, list) or not result:
            raise HisenseCloudError("海信爱家刷新 token 失败。")
        first = result[0]
        token = first.get("token") if isinstance(first, dict) else None
        if not token:
            raise HisenseCloudError("海信爱家刷新 token 失败：响应里没有 token。")
        return str(token)


class HisenseAC:
    def __init__(
        self,
        *,
        http: HisenseHttp,
        wifi_id: str,
        device_id: str,
        access_token: str,
        refresh_token: str,
        refresher: HisenseSession | None = None,
    ) -> None:
        self.http = http
        self.wifi_id = wifi_id
        self.device_id = device_id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._refresher = refresher or HisenseSession(http)
        self.status: dict[str, Any] = {"power_on": False}
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "User-Agent": _APP_UA,
        }

    def _power_url(self) -> str:
        return f"{OUTER_HEAD}{POWER_PATH}{self.access_token}"

    def _command_url(self) -> str:
        return f"{OUTER_HEAD}{COMMAND_PATH}{self.access_token}"

    def _status_url(self) -> str:
        return f"{OUTER_HEAD}{STATUS_PATH}{self.access_token}"

    def _power_body(self) -> dict[str, Any]:
        return {
            "wifiId": self.wifi_id,
            "deviceId": self.device_id,
            "extendParam": "1",
            "cmdVersion": "0",
        }

    def _command_body(self) -> dict[str, Any]:
        return {
            "wifiId": self.wifi_id,
            "deviceId": self.device_id,
            "extendParm": "1",
            "cmdVersion": "1684085201",
        }

    def _status_body(self) -> dict[str, Any]:
        return {
            "deviceList": [
                {"wifiId": self.wifi_id, "deviceId": self.device_id},
            ]
        }

    def _post_command(
        self, url: str, body: dict[str, Any], *, status_required: bool
    ) -> bool | None:
        result = self.http.post(url, headers=self._headers, json_body=body)
        if not isinstance(result, dict):
            return False
        response = result.get("response")
        if not isinstance(response, dict) or response.get("resultCode") != 0:
            return False
        if not status_required:
            try:
                self.status.update(parse_status_csv(_extract_status_payload(result)))
                return True
            except HisenseCloudError:
                return None
        try:
            self.status.update(parse_status_csv(_extract_status_payload(result)))
            return True
        except HisenseCloudError:
            return False

    def _with_refresh(
        self, url_fn, body: dict[str, Any], *, status_required: bool
    ) -> bool | None:
        outcome = self._post_command(url_fn(), body, status_required=status_required)
        if outcome is not False:
            return outcome
        log.info("hisense token expired; refreshing")
        try:
            self.access_token = self._refresher.refresh_access_token(self.refresh_token)
        except HisenseCloudError as e:
            raise HisenseCloudError(f"海信爱家 token 刷新失败（{e}）") from e
        return self._post_command(url_fn(), body, status_required=status_required)

    def _send_and_refresh_status(self, url_fn, body: dict[str, Any]) -> bool:
        outcome = self._with_refresh(url_fn, body, status_required=False)
        if outcome is True:
            return True
        if outcome is None:
            return self.check_status() is not None
        return False

    def turn_on(self) -> bool:
        body = self._power_body()
        body["attributes"] = '{"onAndOff":"On"}'
        return self._send_and_refresh_status(self._power_url, body)

    def turn_off(self) -> bool:
        body = self._power_body()
        body["attributes"] = '{"onAndOff":"Off"}'
        return self._send_and_refresh_status(self._power_url, body)

    def send_logic_command(self, cmd_id: int, param: int) -> bool:
        body = self._command_body()
        body["cmdList"] = [
            {"cmdId": cmd_id, "cmdOrder": 0, "cmdParm": param, "delayTime": 0}
        ]
        return self._send_and_refresh_status(self._command_url, body)

    def check_status(self) -> dict[str, Any] | None:
        outcome = self._with_refresh(
            self._status_url, self._status_body(), status_required=True
        )
        if outcome is True:
            return dict(self.status)
        return None
