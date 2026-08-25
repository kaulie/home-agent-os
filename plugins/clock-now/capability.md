# Service: local.clock

本机时钟插件（`clock-now`），group=`clock`。  
读 **墙上时钟 / 本机时区**，不经过 LLM。

**Brain 不执行、不持有密钥**；只通过心跳看到 `clock.now`，再把 plan 派到具备该能力的 Edge。

**与 `query.content` 独立**：禁止互相 import。问「现在几点了」应派本能力，不要派问答去编一个时刻。

## 规划自描述

心跳结构化字段（planner 契约；`description` 非权威）：

| 字段 | 值 |
|------|-----|
| role | 本机时钟读取器 |
| planner_recognize | 读取当前时间 |
| typical_triggers | `现在几点了`、`今天几号` |
| do_not_dispatch | 知识问答、计算、看图 |

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
| **输出** | `now_iso`（必填，ISO-8601 含偏移）；`time_text`（必填，给人听/看的中文时刻，如「现在是2026年8月23日上午9点25分」。不要写 IANA 名、斜杠、`HH:MM:SS` 或 `UTC+08:00`；时区只放 `now_iso`） |

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
