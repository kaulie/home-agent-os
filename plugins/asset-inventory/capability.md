# Service: system.asset

Brain 已登记 Asset 盘点（`asset-inventory`），group=`asset`，`kind=system`。  
只查 **Brain `assets` 表**（经 Asset Manager 注册的资源），**不**扫手机系统相册、不碰 filesystem。

由 **Brain 就地执行**，不绑任何 Runtime。入参只看本步已 resolve 的字段。

**禁止** Capability / Edge 直连 Brain SQLite、扫存储目录、读手机相册。Asset 状态以 Brain 目录为准。

## 规划自描述（系统目录结构化字段）

| 字段 | 值 |
|------|-----|
| kind | system |
| role | Asset 盘点查询器 |
| planner_recognize | 查询 Brain 已登记 Asset（含 image/video/audio/document）的数量、列表，或按登记顺序取第 N 条（index）；最新 PDF/文档用 type=document + order=newest_first + index=1 |
| typical_triggers | `我今天拍了几张照片`、`昨天拍了多少张照片`、`最近有哪些图`、`给我看第五张照片`、`最新的PDF`、`把最新的文件打印出来` |
| do_not_dispatch | 拍照、看图理解、投屏、手机系统相册、扫本机磁盘 |

问「今天拍了几张」：`day=today` + `type=image`（可选 `producer_capability=camera.capture`）。  
问「昨天拍了几张」：`day=yesterday` + `type=image`。不要先派时钟再拼假日期字符串。  
问「第 N 张」：`type=image` + `index=N`；Presentation 用 `type=image` + `from=asset_ref`（不要用 `limit=N` 再自行下标）。  
问「看下最新 PDF/文档」：`type=document` + `order=newest_first` + `index=1`；Presentation 用 `type=document` + `from=asset_ref`（手机预览，不是打印）。  
问「最新 PDF/文件」并打印：`type=document` + `order=newest_first` + `index=1`，再把产出 `asset_ref` 交给 `printer.print`。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `asset-inventory` |
| service_id | `system.asset` |
| group | `asset` |
| wire capability | `asset.inventory` |
| kind | `system` |
| 执行方 | Brain（`server/system_capabilities.py`） |

## 契约

### 入参

| 字段 | 必填 | 说明 |
|------|------|------|
| `type` | 否 | `image` / `video` / `audio` / `document` / … |
| `day` | 否 | `today` / `yesterday` / `YYYY-MM-DD` |
| `timezone` | 否 | IANA，默认 `Asia/Shanghai` |
| `since` / `until` | 否 | ISO 或 unix；有 `day` 时以 day 为准 |
| `producer_capability` | 否 | 如 `camera.capture` |
| `limit` | 否 | `asset_refs` 上限，默认 50 |
| `offset` | 否 | 跳过前 N 条（0 起）；与 `index` 二选一，优先 `index` |
| `index` | 否 | 1 起：取第 N 张（默认 `order=oldest_first`，强制 `limit=1`） |
| `order` | 否 | `newest_first`（默认列表）或 `oldest_first`（`index` 默认） |
| `include_refs` | 否 | `true`/`false`，只要数量可 `false` |

### 产出

| 字段 | 必填 | 说明 |
|------|------|------|
| `count` | 是 | 匹配总数（字符串） |
| `answer_text` | 是 | 中文结果；`index` 时为定位说明 |
| `asset_ref` | 否 | 单张 AssetRef（`index` 或仅一条时） |
| `asset_refs` | 否 | AssetRef JSON 数组 |
| `asset_index` | 否 | 回显请求的 1 起下标 |

禁止产出 `photo_url` / path / 永久 URL。
