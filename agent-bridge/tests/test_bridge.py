from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_bridge.config import BridgeConfig
from agent_bridge.fleet_state import FleetStateStore
from agent_bridge.runner import AgentRunner
from agent_bridge.server import create_app
from agent_bridge.state import StateStore


def _fleet(tmp: str) -> FleetStateStore:
    return FleetStateStore(Path(tmp))


class StateStoreTests(unittest.TestCase):
    def test_persist_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp))
            run = store.create_run("hello")
            store.set_agent_id("agent-1")
            store.update_run(run.run_id, status="finished", result="ok")

            store2 = StateStore(Path(tmp))
            self.assertEqual(store2.get_agent_id(), "agent-1")
            got = store2.get_run(run.run_id)
            assert got is not None
            self.assertEqual(got.status, "finished")
            self.assertEqual(got.result, "ok")


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = StateStore(Path(self.tmp.name))
        self.fleet = FleetStateStore(Path(self.tmp.name))
        self.config = BridgeConfig(
            host="127.0.0.1",
            port=9540,
            cwd=Path(self.tmp.name),
            data_dir=Path(self.tmp.name),
            model="composer-2.5",
            api_key="test-key",
            auth_token="secret",
            cursor_agent_bin=None,
        )
        self.runner = MagicMock()
        self.runner.pending_queue_depth.return_value = 0
        self.runner.fleet_status = MagicMock(return_value=[])
        self.runner.status.return_value = {
            "agent_id": None,
            "agent_connected": False,
            "active_run_id": None,
            "active_status": None,
            "cwd": str(self.config.cwd),
            "model": self.config.model,
        }
        self.app = create_app(self.config, self.store, self.fleet, self.runner)
        self.client = self.app.test_client()

    def _auth(self) -> dict[str, str]:
        return {"Authorization": "Bearer secret"}

    def test_health(self) -> None:
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_command_requires_auth(self) -> None:
        resp = self.client.post(
            "/api/v1/command",
            json={"text": "do something"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_list_agents(self) -> None:
        self.runner.fleet_status.return_value = [{"handle": "brain", "agent_id": None}]
        resp = self.client.get("/api/v1/agents", headers=self._auth())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.get_json()["agents"]), 1)

    def test_wake_agent(self) -> None:
        with patch("agent_bridge.server.wake_handle") as wake:
            wake.return_value = {"handle": "brain", "run_id": "abc", "status": "queued"}
            resp = self.client.post(
                "/api/v1/agents/brain/wake",
                headers=self._auth(),
                json={"text": "fix planner"},
            )
            self.assertEqual(resp.status_code, 202)
            wake.assert_called_once()

    def test_command_enqueues_run(self) -> None:
        resp = self.client.post(
            "/api/v1/command",
            headers=self._auth(),
            json={"text": "do something"},
        )
        self.assertEqual(resp.status_code, 202)
        body = resp.get_json()
        self.assertIn("run_id", body)
        self.runner.enqueue.assert_called_once_with(body["run_id"])

        got = self.client.get(
            f"/api/v1/runs/{body['run_id']}",
            headers=self._auth(),
        )
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["status"], "queued")

    def test_command_rejects_empty_text(self) -> None:
        resp = self.client.post(
            "/api/v1/command",
            headers=self._auth(),
            json={"text": "  "},
        )
        self.assertEqual(resp.status_code, 400)

    def test_command_accepts_attachments_with_brain_url(self) -> None:
        resp = self.client.post(
            "/api/v1/command",
            headers=self._auth(),
            json={
                "text": "analyze screenshot",
                "task_id": 42,
                "brain_url": "http://192.168.3.73:9527",
                "attachments": [
                    {
                        "asset_id": "asset_abc",
                        "kind": "image",
                        "mime_type": "image/jpeg",
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 202)
        body = resp.get_json()
        run = self.store.get_run(body["run_id"])
        assert run is not None
        self.assertEqual(run.brain_url, "http://192.168.3.73:9527")
        self.assertEqual(run.attachments[0]["asset_id"], "asset_abc")

    def test_command_queues_when_busy(self) -> None:
        busy = self.store.create_run("in flight")
        self.store.update_run(busy.run_id, status="running")
        self.runner.pending_queue_depth.return_value = 1
        resp = self.client.post(
            "/api/v1/command",
            headers=self._auth(),
            json={"text": "next"},
        )
        self.assertEqual(resp.status_code, 202)
        body = resp.get_json()
        self.assertIn("run_id", body)
        self.assertEqual(body.get("status"), "queued")
        self.assertEqual(body.get("queue_depth"), 1)
        self.runner.enqueue.assert_called_once_with(body["run_id"])

        self.runner.enqueue.assert_called_once_with(body["run_id"])


class RunnerTests(unittest.TestCase):
    @patch("agent_bridge.runner.Agent")
    def test_execute_run_streams_and_finishes(self, agent_cls: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp))
            config = BridgeConfig(
                host="127.0.0.1",
                port=9540,
                cwd=Path(tmp),
                data_dir=Path(tmp),
                model="composer-2.5",
                api_key="test-key",
                auth_token=None,
                cursor_agent_bin=None,
            )
            fleet = _fleet(tmp)
            run = store.create_run("say hi")

            agent = MagicMock()
            agent.agent_id = "agent-42"
            agent_cls.create.return_value = agent

            sdk_run = MagicMock()
            block = MagicMock()
            block.type = "text"
            block.text = "hello"
            assistant = MagicMock()
            assistant.type = "assistant"
            assistant.message.content = [block]
            sdk_run.messages.return_value = [assistant]
            sdk_run.wait.return_value = MagicMock(
                status="finished",
                result="done",
            )
            agent.send.return_value = sdk_run

            runner = AgentRunner(config, store, fleet)
            runner._execute_run(run.run_id)

            got = store.get_run(run.run_id)
            assert got is not None
            self.assertEqual(got.status, "finished")
            self.assertEqual(got.result, "done")
            self.assertEqual(fleet.get_agent_id("controller"), "agent-42")
            self.assertTrue(any(e.get("type") == "assistant" for e in got.events))


class RunnerCancelTests(unittest.TestCase):
    def test_cancel_queued_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp))
            config = BridgeConfig(
                host="127.0.0.1",
                port=9540,
                cwd=Path(tmp),
                data_dir=Path(tmp),
                model="composer-2.5",
                api_key="test-key",
                auth_token=None,
                cursor_agent_bin=None,
            )
            fleet = _fleet(tmp)
            runner = AgentRunner(config, store, fleet)
            run = store.create_run("queued")
            runner.enqueue(run.run_id)
            result = runner.cancel_run(run.run_id)
            assert result is not None
            self.assertTrue(result.get("cancelled"))
            got = store.get_run(run.run_id)
            assert got is not None
            self.assertEqual(got.status, "cancelled")

    def test_cancel_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp))
            config = BridgeConfig(
                host="127.0.0.1",
                port=9540,
                cwd=Path(tmp),
                data_dir=Path(tmp),
                model="composer-2.5",
                api_key="test-key",
                auth_token="secret",
                cursor_agent_bin=None,
            )
            fleet = _fleet(tmp)
            runner = AgentRunner(config, store, fleet)
            app = create_app(config, store, fleet, runner)
            client = app.test_client()
            runner.start()
            try:
                resp = client.post(
                    "/api/v1/command",
                    headers={"Authorization": "Bearer secret"},
                    json={"text": "wait"},
                )
                run_id = resp.get_json()["run_id"]
                cancel = client.post(
                    f"/api/v1/runs/{run_id}/cancel",
                    headers={"Authorization": "Bearer secret"},
                )
                self.assertEqual(cancel.status_code, 200)
                body = cancel.get_json()
                self.assertTrue(body.get("cancelled"))
                got = store.get_run(run_id)
                assert got is not None
                self.assertEqual(got.status, "cancelled")
            finally:
                runner.shutdown()


class CliBackendTests(unittest.TestCase):
    @patch("agent_bridge.cli_backend.subprocess.Popen")
    def test_execute_cli_run_parses_stream_json(self, popen_cls: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp))
            config = BridgeConfig(
                host="127.0.0.1",
                port=9540,
                cwd=Path(tmp),
                data_dir=Path(tmp),
                model="composer-2.5",
                api_key=None,
                auth_token=None,
                cursor_agent_bin="/usr/bin/cursor-agent",
            )
            fleet = _fleet(tmp)
            run = store.create_run("say hi")

            proc = MagicMock()
            proc.stdout = iter(
                [
                    json.dumps(
                        {
                            "type": "system",
                            "session_id": "sess-1",
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [{"type": "text", "text": "hello"}],
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "type": "result",
                            "is_error": False,
                            "result": "hello",
                            "usage": {
                                "inputTokens": 100,
                                "outputTokens": 20,
                                "cacheReadTokens": 5,
                            },
                        }
                    )
                    + "\n",
                ]
            )
            proc.stderr = MagicMock()
            proc.stderr.read.return_value = ""
            proc.wait.return_value = 0
            popen_cls.return_value = proc

            from agent_bridge.cli_backend import execute_cli_run

            execute_cli_run(run.run_id, config=config, store=store, fleet=fleet)

            got = store.get_run(run.run_id)
            assert got is not None
            self.assertEqual(got.status, "finished")
            self.assertEqual(got.result, "hello")
            self.assertEqual(got.usage.get("total_tokens"), 120)
            self.assertEqual(fleet.get_agent_id("controller"), "sess-1")

    @patch("agent_bridge.cli_backend.subprocess.Popen")
    def test_execute_cli_run_retries_when_resume_session_missing(self, popen_cls: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp))
            fleet = _fleet(tmp)
            fleet.set_agent_id("controller", "stale-session")
            config = BridgeConfig(
                host="127.0.0.1",
                port=9540,
                cwd=Path(tmp),
                data_dir=Path(tmp),
                model="composer-2.5",
                api_key=None,
                auth_token=None,
                cursor_agent_bin="/usr/bin/cursor-agent",
            )
            run = store.create_run("retry me")

            stale = MagicMock()
            stale.stdout = iter([])
            stale.stderr = MagicMock()
            stale.stderr.read.return_value = "Agent stale-session not found"
            stale.wait.return_value = 1

            ok = MagicMock()
            ok.stdout = iter(
                [
                    json.dumps({"type": "system", "session_id": "sess-2"}) + "\n",
                    json.dumps(
                        {
                            "type": "result",
                            "is_error": False,
                            "result": "ok",
                        }
                    )
                    + "\n",
                ]
            )
            ok.stderr = MagicMock()
            ok.stderr.read.return_value = ""
            ok.wait.return_value = 0
            popen_cls.side_effect = [stale, ok]

            from agent_bridge.cli_backend import execute_cli_run

            execute_cli_run(run.run_id, config=config, store=store, fleet=fleet)

            got = store.get_run(run.run_id)
            assert got is not None
            self.assertEqual(got.status, "finished")
            self.assertEqual(got.result, "ok")
            self.assertEqual(fleet.get_agent_id("controller"), "sess-2")
            self.assertEqual(popen_cls.call_count, 2)


class RunnerRecoveryTests(unittest.TestCase):
    def test_recover_requeues_persisted_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp))
            running = store.create_run("stuck")
            store.update_run(running.run_id, status="running", started_at=1.0)
            queued = store.create_run("waiting")
            config = BridgeConfig(
                host="127.0.0.1",
                port=9540,
                cwd=Path(tmp),
                data_dir=Path(tmp),
                model="composer-2.5",
                api_key=None,
                auth_token=None,
                cursor_agent_bin="/usr/bin/cursor-agent",
            )
            fleet = _fleet(tmp)
            runner = AgentRunner(config, store, fleet)
            runner._recover_after_restart()
            got_running = store.get_run(running.run_id)
            got_queued = store.get_run(queued.run_id)
            assert got_running is not None
            assert got_queued is not None
            self.assertEqual(got_running.status, "error")
            self.assertIn("bridge restarted", got_running.error or "")
            with runner._queue_cv:
                self.assertIn(queued.run_id, runner._queue)


class RunnerQueueTests(unittest.TestCase):
    def test_worker_executes_runs_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp))
            config = BridgeConfig(
                host="127.0.0.1",
                port=9540,
                cwd=Path(tmp),
                data_dir=Path(tmp),
                model="composer-2.5",
                api_key="test-key",
                auth_token=None,
                cursor_agent_bin=None,
            )
            fleet = _fleet(tmp)
            runner = AgentRunner(config, store, fleet)
            order: list[str] = []

            def fake_execute(run_id: str) -> None:
                order.append(run_id)
                store.update_run(run_id, status="finished", finished_at=1.0)

            runner._execute_run = fake_execute  # type: ignore[method-assign]
            runner.start()
            first = store.create_run("one")
            second = store.create_run("two")
            runner.enqueue(first.run_id)
            runner.enqueue(second.run_id)
            runner.shutdown()
            self.assertEqual(order, [first.run_id, second.run_id])


if __name__ == "__main__":
    unittest.main()
