"""Xiaomi TV S Pro display adapter: DLNA SetAVTransportURI for display.photo.

Same wire capabilities as Cast. Mac Edge picks this backend when
MAC_EDGE_DISPLAY_BACKEND=xiaomi or a Xiaomi TV host/name is configured.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from typing import Any, Callable
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

import httpx

from mac_edge.plugins.chromecast_display import (
    DEFAULT_SLIDESHOW_INTERVAL_SEC,
    ORDER_ARRAY_ASC,
    order_photo_urls,
)

log = logging.getLogger("mac_edge.xiaomi_tv")

SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_ST = "urn:schemas-upnp-org:device:MediaRenderer:1"
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
    payload = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
        "MAN: \"ssdp:discover\"\r\n"
        f"MX: {max(1, int(timeout_sec))}\r\n"
        f"ST: {SSDP_ST}\r\n"
        "\r\n"
    ).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    locations: list[str] = []
    seen: set[str] = set()
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout_sec)
        sock.sendto(payload, SSDP_ADDR)
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                data, _addr = sock.recvfrom(4096)
            except socket.timeout:
                break
            text = data.decode("utf-8", errors="replace")
            for line in text.splitlines():
                if line.lower().startswith("location:"):
                    loc = line.split(":", 1)[1].strip()
                    if loc and loc not in seen:
                        seen.add(loc)
                        locations.append(loc)
    except OSError as e:
        raise XiaomiTvError(f"投电视失败：SSDP 发现失败（{e}）。") from e
    finally:
        sock.close()
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


def discover_renderer(
    *,
    search_fn: Callable[[], list[str]] | None = None,
    fetch_fn: Callable[[str], str] | None = None,
    timeout_sec: float = 5.0,
) -> dict[str, str]:
    search = search_fn or (lambda: _ssdp_search(min(timeout_sec, 3.0)))
    locations = search()
    if not locations:
        raise XiaomiTvError(
            "投电视失败：局域网里没有发现 DLNA 电视。请打开小米电视投屏/DLNA，"
            "或设置 MAC_EDGE_XIAOMI_TV_HOST。"
        )
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
    candidates: list[dict[str, str]] = []
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
        if _wanted_name() or not _wanted_host():
            if not _name_matches(parsed["friendly_name"]) and not _wanted_host():
                continue
        if _wanted_name() and not _name_matches(parsed["friendly_name"]):
            continue
        candidates.append(parsed)
    if not candidates:
        raise XiaomiTvError(
            "投电视失败：发现了 DLNA 设备，但没有匹配的小米电视。"
            "请设置 MAC_EDGE_XIAOMI_TV_NAME 或 HOST。"
        )
    chosen = candidates[0]
    log.info(
        "xiaomi tv renderer name=%s control=%s",
        chosen.get("friendly_name"),
        chosen.get("control_url"),
    )
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
