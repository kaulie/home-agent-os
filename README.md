# Home Agent OS

面向家庭场景的 Agent 运行时：在 **异构设备与能力** 之上，把一次家务任务贯通 **感知 → 理解 → 规划 → 执行**。

远程仓库：[`kaulie/home-agent-os`](https://github.com/kaulie/home-agent-os)。

## 定位

家庭不是单一 App、单一协议的闭环，而是一堆互不相同的端：手机、电视 / Chromecast、相机、Mac、扬声器……各自 OS、网络与能力都不一样。Home Agent OS 要解决的是这类 **复杂异构场景** 里的端到端闭环：

1. **异构场景** — 多设备、多能力、多网络形态并存；Edge 按真实能力注册，Brain 按在线能力选人。
2. **四层贯通** — 不只「下发一条指令」，而是覆盖感知、理解、规划、执行。
3. **统一协议** — Edge 上报 `services[] → capabilities[]`；Brain 下发带 `assigned_edge_id` 的 `execution_plan`。

| 层面 | 在家里意味着什么 | 本仓库落点 |
|------|------------------|------------|
| **感知** Sense | 拍照、语音、设备状态、环境信号 | GoPro / 语音入口 / Edge 心跳与能力登记 |
| **理解** Understand | 把自然语言 / 事件变成可执行意图 | Brain `POST /api/v1/intent` |
| **规划** Plan | 拆成 capability 步骤、选 Edge、定时机 | `execution_plan` + 能力路由 + `execution_timing` |
| **执行** Act | 在具体设备上调用 Skill / Plugin | Chromecast / iPhone / Android / Mac Edge |

## 架构

```text
                    ┌──────────────────────────────────────┐
                    │              家庭异构场景              │
                    │  相机 · 手机 · TV/Cast · Mac · 音箱…  │
                    └──────────────────┬───────────────────┘
                                       │
          感知 ────────────────────────┼──────────────────────── 执行
          (Sense)                      │                      (Act)
                                       ▼
                         ┌─────────────────────────┐
                         │   Brain · 理解 + 规划    │
                         │  intent → plan → 路由    │
                         └────────────┬────────────┘
                                      │ execution_plan
                                      │ assigned_edge_id
              ┌───────────────┬───────┴───────┬───────────────┐
              ▼               ▼               ▼               ▼
         Chromecast         iPhone        Android 手机          Mac
          music.*         意图入口          wifi.*        camera.capture
                                                       display.photo
                                                       notify.speak
```

**Brain** 负责理解与规划（意图、plan、按能力选一个 Edge、时间同步）。  
**Edge** 负责感知接入与本地执行（注册能力、拉 intents、Scheduler → Runtime → Skill）。  
**Plugin** 是跨端复用的能力实现（相机、投屏、音乐等）。

## 仓库结构

| 路径 | 说明 |
|------|------|
| [`server/`](server/) | Brain：意图、能力路由、心跳、`execution_timing` |
| [`mac/`](mac/README.md) | Mac Edge（Cast 转发、TTS、内网 ping） |
| [`home-agent-cli`](https://github.com/kaulie/home-agent-cli) | iOS / Android **客户端 App**（**已迁出本仓**：App 不作为服务部署） |
| [`agent-bridge/`](agent-bridge/) | Cursor Agent 本地 bridge（手机 `source=dev` 开发任务） |
| [`plugins/`](plugins/) | 跨端 Skill：`gopro-camera`、`chromecast-display`、`netease-music`、`runtime-agent-sdk` |

## 能力一览（当前主路径）

| Edge | 典型 service | capability |
|------|--------------|------------|
| Chromecast (`app-v2`) | `netease.music` | `music.play` 等 |
| iPhone | （非 Edge） | 只 `POST /api/v1/intent`，每 5s 拉 `intent_detail` |
| Mac home-server | `gopro.camera` | `camera.capture`（无感切 Wi‑Fi） |
| Mac | `chromecast.display` | `display.photo`（转发本机 Cast HTTP） |
| Mac | `local.notify` | `notify.speak` |
| Android 手机 | `network.wifi` | `network.wifi.join` / `leave`（调试） |

示例闭环：`camera.capture`（感知）→ Brain 规划 → `display.photo` / `notify.speak`（执行）。

## Demo 演示

## 快速开始

```bash
# Brain
cd server && python3 home_brain.py

# Mac Edge（其它端见各自 README）
cd mac && PYTHONPATH=src python -m mac_edge
```

```text
POST /api/v1/intent
GET  /api/v1/devices/living-room/intents?edge_id=<本节点>
```

## 文档索引

| 文档 | 内容 |
|------|------|
| [`docs/service-topology.md`](docs/service-topology.md) | 本机/云服务端口、开机拉起、巡检 |
| [`server/README.md`](server/README.md) | 协议、路由 |
| [`mac/README.md`](mac/README.md) | Mac Edge |
| [`home-agent-cli`](https://github.com/kaulie/home-agent-cli) | iOS / Android 客户端 App（已迁出；各工程 README 在该仓 `ios/*/README.md`） |
| [`plugins/*/capability.md`](plugins/) | 插件 wire schema |
