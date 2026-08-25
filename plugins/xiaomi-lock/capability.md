# Service: entry.lock

小米门锁只读插件（`xiaomi-lock`），group=`lock`。  
经 **小米云 / MIoT** 读取门锁是否上锁、门是否开着。不经过 LLM。**禁止远程开锁。**

**Brain 不执行**；只通过心跳看到 `lock.status`，再把 plan 派到具备该能力的 Edge（本机 laptop Mac）。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | 门锁状态读取器 |
| planner_recognize | 读取门锁是否上锁、门是否开着；不能远程开锁 |
| typical_triggers | `门锁开了吗`、`门有没有锁上`、`门锁状态` |
| do_not_dispatch | 远程开锁、开门、开灯、知识问答 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `xiaomi-lock` |
| service_id | `entry.lock` |
| group | `lock` |
| wire capability | `lock.status` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.xiaomi_lock`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | 无必填。若传入 unlock/开锁 → **失败** |
| **输出** | `status_text`（必填）；`online`（必填）；`locked` / `door`（有则带） |

本能力 **只看本步入参**。  
门锁离线（无蓝牙网关 / 无 Wi-Fi）→ `online=false`，`status_text` 说明原因。  
**禁止** LLM、禁止开锁动作。

账号与鱼缸共用 `MAC_EDGE_XIAOMI_USERNAME` / `PASSWORD`。多把锁时设 `MAC_EDGE_XIAOMI_LOCK_DID`。

## 入口

- Mac：`mac/src/mac_edge/plugins/xiaomi_lock.py` + `xiaomi_cloud.py`
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["lock.status"]`
