# Service: local.clock

本机时钟插件（`clock-now`），group=`clock`。  
读 **墙上时钟 / 本机时区**，不经过 LLM。

**Brain 不执行、不持有密钥**；只通过心跳看到 `clock.now`，再把 plan 派到具备该能力的 Edge。

**与 `query.content` 独立**：禁止互相 import。问「现在几点了」应派本能力，不要派问答去编一个时刻。

## 规划自描述

心跳 `description`（planner 只看这段）：能读墙上时钟产出 `now_iso`/`time_text`；不能 LLM 编时刻、不能用 `query.content`/`notify.speak` 顶替、不 TTS。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `clock-now` |
| service_id | `local.clock` |
| group | `clock` |
| wire capability | `clock.now` |
| 执行方 | Mac Edge（`mac_edge.plugins.clock_now`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `timezone`（可选，IANA 如 `Asia/Shanghai`；缺省=本机本地时区） |
| **输出** | `now_iso`（必填，ISO-8601 含偏移）；`time_text`（必填，人类可读，含时区） |

本能力 **只看本步入参**。未知 `timezone` → 失败。  
**禁止** LLM、禁止猜测。  
**不**自己 TTS。成功后 Brain 组装 `intent_detail.presentation`；纯提醒仍用 `notify.speak`。

## Wire

```json
{
  "capability": "clock.now",
  "step": 1,
  "assigned_edge_id": "<mac-edge-id>",
  "input_constrict": {},
  "output_constrict": {
    "now_iso": { "type": "string", "data_dest": "context" },
    "time_text": { "type": "string", "data_dest": "context" }
  }
}
```

典型：`clock.now`（Brain finalize → `presentation`）。纯提醒仍 `notify.speak`。

## 入口

- Mac：`mac/src/mac_edge/plugins/clock_now.py` + `services.py` 广告 `local.clock`
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["clock.now"]`（仅索引，不跑时钟）
