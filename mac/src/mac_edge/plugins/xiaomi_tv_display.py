"""Xiaomi TV S Pro display adapter: DLNA SetAVTransportURI for display.photo.

Same wire capabilities as Cast. Mac Edge picks this backend when
MAC_EDGE_DISPLAY_BACKEND=xiaomi or a Xiaomi TV host/name is configured.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

import httpx

from mac_edge.plugins import lan_discovery as lan
from mac_edge.plugins.chromecast_display import (
    DEFAULT_SLIDESHOW_INTERVAL_SEC,
    ORDER_ARRAY_ASC,
    order_photo_urls,
)

log = logging.getLogger("mac_edge.xiaomi_tv")

SSDP_ADDR = lan.SSDP_ADDR
SSDP_ST = lan.SSDP_ST_MEDIA_RENDERER
AV_TRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"


class XiaomiTvError(Exception):
    pass


def display_backend() -> str:
    raw = (os.environ.get("MAC_EDGE_DISPLAY_BACKEND") or "").strip().lower()
    if raw in ("xiaomi", "dlna", "tv"):
        return "xiaomi"
    if raw in ("cast", "chromecast"):
        return "cast"
    if tv_configured():
        return "xiaomi"
    return "cast"


def tv_configured() -> bool:
    flag = (os.environ.get("MAC_EDGE_XIAOMI_TV") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if (os.environ.get("MAC_EDGE_XIAOMI_TV_HOST") or "").strip():
        return True
    if (os.environ.get("MAC_EDGE_XIAOMI_TV_NAME") or "").strip():
        return True
    return False


def _wanted_host() -> str:
    return (os.environ.get("MAC_EDGE_XIAOMI_TV_HOST") or "").strip()


def _wanted_name() -> str:
    return (os.environ.get("MAC_EDGE_XIAOMI_TV_NAME") or "").strip()


def _ssdp_search(timeout_sec: float = 2.0) -> list[str]:
    """组播 M-SEARCH 找 DLNA 渲染器（走共用探测层，语义与旧实现一致）。"""
    try:
        responses = lan.ssdp_search(
            lan.SSDP_ST_MEDIA_RENDERER, timeout_sec=timeout_sec, rounds=1
        )
    except lan.LanDiscoveryError as e:
        raise XiaomiTvError(f"投电视失败：SSDP 发现失败（{e}）。") from e
    locations: list[str] = []
    for resp in responses:
        if resp.location and resp.location not in locations:
            locations.append(resp.location)
    return locations


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def parse_device_description(xml_text: str, base_url: str) -> dict[str, str] | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise XiaomiTvError("投电视失败：电视描述 XML 无法解析。") from e
    friendly = ""
    control = ""
    for node in root.iter():
        name = _local_name(node.tag)
        if name == "friendlyName" and not friendly:
            friendly = _text(node)
        if name == "service":
            stype = ""
            curl = ""
            for child in list(node):
                cname = _local_name(child.tag)
                if cname == "serviceType":
                    stype = _text(child)
                elif cname == "controlURL":
                    curl = _text(child)
            if AV_TRANSPORT in stype and curl:
                control = urljoin(base_url, curl)
    if not control:
        return None
    return {"friendly_name": friendly, "control_url": control, "base_url": base_url}


def _name_matches(friendly: str) -> bool:
    wanted = _wanted_name()
    if wanted:
        return wanted.casefold() in friendly.casefold()
    tokens = ("小米", "xiaomi", "mitv", "电视", "s pro", "spro")
    folded = friendly.casefold()
    return any(token in folded or token in friendly for token in tokens)


def _host_matches(url: str) -> bool:
    wanted = _wanted_host()
    if not wanted:
        return True
    host = urlparse(url).hostname or ""
    return host == wanted or host.endswith("." + wanted) or wanted == host


def _renderer_matches(parsed: dict[str, str], location: str) -> bool:
    """统一的电视匹配语义：配了 NAME 必须名匹配；只配 HOST 则地址匹配即可；
    都没配则 friendlyName 须命中默认小米电视词。"""
    if not _host_matches(location):
        return False
    if _wanted_name():
        return _name_matches(parsed["friendly_name"])
    if _wanted_host():
        return True
    return _name_matches(parsed["friendly_name"])


# ---------------------------------------------------------------------------
# 发现加速与待机唤醒：位置缓存 + SSDP 多轮 + WoL
#
# 小米电视「网络待机」时 DLNA 活着、可直接投（电视被唤醒亮屏）；但 SSDP 组播
# 在 Wi-Fi 下抖动明显，且深度休眠时组播无响应。因此：
# 1. 投成功过的电视描述地址（location）落盘缓存，下次先单播直连——不依赖组播；
# 2. SSDP 默认搜 2 轮（MAC_EDGE_XIAOMI_TV_SSDP_ROUNDS 可调，1–5）；
# 3. 配了 MAC_EDGE_XIAOMI_TV_MAC 时，搜不到就发 WoL 魔术包唤醒后再补一轮。
# ---------------------------------------------------------------------------


def _cache_path() -> Path:
    root = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    base = Path(root) if root else Path(tempfile.gettempdir()) / "mac-edge-xiaomi-tv"
    return base / "xiaomi_tv_renderer.json"


def _read_cache(path: Path) -> dict[str, str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    location = str(data.get("location") or "").strip()
    if not location:
        return None
    data["location"] = location
    return data


def _write_cache(path: Path, location: str, parsed: dict[str, str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "location": location,
                    "friendly_name": parsed.get("friendly_name", ""),
                    "control_url": parsed.get("control_url", ""),
                    "saved_at": int(time.time()),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _ssdp_rounds() -> int:
    raw = (os.environ.get("MAC_EDGE_XIAOMI_TV_SSDP_ROUNDS") or "").strip()
    try:
        return max(1, min(5, int(raw))) if raw else 2
    except ValueError:
        return 2


def _send_wol(mac: str) -> None:
    """Wake-on-LAN 魔术包（UDP 广播 9 端口 ×3）。MAC 形如 aa:bb:cc:dd:ee:ff。"""
    cleaned = mac.replace(":", "").replace("-", "").strip()
    if len(cleaned) != 12:
        raise XiaomiTvError(f"MAC_EDGE_XIAOMI_TV_MAC 格式不对：{mac!r}")
    try:
        payload = b"\xff" * 6 + bytes.fromhex(cleaned) * 16
    except ValueError as e:
        raise XiaomiTvError(f"MAC_EDGE_XIAOMI_TV_MAC 格式不对：{mac!r}") from e
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            s.sendto(payload, ("255.255.255.255", 9))


def discover_renderer(
    *,
    search_fn: Callable[[], list[str]] | None = None,
    fetch_fn: Callable[[str], str] | None = None,
    timeout_sec: float = 5.0,
    wol_fn: Callable[[str], None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> dict[str, str]:
    fetcher = fetch_fn
    if fetcher is None:

        def _fetch(url: str) -> str:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.get(url)
            if resp.status_code >= 400:
                raise XiaomiTvError(
                    f"投电视失败：读取电视描述 HTTP {resp.status_code}。"
                )
            return resp.text

        fetcher = _fetch

    # 1) 缓存直连：上次投成功的描述地址单播重取（拿到最新 control_url），
    #    不依赖组播；待机电视只要网络栈活着即可命中。
    cache = _cache_path()
    cached = _read_cache(cache)
    if cached is not None:
        loc = cached["location"].strip()
        try:
            parsed = parse_device_description(fetcher(loc), loc)
        except (XiaomiTvError, httpx.RequestError):
            parsed = None
        if parsed is not None and _renderer_matches(parsed, loc):
            log.info(
                "xiaomi tv renderer via cache name=%s control=%s",
                parsed.get("friendly_name"),
                parsed.get("control_url"),
            )
            return parsed
        log.info("xiaomi tv cache stale (%s), fall back to SSDP", loc)

    # 2) SSDP 多轮（Wi-Fi 组播抖动，一轮空手不代表电视不在）
    search = search_fn or (lambda: _ssdp_search(min(timeout_sec, 3.0)))
    locations: list[str] = []
    for _ in range(_ssdp_rounds()):
        locations = search()
        if locations:
            break

    # 3) 配了电视 MAC 时发 WoL 魔术包唤醒（深度休眠），稍等网络栈起来再补一轮
    if not locations:
        mac = (os.environ.get("MAC_EDGE_XIAOMI_TV_MAC") or "").strip()
        if mac:
            (wol_fn or _send_wol)(mac)
            (sleep_fn or time.sleep)(3.0)
            locations = search()

    if not locations:
        raise XiaomiTvError(
            "投电视失败：局域网里没有发现 DLNA 电视。请打开小米电视投屏/DLNA，"
            "或设置 MAC_EDGE_XIAOMI_TV_HOST；深度休眠可配 MAC_EDGE_XIAOMI_TV_MAC 网络唤醒。"
        )
    candidates: list[tuple[str, dict[str, str]]] = []
    for loc in locations:
        if not _host_matches(loc):
            continue
        try:
            xml_text = fetcher(loc)
            parsed = parse_device_description(xml_text, loc)
        except XiaomiTvError:
            continue
        except httpx.RequestError:
            continue
        if parsed is None:
            continue
        if not _renderer_matches(parsed, loc):
            continue
        candidates.append((loc, parsed))
    if not candidates:
        raise XiaomiTvError(
            "投电视失败：发现了 DLNA 设备，但没有匹配的小米电视。"
            "请设置 MAC_EDGE_XIAOMI_TV_NAME 或 HOST。"
        )
    chosen_loc, chosen = candidates[0]
    log.info(
        "xiaomi tv renderer name=%s control=%s",
        chosen.get("friendly_name"),
        chosen.get("control_url"),
    )
    _write_cache(cache, chosen_loc, chosen)
    return chosen


def _soap_body(action: str, inner: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{SOAP_ENV}" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        f'<u:{action} xmlns:u="{AV_TRANSPORT}">{inner}</u:{action}>'
        "</s:Body></s:Envelope>"
    )


def soap_action(
    control_url: str,
    action: str,
    inner: str,
    *,
    timeout_sec: float = 10.0,
    post_fn: Callable[[str, str, dict[str, str]], int] | None = None,
) -> None:
    envelope = _soap_body(action, inner)
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": f'"{AV_TRANSPORT}#{action}"',
    }
    if post_fn is not None:
        status = post_fn(control_url, envelope, headers)
    else:
        try:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.post(control_url, content=envelope, headers=headers)
            status = resp.status_code
        except httpx.RequestError as e:
            raise XiaomiTvError(f"投电视失败：DLNA 控制请求失败（{e}）。") from e
    if status >= 400:
        raise XiaomiTvError(f"投电视失败：DLNA {action} HTTP {status}。")


def play_photo(
    photo_url: str,
    *,
    renderer: dict[str, str] | None = None,
    timeout_sec: float = 10.0,
    post_fn: Callable[[str, str, dict[str, str]], int] | None = None,
    discover_fn: Callable[[], dict[str, str]] | None = None,
) -> str:
    url = (photo_url or "").strip()
    if not url:
        raise XiaomiTvError("投电视失败：photo_url 为空。")
    if not url.startswith("http://") and not url.startswith("https://"):
        raise XiaomiTvError("投电视失败：photo_url 必须是 http(s)。")
    target = renderer or (discover_fn or discover_renderer)()
    control = target["control_url"]
    soap_action(
        control,
        "SetAVTransportURI",
        f"<InstanceID>0</InstanceID><CurrentURI>{xml_escape(url)}</CurrentURI>"
        "<CurrentURIMetaData></CurrentURIMetaData>",
        timeout_sec=timeout_sec,
        post_fn=post_fn,
    )
    soap_action(
        control,
        "Play",
        "<InstanceID>0</InstanceID><Speed>1</Speed>",
        timeout_sec=timeout_sec,
        post_fn=post_fn,
    )
    name = target.get("friendly_name") or "xiaomi-tv"
    return f"dlna ok → {name}"


def play_slideshow(
    urls: list[str],
    *,
    interval_sec: float = DEFAULT_SLIDESHOW_INTERVAL_SEC,
    order: str = ORDER_ARRAY_ASC,
    timeout_sec: float = 10.0,
    post_fn: Callable[[str, str, dict[str, str]], int] | None = None,
    discover_fn: Callable[[], dict[str, str]] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> str:
    ordered = order_photo_urls(urls, order)
    if not ordered:
        raise XiaomiTvError("display.slideshow requires photo_urls")
    renderer = (discover_fn or discover_renderer)()
    hold = max(0.0, float(interval_sec))
    sleeper = sleep_fn or time.sleep
    last = ""
    for i, url in enumerate(ordered):
        last = play_photo(
            url,
            renderer=renderer,
            timeout_sec=timeout_sec,
            post_fn=post_fn,
        )
        if i + 1 < len(ordered) and hold > 0:
            sleeper(hold)
    return f"slideshow ok count={len(ordered)} order={order} {last}"


def photo_from_params(
    params: dict[str, str],
    *,
    asset: Any,
    timeout_sec: float = 10.0,
    **_kwargs: Any,
) -> tuple[str, dict[str, Any]]:
    from mac_edge.asset.sdk import CapAsset
    from mac_edge.asset.types import AssetError

    if not isinstance(asset, CapAsset):
        raise XiaomiTvError("display.photo requires CapAsset (Runtime SDK)")
    try:
        ref = asset.require_ref(params, "asset_ref")
        photo_url = asset.http_url(ref)
    except AssetError as e:
        raise XiaomiTvError(str(e)) from e
    msg = play_photo(photo_url, timeout_sec=timeout_sec)
    asset_id = getattr(ref, "asset_id", None) or (
        ref.get("asset_id") if isinstance(ref, dict) else None
    )
    return (
        f"{msg} · cast_status=accepted (xiaomi dlna)",
        {
            "cast_transport": "xiaomi_dlna",
            "cast_status": "accepted",
            "protocol_version": 0,
            "asset_id": asset_id,
        },
    )


def slideshow_from_params(
    params: dict[str, str],
    *,
    asset: Any,
    timeout_sec: float = 10.0,
    **_kwargs: Any,
) -> tuple[str, dict[str, Any]]:
    from mac_edge.asset.sdk import CapAsset
    from mac_edge.asset.types import AssetError

    if not isinstance(asset, CapAsset):
        raise XiaomiTvError("display.slideshow requires CapAsset (Runtime SDK)")
    try:
        refs = asset.require_refs(params, "asset_refs")
        urls = [asset.http_url(ref) for ref in refs]
    except AssetError as e:
        raise XiaomiTvError(str(e)) from e
    interval = DEFAULT_SLIDESHOW_INTERVAL_SEC
    raw_interval = (params.get("interval_sec") or "").strip()
    if raw_interval:
        try:
            interval = float(raw_interval)
        except ValueError as e:
            raise XiaomiTvError(f"interval_sec must be a number: {raw_interval}") from e
    order = (params.get("order") or ORDER_ARRAY_ASC).strip() or ORDER_ARRAY_ASC
    msg = play_slideshow(
        urls,
        interval_sec=interval,
        order=order,
        timeout_sec=timeout_sec,
    )
    return (
        f"{msg} · cast_status=accepted (xiaomi dlna slideshow)",
        {
            "cast_transport": "xiaomi_dlna",
            "cast_status": "accepted",
            "protocol_version": 0,
            "count": len(urls),
        },
    )
