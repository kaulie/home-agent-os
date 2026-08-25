# Service: local.chat

闲聊问候插件（`chat-smalltalk`），group=`chat`。  
**无 LLM**。交付（text/audio/endpoint）不归本能力。

## 契约

| 方向 | 字段 | 说明 |
|------|------|------|
| 入参 | `text`（必填） | 用户的话 |
| 产出 | `reply`（必填） | 回复的话 |

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | 闲聊问候回复器 |
| planner_recognize | 仅匹配纯寒暄短语（早啊/你好/谢谢/再见/在吗），不含疑问句、不含你会/你可以/能不能 |
| typical_triggers | `早啊`、`你好啊`、`谢谢`、`再见`、`在吗` |
| do_not_dispatch | 知识问答、算式、报时、看图、拍照、投屏、控制设备、能力介绍、你会…吗、你可以…吗、能不能… |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `chat-smalltalk` |
| service_id | `local.chat` |
| group | `chat` |
| wire capability | `chat.smalltalk` |
| 执行方 | Mac Edge（`mac_edge.plugins.chat_smalltalk`） |

无法匹配寒暄时失败（勿用本能力顶替 `query.content`）。
