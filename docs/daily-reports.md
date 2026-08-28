# Agent 日报

统一管理各 Cursor handle 的日报。规范见 [`agent-coordination.md`](agent-coordination.md) 第 9 节。催办由 `@coordinator` 每晚 **22:50** 在 Agent Chatbox（`http://127.0.0.1:8787/`）`@all` 发出，截止 **23:00**（UTC+8）。

## 制度

| 项 | 约定 |
| --- | --- |
| 谁交 | 已注册全部 handle（含 `@coordinator`） |
| 怎么交 | chat `push_msg`：`@coordinator`，正文以 `日报` 开头 |
| 截止 | 当天 23:00 前 |
| 催办 | `@coordinator` 22:50 `@all` 催办-日报 |
| 汇总 | `@coordinator` 把当日各条写入本文（新日期在上）；未交标 **缺交** |
| 代汇总 | 当日无人交正式日报时，coordinator 可从完工/交卷代填，并注明来源 |
| 不结案 | 日报不是验收；已报备问题仍须 `@quality` 打对外 API |

## 模板（chat 正文单行）

```text
完成：…｜阻塞：…｜明日：…｜待验收：…
```

四段都要有。没有则写「无」。过长把细节放到文档路径，chat 只留摘要。

## 交收台账

| 日期 | coordinator | brain | runtime | ui | capability | quality | deploy | sre | dba | 备注 |
|------|-------------|-------|---------|-----|------------|---------|--------|-----|-----|------|
| 2026-08-19 | 已写入本文 | 缺交（代汇总） | 缺交（代汇总） | 缺交（代汇总） | 缺交（代汇总） | 缺交（代汇总） | — | — | 缺交（代汇总） | 22:50 催办 loop 中断；23:42 补催+代汇总 |
| 2026-08-18 | 已写入本文 | 缺交（代汇总） | 缺交（代汇总） | 缺交（代汇总） | 缺交（代汇总） | 缺交（代汇总） | — | — | 缺交（代汇总） | 制度当日建立，已过 23:00；从信箱代填 |

---

## 2026-08-19

当日无人交主题 `日报`（22:50 催办 loop 曾中断）。下列由 `@coordinator` 从 chat #40–#119 完工/交卷/对齐代汇总。**不结案**。

### @coordinator

- **完成：** 现场管理页拆到本机 `admin/serve.py`（8788，不上云）；默认 `BRAIN_URL` 指云 `115.190.153.53:9527`。9527 崩溃（`load_control_policy_index`）修复并上云；admin 列表 fallback（无 `list_participants` 也能列节点）。chat `@all` 调度口径 #103/#105。23:42 补催 brain/runtime/intent/quality/dba + 本汇总。
- **阻塞：** 云库仍 v12，管理页策略开关写库待 014 迁移；多 handle 长时间未 pull。
- **明日：** 盯 dba 云迁移、quality 验收；补 arm 22:50 日报 loop。
- **待验收：** 无本层实现。

### @brain

- **完成：** AssetRef presentation/planner 上云（#43/#102）；sanitize `$asset_ref`、禁 image_url；GET `/assets/{id}/content`、storage.url 优先 cloud；admin 调度三条 + `can_participate`（本地，部分上云）。116 endpoint asset stream 已上云请 quality 验。配合 9527 重启多次。
- **阻塞：** 云 db 缺 013–015；117/118 feedback API 待确认+上云；D5 Endpoint 拉 stream 仍等 @intent。
- **明日：** 配合 @dba 迁移后 rsync+restart；确认 intent_feedback 路由。
- **待验收：** stream（#116）、asset_ref 全链路、admin policy（迁移后）。

### @runtime

- **完成：** Asset 对齐：CapAsset SDK、LAN→cloud mirror、planner repair 认 asset_ref（#97）。110/113：Brain 全 step terminal 自动 succeeded/failed；iOS RuntimeLoop 防重复拍。111 laptop 已重启。
- **阻塞：** home-server 离线致 N9–11/N17 空 plan；115 light.set 音频待同步 home-server。
- **明日：** 同步 home-server + 重启；确认 110/113 Brain 改动已上云。
- **待验收：** intent 155/158 类单步收口（Brain 已改，iOS 待编）。

### @intent

- **完成：** presentation 只认 asset_ref；取图优先 storage.url/cloud（#104/#106）。117/118 草案：015 intent_user_feedback 表+API+iOS IntentFeedbackStrip。
- **阻塞：** 110/113/114/112 均需重编 iOS（finalize、stream 取图、light.set、feedback）；50 所列 intents 列表 API 未点名不改 Brain。
- **明日：** 合并 capability 改动发版；联调 feedback API（等云迁移）。
- **待验收：** Endpoint stream 取图、light.set 真机。

### @capability

- **完成：** 全线切 asset_ref（#96）；query.content want_image + 拒答仍出图（#91–92）；112 light.set 注册到 iPhone（livingroom.ceiling_light）；114 iPhone 改 stream 取图；115 预录音频 wake/on/off。
- **阻塞：** N7/N9 无拍照是 home-server 离线非 plugin；Cast 503 未在本层闭环。
- **明日：** 等 iPhone App 重装验证 light.set；Android/iOS 仍缺 CapAsset SDK。
- **待验收：** light.set、query 出图投屏（Edge 重启后）。

### @quality

- **完成：** #107–108 N1–N20 复测交卷（intent 130–149）：**13 通过 / 6 部分 / 1 不符**（相对 23:00 的 14/4/2）。材料 `tests/blackbox/report.md` · `log.md` · `run_results_n20_round4*.json`。#109 事实：N7 空 plan、N13 music.play、N9–11/N17 home-server offline、N12 Cast 503。
- **阻塞：** 116 stream、119 迁移后 admin/feedback 未验；brain/runtime 长闲置。
- **明日：** 黑盒 stream；云迁移 013–015 后验 admin nodes + intent_feedback。
- **待验收：** 本层是验收方；N1–N20 仍不结案。

### @dba

- **完成：** 014 edge_control_policy 本地 v14；#119 确认 015 intent_user_feedback 无异议（CHECK/UNIQUE 对齐）；本地 init→v15，test 通过。
- **阻塞：** **云 Brain 生产库仍 v12**（缺 013/014/015）。
- **明日：** rsync `db.py`+`sql/013–015` → 云 `python3 db.py init` + restart；014 解锁管理页写策略。
- **待验收：** 迁移后 @quality 验 admin + feedback。

### 跨层未结

1. 云库 013–015 迁移（admin 开关、feedback、intent_id INTEGER）。
2. iOS 重编：finalize / stream / light.set / feedback UI。
3. N1–N20：N7 query、N13 music、home-server 离线、Cast 503。
4. Asset 全链路验收（stream、旧图无 cloud mirror 需重拍）。

---

## 2026-08-18

制度当日建立（约 23:20）。无人交主题 `日报`。下列由 `@coordinator` 从信箱完工/交卷/对齐代汇总。N1–N20 **不结案**。

### @coordinator

- **完成：** 改名 `@observer` → `system coordinator agent` / `@coordinator`。恢复 30 分钟完整巡检，禁止 5 分钟空转。对齐 Participant Model、Asset Contract（`docs/participant-model.md`、`docs/asset-contract.md`）。看板与 ACK 催办。拆单：DB 归 `@dba`、规划归 `@brain`、调度归 `@runtime`、发出窗口归 `@intent`、Cast503 归 `@capability`。建立本日报文档与 22:50 催办。
- **阻塞：** `@capability` 查阅停 15:25、`@dba` 停 16:40；Cursor 停会话不会被信箱叫醒。
- **明日：** 22:50 催日报；收齐后改「代汇总」为正式条。继续催闲置、监督 ACK。Asset / N1–N20 未点名不改产品代码。
- **待验收：** 无本层实现。

### @brain

- **完成：** 仓库 Brain 换成 `server/home_brain.py`（去 stub、prompt 避 JSON `format`）。持久化对齐 schema：空 plan / 规划失败 → `failed+msg`（不再 `plan_failed`）；拉取按 `assigned_edge_id`。停 `init_db`，部署不带 `db.py`/`sql`。sanitize 去掉默认 `endpoint.present` / 未点名 `display.photo`。「拍张照片我看一下」只派 `camera.capture`，顶层 `presentation`；`presentation.endpoint` = 在线 Endpoint 的 `participant_id`（TTL **5 分钟**，与 Runtime 30s 分开）。intent 71「客厅有几个人」`type=text` 不出图。已上云 `health=200`。已读 Asset Contract，一期不改 presentation 为 `asset_id`。
- **阻塞：** iPhone 只 register 不 heartbeat 则 `presentation.endpoint` 空（已派 `@intent`）。Chromecast `music.play` 因 clock skew `schedule_eligible=0`。
- **明日：** 等 `@quality` 验收 endpoint TTL / 看人出字 / 拍照出图。
- **待验收：** 多则「请验收」已发 `@quality`，未结案。

### @runtime

- **完成：** 允许多 edge 分步；空 plan → failed；失败 `msg`；hydrate fail；GET `/intent/{id}` 本地 200。Presentation 改 Brain 顶层，本层只 Capability + TTS 钩。`finalize_intent_from_plan` / `reconcile_peeked_terminal`；laptop + home-server 已部署，intent 47–52 曾 `running`→`succeeded`。N6/N13/N14/N20 观察窗短于串行队列，事后已 succeeded。已读 Asset Contract：Asset Manager 归本层，一期未点名不改代码。
- **阻塞：** 黑盒连续 POST 时观察窗仍可能看到 `running`。Cast 503 不在本层。
- **明日：** 等 `@quality` 重测 N1–N20 整单收口。
- **待验收：** finalize 请验收已发，未结案。

### @intent

- **完成：** iPhone 登记 Participant（`intent_source`+`endpoint`，`supported_presentation=image,text`），POST `participant_id`/`client_hint`。按顶层 `presentation.type` 渲染图/文；整单终态只信 `intent_status`。记下 `presentation.endpoint` 是 Endpoint id。已读两份对齐文档。
- **阻塞：** 须真机重开后再发「拍张照片我看一下」。Brain 要求 iPhone `POST /api/v1/edge-heartbeat`（30–60s，`services=[]`），23:12 派工是否已做未知（查阅 22:57）。
- **明日：** 心跳 + 真机验证交付。
- **待验收：** 窗口未单独立项请验。

### @capability

- **完成（15:25 前）：** 读 Participant Model；确认不再 5 分钟空转；`endpoint.present` 未点名不删。记下 present 缺 source、对齐后 Presentation 归 Brain。
- **缺交 / 闲置：** 查阅仍 **15:25:47**。Asset 对齐、Cast 503 / query timeout、22:49 催办均未 ACK。下午无 plugin 进展。
- **阻塞：** 会话未打开则催办无效。
- **明日：** 先读约定与信箱；Cast 503 等用户点名或 coordinator 派工再改。
- **待验收：** 无新请验。

### @quality

- **完成：** 00:10 现场 GET + A1–A7；15:21 R1–R5 生产空 plan/`plan_failed`；17:56 N1–N20 对照 **通过 2 / 部分 6 / 不符合 12**；21:44 环境恢复重测 **通过 3 / 部分 12 / 不符合 5**（拍照/问钟/问答步能跑，整单常 `running`，Cast 503，放歌空 plan）。材料 `tests/blackbox/report.md`。已读 Asset Contract，黑盒不把 path/URL 当身份。
- **阻塞：** 整单收口、顶层 presentation、Cast 503、放歌空 plan 未闭环。N20 第三轮若在跑，交卷后补记。
- **明日：** 打 Brain 当晚请验收（endpoint 5min TTL、intent 71 出字、拍照出图）与 runtime finalize。
- **待验收：** 本层是验收方，不结案。

### @dba

- **完成（16:40 前）：** 建库 WAL；迁移 002 jobs 打平、004 `participants`、005 去 `intent_queue`、006 `location`、007 去二级索引、008/009 `intent_reviews`+`session_id`、010 去 `observer_events`；合同 `docs/db-schema.md` 只留现行状态；`intent_waiting` 非终态。Edge JSON 未改。已读 Participant Model。
- **缺交 / 闲置：** 查阅仍 **16:40:58**。Asset 对齐、Brain 不操作 DB 的收回、22:49 催办未 ACK。
- **阻塞：** 云上 SQLite 3.34.1 不能 `DROP COLUMN`；生产迁移是否跑到 version=10 待确认。
- **明日：** 先读箱；接管 `db.py`/上云迁移。
- **待验收：** 多次请验收堆积，等 `@quality` 打 API，不自行结案。

### 跨层未结（写入日报不等于结案）

1. N1–N20 对照未过。
2. Asset Contract：一期未点名不改代码。
3. iPhone Endpoint 心跳与真机交付。
4. Cast 503、`music.play` 不可见、capability/dba 会话闲置。
