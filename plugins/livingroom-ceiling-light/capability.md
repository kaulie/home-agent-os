# Service: livingroom.ceiling_light

客厅大路灯插件（`livingroom-ceiling-light`），group=`light`。  
用 **home-server / iPhone 扬声器** 对智能音箱喊唤醒词，再发开/关指令。优先播放预录音频，缺文件时用本机 TTS。不经过 LLM，不录音。

**Brain 不执行**；只通过心跳看到 `light.set`，再把 plan 派到具备该能力的 Edge（home-server **或** 客厅 iPhone）。

**与 `notify.speak` 独立**：禁止把本能力拆成两个 TTS 计划步。唤醒词、等待、开灯/关灯文案都是本步内部协议。

## 规划自描述

心跳 `description`：能开关客厅大路灯（必填 `state`）；不能拆成 `notify.speak`、不能调亮度、不能控制窗帘或其他灯。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `livingroom-ceiling-light` |
| service_id | `livingroom.ceiling_light` |
| group | `light` |
| wire capability | `light.set` |
| 执行方 | Mac Edge home-server（`mac_edge.plugins.livingroom_light`）；客厅 iPhone（`LivingRoomLight.swift`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `state`（必填：`on` / `off`；兼容 开、关、开灯、关灯） |
| **输出** | `state`（必填，规范化后的 `on` 或 `off`） |

本能力 **只看本步入参**。缺 `state` 或无法识别 → 失败，禁止猜测开或关。  
**禁止** LLM。  
**不**广告 `notify.speak`；内部优先预录音频（见 `plugins/livingroom-ceiling-light/audio/`），缺 clip 时 TTS。

内部协议（开环，不听「在呢」）：

1. 播放 `wake` 录音（或 TTS「小书小书」）
2. sleep **2** 秒
3. 播放 `on` / `off` 录音（或 TTS「开灯」/「关灯」）

预录音频文件名：`wake.*`、`on.*`、`off.*`（`.m4a` / `.wav` / `.mp3` 等）。Mac 目录见 `audio/README.md`；iPhone 见 `Light/Audio/` 或 `Documents/LightAudio/`。

无法验证灯是否真亮：执行节点必须在客厅、扬声器开着、音量够「小书」听见。

## Wire

```json
{
  "capability": "light.set",
  "step": 1,
  "assigned_edge_id": "<home-server-or-iphone-edge-id>",
  "input_constrict": {
    "state": { "type": "string", "value": "on" }
  },
  "output_constrict": {
    "state": { "type": "string", "data_dest": "context" }
  }
}
```

用户说开灯 / 关灯 / 打开客厅灯 → 本能力。不要派 `notify.speak`。

## 入口

- Mac：`mac/src/mac_edge/plugins/livingroom_light.py` + `services.py` 广告 `livingroom.ceiling_light`（仅 home-server）
- iPhone：`ios/LivingRoomEdge/LivingRoomEdge/Light/LivingRoomLight.swift`；runtime 心跳广告同一 `livingroom.ceiling_light` / `light.set`
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["light.set"]`（仅索引，不跑灯）
