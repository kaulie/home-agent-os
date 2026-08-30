from __future__ import annotations

import logging
import signal
import sys

from agent_bridge.chat_inbox import ChatInboxWatcher
from agent_bridge.config import load_config
from agent_bridge.fleet_state import FleetStateStore
from agent_bridge.runner import AgentRunner
from agent_bridge.server import create_app
from agent_bridge.state import StateStore


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    config = load_config()
    config.data_dir.mkdir(parents=True, exist_ok=True)

    store = StateStore(config.data_dir)
    fleet = FleetStateStore(config.data_dir)
    runner = AgentRunner(config, store, fleet)
    runner.start()

    inbox = ChatInboxWatcher(config, store, fleet, runner)
    inbox.start()

    app = create_app(config, store, fleet, runner)

    def _shutdown(*_args: object) -> None:
        logging.getLogger(__name__).info("shutting down agent bridge")
        inbox.shutdown()
        runner.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if not config.can_run():
        logging.getLogger(__name__).warning(
            "No agent backend available; set CURSOR_API_KEY or install cursor-agent"
        )
    elif config.backend == "cli":
        logging.getLogger(__name__).info(
            "Using cursor-agent CLI backend (%s)", config.cursor_agent_bin
        )
    if not config.auth_token:
        logging.getLogger(__name__).warning(
            "AGENT_BRIDGE_TOKEN is not set; HTTP API is open on %s:%s",
            config.host,
            config.port,
        )

    logging.getLogger(__name__).info(
        "agent bridge listening on http://%s:%s (cwd=%s)",
        config.host,
        config.port,
        config.cwd,
    )
    app.run(host=config.host, port=config.port, threaded=True)


if __name__ == "__main__":
    main()
