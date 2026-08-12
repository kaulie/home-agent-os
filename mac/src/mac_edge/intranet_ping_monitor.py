"""Runtime LAN ping monitor (not a Brain capability).

Modes: gateway | targets | lan. Writes SAMPLE/STATS to a dedicated log file.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import subprocess
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque

from mac_edge.config import IntranetPingSettings

log = logging.getLogger("mac_edge.intranet_ping")

_PING_BIN = "/sbin/ping"
_RTT_RE = re.compile(r"time[=<]([\d.]+)\s*ms", re.I)
_ARP_IP_RE = re.compile(r"\((\d{1,3}(?:\.\d{1,3}){3})\)")


@dataclass(frozen=True)
class PingSample:
    ts: float
    host: str
    ok: bool
    rtt_ms: float | None
    error: str | None = None


@dataclass(frozen=True)
class _DefaultRoute:
    gateway: str | None
    iface: str | None
    local_ip: str | None


def _run(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _default_route() -> _DefaultRoute:
    proc = _run(["route", "-n", "get", "default"], timeout=5)
    gateway: str | None = None
    iface: str | None = None
    if proc and proc.stdout:
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("gateway:"):
                gateway = line.split(":", 1)[1].strip() or None
            elif line.startswith("interface:"):
                iface = line.split(":", 1)[1].strip() or None
    local_ip: str | None = None
    if iface:
        proc2 = _run(["ipconfig", "getifaddr", iface], timeout=5)
        if proc2:
            local_ip = (proc2.stdout or "").strip() or None
    return _DefaultRoute(gateway=gateway, iface=iface, local_ip=local_ip)


def default_gateway() -> str | None:
    return _default_route().gateway


def _subnet_for_iface(iface: str, local_ip: str) -> ipaddress.IPv4Network | None:
    proc = _run(["ifconfig", iface], timeout=5)
    mask: str | None = None
    if proc and proc.stdout:
        m = re.search(
            rf"inet\s+{re.escape(local_ip)}\s+netmask\s+(0x[0-9a-fA-F]+|\d+\.\d+\.\d+\.\d+)",
            proc.stdout,
        )
        if m:
            raw = m.group(1)
            if raw.startswith("0x"):
                mask = str(ipaddress.IPv4Address(int(raw, 16)))
            else:
                mask = raw
    try:
        if mask:
            return ipaddress.IPv4Network(f"{local_ip}/{mask}", strict=False)
        return ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
    except ValueError:
        return None


def ping_once(host: str, *, timeout_ms: int = 1000) -> PingSample:
    host = (host or "").strip()
    now = time.time()
    if not host:
        return PingSample(ts=now, host="", ok=False, rtt_ms=None, error="empty host")
    cmd = [_PING_BIN, "-c", "1", "-W", str(max(100, int(timeout_ms))), host]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(2.0, timeout_ms / 1000.0 + 1.5),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return PingSample(ts=now, host=host, ok=False, rtt_ms=None, error="timeout")
    except OSError as e:
        return PingSample(ts=now, host=host, ok=False, rtt_ms=None, error=str(e))
    out = (proc.stdout or "") + (proc.stderr or "")
    m = _RTT_RE.search(out)
    if proc.returncode == 0 and m:
        return PingSample(ts=now, host=host, ok=True, rtt_ms=float(m.group(1)))
    return PingSample(
        ts=now,
        host=host,
        ok=False,
        rtt_ms=None,
        error="no reply" if proc.returncode != 0 else "parse_error",
    )


def _arp_ips_in_network(network: ipaddress.IPv4Network) -> set[str]:
    proc = _run(["arp", "-a"], timeout=10)
    if not proc or not proc.stdout:
        return set()
    found: set[str] = set()
    for line in proc.stdout.splitlines():
        m = _ARP_IP_RE.search(line)
        if not m:
            continue
        try:
            addr = ipaddress.IPv4Address(m.group(1))
        except ValueError:
            continue
        if addr in network:
            found.add(str(addr))
    return found


def discover_lan_peers(
    *,
    timeout_ms: int = 500,
    stop_event: threading.Event | None = None,
) -> list[str]:
    route = _default_route()
    if not route.local_ip or not route.iface:
        return []
    network = _subnet_for_iface(route.iface, route.local_ip)
    if network is None:
        return []
    peers = _arp_ips_in_network(network)
    for host in network.hosts():
        if stop_event is not None and stop_event.is_set():
            break
        ip = str(host)
        if ip == route.local_ip:
            continue
        if ping_once(ip, timeout_ms=timeout_ms).ok:
            peers.add(ip)
    peers.discard(route.local_ip)
    return sorted(peers, key=lambda s: tuple(int(x) for x in s.split(".")))


def _setup_file_logger(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mac_edge.intranet_ping.file")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)
    return logger


class IntranetPingMonitor:
    def __init__(self, settings: IntranetPingSettings):
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._file_log = _setup_file_logger(settings.log_path)
        self._samples: Deque[PingSample] = deque(maxlen=50_000)
        self._peers: list[str] = []
        self._last_discover_mono = 0.0
        self._last_stats_mono = 0.0

    def start(self) -> None:
        if not self.settings.enabled:
            log.info("intranet ping monitor disabled")
            return
        if self.settings.mode == "targets" and not self.settings.targets:
            log.warning(
                "intranet ping mode=targets but MAC_EDGE_INTRANET_PING_TARGETS empty — skip"
            )
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="intranet-ping-monitor",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "intranet ping monitor started mode=%s interval=%ss log=%s",
            self.settings.mode,
            self.settings.interval_sec,
            self.settings.log_path,
        )

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=5.0)
        self._thread = None
        log.info("intranet ping monitor stopped")

    def _run(self) -> None:
        if self.settings.mode == "lan":
            self._refresh_peers(force=True)
        self._last_stats_mono = time.monotonic()
        while not self._stop.is_set():
            round_started = time.monotonic()
            try:
                if self.settings.mode == "lan":
                    self._refresh_peers(force=False)
                hosts = self._current_hosts()
                if not hosts:
                    self._file_log.info("SAMPLE host=- ok=0 rtt_ms=- error=discover_empty")
                else:
                    for host in hosts:
                        if self._stop.is_set():
                            break
                        self._record(ping_once(host, timeout_ms=self.settings.timeout_ms))
                now = time.monotonic()
                if now - self._last_stats_mono >= self.settings.stats_interval_sec:
                    self._write_stats()
                    self._last_stats_mono = now
            except Exception as e:
                self._file_log.info("SAMPLE host=- ok=0 rtt_ms=- error=%s", type(e).__name__)
                log.warning("intranet ping round failed: %s", e)
            elapsed = time.monotonic() - round_started
            self._stop.wait(max(0.2, self.settings.interval_sec - elapsed))

    def _current_hosts(self) -> list[str]:
        if self.settings.mode == "gateway":
            gw = default_gateway()
            return [gw] if gw else []
        if self.settings.mode == "targets":
            return list(self.settings.targets)
        return list(self._peers)

    def _refresh_peers(self, *, force: bool) -> None:
        now = time.monotonic()
        if not force and (now - self._last_discover_mono) < self.settings.discover_interval_sec:
            return
        self._last_discover_mono = now
        peers = discover_lan_peers(
            timeout_ms=min(500, self.settings.timeout_ms),
            stop_event=self._stop,
        )
        self._peers = peers
        preview = ",".join(peers[:32]) + ("…" if len(peers) > 32 else "")
        self._file_log.info("DISCOVER peers=%d list=%s", len(peers), preview)

    def _record(self, sample: PingSample) -> None:
        self._samples.append(sample)
        if sample.ok and sample.rtt_ms is not None:
            self._file_log.info("SAMPLE host=%s ok=1 rtt_ms=%.3f", sample.host, sample.rtt_ms)
        else:
            self._file_log.info(
                "SAMPLE host=%s ok=0 rtt_ms=- error=%s",
                sample.host or "-",
                sample.error or "fail",
            )

    def _write_stats(self) -> None:
        now = time.time()
        for window_sec, label in ((60.0, "1m"), (300.0, "5m")):
            cutoff = now - window_sec
            by_host: dict[str, list[PingSample]] = defaultdict(list)
            all_samples: list[PingSample] = []
            for s in self._samples:
                if s.ts < cutoff or not s.host:
                    continue
                by_host[s.host].append(s)
                all_samples.append(s)
            for host in sorted(by_host):
                self._emit_window_stats(label, host, by_host[host])
            if all_samples:
                self._emit_window_stats(label, "*", all_samples)
            else:
                self._file_log.info(
                    "STATS window=%s host=* count=0 ok=0 loss_pct=0 avg_ms=-",
                    label,
                )

    def _emit_window_stats(self, window: str, host: str, samples: list[PingSample]) -> None:
        count = len(samples)
        ok_samples = [s for s in samples if s.ok and s.rtt_ms is not None]
        ok_n = len(ok_samples)
        loss_pct = 0.0 if count == 0 else (100.0 * (count - ok_n) / count)
        avg_s = (
            f"{sum(float(s.rtt_ms or 0.0) for s in ok_samples) / ok_n:.3f}"
            if ok_samples
            else "-"
        )
        self._file_log.info(
            "STATS window=%s host=%s count=%d ok=%d loss_pct=%.1f avg_ms=%s",
            window,
            host,
            count,
            ok_n,
            loss_pct,
            avg_s,
        )
