"""Finger-ray vs character-box geometry. Stdlib only (no OpenCV / MediaPipe)."""

from __future__ import annotations

import math
from typing import Any

INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8


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
BODY_CHAR_PX = 48.0
TITLE_CHAR_PX = 88.0


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
      ray enters FIRST (smallest entry_t) is the target — "the closest character
      on the finger ray". This is the authoritative mode.
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
                # angle between finger direction and vector to box center
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
    # Cone mode uses a generous angle (3x the strict ray threshold) so that
    # characters near the fingertip but off the narrow ray (e.g. a vertical
    # column where the pointed glyph sits below the ray line) still enter as
    # cone candidates. They rank below ray hits but can appear in top-3.
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
        # Take the better of the ray/cone score and the fingertip-neighbour score.
        # The neighbour score rescues glyphs the finger points beside (ray misses
        # them) without displacing cases where the ray already hits the target.
        chosen = None
        if metrics is not None and (lat is None or metrics["score"] >= lat["score"]):
            chosen = metrics
        elif lat is not None:
            chosen = lat
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
    # decorative header). Off-ray (lateral/cone) candidates get the title filter
    # so headers don't crowd out body text. Then merge everything by score: a
    # fingertip neighbour whose lateral score beats a ray hit's ray score ranks
    # above it (the finger can point beside the glyph, not just down the ray).
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
