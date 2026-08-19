"""DEPRECATED reference stub — do not mount on Brain.

Vision understanding is an Edge runtime capability (`vision.perceive` on Mac).
Model API keys and endpoints are configured on the Edge
(`MAC_EDGE_VISION_API_*`), not on Brain.

Kept only as a historical contract sketch. Prefer:
  mac/src/mac_edge/plugins/vision_perceive.py
"""

from __future__ import annotations

from flask import Blueprint, jsonify

bp = Blueprint("vision_analyze_deprecated", __name__)


@bp.route("/api/v1/vision/analyze", methods=["POST"])
def analyze_photo_deprecated():
    return (
        jsonify(
            ok=False,
            error=(
                "vision runs on Edge capability vision.perceive; "
                "configure MAC_EDGE_VISION_API_* on the Mac runtime"
            ),
        ),
        410,
    )
