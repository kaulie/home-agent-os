"""Mac Edge capability: camera.capture via GoPro + silent Wi‑Fi switch.

Pipeline (unlike iOS cellular-on-AP):
  remember home SSID → join GoPro AP → shutter → download still
  → restore home Wi‑Fi → upload → photo_url
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
)

log = logging.getLogger("mac_edge.gopro_camera")

DEFAULT_HOST = "http://10.5.5.9"
DEFAULT_UPLOAD_URL = "http://115.190.153.53:9527/api/v1/photos/upload"
DEFAULT_PUBLIC_BASE = "http://115.190.153.53:8080"
DEFAULT_LAN_UPLOAD_URL = "http://192.168.3.65:8080/api/v1/photos/upload"
DEFAULT_LAN_PUBLIC_BASE = "http://192.168.3.65:8080"

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
        return f"拍照失败：已切回家里网，但图片服务器不可达。（{text}）"
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


def _normalize_upload_dest(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    if v in ("cloud",):
        return "cloud"
    if v in ("lan", "local", "home", ""):
        return "lan"
    log.warning("unknown upload_dest=%r — using lan", raw)
    return "lan"


def _upload_dest_from_params(params: dict[str, Any] | None) -> str:
    if isinstance(params, dict):
        raw = params.get("upload_dest") or params.get("uploadDest")
        if raw is not None and str(raw).strip():
            return _normalize_upload_dest(str(raw))
    return _normalize_upload_dest(_env("MAC_EDGE_PHOTO_UPLOAD_DEST") or "lan")


def _upload_endpoints(dest: str) -> tuple[str, str, str]:
    """Return (upload_url, public_base, probe_url) for cloud or lan."""
    if dest == "lan":
        upload = _env("MAC_EDGE_LAN_PHOTO_UPLOAD_URL") or DEFAULT_LAN_UPLOAD_URL
        public = _env("MAC_EDGE_LAN_PHOTO_PUBLIC_BASE") or DEFAULT_LAN_PUBLIC_BASE
        probe = public.rstrip("/") + "/health"
        return upload, public.rstrip("/"), probe
    upload = _env("MAC_EDGE_PHOTO_UPLOAD_URL") or DEFAULT_UPLOAD_URL
    public = _env("MAC_EDGE_PHOTO_PUBLIC_BASE") or DEFAULT_PUBLIC_BASE
    brain = _env("MAC_EDGE_BRAIN_URL") or re.sub(r"/api/v1/photos/upload/?$", "", upload)
    probe = brain.rstrip("/") + "/"
    return upload, public.rstrip("/"), probe


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


def _multipart_upload(path: Path, upload_url: str) -> dict[str, Any]:
    boundary = f"----MacEdgeGoPro{int(time.time() * 1000)}"
    filename = path.name
    file_bytes = path.read_bytes()
    parts: list[bytes] = []
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
    )
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = int(resp.getcode() or 0)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise GoProCameraError(f"upload HTTP {e.code}: {raw[:300]}") from e
    except urllib.error.URLError as e:
        raise GoProCameraError(f"upload failed: {e}") from e

    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        raise GoProCameraError(f"upload response not JSON (http={code}): {raw[:200]}") from e
    if not isinstance(data, dict):
        raise GoProCameraError("upload response must be object")
    return data


def _resolve_photo_url(
    upload_json: dict[str, Any],
    *,
    public_base: str,
) -> tuple[str, str]:
    saved_as = str(upload_json.get("saved_as") or "").strip()
    url = str(upload_json.get("url") or "").strip()
    base = public_base.rstrip("/")
    if url.startswith("http://") or url.startswith("https://"):
        # Loopback is only reachable on the uploader; rewrite to this dest's public base.
        if saved_as and url.startswith("http://127."):
            return f"{base}/{Path(saved_as).name}", saved_as
        return url, saved_as
    if saved_as:
        return f"{base}/{Path(saved_as).name}", saved_as
    raise GoProCameraError(f"upload ok but no photo_url/saved_as: {upload_json}")


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


def capture_photo_pipeline(*, upload_dest: str = "lan") -> dict[str, str]:
    """Full wire pipeline → flat string outputs."""
    target = _normalize_upload_dest(upload_dest)
    upload_url, public_base, probe = _upload_endpoints(target)

    home = wifi_snapshot()
    log.info(
        "camera.capture start dest=%s upload=%s probe=%s home_ssid=%s device=%s gopro_ssid=%s",
        target,
        upload_url,
        probe,
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
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^\w.\-]+", "_", name) or "capture.jpg"
        dest = _project_data_gopro() / f"{ts}_{safe_name}"
        dest.write_bytes(data)
        local_path = str(dest)
        timer.end("download")
        log.info("downloaded still bytes=%s path=%s", len(data), local_path)

        timer.begin("restore_home")
        _restore_home(home)
        timer.end("restore_home")

        timer.begin("wait_home")
        wait_home_reachable(probe_url=probe, timeout_sec=60.0, poll_sec=1.0)
        timer.end("wait_home")

        timer.begin("upload")
        upload_json = _multipart_upload(dest, upload_url)
        photo_url, saved_as = _resolve_photo_url(upload_json, public_base=public_base)
        timer.end("upload")
        if not photo_url.startswith("http://") and not photo_url.startswith("https://"):
            raise GoProCameraError(f"refusing non-http photo_url: {photo_url}")

        outputs = {
            "photo_local_path": local_path,
            "photo_url": photo_url,
        }
        if saved_as:
            outputs["saved_as"] = saved_as
        timer.finish()
        log.info("camera.capture ok photo_url=%s", photo_url)
        return outputs
    except Exception:
        for name in list(timer._open):
            timer.end(name)
        timer.finish()
        raise
    finally:
        # Always try to leave the GoPro AP, even if shutter/download/upload failed.
        try:
            _restore_home(home)
        except Exception as restore_err:  # noqa: BLE001
            log.error("failed to restore home Wi-Fi: %s", restore_err)


def capture_from_params(
    params: dict[str, Any] | None = None,
    *,
    asset: "CapAsset",
) -> tuple[str, dict[str, Any]]:
    """Upload still, then register via Runtime Asset Manager → capture_ref only."""
    from mac_edge.asset.sdk import CapAsset

    if not isinstance(asset, CapAsset):
        raise GoProCameraError("camera.capture requires CapAsset (Runtime SDK)")
    dest = _upload_dest_from_params(params)
    raw = capture_photo_pipeline(upload_dest=dest)
    ref = asset.register_from_upload_url(
        photo_url=str(raw.get("photo_url") or ""),
        saved_as=str(raw.get("saved_as") or "") or None,
        producer="camera.capture",
        mime_type="image/jpeg",
    )
    outputs: dict[str, Any] = {"capture_ref": ref.to_dict()}
    local = str(raw.get("photo_local_path") or "").strip()
    msg = (
        f"capture ok dest={dest}\n"
        f"asset_id: {ref.asset_id}\n"
        f"local: {local}"
    )
    return msg, outputs
