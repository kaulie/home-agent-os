# TV Game MVP — 黑盒验收（接金币）

对照 [`tv_game.md`](/Users/gaolei/devspace/home-agent-docs/tv_game.md) 十条验收标准。

## 前置

1. Mac Edge 在线，`mac.game.host` 广告（`:8102` serve 已起）
2. Chromecast 与 Mac / iPhone 同 LAN
3. Cast Receiver `F7649303` 已部署含 game mode 的 [`receiver/index.html`](../../plugins/chromecast-display/receiver/index.html)
4. iPhone LivingRoomEdge：Runtime + Endpoint 角色开启

## 启动

```bash
python3 games/coin-catcher/serve.py
open http://127.0.0.1:8102/
```

Intent：`POST /api/v1/intent` `{ "text": "打开接金币游戏", "source": "voice" }`

期望 plan：`game.launch` + `game_id=coin_catcher`。

## 实时控制（不经 Brain）

iPhone **游戏** Tab，或：

```bash
MAC=http://192.168.x.x:8102
curl -s -X POST "$MAC/command" -H 'Content-Type: application/json' \
  -d '{"type":"START","source":"VOICE","timestamp":1730000000123}'
```

## 验收清单 G1–G10

| # | 场景 | 通过条件 |
|---|------|----------|
| G1 | 电视打开游戏 | iframe 加载 game_url |
| G2 | 说「开始游戏」 | START |
| G3–G4 | 挥臂左右 | MOVE_LEFT / MOVE_RIGHT |
| G5 | 说「向左」 | MOVE_LEFT |
| G6–G7 | 暂停/继续 | PAUSE / RESUME |
| G8 | 玩 2–5 分钟 | 稳定 |
| G9 | 低延迟 | Cast 或 HTTP+SSE |
| G10 | Brain 不中转帧命令 | plan 仅 game.launch |

Runner：[`run_game_mvp.sh`](run_game_mvp.sh)
