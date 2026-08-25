# Service: document.scanner

iPhone **document.scan** = Intent Source 侧 **本地 Input**：

UI 触发 → 系统文档扫描 → `POST /api/v1/assets/upload`（一次收文件并登记 Asset）。

不做 OCR / 业务理解。Chat 入口 **不经** Planner / 「扫描一下」文本意图。

## 规划自描述（心跳广告，能力发现）

| 字段 | 值 |
|------|-----|
| kind | `input` |
| role | 纸质文档扫描器 |
| planner_recognize | 用 iPhone 系统文档扫描采集纸质并上传为 Image Asset |
| typical_triggers | `扫描一下`、`扫一下`、`扫描一下这个小票` |
| do_not_dispatch | OCR、金额识别、看图理解、投屏、开灯 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `document-scanner` |
| service_id | `document.scanner` |
| wire | **`document.scan`** |
| 主路径 | Chat「扫描」本地 Input（立刻弹扫描仪） |
| 上传 | `POST /api/v1/assets/upload`，`upload_intent=document.scan` |

## Chat 主路径

1. 用户点「扫描」
2. 立刻 `VNDocumentCameraViewController`
3. 用户点系统「完成」
4. `POST {brain}/api/v1/assets/upload`（multipart：`file` + `upload_intent`）
5. 对话展示 `asset_id`（不开 intent 轮询）

## 实现

- iOS：`VisualInput.swift`、`AppModel.runLocalDocumentScan`
- Brain：`server/home_brain.py` → `POST /api/v1/assets/upload`
