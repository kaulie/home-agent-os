"""Mac Wi‑Fi switch helpers.

Read-only queries use ``networksetup``. Association uses CoreWLAN via
osascript so a LaunchAgent does not trigger the admin SecurityAgent dialog
that ``networksetup -setairportnetwork`` shows even under ``sudo -n``.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass

log = logging.getLogger("mac_edge.wifi_switch")

_SSID_LINE = re.compile(
    r"Current Wi-Fi Network:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)
_NOT_ASSOCIATED = re.compile(r"not associated|You are not associated", re.IGNORECASE)
# networksetup often prints this while macOS still auto-joins preferred nets.
_TRANSIENT_JOIN = re.compile(r"-3900|\btmpErr\b", re.IGNORECASE)
_IPCONFIG_SSID = re.compile(
    r"^\s*SSID\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE
)

_OSASCRIPT = "/usr/bin/osascript"
_JXA_ASSOCIATE = """
ObjC.import("CoreWLAN");
function run(argv) {
  var ssid = argv[0] || "";
  var password = argv.length > 1 ? argv[1] : "";
  if (!ssid) return "ERR empty ssid";
  var iface = $.CWWiFiClient.sharedWiFiClient.interface;
  if (!iface) return "ERR no wifi interface";
  var err = Ref();
  var nets = iface.scanForNetworksWithNameError(ssid, err);
  if (!nets || Number(nets.count) < 1) {
    return "ERR scan empty ssid=" + ssid;
  }
  var net = nets.anyObject;
  var aerr = Ref();
  var pw = password ? password : null;
  var ok = iface.associateToNetworkPasswordError(net, pw, aerr);
  if (!ok) {
    var msg = aerr[0] ? String(aerr[0]) : "associate returned false";
    return "ERR associate " + msg;
  }
  return "OK";
}
"""


class WifiSwitchError(Exception):
    pass


@dataclass(frozen=True)
class WifiSnapshot:
    device: str
    ssid: str | None


def _run(argv: list[str], *, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise WifiSwitchError(f"command timed out: {' '.join(argv)}") from e
    except OSError as e:
        raise WifiSwitchError(f"command failed to start: {e}") from e


def _associate_corewlan(ssid: str, password: str | None) -> tuple[int, str]:
    """Join ``ssid`` via CoreWLAN. Does not prompt for admin on macOS 11 LaunchAgents."""
    argv = [_OSASCRIPT, "-l", "JavaScript", "-", ssid, (password or "")]
    try:
        proc = subprocess.run(
            argv,
            input=_JXA_ASSOCIATE,
            check=False,
            capture_output=True,
            text=True,
            timeout=90.0,
        )
    except subprocess.TimeoutExpired as e:
        raise WifiSwitchError(f"corewlan associate timed out ssid={ssid}") from e
    except OSError as e:
        raise WifiSwitchError(f"osascript failed to start: {e}") from e
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    out = "\n".join(x for x in (stdout, stderr) if x)
    if proc.returncode != 0 or not re.search(r'(^|\n)"?OK"?\s*$', stdout):
        return int(proc.returncode or 1), out or "corewlan associate failed"
    return 0, out


def wifi_device() -> str:
    """Return Airport hardware port device (e.g. en0)."""
    override = (os.environ.get("MAC_EDGE_WIFI_DEVICE") or "").strip()
    if override:
        return override
    proc = _run(["/usr/sbin/networksetup", "-listallhardwareports"], timeout=15.0)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode == 0 and text.strip():
        lines = text.splitlines()
        for i, line in enumerate(lines):
            lower = line.lower()
            if "wi-fi" in lower or "wifi" in lower or "airport" in lower:
                for j in range(i + 1, min(i + 5, len(lines))):
                    m = re.match(r"Device:\s*(\S+)", lines[j].strip(), re.IGNORECASE)
                    if m:
                        return m.group(1)
    # Fallback: probe common devices
    for candidate in ("en0", "en1"):
        probe = _run(
            ["/usr/sbin/networksetup", "-getairportnetwork", candidate],
            timeout=10.0,
        )
        blob = ((probe.stdout or "") + (probe.stderr or "")).lower()
        if "airport" in blob or "wi-fi" in blob or "network" in blob:
            if "unrecognized" not in blob and "not a wi-fi" not in blob:
                return candidate
    raise WifiSwitchError(
        "could not find Wi-Fi hardware port (set MAC_EDGE_WIFI_DEVICE); "
        f"listallhardwareports rc={proc.returncode} out={text[:200]!r}"
    )


def _parse_ipconfig_ssid(text: str) -> str | None:
    m = _IPCONFIG_SSID.search(text or "")
    if not m:
        return None
    ssid = m.group(1).strip()
    if not ssid or ssid.lower() in ("<redacted>", "redacted"):
        return None
    return ssid


def _parse_networksetup_ssid(blob: str) -> str | None:
    if _NOT_ASSOCIATED.search(blob or ""):
        return None
    m = _SSID_LINE.search(blob or "")
    if m:
        ssid = m.group(1).strip()
        return ssid or None
    m2 = re.search(r"connected to\s+(.+?)\.?\s*$", blob or "", re.IGNORECASE)
    if m2:
        return m2.group(1).strip() or None
    return None


def current_ssid(device: str | None = None) -> str | None:
    """Current SSID. Prefer ``ipconfig`` (fast); fall back to ``networksetup``."""
    dev = (device or wifi_device()).strip()
    fast = _run(["/usr/sbin/ipconfig", "getsummary", dev], timeout=5.0)
    ssid = _parse_ipconfig_ssid((fast.stdout or "") + "\n" + (fast.stderr or ""))
    if ssid:
        return ssid
    proc = _run(
        ["/usr/sbin/networksetup", "-getairportnetwork", dev],
        timeout=15.0,
    )
    blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    parsed = _parse_networksetup_ssid(blob)
    if parsed is not None or _NOT_ASSOCIATED.search(blob):
        return parsed
    if proc.returncode != 0:
        raise WifiSwitchError(f"getairportnetwork failed: {blob}")
    return None


def snapshot() -> WifiSnapshot:
    dev = wifi_device()
    return WifiSnapshot(device=dev, ssid=current_ssid(dev))


def _associate(dev: str, ssid: str, password: str | None) -> tuple[int, str]:
    pwd = (password or "").strip()
    log.info("wifi join device=%s ssid=%s via=corewlan password=%s", dev, ssid, "yes" if pwd else "no")
    t0 = time.perf_counter()
    rc, out = _associate_corewlan(ssid, pwd)
    log.info(
        "stage wifi_associate ssid=%s via=corewlan ms=%s rc=%s out=%s",
        ssid,
        int((time.perf_counter() - t0) * 1000),
        rc,
        (out or "")[:240],
    )
    return rc, out


def _looks_like_join_error(rc: int, out: str) -> bool:
    if rc != 0:
        return True
    if not out:
        return False
    if re.search(r"error|could not|failed", out, re.IGNORECASE):
        return "Error:" in out or "could not" in out.lower() or "failed" in out.lower()
    return False


def join_network(
    ssid: str,
    password: str | None = None,
    *,
    device: str | None = None,
    settle_sec: float = 3.0,
    timeout_sec: float = 30.0,
) -> None:
    """Associate with ``ssid``. Password optional if already in Preferred Networks."""
    name = (ssid or "").strip()
    if not name:
        raise WifiSwitchError("ssid is empty")
    dev = (device or wifi_device()).strip()
    if current_ssid(dev) == name:
        log.info("already on ssid=%s", name)
        return
    rc, out = _associate(dev, name, password)
    if _looks_like_join_error(rc, out) and not _TRANSIENT_JOIN.search(out or ""):
        raise WifiSwitchError(f"join '{name}' failed (rc={rc}): {out or 'no output'}")
    if _looks_like_join_error(rc, out):
        log.warning("join networksetup transient error, waiting for SSID: %s", out[:240])
    _wait_associated(name, device=dev, settle_sec=settle_sec, timeout_sec=timeout_sec)


def _hold_sec() -> float:
    raw = (os.environ.get("MAC_EDGE_WIFI_HOLD_SEC") or "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            log.warning("invalid MAC_EDGE_WIFI_HOLD_SEC=%r, using 1.0", raw)
    return 1.0


def _wait_associated(
    expected: str,
    *,
    device: str,
    settle_sec: float,
    timeout_sec: float,
) -> None:
    """Wait until ``expected`` is the current SSID; skip settle if already there."""
    if current_ssid(device) == expected:
        log.info("ssid=%s associated immediately, skip settle", expected)
        return
    if settle_sec > 0:
        time.sleep(settle_sec)
    t_wait = time.perf_counter()
    wait_until_ssid(expected, device=device, timeout_sec=timeout_sec, poll_sec=0.3)
    log.info(
        "stage wifi_wait_ssid ssid=%s ms=%s",
        expected,
        int((time.perf_counter() - t_wait) * 1000),
    )


def _hold_ssid(
    expected: str,
    *,
    device: str,
    password: str | None,
    hold_sec: float | None = None,
) -> None:
    """Re-join if auto-join snaps away shortly after a successful restore.

    Joining the GoPro AP promotes it in Preferred Networks; macOS may bounce
    back. We cannot ``networksetup -removepreferredwirelessnetwork`` from a
    LaunchAgent (admin dialog). A short hold is the substitute.
    """
    seconds = _hold_sec() if hold_sec is None else hold_sec
    if seconds <= 0:
        return
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(min(0.4, max(0.2, seconds)))
        now = current_ssid(device)
        if now == expected:
            continue
        log.warning("wifi bounced to ssid=%s, re-joining %s", now, expected)
        _associate(device, expected, password)
        wait_until_ssid(expected, device=device, timeout_sec=20.0, poll_sec=0.3)
        return


def restore_network(
    home: WifiSnapshot,
    *,
    password: str | None = None,
    settle_sec: float = 3.0,
    timeout_sec: float = 45.0,
) -> None:
    """Restore association recorded in ``home``.

    ``networksetup`` often returns -3900/tmpErr while macOS still joins the
    preferred home network — wait for the SSID instead of treating that as fatal.
    """
    if not home.ssid:
        raise WifiSwitchError("no home SSID recorded to restore")
    dev = (home.device or wifi_device()).strip()
    if current_ssid(dev) == home.ssid:
        log.info("already on home ssid=%s", home.ssid)
        return
    # Do not call networksetup -removepreferredwirelessnetwork: that always
    # raises the admin dialog from a LaunchAgent. CoreWLAN join + a short
    # hold loop is enough to beat auto-join bounce-back.
    rc, out = _associate(dev, home.ssid, password)
    if _looks_like_join_error(rc, out):
        log.warning(
            "restore networksetup rc=%s out=%s (will wait for home SSID)",
            rc,
            (out or "")[:240],
        )
    try:
        _wait_associated(
            home.ssid, device=dev, settle_sec=settle_sec, timeout_sec=timeout_sec
        )
        _hold_ssid(home.ssid, device=dev, password=password)
        return
    except WifiSwitchError:
        log.warning("home SSID not associated yet, retrying restore")
    rc, out = _associate(dev, home.ssid, password)
    if _looks_like_join_error(rc, out):
        log.warning("restore retry rc=%s out=%s", rc, (out or "")[:240])
    _wait_associated(
        home.ssid,
        device=dev,
        settle_sec=0.0,
        timeout_sec=max(15.0, timeout_sec / 2.0),
    )
    _hold_ssid(home.ssid, device=dev, password=password)


def wait_until_ssid(
    expected: str,
    *,
    device: str | None = None,
    timeout_sec: float = 30.0,
    poll_sec: float = 1.0,
) -> None:
    name = (expected or "").strip()
    if not name:
        raise WifiSwitchError("expected ssid empty")
    dev = (device or wifi_device()).strip()
    deadline = time.monotonic() + max(1.0, timeout_sec)
    while time.monotonic() < deadline:
        now = current_ssid(dev)
        if now == name:
            return
        time.sleep(max(0.2, poll_sec))
    raise WifiSwitchError(
        f"timed out waiting for ssid={name!r} (current={current_ssid(dev)!r})"
    )
