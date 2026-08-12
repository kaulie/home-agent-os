"""Vision analyze — copy into your Flask app.

Contract (server-side vision; Edge/frontend only consumes results):
  POST /api/v1/vision/analyze
  multipart/form-data:
    file   = image bytes (required)
    prompt = optional text hint

Response JSON:
  {
    "ok": true,
    "summary": "客厅里有两人在聊天",
    "people": [
      {"description": "成年男性", "count": 1},
      {"description": "成年女性", "count": 1}
    ],
    "activities": ["站着交谈"],
    "scene": "室内客厅",
    "raw_text": "…"
  }

App default:
  http://115.190.153.53:9527/api/v1/vision/analyze

Wire `call_vision_model` to Doubao / GPT-4V / your multimodal API.
The stub below returns a placeholder so the Edge can be tested end-to-end.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from flask import Blueprint, Flask, jsonify, request

VISION_PATH = "/api/v1/vision/analyze"
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads" / "vision"

bp = Blueprint("vision_analyze", __name__)


def call_vision_model(image_bytes: bytes, prompt: str) -> dict:
    """Replace this with your real multimodal LLM call.

    Expected return keys: summary, people (list[str|dict]), activities (list[str]),
    scene (str), raw_text (str).
    """
    # TODO: e.g. base64 + POST to doubao vision / OpenAI vision
    _ = image_bytes
    return {
        "summary": "（占位）尚未接入视觉大模型；请在 call_vision_model 中实现。",
        "people": [],
        "activities": [],
        "scene": "",
        "raw_text": prompt,
    }


@bp.route(VISION_PATH, methods=["POST"])
def analyze_photo():
    if "file" not in request.files:
        return jsonify(ok=False, error='expected multipart field name "file"'), 400

    f = request.files["file"]
    data = f.read()
    if not data:
        return jsonify(ok=False, error="empty file"), 400

    prompt = (
        request.form.get("prompt")
        or "请描述图中有哪些人、他们在做什么、场景是什么。用中文简要回答。"
    ).strip()

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    original = Path(f.filename or "photo.jpg").name.replace("/", "_") or "photo.jpg"
    saved = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{original}"
    saved.write_bytes(data)

    try:
        result = call_vision_model(data, prompt)
    except Exception as exc:  # noqa: BLE001 — surface to client
        return jsonify(ok=False, error=f"vision model failed: {exc}"), 500

    people = result.get("people") or []
    # normalize people to list of {description, count}
    norm_people = []
    for p in people:
        if isinstance(p, str):
            norm_people.append({"description": p, "count": 1})
        elif isinstance(p, dict):
            norm_people.append(
                {
                    "description": p.get("description") or p.get("name") or "人",
                    "count": int(p.get("count") or 1),
                }
            )

    return jsonify(
        ok=True,
        summary=result.get("summary") or "",
        people=norm_people,
        activities=result.get("activities") or [],
        scene=result.get("scene") or "",
        raw_text=result.get("raw_text") or "",
        saved_as=saved.name,
        bytes=len(data),
    )


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
    app.register_blueprint(bp)
    return app


app = create_app()


if __name__ == "__main__":
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    print(f"vision POST http://0.0.0.0:9527{VISION_PATH}")
    app.run(host="0.0.0.0", port=9527, threaded=True)
