# Service: local.pdf.rotate

PDF 旋转插件（`pdf-rotate`），group=`convert`。基于 **pypdf** 把已有 `type=document`
（PDF）Asset **整份**在横版/竖版之间切换，产物登记为新的 document Asset，可交给
`printer.print` 打印或其它流程继续消费。

**Brain 不执行**；只通过心跳看到 `pdf.rotate`，再把 plan 派到具备该能力的
Edge（Mac Edge laptop，`mac_edge.plugins.pdf_rotate`）。依赖 pypdf 已安装才会广告。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | PDF 旋转器（横版/竖版） |
| planner_recognize | 把本步已有的 PDF/document Asset 整份转成横版或竖版（先判断当前是横版还是竖版，需要旋转的页转 90°）。入参 asset_ref（必填，type=document）、orientation（必填，portrait=竖版 / landscape=横版，可写中文）。产出新的 document Asset 或无需旋转时复用原 asset_ref。转完通常交给 printer.print 打印 |
| typical_triggers | `把这个 PDF 转成横版`、`把这个 PDF 转成竖版`、`横着打这份 PDF`、`竖着打这份 PDF`、`把 PDF 旋转成横版`、`PDF 横竖切换` |
| do_not_dispatch | 打印、OCR、看图理解、扫描、识别内容、PDF 合成/转图片、配网 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `pdf-rotate` |
| service_id | `local.pdf.rotate` |
| group | `convert` |
| wire capability | `pdf.rotate` |
| kind | `action` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.pdf_rotate`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `asset_ref`（必填，AssetRef，`type=document` PDF）；`orientation`（必填，`portrait`=竖版 / `landscape`=横版，也接受 竖版/横版/竖向/横向 等中文别名）；`name`（可选展示名，自动补 `.pdf`） |
| **输出** | `asset_ref`（旋转后新登记 document AssetRef；**无需旋转时复用原 asset_ref**）；`page_count`（number）；`source_orientation`（`portrait`/`landscape`/`mixed`/`square`）；`target_orientation`（`portrait`/`landscape`）；`rotated_pages`（number，实际旋转页数，0=复用原 asset）；`status_text`（中文一句话） |

本能力 **只看本步入参**。缺 `asset_ref` / 非 `document` / 读不了文件 / 加密 / 空 PDF →
**明确中文失败**，不产生脏 Asset。旋转角度固定为 **顺时针 90°**（`/Rotate` 累加），
不改动页内内容流。

## 方向判定（横版 / 竖版）

判断依据是**页面几何**，不是内容语义：

- 每页读 `MediaBox`（宽 `w`、高 `h`）+ 页面 `/Rotate`（0/90/180/270）。
  `/Rotate` 为 90 或 270 时，页面实际出纸方向宽高已对调，判定前先互换。
- 有效方向：`宽>高=横版(landscape)`，`高>宽=竖版(portrait)`；
  宽高差 ≤ 0.5pt 视为**方形页**（横竖等价，不参与判定/旋转）。
- **整份判**（`source_orientation`）：只看非方形页 —— 全竖 → `portrait`；
  全横 → `landscape`；横竖都有 → `mixed`；全方形 → `square`。

## 旋转语义

- 对每页比较“有效方向”与目标 `orientation`：不同 → 该页顺时针转 90°
  （累加 `/Rotate`，不动内容流，是 PDF 规范标准做法，CUPS/lp 与各查看器打印时遵守，
  转完的横版 PDF 打印出来就是横版）；已同向/方形页不动。
- 有页被旋转 → 上传登记**新** document Asset，返回它的 `asset_ref`。
- 无需旋转（已是目标方向 / 全方形）→ **复用原 asset_ref**，不重复上传。

> **局限**：本能力按“页面尺寸方向”切换横竖，不识别“页面内文字本身是否横躺”。
> 若页面尺寸已是目标方向、但页内内容仍侧转（少见），请先在该方向内再做一次整份
> 旋转修正（后续可按需增加 angle 参数）。

## 技术实现（pypdf）

- **读**：`pypdf.PdfReader` 解析（含 xref/object stream / `/Rotate`）；加密 / 无页 /
  解析失败 → 中文失败。
- **转**：对需要旋转的页调 `page.rotate(90)`（仅累加 `/Rotate`），其余页原样保留，
  经 `PdfWriter` 写出字节；对任意第三方 PDF 内容流零改动、风险最低。
- **取 PDF**：复用 Runtime SDK `CapAsset.materialize_file(ref)` 物化本步 document Asset。
- **回传产物**：旋转后字节写临时文件 → Brain `/api/v1/assets/upload`
  （`manager.upload_file`）以 `mime=application/pdf`、`type=document`、
  `producer/pdf.rotate` 上传 → 返回新 `asset_ref`（与 file.convert 同一通道）。

## 输入 schema

| 字段 | 必填 | 说明 |
|---|---|---|
| `asset_ref` | 是 | AssetRef JSON，type 必须为 `document`（PDF）。禁止 path / 永久 URL |
| `orientation` | 是 | `portrait`（竖版）或 `landscape`（横版）；接受 竖版/横版/竖向/横向 等别名 |
| `name` | 否 | 新 PDF 展示名；不传则 `pdf-rotate-<时间戳>-<横版|竖版>.pdf` |

## 输出 schema

| 字段 | 说明 |
|---|---|
| `asset_ref` | 旋转后新登记 document AssetRef；无需旋转时 = 原 asset_ref |
| `page_count` | number，PDF 页数 |
| `source_orientation` | 整份判出的原始方向：`portrait` / `landscape` / `mixed` / `square` |
| `target_orientation` | 请求的目标方向：`portrait` / `landscape` |
| `rotated_pages` | number，实际旋转 90° 的页数（0=无需旋转，复用原 asset） |
| `status_text` | 中文一句话，含页数、方向与 asset_id |

## 入口

- Mac：`mac/src/mac_edge/plugins/pdf_rotate.py`；`services.py` 广告
  `local.pdf.rotate`（laptop 角色且本机装有 pypdf 时广告）
- 执行器：`mac/src/mac_edge/executor.py` 的 `pdf.rotate` 分支
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["pdf.rotate"]`；
  `server/capability_ads.py` 与 `mac/src/mac_edge/capability_ads.py` 同步广告
