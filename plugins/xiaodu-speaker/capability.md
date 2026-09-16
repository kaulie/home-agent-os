# Service: xiaodu.speaker

小度音箱 TTS 播报插件（`xiaodu-speaker`），group=`notify`。

**流程**：**SSDP 探测小度（地址不写死）** → edge-tts 合成 MP3 → Mac LAN HTTP 供小度拉流 → UPnP AVTransport（best-effort Stop → SetAVTransportURI → Play）。空闲时 Stop 可能超时，插件短时尝试后继续 SetURI/Play，不因 Stop 失败整步报错。

**Brain 不执行、不持有设备密钥**；只通过心跳看到 `xiaodu.speak`，再把 plan 派到「现场探测到小度」的 Mac Edge（`MAC_EDGE_XIAODU_IP` 只是可选覆盖，见环境变量）。

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

## 地址探测（不写死）

1. **显式覆盖**：调用方 `du_ip` 或 `MAC_EDGE_XIAODU_IP`（视为「用户说了算」，不再探测）；
2. **缓存**：`mac/data/xiaodu_renderer.json`，命中前先拉一次描述 + `GetTransportInfo` 探活，探不通即丢；
3. **SSDP 探测**：`M-SEARCH ST=urn:schemas-upnp-org:device:MediaRenderer:1` → 拉设备描述 →
   按 `manufacturer=DuerOS`／名字含「小度」认身份（`MAC_EDGE_XIAODU_NAME` 可指定）→
   `GetTransportInfo` 探活 → 落缓存。

控制地址用描述里的 `controlURL` + `URLBase`（不再写死 `:49494/upnp/control/rendertransport1`，
只在「只给了 IP」的老式覆盖下才按老路径拼）。播放失败会**丢缓存重新探测后重试一次**（自愈）。

供流地址（小度拉 MP3 用）按目标设备探测本机出口 IP；写死的 `MAC_EDGE_XIAODU_PUBLIC_HOST`
如果已经过期（不再是本机网卡地址）会被忽略并写 warn。

## 环境变量

| 变量 | 说明 |
|------|------|
| `MAC_EDGE_XIAODU_IP` | **可选覆盖**（调试/探测不到时用）。默认不设：地址由 SSDP 探测得出 |
| `MAC_EDGE_XIAODU_NAME` | 可选：家里多台小度时按名字子串指定（如 `卧室` / `8432`） |
| `MAC_EDGE_XIAODU_DISCOVER` | 默认开；`0` = 关掉 SSDP 探测（只认覆盖/缓存） |
| `MAC_EDGE_XIAODU` | `0/off` = 彻底关闭本能力（不广告） |
| `MAC_EDGE_XIAODU_HTTP_PORT` | MP3 供流端口，默认 `8000` |
| `MAC_EDGE_XIAODU_PUBLIC_HOST` | 小度能访问的 Mac LAN IP；**只有它确实是本机网卡地址时才采信**，否则按目标设备探测出口地址 |
| `MAC_EDGE_XIAODU_VOICE` | 默认 edge-tts 音色 |
| `MAC_EDGE_XIAODU_CACHE` | 可选：探测结果缓存路径（默认 `mac/data/xiaodu_renderer.json`） |

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
