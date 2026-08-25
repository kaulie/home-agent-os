#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export KINDLE_PAGE_PORT="${KINDLE_PAGE_PORT:-8088}"
export KINDLE_BRAIN_URL="${KINDLE_BRAIN_URL:-http://127.0.0.1:9527}"
exec python3 -u "$ROOT/serve.py"
