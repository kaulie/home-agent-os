from __future__ import annotations

import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from time import sleep

from chat import db
from chat import attachments as chat_attachments
from chat.mentions import (
    HANDLE_DUTIES,
    audience_for,
    normalize_handle,
    parse_mention_roles,
    parse_mentions,
    recipients_for,
    visible_to,
)
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
        self.assertEqual(parse_mentions("@brain @intent 两步"), ["brain", "ui"])
        self.assertEqual(parse_mentions("@brain @endpoint Cast"), ["brain", "ui"])
        self.assertEqual(parse_mentions("@dev 非法"), [])
        self.assertEqual(parse_mentions("@observer 也算 coordinator"), ["coordinator"])

    def test_handle_aliases(self) -> None:
        self.assertEqual(normalize_handle("intent"), "ui")
        self.assertEqual(normalize_handle("endpoint"), "ui")

    def test_handle_duties_roster(self) -> None:
        self.assertIn("ui", HANDLE_DUTIES)
        self.assertIn("controller", HANDLE_DUTIES)
        self.assertTrue(HANDLE_DUTIES["ui"])

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
            "coordinator", "controller", "brain", "runtime", "ui",
            "capability", "quality", "deploy", "sre", "dba",
        ])
        recips = recipients_for("brain", ["all"])
        self.assertIn("boss", recips)
        self.assertIn("runtime", recips)
        self.assertEqual(recipients_for("brain", ["boss"]), ["boss"])
        self.assertEqual(recipients_for("brain", ["owner"]), ["boss"])

    def test_cc_roles(self) -> None:
        roles = parse_mention_roles("@runtime 做分路。cc @controller @boss")
        self.assertEqual(roles.action, ["runtime"])
        self.assertEqual(roles.cc, ["controller", "boss"])
        self.assertEqual(roles.all_mentions, ["runtime", "controller", "boss"])
        self.assertEqual(parse_mentions("@runtime 做分路。cc @controller @boss"), roles.all_mentions)

    def test_cc_colon_and_primary_wins(self) -> None:
        roles = parse_mention_roles("@ui 改按钮 cc:@sre")
        self.assertEqual(roles.action, ["ui"])
        self.assertEqual(roles.cc, ["sre"])
        both = parse_mention_roles("@controller 主送。cc @controller @boss")
        self.assertEqual(both.action, ["controller"])
        self.assertEqual(both.cc, ["boss"])

    def test_cc_only(self) -> None:
        roles = parse_mention_roles("FYI cc @sre @deploy")
        self.assertEqual(roles.action, [])
        self.assertEqual(roles.cc, ["sre", "deploy"])
        self.assertEqual(roles.all_mentions, ["sre", "deploy"])

    def test_acc_not_cc(self) -> None:
        roles = parse_mention_roles("acc @runtime 不是抄送")
        self.assertEqual(roles.action, ["runtime"])
        self.assertEqual(roles.cc, [])


class DbPullTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db.reset(path=Path(self.tmp.name) / "agent_chat.sqlite3")
        chat_attachments.reset_upload_root(Path(self.tmp.name) / "uploads")

    def tearDown(self) -> None:
        chat_attachments.reset_upload_root(None)
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

    def test_cc_stored_and_visible(self) -> None:
        msg = db.push_message(
            from_handle="boss",
            body="@runtime 做分路。cc @controller @sre",
        )
        self.assertEqual(msg["action"], ["runtime"])
        self.assertEqual(msg["cc"], ["controller", "sre"])
        self.assertEqual(msg["mentions"], ["runtime", "controller", "sre"])
        self.assertEqual(msg["audience"], ["runtime", "controller", "sre"])
        runtime = db.pull_messages(handle="runtime")
        sre = db.pull_messages(handle="sre")
        ui = db.pull_messages(handle="ui")
        self.assertEqual(len(runtime["messages"]), 1)
        self.assertEqual(len(sre["messages"]), 1)
        self.assertEqual(ui["messages"], [])

    def test_ack_message_badge(self) -> None:
        msg = db.push_message(from_handle="boss", body="@runtime 主送。cc @sre")
        got = db.ack_message(from_handle="sre", message_id=msg["id"], ack_type="got")
        self.assertEqual(len(got["acks"]), 1)
        self.assertEqual(got["acks"][0]["handle"], "sre")
        self.assertEqual(got["acks"][0]["ack_type"], "got")
        recv = db.ack_message(from_handle="runtime", message_id=msg["id"], ack_type="recv")
        types = {a["handle"]: a["ack_type"] for a in recv["acks"]}
        self.assertEqual(types["sre"], "got")
        self.assertEqual(types["runtime"], "recv")
        # Switching type upserts
        switched = db.ack_message(from_handle="sre", message_id=msg["id"], ack_type="recv")
        types2 = {a["handle"]: a["ack_type"] for a in switched["acks"]}
        self.assertEqual(types2["sre"], "recv")
        cleared = db.unack_message(from_handle="sre", message_id=msg["id"])
        self.assertTrue(all(a["handle"] != "sre" for a in cleared["acks"]))
        patches, latest = db.ack_patches(since_ack_at=0)
        self.assertTrue(latest > 0)
        self.assertTrue(any(p["id"] == msg["id"] for p in patches))

    def test_directed_message_only_target_sees(self) -> None:
        db.push_message(from_handle="owner", body="@brain 去看 intent 71")
        brain = db.pull_messages(handle="brain")
        runtime = db.pull_messages(handle="runtime")
        self.assertEqual(len(brain["messages"]), 1)
        self.assertEqual(brain["messages"][0]["from"], "boss")
        self.assertEqual(runtime["messages"], [])

    def test_all_visible_to_every_handle(self) -> None:
        db.push_message(from_handle="boss", body="@all 对齐 Asset")
        fleet_handles = (
            "coordinator", "controller", "brain", "runtime", "ui",
            "capability", "quality", "deploy", "sre", "dba",
        )
        for handle in fleet_handles:
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

    def test_push_message_with_image_attachment(self) -> None:
        row = chat_attachments.store_image(b"\xff\xd8\xffchat", filename="a.jpg")
        msg = db.push_message(
            from_handle="boss",
            body="@brain 请看图",
            attachments=[row],
        )
        self.assertEqual(msg["attachments"][0]["attachment_id"], row["attachment_id"])
        pulled = db.pull_messages(handle="brain")
        self.assertEqual(len(pulled["messages"]), 1)
        self.assertEqual(pulled["messages"][0]["attachments"][0]["attachment_id"], row["attachment_id"])

    def test_push_message_image_only(self) -> None:
        row = chat_attachments.store_image(b"\xff\xd8\xffonly", filename="only.jpg")
        msg = db.push_message(from_handle="boss", body="", attachments=[row])
        self.assertEqual(len(msg["attachments"]), 1)


class HttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db.reset(path=Path(self.tmp.name) / "agent_chat.sqlite3")
        chat_attachments.reset_upload_root(Path(self.tmp.name) / "uploads")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ChatHandler)
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        sleep(0.05)
        self.host, self.port = self.httpd.server_address[:2]

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        chat_attachments.reset_upload_root(None)
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


    def _multipart_upload(self, data: bytes, filename: str = "shot.jpg") -> tuple[int, dict]:
        boundary = "TestBoundary"
        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                "Content-Type: image/jpeg\r\n\r\n"
            ).encode()
        )
        body.extend(data)
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request(
            "POST",
            "/api/v1/attachment/upload",
            body=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        import json

        return resp.status, json.loads(raw)

    def test_chat_attachment_upload_and_send(self) -> None:
        status, uploaded = self._multipart_upload(b"\xff\xd8\xffhttp")
        self.assertEqual(status, 200)
        aid = uploaded["attachment"]["attachment_id"]
        status, posted = self._json(
            "POST",
            "/api/v1/push_msg",
            {
                "from": "boss",
                "body": "@brain 图",
                "attachments": [uploaded["attachment"]],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(posted["message"]["attachments"][0]["attachment_id"], aid)
        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request("GET", f"/api/v1/attachments/{aid}/content")
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertEqual(payload, b"\xff\xd8\xffhttp")

    def test_work_board_route(self) -> None:
        status, data = self._json("GET", "/api/v1/work_board")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertIn("handles", data)
        self.assertIn("ui", data["handles"])

    def test_messages_include_handle_duties(self) -> None:
        status, data = self._json("GET", "/api/v1/messages")
        self.assertEqual(status, 200)
        self.assertIn("handle_duties", data)
        self.assertIn("ui", data["handle_duties"])
        self.assertIn("controller", data["display_names"])

    def test_agent_fleet_proxy_route(self) -> None:
        status, data = self._json("GET", "/api/v1/agent_fleet")
        self.assertEqual(status, 200)
        self.assertIn("agents", data)
        if not data.get("ok"):
            self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
