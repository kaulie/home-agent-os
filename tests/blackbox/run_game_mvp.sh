#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PORT="${COIN_CATCHER_GAME_PORT:-8102}"
BASE="http://127.0.0.1:${PORT}"

if ! curl -sf "$BASE/" >/dev/null 2>&1; then
  echo "Starting serve.py on :$PORT ..."
  python3 "$ROOT/games/coin-catcher/serve.py" &
  SPID=$!
  trap 'kill $SPID 2>/dev/null || true' EXIT
  for _ in $(seq 1 30); do
    curl -sf "$BASE/" >/dev/null 2>&1 && break
    sleep 0.2
  done
fi

ts() { python3 -c 'import time; print(int(time.time()*1000))'; }

post() {
  local type=$1 src=$2
  curl -sf -X POST "$BASE/command" -H 'Content-Type: application/json' \
    -d "{\"type\":\"$type\",\"source\":\"$src\",\"timestamp\":$(ts)}"
  echo " → $type"
}

post START VOICE
sleep 0.5
post MOVE_LEFT GESTURE
post MOVE_RIGHT GESTURE
post PAUSE VOICE
post RESUME VOICE
echo "OK: game MVP HTTP commands"
