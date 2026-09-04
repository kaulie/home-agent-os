#!/bin/bash
# Restart LAN Brain.
# Default: this checkout on the current machine (no SSH).
# Remote home-server is opt-in via BRAIN_HOST.
#
# Usage:
#   ./server/deploy/deploy_lan_brain.sh                 # local restart
#   BRAIN_HOST=other-mac ./server/deploy/deploy_lan_brain.sh
#   BRAIN_HOST=user@hostname ./server/deploy/deploy_lan_brain.sh
#   BRAIN_REMOTE_ROOT=~/home-agent-os BRAIN_HOST=other-mac ./server/deploy/deploy_lan_brain.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

restart_local() {
  echo "==> restart LAN Brain on this machine (no SSH)"
  mkdir -p "$ROOT/server/data" "$ROOT/server/llm_logs"
  local PY=python3
  if [[ -x "$ROOT/server/.venv/bin/python" ]]; then
    PY="$ROOT/server/.venv/bin/python"
  fi
  "$PY" -c 'import sys; assert sys.version_info >= (3,10), sys.version'
  pkill -f 'python.*home_brain.py' 2>/dev/null || true
  pkill -f 'python3.*home_brain.py' 2>/dev/null || true
  sleep 1
  cd "$ROOT/server"
  nohup env BRAIN_ORIGIN=lan "$PY" home_brain.py >> llm_logs/brain.nohup.log 2>&1 &
  echo "started pid $!"
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sf http://127.0.0.1:9527/api/v1/ping >/dev/null; then
      break
    fi
    sleep 0.5
  done
  echo "==> local ping"
  curl -sf http://127.0.0.1:9527/api/v1/ping | head -c 200
  echo
  echo "done"
}

deploy_remote() {
  local HOST="$BRAIN_HOST"
  local REMOTE_ROOT="${BRAIN_REMOTE_ROOT:-~/home-agent-os}"
  local SSH=(ssh -o ConnectTimeout=8 -o BatchMode=yes "$HOST")

  echo "==> probe $HOST"
  "${SSH[@]}" 'echo ok; hostname; uname -s; (ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null || true)'

  echo "==> rsync tree → $HOST:$REMOTE_ROOT (keep remote .env / data / llm_logs)"
  rsync -az --delete \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '**/__pycache__/' \
    --exclude '**/.DS_Store' \
    --exclude 'server/data/' \
    --exclude 'server/llm_logs/' \
    --exclude 'server/.env' \
    --exclude 'mac/.env' \
    --exclude 'mac/data/' \
    --exclude 'mac/logs/' \
    --exclude 'gopropics/' \
    --exclude 'agent_access.log' \
    --exclude 'pronunciation-service/pyenv/' \
    --exclude 'ios/**/DerivedData/' \
    --exclude '**/node_modules/' \
    "$ROOT/" "$HOST:$REMOTE_ROOT/"

  echo "==> ensure remote .env + data dir"
  "${SSH[@]}" bash -s <<EOF
set -euo pipefail
cd $REMOTE_ROOT
mkdir -p server/data server/llm_logs
if [[ ! -f server/.env ]]; then
  if [[ -f server/.env.example ]]; then
    cp server/.env.example server/.env
    echo "created server/.env from example — fill ARK_API_KEY before use"
  else
    echo "ARK_API_KEY=" > server/.env
    echo "created empty server/.env — fill ARK_API_KEY"
  fi
fi
PY=python3
command -v python3.12 >/dev/null && PY=python3.12
command -v python3.11 >/dev/null && PY=python3.11
\$PY -c 'import sys; assert sys.version_info >= (3,10), sys.version'
if [[ ! -f server/data/brain.sqlite3 ]]; then
  (cd server && \$PY db.py init) || echo "WARN: db.py init failed — run as @dba if needed"
fi
pkill -f 'python.*home_brain.py' 2>/dev/null || true
pkill -f 'python3.*home_brain.py' 2>/dev/null || true
sleep 1
nohup env BRAIN_ORIGIN=lan \$PY home_brain.py >> server/llm_logs/brain.nohup.log 2>&1 &
echo "started pid \$!"
sleep 2
curl -sf http://127.0.0.1:9527/api/v1/ping | head -c 200
echo
EOF

  echo "==> ping $HOST:9527 from this machine"
  local ping_host
  ping_host="$(ssh -G "$HOST" 2>/dev/null | awk '/^hostname /{print $2; exit}')"
  ping_host="${ping_host:-$HOST}"
  curl -sf "http://${ping_host}:9527/api/v1/ping" | head -c 200
  echo
  echo "done"
}

if [[ -n "${BRAIN_HOST:-}" ]]; then
  deploy_remote
else
  restart_local
fi
