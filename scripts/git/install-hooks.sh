#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

chmod +x .githooks/commit-msg
chmod +x scripts/git/commit_scope_check.py

git config core.hooksPath .githooks
git config commit.template .githooks/commit-template.txt

echo "Installed git hooks -> .githooks/commit-msg"
echo "Commit template -> .githooks/commit-template.txt"
echo "Self-test: python3 scripts/git/commit_scope_check.py --self-test"
