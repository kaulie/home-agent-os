# Service: local.voice（capability: voicewakeup.echo）

唤醒回声：**本机 TTS 念「又咋了」**。挂在客厅 Mac Runtime 的 `local.voice` 上，和 `voice.stream` 同一 edge。

**与 `notify.speak` 独立**：普通播报 / 提醒 / 念答案仍用 `notify.speak`。本能力只做唤醒这一句，不要互相替代、不要互相 import。

**Brain 不执行唤醒应答**：`mac_voice` 本机直接调用 `echo()` 念「又咋了」，不经规划、不建 intent。本能力仍可被 Runtime 当普通步拉取执行，但唤醒路径不走计划。

## 规划自描述

心跳结构化字段（planner 契约；`description` 非权威）：

| 字段 | 值 |
|------|-----|
| role | 唤醒回声 |
| planner_recognize | 唤醒应答由语音入口本机完成，不要排进用户任务计划 |
| typical_triggers | `系统内部唤醒回声（非用户指令）` |
| do_not_dispatch | 作为计划逐步执行、普通播报、提醒、念答案、知识问答、控制设备、报时 |

LLM 规划不应派本步。唤醒应答由本机直接念，不经 Brain。用户转写里出现「又咋了」是喇叭回声，不是用户要求。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `voice-wakeup-echo` |
| service_id | `local.voice` |
| group | `voice` |
| wire capability | `voicewakeup.echo` |
| 执行方 | Mac Edge（`mac_edge.plugins.voicewakeup_echo`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `text`（可选；缺省且实际固定为 `又咋了`） |
| **输出** | `echo_text`（念出的文案，即「又咋了」） |

本能力 **只看本步入参**。不读前序 step。实现是 macOS `say -v Tingting`（本机 zh_CN 音色，不用系统默认英文声）。

## Wire

```json
{
  "capability": "voicewakeup.echo",
  "step": 1,
  "assigned_edge_id": "<issuing-voice.stream-edge-id>",
  "input_constrict": {"text": "又咋了"},
  "output_constrict": {
    "echo_text": { "type": "string", "data_dest": "context" }
  }
}
```

典型：唤醒成功 → 本机 TTS「又咋了」（不是 intent）。用户指令的语音播报仍是 `notify.speak`。

## 入口

- Mac：`mac/src/mac_edge/plugins/voicewakeup_echo.py` + `services.py` 广告 `local.voice`
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["voicewakeup.echo"]`
