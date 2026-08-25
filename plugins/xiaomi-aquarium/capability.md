# Service: livingroom.aquarium

米家智能鱼缸插件（`xiaomi-aquarium`），group=`aquarium`。  
经 **小米云 / MIoT** 控制鱼缸开关、灯光、水泵、喂食。不经过 LLM。

**Brain 不执行**；只通过心跳看到 `aquarium.set`，再把 plan 派到具备该能力的 Edge（本机 laptop Mac）。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | 鱼缸控制器 |
| planner_recognize | 开关米家鱼缸、灯光、水泵，调节流量，远程喂食 |
| typical_triggers | `喂鱼`、`开鱼缸灯`、`关鱼缸`、`鱼缸水温` |
| do_not_dispatch | 开锁、开空调、知识问答、TTS、投屏 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `xiaomi-aquarium` |
| service_id | `livingroom.aquarium` |
| group | `aquarium` |
| wire capability | `aquarium.set` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.xiaomi_aquarium`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `power`（可选 on/off）；`light`（可选 on/off）；`pump`（可选 on/off）；`pump_flux`（可选 1–10）；`feed`（可选 true 或 1–10）。**至少填一项** |
| **输出** | `status_text`（必填）；`power` / `light` / `pump` / `pump_flux` / `water_temp` / `fed`（有则带） |

本能力 **只看本步入参**。五项全缺 → 失败。  
**禁止** LLM。缺账号、登录失败、云端拒绝 → 失败。  
**不**广告 TTS / 投屏。

账号：`MAC_EDGE_XIAOMI_USERNAME` / `MAC_EDGE_XIAOMI_PASSWORD`（本机 `mac/.env`）。多台鱼缸时设 `MAC_EDGE_XIAOMI_AQUARIUM_DID`。

## 入口

- Mac：`mac/src/mac_edge/plugins/xiaomi_aquarium.py` + `xiaomi_cloud.py`；`services.py` 广告 `livingroom.aquarium`（laptop 且已配置小米账号）
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["aquarium.set"]`
