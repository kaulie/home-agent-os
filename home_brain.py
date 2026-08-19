"""systemd / project-root entry for Brain.

Cloud: WorkingDirectory=/root/chat-gateway, ExecStart=python3 home_brain.py.
Implementation lives in server/home_brain.py. Do not add control-plane logic here.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SERVER = _ROOT / "server"
sys.path.insert(0, str(_SERVER))
runpy.run_path(str(_SERVER / "home_brain.py"), run_name="__main__")
