#!/bin/bash
set -euo pipefail
launchctl unload "$HOME/Library/LaunchAgents/com.kaulie.home-agent-mac-edge.plist" 2>/dev/null || true
pkill -f '[P]ython -m mac_edge' 2>/dev/null || true
echo "stopped"
