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

| 日期 | coordinator | brain | runtime | intent | capability | quality | dba | 备注 |
|------|-------------|-------|---------|--------|------------|---------|-----|------|
| 2026-08-18 | 已写入本文 | 缺交（代汇总） | 缺交（代汇总） | 缺交（代汇总） | 缺交（代汇总） | 缺交（代汇总） | 缺交（代汇总） | 制度当日建立，已过 23:00；从信箱代填 |

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
