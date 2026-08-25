#!/bin/bash
# Play a recorded MPEG-TS. Do this AFTER Stop Stream (QuickTime cannot follow a live file).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DIR="$ROOT/data/video-live"
if [[ "${1:-}" != "" ]]; then
  TS="$1"
else
  TS="$(ls -t "$DIR"/*.ts 2>/dev/null | head -1 || true)"
fi
if [[ -z "${TS}" || ! -f "$TS" ]]; then
  echo "no .ts in $DIR" >&2
  exit 1
fi
# Re-encode to yuv420p so QuickTime actually plays past the first frame.
MP4="${TS%.ts}.mp4"
ffmpeg -y -hide_banner -loglevel error \
  -fflags +genpts+discardcorrupt \
  -i "$TS" \
  -c:v libx264 -pix_fmt yuv420p -preset ultrafast -an \
  "$MP4"
open "$MP4"
echo "opened $MP4"
