"""Download Dev Task attachments from Brain for local agent analysis."""

from __future__ import annotations

import logging
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from agent_bridge.config import BridgeConfig

log = logging.getLogger(__name__)


def _format_attachment_section(
    attachments: list[dict[str, str]],
    *,
    local_paths: dict[str, str],
) -> str:
    if not attachments:
        return ""
    lines = ["", "## Attachments"]
    for row in attachments:
        kind = row.get("kind") or "file"
        aid = row.get("asset_id") or "—"
        mime = row.get("mime_type") or ""
        name = row.get("filename") or ""
        detail = f"- {kind} {aid}"
        if mime:
            detail += f" mime={mime}"
        if name:
            detail += f" name={name}"
        local = local_paths.get(str(aid))
        if local:
            detail += f"\n  local_path={local}"
        lines.append(detail)
    lines.append(
        "Use local_path files when present. Image attachments are for visual analysis."
    )
    return "\n".join(lines)


def _build_prompt(text: str, attachments: list[dict[str, str]], local_paths: dict[str, str]) -> str:
    body = str(text or "").strip()
    if not attachments:
        return body
    section = _format_attachment_section(attachments, local_paths=local_paths)
    if not body:
        return ("[Dev Task with attachments — analyze the attached files.]" + section).strip()
    return f"{body}{section}"


def _attachment_scope(task_id: int) -> str:
    return f"dev_task:{int(task_id)}"


def _guess_suffix(row: dict[str, str]) -> str:
    filename = str(row.get("filename") or "").strip()
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix
    mime = str(row.get("mime_type") or "").strip().lower()
    if mime:
        ext = mimetypes.guess_extension(mime, strict=False)
        if ext:
            return ext
    kind = str(row.get("kind") or "").strip().lower()
    if kind == "image":
        return ".jpg"
    if kind == "audio":
        return ".m4a"
    if kind == "video":
        return ".mp4"
    return ".bin"


def _download_attachment(
  config: BridgeConfig,
  *,
  asset_id: str,
  task_id: int | None,
  dest: Path,
  brain_url: str | None = None,
) -> None:
    base = str(brain_url or config.brain_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("AGENT_BRIDGE_BRAIN_URL is not configured")
    query = {}
    if task_id is not None:
        query["intent_id"] = _attachment_scope(task_id)
    qs = urllib.parse.urlencode(query)
    url = f"{base}/api/v1/assets/{urllib.parse.quote(asset_id, safe='')}/content"
    if qs:
        url = f"{url}?{qs}"
    headers = {"Accept": "*/*"}
    token = (config.brain_admin_token or "").strip()
    if token:
        headers["X-Admin-Token"] = token
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"attachment download HTTP {err.code}: {detail[:200]}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"attachment download failed: {err.reason}") from err
    if not data:
        raise RuntimeError("attachment download returned empty body")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def materialize_dev_task_attachments(
    text: str,
    *,
    attachments: list[dict[str, str]],
    task_id: int | None,
    run_id: str,
    data_dir: Path,
    config: BridgeConfig,
    brain_url: str | None = None,
) -> tuple[str, dict[str, str]]:
    if not attachments:
        return text, {}
    local_paths: dict[str, str] = {}
    root = data_dir / "dev_task_attachments" / run_id
    for index, row in enumerate(attachments):
        aid = str(row.get("asset_id") or "").strip()
        if not aid:
            continue
        suffix = _guess_suffix(row)
        dest = root / f"{index + 1:02d}_{aid}{suffix}"
        try:
            _download_attachment(
                config,
                asset_id=aid,
                task_id=task_id,
                dest=dest,
                brain_url=brain_url,
            )
            local_paths[aid] = str(dest.resolve())
        except Exception:
            log.exception("failed to download dev_task attachment asset=%s", aid)
    prompt = _build_prompt(text, attachments, local_paths)
    return prompt, local_paths
