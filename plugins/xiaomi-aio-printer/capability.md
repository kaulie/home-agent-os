# Service: local.printer

米家喷墨一体机插件（`xiaomi-aio-printer`），group=`printer`。  
经 **本机 CUPS**（`lp` / `lpstat`）把已有 PDF/`document` Asset 打到家宽 Wi‑Fi 上已配置的打印机队列。

**不切网、不连打印机 SoftAP、不走米家云。** SoftAP 仅用于打印机首次配网，本能力不涉及。

**Brain 不执行**；只通过心跳看到 `printer.print`，再把 plan 派到具备该能力的 Edge（Mac Edge laptop）。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | 文档打印机 |
| planner_recognize | 把本步已有的 PDF/document Asset 经本机 CUPS 队列打出纸 |
| typical_triggers | `打印这份 PDF`、`把文档打出来`、`打印一下` |
| do_not_dispatch | 配网、切 SoftAP、扫描、投屏、TTS、知识问答 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `xiaomi-aio-printer` |
| service_id | `local.printer` |
| group | `printer` |
| wire capability | `printer.print` |
| kind | `output` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.xiaomi_aio_printer`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `asset_ref`（必填，AssetRef，`type=document`）；`copies`（可选正整数）；`printer_name`（可选 CUPS 队列名） |
| **输出** | `status_text`（必填）；`job_id`；`printer_name` |

本能力 **只看本步入参**。缺 `asset_ref`、非 `document`、本机无 `lp`、或 CUPS 队列不可用 → **明确中文失败**（文案不提示连接 SoftAP）。

队列解析优先级：入参 `printer_name` → 环境变量 `MAC_EDGE_PRINTER_NAME` → `lpstat` 中名称含 `Mi_All_in_One_Inkjet` 的队列。

## 网络前提

- Mac 与打印机同在家宽 Wi‑Fi
- CUPS 已配置可用队列（例：`Mi_All_in_One_Inkjet_Printer__1EB808_`）

## 入口

- Mac：`mac/src/mac_edge/plugins/xiaomi_aio_printer.py`；`services.py` 广告 `local.printer`（laptop 且本机有 `lp`）
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["printer.print"]`
