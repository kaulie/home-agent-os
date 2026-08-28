# Service: chromecast.game

TV 互动游戏 Cast 启动（`tv-game`），group=`game`。

Wire capability：`game.launch`（output）。实时 GameCommand 走 iPhone 本地 `game.input`，不经 Brain。

协议：[`docs/chromecast-cast-protocol.md`](../../docs/chromecast-cast-protocol.md) — `launch_game` / `game.command`。

游戏页由 Mac `mac.game.host` 托管：[`games/coin-catcher/serve.py`](../../games/coin-catcher/serve.py)（`:8102`）。
