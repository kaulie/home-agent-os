"""Mac Edge capability: camera.capture via GoPro + silent Wi‑Fi switch.

Pipeline (unlike iOS cellular-on-AP):
  remember home SSID → join GoPro AP → shutter → download still
  → restore home Wi‑Fi → write local inbox capture_ref. Upload is ``asset.upload``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mac_edge.plugins.wifi_switch import (
    WifiSnapshot,
    WifiSwitchError,
    join_network,
    restore_network,
    snapshot as wifi_snapshot,
    ssid_visible,
    current_ssid,
)

log = logging.getLogger("mac_edge.gopro_camera")

DEFAULT_HOST = "http://10.5.5.9"

PATH_MODE_PHOTO = "/gp/gpControl/command/mode?p=1"
PATH_SUB_MODE_PHOTO_SINGLE = "/gp/gpControl/command/sub_mode?mode=1&sub_mode=0"
PATH_STATUS = "/gp/gpControl/status"
PATH_SHUTTER_START = "/gp/gpControl/command/shutter?p=1"
PATH_SHUTTER_STOP = "/gp/gpControl/command/shutter?p=0"
PATH_MEDIA_LIST = "/gp/gpMediaList"

_STILL_SUFFIXES = (".jpg", ".jpeg", ".gpr")


class GoProCameraError(Exception):
    pass


_SSID_IN_ERR = re.compile(
    r"ssid=([^\s,)'\"]+)|join '([^']+)'|热点「([^」]+)」",
    re.IGNORECASE,
)


def humanize_capture_error(err: BaseException | str) -> str:
    """Readable step ``msg`` for camera.capture failures (Chinese + technical tail)."""
    text = str(err).strip()
    if not text:
        return "拍照失败：未返回原因。"
    low = text.lower()
    ssid = ""
    m = _SSID_IN_ERR.search(text)
    if m:
        ssid = next((g for g in m.groups() if g), "") or ""
    hotspot = f"「{ssid}」" if ssid else "GoPro"

    if "scan empty" in low:
        return (
            f"拍照失败：扫描不到{hotspot}热点，请确认相机已开机并打开 Wi‑Fi。"
            f"（{text}）"
        )
    if "join '" in low and "failed" in low:
        return (
            f"拍照失败：连不上{hotspot}热点，请确认相机热点已打开。"
            f"（{text}）"
        )
    if "no home ssid" in low:
        return "拍照失败：没有记录家里的 Wi‑Fi 名称，无法切回去。"
    if "restore home" in low or "timed out waiting for ssid" in low:
        return f"拍照失败：切回家里 Wi‑Fi 失败。（{text}）"
    if "gopro not reachable" in low:
        return f"拍照失败：已连相机热点，但相机无响应。请确认 GoPro 已开机。（{text}）"
    if "home network not reachable" in low:
        return f"拍照失败：已切回家里网，但网络不通。（{text}）"
    if "download still" in low:
        return f"拍照失败：快门可能已按下，但下载照片失败。（{text}）"
    if "upload" in low:
        return f"拍照失败：照片上传失败。（{text}）"
    if "gopro_ssid is required" in low or "gopro_password is required" in low:
        return f"拍照失败：Mac Edge 未配置 GoPro Wi‑Fi。（{text}）"
    if "shutter" in low:
        return f"拍照失败：快门指令失败。（{text}）"
    if text.startswith("拍照失败"):
        return text
    return f"拍照失败：{text}"


class _StageTimer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.marks: dict[str, int] = {}
        self._open: dict[str, float] = {}

    def begin(self, name: str) -> None:
        self._open[name] = time.perf_counter()

    def end(self, name: str) -> int:
        started = self._open.pop(name, time.perf_counter())
        ms = int((time.perf_counter() - started) * 1000)
        self.marks[name] = ms
        log.info("stage %s ms=%s", name, ms)
        return ms

    def finish(self) -> dict[str, int]:
        self.marks["total"] = int((time.perf_counter() - self.t0) * 1000)
        log.info("stage_timings %s", json.dumps(self.marks, ensure_ascii=False))
        return dict(self.marks)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _project_data_gopro() -> Path:
    # src/mac_edge/plugins/gopro_camera.py → parents[3] = mac/
    root = Path(__file__).resolve().parents[3]
    data = Path(_env("MAC_EDGE_DATA_DIR") or str(root / "data"))
    out = data / "gopro"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _gopro_host() -> str:
    return (_env("MAC_EDGE_GOPRO_HOST") or DEFAULT_HOST).rstrip("/")


def _http_get(url: str, *, timeout: float = 15.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.getcode() or 0), resp.read()
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        return int(e.code or 0), body
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GoProCameraError(f"HTTP GET failed {url}: {e}") from e


def _control_get(path: str, *, timeout: float = 15.0) -> tuple[int, bytes]:
    return _http_get(_gopro_host() + path, timeout=timeout)


def wait_camera_reachable(*, timeout_sec: float = 45.0, poll_sec: float = 1.0) -> None:
    deadline = time.monotonic() + max(5.0, timeout_sec)
    last_err = ""
    while time.monotonic() < deadline:
        try:
            code, _ = _control_get(PATH_STATUS, timeout=5.0)
            if 200 <= code < 300:
                return
            last_err = f"status http {code}"
        except GoProCameraError as e:
            last_err = str(e)
        time.sleep(max(0.3, poll_sec))
    raise GoProCameraError(f"GoPro not reachable at {_gopro_host()}: {last_err}")


def probe_camera_http(*, timeout_sec: float = 2.0) -> bool:
    """Single short status GET — used by is_available when already on GoPro AP."""
    try:
        code, _ = _control_get(PATH_STATUS, timeout=max(0.5, float(timeout_sec)))
        return 200 <= code < 300
    except GoProCameraError:
        return False


def is_available(*, config: Any = None):
    """Cheap preflight for Runtime: do not join or wait 45s.

    - Require MAC_EDGE_GOPRO_SSID (/password).
    - If already on GoPro SSID → short HTTP status probe.
    - Else → CoreWLAN scan for the hotspot (visible ⇔ likely powered on).
    """
    from mac_edge.capability_availability import Availability

    ssid = _env("MAC_EDGE_GOPRO_SSID")
    password = _env("MAC_EDGE_GOPRO_PASSWORD")
    if not ssid:
        return Availability.unavailable(
            "拍照不可用：未配置 GoPro Wi‑Fi（MAC_EDGE_GOPRO_SSID）。"
        )
    if not password:
        return Availability.unavailable(
            "拍照不可用：未配置 GoPro Wi‑Fi 密码（MAC_EDGE_GOPRO_PASSWORD）。"
        )

    try:
        on_ssid = current_ssid()
    except WifiSwitchError as e:
        return Availability.unavailable(f"拍照不可用：无法读取本机 Wi‑Fi（{e}）")

    if on_ssid == ssid:
        if probe_camera_http(timeout_sec=2.0):
            return Availability.available()
        return Availability.unavailable(
            f"拍照不可用：已连热点「{ssid}」，但相机无响应。请确认 GoPro 已开机。"
        )

    try:
        visible = ssid_visible(ssid, timeout_sec=8.0)
    except WifiSwitchError as e:
        return Availability.unavailable(f"拍照不可用：扫描 GoPro 热点失败（{e}）")
    if not visible:
        return Availability.unavailable(
            f"拍照不可用：扫描不到热点「{ssid}」。请确认相机已开机并打开 Wi‑Fi。"
        )
    return Availability.available()


def wait_home_reachable(
    *,
    probe_url: str,
    timeout_sec: float = 60.0,
    poll_sec: float = 1.0,
) -> None:
    """Best-effort: GET probe_url until TCP/HTTP works (home Wi‑Fi back)."""
    url = (probe_url or "").strip()
    if not url:
        time.sleep(2.0)
        return
    deadline = time.monotonic() + max(5.0, timeout_sec)
    last_err = ""
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                _ = resp.getcode()
            return
        except urllib.error.HTTPError:
            # Any HTTP status (incl. 404 on Brain "/") means the LAN/WAN is up.
            return
        except Exception as e:  # noqa: BLE001 — connectivity errors, keep polling
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(max(0.5, poll_sec))
    raise GoProCameraError(f"home network not reachable ({url}): {last_err}")


def capture_shutter() -> None:
    for path in (PATH_MODE_PHOTO, PATH_SUB_MODE_PHOTO_SINGLE, PATH_SHUTTER_START):
        code, body = _control_get(path, timeout=12.0)
        if code >= 400:
            raise GoProCameraError(
                f"shutter step {path} failed http={code} "
                f"body={body.decode('utf-8', errors='replace')[:120]}"
            )


def _folder_sequence(folder: str) -> int:
    digits = ""
    for ch in folder:
        if ch.isdigit():
            digits += ch
        else:
            break
    try:
        return int(digits) if digits else -1
    except ValueError:
        return -1


def _file_sequence(name: str) -> int:
    stem = Path(name).stem.upper()
    digits = ""
    for ch in reversed(stem):
        if ch.isdigit():
            digits = ch + digits
        else:
            break
    try:
        return int(digits) if digits else -1
    except ValueError:
        return -1


def _latest_still(media_payload: dict[str, Any]) -> tuple[str, str]:
    """Return (relative_path, filename) for newest still."""
    media = media_payload.get("media")
    if not isinstance(media, list):
        raise GoProCameraError("gpMediaList missing media[]")

    candidates: list[tuple[str, str, bool, int, int, int]] = []
    order = 0
    for folder_entry in media:
        if not isinstance(folder_entry, dict):
            continue
        folder = str(folder_entry.get("d") or "")
        files = folder_entry.get("fs") or []
        if not isinstance(files, list):
            continue
        for file in files:
            if not isinstance(file, dict):
                continue
            name = str(file.get("n") or "").strip()
            if not name:
                continue
            lower = name.lower()
            is_still = any(lower.endswith(suf) for suf in _STILL_SUFFIXES)
            candidates.append(
                (
                    folder,
                    name,
                    is_still,
                    _folder_sequence(folder),
                    _file_sequence(name),
                    order,
                )
            )
            order += 1

    stills = [c for c in candidates if c[2]]
    pool = stills or candidates
    if not pool:
        raise GoProCameraError("gpMediaList has no files")

    best = max(pool, key=lambda c: (c[3], c[4], c[5]))
    folder, name = best[0], best[1]
    if folder:
        rel = f"/videos/DCIM/{folder}/{name}"
    else:
        rel = f"/videos/DCIM/{name}"
    return rel, name


def fetch_latest_still_bytes() -> tuple[bytes, str]:
    code, body = _control_get(PATH_MEDIA_LIST, timeout=25.0)
    if code >= 400:
        raise GoProCameraError(f"gpMediaList http={code}")
    try:
        payload = json.loads(body.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError as e:
        raise GoProCameraError(f"gpMediaList not JSON: {e}") from e
    if not isinstance(payload, dict):
        raise GoProCameraError("gpMediaList root must be object")
    rel, name = _latest_still(payload)

    host = _gopro_host()
    # Control on :80; media usually :8080
    if "://" in host:
        scheme, rest = host.split("://", 1)
        host_only = rest.split("/")[0]
        if ":" in host_only:
            hostname = host_only.rsplit(":", 1)[0]
        else:
            hostname = host_only
        media_base = f"{scheme}://{hostname}:8080"
    else:
        media_base = host + ":8080"

    primary = media_base + rel
    last_err = ""
    try:
        code, data = _http_get(primary, timeout=45.0)
        if 200 <= code < 300 and data:
            return data, name
        last_err = f"http={code} bytes={len(data or b'')}"
    except GoProCameraError as e:
        last_err = str(e)
        err_l = last_err.lower()
        if "timed out" in err_l or "timeout" in err_l:
            raise GoProCameraError(f"download still timed out: {primary}") from e
    fallback = _gopro_host() + rel
    try:
        code, data = _http_get(fallback, timeout=20.0)
    except GoProCameraError as e:
        raise GoProCameraError(
            f"download still failed primary={last_err} fallback={e}"
        ) from e
    if code >= 400 or not data:
        raise GoProCameraError(
            f"download still failed http={code} url={primary} ({last_err})"
        )
    return data, name


def _join_gopro(home: WifiSnapshot) -> None:
    ssid = _env("MAC_EDGE_GOPRO_SSID")
    password = _env("MAC_EDGE_GOPRO_PASSWORD")
    if not ssid:
        raise GoProCameraError("MAC_EDGE_GOPRO_SSID is required for silent Wi-Fi switch")
    if not password:
        raise GoProCameraError(
            "MAC_EDGE_GOPRO_PASSWORD is required (GoPro AP is almost always WPA)"
        )
    # Already on camera AP?
    if home.ssid == ssid:
        log.info("already on GoPro SSID=%s", ssid)
        return
    try:
        join_network(ssid, password, device=home.device, settle_sec=1.0)
    except WifiSwitchError as e:
        raise GoProCameraError(str(e)) from e


def _restore_home(home: WifiSnapshot) -> None:
    home_ssid = _env("MAC_EDGE_HOME_WIFI_SSID") or (home.ssid or "")
    home_password = _env("MAC_EDGE_HOME_WIFI_PASSWORD") or None
    if not home_ssid:
        raise GoProCameraError("cannot restore home Wi-Fi: no home SSID recorded")
    snap = WifiSnapshot(device=home.device, ssid=home_ssid)
    try:
        restore_network(snap, password=home_password, settle_sec=1.0)
    except WifiSwitchError as e:
        raise GoProCameraError(f"restore home Wi-Fi failed: {e}") from e


def capture_photo_pipeline() -> dict[str, Any]:
    """Shutter + download + restore home. Does not upload (that is asset.upload)."""
    home = wifi_snapshot()
    log.info(
        "camera.capture start home_ssid=%s device=%s gopro_ssid=%s",
        home.ssid,
        home.device,
        _env("MAC_EDGE_GOPRO_SSID"),
    )

    local_path = ""
    timer = _StageTimer()
    try:
        timer.begin("join_gopro")
        _join_gopro(home)
        timer.end("join_gopro")

        timer.begin("wait_camera")
        wait_camera_reachable(timeout_sec=45.0)
        timer.end("wait_camera")

        timer.begin("shutter")
        try:
            _control_get(PATH_SHUTTER_STOP, timeout=5.0)
        except GoProCameraError:
            pass
        capture_shutter()
        time.sleep(2.0)
        timer.end("shutter")

        timer.begin("download")
        data, name = fetch_latest_still_bytes()
        from mac_edge.capture import store as capture_store
        cref = capture_store.put(data, original_name=name)
        local_path = str(capture_store.open_jpeg(cref["capture_id"]))
        timer.end("download")
        log.info("downloaded still bytes=%s capture_id=%s path=%s", len(data), cref["capture_id"], local_path)

        timer.begin("restore_home")
        _restore_home(home)
        timer.end("restore_home")

        outputs = {"photo_local_path": local_path, "capture_ref": cref}
        timer.finish()
        log.info("camera.capture ok capture_id=%s", cref["capture_id"])
        return outputs
    except Exception:
        for name in list(timer._open):
            timer.end(name)
        timer.finish()
        raise
    finally:
        # Always try to leave the GoPro AP, even if shutter/download failed.
        try:
            _restore_home(home)
        except Exception as restore_err:  # noqa: BLE001
            log.error("failed to restore home Wi-Fi: %s", restore_err)


def capture_from_params(
    params: dict[str, Any] | None = None,
    *,
    asset: "CapAsset | None" = None,
) -> tuple[str, dict[str, Any]]:
    """Download still into the local inbox. Upload is a later asset.upload step."""
    _ = params
    _ = asset
    raw = capture_photo_pipeline()
    cref = raw.get("capture_ref")
    if not isinstance(cref, dict) or not str(cref.get("capture_id") or "").strip():
        raise GoProCameraError("camera.capture produced no capture_ref")
    outputs: dict[str, Any] = {"capture_ref": cref}
    msg = (
        f"capture ok (local inbox, no asset)\n"
        f"capture_id: {cref['capture_id']}"
    )
    return msg, outputs
