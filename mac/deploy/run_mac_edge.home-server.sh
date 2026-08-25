#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Override ROOT when copied to home-server tree as run_mac_edge.sh next to src/
if [ -d "$ROOT/src/mac_edge" ]; then
  :
elif [ -d "$(cd "$(dirname "$0")" && pwd)/src/mac_edge" ]; then
  ROOT="$(cd "$(dirname "$0")" && pwd)"
fi
export MAC_EDGE_BRAIN_URL="http://192.168.3.73:9527"
export MAC_EDGE_INTERVAL_SEC="3"
export MAC_EDGE_CLIENT_HINT="home-server-mac"
export MAC_EDGE_DISPLAY_NAME="Home Server · Mac Edge"
export MAC_EDGE_DEVICE_TYPE="mac"
export MAC_EDGE_ROOM="living-room"
export MAC_EDGE_APP_VERSION="0.3.0"
export MAC_EDGE_DATA_DIR="$ROOT/data"
export MAC_EDGE_CAST_DISPLAY_URL="http://127.0.0.1:9095/endpoint/display"
export PYTHONPATH="$ROOT/src"
# Optional local secrets (ARK_API_KEY / MAC_EDGE_VISION_*); also loaded by Python from .env
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
# GoPro + living-room ceiling light stay here. query/speak/vision/Cast register on the laptop.
export MAC_EDGE_ROLE="${MAC_EDGE_ROLE:-home-server}"
export MAC_EDGE_SERVICE_WHITELIST="${MAC_EDGE_SERVICE_WHITELIST:-gopro.camera,livingroom.ceiling_light,local.asset}"
# camera.capture default: lan (home img-server). cloud only when user asks.
export MAC_EDGE_PHOTO_UPLOAD_DEST="${MAC_EDGE_PHOTO_UPLOAD_DEST:-lan}"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m mac_edge
