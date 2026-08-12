from __future__ import annotations

import logging
import sys

from mac_edge.agent import EdgeAgent
from mac_edge.config import load_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # Quieter httpx unless debugging.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    config = load_config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    EdgeAgent(config).run()


if __name__ == "__main__":
    main()
