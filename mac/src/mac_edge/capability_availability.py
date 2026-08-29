"""Capability availability probe — Runtime calls before execute.

Contract:
  is_available(capability_id) -> Availability
  - Default: ok=True (no probe).
  - Special cases (e.g. camera.capture / GoPro): cheap probe so Runtime fails fast
    instead of waiting through a long join/shutter timeout.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from mac_edge.config import Config

log = logging.getLogger("mac_edge.capability_availability")


@dataclass(frozen=True)
class Availability:
    ok: bool
    msg: str = ""

    @staticmethod
    def available(msg: str = "") -> "Availability":
        return Availability(ok=True, msg=msg)

    @staticmethod
    def unavailable(msg: str) -> "Availability":
        text = (msg or "").strip() or "capability unavailable"
        return Availability(ok=False, msg=text)


Checker = Callable[[Config | None], Availability]


def _default_available(_config: Config | None = None) -> Availability:
    return Availability.available()


def _check_camera_capture(config: Config | None = None) -> Availability:
    from mac_edge.plugins.gopro_camera import is_available as gopro_available

    return gopro_available(config=config)


def _check_reading_stage(_config: Config | None = None) -> Availability:
    from mac_edge.plugins.point_to_character import is_available as character_available

    return character_available(_config)


def _check_reading_point_to_character(config: Config | None = None) -> Availability:
    for part in ("reading.detect_finger", "reading.ocr_at_finger", "reading.rank_pointed"):
        avail = is_available(part, config=config)
        if not avail.ok:
            return avail
    return Availability.available()


def _check_camera_capture_and_upload(config: Config | None = None) -> Availability:
    capture = is_available("camera.capture", config=config)
    if not capture.ok:
        return capture
    upload = is_available("asset.upload", config=config)
    if not upload.ok:
        return upload
    return Availability.available()


def _check_netease_music(_config: Config | None = None) -> Availability:
    from mac_edge.plugins.netease_music import is_available as ncm_available

    return ncm_available(_config)


_CHECKERS: dict[str, Checker] = {
    "camera.capture": _check_camera_capture,
    "camera.capture_and_upload": _check_camera_capture_and_upload,
    "reading.detect_finger": _check_reading_stage,
    "reading.ocr_at_finger": _check_reading_stage,
    "reading.rank_pointed": _check_reading_stage,
    "reading.point_to_character": _check_reading_point_to_character,
    "music.play": _check_netease_music,
    "music.cache": _check_netease_music,
    "music.pause": _check_netease_music,
    "music.resume": _check_netease_music,
    "music.stop": _check_netease_music,
    "music.next": _check_netease_music,
    "music.previous": _check_netease_music,
}


def is_available(capability_id: str, *, config: Config | None = None) -> Availability:
    """Runtime entry: probe before execute. Unknown caps → available."""
    cap = str(capability_id or "").strip()
    if not cap:
        return Availability.unavailable("capability_id 为空")
    checker = _CHECKERS.get(cap, _default_available)
    try:
        result = checker(config)
    except Exception as e:  # noqa: BLE001 — availability must never hang the executor
        log.warning("is_available crashed cap=%s: %s", cap, e)
        return Availability.unavailable(f"{cap} 不可用：探测失败（{e}）")
    if not isinstance(result, Availability):
        return Availability.available()
    if not result.ok:
        log.info("is_available cap=%s unavailable: %s", cap, result.msg)
    return result


def register_checker(capability_id: str, checker: Checker) -> None:
    """Tests / plugins may register additional checkers."""
    cid = str(capability_id or "").strip()
    if cid:
        _CHECKERS[cid] = checker


def snapshot_services(
    services: list[dict[str, Any]],
    *,
    config: Config | None = None,
) -> list[dict[str, Any]]:
    """Build a heartbeat availability snapshot over declared services.

    For each declared capability, run is_available() and inject
    {available: bool, observed_at: float}. DECLARED-but-unavailable caps
    stay in the list (Brain keeps the Declaration) but carry available=false
    so Brain's schedulable map filters them out (two-phase check, phase 1).
    Unknown caps without a checker default to available (legacy compat).
    """
    import time
    out: list[dict[str, Any]] = []
    for svc in services or []:
        if not isinstance(svc, dict):
            continue
        svc_out = dict(svc)
        caps_out: list[dict[str, Any]] = []
        for cap in svc.get("capabilities") or []:
            if not isinstance(cap, dict):
                caps_out.append(cap)
                continue
            cap_out = dict(cap)
            cid = str(cap.get("capability_id") or "").strip()
            if cid:
                avail = is_available(cid, config=config)
                cap_out["available"] = bool(avail.ok)
                cap_out["observed_at"] = time.time()
                if not avail.ok and avail.msg:
                    cap_out.setdefault("unavailable_reason", avail.msg)
            caps_out.append(cap_out)
        svc_out["capabilities"] = caps_out
        out.append(svc_out)
    return out
