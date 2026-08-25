# Service: local.query

问答插件（`query-content`），group=`query`。  
这是 **Edge runtime 自身的 capability**：Mac Edge 用独立 LLM/生图栈回答一句话，把平铺结果作为 step outputs / `ctx_param` 上报 Brain。  
**Brain 不执行问答、不持有模型密钥**；只通过心跳看到 `services[]` 里广告了 `query.content`，再把 plan 派到具备该能力的 Edge。

**与 `vision-perceive` 完全独立**：禁止互相 import；不共享 provider、prompt、schema、config helper。同一台机器可以各自读 `ARK_API_KEY`，代码路径零共享。

**与 `search.images`（文搜图）独立**：本能力可 **AI 文生图**（画一张 / 生成一张 / 来张图）。搜网上实拍图不要派本能力，不要 import `search_images`。

## 规划自描述

心跳 `description`：能按本步 `query` 文字问答产出 `answer_text`；自带文生图（要图、投屏/电视展示、或示意/步骤/笔顺时产出 `asset_ref`；简单事实默认不生图）。不能报时、看已有图、拍照、自己投电视、TTS、开灯、放歌。缺能力不要用本能力顶替。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `query-content` |
| service_id | `local.query` |
| group | `query` |
| wire capability | `query.content` |
| 执行方 | Mac Edge（`mac_edge.plugins.query_content`） |

## 诚实作答（硬规则）

对 **所有** query 生效：

- 不确定、没有依据、超出所知 → `answer_text` **直说「我不知道」**（可补一句缺什么信息）。
- **禁止**猜测、补全、用「一般来说 / 可能是 / 据我所知大概」装作知道。
- `refused=true` 时能力仍成功（下游可播报拒答文案），**禁止生图**。

### 专业域额外约束

科普、百科、**汉字笔顺/笔画**、健康、医药、用药、诊断、营养、法律等 **不得用模型记忆编造**。v1 不接外部检索库：有具体可点名的来源才答，否则按「我不知道」处理。

- 专业域作答：`citations` 非空，正文点名来源；不得补充来源未覆盖的「常识」。
- 专业域无可靠来源：`refused=true`，直说不知道（可提示去查专业库或问执业人员）。
- **禁止**虚构论文、指南、剂量、诊断、假 URL。
- **汉字笔顺 / 笔画怎么写 / 几画**：`domain=professional`；`citations` 必须是汉语字典（汉典 / 新华字典 / 教育部笔顺规范等）。没有字典依据则拒答、不生图。
- **是否出图**：
  1. 简单知识类默认不出图。
  2. 静态/动态图更能协助解释（外观、结构、步骤、笔顺等）则出图。
  3. 用户明确要求出图则尽量出图。
  4. 用户要把结果投屏 / 投到电视 / 来张图片：出图。
  5. 入参 `want_image=true`：必须出图（planner 在出图/投屏计划里可显式传）。
  模型 `want_image=true` 时出图；问句含「出图/画一张/来张/图片/长什么样子/笔顺/投屏/投到电视/电视上」等时，即使模型漏标或拒答知识也会出图。汉字笔顺无字典依据仍不生图。未给 `image_prompt` 时用原问题作画面描述。
- 闲聊 / 家居 / 故事走 `general`，不强制 citations，仍适用「不知道就说不知道」。
- 配图只做示意，不是诊疗依据。用户只要图时，不要因为不确定百科而拒答不配图。

v1 **不核验**引用 URL 是否真实存在。专业域 `refused=false` 却无 `citations` → 能力失败（模型违约，改提示词，不补假引用）。

## 契约（明确）

| 方向 | 内容 |
|------|------|
| **输入** | `query`（必填）：用户原话。可选 `want_image`（true 必出图）、`upload_dest`（默认 lan） |
| **输出** | `answer_text`（必填）；`asset_ref`（可选，仅生图成功，AssetRef）；`citations`（JSON 数组字符串） |

本能力 **只看本步入参**。缺 `query` 则失败，禁止从前序 step 补。  
Plugin 内部上传仍把 blob 交给 Runtime；对外契约禁止 `photo_url`。  
**不**自己 TTS / Cast。成功后 Brain 组装 `presentation`；纯提醒仍 `notify.speak`；投电视仍 `display.photo`：

```text
query.content  →  Brain finalize → presentation
               →  display.photo(asset_ref=$asset_ref)   # 仅用户要看电视时由 Brain 排步
delay          →  notify.speak(text=该喝水了)            # 纯提醒，不用 present
```

## Wire

```json
{
  "capability": "query.content",
  "step": 1,
  "assigned_edge_id": "<mac-edge-id>",
  "input_constrict": { "query": "今天天气适合散步吗" },
  "output_constrict": {
    "answer_text": { "type": "string", "data_dest": "context" },
    "asset_ref": { "type": "string", "data_dest": "context" },
    "citations": { "type": "string", "data_dest": "context" }
  }
}
```

模型原始返回必须是一层 JSON（禁止兜底拆包）：

```json
{
  "answer_text": "……",
  "want_image": false,
  "image_prompt": "",
  "domain": "general",
  "refused": false,
  "citations": [{"name": "来源名", "url": "https://…"}]
}
```

`domain`：`general` | `science` | `health` | `medicine` | `professional`。后四类为专业域。

## Edge 本地模型配置（与 vision 环境变量独立）

```bash
MAC_EDGE_QUERY_PROVIDER=ark
MAC_EDGE_QUERY_API_BASE=https://ark.cn-beijing.volces.com/api/v3
MAC_EDGE_QUERY_API_KEY=...          # 或 ARK_API_KEY
MAC_EDGE_QUERY_MODEL=ep-xxxxxxxx    # 文本模型 / 接入点
MAC_EDGE_QUERY_IMAGE_MODEL=ep-20260814163146-9nwqb
```

未配置 Key 时 **直接失败**（不占位假答案）。生图上传默认 LAN img-server（`MAC_EDGE_LAN_PHOTO_UPLOAD_URL`），与相机同一套地址，但不 import GoPro / vision。

## 入口

- Mac：`mac/src/mac_edge/plugins/query_content.py` + `query_providers/` + `services.py` 广告 `local.query`
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["query.content"]`（仅索引/校验，不跑模型）
