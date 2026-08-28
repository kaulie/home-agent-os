#!/usr/bin/env bash
# Reverse SSH tunnel: cloud Brain -> home Mac agent-bridge
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

REMOTE_HOST="${TUNNEL_SSH_HOST:-cloud-server}"
REMOTE_PORT="${TUNNEL_REMOTE_PORT:-19540}"
LOCAL_PORT="${AGENT_BRIDGE_PORT:-9540}"
LOCAL_HOST="${AGENT_BRIDGE_HOST:-127.0.0.1}"

exec ssh -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  -o StrictHostKeyChecking=accept-new \
  -R "127.0.0.1:${REMOTE_PORT}:${LOCAL_HOST}:${LOCAL_PORT}" \
  "$REMOTE_HOST"
