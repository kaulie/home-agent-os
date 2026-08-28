#!/usr/bin/env bash
# character-service 启动脚本。
# 必须用 local-rt/venv 的 python3.11：cv2 / mediapipe 装在这里。
# 系统 python3 / python3.11 都没有 cv2，用错会 detect_finger 500 (ModuleNotFoundError: cv2)。
set -euo pipefail
cd "$(dirname "$0")"

VENV_PY="$(cd .. && pwd)/local-rt/venv/bin/python3.11"
if [ ! -x "$VENV_PY" ]; then
  echo "missing venv python: $VENV_PY" >&2
  exit 1
fi

exec "$VENV_PY" main.py
