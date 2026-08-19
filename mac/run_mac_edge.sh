#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export MAC_EDGE_BRAIN_URL="http://115.190.153.53:9527"
export MAC_EDGE_INTERVAL_SEC="3"
export MAC_EDGE_CLIENT_HINT="living-room-mac"
export MAC_EDGE_DISPLAY_NAME="客厅 · Mac Edge"
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
# This machine registers all Mac capabilities except GoPro / img-server.
export MAC_EDGE_ROLE="${MAC_EDGE_ROLE:-laptop}"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m mac_edge
