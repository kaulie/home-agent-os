"""Resolve hosting Mac Runtime edge_id for voice.stream (kind=input).

Does not register a separate participant. POST /intent uses the parent Runtime id.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from mac_voice.config import VoiceConfig

log = logging.getLogger("mac_voice.edge_id")


def _id_from_file(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("edge_id") or data.get("participant_id") or "").strip()


def resolve_parent_edge_id(cfg: VoiceConfig) -> str:
    """Return Mac Runtime edge_id or empty if not yet available.

    Prefer edge_id.json over MAC_EDGE_EDGE_ID: the file is rewritten on
    re-register, while the env is frozen at mac_voice spawn.
    """
    candidates = [
        cfg.edge_id_path,
        cfg.data_dir.parent / "edge_id.json",  # mac/data when data_dir is mac/data/mac_voice
        Path(os.environ.get("MAC_EDGE_DATA_DIR") or "").expanduser() / "edge_id.json"
        if (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
        else None,
    ]
    for path in candidates:
        pid = _id_from_file(path)
        if pid:
            return pid
    return (os.environ.get("MAC_EDGE_EDGE_ID") or "").strip()


def require_parent_edge_id(cfg: VoiceConfig) -> str:
    pid = resolve_parent_edge_id(cfg)
    if not pid:
        raise RuntimeError(
            "voice.stream needs Mac Runtime edge_id "
            "(set MAC_EDGE_EDGE_ID or ensure mac/data/edge_id.json exists); "
            "will not self-register"
        )
    return pid
