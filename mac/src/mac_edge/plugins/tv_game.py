"""Execute game.launch — ensure LAN game server is up."""

from __future__ import annotations

from typing import Any

from mac_edge.plugins.game_host import ensure_running, game_url


class GameLaunchError(Exception):
    pass


def launch_from_params(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    game_id = str(params.get("game_id") or "coin_catcher").strip() or "coin_catcher"
    try:
        url = ensure_running()
    except RuntimeError as e:
        raise GameLaunchError(str(e)) from e
    explicit = str(params.get("game_url") or "").strip()
    if explicit.startswith("http://") or explicit.startswith("https://"):
        url = explicit
    outputs = {
        "status": "ready",
        "game_id": game_id,
        "game_url": url,
    }
    return f"game.launch ok game_id={game_id} url={url}", outputs
