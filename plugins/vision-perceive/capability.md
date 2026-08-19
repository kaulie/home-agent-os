# Service: local.vision

视觉感知插件（`vision-perceive`），group=`vision`。  
这是 **Edge runtime 自身的 capability**：Mac Edge 本地拉图并调用视觉模型，再把结构化结果作为 step outputs / `ctx_param` 上报 Brain。  
**Brain 不执行视觉、不持有模型密钥**；只通过心跳看到 `services[]` 里广告了 `vision.perceive`，再把 plan 派到具备该能力的 Edge。

## 规划自描述

心跳 `description`：能对必填 `image_ref` 产出场景结构（summary/people 等）；不能无图、不能收 `photo_url`、不能做「这个字读啥」（用 `vision.ask`）、不拍照不投屏。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `vision-perceive` |
| service_id | `local.vision` |
| group | `vision` |
| wire capability | `vision.perceive` |
| 执行方 | Mac Edge（`mac_edge.plugins.vision_perceive`） |

## 契约（明确）

| 方向 | 内容 |
|------|------|
| **输入** | `image_ref`（必填 AssetRef）：待分析照片 |
| **输出** | 平铺字段：`summary`（必填）、`people` / `spatial` / `actions` / `posture` / `lighting` |

字段语义：

| 字段 | 类型（wire） | 说明 |
|------|--------------|------|
| `summary` | string | 一句话画面摘要 |
| `people` | string（JSON 数组） | `[{id, description, count, position}, …]` |
| `spatial` | string | 空间布局与位置关系 |
| `actions` | string | 主要动作 |
| `posture` | string | 体态/姿势 |
| `lighting` | string（JSON 对象） | `{whole, region:[{person_id, lighting, summary}]}` |

要求：`people[].id` 唯一；`lighting.region[].person_id` 引用 `people[].id`。

| 层 | 内容 |
|----|------|
| step `outputs` | 上述平铺字段 |
| `output_constrict` | 声明要写入 context 的键（通常全量；播报至少 `summary`） |
| `ctx_param` | 只含 constrict 声明的键（+ 上游如 `capture_ref`） |

下游直接用 `$summary`（播报推荐）；复杂字段可用 `$lighting.whole` / `$people`。旧写法 `$perception_json.summary` 仍会落到 `$summary`。Brain 只按 `output_constrict` 登记 context，不做视觉专用改写。

## Wire

```json
{
  "capability": "vision.perceive",
  "step": 2,
  "assigned_edge_id": "<mac-edge-id>",
  "input_constrict": { "image_ref": "$capture_ref" },
  "output_constrict": {
    "summary": { "type": "string", "data_dest": "context" },
    "people": { "type": "string", "data_dest": "context" },
    "spatial": { "type": "string", "data_dest": "context" },
    "actions": { "type": "string", "data_dest": "context" },
    "posture": { "type": "string", "data_dest": "context" },
    "lighting": { "type": "string", "data_dest": "context" }
  }
}
```

典型流水线：`camera.capture`（Mac home-server 无感切网）→ `vision.perceive`（Mac）→ `endpoint.present`（`input_constrict: {}`，用 `$summary`）。整单须同一 `assigned_edge_id`。

看图回答「这个字读啥」等指向问题用独立能力 `vision.ask`（`image_ref` + `query` → `answer_text`），不要把 OCR/问答塞进本能力。

## Edge 本地模型配置（可插拔 provider，与 Brain 无关）

默认 provider=`ark` 使用官方 SDK（需先安装）：

```bash
pip install --upgrade "volcengine-python-sdk[ark]"
# 或在 mac/ 下: pip install -r requirements.txt
```

通过 `MAC_EDGE_VISION_PROVIDER` 切换后端（默认 `ark`）：

| provider | 协议 | 说明 |
|----------|------|------|
| `ark` / `volc` / `doubao` | 方舟 SDK `Ark.responses.create` | `input_image` + `input_text`（当前默认） |
| `openai` / `openai_chat` | OpenAI `POST …/chat/completions` | httpx，无需方舟 SDK |

扩展：实现 `VisionProvider.analyze(...)`，再 `register_provider("name", Factory)`。

```bash
# 默认：火山方舟 SDK
MAC_EDGE_VISION_PROVIDER=ark
MAC_EDGE_VISION_API_BASE=https://ark.cn-beijing.volces.com/api/v3
MAC_EDGE_VISION_API_KEY=...          # 或 ARK_API_KEY
MAC_EDGE_VISION_MODEL=ep-xxxxxxxx    # 方舟推理接入点 ID，或模型名

# 将来切到其它模型示例
# MAC_EDGE_VISION_PROVIDER=openai
# MAC_EDGE_VISION_API_BASE=https://api.openai.com/v1
# MAC_EDGE_VISION_MODEL=gpt-4o-mini
```

Runtime 把 `image_ref` resolve 成本步临时 HTTP URL 后再调模型（图须模型可达）。未配置 Key 时返回结构化占位。

## 入口

- Mac：`mac/src/mac_edge/plugins/vision_perceive.py` + `services.py` 广告 `local.vision`
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["vision.perceive"]`（仅索引/校验，不跑模型）
