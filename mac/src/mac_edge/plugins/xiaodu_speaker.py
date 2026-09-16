"""Xiaodu speaker: edge-tts MP3 over LAN HTTP + UPnP AVTransport play."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mac_edge.plugins import lan_discovery as lan

log = logging.getLogger("mac_edge.xiaodu_speaker")

DEFAULT_HTTP_PORT = 8000
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
UPNP_CONTROL_PATH = "/upnp/control/rendertransport1"
UPNP_PORT = 49494
UPNP_TIMEOUT_SEC = 8.0
UPNP_STOP_TIMEOUT_SEC = 2.5

_STOP_XML = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding">'
    "<s:Body>"
    '<u:Stop xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
    "<InstanceID>0</InstanceID>"
    "</u:Stop>"
    "</s:Body></s:Envelope>"
)
_PLAY_XML = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding">'
    "<s:Body>"
    '<u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
    "<InstanceID>0</InstanceID><Speed>1</Speed>"
    "</u:Play>"
    "</s:Body></s:Envelope>"
)

_server: XiaoduTtsHttpServer | None = None
_server_lock = threading.Lock()


class XiaoduSpeakerError(Exception):
    pass


def lan_ip() -> str:
    """本机默认路由出口地址（保留旧 API；按设备探测用 `public_host(device_ip)`）。"""
    return lan.lan_host_fallback()


def xiaodu_ip() -> str:
    """显式覆盖：env `MAC_EDGE_XIAODU_IP`（可选，不再是必需项）。"""
    return (os.environ.get("MAC_EDGE_XIAODU_IP") or "").strip()


def xiaodu_name() -> str:
    """显式指定哪台小度：env `MAC_EDGE_XIAODU_NAME`（家里多台时用，子串匹配）。"""
    return (os.environ.get("MAC_EDGE_XIAODU_NAME") or "").strip()


def xiaodu_disabled() -> bool:
    raw = (os.environ.get("MAC_EDGE_XIAODU") or "").strip().lower()
    return raw in ("0", "off", "false", "no")


def discovery_enabled() -> bool:
    """SSDP 探测开关：env `MAC_EDGE_XIAODU_DISCOVER`（默认开；=0 则只认 env/缓存）。"""
    raw = (os.environ.get("MAC_EDGE_XIAODU_DISCOVER") or "").strip().lower()
    return raw not in ("0", "off", "false", "no")


def _cache_path() -> Path:
    """探测结果落盘位置：env 覆盖 > MAC_EDGE_DATA_DIR > mac/data（本插件在 mac/src/mac_edge/plugins/）。"""
    override = (os.environ.get("MAC_EDGE_XIAODU_CACHE") or "").strip()
    if override:
        return Path(override).expanduser()
    root = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if root:
        return Path(root).expanduser() / "xiaodu_renderer.json"
    return Path(__file__).resolve().parents[3] / "data" / "xiaodu_renderer.json"


@dataclass(frozen=True)
class XiaoduDevice:
    """一台可控制的小度音箱（地址是**探测**出来的）。"""

    ip: str
    control_url: str = ""
    friendly_name: str = ""
    location: str = ""
    source: str = "discovered"  # override / cache / discovered

    def describe(self) -> str:
        name = self.friendly_name or "(unknown)"
        via = f" via {self.control_url}" if self.control_url else ""
        return f"{name} @ {self.ip} [{self.source}]{via}"


def _legacy_control_url(ip: str) -> str:
    """只拿到 IP 时按老路径拼控制地址（DuerOS 默认端口/路径）。"""
    return f"http://{ip}:{UPNP_PORT}{UPNP_CONTROL_PATH}"


def _matches_xiaodu(desc: lan.DeviceDescription) -> bool:
    """小度识别：`MAC_EDGE_XIAODU_NAME` 指定则按名匹配；否则 DuerOS 厂牌或名字含小度。"""
    wanted = xiaodu_name()
    identity = desc.identity_text()
    if wanted:
        return wanted.casefold() in identity
    tokens = ("dueros", "小度", "xiaodu", "duer")
    return any(token in identity for token in tokens)


def _device_from_description(desc: lan.DeviceDescription, *, source: str) -> XiaoduDevice:
    return XiaoduDevice(
        ip=desc.ip or str(urlparse(desc.location).hostname or ""),
        control_url=desc.control_url(),
        friendly_name=desc.friendly_name,
        location=desc.location,
        source=source,
    )


def default_voice() -> str:
    return (os.environ.get("MAC_EDGE_XIAODU_VOICE") or DEFAULT_VOICE).strip() or DEFAULT_VOICE


def public_host(device_ip: str | None = None) -> str:
    """小度能访问到的**本机**地址：按目标设备探测；env 只在确实是本机网卡地址时才采信。"""
    return lan.resolve_public_host(
        device_ip, (os.environ.get("MAC_EDGE_XIAODU_PUBLIC_HOST") or "").strip(), what="小度"
    )


def _set_uri_xml(uri: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding">'
        "<s:Body>"
        '<u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
        "<InstanceID>0</InstanceID>"
        f"<CurrentURI>{uri}</CurrentURI>"
        "<CurrentURIMetaData></CurrentURIMetaData>"
        "</u:SetAVTransportURI>"
        "</s:Body></s:Envelope>"
    )


def discover_xiaodu(
    *, timeout_sec: float = lan.DEFAULT_SSDP_TIMEOUT_SEC, rounds: int = 2, probe: bool = True
) -> XiaoduDevice | None:
    """SSDP 现场探测小度：发现 → 拉描述 → 认身份 → 探活（`GetTransportInfo`）。

    探活失败的设备不采信（同网段可能躺着别的 DuerOS 设备或休眠设备）。
    没有小度 → None；组播本身发不出去 → 记 warn 并返回 None（调用方给出明确中文失败）。
    """
    try:
        responses = lan.ssdp_search(timeout_sec=timeout_sec, rounds=rounds)
    except lan.LanDiscoveryError as e:
        log.warning("SSDP 探测失败：%s", e)
        return None
    for resp in responses:
        if not resp.location:
            continue
        try:
            desc = lan.fetch_device_description(resp.location, timeout_sec=timeout_sec)
        except lan.LanDiscoveryError as e:
            log.info("跳过 %s：%s", resp.location, e)
            continue
        if not _matches_xiaodu(desc):
            continue
        if probe and not lan.probe_av_transport(desc.control_url(), timeout_sec=timeout_sec):
            log.info("跳过 %s（%s）：AVTransport 探活失败", resp.location, desc.friendly_name)
            continue
        device = _device_from_description(desc, source="discovered")
        log.info("xiaodu 探测到 %s", device.describe())
        return device
    return None


def _load_cached_device(*, probe: bool = True) -> XiaoduDevice | None:
    """缓存命中的前提是**现在还能探通**：拉一次描述 + 探活，失败即丢缓存。"""
    path = _cache_path()
    data = lan.read_cache(path)
    if not data:
        return None
    location = str(data.get("location") or "").strip()
    ip = str(data.get("ip") or "").strip()
    if not location and not ip:
        return None
    if not location:  # 只有 IP 的老缓存：按老路径用，不额外探测
        device = XiaoduDevice(ip=ip, control_url="", source="cache")
        log.info("xiaodu 用缓存 %s", device.describe())
        return device
    try:
        desc = lan.fetch_device_description(location)
    except lan.LanDiscoveryError as e:
        log.info("小度缓存已失效（%s）：%s", location, e)
        lan.drop_cache(path)
        return None
    if not _matches_xiaodu(desc):
        log.info("小度缓存身份不匹配（%s）—— 丢弃", desc.friendly_name)
        lan.drop_cache(path)
        return None
    control_url = desc.control_url()
    if probe and not lan.probe_av_transport(control_url):
        log.info("小度缓存探活失败（%s）—— 丢弃", location)
        lan.drop_cache(path)
        return None
    device = XiaoduDevice(
        ip=desc.ip or ip,
        control_url=control_url,
        friendly_name=desc.friendly_name or str(data.get("friendly_name") or ""),
        location=location,
        source="cache",
    )
    log.info("xiaodu 用缓存 %s", device.describe())
    return device


def _remember_device(device: XiaoduDevice) -> None:
    lan.write_cache(
        _cache_path(),
        {
            "ip": device.ip,
            "control_url": device.control_url,
            "friendly_name": device.friendly_name,
            "location": device.location,
            "source": device.source,
        },
    )


def resolve_device(
    *,
    override_ip: str | None = None,
    use_cache: bool = True,
    use_discovery: bool = True,
    probe: bool = True,
) -> XiaoduDevice:
    """地址解析顺序：显式覆盖 → 缓存（探活）→ SSDP 探测 → 明确中文失败。

    显式覆盖（参数或 `MAC_EDGE_XIAODU_IP`）视为「用户说了算」，不再探测。
    """
    explicit = str(override_ip or "").strip() or xiaodu_ip()
    if explicit:
        return XiaoduDevice(ip=explicit, control_url="", source="override")
    if use_cache:
        cached = _load_cached_device(probe=probe)
        if cached is not None:
            return cached
    if use_discovery and discovery_enabled():
        found = discover_xiaodu(probe=probe)
        if found is not None:
            _remember_device(found)
            return found
    raise XiaoduSpeakerError(
        "没有找到小度音箱：SSDP 没探测到可控制的小度（确认音箱在线、与 Mac 同一网段；"
        "多台可设 MAC_EDGE_XIAODU_NAME，或直接给 MAC_EDGE_XIAODU_IP）"
    )


def xiaodu_configured() -> bool:
    """是否向 Brain 广告本能力：显式关闭 → 否；有覆盖 / 有缓存 / 现场探测到 → 是。"""
    if xiaodu_disabled():
        return False
    if xiaodu_ip() or lan.read_cache(_cache_path()):
        return True
    if not discovery_enabled():
        return False
    return discover_xiaodu(timeout_sec=1.5, rounds=1, probe=False) is not None
    return (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding">'
        "<s:Body>"
        '<u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
        "<InstanceID>0</InstanceID>"
        f"<CurrentURI>{uri}</CurrentURI>"
        "<CurrentURIMetaData></CurrentURIMetaData>"
        "</u:SetAVTransportURI>"
        "</s:Body></s:Envelope>"
    )


def _upnp_post_url(
    control_url: str,
    soap_action: str,
    xml_body: str,
    *,
    timeout_sec: float = UPNP_TIMEOUT_SEC,
) -> None:
    req = urllib.request.Request(
        control_url,
        data=xml_body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPACTION": f'"{soap_action}"',
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            resp.read()
    except urllib.error.URLError as e:
        raise XiaoduSpeakerError(f"UPnP request failed ({soap_action}): {e}") from e


def _upnp_post(
    du_ip: str,
    soap_action: str,
    xml_body: str,
    *,
    timeout_sec: float = UPNP_TIMEOUT_SEC,
) -> None:
    """按「只给了 IP」的老式路径发 UPnP（兼容旧调用与旧配置）。"""
    _upnp_post_url(
        _legacy_control_url(du_ip), soap_action, xml_body, timeout_sec=timeout_sec
    )


def _try_upnp_stop(device: XiaoduDevice) -> None:
    """Best-effort Stop before a new URI. Idle speakers often hang on Stop."""
    try:
        _post(device, "urn:schemas-upnp-org:service:AVTransport:1#Stop", _STOP_XML,
              timeout_sec=UPNP_STOP_TIMEOUT_SEC)
    except XiaoduSpeakerError as e:
        log.warning("xiaodu UPnP Stop best-effort failed (continuing): %s", e)


def _post(
    device: XiaoduDevice,
    soap_action: str,
    xml_body: str,
    *,
    timeout_sec: float = UPNP_TIMEOUT_SEC,
) -> None:
    """发 UPnP 控制：探测到的设备用描述里的控制地址，只有 IP 的老式配置走老路径。"""
    if device.control_url:
        _upnp_post_url(device.control_url, soap_action, xml_body, timeout_sec=timeout_sec)
    else:
        _upnp_post(device.ip, soap_action, xml_body, timeout_sec=timeout_sec)


def play_uri(du_ip: str, uri: str, *, control_url: str | None = None) -> None:
    """把 uri 交给小度播（老签名：给 IP 就行；有探测到的 control_url 时用它）。"""
    device = XiaoduDevice(ip=str(du_ip), control_url=str(control_url or ""), source="explicit")
    _try_upnp_stop(device)
    _post(device, "urn:schemas-upnp-org:service:AVTransport:1#SetAVTransportURI", _set_uri_xml(uri))
    _post(device, "urn:schemas-upnp-org:service:AVTransport:1#Play", _PLAY_XML)


def play_device(device: XiaoduDevice, uri: str) -> None:
    """按探测到的设备播放（地址/控制路径都来自探测）。"""
    play_uri(device.ip, uri, control_url=device.control_url)


class _TtsFileHandler(BaseHTTPRequestHandler):
    serve_dir: Path

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("xiaodu-tts http " + fmt, *args)

    def do_GET(self) -> None:
        name = (self.path or "/").split("?", 1)[0].lstrip("/")
        if not name or ".." in name or "/" in name:
            self.send_error(404)
            return
        path = self.serve_dir / name
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class XiaoduTtsHttpServer:
    def __init__(
        self,
        *,
        data_dir: Path,
        http_host: str = "0.0.0.0",
        http_port: int = DEFAULT_HTTP_PORT,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.serve_dir = self.data_dir / "xiaodu-tts"
        self.serve_dir.mkdir(parents=True, exist_ok=True)
        self.http_host = http_host
        self.http_port = int(http_port)
        self._httpd: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None

    @classmethod
    def from_env(cls, data_dir: Path) -> XiaoduTtsHttpServer | None:
        if not xiaodu_configured():
            log.info("xiaodu.speaker off（没探测到小度，也没有 MAC_EDGE_XIAODU_IP）")
            return None
        port = int(os.environ.get("MAC_EDGE_XIAODU_HTTP_PORT") or DEFAULT_HTTP_PORT)
        return cls(data_dir=data_dir, http_port=port)

    def public_url(self, filename: str, *, host: str | None = None) -> str:
        """小度拉流地址；host 缺省按默认路由探测（有具体设备时传 `public_host(device.ip)`）。"""
        use_host = str(host or "").strip() or public_host()
        port = self.http_port
        if self._httpd is not None:
            port = int(self._httpd.server_address[1])
        return f"http://{use_host}:{port}/{filename}"

    def start(self) -> None:
        handler = type(
            "XiaoduTtsHandler",
            (_TtsFileHandler,),
            {"serve_dir": self.serve_dir},
        )
        httpd = ThreadingHTTPServer((self.http_host, self.http_port), handler)
        self.http_port = int(httpd.server_address[1])
        self._httpd = httpd
        self._http_thread = threading.Thread(
            target=httpd.serve_forever,
            name="xiaodu-tts-http",
            daemon=True,
        )
        self._http_thread.start()
        log.info(
            "xiaodu-tts http://%s:%s dir=%s public_host=%s",
            self.http_host,
            self.http_port,
            self.serve_dir,
            public_host(),
        )

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def bind_server(server: XiaoduTtsHttpServer | None) -> None:
    global _server
    with _server_lock:
        _server = server


def get_server() -> XiaoduTtsHttpServer:
    with _server_lock:
        if _server is None:
            raise XiaoduSpeakerError("xiaodu TTS HTTP server not running")
        return _server


async def _synthesize(text: str, voice: str, path: Path) -> None:
    try:
        import edge_tts  # type: ignore
    except ImportError as e:
        raise XiaoduSpeakerError("edge-tts not installed (pip install edge-tts)") from e
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(path))


def speak(text: str, *, voice: str | None = None, du_ip: str | None = None) -> str:
    body = (text or "").strip()
    if not body:
        raise XiaoduSpeakerError("text is required")

    device = resolve_device(override_ip=du_ip)

    server = get_server()
    voice_name = (voice or default_voice()).strip() or DEFAULT_VOICE
    ts = int(time.time())
    fname = f"tts_{ts}.mp3"
    out_path = server.serve_dir / fname

    try:
        asyncio.run(_synthesize(body, voice_name, out_path))
    except Exception as e:
        raise XiaoduSpeakerError(f"edge-tts failed: {e}") from e
    if not out_path.is_file() or out_path.stat().st_size < 64:
        raise XiaoduSpeakerError("edge-tts returned empty audio")

    uri = server.public_url(fname, host=public_host(device.ip))
    log.info("xiaodu.speak uri=%s device=%s text=%r", uri, device.describe(), body[:80])
    try:
        play_device(device, uri)
    except XiaoduSpeakerError as e:
        if device.source == "override":
            raise
        # 播放失败常见于「音箱换了 IP / 控制地址变了」：丢缓存重新探测后重试一次
        log.warning("xiaodu 播放失败（%s）—— 重新探测后重试：%s", device.source, e)
        lan.drop_cache(_cache_path())
        retry = resolve_device(use_cache=False)
        retry_uri = server.public_url(fname, host=public_host(retry.ip))
        play_device(retry, retry_uri)
        log.info("xiaodu 重新探测后播放成功 device=%s", retry.describe())
    preview = body if len(body) <= 40 else body[:40] + "…"
    return f"xiaodu spoke: {preview}"


def speak_from_params(params: dict[str, Any]) -> str:
    text = str(params.get("text") or "").strip()
    voice = str(params.get("voice") or "").strip() or None
    return speak(text, voice=voice)
