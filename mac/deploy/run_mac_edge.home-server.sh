#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Override ROOT when copied to home-server tree as run_mac_edge.sh next to src/
if [ -d "$ROOT/src/mac_edge" ]; then
  :
elif [ -d "$(cd "$(dirname "$0")" && pwd)/src/mac_edge" ]; then
  ROOT="$(cd "$(dirname "$0")" && pwd)"
fi
export MAC_EDGE_BRAIN_URL="http://115.190.153.53:9527"
export MAC_EDGE_INTERVAL_SEC="3"
export MAC_EDGE_CLIENT_HINT="home-server-mac"
export MAC_EDGE_DISPLAY_NAME="Home Server · Mac Edge"
export MAC_EDGE_DEVICE_TYPE="mac"
export MAC_EDGE_ROOM="living-room"
export MAC_EDGE_APP_VERSION="0.3.0"
export MAC_EDGE_DATA_DIR="$ROOT/data"
export MAC_EDGE_CAST_DISPLAY_URL="http://127.0.0.1:9095/endpoint/display"
export PYTHONPATH="$ROOT/src"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m mac_edge
