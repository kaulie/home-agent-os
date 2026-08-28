#!/usr/bin/env python3
"""Reject git commits that mix unrelated feature scopes or violate message format.

Usage (commit-msg hook):
  commit_scope_check.py --commit-msg "$1"

Convention: docs/git-commit-convention.md

Bypass:
  - commit message contains [skip-scope-check]
  - environment SKIP_SCOPE_CHECK=1

Explicit multi-scope (same intentional change-set):
  - Scopes: server, ios-dev   (footer)
  - [scopes: server, ios-dev] (legacy inline)

Same issue across scopes (branch + message must both reference the id):
  - branch: feature/42-fleet-ui  +  footer/message: Refs: #42
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = Path(__file__).with_name("commit_scope_rules.json")

SKIP_MARKERS = ("[skip-scope-check]", "[skip-scope]")
SCOPES_INLINE_RE = re.compile(r"\[scopes?:\s*([^\]]+)\]", re.IGNORECASE)
SCOPES_FOOTER_RE = re.compile(r"^Scopes:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
ISSUE_RE = re.compile(r"(?:\(#|#|fixes\s+#|issue\s+#?)(\d+)\b", re.IGNORECASE)
REFS_FOOTER_RE = re.compile(r"^Refs:\s*#?(\d+)\b", re.IGNORECASE | re.MULTILINE)
BRANCH_ISSUE_RE = re.compile(r"(?:^|[/_-])(?:issue[-_]?)?(\d+)(?:[/_-]|$)", re.IGNORECASE)

COMMIT_TYPES = ("feat", "fix", "docs", "refactor", "test", "chore", "deploy", "perf")
SUBJECT_RE = re.compile(
    r"^(?P<type>" + "|".join(COMMIT_TYPES) + r")\((?P<scope>[a-z0-9-]+)\): (?P<summary>.+)$"
)
SUMMARY_LEN_MIN = 4
SUMMARY_LEN_MAX = 72


def _run_git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def load_rules() -> dict:
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return raw


def _match_prefix(path: str, prefix: str) -> bool:
    if prefix.endswith("/"):
        return path.startswith(prefix) or path == prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def classify_path(path: str, rules: dict) -> tuple[str, str]:
    """Return (kind, scope_name) where kind is primary|companion|other."""
    norm = path.replace("\\", "/").lstrip("./")
    for row in rules.get("primary_scopes", []):
        name = str(row.get("name") or "").strip()
        for prefix in row.get("prefixes") or []:
            if _match_prefix(norm, str(prefix)):
                return "primary", name
    for row in rules.get("companion_scopes", []):
        name = str(row.get("name") or "").strip()
        for prefix in row.get("prefixes") or []:
            if _match_prefix(norm, str(prefix)):
                return "companion", name
    return "other", "other"


def staged_files() -> list[str]:
    out = _run_git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def current_branch() -> str:
    return _run_git("rev-parse", "--abbrev-ref", "HEAD") or ""


def known_scopes(rules: dict) -> set[str]:
    names: set[str] = set()
    for key in ("primary_scopes", "companion_scopes"):
        for row in rules.get(key, []):
            name = str(row.get("name") or "").strip().lower()
            if name:
                names.add(name)
    names.add("repo")
    return names


def split_message(message: str) -> tuple[str, str]:
    text = (message or "").strip("\n")
    if not text:
        return "", ""
    parts = text.split("\n\n", 1)
    subject = parts[0].splitlines()[0].strip()
    body = parts[1] if len(parts) > 1 else ""
    return subject, body


def parse_declared_scopes(message: str) -> set[str]:
    found: set[str] = set()
    for match in SCOPES_INLINE_RE.finditer(message or ""):
        chunk = match.group(1)
        for part in re.split(r"[,+]", chunk):
            token = part.strip().lower()
            if token:
                found.add(token)
    for match in SCOPES_FOOTER_RE.finditer(message or ""):
        chunk = match.group(1)
        for part in re.split(r"[,+]", chunk):
            token = part.strip().lower()
            if token:
                found.add(token)
    return found


def parse_issue_ids(message: str, branch: str) -> set[str]:
    ids: set[str] = set()
    for match in ISSUE_RE.finditer(message or ""):
        ids.add(match.group(1))
    for match in REFS_FOOTER_RE.finditer(message or ""):
        ids.add(match.group(1))
    for match in BRANCH_ISSUE_RE.finditer(branch or ""):
        ids.add(match.group(1))
    return ids


def primary_scopes_from_files(files: list[str], rules: dict) -> set[str]:
    primaries: set[str] = set()
    for path in files:
        kind, scope = classify_path(path, rules)
        if kind == "primary":
            primaries.add(scope)
    return primaries


def _format_help(*lines: str) -> str:
    return "\n".join(lines)


def validate_format(
    message: str,
    *,
    rules: dict | None = None,
    staged: list[str] | None = None,
) -> tuple[bool, str]:
    rules = rules or load_rules()
    if should_skip_commit(message):
        return True, ""

    subject, _body = split_message(message)
    if not subject or subject.startswith("#"):
        return False, _format_help(
            "commit-msg-check: 缺少有效标题行（模板注释行不算）。",
            "示例: feat(server): 新增 agent_fleet API",
            "规范: docs/git-commit-convention.md",
        )

    match = SUBJECT_RE.match(subject)
    if not match:
        return False, _format_help(
            "commit-msg-check: 标题须为 type(scope): summary",
            f"当前: {subject}",
            "示例: fix(ios-dev): Fleet 页展示运行状态",
            "规范: docs/git-commit-convention.md",
        )

    summary = match.group("summary").strip()
    if len(summary) < SUMMARY_LEN_MIN or len(summary) > SUMMARY_LEN_MAX:
        return False, _format_help(
            f"commit-msg-check: summary 长度需在 {SUMMARY_LEN_MIN}–{SUMMARY_LEN_MAX} 字。",
            f"当前长度: {len(summary)}",
        )

    scope = match.group("scope").lower()
    commit_type = match.group("type")
    allowed = known_scopes(rules)
    if commit_type != "docs" and scope not in allowed:
        return False, _format_help(
            f"commit-msg-check: 未知 scope «{scope}»。",
            f"可选: {', '.join(sorted(allowed))}",
        )
    if commit_type == "docs" and not re.fullmatch(r"[a-z0-9-]+", scope):
        return False, _format_help("commit-msg-check: docs 的 scope 仅允许小写与连字符。")

    if commit_type == "docs":
        return True, ""

    staged = staged or []
    primaries = primary_scopes_from_files(staged, rules)
    if len(primaries) == 1:
        primary = next(iter(primaries))
        meta_scopes = {"docs", "repo", "cursor", "git-hooks", "repo-meta"}
        if scope != primary and scope not in meta_scopes:
            return False, _format_help(
                "commit-msg-check: 标题 scope 与暂存区 primary 不一致。",
                f"暂存 primary: {primary}",
                f"标题 scope: {scope}",
                f"建议: {match.group('type')}({primary}): {summary}",
            )
    elif not primaries and staged:
        companion_names = {
            classify_path(path, rules)[1]
            for path in staged
            if classify_path(path, rules)[0] == "companion"
        }
        if scope not in companion_names and scope != "repo":
            return False, _format_help(
                "commit-msg-check: 仅 companion 文件时，scope 应为 docs 或 repo。",
                f"暂存 companion: {', '.join(sorted(companion_names)) or '(无)'}",
            )

    return True, ""


def linked_group_allowed(primary: set[str], rules: dict) -> bool:
    if len(primary) <= 1:
        return True
    groups = rules.get("linked_primary_groups") or []
    primary_sorted = sorted(primary)
    for group in groups:
        if not isinstance(group, list):
            continue
        allowed = {str(x).strip().lower() for x in group if str(x).strip()}
        if primary.issubset(allowed):
            return True
    return False


def should_skip_commit(message: str) -> bool:
    if os.environ.get("SKIP_SCOPE_CHECK", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if any(marker in message for marker in SKIP_MARKERS):
        return True
    stripped = (message or "").lstrip()
    if stripped.startswith("Merge ") or stripped.startswith("Revert "):
        return True
    if (ROOT / ".git" / "MERGE_HEAD").is_file():
        return True
    return False


def analyze(
    files: list[str],
    message: str = "",
    *,
    rules: dict | None = None,
    branch: str = "",
) -> tuple[bool, str]:
    rules = rules or load_rules()
    if not files:
        return True, ""

    msg = message or ""
    if should_skip_commit(msg):
        return True, ""

    primaries: set[str] = set()
    companions: set[str] = set()
    others: list[str] = []
    by_scope: dict[str, list[str]] = {}

    for path in files:
        kind, scope = classify_path(path, rules)
        by_scope.setdefault(scope, []).append(path)
        if kind == "primary":
            primaries.add(scope)
        elif kind == "companion":
            companions.add(scope)
        else:
            others.append(path)

    if len(primaries) <= 1:
        return True, ""

    declared = {s.lower() for s in parse_declared_scopes(msg)}
    if declared and primaries.issubset(declared):
        return True, ""

    if linked_group_allowed(primaries, rules):
        return True, ""

    issue_ids = parse_issue_ids(msg, branch)
    if issue_ids and len(issue_ids) == 1:
        issue = next(iter(issue_ids))
        in_msg = bool(ISSUE_RE.search(msg) or REFS_FOOTER_RE.search(msg))
        in_branch = bool(BRANCH_ISSUE_RE.search(branch) and issue in {
            m.group(1) for m in BRANCH_ISSUE_RE.finditer(branch)
        })
        if in_msg and in_branch:
            return True, ""

    lines = [
        "commit-scope-check: 本次暂存跨越多个 feature 区域，请拆成多次提交。",
        "",
        "检测到的 primary scopes:",
    ]
    for scope in sorted(primaries):
        sample = ", ".join(by_scope.get(scope, [])[:4])
        more = ""
        extra = len(by_scope.get(scope, [])) - 4
        if extra > 0:
            more = f" … +{extra} more"
        lines.append(f"  - {scope}: {sample}{more}")
    if companions:
        lines.append("")
        lines.append("同行 companion 文件（docs / .cursor / hooks 等）可随 primary 一起提交。")
    if others:
        lines.append("")
        lines.append("未归类文件:")
        for path in others[:8]:
            lines.append(f"  - {path}")
    lines.extend(
        [
            "",
            "如何继续:",
            "  1) 推荐：git reset 后按 feature 分拆 git add / git commit",
            "  2) 同一 issue 跨层：分支名与正文都写 Refs: #<id>",
            "  3) 明确多 scope：正文加 Scopes: server, ios-dev",
            "  4) 标题格式见 docs/git-commit-convention.md",
            "  5) 紧急跳过：正文加 [skip-scope-check] 或 SKIP_SCOPE_CHECK=1 git commit",
        ]
    )
    return False, "\n".join(lines)


def read_commit_message(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    message = ""
    if args[:1] == ["--commit-msg"]:
        message = read_commit_message(args[1] if len(args) > 1 else None)
    elif args[:1] == ["--message"]:
        message = args[1] if len(args) > 1 else ""
    elif args[:1] == ["--self-test"]:
        return run_self_test()

    files = staged_files()
    rules = load_rules()
    branch = current_branch()

    fmt_ok, fmt_detail = validate_format(message, rules=rules, staged=files)
    if not fmt_ok:
        print(fmt_detail, file=sys.stderr)
        return 1

    scope_ok, scope_detail = analyze(files, message, rules=rules, branch=branch)
    if not scope_ok:
        print(scope_detail, file=sys.stderr)
        return 1
    return 0


def run_self_test() -> int:
    import unittest

    loader = unittest.TestLoader()
    suite = loader.discover(str(Path(__file__).with_name("tests")), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
