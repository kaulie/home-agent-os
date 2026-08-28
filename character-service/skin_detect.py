"""Skin-segmentation fingertip detector. Drop-in alternative to hands.detect_hands_landmarks.

Same return contract: list[dict[int, tuple[float, float]]] — a list of hands,
each a dict of MediaPipe landmark index -> (x, y) in original-image pixels.

This module only fills INDEX_TIP (8) and INDEX_PIP (6) (a base point behind the
tip). geometry.pointing_fingers falls back to finger_ray when the full 21 are
not present, so two points are enough to produce a finger ray.

No MediaPipe dependency. Pure OpenCV + numpy. Tuned for top-down desk photos
where only a fingertip is in frame (MediaPipe Hands blind spot).
"""

from __future__ import annotations

from typing import Any

# MediaPipe indices reused by geometry.finger_ray / pointing_fingers.
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8

# Skin mask tuning. LOOSE Cr/Cb (works on white paper / dark backgrounds where
# non-skin surfaces have Cr<135; per-camera skin tone varies: iPhone Cr~168 vs
# Android Cr~146, so lower bound stays 135). Saturation cap excludes high-
# saturation printed orange/red text (S>175) that passes the Cr filter on
# document photos. Wooden desk (Cr~142) is a known bad case — handled via user
# guidance, not thresholds (see eval/ALGORITHM_CHANGELOG.md intent 253).
_HSV_LOW = (0, 30, 60)
_HSV_HIGH = (35, 150, 255)
_HSV_LOW2 = (160, 30, 60)  # wrap-around hue for reddish skin
_HSV_HIGH2 = (180, 150, 255)
_YCBCR_LOW = (0, 135, 85)
_YCBCR_HIGH = (255, 180, 135)

_MIN_BLOB_AREA = 800          # px² at the working scale
_WORK_MAX_DIM = 1000          # downscale for speed + denoise
_BASE_BACK_FRAC = 0.55        # base sits this fraction of tip->centroid back from tip
_MIN_ELONGATION = 1.8         # aspect ratio (major/minor) to count as a finger-like blob
_BORDER_MARGIN = 3            # px tolerance for "touching" a border
_LARGE_BLOB_FRAC = 0.10       # blobs > this fraction of image area get an area bonus


class SkinDetectError(Exception):
    pass


def _skin_mask(bgr: Any) -> Any:
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, _HSV_LOW, _HSV_HIGH)
    m2 = cv2.inRange(hsv, _HSV_LOW2, _HSV_HIGH2)
    hsv_mask = m1 | m2

    ycbcr = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    ycbcr_mask = cv2.inRange(ycbcr, _YCBCR_LOW, _YCBCR_HIGH)

    mask = hsv_mask & ycbcr_mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask


def _blob_aspect(contour: Any) -> tuple[float, float, float]:
    """Return (aspect_ratio, major_len, minor_len) from fitEllipse if possible."""
    import cv2
    import numpy as np

    if len(contour) < 5:
        rect = cv2.boundingRect(contour)
        w, h = float(rect[2]), float(rect[3])
        major, minor = max(w, h), max(min(w, h), 1.0)
        return (major / minor, major, minor)
    (cx, cy), (w, h), _ = cv2.fitEllipse(contour)
    major, minor = float(max(w, h)), float(max(min(w, h), 1.0))
    return (major / minor, major, minor)


def _border_tier(contour: Any, img_w: int, img_h: int) -> int:
    """Sort tier based on which image borders the blob touches.

    Lower tier = higher priority.  In top-down book photos the hand enters from
    the bottom (or a side), while printed illustrations sit at the top of the
    page.  A blob touching the bottom border is far more likely to be the real
    hand than one touching only the top.

    0 = touches bottom, 1 = side-only (left/right without top),
    2 = top-only, 3 = no border touch.
    """
    import cv2

    x, y, bw, bh = cv2.boundingRect(contour)
    m = _BORDER_MARGIN
    touches_left = x <= m
    touches_right = x + bw >= img_w - m
    touches_top = y <= m
    touches_bottom = y + bh >= img_h - m
    if touches_bottom:
        return 0
    if (touches_left or touches_right) and not touches_top:
        return 1
    if touches_top and not (touches_left or touches_right or touches_bottom):
        return 2
    return 3


def _farthest_hull_point(contour: Any, centroid: tuple[float, float]) -> tuple[float, float]:
    import cv2
    import numpy as np

    hull = cv2.convexHull(contour)
    pts = hull.reshape(-1, 2)
    cx, cy = centroid
    d2 = (pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2
    i = int(np.argmax(d2))
    return (float(pts[i, 0]), float(pts[i, 1]))


def _fingertip_point(contour: Any, img_w: int, img_h: int) -> tuple[float, float] | None:
    """Fingertip = the hull vertex farthest from the image border the finger
    enters from. A finger poking into frame from the bottom has its tip at the
    top; from the left, tip is at the right; etc. Falls back to farthest-from-
    centroid when the blob doesn't touch a border (whole hand in frame)."""
    import cv2
    import numpy as np

    hull = cv2.convexHull(contour)
    pts = hull.reshape(-1, 2)
    x, y, bw, bh = cv2.boundingRect(contour)
    margin = 3  # px tolerance for "touching" a border
    touches_left = x <= margin
    touches_right = x + bw >= img_w - margin
    touches_top = y <= margin
    touches_bottom = y + bh >= img_h - margin

    if touches_bottom and not touches_top:
        i = int(np.argmin(pts[:, 1]))  # topmost = tip
    elif touches_top and not touches_bottom:
        i = int(np.argmax(pts[:, 1]))  # bottommost = tip
    elif touches_left and not touches_right:
        i = int(np.argmax(pts[:, 0]))  # rightmost = tip
    elif touches_right and not touches_left:
        i = int(np.argmin(pts[:, 0]))  # leftmost = tip
    else:
        return None  # fully in frame or touches opposing borders — use centroid fallback
    return (float(pts[i, 0]), float(pts[i, 1]))


def _blob_to_landmarks(contour: Any, scale: float, img_w: int = 0, img_h: int = 0) -> dict[int, tuple[float, float]] | None:
    import cv2
    import numpy as np

    area = cv2.contourArea(contour)
    if area < _MIN_BLOB_AREA:
        return None
    aspect, major, minor = _blob_aspect(contour)
    if aspect < _MIN_ELONGATION:
        return None  # round blob (face palm / noise), not a finger

    m = cv2.moments(contour)
    if m["m00"] <= 0:
        return None
    cx = m["m10"] / m["m00"]
    cy = m["m01"] / m["m00"]

    # Prefer border-aware fingertip (finger enters from edge, tip points inward);
    # fall back to farthest-from-centroid (whole hand in frame).
    tip = None
    if img_w and img_h:
        tip = _fingertip_point(contour, img_w, img_h)
    if tip is None:
        tip = _farthest_hull_point(contour, (cx, cy))
    # base = point back from tip toward centroid by BASE_BACK_FRAC of the span.
    bx = tip[0] + (_BASE_BACK_FRAC * (cx - tip[0]))
    by = tip[1] + (_BASE_BACK_FRAC * (cy - tip[1]))
    # rescale to original-image pixels
    return {
        INDEX_TIP: (tip[0] * scale, tip[1] * scale),
        INDEX_PIP: (bx * scale, by * scale),
    }


def detect_hands_landmarks(
    image_bgr: Any, max_dim: int = 1600
) -> list[dict[int, tuple[float, float]]]:
    """Skin-segmentation based fingertip detector. Returns [] if none found."""
    import cv2
    import numpy as np

    h, w = image_bgr.shape[:2]
    if max(h, w) > _WORK_MAX_DIM:
        s = _WORK_MAX_DIM / max(h, w)
        small = cv2.resize(image_bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    else:
        s = 1.0
        small = image_bgr

    mask = _skin_mask(small)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    sh, sw = small.shape[:2]
    # Rank by (border_tier, score).  Fingers are moderately elongated (3-8x)
    # and vertical (taller than wide) on top-down book photos.  Horizontal
    # bands (illustration strips, page edges) and extreme aspect ratios
    # (>10x, lines) are deprioritized.  Area is a gate, not a score — a big
    # illustration band would otherwise drown out a small finger.  The border
    # tier strongly favours blobs entering from the bottom/sides (real hand)
    # over blobs at the top of the page (printed illustration characters with
    # skin tones): tier 0 = bottom, tier 1 = side, tier 2 = top-only, tier 3 = none.
    img_area = sw * sh
    scored: list[tuple[int, float, Any]] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < _MIN_BLOB_AREA:
            continue
        aspect, _, _ = _blob_aspect(c)
        if aspect < _MIN_ELONGATION:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        orient_bonus = 2.0 if bh > bw else 0.5  # vertical finger > horizontal band
        area_bonus = 1.5 if area > _LARGE_BLOB_FRAC * img_area else 1.0
        score = min(aspect, 10.0) * orient_bonus * area_bonus
        tier = _border_tier(c, sw, sh)
        scored.append((tier, score, c))
    if not scored:
        # Fallback: try the largest blob even if not elongated (palm in frame).
        scored = [(3, float(cv2.contourArea(c)), c) for c in contours if cv2.contourArea(c) >= _MIN_BLOB_AREA]
    if not scored:
        return []

    # Sort by tier ascending (bottom first), then score descending.
    scored.sort(key=lambda t: (t[0], -t[1]))
    out: list[dict[int, tuple[float, float]]] = []
    for _, _, c in scored[:1]:  # only the best blob — skin detection can't reliably distinguish multiple hands
        lm = _blob_to_landmarks(c, 1.0 / s, img_w=sw, img_h=sh)
        if lm is not None:
            out.append(lm)
    return out
