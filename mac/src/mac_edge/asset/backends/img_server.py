"""Resolve img-server storage locators to HTTP URLs."""

from __future__ import annotations

import json
import logging
import os
import re
import select
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from mac_edge.asset.types import AssetStorageError, HttpUrlRepresentation

log = logging.getLogger("mac_edge.asset.img_server")

# ---------------------------------------------------------------------------
# 资源服务器（img-server / home-asset-hub）的端口从哪来
#
# 「端口由服务自己决定」：asset-hub 的 ASSET_HUB_PORT（默认 8080）就是权威，
# Edge 不该硬编码它。解析顺序（每层都过 /health 自校验）：
#
#   1. MAC_EDGE_IMG_SERVER_PORT（显式配置永远赢）
#   2. 端点文件：服务启动时自己写的 <runtime>/backend/endpoint.json（确定性、零延迟）
#   3. mDNS `_ha-img-server._tcp`（跨设备兜底；实测本机 dns-sd 不稳，所以放在文件后面）
#   4. 已验证缓存 → 8080（= 现网行为，永远退得回去）
#
# 缓存/负缓存是必须的：上传在请求路径上，不能每次上传都去等 Bonjour。
# ---------------------------------------------------------------------------

IMG_SERVER_SERVICE = "home-asset-hub"
IMG_SERVER_SERVICE_TYPE = "_ha-img-server._tcp"
IMG_SERVER_INSTANCE = "Home Agent img-server"
DEFAULT_IMG_SERVER_PORT = 8080
IMG_SERVER_NEGATIVE_TTL = 15.0

_state: dict[str, Any] = {"at": 0.0, "port": 0, "checked_at": 0.0}
_endpoint_cache: dict[str, Any] = {"path": "", "mtime": 0.0, "data": None}
_lock = threading.Lock()


def img_server_endpoint_candidates() -> list[Path]:
    """端点文件候选路径（按可信度排序）。"""
    out: list[Path] = []
    explicit = (os.environ.get("ASSET_HUB_ENDPOINT_FILE") or "").strip()
    if explicit:
        out.append(Path(explicit))
    disc = (os.environ.get("ASSET_HUB_DISCOVERY_DIR") or "").strip()
    if disc:
        out.append(Path(disc) / f"{IMG_SERVER_SERVICE}.json")
    rt = (os.environ.get("RUNTIME_DIR") or "").strip()
    runtime_root = str(Path(rt).resolve().parent) if rt else str(Path.home() / "runtime")
    out.append(Path(runtime_root) / ".discovery" / f"{IMG_SERVER_SERVICE}.json")
    out.append(Path(runtime_root) / IMG_SERVER_SERVICE / "backend" / "endpoint.json")
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def read_img_server_endpoint() -> dict[str, Any] | None:
    """读端点文件（第一层）：{port, public_base, health_path, ...}；没有返回 None（按 mtime 缓存）。"""
    for path in img_server_endpoint_candidates():
        try:
            stat = path.stat()
        except OSError:
            continue
        with _lock:
            if _endpoint_cache["path"] == str(path) and float(_endpoint_cache["mtime"]) == stat.st_mtime:
                data = _endpoint_cache["data"]
                if isinstance(data, dict):
                    return data
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        try:
            port = int(data.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if port <= 0:
            continue
        with _lock:
            _endpoint_cache.update({"path": str(path), "mtime": stat.st_mtime, "data": data})
        return data
    return None


def _parse_dns_sd_lookup(line: str) -> int | None:
    """解析 `dns-sd -L` 的一行 → 端口。纯函数。

    行尾可能有 `Flags: 1` 这种带冒号的尾巴，所以取「reached at」后的第一个 token 再切 host:port。
    """
    if " can be reached at " not in line:
        return None
    _left, _, right = line.partition(" can be reached at ")
    parts = right.split()
    if not parts:
        return None
    _host, sep, port_s = parts[0].rpartition(":")
    if not sep:
        return None
    try:
        port = int(port_s)
    except ValueError:
        return None
    return port if port > 0 else None


def _lookup_port_via_dns_sd(timeout: float = 1.5) -> int | None:
    """按已知名字 `dns-sd -L` 查端口。

    坑：`dns-sd -L` 命中后**不会自己退出**（subprocess.run 会等超时、并把已读到的输出一起丢掉），
    所以用 Popen 边读边判，拿到答案立刻收工。
    """
    try:
        proc = subprocess.Popen(
            ["dns-sd", "-L", IMG_SERVER_INSTANCE, IMG_SERVER_SERVICE_TYPE, ".", "-t", str(int(max(1, timeout)))],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return None
    deadline = time.time() + max(0.5, timeout) + 0.5
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0 or proc.stdout is None:
                return None
            try:
                ready, _, _ = select.select([proc.stdout], [], [], remaining)
            except Exception:
                return None
            if not ready:
                return None
            line = proc.stdout.readline()
            if not line:
                return None
            port = _parse_dns_sd_lookup(line)
            if port:
                return port
    finally:
        try:
            proc.kill()
            proc.wait(timeout=1)
        except Exception:
            pass


def _health_ok(port: int, timeout: float = 0.6) -> bool:
    """自校验：端点/mDNS 可能过期，先问一句 /health 再采信。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/health", timeout=timeout) as resp:
            if int(getattr(resp, "status", 0) or resp.getcode() or 0) != 200:
                return False
            raw = resp.read().decode("utf-8", "replace")
        data = json.loads(raw) if raw.strip() else {}
        return isinstance(data, dict) and bool(
            data.get("ok") is True or data.get("service") in (IMG_SERVER_SERVICE, "img-server")
        )
    except Exception:
        return False


def resolve_img_server_port(
    default: int = DEFAULT_IMG_SERVER_PORT,
    *,
    ttl: float = 60.0,
    timeout: float = 1.5,
    verify: bool = True,
    blocking: bool | None = None,
) -> int:
    """发现资源服务器端口（永不抛异常，失败即回退 default=8080）。"""
    explicit = (os.environ.get("MAC_EDGE_IMG_SERVER_PORT") or "").strip()
    if explicit.isdigit() and int(explicit) > 0:
        return int(explicit)
    now = time.time()
    with _lock:
        port = int(_state.get("port") or 0)
        at = float(_state.get("at") or 0.0)
        checked_at = float(_state.get("checked_at") or 0.0)
    if port and (now - at) < ttl:
        return port
    if (now - checked_at) < IMG_SERVER_NEGATIVE_TTL:
        return port or int(default)
    if blocking is None:
        blocking = checked_at <= 0.0

    def _probe() -> int:
        endpoint = read_img_server_endpoint()
        candidate = int(endpoint["port"]) if endpoint else 0
        if not candidate:
            candidate = _lookup_port_via_dns_sd(timeout=timeout) or 0
        ok = bool(candidate) and (not verify or _health_ok(candidate))
        with _lock:
            _state["checked_at"] = time.time()
            if ok:
                _state.update({"at": time.time(), "port": candidate})
        if candidate and not ok:
            log.warning("img-server 发现到端口 %s 但 /health 自校验失败，忽略", candidate)
        return candidate if ok else 0

    if blocking:
        found = _probe()
        with _lock:
            return found or int(_state.get("port") or 0) or int(default)

    # 非阻塞：先用旧值/默认值，后台刷新下一次生效（上传路径不被 Bonjour 挡住）
    def _bg() -> None:
        try:
            _probe()
        except Exception:  # pragma: no cover - 后台线程不该影响主流程
            log.debug("img-server background discovery failed", exc_info=True)

    threading.Thread(target=_bg, name="img-server-port-refresh", daemon=True).start()
    return port or int(default)


def img_server_port() -> int:
    """当前应使用的资源服务器端口（发现 → 已验证缓存 → 8080）。"""
    return resolve_img_server_port()



def detect_lan_ipv4() -> str:
    """Primary LAN IPv4 of this host — no hardcoded home-LAN IP.

    1. UDP "connect" picks the interface used for the default route (no packets
       are actually sent).
    2. If there is no default route, enumerate hostname-resolved IPv4 addresses
       and keep the first non-loopback one.
    3. Last resort is loopback — still better than a stale fixed LAN IP.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        try:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
        finally:
            sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    try:
        # macOS / Linux: enumerate every interface so a DHCP re-lease on an
        # interface that hostname does not resolve is still discovered.
        import subprocess

        out = subprocess.run(
            ["ifconfig"], capture_output=True, text=True, timeout=3.0
        )
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("inet "):
                continue
            ip = line.split()[1].split("%", 1)[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def default_lan_public_base(port: int | None = None) -> str:
    """LAN URL of this host's img-server (the address other devices fetch).

    port=None → 走发现（端点文件 → mDNS → 已验证缓存 → 8080）：asset-hub 换端口这一处，
    给电视/小度的地址自动跟着换。
    """
    return f"http://{detect_lan_ipv4()}:{int(port) if port else img_server_port()}"


# Backward-compatible name. 注意：**导入期不做发现**（import 不该有 IO/子进程），
# 这里只给「默认端口的 LAN 地址」形态；运行时请用 default_lan_public_base()（会走发现）。
DEFAULT_LAN_PUBLIC_BASE = f"http://{detect_lan_ipv4()}:{DEFAULT_IMG_SERVER_PORT}"


def lan_facing_brain_base(brain_base_url: str) -> str:
    """TV/DLNA cannot fetch 127.0.0.1; rewrite Brain loopback to the LAN host."""
    explicit = (os.environ.get("MAC_EDGE_BRAIN_LAN_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    raw = (brain_base_url or "").strip()
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    host = (parsed.hostname or "").strip().lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return raw.rstrip("/")
    lan = (os.environ.get("MAC_EDGE_LAN_PUBLIC_BASE") or default_lan_public_base()).strip()
    lan_parsed = urlparse(lan if "://" in lan else f"http://{lan}")
    lan_host = lan_parsed.hostname or detect_lan_ipv4()
    port = parsed.port or 9527
    scheme = parsed.scheme or "http"
    return f"{scheme}://{lan_host}:{port}"


def brain_content_http_url(brain_base_url: str, asset_id: str, intent_id: str) -> str:
    aid = str(asset_id or "").strip()
    iid = str(intent_id or "").strip()
    if not aid or not iid:
        raise AssetStorageError("brain content url requires asset_id and intent_id")
    base = lan_facing_brain_base(brain_base_url)
    return f"{base}/api/v1/assets/{aid}/content?intent_id={iid}&representation=original"


def _lan_public_base() -> str:
    raw = (os.environ.get("MAC_EDGE_LAN_PUBLIC_BASE") or default_lan_public_base()).strip()
    return raw.rstrip("/")


def _is_private_lan_base(base: str) -> bool:
    """True when base points at a loopback / RFC1918 private-LAN host.

    img-server's LAN IP is DHCP-assigned, so a stored private-LAN public_base
    may be stale (e.g. an old .x from a previous re-lease). Public/cloud hosts
    are stable and not subject to this.
    """
    try:
        host = (urlparse(base).hostname or "").strip().lower()
    except Exception:
        return False
    if host in ("localhost", "::1", "127.0.0.1"):
        return True
    return bool(re.match(r"^(10\.|192\.168\.|127\.|172\.(1[6-9]|2\d|3[01])\.)", host))


def _pick_base(storage: dict[str, Any], *, prefer_cloud: bool) -> str:
    pub = str(storage.get("public_base") or "").strip().rstrip("/")
    cloud = str(storage.get("cloud_public_base") or "").strip().rstrip("/")
    if prefer_cloud and cloud:
        return cloud
    # A stored non-private (public/cloud) base is stable — keep using it.
    if pub and not _is_private_lan_base(pub):
        return pub
    # A stored private-LAN/loopback public_base is DHCP-volatile and may be
    # stale; resolve the CURRENT LAN base at use time for the co-located
    # img-server (cloud mirror is kept as a fallback).
    if pub:
        return _lan_public_base() or cloud or pub
    # No stored public_base: prefer the cloud mirror if present, else the
    # current LAN base (co-located img-server).
    return cloud or _lan_public_base()


def _locator_candidates(storage: dict[str, Any]) -> list[tuple[str, str]]:
    """(base, key) pairs: original first, then preview / cloud variants."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(*, prefer_cloud: bool, key: str) -> None:
        k = (key or "").strip()
        if not k:
            return
        base = _pick_base(storage, prefer_cloud=prefer_cloud)
        pair = (base, k)
        if pair not in seen:
            seen.add(pair)
            out.append(pair)

    # Original (prefer), then preview fallback — covers P0 preview-first register.
    add(prefer_cloud=False, key=str(storage.get("key") or storage.get("saved_as") or ""))
    add(prefer_cloud=True, key=str(storage.get("cloud_key") or ""))
    add(prefer_cloud=False, key=str(storage.get("preview_key") or ""))
    add(prefer_cloud=True, key=str(storage.get("cloud_preview_key") or ""))
    return out


def _url_path_for_storage_key(key: str) -> str:
    """Percent-encode path segments so non-ASCII filenames are valid HTTP URLs."""
    parts = [p for p in str(key or "").strip().lstrip("/").split("/") if p]
    return "/" + "/".join(quote(p, safe="") for p in parts)


def http_url_from_storage(storage: dict[str, Any]) -> HttpUrlRepresentation:
    backend = str(storage.get("backend") or storage.get("provider") or "").strip()
    if backend and backend not in ("img_server", "local", "lan"):
        raise AssetStorageError(f"unsupported storage backend: {backend}")
    candidates = _locator_candidates(storage)
    if not candidates:
        raise AssetStorageError("img_server storage missing key")
    base, key = candidates[0]
    k = str(key or "").strip()
    if k.startswith("http://") or k.startswith("https://"):
        url = k
    else:
        url = f"{base.rstrip('/')}{_url_path_for_storage_key(k)}"
    if not url.startswith("http://") and not url.startswith("https://"):
        raise AssetStorageError(f"refusing non-http url: {url}")
    return HttpUrlRepresentation(url=url, expires_at_ms=None)
