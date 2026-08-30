"""Agent Chat admin proxy tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

os.environ["BRAIN_SKIP_LLM_WORKER"] = "1"

import agent_chat  # noqa: E402


class AgentChatTests(unittest.TestCase):
    def test_build_promoted_task_text(self) -> None:
        text = agent_chat.build_promoted_task_text(
            "fix console spacing",
            [
                {"from": "boss", "body": "@ui thoughts?"},
                {"from": "ui", "body": "Fleet tab needs work"},
            ],
        )
        self.assertIn("## Background", text)
        self.assertIn("## Task", text)
        self.assertIn("fix console spacing", text)

    def test_related_background_from_messages(self) -> None:
        rows = agent_chat.related_background_from_messages(
            [
                {"id": 1, "from": "boss", "body": "hi"},
                {"id": 2, "from": "brain", "body": "hello"},
                {"id": 3, "from": "boss", "body": "task"},
            ],
            anchor_id=3,
            limit=2,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["body"], "task")

    def test_related_background_from_message_ids(self) -> None:
        rows = agent_chat.related_background_from_messages(
            [
                {"id": 1, "from": "boss", "body": "a"},
                {"id": 2, "from": "brain", "body": "b"},
                {"id": 3, "from": "boss", "body": "c"},
            ],
            message_ids=[3, 1],
        )
        self.assertEqual([row["id"] for row in rows], [1, 3])
        self.assertEqual(rows[0]["body"], "a")
        self.assertEqual(rows[1]["body"], "c")

    @patch("agent_chat.submit_agent_task")
    def test_promote_chat_to_dev_task(self, submit) -> None:
        submit.return_value = {"task_id": 9, "status": "queued"}
        out = agent_chat.promote_chat_to_dev_task(
            task_text="ship feature",
            target_handle="ui",
            category="feature",
            background_messages=[{"from": "boss", "body": "context"}],
        )
        self.assertTrue(out.get("ok"))
        submit.assert_called_once()

    def test_resolve_chat_url_cloud_default(self) -> None:
        with patch.dict(
            os.environ,
            {"CHAT_URL": "", "BRAIN_ORIGIN": "cloud"},
            clear=False,
        ):
            self.assertEqual(agent_chat.resolve_chat_url(), "http://127.0.0.1:18787")

    def test_resolve_chat_url_lan_default(self) -> None:
        with patch.dict(
            os.environ,
            {"CHAT_URL": "", "BRAIN_ORIGIN": "lan"},
            clear=False,
        ):
            self.assertEqual(agent_chat.resolve_chat_url(), "http://127.0.0.1:8787")

    def test_resolve_chat_url_explicit_override(self) -> None:
        with patch.dict(
            os.environ,
            {"CHAT_URL": "http://example.test:9999", "BRAIN_ORIGIN": "cloud"},
            clear=False,
        ):
            self.assertEqual(agent_chat.resolve_chat_url(), "http://example.test:9999")

    def test_unwrap_chat_message_nested(self) -> None:
        inner = {"id": 7, "from": "boss", "body": "@brain hi"}
        wrapped = {"ok": True, "message": inner}
        self.assertEqual(agent_chat._unwrap_chat_message(wrapped), inner)

    def test_unwrap_chat_message_flat(self) -> None:
        flat = {"id": 8, "from": "boss", "body": "hello"}
        self.assertEqual(agent_chat._unwrap_chat_message(flat), flat)

    @patch("agent_chat._request")
    def test_send_boss_message_unwraps_nested_payload(self, request) -> None:
        request.return_value = {
            "ok": True,
            "message": {"id": 9, "from": "boss", "body": "@brain ping"},
        }
        out = agent_chat.send_boss_message("@brain ping")
        self.assertEqual(out["id"], 9)
        self.assertEqual(out["body"], "@brain ping")

    @patch("agent_chat._request")
    def test_send_boss_message_with_attachments(self, request) -> None:
        request.return_value = {
            "ok": True,
            "message": {
                "id": 10,
                "from": "boss",
                "body": "@brain 图",
                "attachments": [{"attachment_id": "chatimg_abc", "kind": "image"}],
            },
        }
        out = agent_chat.send_boss_message(
            "@brain 图",
            attachments=[{"attachment_id": "chatimg_abc", "kind": "image"}],
        )
        self.assertEqual(out["attachments"][0]["attachment_id"], "chatimg_abc")
        _args, kwargs = request.call_args
        self.assertEqual(kwargs["body"]["attachments"][0]["attachment_id"], "chatimg_abc")


if __name__ == "__main__":
    unittest.main()
