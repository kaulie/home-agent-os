"""Shared mDNS / Bonjour publish + discover for Home Agent LAN services.

Single source of the well-known service types (see
agent_plans/service_discovery_mdns_migration_v1.md):

  _home-agent-brain._tcp         Brain (server/home_brain.py)        :9527
  _home-agent-gateway._tcp       mac_edge gateway (voice/video rx)   TXT ports
  _home-agent-runtime._tcp       mac_edge runtime identity
  _home-agent-img-server._tcp    img-server (img-server/serve.py)    :8080

Backend selection at import:
  1. python-zeroconf  - if importable (mac venv has it)
  2. macOS `dns-sd` CLI - zero-dependency fallback (Brain / img-server run on macOS)

Publishing (keep the returned Publisher alive for the process lifetime)::

    pub = mdns_service.publish_service(
        name="Home Agent Brain",
        type_=mdns_service.BRAIN_TYPE,
        port=9527,
        txt={"role": "brain"},
        hostname="brain.local",
    )
    ...
    pub.close()  # optional; also closed by GC / process exit

Discovering::

    for svc in mdns_service.discover_service(mdns_service.BRAIN_TYPE, timeout=3):
        host, port = svc["host"], svc["port"]
"""

from __future__ import annotations

import json
import logging
import select
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("mdns_service")

# NOTE: mDNS service-type labels must be <= 15 bytes (RFC 6763 §7.1), so the
# contract's `_home-agent-gateway._tcp` / `_home-agent-runtime._tcp` names are
# NOT spec-compliant (17 chars). We use the compact `_ha-*` prefix instead;
# `brain.local`/`gateway.local` hostnames are unaffected.
BRAIN_TYPE = "_ha-brain._tcp"
GATEWAY_TYPE = "_ha-gateway._tcp"
RUNTIME_TYPE = "_ha-runtime._tcp"
IMG_SERVER_TYPE = "_ha-img-server._tcp"

try:
    import zeroconf  # type: ignore[import-untyped]

    HAS_ZEROCONF = True
except Exception:  # pragma: no cover - depends on environment
    HAS_ZEROCONF = False


def lan_ipv4() -> str:
    """Primary LAN IPv4 of this host — never a hardcoded home-LAN IP.

    1. UDP "connect" picks the interface used for the default route (no packets
       are actually sent).
    2. Without a default route, fall back to hostname-resolved IPv4 addresses.
    3. Last resort is loopback.
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


def _encode_txt(txt: dict[str, Any] | None) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for key, value in (txt or {}).items():
        if isinstance(value, bool):
            value = "1" if value else "0"
        out[str(key)] = str(value).encode("utf-8")
    return out


def _fq_type(type_: str) -> str:
    """Fully-qualified mDNS type (``_x._tcp.local.``) accepted by python-zeroconf."""
    return type_ if type_.endswith(".local.") else type_ + ".local."

class MdnsPublisher:
    """Publishes one or more mDNS services for the process lifetime."""

    def __init__(self) -> None:
        self._zc: Any = None
        self._infos: list[Any] = []
        self._procs: list[subprocess.Popen[bytes]] = []

    def publish(
        self,
        *,
        name: str,
        type_: str,
        port: int,
        txt: dict[str, Any] | None = None,
        hostname: str | None = None,
    ) -> None:
        merged = dict(txt or {})
        merged.setdefault("lan_ip", lan_ipv4())
        if HAS_ZEROCONF:
            self._publish_zeroconf(name, type_, port, merged, hostname)
        else:
            self._publish_dns_sd(name, type_, port, merged)

    def _publish_zeroconf(
        self,
        name: str,
        type_: str,
        port: int,
        txt: dict[str, Any] | None,
        hostname: str | None,
    ) -> None:
        if self._zc is None:
            self._zc = zeroconf.Zeroconf()
        fq_type = _fq_type(type_)
        info = zeroconf.ServiceInfo(
            fq_type,
            f"{name}.{fq_type}",
            addresses=[socket.inet_aton(lan_ipv4())],
            port=int(port),
            properties=_encode_txt(txt),
            server=(f"{hostname}." if hostname else None),
        )
        try:
            self._zc.register_service(info)
            self._infos.append(info)
            log.info("mdns published %s -> %s:%s (zeroconf)", name, lan_ipv4(), port)
        except Exception:
            log.warning("mdns publish failed name=%s type=%s", name, type_, exc_info=True)

    def _publish_dns_sd(
        self,
        name: str,
        type_: str,
        port: int,
        txt: dict[str, Any] | None,
    ) -> None:
        args = ["dns-sd", "-R", name, type_, ".", str(int(port))]
        for key, value in (txt or {}).items():
            args.append(f"{key}={value}")
        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._procs.append(proc)
            log.info("mdns published %s %s:%s (dns-sd)", name, type_, port)
        except OSError:
            log.warning("mdns publish (dns-sd) failed for %s", name, exc_info=True)

    def close(self) -> None:
        if self._zc is not None:
            try:
                self._zc.unregister_all_services()
                self._zc.close()
            except Exception:
                pass
            self._zc = None
        for proc in self._procs:
            try:
                proc.terminate()
            except OSError:
                pass
        self._procs.clear()


def publish_service(
    *,
    name: str,
    type_: str,
    port: int,
    txt: dict[str, Any] | None = None,
    hostname: str | None = None,
) -> MdnsPublisher:
    """Convenience: publish a single service and return a handle to keep alive."""
    pub = MdnsPublisher()
    pub.publish(name=name, type_=type_, port=port, txt=txt, hostname=hostname)
    return pub


# ---------------------------------------------------------------------------
# 资源服务器（img-server / home-asset-hub）端口发现
#
# 端口应该由资源服务器自己决定：它 mDNS 广告里的 port 就是权威
# （asset-hub 的 `ASSET_HUB_PORT`，现网 img-server 的 `PHOTO_UPLOAD_PORT`）。
# Brain/Edge/iOS 不该各自硬编码 8080 —— 改一次端口要改四处，漏一处就是「静默拿不到字节」。
#
# 这里的解析顺序（每一层都能单独解释）：
#   1. 显式 env（BRAIN_IMG_UPLOAD_URL / PHOTO_UPLOAD_URL…）：配置永远赢
#   2. mDNS 发现（`_ha-img-server._tcp` 的 SRV 端口）+ `/health` 自校验
#   3. 上一次校验过的缓存（Bonjour 抖动时别把已经能用的地址丢掉）
#   4. 默认 8080（= 现网行为，永远退得回去）
#
# 缓存是必须的：上传/取字节都在请求路径上，不能让 Bonjour 查询挡在前面。
# ---------------------------------------------------------------------------

IMG_SERVER_SERVICE = "home-asset-hub"
# 「命名发现」用的两个名字（与 asset-hub / img-server 的广告一致）：
IMG_SERVER_INSTANCE = "Home Agent img-server"
IMG_SERVER_HOSTNAME = "img-server.local"

_img_server_state: dict[str, Any] = {"at": 0.0, "port": 0, "checked_at": 0.0}
_img_server_lock = threading.Lock()
_img_server_refreshing = False
# 负缓存：发现失败后这段时间内不再去问 Bonjour（否则每次上传都白等 2-5s）
IMG_SERVER_NEGATIVE_TTL = 15.0


def _img_server_health_ok(port: int, timeout: float = 0.6) -> bool:
    """自校验：mDNS 记录可能过期（服务刚换口/重启），先问一句 /health 再采信。"""
    try:
        url = f"http://127.0.0.1:{int(port)}/health"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if int(getattr(resp, "status", 0) or resp.getcode() or 0) != 200:
                return False
            raw = resp.read().decode("utf-8", "replace")
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            return False
        # 兼容现网 img-server（只给 ok/service）与 asset-hub（service=home-asset-hub）
        return bool(data.get("ok") is True or data.get("service") in (IMG_SERVER_SERVICE, "img-server"))
    except Exception:
        return False


def _lookup_known_instance(timeout: float = 2.0) -> dict[str, Any] | None:
    """按**已知实例名**直查（`dns-sd -L`）。

    为什么不用 `-B` 浏览：实测本机 `dns-sd -B _ha-img-server._tcp .` 在 4s 内什么都列不出来，
    而 `-L "Home Agent img-server" …` 立刻就能解析出 host:port + TXT —— iOS 走的也是这条
    「已知名字」的路（`img-server.local`）。浏览只在「不知道实例名」时才需要。
    """
    try:
        found = _dns_sd_lookup(IMG_SERVER_INSTANCE, IMG_SERVER_TYPE, timeout=timeout)
    except Exception:
        found = None
    if found and int(found.get("port") or 0) > 0:
        return found
    # 名字对不上（实例名被改过）时，退一步用浏览枚举
    return None


def discover_img_server(timeout: float = 2.0) -> dict[str, Any] | None:
    """按名字发现资源服务器：已知实例名直查 → 浏览枚举兜底。返回 {name, host, port, txt}。"""
    found = _lookup_known_instance(timeout=timeout)
    if found is None:
        try:
            for svc in discover_service(IMG_SERVER_TYPE, timeout=timeout):
                try:
                    port = int(svc.get("port") or 0)
                except (TypeError, ValueError):
                    port = 0
                if port > 0:
                    found = {
                        "name": str(svc.get("name") or ""),
                        "host": str(svc.get("host") or ""),
                        "port": port,
                        "txt": svc.get("txt") or {},
                    }
                    break
        except Exception:
            log.debug("discover_img_server browse failed", exc_info=True)
    if found:
        log.info(
            "img-server discovered %s:%s (txt=%s)",
            found.get("host"), found.get("port"), found.get("txt") or {},
        )
    return found


def _img_server_endpoint_candidates() -> list[Path]:
    """端点文件候选路径（按可信度排序）：

    1. 显式 env：`ASSET_HUB_ENDPOINT_FILE` / `ASSET_HUB_DISCOVERY_DIR/<service>.json`
    2. 共享发现目录：`<RUNTIME_DIR>/../.discovery/<service>.json`（服务启动时写的）
    3. 兄弟 runtime：`<RUNTIME_DIR>/../home-asset-hub/backend/endpoint.json`
    4. 约定绝对路径：`~/runtime/.discovery/<service>.json`

    为什么要有「文件」这一层：端口由服务自己决定，但消费方不能靠猜 —— 实测这台机器上
    `dns-sd` 解析不稳（有时 5s 不出结果），所以**确定性的那份**（服务自己写的端点）
    要放在 Bonjour 前面；Bonjour 只兜「消费方与服务器不在同一台机」的场景。
    """
    import os as _os
    out: list[Path] = []
    explicit = (_os.environ.get("ASSET_HUB_ENDPOINT_FILE") or "").strip()
    if explicit:
        out.append(Path(explicit))
    disc = (_os.environ.get("ASSET_HUB_DISCOVERY_DIR") or "").strip()
    if disc:
        out.append(Path(disc) / f"{IMG_SERVER_SERVICE}.json")
    runtime_root = ""
    rt = (_os.environ.get("RUNTIME_DIR") or "").strip()
    if rt:
        runtime_root = str(Path(rt).resolve().parent)
    if not runtime_root:
        # 没拿到 RUNTIME_DIR：按平台的约定布局退化（~/runtime/<service>）
        runtime_root = str(Path.home() / "runtime")
    out.append(Path(runtime_root) / ".discovery" / f"{IMG_SERVER_SERVICE}.json")
    out.append(Path(runtime_root) / IMG_SERVER_SERVICE / "backend" / "endpoint.json")
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


_endpoint_cache: dict[str, Any] = {"path": "", "mtime": 0.0, "data": None}


def read_img_server_endpoint() -> dict[str, Any] | None:
    """读端点文件（发现第一层）：返回 {port, host, public_base, health_path, ...}；没有返回 None。

    按 mtime 缓存：文件没变就不重复解析（请求路径上零开销）。
    """
    import json as _json

    for path in _img_server_endpoint_candidates():
        try:
            stat = path.stat()
        except OSError:
            continue
        with _img_server_lock:
            if _endpoint_cache["path"] == str(path) and float(_endpoint_cache["mtime"]) == stat.st_mtime:
                data = _endpoint_cache["data"]
                if isinstance(data, dict):
                    return data
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            log.debug("endpoint file unreadable: %s", path, exc_info=True)
            continue
        if not isinstance(data, dict):
            continue
        try:
            port = int(data.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if port <= 0:
            continue
        with _img_server_lock:
            _endpoint_cache.update({"path": str(path), "mtime": stat.st_mtime, "data": data})
        return data
    return None


def _refresh_img_server_port(*, timeout: float = 2.0, verify: bool = True) -> int:
    """真的去发现一次并（可选）自校验，更新状态；返回本次结论（0=没找到且无缓存）。

    顺序：端点文件（确定性）→ mDNS（跨设备兜底）。两者都要过 `/health` 自校验。
    """
    endpoint = read_img_server_endpoint()
    port = int(endpoint["port"]) if endpoint else 0
    source = "endpoint-file" if port else ""
    if not port:
        found = discover_img_server(timeout=timeout)
        port = int(found["port"]) if found else 0
        source = "mdns" if port else ""
    ok = bool(port) and (not verify or _img_server_health_ok(port))
    with _img_server_lock:
        _img_server_state["checked_at"] = time.time()
        if ok:
            _img_server_state.update({"at": time.time(), "port": port})
            _img_server_state["source"] = source
            return port
    if port:
        log.warning("img-server %s says port=%s but /health 自校验失败，忽略", source or "?", port)
    with _img_server_lock:
        # 发现到了但校验失败：宁可用已知可用的旧值/默认值，也不把流量引到没应答的口上。
        return int(_img_server_state.get("port") or 0)


def _refresh_in_background(timeout: float, verify: bool) -> None:
    """后台刷新：请求路径绝不因为 Bonjour 变慢，但下一次调用会拿到新结果。"""
    global _img_server_refreshing
    with _img_server_lock:
        if _img_server_refreshing:
            return
        _img_server_refreshing = True

    def _run() -> None:
        global _img_server_refreshing
        try:
            _refresh_img_server_port(timeout=timeout, verify=verify)
        finally:
            with _img_server_lock:
                _img_server_refreshing = False

    threading.Thread(target=_run, name="img-server-mdns-refresh", daemon=True).start()


def resolve_img_server_port(
    default_port: int = 8080,
    *,
    ttl: float = 60.0,
    timeout: float = 2.0,
    verify: bool = True,
    blocking: bool | None = None,
) -> int:
    """资源服务器端口：env 之外的最后一道解析（发现 → 已验证缓存 → 默认值）。

    blocking=None（默认）：**第一次**解析阻塞（把成本付一次），之后走缓存；
    缓存过期时后台刷新、本次先用旧值 —— 上传/取字节在请求路径上，不能被 Bonjour 挡住。
    """
    now = time.time()
    with _img_server_lock:
        port = int(_img_server_state.get("port") or 0)
        at = float(_img_server_state.get("at") or 0.0)
        checked_at = float(_img_server_state.get("checked_at") or 0.0)
        ever_checked = checked_at > 0.0
    if port and (now - at) < ttl:
        return port
    # 负缓存先于「要不要阻塞」：刚探过且没探到，就别再探一次（无论调用方给不给 blocking）
    if (now - checked_at) < IMG_SERVER_NEGATIVE_TTL:
        return port or int(default_port)
    if blocking is None:
        blocking = not ever_checked
    if blocking:
        found_port = _refresh_img_server_port(timeout=timeout, verify=verify)
        return found_port or int(default_port)
    _refresh_in_background(timeout, verify)
    return port or int(default_port)


def warm_img_server_discovery(*, timeout: float = 3.0) -> None:
    """启动时预热（Brain 起来时先问一次，别等第一条上传才发现端口）。非阻塞。"""
    _refresh_in_background(timeout, True)


def img_server_base(host: str = "127.0.0.1", default_port: int = 8080) -> str:
    """`http://<host>:<port>`（host 用现算的 LAN IP 时就是给电视/小度用的地址）。"""
    return f"http://{host}:{resolve_img_server_port(default_port)}"


def discover_service(type_: str, timeout: float = 3.0) -> list[dict[str, Any]]:
    """Return [{name, host, port, txt}] for services of `type_` on the LAN."""
    if HAS_ZEROCONF:
        return _discover_zeroconf(type_, timeout)
    return _discover_dns_sd(type_, timeout)


def _discover_zeroconf(type_: str, timeout: float) -> list[dict[str, Any]]:
    zc = zeroconf.Zeroconf()
    found: dict[str, dict[str, Any]] = {}
    fq_type = _fq_type(type_)

    def capture(name: str) -> None:
        info = zc.get_service_info(fq_type, name)
        if info is not None and info.addresses:
            found[name] = {
                "name": name,
                "host": socket.inet_ntoa(info.addresses[0]),
                "port": info.port,
                "txt": {
                    k.decode("utf-8", "replace"): v.decode("utf-8", "replace")
                    for k, v in (info.properties or {}).items()
                },
            }

    class _Listener:
        def add_service(self, _zc: Any, _type: str, name: str) -> None:
            capture(name)

        def update_service(self, _zc: Any, _type: str, name: str) -> None:
            capture(name)

        def remove_service(self, _zc: Any, _type: str, name: str) -> None:
            found.pop(name, None)

    zeroconf.ServiceBrowser(zc, fq_type, _Listener())
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if found:
                break
            time.sleep(0.2)
        return list(found.values())
    finally:
        zc.close()



def _parse_dns_sd_browse_line(line: str, type_: str) -> str | None:
    """解析 `dns-sd -B` 的一行 → 实例名。纯函数。

    真实输出（列：时间戳 A/R Flags if 域 服务类型 **实例名**，实例名含空格且在最后）：

        23:38:02.456  Add        2   5  local.  _ha-img-server._tcp.  Home Agent img-server

    所以不能按空格数取第 N 列（早先取 parts[3]，取到的是域 `local.`）；正确做法是
    找到服务类型那一段，**后面的整段**才是实例名。
    """
    parts = line.split()
    if not parts or "Add" not in parts[:3]:
        return None
    wanted = type_.rstrip(".")
    marker = ""
    for tok in parts:
        if tok.rstrip(".") == wanted:
            marker = tok
            break
    if not marker:
        return None
    tail = line.split(marker, 1)[1].strip()
    return tail or None


def _discover_dns_sd(type_: str, timeout: float) -> list[dict[str, Any]]:
    """Best-effort browse via `dns-sd -B` + `-L`（零依赖兜底）。

    同样不能 subprocess.run：`dns-sd` 是「一直打印」的进程，我们用 Popen + 期限到了就收工。
    """
    results: list[dict[str, Any]] = []
    try:
        proc = subprocess.Popen(
            ["dns-sd", "-B", type_, ".", "-t", str(int(max(1, timeout)))],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return results
    deadline = time.time() + max(0.5, timeout) + 0.5
    seen: set[str] = set()
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0 or proc.stdout is None:
                break
            try:
                ready, _, _ = select.select([proc.stdout], [], [], remaining)
            except Exception:
                break
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:
                break
            instance = _parse_dns_sd_browse_line(line, type_)
            if instance and instance not in seen:
                seen.add(instance)
                resolved = _dns_sd_lookup(instance, type_, timeout=min(2.0, timeout))
                if resolved is not None:
                    results.append(resolved)
                    break  # 有一个能用的就够了（资源服务器只有一台）
    finally:
        try:
            proc.kill()
            proc.wait(timeout=1)
        except Exception:
            pass
    return results


def _parse_dns_sd_lookup(line: str) -> dict[str, Any] | None:
    """解析 `dns-sd -L` 的一行：「… can be reached at <host>.<domain>.:<port> (interface …)」。
    纯函数（单测直接喂样例行）。

    注意行尾可能还有 `Flags: 1` 这类**带冒号的尾巴** —— 所以只能取「reached at」后的
    第一个 token 再在它里面切 host:port（早先按最后一个冒号切，会把端口读成 1）。
    """
    if " can be reached at " not in line:
        return None
    _left, _, right = line.partition(" can be reached at ")
    target = right.split()[0] if right.split() else ""
    host, sep, port_s = target.rpartition(":")
    if not sep:
        return None
    host = host.strip().removesuffix(".")
    try:
        port = int(port_s)
    except ValueError:
        return None
    if not host or port <= 0:
        return None
    return {"host": host, "port": port}


def _dns_sd_lookup(instance: str, type_: str, timeout: float = 2.0) -> dict[str, Any] | None:
    """按名字查一个实例的 host:port。

    坑：`dns-sd -L` **命中之后不会自己退出**（subprocess.run 会一直等到我们超时，
    超时异常又把已经读到的输出一起丢掉 —— 这就是「发现路径明明有服务却总也找不到」的原因）。
    所以这里用 Popen 边读边判：拿到答案立刻收工，最多等 timeout 秒。
    """
    try:
        proc = subprocess.Popen(
            ["dns-sd", "-L", instance, type_, ".", "-t", str(int(max(1, timeout)))],
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
            found = _parse_dns_sd_lookup(line)
            if found is not None:
                found["name"] = f"{instance}.{type_}"
                found["txt"] = {}
                return found
    finally:
        try:
            proc.kill()
            proc.wait(timeout=1)
        except Exception:
            pass
