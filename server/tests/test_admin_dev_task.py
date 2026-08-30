"""Admin dev_task API for HomeAgent Admin mobile controller."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

os.environ["BRAIN_SKIP_LLM_WORKER"] = "1"
os.environ["BRAIN_ENABLE_DEV_TASK_POLLER"] = "1"

try:
    import flask  # noqa: F401
except ImportError:  # pragma: no cover
    flask = None  # type: ignore

if flask is not None:
    import agent_task_store  # noqa: E402
    import db as brain_db  # noqa: E402
    import home_brain as hb  # noqa: E402
else:
    agent_task_store = None  # type: ignore
    brain_db = None  # type: ignore
    hb = None  # type: ignore


@unittest.skipUnless(flask is not None, "flask not installed in this interpreter")
class AdminDevTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        assert hb is not None
        assert brain_db is not None
        assert agent_task_store is not None
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()
        agent_task_store.reset_store(Path(self.tmp.name) / "agent_tasks.json")
        hb._REGISTERED_edges = brain_db.registration_ids()

    def test_post_admin_dev_task_does_not_create_intent(self) -> None:
        assert hb is not None
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-admin-1", "status": "queued"}
            resp = client.post(
                "/api/v1/admin/dev_task",
                json={"text": "列出 server 目录"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("task_kind"), "dev_task")
        self.assertEqual(body["dev_task"]["bridge_run_id"], "run-admin-1")
        task_id = int(body["task_id"])
        self.assertEqual(body.get("intent_id"), task_id)
        self.assertFalse(hb.get_intent(task_id))

    def test_post_admin_dev_task_with_image_attachment(self) -> None:
        assert hb is not None
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-img", "status": "queued"}
            resp = client.post(
                "/api/v1/admin/dev_task",
                json={
                    "text": "请看截图",
                    "attachments": [
                        {
                            "asset_id": "asset_dev_img",
                            "kind": "image",
                            "mime_type": "image/jpeg",
                        }
                    ],
                },
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body["attachments"][0]["asset_id"], "asset_dev_img")
        submit.assert_called_once()
        kwargs = submit.call_args.kwargs
        self.assertEqual(kwargs.get("brain_url"), "http://localhost")
        self.assertIn("asset_dev_img", submit.call_args.args[0])

    def test_post_admin_dev_task_image_only(self) -> None:
        assert hb is not None
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-only-img", "status": "queued"}
            resp = client.post(
                "/api/v1/admin/dev_task",
                json={
                    "attachments": [
                        {"asset_id": "asset_only", "kind": "image"},
                    ],
                },
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body["attachments"][0]["asset_id"], "asset_only")

    def test_upload_admin_dev_task_attachment(self) -> None:
        assert hb is not None
        jpeg = b"\xff\xd8\xffdev-task"
        upload_root = Path(self.tmp.name) / "gopropics"
        prev_origin = os.environ.get("BRAIN_ORIGIN")
        prev_img = os.environ.get("BRAIN_IMG_UPLOAD_URL")
        prev_photo = os.environ.get("PHOTO_UPLOAD_URL")
        prev_upload = hb.UPLOAD_DIR
        prev_asset_dir = hb._ASSET_UPLOAD_DIR
        os.environ["BRAIN_ORIGIN"] = "cloud"
        os.environ.pop("BRAIN_IMG_UPLOAD_URL", None)
        os.environ.pop("PHOTO_UPLOAD_URL", None)
        hb.UPLOAD_DIR = upload_root
        hb._ASSET_UPLOAD_DIR = None
        client = hb.app.test_client()
        try:
            resp = client.post(
                "/api/v1/admin/dev_task/attachment/upload",
                data={
                    "kind": "image",
                    "mime_type": "image/jpeg",
                    "file": (BytesIO(jpeg), "shot.jpg"),
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertTrue(body.get("ok"))
            attachment = body.get("attachment") or {}
            aid = str(attachment.get("asset_id") or "")
            self.assertTrue(aid.startswith("asset_"))
            content = client.get(
                f"/api/v1/assets/{aid}/content",
                query_string={"intent_id": "dev_task:1"},
            )
            self.assertEqual(content.status_code, 403)
        finally:
            hb.UPLOAD_DIR = prev_upload
            hb._ASSET_UPLOAD_DIR = prev_asset_dir
            if prev_origin is None:
                os.environ.pop("BRAIN_ORIGIN", None)
            else:
                os.environ["BRAIN_ORIGIN"] = prev_origin
            if prev_img is None:
                os.environ.pop("BRAIN_IMG_UPLOAD_URL", None)
            else:
                os.environ["BRAIN_IMG_UPLOAD_URL"] = prev_img
            if prev_photo is None:
                os.environ.pop("PHOTO_UPLOAD_URL", None)
            else:
                os.environ["PHOTO_UPLOAD_URL"] = prev_photo

    def test_list_admin_dev_tasks_only_agent_store(self) -> None:
        assert hb is not None
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-a", "status": "queued"}
            client.post("/api/v1/admin/dev_task", json={"text": "dev one"})
        hb.new_intent({"status": "intent_received", "text": "normal", "source": "text"})
        resp = client.get("/api/v1/admin/dev_tasks?limit=10")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        tasks = body.get("tasks") or []
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].get("text"), "dev one")


if __name__ == "__main__":
    unittest.main()
