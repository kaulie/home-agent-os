#!/bin/bash
# Start the PaddleOCR service on :9188 using the bundled pyenv venv.
# The venv has paddlepaddle 3.0.0 + paddleocr 3.7.0 + opencv installed.
# Do NOT use system python3 (3.14) — paddleocr is not installed there.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/pyenv/bin/python3.11"

if [ ! -x "$PY" ]; then
  echo "ERROR: $PY not found. Create the venv first (see README.md)." >&2
  exit 1
fi

# PaddleOCR ships its own model cache; keep it inside the repo.
export PADDLEX_HOME="${PADDLEX_HOME:-$HERE/paddlex-home}"
# PaddleOCR may try to write to ~/.paddlex; point it at the repo dir too.
export PADDLE_PDX_CACHE_HOME="${PADDLE_PDX_CACHE_HOME:-$HERE/cache}"
# Models are pre-downloaded into $HERE/cache; skip the connectivity check
# to the official hosters so the service starts without internet access.
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="${PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK:-True}"

cd "$HERE"
exec "$PY" main.py "$@"
