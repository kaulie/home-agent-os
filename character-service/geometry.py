"""Finger-ray vs character-box geometry. Stdlib only (no OpenCV / MediaPipe)."""

from __future__ import annotations

import math
from typing import Any

WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_MCP, RING_PIP, RING_TIP = 13, 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20

# (name, mcp, pip_or_ip, dip_or_ip, tip) — MediaPipe Hands indices.
POINTING_FINGERS = (
    ("thumb", THUMB_MCP, THUMB_IP, THUMB_IP, THUMB_TIP),
    ("index", INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP),
    ("middle", MIDDLE_MCP, MIDDLE_PIP, 11, MIDDLE_TIP),
    ("ring", RING_MCP, RING_PIP, 15, RING_TIP),
    ("pinky", PINKY_MCP, PINKY_PIP, 19, PINKY_TIP),
)
# When multiple digits are extended, the one whose tip reaches farthest from
# the wrist is the pointer. Only call ambiguous when the top two are within
# this ratio (e.g. index+middle both fully extended — a peace sign, not a
# point). 1.1: index tip ~400 vs middle ~352 (intent 8024) clears it; two
# equally-extended fingers (~1.0) stay ambiguous.
DOMINANT_TIP_RATIO = 1.1
# Within the palm-forward cluster (fingers reaching toward the page), a modest
# reach gap is enough to pick the pointer (8022 index vs middle).
DOMINANT_REACH_CLUSTER_RATIO = 1.03
PALM_FORWARD_CLUSTER_FRAC = 0.92
# Spread-hand grip on a book: every digit passes is_extended_digit, but the
# digit actually touching the target glyph is a spatial outlier from the fan.
GRIP_PATTERN_MIN_DIGITS = 4
DOMINANT_ISOLATION_RATIO = 1.25
MIN_ISOLATION_PX = 35.0
# Thumb pressing beside a fanned grip points across the palm (intent 239 缴).
THUMB_LATERAL_RATIO = 1.35
MIN_THUMB_LATERAL_PX = 80.0
AMBIGUOUS_FINGER_MSG = "图里有多根手指，系统无法判断你指的是哪个字。"


def as_xyxy(bbox: Any) -> list[float]:
    if bbox is None:
        return [0.0, 0.0, 0.0, 0.0]
    nums = [float(n) for n in bbox]
    if len(nums) != 4:
        return [0.0, 0.0, 0.0, 0.0]
    x1, y1, x2, y2 = nums
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]


def bbox_center(bbox: list[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = as_xyxy(bbox)
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def bbox_wh(bbox: list[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = as_xyxy(bbox)
    return (max(x2 - x1, 1.0), max(y2 - y1, 1.0))


def vec_len(x: float, y: float) -> float:
    return math.hypot(x, y)


def vec_norm(x: float, y: float) -> tuple[float, float]:
    n = vec_len(x, y)
    if n < 1e-9:
        return (0.0, 0.0)
    return (x / n, y / n)


def dot(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * bx + ay * by


def angle_deg(ax: float, ay: float, bx: float, by: float) -> float:
    na = vec_len(ax, ay)
    nb = vec_len(bx, by)
    if na < 1e-9 or nb < 1e-9:
        return 180.0
    c = max(-1.0, min(1.0, dot(ax, ay, bx, by) / (na * nb)))
    return math.degrees(math.acos(c))


def finger_ray(
    landmarks: dict[int, tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """(tip origin, unit finger direction) in image pixels.

    Prefers MCP->TIP (knuckle to tip): the longest, most stable baseline that
    stays correct for bent fingers where the last phalanx (DIP->TIP) curls.
    Falls back to PIP->TIP then DIP->TIP when earlier joints are unavailable.
    """
    tip = landmarks.get(INDEX_TIP)
    if tip is None:
        return None
    for base_idx in (INDEX_MCP, INDEX_PIP, INDEX_DIP):
        base = landmarks.get(base_idx)
        if base is None:
            continue
        dx, dy = tip[0] - base[0], tip[1] - base[1]
        if vec_len(dx, dy) < 1e-9:
            continue
        ux, uy = vec_norm(dx, dy)
        return (tip, (ux, uy))
    return None


def _digit_ray(
    landmarks: dict[int, tuple[float, float]],
    mcp: int,
    dip: int,
    tip: int,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Prefer MCP→TIP (overall finger direction); fall back to DIP→TIP.

    MCP→TIP gives the stable knuckle-to-tip baseline that stays correct for
    slightly bent fingers where the last phalanx (DIP→TIP) curls in a different
    direction.  This matches finger_ray's behaviour for partial landmarks.
    """
    origin = landmarks.get(tip)
    if origin is None:
        return None
    for base_idx in (mcp, dip):
        base = landmarks.get(base_idx)
        if base is None:
            continue
        dx, dy = origin[0] - base[0], origin[1] - base[1]
        if vec_len(dx, dy) < 1e-9:
            continue
        ux, uy = vec_norm(dx, dy)
        return (origin, (ux, uy))
    return None


def is_extended_digit(
    landmarks: dict[int, tuple[float, float]],
    mcp: int,
    pip: int,
    tip: int,
) -> bool:
    """True when this digit is stretched out (a pointing finger), not a fist curl."""
    wrist = landmarks.get(WRIST)
    p_mcp = landmarks.get(mcp)
    p_pip = landmarks.get(pip)
    p_tip = landmarks.get(tip)
    if wrist is None or p_mcp is None or p_pip is None or p_tip is None:
        return False
    d_tip = vec_len(p_tip[0] - wrist[0], p_tip[1] - wrist[1])
    d_pip = vec_len(p_pip[0] - wrist[0], p_pip[1] - wrist[1])
    d_mcp = vec_len(p_mcp[0] - wrist[0], p_mcp[1] - wrist[1])
    if d_tip < d_mcp * 1.12 or d_tip < d_pip * 1.02:
        return False
    span = vec_len(p_tip[0] - p_mcp[0], p_tip[1] - p_mcp[1])
    chain = vec_len(p_pip[0] - p_mcp[0], p_pip[1] - p_mcp[1]) + vec_len(
        p_tip[0] - p_pip[0], p_tip[1] - p_pip[1]
    )
    if chain < 1e-6 or span < 0.70 * chain:
        return False
    mid = landmarks.get(MIDDLE_MCP) or p_mcp
    palm = vec_len(mid[0] - wrist[0], mid[1] - wrist[1])
    if span < 0.28 * max(palm, d_mcp, 1.0):
        return False
    return True


def _palm_axes(
    landmarks: dict[int, tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None:
    wrist = landmarks.get(WRIST)
    mid = landmarks.get(MIDDLE_MCP)
    if wrist is None or mid is None:
        return None
    fwd = vec_norm(mid[0] - wrist[0], mid[1] - wrist[1])
    lat = (-fwd[1], fwd[0])
    return wrist, fwd, lat


def _enrich_digit_metrics(
    landmarks: dict[int, tuple[float, float]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    axes = _palm_axes(landmarks)
    if axes is None:
        return candidates
    wrist, fwd, lat = axes
    tips = [c["origin"] for c in candidates]
    for cand in candidates:
        tip = cand["origin"]
        vx, vy = tip[0] - wrist[0], tip[1] - wrist[1]
        cand["forward"] = dot(vx, vy, fwd[0], fwd[1])
        cand["lateral"] = abs(dot(vx, vy, lat[0], lat[1]))
        if len(tips) > 1:
            cand["isolation"] = min(
                vec_len(tip[0] - other[0], tip[1] - other[1])
                for other in tips
                if other != tip
            )
        else:
            cand["isolation"] = 0.0
    return candidates


def _strip_digit_metrics(candidate: dict[str, Any]) -> dict[str, Any]:
    out = dict(candidate)
    for key in ("reach", "forward", "lateral", "isolation", "adj_isolation"):
        out.pop(key, None)
    return out


def _thumb_index_splay_override(
    chosen: dict[str, Any],
    landmarks: dict[int, tuple[float, float]],
) -> dict[str, Any]:
    """Thumb reach can dominate a splayed grip even when the index is the pointer."""
    if chosen.get("name") != "thumb":
        return chosen
    idx_tip = landmarks.get(INDEX_TIP)
    idx_mcp = landmarks.get(INDEX_MCP)
    if not idx_tip or not idx_mcp:
        return chosen
    origin = chosen["origin"]
    dx = idx_tip[0] - origin[0]
    dy = idx_tip[1] - origin[1]
    if vec_len(dx, dy) >= 30:
        return chosen
    rdx, rdy = idx_tip[0] - idx_mcp[0], idx_tip[1] - idx_mcp[1]
    if vec_len(rdx, rdy) <= 1e-9:
        return chosen
    ux, uy = vec_norm(rdx, rdy)
    updated = dict(chosen)
    updated["direction"] = (ux, uy)
    return updated


def _choose_pointing_digit(
    landmarks: dict[int, tuple[float, float]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(candidates) <= 1:
        return candidates

    enriched = _enrich_digit_metrics(landmarks, [dict(c) for c in candidates])

    by_reach = sorted(enriched, key=lambda d: float(d.get("reach") or 0.0), reverse=True)
    if float(by_reach[0]["reach"]) >= float(by_reach[1]["reach"]) * DOMINANT_TIP_RATIO:
        chosen = _thumb_index_splay_override(by_reach[0], landmarks)
        out = [_strip_digit_metrics(chosen)]
        if out:
            out[0]["signal"] = "reach"
        return out

    if len(enriched) >= GRIP_PATTERN_MIN_DIGITS:
        max_forward = max(float(c.get("forward") or 0.0) for c in enriched)
        if max_forward > 1e-6:
            for cand in enriched:
                fwd_frac = float(cand.get("forward") or 0.0) / max_forward
                cand["adj_isolation"] = float(cand.get("isolation") or 0.0) * fwd_frac
        else:
            for cand in enriched:
                cand["adj_isolation"] = float(cand.get("isolation") or 0.0)
        by_iso = sorted(enriched, key=lambda d: float(d.get("adj_isolation") or 0.0), reverse=True)
        top_iso = float(by_iso[0].get("adj_isolation") or 0.0)
        second_iso = float(by_iso[1].get("adj_isolation") or 0.0)
        if top_iso >= MIN_ISOLATION_PX and top_iso >= second_iso * DOMINANT_ISOLATION_RATIO:
            out = [_strip_digit_metrics(by_iso[0])]
            if out:
                out[0]["signal"] = "grip"
            return out

    max_forward = max(float(c.get("forward") or 0.0) for c in enriched)
    cluster = [
        c
        for c in enriched
        if float(c.get("forward") or 0.0) >= max_forward * PALM_FORWARD_CLUSTER_FRAC
    ]
    if len(cluster) >= 2:
        cluster.sort(key=lambda d: float(d.get("reach") or 0.0), reverse=True)
        if float(cluster[0]["reach"]) >= float(cluster[1]["reach"]) * DOMINANT_REACH_CLUSTER_RATIO:
            out = [_strip_digit_metrics(cluster[0])]
            if out:
                out[0]["signal"] = "cluster"
            return out
    elif len(cluster) == 1:
        out = [_strip_digit_metrics(cluster[0])]
        if out:
            out[0]["signal"] = "cluster"
        return out

    thumb = next((c for c in enriched if c.get("name") == "thumb"), None)
    if thumb is not None and len(enriched) >= GRIP_PATTERN_MIN_DIGITS:
        others = [c for c in enriched if c.get("name") != "thumb"]
        if others:
            max_other_lat = max(float(c.get("lateral") or 0.0) for c in others)
            thumb_lat = float(thumb.get("lateral") or 0.0)
            if (
                thumb_lat >= MIN_THUMB_LATERAL_PX
                and thumb_lat >= max_other_lat * THUMB_LATERAL_RATIO
            ):
                out = [_strip_digit_metrics(thumb)]
                if out:
                    out[0]["signal"] = "thumb_lateral"
                return out

    out = [_strip_digit_metrics(c) for c in enriched]
    for o in out:
        o["signal"] = "ambiguous"
    return out


def _joint_in_bounds(
    point: tuple[float, float],
    width: int,
    height: int,
    *,
    margin: float = 4.0,
) -> bool:
    x, y = point
    return margin <= x <= width - margin and margin <= y <= height - margin


def resolve_digit_origin(
    landmarks: dict[int, tuple[float, float]],
    digit_name: str,
    width: int,
    height: int,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Use an in-bounds PIP/MCP when MediaPipe places TIP above the frame."""
    for name, mcp, pip, dip, tip_idx in POINTING_FINGERS:
        if name != digit_name:
            continue
        ray = _digit_ray(landmarks, mcp, dip, tip_idx)
        if ray is None:
            return None
        origin, direction = ray
        if _joint_in_bounds(origin, width, height):
            return origin, direction
        for idx in (pip, mcp):
            pt = landmarks.get(idx)
            if pt and _joint_in_bounds(pt, width, height):
                return pt, direction
        if name == "thumb":
            cmc = landmarks.get(THUMB_CMC)
            if cmc and _joint_in_bounds(cmc, width, height):
                return cmc, direction
        return origin, direction
    return None


def fallback_in_bounds_origin(
    landmarks: dict[int, tuple[float, float]],
    width: int,
    height: int,
) -> tuple[tuple[float, float], tuple[float, float], str] | None:
    """Grip at the bottom edge: every TIP is off-frame — anchor on the highest joint still visible."""
    best: tuple[tuple[float, float], tuple[float, float], str, float] | None = None
    for name, mcp, pip, dip, tip_idx in POINTING_FINGERS:
        ray = _digit_ray(landmarks, mcp, dip, tip_idx)
        if ray is None:
            continue
        _, direction = ray
        for idx in (pip, mcp):
            pt = landmarks.get(idx)
            if pt and _joint_in_bounds(pt, width, height):
                score = pt[1]
                if best is None or score < best[3]:
                    best = (pt, direction, name, score)
    if best is None:
        return None
    return best[0], best[1], best[2]


def _all_tips_above_frame(
    landmarks: dict[int, tuple[float, float]],
    height: int,
    *,
    margin: float = 4.0,
) -> bool:
    """True when every fingertip sits above the top edge (bottom-of-photo grip)."""
    saw_tip = False
    for _, _, _, _, tip_idx in POINTING_FINGERS:
        tip = landmarks.get(tip_idx)
        if tip is None:
            continue
        saw_tip = True
        if tip[1] >= margin:
            return False
    return saw_tip


def project_bottom_edge_grip(
    landmarks: dict[int, tuple[float, float]],
    digit_name: str,
    width: int,
    height: int,
    *,
    margin: float = 4.0,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Project from an in-bounds knuckle toward the page when tips are off-screen.

    Tall phone photos often crop the hand at the bottom: MediaPipe still sees the
    wrist and MCPs, but every TIP is above y=0. Clamping backward along the digit
    ray lands on the top margin (empty area). Walk *forward* along the flipped
    ray from the visible knuckle until we reach the book below the hand.
    """
    if not _all_tips_above_frame(landmarks, height, margin=margin):
        return None
    wrist = landmarks.get(WRIST)
    min_y = (wrist[1] + 50.0) if wrist else 80.0
    for name, mcp, pip, dip, tip_idx in POINTING_FINGERS:
        if digit_name and name != digit_name:
            continue
        ray = _digit_ray(landmarks, mcp, dip, tip_idx)
        if ray is None:
            continue
        _, direction = ray
        flip = (-direction[0], -direction[1])
        if vec_len(flip[0], flip[1]) < 1e-9:
            continue
        anchor = None
        for idx in (mcp, pip):
            pt = landmarks.get(idx)
            if pt and _joint_in_bounds(pt, width, height):
                anchor = pt
                break
        if anchor is None and name == "thumb":
            cmc = landmarks.get(THUMB_CMC)
            if cmc and _joint_in_bounds(cmc, width, height):
                anchor = cmc
        if anchor is None:
            continue
        for step in range(30, int(max(width, height)), 8):
            px = anchor[0] + flip[0] * step
            py = anchor[1] + flip[1] * step
            if not (margin <= px <= width - margin and margin <= py <= height - margin):
                continue
            if py >= min_y:
                return (px, py), flip
    return None


def clamp_finger_tip_to_image(
    origin: tuple[float, float],
    direction: tuple[float, float],
    width: int,
    height: int,
    *,
    margin: float = 4.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Pull an off-frame fingertip back along its ray into the image.

    MediaPipe often places TIP above the top edge when the hand grips the
    bottom of a tall photo. OCR windows are anchored on TIP, so we walk
  backward along the finger direction until the point lands inside the frame.
    """
    x, y = origin
    if margin <= x <= width - margin and margin <= y <= height - margin:
        return origin, direction
    dx, dy = direction
    if vec_len(dx, dy) < 1e-9:
        return origin, direction
    max_step = int(max(width, height) * 2)
    for step in range(1, max_step, 2):
        px = x - dx * step
        py = y - dy * step
        if margin <= px <= width - margin and margin <= py <= height - margin:
            return (px, py), direction
    return origin, direction


def extended_fingers(
    landmarks: dict[int, tuple[float, float]],
) -> list[dict[str, Any]]:
    """All independent extended digits with origin/direction/reach — no dominance
    filtering. Used by the multi-finger OCR-based selection (Stage 2): when 3+
    fingers are extended, reach alone is unreliable, so the caller collects every
    candidate and lets text proximity decide.
    """
    if not landmarks:
        return []
    full = all(i in landmarks for i in range(21))
    if not full:
        ray = finger_ray(landmarks)
        if ray is None:
            return []
        origin, direction = ray
        return [{"name": "index", "origin": origin, "direction": direction, "reach": 0.0}]
    out: list[dict[str, Any]] = []
    wrist = landmarks.get(WRIST)
    for name, mcp, pip, dip, tip in POINTING_FINGERS:
        if not is_extended_digit(landmarks, mcp, pip, tip):
            continue
        ray = _digit_ray(landmarks, mcp, dip, tip)
        if ray is None:
            continue
        origin, direction = ray
        reach = vec_len(origin[0] - wrist[0], origin[1] - wrist[1]) if wrist else 0.0
        out.append({"name": name, "origin": origin, "direction": direction, "reach": reach})
    return out


def pointing_fingers(
    landmarks: dict[int, tuple[float, float]],
) -> list[dict[str, Any]]:
    """Independent extended digits on one hand. Partial (index-only) dumps fall back to finger_ray.

    When multiple digits are extended, the one whose tip is farthest from the
    wrist is the pointer (e.g. index pointing with thumb naturally splayed —
    the index tip reaches much farther). Only fall back to ambiguous when no
    single digit clearly dominates (ratio < DOMINANT_TIP_RATIO).
    """
    if not landmarks:
        return []
    full = all(i in landmarks for i in range(21))
    if not full:
        ray = finger_ray(landmarks)
        if ray is None:
            return []
        origin, direction = ray
        return [{"name": "index", "origin": origin, "direction": direction}]
    out: list[dict[str, Any]] = []
    for name, mcp, pip, dip, tip in POINTING_FINGERS:
        if not is_extended_digit(landmarks, mcp, pip, tip):
            continue
        ray = _digit_ray(landmarks, mcp, dip, tip)
        if ray is None:
            continue
        origin, direction = ray
        wrist = landmarks.get(WRIST)
        reach = vec_len(origin[0] - wrist[0], origin[1] - wrist[1]) if wrist else 0.0
        out.append({"name": name, "origin": origin, "direction": direction, "reach": reach})
    if not out:
        return []
    chosen_list = _choose_pointing_digit(landmarks, out)
    if len(chosen_list) == 1:
        item = chosen_list[0]
        return [
            {
                "name": item["name"],
                "origin": item["origin"],
                "direction": item["direction"],
                "signal": item.get("signal", "single"),
            }
        ]
    return [
        {
            "name": item["name"],
            "origin": item["origin"],
            "direction": item["direction"],
            "signal": item.get("signal", "ambiguous"),
        }
        for item in chosen_list
    ]


def ray_aabb_t(
    origin: tuple[float, float],
    direction: tuple[float, float],
    bbox: list[float],
) -> tuple[float, float] | None:
    ox, oy = origin
    dx, dy = direction
    x1, y1, x2, y2 = as_xyxy(bbox)
    tmin, tmax = -1e9, 1e9
    for origin_i, dir_i, lo, hi in ((ox, dx, x1, x2), (oy, dy, y1, y2)):
        if abs(dir_i) < 1e-9:
            if origin_i < lo or origin_i > hi:
                return None
            continue
        t1 = (lo - origin_i) / dir_i
        t2 = (hi - origin_i) / dir_i
        if t1 > t2:
            t1, t2 = t2, t1
        tmin = max(tmin, t1)
        tmax = min(tmax, t2)
        if tmin > tmax:
            return None
    return (tmin, tmax)


def intersection_length(
    origin: tuple[float, float],
    direction: tuple[float, float],
    bbox: list[float],
    max_t: float,
) -> float:
    hit = ray_aabb_t(origin, direction, bbox)
    if hit is None:
        return 0.0
    tmin, tmax = hit
    lo = max(tmin, 0.0)
    hi = min(tmax, max_t)
    return max(0.0, hi - lo)


def perpendicular_distance(
    origin: tuple[float, float],
    direction: tuple[float, float],
    point: tuple[float, float],
) -> float:
    vx, vy = point[0] - origin[0], point[1] - origin[1]
    dx, dy = direction
    return abs(vx * dy - vy * dx)


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF
        or 0x3400 <= o <= 0x4DBF
        or 0xF900 <= o <= 0xFAFF
        or 0x2E80 <= o <= 0x2EFF
        or 0x3000 <= o <= 0x303F
        or 0xFF00 <= o <= 0xFFEF
    )


def split_text_units(text: str) -> list[str]:
    units: list[str] = []
    buf: list[str] = []
    for ch in text:
        if ch.isspace():
            if buf:
                units.append("".join(buf))
                buf = []
            continue
        if is_cjk(ch):
            if buf:
                units.append("".join(buf))
                buf = []
            units.append(ch)
        else:
            buf.append(ch)
    if buf:
        units.append("".join(buf))
    return [u for u in units if u]


def bbox_contains(
    point: tuple[float, float], bbox: list[float], pad: float = 0.0
) -> bool:
    x1, y1, x2, y2 = as_xyxy(bbox)
    return (x1 - pad) <= point[0] <= (x2 + pad) and (y1 - pad) <= point[1] <= (y2 + pad)


def has_cjk(text: str) -> bool:
    return any(is_cjk(ch) for ch in text)


def is_line_fragment(bbox: list[float]) -> bool:
    """A line of text misread as a single char: very wide and short.
    These crowd out real single chars when they happen to clip the fingertip."""
    w, h = bbox_wh(bbox)
    return w > 1.8 * h and w > BODY_CHAR_PX * 1.5


def split_block_to_chars(block: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(block.get("text") or "")
    bbox = as_xyxy(block.get("bbox"))
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return []
    conf = block.get("confidence")
    units = split_text_units(text)
    if not units:
        return []
    if len(units) == 1:
        item: dict[str, Any] = {
            "text": units[0],
            "bbox": [int(round(n)) for n in bbox],
            "split": False,
        }
        if conf is not None:
            item["confidence"] = conf
        return [item]
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    vertical = h > w * 1.2
    n = len(units)
    out: list[dict[str, Any]] = []
    for i, unit in enumerate(units):
        if vertical:
            box = [x1, y1 + h * i / n, x2, y1 + h * (i + 1) / n]
        else:
            box = [x1 + w * i / n, y1, x1 + w * (i + 1) / n, y2]
        item = {
            "text": unit,
            "bbox": [int(round(v)) for v in box],
            "split": True,
            "source_text": text,
        }
        if conf is not None:
            item["confidence"] = conf
        out.append(item)
    return out


def explode_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chars: list[dict[str, Any]] = []
    for block in blocks:
        chars.extend(split_block_to_chars(block))
    return chars


CONTACT_PAD_PX = 8.0
CONTACT_NEAR_PX = 56.0
# 0.4 of the 600px fingertip OCR window — a local neighborhood, not a page search.
CONTACT_WINDOW_PAD_PX = 240.0
CONTACT_GLYPH_FRAC = 1.35
CONTACT_DIST_FRAC = 0.09
CONTACT_SHAFT_PERP_FRAC = 0.40
BODY_CHAR_PX = 48.0
TITLE_CHAR_PX = 88.0


def nearest_point_on_aabb(
    point: tuple[float, float], bbox: list[float]
) -> tuple[float, float]:
    x1, y1, x2, y2 = as_xyxy(bbox)
    px, py = point
    return (min(max(px, x1), x2), min(max(py, y1), y2))


def point_to_aabb_distance(point: tuple[float, float], bbox: list[float]) -> float:
    qx, qy = nearest_point_on_aabb(point, bbox)
    return vec_len(point[0] - qx, point[1] - qy)


def contact_pad_px(body_size: float, max_distance: float) -> float:
    """Scale-aware nail neighborhood.

    CONTACT_PAD_PX=8 is a floor for tight photos; 2k–4k scans need a pad on the
    order of a body glyph (nail just under the character). Cap with a fraction of
    the ranking radius so small synthetic frames stay tight.
    """
    scale = max(body_size, 1.0)
    glyph = CONTACT_GLYPH_FRAC * scale
    near = CONTACT_NEAR_PX * scale / BODY_CHAR_PX
    scaled = max(CONTACT_PAD_PX, glyph, near, CONTACT_WINDOW_PAD_PX)
    cap = max(CONTACT_PAD_PX, CONTACT_DIST_FRAC * max(max_distance, 1.0))
    return min(scaled, cap)


def on_finger_shaft(
    origin: tuple[float, float],
    direction: tuple[float, float],
    point: tuple[float, float],
) -> bool:
    """True when `point` lies on the finger body (behind the tip, along the ray)."""
    vx, vy = point[0] - origin[0], point[1] - origin[1]
    t_along = dot(vx, vy, direction[0], direction[1])
    if t_along >= 0.0:
        return False
    perp = perpendicular_distance(origin, direction, point)
    return perp < CONTACT_SHAFT_PERP_FRAC * max(-t_along, 1.0)


def score_character(
    *,
    origin: tuple[float, float],
    direction: tuple[float, float],
    bbox: list[float],
    max_angle_deg: float,
    max_distance: float,
) -> dict[str, float] | None:
    """Score a character box against the finger ray.

    Two modes, in priority order:
    - "ray": the ray from the fingertip in the finger direction passes through
      the box ahead of the fingertip (within max_distance). The character the
      ray enters FIRST (smallest entry_t) is the target — the closest character
      on the finger ray. This is the authoritative mode.
    - "cone": fallback when no box is directly on the ray. Ranks by perpendicular
      distance to the ray line, then by angular alignment.
    """
    box = as_xyxy(bbox)
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    cx, cy = bbox_center(box)
    w, h = bbox_wh(box)
    char_size = max(w, h)
    vx, vy = cx - origin[0], cy - origin[1]
    dist = vec_len(vx, vy)
    size_s = min(1.0, BODY_CHAR_PX / char_size)

    hit = ray_aabb_t(origin, direction, box)
    if hit is not None:
        tmin, tmax = hit
        lo = max(tmin, 0.0)
        hi = min(tmax, max_distance)
        if hi > lo and hi > 0.0:
            contains = bbox_contains(origin, box, pad=min(CONTACT_PAD_PX, 0.25 * min(w, h)))
            # If the fingertip is inside the box, only treat it as the target when
            # the finger actually points toward the box center. A wide/line box that
            # merely clips the fingertip while the finger points away is incidental.
            if contains and dot(vx, vy, direction[0], direction[1]) <= 0:
                pass  # fall through to cone mode
            else:
                entry_t = lo
                inter_len = hi - lo
                inter_score = min(1.0, inter_len / max(char_size, 1.0))
                entry_score = max(0.0, 1.0 - entry_t / max_distance)
                ang = angle_deg(direction[0], direction[1], vx, vy)
                total = 0.55 * entry_score + 0.25 * inter_score + 0.10 * size_s + (0.10 if contains else 0.0)
                return {
                    "score": total,
                    "mode": "ray",
                    "entry_t": entry_t,
                    "intersection": inter_score,
                    "alignment": 1.0,
                    "distance": entry_score,
                    "center": 1.0 if contains else 0.0,
                    "angle_deg": ang,
                    "pixel_distance": dist,
                }

    if dist < 1e-6:
        return None
    if dot(vx, vy, direction[0], direction[1]) <= 0:
        return None
    ang = angle_deg(direction[0], direction[1], vx, vy)
    cone_max = max_angle_deg * 3.0
    if ang > cone_max:
        return None
    if dist > max_distance:
        return None
    align = max(0.0, 1.0 - ang / cone_max)
    dist_score = max(0.0, 1.0 - dist / max_distance)
    perp = perpendicular_distance(origin, direction, (cx, cy))
    center = max(0.0, 1.0 - perp / max(char_size * 0.5, 1.0))
    total = 0.40 * center + 0.30 * align + 0.20 * dist_score + 0.10 * size_s
    return {
        "score": total,
        "mode": "cone",
        "entry_t": float(dist),
        "intersection": 0.0,
        "alignment": align,
        "distance": dist_score,
        "center": center,
        "angle_deg": ang,
        "pixel_distance": dist,
    }


def lateral_score(
    *,
    origin: tuple[float, float],
    direction: tuple[float, float],
    bbox: list[float],
    max_angle_deg: float,
    max_distance: float,
    body_size: float,
) -> dict[str, float] | None:
    """Fingertip-neighbour score for the case where the finger is placed beside
    the target (the fingertip sits at the target's height, one column over) rather
    than aiming down the ray at it.

    Two-tier model keyed on whether the box's vertical span contains the fingertip
    height (the finger is at this glyph's level):
    - Containing boxes score in a high band. Within it, *horizontal distance* to
      the fingertip dominates (the closest column the finger reaches is the
      target), and centre-y proximity is a tiebreak for glyphs in the same column
      (e.g. an over-tall mis-split neighbour vs. the glyph whose centre is exactly
      at the fingertip).
    - Non-containing boxes score in a low band so a spanning glyph always ranks
      above a merely nearby one.

    ``scale`` is the per-image body character size, so an over-tall box no longer
    inflates its own x-proximity denominator or dilutes its y penalty.
    """
    box = as_xyxy(bbox)
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    cx, cy = bbox_center(box)
    w, h = bbox_wh(box)
    vx, vy = cx - origin[0], cy - origin[1]
    dist = vec_len(vx, vy)
    if dot(vx, vy, direction[0], direction[1]) <= 0.0:
        return None
    if dist > max_distance:
        return None
    ang = angle_deg(direction[0], direction[1], vx, vy)
    cone_max = max_angle_deg * 3.0
    if ang > cone_max:
        return None
    dir_align = max(0.0, 1.0 - ang / cone_max)
    scale = max(body_size, 1.0)
    contains = box[1] <= origin[1] <= box[3]
    # The containing-neighbour model only applies when the finger points roughly
    # sideways at the glyph beside the fingertip. When the finger points steeply
    # up/down (angle from horizontal > ~32°), the finger is *aiming* along the ray
    # at a distant glyph, so a containing box here is incidental — fall through to
    # the low-band score and let the authoritative ray hit win (e.g. a finger
    # pointing up at 渊 while the fingertip happens to sit at 为's level).
    horiz_deg = math.degrees(math.atan2(abs(direction[1]), max(abs(direction[0]), 1e-6)))
    if contains and horiz_deg <= 32.0:
        # High band: the finger points sideways at this glyph. Horizontal gap to
        # the fingertip dominates (the closest column the finger reaches is the
        # target); centre-y proximity breaks ties within the same column (an
        # over-tall mis-split neighbour vs. the glyph whose centre is exactly at
        # the fingertip). dir_align is a small bonus.
        hgap = abs(cx - origin[0])
        hgap_score = max(0.0, 1.0 - hgap / (scale * 8.0))
        y_tie = max(0.0, 1.0 - abs(cy - origin[1]) / scale)
        total = 0.41 + 0.50 * hgap_score + 0.10 * y_tie
        center_score = y_tie
        x_prox = hgap_score
    else:
        edge_gap = min(abs(origin[1] - box[1]), abs(origin[1] - box[3]))
        y_align = 0.4 * max(0.0, 1.0 - edge_gap / scale) if not contains else 0.4
        hgap = abs(cx - origin[0])
        x_prox = max(0.0, 1.0 - hgap / (scale * 4.0))
        total = 0.55 * x_prox + 0.25 * y_align + 0.12 * dir_align
        center_score = y_align
    return {
        "score": total,
        "mode": "lateral",
        "entry_t": float(dist),
        "intersection": 0.0,
        "alignment": dir_align,
        "distance": x_prox,
        "center": center_score,
        "angle_deg": ang,
        "pixel_distance": dist,
    }


def contact_covers_many_glyphs(
    box: list[float], others: list[dict[str, Any]], body_size: float
) -> bool:
    """True when `box` contains the centers of two+ smaller body-sized glyphs.

    Catches a misplaced OCR box that landed on top of a real line (e.g. 牵
    covering 的+崭) without dropping a well-split character that only shares
    an edge or a dual-window duplicate of itself.
    """
    x1, y1, x2, y2 = as_xyxy(box)
    area = max((x2 - x1) * (y2 - y1), 1.0)
    seen: set[str] = set()
    for other in others:
        ob = other.get("bbox")
        if not ob:
            continue
        ob = as_xyxy(ob)
        if ob == [x1, y1, x2, y2]:
            continue
        oa = max((ob[2] - ob[0]) * (ob[3] - ob[1]), 1.0)
        if oa >= 0.9 * area:
            continue
        ow, oh = bbox_wh(ob)
        if max(ow, oh) > 1.8 * max(body_size, 1.0):
            continue
        cx, cy = bbox_center(ob)
        if not (x1 <= cx <= x2 and y1 <= cy <= y2):
            continue
        text = str(other.get("text") or "")
        if not text or text in seen:
            continue
        seen.add(text)
        if len(seen) >= 2:
            return True
    return False


def contact_score(
    *,
    origin: tuple[float, float],
    direction: tuple[float, float],
    bbox: list[float],
    body_size: float,
    max_distance: float,
) -> dict[str, float] | None:
    """Nail-adjacent score. First-class class alongside ray-ahead ranking.

    Glyphs in a scale-aware pad around the TIP are kept even when
    ``dot(center - TIP, direction) ≤ 0`` (the nail is pressing next to / just
    under the glyph). Ahead-of-ray glyphs keep ray/lateral only — contact is the
    behind-ray rescue, not a near-tip override of a high-band lateral neighbour.
    Finger-shaft boxes (straight behind the tip toward the knuckle) are excluded.
    """
    box = as_xyxy(bbox)
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    pad = contact_pad_px(body_size, max_distance)
    edge_gap = point_to_aabb_distance(origin, box)
    if edge_gap > pad:
        return None
    nearest = nearest_point_on_aabb(origin, box)
    if on_finger_shaft(origin, direction, nearest):
        return None
    cx, cy = bbox_center(box)
    vx, vy = cx - origin[0], cy - origin[1]
    dist = vec_len(vx, vy)
    pressing = bbox_contains(origin, box, pad=0.0)
    behind = dist < 1e-6 or dot(vx, vy, direction[0], direction[1]) <= 0.0
    if not pressing and not behind:
        return None
    # Contact is a placed-nail gesture (finger along the page). When the finger
    # aims steeply up/down the ray, a box that merely clips the TIP is incidental
    # — same 32° gate as lateral_score (渊 while the tip sits at 了/为).
    horiz_deg = math.degrees(
        math.atan2(abs(direction[1]), max(abs(direction[0]), 1e-6))
    )
    if horiz_deg > 32.0:
        return None
    w, h = bbox_wh(box)
    char_size = max(w, h)
    scale = max(body_size, 1.0)
    edge_s = max(0.0, 1.0 - edge_gap / max(pad, 1.0))
    dist_s = max(0.0, 1.0 - dist / max(pad + 0.5 * scale, 1.0))
    size_s = min(1.0, BODY_CHAR_PX / char_size)
    if pressing:
        total = 0.72 + 0.18 * size_s + 0.08 * edge_s
    else:
        total = min(0.78, 0.50 + 0.16 * edge_s + 0.12 * dist_s + 0.08 * size_s)
    ang = 0.0 if dist < 1e-6 else angle_deg(direction[0], direction[1], vx, vy)
    return {
        "score": total,
        "mode": "contact",
        "entry_t": float(edge_gap),
        "intersection": 0.0,
        "alignment": 1.0,
        "distance": edge_s,
        "center": dist_s,
        "angle_deg": ang,
        "pixel_distance": dist,
    }


def prefer_body_text(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop decorative title boxes when body-sized glyphs exist."""
    body = []
    for r in ranked:
        w, h = bbox_wh(r.get("bbox") or [0, 0, 0, 0])
        if max(w, h) <= TITLE_CHAR_PX:
            body.append(r)
    return body if body else ranked


def rank_characters(
    chars: list[dict[str, Any]],
    origin: tuple[float, float],
    direction: tuple[float, float],
    *,
    max_angle_deg: float,
    max_distance: float,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    # Per-image body character size: robust median of candidate heights, so an
    # over-tall mis-split box or a decorative title does not inflate the scale.
    heights = [bbox_wh(c.get("bbox") or [0, 0, 0, 0])[1] for c in chars if not is_line_fragment(c.get("bbox") or [0, 0, 0, 0])]
    if heights:
        heights_sorted = sorted(heights)
        body_size = heights_sorted[len(heights_sorted) // 2]
    else:
        body_size = BODY_CHAR_PX
    for ch in chars:
        if is_line_fragment(ch.get("bbox") or [0, 0, 0, 0]):
            continue
        metrics = score_character(
            origin=origin,
            direction=direction,
            bbox=ch["bbox"],
            max_angle_deg=max_angle_deg,
            max_distance=max_distance,
        )
        lat = lateral_score(
            origin=origin,
            direction=direction,
            bbox=ch["bbox"],
            max_angle_deg=max_angle_deg,
            max_distance=max_distance,
            body_size=body_size,
        )
        contact = contact_score(
            origin=origin,
            direction=direction,
            bbox=ch["bbox"],
            body_size=body_size,
            max_distance=max_distance,
        )
        if contact is not None and contact_covers_many_glyphs(
            ch["bbox"], chars, body_size
        ):
            contact = None
        # Take the best of ray/cone, fingertip-neighbour, and nail-contact.
        # Contact rescues glyphs the nail is pressing that sit behind a collapsed
        # ray, without replacing ray-ahead ranking when the ray already hits.
        chosen = None
        for cand in (metrics, lat, contact):
            if cand is None:
                continue
            if chosen is None or float(cand["score"]) > float(chosen["score"]):
                chosen = cand
        if chosen is None:
            continue
        item = dict(ch)
        item.update(chosen)
        ranked.append(item)
    cjk = [r for r in ranked if has_cjk(str(r.get("text") or ""))]
    if cjk:
        ranked = cjk

    # Deduplicate by text: keep only the best candidate per unique character
    # so duplicate reads (e.g. the same glyph returned by two OCR windows)
    # do not crowd out other neighbours in top-3.
    best_by_text: dict[str, dict[str, Any]] = {}
    for r in ranked:
        t = str(r.get("text") or "")
        if not t:
            continue
        cur = best_by_text.get(t)
        if cur is None or float(r.get("score") or 0) > float(cur.get("score") or 0):
            best_by_text[t] = r
    ranked = list(best_by_text.values())

    # Deduplicate by box: a hallucinated duplicate that shares another glyph's
    # box (e.g. a misread "四" over a "惜" with the identical bbox) would otherwise
    # crowd the top-3. Keep the highest-scoring candidate per rounded box.
    best_by_box: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    for r in ranked:
        b = r.get("bbox") or [0, 0, 0, 0]
        key = (round(b[0]), round(b[1]), round(b[2]), round(b[3]))
        cur = best_by_box.get(key)
        if cur is None or float(r.get("score") or 0) > float(cur.get("score") or 0):
            best_by_box[key] = r
    ranked = list(best_by_box.values())

    # Ray hits are what the finger actually points at — protect them from the
    # title-size filter (a large glyph the finger points at is a target, not a
    # decorative header). Off-ray (lateral/cone/contact) candidates get the title
    # filter so headers don't crowd out body text. Then merge everything by score:
    # a fingertip neighbour or nail-contact whose score beats a ray hit ranks
    # above it (the finger can press beside the glyph, not just down the ray).
    ray_hits = [r for r in ranked if r.get("mode") == "ray"]
    off_ray = [r for r in ranked if r.get("mode") != "ray"]
    off_ray = prefer_body_text(off_ray)
    ranked = ray_hits + off_ray
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked


def decide(
    ranked: list[dict[str, Any]],
    *,
    min_score: float,
    min_margin: float,
) -> dict[str, Any]:
    if not ranked:
        return {"status": "uncertain", "reason": "no_candidate"}
    top = ranked[0]
    if float(top["score"]) < min_score:
        return {"status": "uncertain", "reason": "low_score", "top": top}
    if len(ranked) >= 2:
        margin = float(top["score"]) - float(ranked[1]["score"])
        if margin < min_margin:
            return {
                "status": "ok_with_alternatives",
                "top": top,
                "alternatives": ranked[1:3],
                "margin": margin,
            }
    return {"status": "ok", "top": top}
