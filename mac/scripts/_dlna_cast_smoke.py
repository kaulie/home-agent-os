"""One-shot: SSDP-find Xiaomi TV and DLNA-play a LAN photo URL."""

from __future__ import annotations

import logging
import sys

from mac_edge.plugins.xiaomi_tv_display import _ssdp_search, discover_renderer, play_photo

PHOTO = "http://192.168.3.73:8080/1e41fc7d_20260824_194504_search_1.jpg"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("ssdp search...")
    locs = _ssdp_search(3.0)
    print("ssdp locations:", locs)
    try:
        renderer = discover_renderer(timeout_sec=6.0)
    except Exception as e:
        print("discover FAILED:", type(e).__name__, e)
        return 2
    print("renderer:", renderer)
    print("play", PHOTO)
    try:
        msg = play_photo(PHOTO, renderer=renderer, timeout_sec=10.0)
    except Exception as e:
        print("play FAILED:", type(e).__name__, e)
        return 3
    print("PLAY OK:", msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
