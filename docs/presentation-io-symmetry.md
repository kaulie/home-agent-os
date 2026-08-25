# Home Agent Input–Output 对等原则

Status: Architecture Principle  
Version: 1.0  
Date: 2026-08-23  
Source: `presentation_io_symmetry.md`（home-agent-docs）

## 一句话

用户从哪里发起一次交互，系统**默认**就从哪里完成这次交互的 Output。这是 **Source Affinity（默认路由）**，不是硬性原路返回。

```text
Input Source → Brain / Planner → 默认 Output Target = Input Source
```

Intent、用户点名、交互上下文或系统策略可以覆盖默认目标。Capability **不**决定回复给谁。Task 在哪执行 ≠ 反馈从哪出去。

## 路由优先级

```text
OutputTarget =
  ExplicitIntentTarget
  ?? UserSpecifiedTarget
  ?? ContextTarget
  ?? InputSourceAffinity
  ?? SystemDefaultEndpoint
```

| 优先级 | 含义 | 例子 |
|---|---|---|
| ① Intent 明确指定 | 规划结果里的交付目标 | 「把这张照片显示到电视上」→ TV |
| ② 用户明确指定 | 话语里的设备/房间 | 「在客厅音响播」 |
| ③ Interaction Context | 本轮/会话已绑定的 affinity | 客厅语音模式 → 客厅喇叭 |
| ④ Input Source Affinity | **默认**：回到发出这次 Input 的设备 | iPhone 问几点 → iPhone |
| ⑤ 系统默认 Endpoint | Source 离线或无法呈现该 type | 仅 Runtime 的 Mac 发单 → 活着的 Kindle |

## Execution Target ≠ Response Target

拍照可以在 GoPro 上执行；「拍好了 / 照片」默认仍回到 iPhone。关灯在灯上执行，确认语仍回到发出端。

## 入站必须带 Source Context

Intent 不只是一句 `text`。Brain 在 `POST /api/v1/intent` 写入并贯穿生命周期：

```json
{
  "source_context": {
    "device_id": "iphone-001",
    "endpoint_id": "microphone",
    "capability_id": "voice.input"
  },
  "session_id": "…",
  "output_affinity": {
    "participant_id": "iphone-001",
    "reason": "input_source"
  }
}
```

客户端可显式传 `source_context`；缺省时由 `edge_id` / `participant_id` + `source`（text/voice/visual）推导。

## 谁做什么

| 层 | 职责 |
|---|---|
| Capability | 只声明「我能做什么」 |
| Endpoint | 声明「我能在哪里呈现」 |
| Planner | 决定 `presentation.type` / `from`；**仅当用户点名目的地时**写 `presentation.endpoint` |
| Brain | 按上表选 Response Target，组装 `intent_detail.presentation` |
| Runtime | 按步执行 Execution Target，不把执行边当成回复边 |

Planner **禁止**因为某步在 GoPro / 灯 / 音箱上跑，就把 Presentation 指到那台设备。

## 例外（允许覆盖默认）

1. 用户明确指定另一 Endpoint  
2. Intent 天然要求特定 Output（例如点名投电视）  
3. 当前 Interaction Context 已指定 Output  
4. Input Source 无法提供该 type 的呈现（无屏、无喇叭、离线）→ ⑤  
5. 系统策略（隐私、权限、`PRESENTATION_TTS_EDGE_ID`、Endpoint 不可用）

## 落地（本仓库）

- Brain：`assemble_presentation` / `_match_endpoint_participant` / `_append_issuer_speak_step`  
- Planner：`server/prompts/task_planner_system_prompt.md.en` §3.8  
- 发出端只 **Pull** `intent_detail.presentation` 渲染；Cast 电视是显式覆盖后的 Push
