#!/usr/bin/env bash
# Helper: enqueue a music command to the living-room device queue.
# Usage:
#   ./enqueue.sh play spotify
#   ./enqueue.sh next netease
#   ./enqueue.sh play_song netease '晴天 周杰伦'
#   ./enqueue.sh launch spotify 'spotify:track:3n3AvegLEkuQnqzMxVKLhG'
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
DEVICE_ID="${DEVICE_ID:-living-room}"
ACTION="${1:-}"
APP="${2:-netease}"

if [[ -z "$ACTION" ]]; then
  echo "Usage:"
  echo "  $0 <launch|play|pause|play_pause|next|previous|stop> [spotify|netease] [uri]"
  echo "  $0 play_song netease '<歌名>'"
  echo "  $0 play_song netease '<歌名> <歌手>'   # 歌手可选"
  exit 1
fi

if [[ "$ACTION" == "play_song" ]]; then
  SONG_LINE="${3:-}"
  if [[ -z "$SONG_LINE" ]]; then
    echo "play_song requires 歌名，例如: '披荆斩棘' 或 '十年 陈奕迅'"
    exit 1
  fi
  payload=$(python3 - <<PY
import json
data = {"action": "play_song", "app": "$APP", "song": """$SONG_LINE"""}
print(json.dumps(data, ensure_ascii=False))
PY
)
else
  URI="${3:-}"
  payload=$(python3 - <<PY
import json
data = {"action": "$ACTION", "app": "$APP"}
uri = """$URI"""
if uri:
    data["uri"] = uri
print(json.dumps(data, ensure_ascii=False))
PY
)
fi

curl -sS -X POST \
  "$BASE_URL/api/v1/devices/$DEVICE_ID/commands" \
  -H 'Content-Type: application/json' \
  -d "$payload"
echo
