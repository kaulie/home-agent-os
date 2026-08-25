# Service: livingroom.climate

客厅海信空调插件（`hisense-ac`），group=`climate`。  
经 **海信爱家云端** 控制 KFR-46GW/X500U-X1（及同账号下的其它海信挂机）。不经过 LLM，不走局域网私有协议。

**Brain 不执行**；只通过心跳看到 `climate.set`，再把 plan 派到具备该能力的 Edge（本机 laptop Mac，或已配置爱家账号的 iPhone LivingRoomEdge）。

**与 `notify.speak` / `query.content` 独立**：禁止把本能力拆成 TTS 或问答。缺入参不得从前序 step 补。

## 规划自描述

心跳结构化字段（planner 契约；`description` 非权威）：

| 字段 | 值 |
|------|-----|
| role | 空调控制器 |
| planner_recognize | 开关空调、制冷/制热/送风、设定温度、风速、扫风 |
| typical_triggers | `打开空调`、`关掉空调`、`制冷 26 度`、`风速高`、`左右扫风` |
| do_not_dispatch | 放歌、TTS、开灯、知识问答、新风、除湿 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `hisense-ac` |
| service_id | `livingroom.climate` |
| group | `climate` |
| wire capability | `climate.set` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.hisense_ac`）；iPhone LivingRoomEdge（`Climate/HisenseClimate.swift`，设置页填爱家账号） |

## 契约

| 方向 | 内容 |
|------|-----|
| **输入** | `power`（可选：`on` / `off`，兼容 开、关、打开、关闭）；`mode`（可选：`cool` / `heat` / `fan`，兼容 制冷、制热、送风）；`target_temp`（可选，摄氏整数 16–32）；`fan`（可选：`auto` / `diffuse` / `low` / `medium` / `high`，兼容 自动、柔风、低、中、高）；`swing`（可选：`off` / `on` / `horizontal` / `vertical`，兼容 关、开、左右扫风、上下扫风）；`appliance`（可选：绑定显示名，如 客厅空调 / 儿童房空调；同一 Runtime 绑定多台时必填）。**power/mode/target_temp/fan/swing 至少填一项** |
| **输出** | `power`（必填 `on`/`off`）；`mode`（必填）；`status_text`（必填，人类可读）；`target_temp` / `indoor_temp` / `fan` / `swing`（有则带） |

本能力 **只看本步入参**。五项全缺 → 失败。  
`power=off` 且同时带 `mode` / `target_temp` / `fan` / `swing` → 失败。  
`mode=fan` 且带 `target_temp` → 失败。  
设温/改模式/风速/扫风且未写 `power`：本步内部先开机（不是从前序 step 捡状态）。  
**禁止** LLM。缺账号配置、登录失败、云端拒绝 → 失败，禁止假装成功。  
**不**广告新风、除湿、电辅热、面板灯。

云端协议对齐社区 MIT 项目 HisenseHA（`portal-account.hismarttv.com` / `api-wg.hismarttv.com`）。风速 `cmdId=1`，扫风 `cmdId=62`。非官方接口，海信改签会挂。禁止后台轮询。

## Wire

```json
{
  "capability": "climate.set",
  "step": 1,
  "assigned_edge_id": "<laptop-mac-edge-id>",
  "input_constrict": {
    "power": { "type": "string", "value": "on" },
    "mode": { "type": "string", "value": "cool" },
    "target_temp": { "type": "number", "value": 26 },
    "fan": { "type": "string", "value": "high" },
    "swing": { "type": "string", "value": "horizontal" }
  },
  "output_constrict": {
    "power": { "type": "string", "data_dest": "context" },
    "mode": { "type": "string", "data_dest": "context" },
    "status_text": { "type": "string", "data_dest": "context" }
  }
}
```

用户说打开空调 / 关掉空调 / 制冷 26 度 / 风速高 / 左右扫风 → 本能力。不要派 `notify.speak` 或 `query.content`。

## 入口

- Mac：`mac/src/mac_edge/plugins/hisense_ac.py` + `hisense_cloud.py`；`services.py` 广告 `livingroom.climate`（本机 laptop，且已配置爱家账号）
- iPhone：`ios/LivingRoomEdge/.../Climate/`；设置页填爱家账号后点「验证并绑定到本机」（登录解析空调 + 立即心跳广告 `climate.set`）
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["climate.set"]`（仅索引，不跑空调）
