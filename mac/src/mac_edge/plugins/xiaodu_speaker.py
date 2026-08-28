"""Xiaodu speaker: edge-tts MP3 over LAN HTTP + UPnP AVTransport play."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

log = logging.getLogger("mac_edge.xiaodu_speaker")

DEFAULT_HTTP_PORT = 8000
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
UPNP_CONTROL_PATH = "/upnp/control/rendertransport1"
UPNP_PORT = 49494

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
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def xiaodu_ip() -> str:
    return (os.environ.get("MAC_EDGE_XIAODU_IP") or "").strip()


def xiaodu_configured() -> bool:
    return bool(xiaodu_ip())


def default_voice() -> str:
    return (os.environ.get("MAC_EDGE_XIAODU_VOICE") or DEFAULT_VOICE).strip() or DEFAULT_VOICE


def public_host() -> str:
    override = (os.environ.get("MAC_EDGE_XIAODU_PUBLIC_HOST") or "").strip()
    return override or lan_ip()


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


def _upnp_post(du_ip: str, soap_action: str, xml_body: str, *, timeout_sec: float = 8.0) -> None:
    url = f"http://{du_ip}:{UPNP_PORT}{UPNP_CONTROL_PATH}"
    req = urllib.request.Request(
        url,
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


def play_uri(du_ip: str, uri: str) -> None:
    _upnp_post(du_ip, "urn:schemas-upnp-org:service:AVTransport:1#Stop", _STOP_XML)
    _upnp_post(
        du_ip,
        "urn:schemas-upnp-org:service:AVTransport:1#SetAVTransportURI",
        _set_uri_xml(uri),
    )
    _upnp_post(du_ip, "urn:schemas-upnp-org:service:AVTransport:1#Play", _PLAY_XML)


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
            log.info("xiaodu.speaker off (MAC_EDGE_XIAODU_IP unset)")
            return None
        port = int(os.environ.get("MAC_EDGE_XIAODU_HTTP_PORT") or DEFAULT_HTTP_PORT)
        return cls(data_dir=data_dir, http_port=port)

    def public_url(self, filename: str) -> str:
        host = public_host()
        port = self.http_port
        if self._httpd is not None:
            port = int(self._httpd.server_address[1])
        return f"http://{host}:{port}/{filename}"

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
    device_ip = (du_ip or xiaodu_ip()).strip()
    if not device_ip:
        raise XiaoduSpeakerError("MAC_EDGE_XIAODU_IP not configured")

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

    uri = server.public_url(fname)
    log.info("xiaodu.speak uri=%s text=%r", uri, body[:80])
    play_uri(device_ip, uri)
    preview = body if len(body) <= 40 else body[:40] + "…"
    return f"xiaodu spoke: {preview}"


def speak_from_params(params: dict[str, Any]) -> str:
    text = str(params.get("text") or "").strip()
    voice = str(params.get("voice") or "").strip() or None
    return speak(text, voice=voice)
