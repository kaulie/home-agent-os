# Service: xiaodu.speaker

小度音箱 TTS 播报插件（`xiaodu-speaker`），group=`notify`。

**流程**：edge-tts 合成 MP3 → Mac LAN HTTP 供小度拉流 → UPnP AVTransport（Stop → SetAVTransportURI → Play）。

**Brain 不执行、不持有设备密钥**；只通过心跳看到 `xiaodu.speak`，再把 plan 派到配置了 `MAC_EDGE_XIAODU_IP` 的 Mac Edge。

**与 `notify.speak` 独立**：Mac 本机 TTS 用 `local.notify`；用户明确要小度音箱时用本能力。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | 小度音箱播报器 |
| planner_recognize | 把指定文案经客厅小度音箱播报 |
| typical_triggers | `用小度说`、`小度播报`、`客厅音箱说` |
| do_not_dispatch | Mac 本机播报、知识问答、放歌、投屏 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `xiaodu-speaker` |
| service_id | `xiaodu.speaker` |
| group | `notify` |
| wire capability | `xiaodu.speak` |
| 执行方 | Mac Edge（`mac_edge.plugins.xiaodu_speaker`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `text`（必填，要播报的原文）；`voice`（可选，edge-tts 音色，默认 `zh-CN-XiaoxiaoNeural`） |
| **输出** | 无（`output_schema={}`）；成功步须有可读 `msg` |

本能力 **只看本步入参**。缺 `text` → 失败。  
**不**读前序 step、不拼 `$answer_text`。  
**不**走 DuerOS Push API；走 UPnP DLNA。

## 环境变量

| 变量 | 说明 |
|------|------|
| `MAC_EDGE_XIAODU_IP` | 小度音箱 LAN IP；**未设则不向 Brain 广告本能力** |
| `MAC_EDGE_XIAODU_HTTP_PORT` | MP3 供流端口，默认 `8000` |
| `MAC_EDGE_XIAODU_PUBLIC_HOST` | 小度能访问的 Mac LAN IP（默认同本机 `lan_ip()`） |
| `MAC_EDGE_XIAODU_VOICE` | 默认 edge-tts 音色 |

## 示例 plan

用户：「用小度说欢迎暄暄妈妈回家」

```json
{
  "execution_plan": [
    {
      "step": 1,
      "capability": "xiaodu.speak",
      "input_constrict": {
        "text": "欢迎暄暄妈妈回家"
      }
    }
  ]
}
```
