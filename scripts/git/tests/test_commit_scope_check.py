from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import commit_scope_check as csc  # noqa: E402


class CommitScopeCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = json.loads(csc.RULES_PATH.read_text(encoding="utf-8"))

    def test_single_scope_ok(self) -> None:
        files = ["server/home_brain.py", "server/dev_task.py", "docs/agent-roster.md"]
        ok, msg = csc.analyze(files, "feat: fleet api", rules=self.rules)
        self.assertTrue(ok, msg)

    def test_multi_scope_rejected(self) -> None:
        files = ["server/dev_task.py", "character-service/geometry.py"]
        ok, msg = csc.analyze(files, "mixed work", rules=self.rules)
        self.assertFalse(ok)
        self.assertIn("character-service", msg)
        self.assertIn("server", msg)

    def test_declared_scopes_allowed(self) -> None:
        files = ["server/dev_task.py", "ios/HomeAgentDev/HomeAgentDev/DevStore.swift"]
        ok, _ = csc.analyze(
            files,
            "feat(ios-dev): Fleet UI\n\nScopes: server, ios-dev",
            rules=self.rules,
        )
        self.assertTrue(ok)

    def test_linked_group_allowed(self) -> None:
        files = ["agent-bridge/src/agent_bridge/server.py", "chat/mentions.py"]
        ok, _ = csc.analyze(files, "fleet chat handles", rules=self.rules)
        self.assertTrue(ok)

    def test_issue_branch_and_message_allowed(self) -> None:
        files = ["server/dev_task.py", "ios/HomeAgentDev/HomeAgentDev/DevStore.swift"]
        ok, _ = csc.analyze(
            files,
            "fix(ios-dev): Fleet 页展示状态\n\nRefs: #42",
            rules=self.rules,
            branch="feature/42-fleet-tab",
        )
        self.assertTrue(ok)


class CommitMsgFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = json.loads(csc.RULES_PATH.read_text(encoding="utf-8"))

    def test_valid_subject(self) -> None:
        ok, msg = csc.validate_format(
            "feat(server): 新增 agent_fleet API",
            rules=self.rules,
            staged=["server/agent_fleet.py"],
        )
        self.assertTrue(ok, msg)

    def test_invalid_subject(self) -> None:
        ok, _ = csc.validate_format("update stuff", rules=self.rules)
        self.assertFalse(ok)

    def test_scope_mismatch(self) -> None:
        ok, detail = csc.validate_format(
            "feat(server): wrong scope title",
            rules=self.rules,
            staged=["ios/HomeAgentDev/Foo.swift"],
        )
        self.assertFalse(ok)
        self.assertIn("ios-dev", detail)

    def test_docs_scope_for_docs_only(self) -> None:
        ok, _ = csc.validate_format(
            "docs(agent-coordination): 更新 Fleet 说明",
            rules=self.rules,
            staged=["docs/agent-coordination.md"],
        )
        self.assertTrue(ok)

    def test_repo_scope_for_hooks(self) -> None:
        ok, _ = csc.validate_format(
            "chore(repo): 增加 commit message 校验",
            rules=self.rules,
            staged=["scripts/git/commit_scope_check.py"],
        )
        self.assertTrue(ok)

    def test_issue_only_in_message_not_enough(self) -> None:
        files = ["server/dev_task.py", "character-service/geometry.py"]
        ok, _ = csc.analyze(
            files,
            "fix (#42)",
            rules=self.rules,
            branch="main",
        )
        self.assertFalse(ok)

    def test_skip_marker(self) -> None:
        files = ["server/a.py", "character-service/b.py"]
        ok, _ = csc.analyze(files, "wip [skip-scope-check]", rules=self.rules)
        self.assertTrue(ok)

    def test_footer_scopes_parsed(self) -> None:
        scopes = csc.parse_declared_scopes("feat(x): y\n\nScopes: server, ios-dev")
        self.assertEqual(scopes, {"server", "ios-dev"})


if __name__ == "__main__":
    unittest.main()
