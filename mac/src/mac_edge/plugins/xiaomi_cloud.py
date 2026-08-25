"""Xiaomi / 米家 cloud client (sync httpx).

Login + signed MIoT prop/action calls. Protocol matches community
micloud / python-miio (account.xiaomi.com + api.io.mi.com RC4).

Not a Home Assistant integration. No background polling.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import struct
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

log = logging.getLogger("mac_edge.xiaomi_cloud")

_JSON_PREFIX = "&&&START&&&"
_UA = (
    "Android-7.1.1-1.0.0-ONEPLUS A3010-136-ABCDEFABCDEF A "
    "APP/xiaomi.smarthome APPV/62830"
)
_DEFAULT_TIMEOUT = 20.0
_API_SID = "xiaomiio"


class XiaomiCloudError(Exception):
    pass


def credentials_configured() -> bool:
    user = (os.environ.get("MAC_EDGE_XIAOMI_USERNAME") or "").strip()
    password = (os.environ.get("MAC_EDGE_XIAOMI_PASSWORD") or "").strip()
    return bool(user and password)


def country_code() -> str:
    raw = (os.environ.get("MAC_EDGE_XIAOMI_COUNTRY") or "cn").strip().lower()
    return raw or "cn"


def api_base(country: str | None = None) -> str:
    code = (country or country_code()).strip().lower() or "cn"
    if code == "cn":
        return "https://api.io.mi.com/app"
    return f"https://{code}.api.io.mi.com/app"


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray(len(data))
    for n, byte in enumerate(data):
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out[n] = byte ^ s[(s[i] + s[j]) % 256]
    return bytes(out)


def gen_nonce() -> str:
    millis = int(time.time() * 1000)
    packed = os.urandom(8) + struct.pack(">I", int(millis / 60000) & 0xFFFFFFFF)
    return base64.b64encode(packed).decode("ascii")


def signed_nonce(ssecurity: str, nonce: str) -> str:
    digest = hashlib.sha256(
        base64.b64decode(ssecurity) + base64.b64decode(nonce)
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def encrypt_rc4(password_b64: str, payload: str) -> str:
    key = base64.b64decode(password_b64)
    dropped = _rc4(key, bytes(1024) + payload.encode("utf-8"))
    return base64.b64encode(dropped[1024:]).decode("ascii")


def decrypt_rc4(password_b64: str, payload: str) -> bytes:
    key = base64.b64decode(password_b64)
    raw = base64.b64decode(payload)
    dropped = _rc4(key, bytes(1024) + raw)
    return dropped[1024:]


def _enc_signature(url: str, method: str, signed: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    path = parsed.path.replace("/app/", "/", 1)
    parts = [method.upper(), path]
    for key, value in params.items():
        parts.append(f"{key}={value}")
    parts.append(signed)
    digest = hashlib.sha1("&".join(parts).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def generate_enc_params(
    url: str,
    method: str,
    signed: str,
    nonce: str,
    data: str,
    ssecurity: str,
) -> dict[str, str]:
    params = {"data": data}
    params["rc4_hash__"] = _enc_signature(url, method, signed, params)
    encrypted = {key: encrypt_rc4(signed, value) for key, value in params.items()}
    encrypted["signature"] = _enc_signature(url, method, signed, encrypted)
    encrypted["ssecurity"] = ssecurity
    encrypted["_nonce"] = nonce
    return encrypted


def spec_short_name(urn: str) -> str:
    parts = str(urn or "").split(":")
    if len(parts) >= 4:
        return parts[3]
    return ""


def find_property(
    spec: dict[str, Any],
    names: tuple[str, ...],
    *,
    service_names: tuple[str, ...] | None = None,
) -> tuple[int, int] | None:
    wanted = frozenset(names)
    services = spec.get("services") if isinstance(spec, dict) else None
    if not isinstance(services, list):
        return None
    for service in services:
        if not isinstance(service, dict):
            continue
        if service_names:
            svc_name = spec_short_name(str(service.get("type") or ""))
            if svc_name not in service_names:
                continue
        siid = service.get("iid")
        if not isinstance(siid, int):
            continue
        for prop in service.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            short = spec_short_name(str(prop.get("type") or ""))
            if short in wanted:
                piid = prop.get("iid")
                if isinstance(piid, int):
                    return siid, piid
    return None


def find_action(
    spec: dict[str, Any],
    names: tuple[str, ...],
    *,
    service_names: tuple[str, ...] | None = None,
) -> tuple[int, int] | None:
    wanted = frozenset(names)
    services = spec.get("services") if isinstance(spec, dict) else None
    if not isinstance(services, list):
        return None
    for service in services:
        if not isinstance(service, dict):
            continue
        if service_names:
            svc_name = spec_short_name(str(service.get("type") or ""))
            if svc_name not in service_names:
                continue
        siid = service.get("iid")
        if not isinstance(siid, int):
            continue
        for action in service.get("actions") or []:
            if not isinstance(action, dict):
                continue
            short = spec_short_name(str(action.get("type") or ""))
            if short in wanted:
                aiid = action.get("iid")
                if isinstance(aiid, int):
                    return siid, aiid
    return None


def _parse_json_prefixed(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith(_JSON_PREFIX):
        raw = raw[len(_JSON_PREFIX) :]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise XiaomiCloudError("米家登录失败：无法解析账号服务响应。") from e
    if not isinstance(parsed, dict):
        raise XiaomiCloudError("米家登录失败：账号服务响应不是对象。")
    return parsed


@dataclass(frozen=True)
class XiaomiDevice:
    did: str
    name: str
    model: str
    online: bool
    uid: int | None = None
    extra: dict[str, Any] | None = None


class XiaomiCloud:
    def __init__(
        self,
        *,
        username: str,
        password: str,
        country: str | None = None,
        timeout_sec: float = _DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self.username = username.strip()
        self.password = password
        self.country = (country or country_code()).strip().lower() or "cn"
        self.timeout_sec = timeout_sec
        self._client = client
        self.user_id: str | None = None
        self.ssecurity: str | None = None
        self.service_token: str | None = None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout_sec,
                follow_redirects=False,
                headers={"User-Agent": _UA},
            )
        return self._client

    def login(self) -> None:
        if self.user_id and self.ssecurity and self.service_token:
            return
        http = self._http()
        try:
            step1 = http.get(
                "https://account.xiaomi.com/pass/serviceLogin",
                params={"sid": _API_SID, "_json": "true"},
                cookies={"userId": self.username},
            )
        except httpx.RequestError as e:
            raise XiaomiCloudError(f"米家登录失败：连不上账号服务（{e}）。") from e
        payload = _parse_json_prefixed(step1.text)
        sign = str(payload.get("_sign") or "")
        post: dict[str, str] = {
            "sid": _API_SID,
            "hash": hashlib.md5(
                self.password.encode("utf-8"), usedforsecurity=False
            ).hexdigest().upper(),
            "callback": "https://sts.api.io.mi.com/sts",
            "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
            "user": self.username,
            "_json": "true",
        }
        if sign and not sign.startswith("http"):
            post["_sign"] = sign
        try:
            step2 = http.post(
                "https://account.xiaomi.com/pass/serviceLoginAuth2",
                data=post,
            )
        except httpx.RequestError as e:
            raise XiaomiCloudError(f"米家登录失败：账号鉴权请求失败（{e}）。") from e
        auth = _parse_json_prefixed(step2.text)
        if str(auth.get("result") or "") != "ok":
            desc = str(auth.get("desc") or auth.get("tips") or auth.get("code") or "")
            if auth.get("notificationUrl") or "captcha" in json.dumps(auth).lower():
                raise XiaomiCloudError(
                    "米家登录失败：需要验证码。请先在米家 App 登录该账号后再试。"
                )
            raise XiaomiCloudError(
                f"米家登录失败：账号或密码不对{f'（{desc}）' if desc else ''}。"
            )
        self.user_id = str(auth.get("userId") or "").strip() or None
        self.ssecurity = str(auth.get("ssecurity") or "").strip() or None
        location = str(auth.get("location") or "").strip()
        if not self.user_id or not self.ssecurity or not location:
            raise XiaomiCloudError("米家登录失败：账号服务没有返回 token。")
        try:
            step3 = http.get(location)
        except httpx.RequestError as e:
            raise XiaomiCloudError(f"米家登录失败：无法换取 serviceToken（{e}）。") from e
        token = step3.cookies.get("serviceToken")
        if not token:
            raise XiaomiCloudError("米家登录失败：没有拿到 serviceToken。")
        self.service_token = token
        log.info("xiaomi cloud login ok user_id=%s country=%s", self.user_id, self.country)

    def request(self, path: str, data: dict[str, Any] | list[Any]) -> Any:
        self.login()
        if not self.ssecurity or not self.service_token or not self.user_id:
            raise XiaomiCloudError("米家请求失败：尚未登录。")
        url = api_base(self.country) + path
        payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        nonce = gen_nonce()
        signed = signed_nonce(self.ssecurity, nonce)
        form = generate_enc_params(
            url, "POST", signed, nonce, payload, self.ssecurity
        )
        http = self._http()
        try:
            resp = http.post(
                url,
                data=form,
                headers={
                    "Accept-Encoding": "identity",
                    "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
                    "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
                    "content-type": "application/x-www-form-urlencoded",
                },
                cookies={
                    "userId": str(self.user_id),
                    "serviceToken": self.service_token,
                    "yetAnotherServiceToken": self.service_token,
                    "locale": "zh_CN",
                    "timezone": "GMT+08:00",
                    "channel": "MI_APP_STORE",
                    "sdkVersion": "3.8.6",
                },
            )
        except httpx.RequestError as e:
            raise XiaomiCloudError(f"米家请求失败：{path}（{e}）。") from e
        if resp.status_code == 403:
            self.service_token = None
            raise XiaomiCloudError("米家请求被拒绝（403）。请检查账号登录状态。")
        if resp.status_code >= 400:
            raise XiaomiCloudError(
                f"米家请求失败：HTTP {resp.status_code} {path}。"
            )
        try:
            decrypted = decrypt_rc4(
                signed_nonce(self.ssecurity, form["_nonce"]),
                resp.text,
            )
            parsed = json.loads(decrypted.decode("utf-8"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
            raise XiaomiCloudError("米家请求失败：无法解密或解析响应。") from e
        if not isinstance(parsed, dict):
            raise XiaomiCloudError("米家请求失败：响应不是对象。")
        code = parsed.get("code")
        if code not in (0, "0", None):
            message = str(parsed.get("message") or parsed.get("result") or code)
            raise XiaomiCloudError(f"米家接口失败：{message}。")
        return parsed.get("result")

    def list_devices(self) -> list[XiaomiDevice]:
        result = self.request(
            "/home/device_list",
            {
                "getVirtualModel": True,
                "getHuamiDevices": 1,
                "get_split_device": False,
                "support_smart_home": True,
            },
        )
        rows = []
        if isinstance(result, dict):
            raw = result.get("list")
            if isinstance(raw, list):
                rows = raw
        devices: list[XiaomiDevice] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            did = str(item.get("did") or "").strip()
            if not did:
                continue
            devices.append(
                XiaomiDevice(
                    did=did,
                    name=str(item.get("name") or "").strip() or did,
                    model=str(item.get("model") or "").strip(),
                    online=bool(item.get("isOnline")),
                    uid=item.get("uid") if isinstance(item.get("uid"), int) else None,
                    extra=item,
                )
            )
        return devices

    def get_properties(
        self, did: str, props: list[tuple[int, int]]
    ) -> list[dict[str, Any]]:
        params = [{"did": did, "siid": siid, "piid": piid} for siid, piid in props]
        result = self.request("/miotspec/prop/get", {"params": params})
        if isinstance(result, list):
            return [row for row in result if isinstance(row, dict)]
        return []

    def set_properties(
        self, did: str, props: list[tuple[int, int, Any]]
    ) -> list[dict[str, Any]]:
        params = [
            {"did": did, "siid": siid, "piid": piid, "value": value}
            for siid, piid, value in props
        ]
        result = self.request("/miotspec/prop/set", {"params": params})
        if isinstance(result, list):
            return [row for row in result if isinstance(row, dict)]
        return []

    def call_action(
        self,
        did: str,
        siid: int,
        aiid: int,
        ins: list[Any] | None = None,
    ) -> Any:
        return self.request(
            "/miotspec/action",
            {
                "params": {
                    "did": did,
                    "siid": siid,
                    "aiid": aiid,
                    "in": list(ins or []),
                }
            },
        )


_SESSION: XiaomiCloud | None = None


def connect_cloud(
    *,
    factory: Any | None = None,
) -> XiaomiCloud:
    global _SESSION
    if factory is not None:
        cloud = factory()
        cloud.login()
        return cloud
    username = (os.environ.get("MAC_EDGE_XIAOMI_USERNAME") or "").strip()
    password = (os.environ.get("MAC_EDGE_XIAOMI_PASSWORD") or "").strip()
    if not username or not password:
        raise XiaomiCloudError(
            "米家控制失败：未配置 MAC_EDGE_XIAOMI_USERNAME / MAC_EDGE_XIAOMI_PASSWORD。"
        )
    if (
        _SESSION is not None
        and _SESSION.username == username
        and _SESSION.password == password
        and _SESSION.service_token
    ):
        return _SESSION
    cloud = XiaomiCloud(username=username, password=password)
    cloud.login()
    _SESSION = cloud
    return cloud


def reset_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.close()
    _SESSION = None


def pick_device(
    devices: list[XiaomiDevice],
    *,
    did: str = "",
    name_contains: tuple[str, ...] = (),
    model_contains: tuple[str, ...] = (),
    label: str,
) -> XiaomiDevice:
    if not devices:
        raise XiaomiCloudError(f"{label}失败：账号下没有匹配的设备。")
    wanted = did.strip()
    if wanted:
        for device in devices:
            if device.did == wanted:
                return device
        raise XiaomiCloudError(f"{label}失败：找不到设备 {wanted}。")
    matched: list[XiaomiDevice] = []
    for device in devices:
        model = device.model.lower()
        name = device.name
        if model_contains and any(token in model for token in model_contains):
            matched.append(device)
            continue
        if name_contains and any(token in name for token in name_contains):
            matched.append(device)
    filtered = bool(name_contains or model_contains)
    pool = matched if filtered else list(devices)
    if not pool:
        raise XiaomiCloudError(f"{label}失败：账号下没有匹配的设备。")
    if len(pool) == 1:
        return pool[0]
    names = "、".join(f"{d.name}({d.did}/{d.model})" for d in pool[:8])
    raise XiaomiCloudError(
        f"{label}失败：匹配到多台设备，请设置对应 DID。候选：{names}"
    )
