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

import logging
import socket
import subprocess
import time
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
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


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
        if HAS_ZEROCONF:
            self._publish_zeroconf(name, type_, port, txt, hostname)
        else:
            self._publish_dns_sd(name, type_, port, txt)

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



def _discover_dns_sd(type_: str, timeout: float) -> list[dict[str, Any]]:
    """Best-effort browse via `dns-sd -B` + `-L` (zero-dependency fallback)."""
    results: list[dict[str, Any]] = []
    try:
        proc = subprocess.run(
            ["dns-sd", "-B", type_, ".", "-t", str(int(max(1, timeout)))],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
    except Exception:
        return results
    seen: set[str] = set()
    for line in (proc.stdout or "").splitlines():
        # "Add 2 4 <instance>.<type>. <domain>"
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "Add":
            instance = parts[3]
            if instance.endswith(f".{type_}."):
                instance = instance[: -len(f".{type_}.")]
            if instance and instance not in seen:
                seen.add(instance)
                resolved = _dns_sd_lookup(instance, type_)
                if resolved is not None:
                    results.append(resolved)
    return results


def _dns_sd_lookup(instance: str, type_: str) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            ["dns-sd", "-L", instance, type_, ".", "-t", "2"],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except Exception:
        return None
    # "… <Instance>.<type>. can be reached at <host>.<domain>.:<port> (interface …)"
    for line in (proc.stdout or "").splitlines():
        if " can be reached at " in line:
            _left, _, right = line.partition(" can be reached at ")
            host = right.split(":")[0].strip().removesuffix(".")
            try:
                port = int(right.rsplit(":", 1)[-1].split()[0])
            except (ValueError, IndexError):
                port = 0
            if host and port:
                return {"name": f"{instance}.{type_}", "host": host, "port": port, "txt": {}}
    return None
