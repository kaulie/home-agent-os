# Plan：URL 作为一级 Asset 类型 + Console 保存链接 + 能力端可消费

> 落盘：task-c7cf506e · 开发分支 `feature/task-c7cf506e-url-asset` · 交付：PR 到 main

## 1. 背景与目标
用户确认：**URL 也是一种 Asset 类型**（`type=url`）。HomeAgent Console（iOS
LivingRoomEdge）「文件」页要能「保存链接」= 把一条 URL 登记成 Brain 的 `url` Asset
（不是转文档、也不是本机书签），并满足：
1. 进 Brain（可被家里各端/planner 看到）；
2. 授权读取：`GET /api/v1/assets/<id>` 返回 url，`/content` 对 url 资产 302 到目标；
3. 能力端可消费：planner 能把 url Asset 作为 `asset_ref(type=url)` 交给能力（如
   `web.scraper` 直接抓该链接转 PDF/文本）。

## 2. 已确认决策汇总
| 维度 | 决策 |
|---|---|
| 资产类型 | 新增一级类型 `url`（db `_ASSET_TYPES` 加 `url`） |
| 链接存放 | metadata 专用键 `url_target`（不在现有剥离名单）；不改“身份=asset_id”契约，URL 不落 storage/身份 |
| 注册 | 无字节 JSON 接口 `POST /api/v1/assets/register`（type=url 专用） |
| 读取 | GET 授权视图返回顶层 `url`；public 视图隐藏 url_target |
| content | type=url → 302 到 url_target；非法/缺失 → 明确 4xx/5xx |
| 消费 | Mac `resolve_for_capability`：url 资产 need=http_url → Brain /content（带 grant，302 到目标）；`web.scraper` 增加 `asset_ref(type=url)` 入参 |
| Console | 文件页「保存链接」→ register 到 Brain → 本地列表留记录（打开/删除仅本机记录） |

## 3. 改动文件
- server：`db.py`（类型白名单）、`home_brain.py`（register 端点 / GET 视图 / content 302）
- mac：`asset/manager.py`（url representation）、`plugins/web_scraper.py`（asset_ref=url 入参）、
  `services.py` / `capability_ads.py`、executor 不变
- server 侧镜像：`capability_ads.py`、`edge_services.py`（web.scraper 入参 schema）
- ios/LivingRoomEdge：新增 register 调用 + AppModel SavedUrlAsset + FileWorkspaceView「保存链接」
- 测试：server（类型归一化/register/content302）、mac（web_scraper asset_ref 分支 + manager url）、
  iOS（xcodebuild 编译校验）
- 文档：`plugins/web-scraper/*`、`docs/asset-contract.md`（类型表补 url）、agent_plans
