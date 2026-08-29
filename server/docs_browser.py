"""Read-only browser for Markdown files in the project repository."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator

_MD_SUFFIXES = {".md", ".markdown"}
_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "DerivedData",
        "pyenv",
        "site-packages",
        "gopropics",
        "llm_logs",
        "agent-transcripts",
        "upload",
        "reading-crops",
    }
)


class DocsBrowserError(Exception):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def docs_root() -> Path:
    """Root directory to list/read markdown from. Defaults to whole repo."""
    raw = (os.environ.get("DOCS_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return repo_root().resolve()


def _validate_relative_path(rel: str) -> str:
    text = str(rel or "").strip().replace("\\", "/").lstrip("/")
    if not text:
        raise DocsBrowserError("path required")
    parts = [p for p in text.split("/") if p]
    if any(p in (".", "..") for p in parts):
        raise DocsBrowserError("invalid path")
    if Path(text).suffix.lower() not in _MD_SUFFIXES:
        raise DocsBrowserError("only markdown files are allowed")
    return "/".join(parts)


def resolve_doc_path(rel: str) -> Path:
    rel_norm = _validate_relative_path(rel)
    root = docs_root()
    target = (root / rel_norm).resolve()
    if not str(target).startswith(str(root)):
        raise DocsBrowserError("invalid path")
    return target


def _iter_markdown_files(root: Path) -> Iterator[tuple[Path, str]]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _SKIP_DIR_NAMES and not name.startswith(".")
        ]
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            if path.suffix.lower() not in _MD_SUFFIXES:
                continue
            rel = path.relative_to(root).as_posix()
            if any(part in _SKIP_DIR_NAMES for part in Path(rel).parts):
                continue
            yield path, rel


def list_documents() -> list[dict[str, Any]]:
    root = docs_root()
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path, rel in sorted(_iter_markdown_files(root), key=lambda row: row[1]):
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        items.append(
            {
                "path": rel,
                "title": _title_from_path(rel),
                "size": size,
            }
        )
    return items


def read_document(rel: str) -> dict[str, Any]:
    rel_norm = _validate_relative_path(rel)
    target = resolve_doc_path(rel_norm)
    if not target.is_file():
        raise DocsBrowserError("document not found")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise DocsBrowserError("document is not valid UTF-8") from e
    except OSError as e:
        raise DocsBrowserError(f"cannot read document: {e}") from e
    return {
        "path": rel_norm,
        "title": _title_from_path(rel_norm),
        "content": content,
        "size": len(content.encode("utf-8")),
    }


def _title_from_path(rel: str) -> str:
    stem = Path(rel).stem
    return stem.replace("-", " ").replace("_", " ")
