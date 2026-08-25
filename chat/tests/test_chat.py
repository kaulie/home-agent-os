from __future__ import annotations

import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from time import sleep

from chat import db
from chat.mentions import audience_for, normalize_handle, parse_mentions, recipients_for, visible_to
from chat.serve import ChatHandler, ThreadingHTTPServer


class MentionTests(unittest.TestCase):
    def test_user_no_mention(self) -> None:
        self.assertEqual(parse_mentions("记一笔，先不用做"), [])
        self.assertEqual(audience_for("boss", []), [])
        self.assertEqual(audience_for("owner", []), [])

    def test_user_and_owner_alias_is_boss(self) -> None:
        self.assertEqual(normalize_handle("user"), "boss")
        self.assertEqual(normalize_handle("owner"), "boss")
        self.assertEqual(normalize_handle("boss"), "boss")
        self.assertEqual(parse_mentions("@user 你好"), ["boss"])
        self.assertEqual(parse_mentions("@owner 看这里"), ["boss"])
        self.assertEqual(parse_mentions("@boss 看这里"), ["boss"])

    def test_all_aliases(self) -> None:
        self.assertEqual(parse_mentions("@all 对齐"), ["all"])
        self.assertEqual(parse_mentions("@所有人 对齐"), ["all"])
        self.assertEqual(parse_mentions("@everyone 对齐"), ["all"])
        self.assertEqual(audience_for("boss", ["all"]), ["all"])

    def test_specific_handles(self) -> None:
        self.assertEqual(parse_mentions("@brain 去看 intent 71"), ["brain"])
        self.assertEqual(parse_mentions("@brain @intent 两步"), ["brain", "intent"])
        self.assertEqual(parse_mentions("@dev 非法"), [])
        self.assertEqual(parse_mentions("@observer 也算 coordinator"), ["coordinator"])

    def test_all_wins_over_specific(self) -> None:
        self.assertEqual(parse_mentions("@brain @all 全员"), ["all"])

    def test_agent_without_mention_is_public(self) -> None:
        self.assertEqual(audience_for("runtime", []), ["all"])

    def test_visibility(self) -> None:
        self.assertFalse(visible_to([], "brain"))
        self.assertTrue(visible_to(["all"], "runtime"))
        self.assertTrue(visible_to(["brain"], "brain"))
        self.assertFalse(visible_to(["brain"], "runtime"))

    def test_recipients(self) -> None:
        self.assertEqual(recipients_for("boss", []), ["boss"])
        self.assertEqual(recipients_for("owner", []), ["boss"])
        self.assertEqual(recipients_for("boss", ["brain"]), ["brain"])
        self.assertEqual(recipients_for("boss", ["all"]), [
            "coordinator", "brain", "runtime", "intent", "capability", "endpoint", "quality", "dba",
        ])
        recips = recipients_for("brain", ["all"])
        self.assertIn("boss", recips)
        self.assertIn("runtime", recips)
        self.assertEqual(recipients_for("brain", ["boss"]), ["boss"])
        self.assertEqual(recipients_for("brain", ["owner"]), ["boss"])


class DbPullTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db.reset(path=Path(self.tmp.name) / "agent_chat.sqlite3")

    def tearDown(self) -> None:
        db.reset()
        self.tmp.cleanup()

    def test_user_note_not_in_pull(self) -> None:
        db.push_message(from_handle="boss", body="只是笔记")
        pulled = db.pull_messages(handle="brain")
        self.assertEqual(pulled["messages"], [])
        self.assertGreaterEqual(pulled["last_id"], 1)
        page = db.list_messages(since_id=0)
        self.assertEqual(len(page), 1)
        self.assertEqual(page[0]["audience"], [])

    def test_directed_message_only_target_sees(self) -> None:
        db.push_message(from_handle="owner", body="@brain 去看 intent 71")
        brain = db.pull_messages(handle="brain")
        runtime = db.pull_messages(handle="runtime")
        self.assertEqual(len(brain["messages"]), 1)
        self.assertEqual(brain["messages"][0]["from"], "boss")
        self.assertEqual(runtime["messages"], [])

    def test_all_visible_to_every_handle(self) -> None:
        db.push_message(from_handle="boss", body="@all 对齐 Asset")
        for handle in ("coordinator", "brain", "runtime", "intent", "capability", "endpoint", "quality", "dba"):
            db.reset(path=Path(self.tmp.name) / "agent_chat.sqlite3")
            pulled = db.pull_messages(handle=handle)
            self.assertEqual(len(pulled["messages"]), 1, handle)

    def test_watermark_second_pull_empty(self) -> None:
        db.push_message(from_handle="boss", body="@brain 第一封")
        first = db.pull_messages(handle="brain")
        self.assertEqual(len(first["messages"]), 1)
        second = db.pull_messages(handle="brain")
        self.assertEqual(second["messages"], [])

    def test_agent_public_speech(self) -> None:
        db.push_message(from_handle="brain", body="本层已读 Asset")
        pulled = db.pull_messages(handle="runtime")
        self.assertEqual(len(pulled["messages"]), 1)
        self.assertEqual(pulled["messages"][0]["audience"], ["all"])

    def test_unread_until_pull_or_mark(self) -> None:
        directed = db.push_message(from_handle="boss", body="@brain 去看 intent 71")
        self.assertEqual(directed["unread"], ["brain"])
        self.assertNotIn("brain", directed["read"])
        agents = {a["handle"]: a for a in db.list_agents()}
        self.assertEqual(agents["brain"]["unread"], 1)
        self.assertEqual(agents["runtime"]["unread"], 0)
        pulled = db.pull_messages(handle="brain")
        self.assertEqual(pulled["messages"][0]["unread"], [])
        self.assertIn("brain", pulled["messages"][0]["read"])
        agents = {a["handle"]: a for a in db.list_agents()}
        self.assertEqual(agents["brain"]["unread"], 0)

        reply = db.push_message(from_handle="brain", body="@owner 已看 intent 71")
        self.assertEqual(reply["unread"], ["boss"])
        self.assertEqual(db.boss_unread_count(), 1)
        marked = db.mark_read(handle="owner", ids=[reply["id"]])
        self.assertEqual(marked["unread"], 0)
        page = db.list_messages(since_id=0)
        last = [m for m in page if m["id"] == reply["id"]][0]
        self.assertEqual(last["unread"], [])
        self.assertIn("boss", last["read"])

    def test_recall_within_minute_if_unseen(self) -> None:
        msg = db.push_message(from_handle="boss", body="@brain 先发错了")
        recalled = db.recall_message(from_handle="boss", msg_id=msg["id"])
        self.assertTrue(recalled["recalled"])
        self.assertEqual(recalled["body"], "")
        pulled = db.pull_messages(handle="brain")
        self.assertEqual(pulled["messages"], [])
        page = db.list_messages(since_id=0)
        self.assertTrue(page[0]["recalled"])

    def test_recall_fails_after_seen(self) -> None:
        msg = db.push_message(from_handle="boss", body="@brain 已发出")
        db.pull_messages(handle="brain")
        with self.assertRaisesRegex(ValueError, "已有人看过"):
            db.recall_message(from_handle="boss", msg_id=msg["id"])

    def test_recall_fails_if_not_sender(self) -> None:
        msg = db.push_message(from_handle="boss", body="@brain 不是你的")
        with self.assertRaisesRegex(ValueError, "只能撤回自己"):
            db.recall_message(from_handle="runtime", msg_id=msg["id"])

    def test_recall_fails_after_one_minute(self) -> None:
        import time

        msg = db.push_message(from_handle="boss", body="@brain 超时")
        with db.locked():
            conn = db._connect()
            conn.execute(
                "UPDATE messages SET created_at = ? WHERE id = ?",
                (time.time() - 61, msg["id"]),
            )
            conn.commit()
        with self.assertRaisesRegex(ValueError, "超过 1 分钟"):
            db.recall_message(from_handle="boss", msg_id=msg["id"])


class HttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db.reset(path=Path(self.tmp.name) / "agent_chat.sqlite3")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ChatHandler)
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        sleep(0.05)
        self.host, self.port = self.httpd.server_address[:2]

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        db.reset()
        self.tmp.cleanup()

    def _json(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        conn = HTTPConnection(self.host, self.port, timeout=5)
        payload = None
        headers = {}
        if body is not None:
            import json

            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        import json

        return resp.status, json.loads(raw)

    def test_push_and_pull_routes(self) -> None:
        status, note = self._json("POST", "/api/v1/push_msg", {"from": "boss", "body": "未点名笔记"})
        self.assertEqual(status, 200)
        self.assertEqual(note["message"]["audience"], [])
        status, brain = self._json("GET", "/api/v1/pull_msg?handle=brain")
        self.assertEqual(status, 200)
        self.assertEqual(brain["messages"], [])
        status, _ = self._json("POST", "/api/v1/push_msg", {"from": "owner", "body": "@brain 去看 intent 71"})
        self.assertEqual(status, 200)
        status, brain = self._json("GET", "/api/v1/pull_msg?handle=brain")
        self.assertEqual(status, 200)
        self.assertEqual(len(brain["messages"]), 1)
        status, runtime = self._json("GET", "/api/v1/pull_msg?handle=runtime")
        self.assertEqual(runtime["messages"], [])
        status, page = self._json("GET", "/api/v1/messages")
        self.assertEqual(status, 200)
        self.assertEqual(len(page["messages"]), 2)
        directed = [m for m in page["messages"] if m["audience"] == ["brain"]][0]
        self.assertEqual(directed["unread"], [])
        self.assertIn("brain", directed["read"])
        status, mark = self._json("POST", "/api/v1/mark_read", {"from": "owner", "ids": [directed["id"]]})
        self.assertEqual(status, 200)

    def test_recall_route(self) -> None:
        status, posted = self._json(
            "POST", "/api/v1/push_msg", {"from": "owner", "body": "@brain 马上撤回"}
        )
        msg_id = posted["message"]["id"]
        status, recalled = self._json(
            "POST", "/api/v1/recall_msg", {"from": "owner", "id": msg_id}
        )
        self.assertEqual(status, 200)
        self.assertTrue(recalled["message"]["recalled"])
        status, brain = self._json("GET", "/api/v1/pull_msg?handle=brain")
        self.assertEqual(brain["messages"], [])


if __name__ == "__main__":
    unittest.main()
