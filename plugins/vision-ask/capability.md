# Service: local.vision（capability: vision.ask）

看图问答插件（`vision-ask`），group=`vision`，与 `vision.perceive` 同属 `local.vision`。  
Mac Edge 拉图并调用视觉模型，针对用户这一句问句作答。  
**Brain 不执行视觉、不持有模型密钥**；只通过心跳看到 `vision.ask`，再把 plan 派到具备该能力的 Edge。

**与 `vision.perceive` 独立**：禁止 import `vision_perceive`；不共享 prompt / JSON schema。可走同一套 `vision_providers` 与 `MAC_EDGE_VISION_*`（同一视觉模型）。  
**与 `query.content` 独立**：本能力必须有图；`query.content` 不看图。

## 规划自描述

心跳 `description`：能对必填 `image_ref`+`query` 只根据图中可见内容作答；不能无图问答、不能收 `photo_url`、不能产出场景结构字段、不生图。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `vision-ask` |
| service_id | `local.vision` |
| group | `vision` |
| wire capability | `vision.ask` |
| 执行方 | Mac Edge（`mac_edge.plugins.vision_ask`） |

## 契约（明确）

| 方向 | 内容 |
|------|------|
| **输入** | `image_ref`（必填 AssetRef）、`query`（必填，用户原话） |
| **输出** | `answer_text`（必填） |

本能力 **只看本步入参**。缺 `image_ref` 或 `query` 则失败，禁止从前序 step 补。  
**不**自己 TTS / Cast。给用户看/听结果的默认下游是 `endpoint.present`（`input_constrict` 为 `{}`，用 `$answer_text`）；纯提醒仍用 `notify.speak`。

## 作答规则

- 只根据这张图里**实际看见**的内容回答 `query`。图里没有的不要写。
- 「这个 / 那个 / 手指指的 / 这个字」必须落到画面里被指向或被问到的那一个对象（字、物、人），不要整页 OCR 当答案。
- 「读啥 / 怎么读」：给出该字（或词）和读音。
- 看不清、无法判定指向、超出图中可见 → `answer_text` 直说「我不知道」。
- **禁止**用客厅场景字段（people / lighting 等）冒充答案；那是 `vision.perceive`。
- **禁止**生图。模型原始返回必须是一层 JSON；不对就失败，不拆包修补。

## Wire

```json
{
  "capability": "vision.ask",
  "step": 2,
  "assigned_edge_id": "<mac-edge-id>",
  "input_constrict": {
    "image_ref": "$capture_ref",
    "query": "这个字读啥"
  },
  "output_constrict": {
    "answer_text": { "type": "string", "data_dest": "context" }
  }
}
```

典型流水线：`camera.capture` → `vision.ask`（`image_ref=$capture_ref`，`query` 为用户问句）→ Brain `presentation`。

模型原始返回：

```json
{
  "answer_text": "这个字是「喵」，读 miāo。",
  "refused": false
}
```

## 入口

- Mac：`mac/src/mac_edge/plugins/vision_ask.py` + `services.py` 广告 `local.vision` / `vision.ask`
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["vision.ask"]`（仅索引/校验，不跑模型）
