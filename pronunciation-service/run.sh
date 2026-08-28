#!/bin/bash
# Start the pronunciation assessment service on :9190 using a local venv.
# The venv must have whisperx + torch + librosa installed (see requirements.txt).
# Do NOT use system python3 — whisperx is not installed there.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/pyenv/bin/python3"

if [ ! -x "$PY" ]; then
  echo "ERROR: $PY not found. Create the venv first:" >&2
  echo "  python3 -m venv $HERE/pyenv && $HERE/pyenv/bin/pip install -r $HERE/requirements.txt" >&2
  exit 1
fi

export HF_HOME="${HF_HOME:-$HERE/hf-cache}"

cd "$HERE"
exec "$PY" main.py "$@"
