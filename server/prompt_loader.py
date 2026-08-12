"""Load text files from a directory and assemble a prompt string.

Template placeholders use Python ``str.format`` syntax, e.g. ``{USER_INTENT}``.
Literal braces in the template must be escaped as ``{{`` / ``}}``.

Typical layout::

    prompts/
      01_system.md
      02_rules.md
      03_user.md

Usage::

    from prompt_loader import build_prompt_from_dir

    prompt = build_prompt_from_dir(
        "/path/to/prompts",
        variables={
            "USER_INTENT": "帮我拍张照",
            "MEMORY": "用户上次要求打开客厅灯",
        },
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

DEFAULT_EXTENSIONS = {".md", ".txt", ".markdown", ".prompt"}


def list_prompt_files(
    directory: str | Path,
    *,
    extensions: Iterable[str] | None = None,
    recursive: bool = False,
) -> list[Path]:
    """Return prompt files under ``directory``, sorted by name (then path).

    Hidden files (name starts with ``.``) are skipped.
    """
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"prompt directory not found: {root}")

    exts = {e if e.startswith(".") else f".{e}" for e in (extensions or DEFAULT_EXTENSIONS)}
    exts = {e.lower() for e in exts}

    if recursive:
        candidates = [p for p in root.rglob("*") if p.is_file()]
    else:
        candidates = [p for p in root.iterdir() if p.is_file()]

    files = [
        p
        for p in candidates
        if not p.name.startswith(".") and p.suffix.lower() in exts
    ]
    files.sort(key=lambda p: (p.name.lower(), str(p).lower()))
    return files


def read_prompt_files(
    directory: str | Path,
    *,
    extensions: Iterable[str] | None = None,
    recursive: bool = False,
    encoding: str = "utf-8",
) -> list[tuple[Path, str]]:
    """Read each prompt file; return list of ``(path, text)``."""
    out: list[tuple[Path, str]] = []
    for path in list_prompt_files(directory, extensions=extensions, recursive=recursive):
        text = path.read_text(encoding=encoding)
        out.append((path, text))
    return out


def render_template(template: str, variables: Mapping[str, object] | None = None) -> str:
    """Replace placeholders with ``str.format(**variables)``.

    Template should use ``{USER_INTENT}``, ``{MEMORY}``, etc.
    """
    if not variables:
        return template
    return template.format(**variables)


def build_prompt_from_dir(
    directory: str | Path,
    *,
    variables: Mapping[str, object] | None = None,
    separator: str = "\n\n",
    extensions: Iterable[str] | None = None,
    recursive: bool = False,
    encoding: str = "utf-8",
    include_filenames: bool = False,
    strip_parts: bool = True,
) -> str:
    """Read all prompt files in ``directory`` and join them into one prompt.

    Args:
        directory: Folder containing ``.md`` / ``.txt`` (etc.) templates.
        variables: Optional dict passed to ``str.format(**variables)``.
        separator: Joined between file contents (default blank line).
        extensions: File suffixes to include; default md/txt/markdown/prompt.
        recursive: Also scan subdirectories.
        encoding: Text encoding when reading files.
        include_filenames: If True, prefix each part with ``# filename``.
        strip_parts: Strip leading/trailing whitespace per file.

    Returns:
        Assembled prompt string.

    Raises:
        FileNotFoundError: Directory missing, or no matching files inside.
        KeyError: Template placeholder missing from ``variables``.
    """
    parts_src = read_prompt_files(
        directory,
        extensions=extensions,
        recursive=recursive,
        encoding=encoding,
    )
    if not parts_src:
        raise FileNotFoundError(f"no prompt files found in: {Path(directory).resolve()}")

    chunks: list[str] = []
    for path, text in parts_src:
        body = text.strip() if strip_parts else text
        body = render_template(body, variables)
        if include_filenames:
            body = f"# {path.name}\n\n{body}"
        if body:
            chunks.append(body)

    prompt = separator.join(chunks)
    return prompt.strip() + ("\n" if prompt.strip() else "")


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Assemble a prompt from a directory of files")
    parser.add_argument("directory", help="prompt template directory")
    parser.add_argument(
        "--vars",
        default="",
        help='JSON object for placeholders, e.g. \'{"USER_INTENT":"hello"}\'',
    )
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--with-names", action="store_true", help="prefix each file name")
    args = parser.parse_args()

    vars_map: dict[str, object] = {}
    if args.vars.strip():
        vars_map = json.loads(args.vars)
        if not isinstance(vars_map, dict):
            print("--vars must be a JSON object", file=sys.stderr)
            sys.exit(2)

    print(
        build_prompt_from_dir(
            args.directory,
            variables=vars_map,
            recursive=args.recursive,
            include_filenames=args.with_names,
        ),
        end="",
    )
