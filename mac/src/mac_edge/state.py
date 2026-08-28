from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path

log = logging.getLogger("mac_edge.state")


def _generate_runtime_id() -> str:
    return "runtime-mac-" + secrets.token_hex(8)


def load_runtime_id(path: Path, *, edge_id_path: Path | None = None) -> str | None:
    """Load persisted Runtime Identity. Smooth migration: reuse edge_id.json value.

    Precedence: runtime_id.json → edge_id.json → None.
    """
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rid = (data.get("runtime_id") or "").strip()
            if rid:
                return rid
        except (OSError, json.JSONDecodeError) as e:
            log.warning("failed to read %s: %s", path, e)
    if edge_id_path is not None and edge_id_path.is_file():
        try:
            data = json.loads(edge_id_path.read_text(encoding="utf-8"))
            eid = (data.get("edge_id") or "").strip()
            if eid:
                return eid
        except (OSError, json.JSONDecodeError):
            pass
    return None


def save_runtime_id(path: Path, runtime_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"runtime_id": runtime_id.strip()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    log.info("persisted runtime_id=%s → %s", runtime_id, path)


def ensure_runtime_id(path: Path, *, edge_id_path: Path | None = None) -> str:
    """Load or generate+persist a stable runtime_id (client-supplied identity)."""
    rid = load_runtime_id(path, edge_id_path=edge_id_path)
    if rid:
        if not path.is_file():
            save_runtime_id(path, rid)
        return rid
    rid = _generate_runtime_id()
    save_runtime_id(path, rid)
    return rid


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
