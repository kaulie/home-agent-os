from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("mac_edge.state")


def load_edge_id(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("failed to read %s: %s", path, e)
        return None
    edge_id = (data.get("edge_id") or "").strip()
    return edge_id or None


def save_edge_id(path: Path, edge_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"edge_id": edge_id.strip()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    log.info("persisted edge_id=%s → %s", edge_id, path)


def clear_edge_id(path: Path) -> None:
    if path.is_file():
        path.unlink()
        log.info("cleared cached edge_id at %s", path)
