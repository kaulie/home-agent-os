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
from typing import Callable

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


_CHECKERS: dict[str, Checker] = {
    "camera.capture": _check_camera_capture,
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
