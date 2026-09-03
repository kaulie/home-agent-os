# Plan：新增独立格式转换能力 `file.convert`（一期 image→pdf）

> 落盘：task-cf9149bf · 开发分支 `feature/task-cf9149bf` · 交付方式：PR 到 main

## 1. 目标与定位

新增一个**独立、通用**的格式转换能力 `file.convert`，支持 `from_format → to_format` 的转换框架；
**一期只实现 image → pdf**，其它组合明确中文失败。能力以 **Mac Edge 插件**形态存在
（不在 Brain 层执行，避免给 Brain server 加重环境依赖），Brain 只负责规划路由。

典型闭环：用户上传/多选 N 张图片（已登记为 Image Asset）→ 说「把这几张图合成 PDF」→ planner
派发 `file.convert` 到 Mac Edge → Mac 本机把 JPEG/PNG 合并成一个 A4 多页 PDF → 上传 Brain
并登记为 **document Asset** → 对话给出文本结果与 `asset_ref`；同一 intent 后续可接
`printer.print` 打印。

## 2. 已确认决策汇总

| 维度 | 决策 |
|---|---|
| 执行层 | Mac Edge 插件（`kind=action`），Brain 只路由，不新增 server 依赖 |
| 调用入口 | planner 意图可发现、可路由，结果回到对话 |
| 输入 | 严格 Brain Image Asset：`asset_refs` 数组，禁止本地路径/base64 |
| 页面语义 | 多张按 `asset_refs` 顺序合并为多页 PDF（1 张 = 1 页，覆盖单张场景） |
| 输出 | 上传 Brain 登记为 document（PDF）Asset，返回 `asset_ref` |
| 页面尺寸 | 每页统一 **A4 纵向**，图片等比适配、居中留白边 |
| 实现技术 | 纯标准库生成 PDF（零新增依赖）：JPEG 直嵌 DCTDecode；PNG 自解码成 RGB 入 PDF |
| 源格式 | 一期 JPEG + PNG；HEIC/WebP 后续再加 |
| wire 契约 | `from_format=image`、`to_format=pdf`、`asset_refs=[…]`；其它组合明确中文失败 |

## 3. 能力标识与契约

- plugin id：`file-convert` · service_id：`local.file.convert` · group：`convert`
- wire capability：`file.convert` · kind：`action`
- 执行方：Mac Edge laptop（`mac_edge.plugins.file_convert`）

输入 schema：`to_format`(必填, 一期仅 pdf)、`from_format`(可选, 缺省推断 image)、
`asset_refs`(必填非空 image 数组, 顺序=页码)、`name`(可选)。

输出 schema：`asset_ref`(新登记 document AssetRef)、`page_count`(number)、
`status_text`(中文一句话，含页数与 asset_id)。

## 4. 技术方案（纯标准库 PDF 生成）

Mac 侧 `mac/src/mac_edge/plugins/file_convert.py` 实现最小 PDF 书写器：

- **JPEG**：解析 marker 到 SOF0/SOF1 取宽高，baseline/sequential Huffman 原字节作为
  `/DCTDecode` 直嵌；progressive/算术编码等变体明确中文失败。
- **PNG**：chunk 解析 → `zlib.decompress(合并 IDAT)` → 还原每行 filter(0–4)。一期支持
  8bit、非隔行，color type 0/2/3/4/6；alpha 在**白色背景**上拍平；隔行/16bit 等明确失败。
- **页面布局**：每页 A4 纵向（595.276 × 841.89 pt），留边距 ~36pt，图片按 `min` 等比居中。
- **取图**：`CapAsset.materialize_file(ref)` 物化为本地路径再读字节。
- **回传产物**：PDF 字节写临时文件 → Brain `/api/v1/assets/upload`（`manager.upload_file`）
  以 `mime=application/pdf`、`type=document`、`producer/file.convert`、携带
  `intent_id`/`edge_id` 上传。

## 5. 代码改动清单（逐文件）

1. `plugins/file-convert/capability.md` 新建（服务说明 + 规划自描述 + 契约）
2. `plugins/file-convert/manifest.yaml` 新建（`id: file-convert` 等，entry 指向 mac plugin）
3. `mac/src/mac_edge/plugins/file_convert.py` 新建（PDF 书写器 + `convert_from_params` 入口）
4. `mac/src/mac_edge/asset/sdk.py` 为 `CapAsset` 增加通用文件上传方法（支持
   asset_type/mime_type/producer/filename 的 `manager.upload_file` 包装）
5. `mac/src/mac_edge/services.py` 新增 `LOCAL_FILE_CONVERT_SERVICE`，加入
   `_LAPTOP_SERVICE_ORDER`，`default_services()` 在 laptop 角色恒广告
6. `mac/src/mac_edge/capability_ads.py` 新增 `file.convert` 广告条目
7. `mac/src/mac_edge/executor.py` import + `if cap == "file.convert":` 分发
8. `server/capability_ads.py` 镜像 `file.convert` 广告
9. `server/edge_services.py` `KNOWN_CAPABILITIES["file.convert"]` 登记
10. `server/system_capabilities.py` `_GROUP_ORDER` 增加 `convert`
11. `mac/tests/test_file_convert.py` 新建单测
12. `agent_plans/file_convert_capability_v1.md` 本计划落盘

## 6. 测试

`mac/tests/test_file_convert.py`：
- 纯 PDF 书写器：最小合法 PNG（zlib 构造 RGB/RGBA/调色板）、baseline JPEG → 断言
  `%PDF-` 头、`/MediaBox` A4、`/Type /Page` 数量 = 图片数、filter 正确；
- 契约校验：`to_format != pdf`、`from_format != image`、空 `asset_refs`、非 image type → 中文失败；
- 插件分发：mock `CapAsset`（materialize 返回本地临时图、上传返回 document AssetRef）→
  输出含 `asset_ref`、`page_count=N`；
- 不支持变体（隔行 PNG / progressive JPEG）→ 明确中文失败。

回归：跑 `mac/` 与 `server/` 现有测试确保未破坏（尤其 ads/executor/services 相关）。

## 7. 明确不做（另开任务）

- 其它 from→to 转换与 HEIC/WebP 等源格式；
- iOS / 端上 PDF 预览与下载 UI；
- Brain 层或独立服务形态的执行；
- 本任务只交付分支与 PR，不自行 merge、不触发 release/deploy。

## 8. 交付流程

在任务工作区 `task-cf9149bf` 开发，建分支 `feature/task-cf9149bf`，按清单实现并单测 →
`git commit` → `git push -u origin HEAD` → `gh pr create` 并把 PR URL 交给用户等待合入。
