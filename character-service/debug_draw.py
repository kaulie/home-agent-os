"""Debug overlay. OpenCV only; not used by geometry tests."""

from __future__ import annotations

import base64
from typing import Any


def overlay_png(
    image_bgr: Any,
    *,
    origin: tuple[float, float] | None,
    direction: tuple[float, float] | None,
    chars: list[dict[str, Any]],
    chosen: dict[str, Any] | None,
    max_distance: float,
) -> str:
    import cv2
    import numpy as np

    canvas = image_bgr.copy()
    for ch in chars:
        x1, y1, x2, y2 = [int(v) for v in ch["bbox"]]
        color = (180, 180, 180)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 1)
        label = str(ch.get("text") or "")
        if label:
            cv2.putText(
                canvas,
                label,
                (x1, max(y1 - 4, 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (80, 80, 80),
                1,
                cv2.LINE_AA,
            )
    if chosen is not None:
        x1, y1, x2, y2 = [int(v) for v in chosen["bbox"]]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 180, 0), 3)
    if origin is not None and direction is not None:
        ox, oy = int(origin[0]), int(origin[1])
        ex = int(origin[0] + direction[0] * max_distance)
        ey = int(origin[1] + direction[1] * max_distance)
        cv2.circle(canvas, (ox, oy), 8, (0, 0, 255), -1)
        cv2.arrowedLine(canvas, (ox, oy), (ex, ey), (0, 0, 255), 2, tipLength=0.04)
    ok, buf = cv2.imencode(".png", canvas)
    if not ok:
        return ""
    return base64.b64encode(np.asarray(buf).tobytes()).decode("ascii")
