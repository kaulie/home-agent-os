"""局域网设备地址**探测层**（纯标准库）：SSDP 发现 → UPnP 描述 → 本机出口 IP 探测。

为什么要它：小度 / 小米这类设备的地址由家里的 DHCP 分配，写死在 env 里迟早过期——
本机就踩过：`MAC_EDGE_XIAODU_PUBLIC_HOST` 停在 `192.168.3.73`，而 Mac 已经是
`192.168.3.84`，小度拿到的音频 URL 指向一个不存在的地址。

规则（本模块与调用方共同保证）：

1. **先探测、再采信**：拿到设备描述 + 一次真控制调用（`GetTransportInfo`）探活，
   探不通就当没发现；
2. **env 只是可选覆盖**：显式指定优先，但要能被验证（是不是本机地址？探活过不过？），
   过期/错的覆盖值会被忽略并写 warn，不允许它静默毁掉功能；
3. **本机出口 IP 按目标探测**：`local_ip_for(peer)` 用 UDP connect 拿「能直达该设备」
   的那块网卡的地址，比「连 8.8.8.8」（家里没外网就失效）可靠。
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import struct
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

log = logging.getLogger("mac_edge.lan_discovery")

SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_ST_MEDIA_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"
SSDP_ST_ALL = "ssdp:all"
SSDP_MX_SEC = 2
DEFAULT_SSDP_TIMEOUT_SEC = 2.5
DEFAULT_HTTP_TIMEOUT_SEC = 4.0

AV_TRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"

_RE_HEADER = re.compile(r"^([A-Za-z0-9-]+):\s*(.*)$")


class LanDiscoveryError(Exception):
    """探测层明确失败（组播发不出去 / 描述拉不到 / 描述解析不了 / 控制调用失败）。"""


@dataclass(frozen=True)
class SsdpResponse:
    """一条 SSDP 应答。"""

    ip: str
    location: str
    st: str = ""
    usn: str = ""
    server: str = ""


@dataclass(frozen=True)
class DeviceDescription:
    """一台 UPnP 设备的描述（只取我们用的字段）。"""

    location: str
    ip: str
    friendly_name: str = ""
    manufacturer: str = ""
    model_name: str = ""
    udn: str = ""
    url_base: str = ""
    services: dict[str, str] = field(default_factory=dict)

    def control_url(self, service_type: str = AV_TRANSPORT) -> str:
        """某服务的控制地址（绝对 URL）；没有则空串。"""
        return str(self.services.get(service_type) or "")

    def identity_text(self) -> str:
        """身份文本（匹配用）：friendlyName + manufacturer + modelName 小写拼接。"""
        return " ".join(
            part for part in (self.friendly_name, self.manufacturer, self.model_name) if part
        ).casefold()


def _parse_headers(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _RE_HEADER.match(line.strip())
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    return out


def _msearch_payload(st: str, mx: int = SSDP_MX_SEC) -> bytes:
    return (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {mx}\r\n"
        f"ST: {st}\r\n"
        "\r\n"
    ).encode("utf-8")


def ssdp_search(
    st: str = SSDP_ST_MEDIA_RENDERER,
    *,
    timeout_sec: float = DEFAULT_SSDP_TIMEOUT_SEC,
    rounds: int = 1,
    socket_fn: Callable[[], Any] | None = None,
) -> list[SsdpResponse]:
    """组播 M-SEARCH，返回去重后的应答列表（按 ip+location 去重）。

    `rounds` > 1 是给 Wi-Fi 组播抖动留余量：一轮空手不代表设备不在。
    组播发不出去（无网卡 / 权限）→ `LanDiscoveryError`；单纯没人应答 → 空列表。
    """
    make_socket = socket_fn or (
        lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    )
    found: list[SsdpResponse] = []
    seen: set[tuple[str, str]] = set()
    budget = max(0.5, float(timeout_sec))
    for _ in range(max(1, int(rounds))):
        sock = make_socket()
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.settimeout(0.5)
            sock.sendto(_msearch_payload(st), SSDP_ADDR)
            deadline = time.time() + budget
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(65507)
                except socket.timeout:
                    continue
                except OSError:
                    break
                headers = _parse_headers(data.decode("utf-8", errors="replace"))
                location = headers.get("location", "")
                key = (str(addr[0]), location)
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    SsdpResponse(
                        ip=str(addr[0]),
                        location=location,
                        st=headers.get("st", ""),
                        usn=headers.get("usn", ""),
                        server=headers.get("server", ""),
                    )
                )
        except OSError as e:
            raise LanDiscoveryError(f"SSDP 组播失败：{e}") from e
        finally:
            try:
                sock.close()
            except OSError:  # pragma: no cover - 关闭失败不影响结果
                pass
    return found


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def parse_device_description(xml_text: str, location: str) -> DeviceDescription:
    """解析 UPnP device description；一个服务都没有时抛错。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise LanDiscoveryError(f"设备描述 XML 无法解析：{location}") from e
    friendly = manufacturer = model = udn = url_base = ""
    services: dict[str, str] = {}
    for node in root.iter():
        name = _local_name(node.tag)
        if name == "friendlyName" and not friendly:
            friendly = _text(node)
        elif name == "manufacturer" and not manufacturer:
            manufacturer = _text(node)
        elif name == "modelName" and not model:
            model = _text(node)
        elif name == "UDN" and not udn:
            udn = _text(node)
        elif name == "URLBase" and not url_base:
            url_base = _text(node)
        elif name == "service":
            stype = curl = ""
            for child in list(node):
                cname = _local_name(child.tag)
                if cname == "serviceType":
                    stype = _text(child)
                elif cname == "controlURL":
                    curl = _text(child)
            if stype and curl:
                services[stype] = urljoin(url_base or location, curl)
    if not services:
        raise LanDiscoveryError(f"设备描述里没有任何服务：{location}")
    return DeviceDescription(
        location=location,
        ip=str(urlparse(location).hostname or ""),
        friendly_name=friendly,
        manufacturer=manufacturer,
        model_name=model,
        udn=udn,
        url_base=url_base,
        services=services,
    )


def fetch_device_description(
    location: str, *, timeout_sec: float = DEFAULT_HTTP_TIMEOUT_SEC
) -> DeviceDescription:
    """HTTP 拉设备描述并解析（「探测」的第一步）。"""
    req = urllib.request.Request(
        location, headers={"User-Agent": "mac-edge-lan-discovery/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            if status >= 400:
                raise LanDiscoveryError(f"设备描述 HTTP {status}：{location}")
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise LanDiscoveryError(f"设备描述 HTTP {e.code}：{location}") from e
    except (urllib.error.URLError, OSError) as e:
        raise LanDiscoveryError(f"设备描述拉取失败（{location}）：{e}") from e
    return parse_device_description(body, location)

def soap_control(
    control_url: str,
    action: str,
    inner: str,
    *,
    service_type: str = AV_TRANSPORT,
    timeout_sec: float = DEFAULT_HTTP_TIMEOUT_SEC,
) -> str:
    """发一次 UPnP 控制调用（SOAP）；非 2xx 抛错，返回响应体文本。"""
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{SOAP_ENV}" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        f'<u:{action} xmlns:u="{service_type}">{inner}</u:{action}>'
        "</s:Body></s:Envelope>"
    )
    req = urllib.request.Request(
        control_url,
        data=envelope.encode("utf-8"),
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"{service_type}#{action}"',
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise LanDiscoveryError(f"UPnP {action} HTTP {e.code}：{control_url}") from e
    except (urllib.error.URLError, OSError) as e:
        raise LanDiscoveryError(f"UPnP {action} 请求失败（{control_url}）：{e}") from e


def probe_av_transport(control_url: str, *, timeout_sec: float = DEFAULT_HTTP_TIMEOUT_SEC) -> bool:
    """AVTransport 探活：`GetTransportInfo` 通了才算这台设备真的可用（返回 bool，不抛）。"""
    if not control_url:
        return False
    try:
        soap_control(
            control_url,
            "GetTransportInfo",
            "<InstanceID>0</InstanceID>",
            timeout_sec=timeout_sec,
        )
        return True
    except LanDiscoveryError as e:
        log.info("av transport probe failed (%s): %s", control_url, e)
        return False


def local_ips(*, include_link_local: bool = False) -> list[str]:
    """本机所有 IPv4 网卡地址（默认滤掉 127.0.0.1 与 169.254.* 链路本地）。"""
    out: list[str] = []
    try:
        names = [name for _idx, name in socket.if_nameindex()]
    except (OSError, AttributeError):  # pragma: no cover - 平台兜底
        names = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        fd = sock.fileno()
        for name in names:
            try:
                res = _ioctl(fd, struct.pack("256s", name.encode("utf-8")[:15]))
            except OSError:
                continue
            ip = socket.inet_ntoa(res[20:24])
            if ip.startswith("127.") or (ip.startswith("169.254.") and not include_link_local):
                continue
            if ip not in out:
                out.append(ip)
    finally:
        sock.close()
    if not out:
        try:
            out.append(local_ip_for("8.8.8.8"))
        except LanDiscoveryError:  # pragma: no cover
            pass
    return out


def _ioctl(fd: int, packed_ifreq: bytes) -> bytes:  # pragma: no cover - 平台相关
    import fcntl

    # macOS / Linux 都是 SIOCGIFADDR=0x8915；ifreq 前 16 字节是网卡名
    return fcntl.ioctl(fd, 0x8915, packed_ifreq)


def is_local_ip(ip: str) -> bool:
    """这个地址是不是本机网卡上的地址（用来验证覆盖值是否过期）。"""
    target = str(ip or "").strip()
    if not target:
        return False
    return target in local_ips(include_link_local=True)


def local_ip_for(peer_ip: str) -> str:
    """探测「能直达 peer_ip」的本机地址（UDP connect 不发包，只按路由选网卡）。

    家里没有外网时「连 8.8.8.8」会失效，所以按目标设备探测更可靠。
    """
    target = str(peer_ip or "").strip()
    if not target:
        raise LanDiscoveryError("local_ip_for 需要一个目标地址")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target, 9))
        return str(sock.getsockname()[0])
    except OSError as e:
        raise LanDiscoveryError(f"探测本机出口地址失败（目标 {target}）：{e}") from e
    finally:
        sock.close()


def lan_host_fallback() -> str:
    """兜底本机地址：默认路由 → 第一块网卡 → 127.0.0.1。"""
    try:
        return local_ip_for("8.8.8.8")
    except LanDiscoveryError:
        pass
    ips = local_ips()
    return ips[0] if ips else "127.0.0.1"


def resolve_public_host(
    peer_ip: str | None, override: str | None = None, *, what: str = "设备"
) -> str:
    """给「对端设备」用的本机供流地址。

    override 只有在**确实是本机网卡地址**时才采信；否则忽略并 warn（过期值会静默毁功能），
    然后按目标设备探测出口地址。
    """
    wanted = str(override or "").strip()
    if wanted:
        if is_local_ip(wanted):
            return wanted
        log.warning(
            "忽略过期的本机地址覆盖 %r（本机网卡：%s）—— 改为按 %s 探测可达地址",
            wanted,
            ",".join(local_ips()) or "?",
            what,
        )
    if peer_ip:
        try:
            return local_ip_for(peer_ip)
        except LanDiscoveryError as e:
            log.warning("按 %s 探测本机出口地址失败（%s）—— 退回默认路由", what, e)
    return lan_host_fallback()


def data_dir(default: Path | None = None) -> Path:
    """探测缓存放哪：`MAC_EDGE_DATA_DIR` 优先，否则给定默认，再退临时目录。"""
    root = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if root:
        return Path(root)
    if default is not None:
        return default
    import tempfile

    return Path(tempfile.gettempdir()) / "mac-edge-lan"


def read_cache(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = dict(payload)
        body.setdefault("saved_at", int(time.time()))
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    except OSError as e:  # pragma: no cover - 缓存写不了不影响功能
        log.warning("探测缓存写入失败 %s：%s", path, e)


def drop_cache(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
