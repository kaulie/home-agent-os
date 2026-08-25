"""JSONL persistence for each voice-lamp trial."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def experiments_dir() -> Path:
    raw = (os.environ.get("MAC_EDGE_VOICE_TEST_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    here = Path(__file__).resolve()
    return here.parents[4] / "data" / "voice_tests"


def trial_dir(experiment_id: str, trial_id: str) -> Path:
    path = experiments_dir() / experiment_id / trial_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def jsonl_path() -> Path:
    root = experiments_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / "trials.jsonl"


def append_trial(record: dict[str, Any]) -> Path:
    path = jsonl_path()
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return path
