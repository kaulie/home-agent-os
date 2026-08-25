# 黑盒测试报告

旧轮次结果已于 2026-08-18 删除。本文件只记 **N1–N20**（2026-08-18 17:32 起跑）。

Brain（下轮）：`http://127.0.0.1:9527`（本机 LAN Brain。下列历史轮次当时打的是云 `http://115.190.153.53:9527`）  
原始：[`run_results_n20.json`](run_results_n20.json) · 本轮 [`run_results_n20_round4.json`](run_results_n20_round4.json) · 无 issuer 门闸 [`run_results_n20_round4_nopid.json`](run_results_n20_round4_nopid.json) · 23:00 [`run_results_n20_round3.json`](run_results_n20_round3.json)  
记录：[`log.md`](log.md)

**质量对照（对照章程 / Participant Model，不是 runner 自动 ok）**

| 批次 | 通过 | 部分 | 不符合 |
|------|------|------|--------|
| **2026-08-19 15:32 再复测** | **13** | **1** | **6** |
| 17:32 首跑 | 2 | 6 | 12 |
| 21:44 环境恢复重测 | 3 | 12 | 5 |
| **23:00 再测一轮** | **14** | **4** | **2** |

对照口径：问钟应 `clock.now` 且可读时刻出现；问答应 `query.content` 且有 `answer_text`；拍照应 `camera.capture`；投电视应 `display.*`；放歌应 `music.play`；无能力应干净失败且不要硬套 speak；失败有可读 `msg`；Brain 顶层 `presentation`；物流应到 `succeeded`/`failed`，不得停在 `intent_parsed` / `intent_dispatched` / `running`。

---

## 2026-08-19 15:32 再复测

用户「再复测一遍 case」。`GET /health` 200，`jobs=129`，`pending_intents=1`，`registered=5`。`tests/blackbox/run_n20.py` 原文（无 `participant_id`）**N1–N20 全部 POST 400**，body `participant_id is required; register and heartbeat first`，无 intent id。探针：未知 id **401**；Mac runtime `9tkgMTtn` **403** `did not declare intent_source`；iPhone `JzvEe287` **403** `heartbeat required`（`GET /edges` 该节点 `online_status=offline`）。

随后用公开 `POST /api/v1/edge-register` + `/edge-heartbeat` 注册测试发出端 `edge-node-CiqVl9ZB`（roles=`intent_source`+`endpoint`，无 runtime 广告），再 **重新 POST N1–N20**（intent **130–149**）。快照 [`run_results_n20_round4.json`](run_results_n20_round4.json)。窗口约 15:41–15:52。全部离开 parsed/dispatched/running；事后再 GET 无非终态单。当时 `GET /edges`：laptop `9tkgMTtn` online；home-server `x0OjfixA` **offline**；Chromecast `ZeECgaki` online 但 `schedule_eligible=false`（time diff）。

| ID | 指令 | intent | plan | 步 | 整单 | 对照 |
|----|------|--------|------|----|------|------|
| N1 | 现在几点了 | 130 | clock.now | status=2，`time_text=15:41:18` | succeeded @9s | **通过**；presentation type=text from=time_text；无 image_url / asset_ref；endpoint=`CiqVl9ZB` |
| N2 | 用语音告诉我现在几点了 | 131 | 仅 clock.now | status=2 | succeeded @15s | **通过**：有时刻；plan 无 speak；presentation type=**audio** from=time_text；无 `pending_delivery` 字段 |
| N3 | TTS你好 | 132 | notify.speak | status=2 | succeeded @21s | **通过**；presentation type=audio from=state，endpoint=`""` |
| N4 | 一加一 | 133 | query.content | status=2 有 answer_text | succeeded @82s | **通过**；presentation type=text from=answer_text |
| N5 | 晋字几画 | 134 | query.content | status=2，answer_text + 步内 asset_ref | succeeded @52s | **通过**；顶层 presentation type=text，**无** image_url、**无** asset_ref（asset_ref 只在 step_outputs） |
| N6 | 猫叫什么 | 135 | query.content | status=2 诚实不知道 | succeeded @46s | **通过** |
| N7 | 客厅适合看书吗语音 | 136 | **空 plan** | — | failed @12s，msg=要先拍 AssetRef / 当前无拍照能力 | **不符合**：看书未派 `query.content` |
| N8 | 开窗帘 | 137 | 空 plan | — | failed，msg=无窗帘能力 | **通过**；未硬套 speak |
| N9 | 拍张照 | 138 | 空 plan | — | failed，msg=无拍照能力 | **不符合**：无 `camera.capture` |
| N10 | 拍照投电视 | 139 | 空 plan | — | failed，msg=无拍照能力 | **不符合**：无 camera / display |
| N11 | 拍照看人语音 | 140 | 空 plan | — | failed，msg=无拍照能力 | **不符合**：无 capture / perceive |
| N12 | 画台灯投电视 | 141 | query → display.photo | 两步 status=2 | **succeeded** @52s | **通过**；presentation type=image from=asset_ref，`asset_ref={asset_id,type,mime_type}`，**无 image_url** |
| N13 | 放陈奕迅十年 | 142 | 空 plan | — | **failed** @9s，msg=没有可调用的 music.play | **不符合**：无 `music.play`；未停 `intent_parsed` |
| N14 | 投到电视上 | 143 | 空 plan | — | failed | **通过** |
| N15 | 轮播刚才的照片 | 144 | 空 plan | — | failed | **通过** |
| N16 | 一分钟后该喝水了 | 145 | notify.speak delay | status=2 | succeeded @64s | **通过**；presentation type=audio endpoint=`""` |
| N17 | take_photo | 146 | 空 plan | — | failed，msg=无拍照能力 | **部分**：未映射 capture；失败有 msg |
| N18 | 拍张照但不要拍照 | 147 | 空 plan | — | failed | **通过**（未拍照） |
| N19 | 地球到月球 | 148 | query.content | status=3 ark timeout + request_id | 观察窗 **failed** @101s；事后 GET 顶层 **succeeded**，步仍 3，无 answer_text，presentation 无 text | **不符合**：succeeded 无问答产出 |
| N20 | 天气适合散步吗 | 149 | query.content | status=2 诚实不知道 | succeeded @67s | **通过** |

### presentation 观察（成功出图 / 问钟；非 AssetRef 全链路验收）

| 单 | 顶层 presentation keys | image_url | asset_ref | endpoint |
|----|------------------------|-----------|-----------|----------|
| N1 钟 130 | type, from, text, channel, endpoint | 无 | 无 | `CiqVl9ZB` |
| N2 钟语音 131 | type=audio, from, text, channel, endpoint | 无 | 无 | `CiqVl9ZB` |
| N5 晋字 134 | type=text, from, text, channel, endpoint | 无 | 顶层无（outputs 有） | `CiqVl9ZB` |
| N12 台灯图 141 | type=image, from=asset_ref, asset_ref, channel, endpoint | **无** | **有** `{asset_id,type,mime_type}` | `CiqVl9ZB` |
| N9/N10 拍照 | （失败 type=text from=msg） | 无 | 无 | `CiqVl9ZB` |

### 相对 23:00 的变化（事实）

1. **入队门闸**：无 `participant_id` 不再入队（400）。本轮执行单均带测试 issuer `CiqVl9ZB`。
2. **物流**：20 单均到 `succeeded`/`failed`，无停 `intent_parsed`。N13 本轮是空 plan **failed**（23:00 是 `music.play` 停 parsed）。
3. **投屏**：N12 `display.photo` status=2 整单 succeeded；本轮未见 Cast HTTP 503。N10 未规划到 display。
4. **拍照**：N9/N10/N11/N17 空 plan；`x0OjfixA` 当时 offline。23:00 这些单有 `camera.capture`。
5. **看书 N7**：23:00 为 camera→vision.ask→speak 且 succeeded；本轮空 plan failed，msg 要拍照 AssetRef，仍未见 `query.content`。
6. **N19**：观察窗 failed（ark timeout 有 msg）；事后 GET 顶层变成 succeeded，步仍失败且无 `answer_text`。
7. **顶层 presentation**：成功问钟/问答有 type=text 或 audio；N12 成功图为 `asset_ref`、无 `image_url`。纯 TTS endpoint 常为 `""`。

不结案。

---

## 2026-08-18 23:00 再测一轮

用户「再测一轮 case」。`GET /health` 200，`jobs=55`，`pending_intents=0`。事前 GET 旧单 **25–52** 已全终态（succeeded 19 / failed 9；含 47–52）。仍 **重新 POST** N1–N20（`tests/blackbox/run_n20.py` 文本，`source=text`，长观察窗）+ 另 POST `拍张照片我看一下` `source=voice`。本轮 intent **56**（拍照看一下）、**57–79**（N1–N20，缺号 67/69/71 非本 runner）。快照 [`run_results_n20_round3.json`](run_results_n20_round3.json)。窗口 23:00–23:21。

| ID | 指令 | intent | plan | 步 | 整单 | 对照 |
|----|------|--------|------|----|------|------|
| P | 拍张照片我看一下 voice | 56 | 仅 camera.capture | status=2，LAN 图 | **succeeded** @64s | **通过**：无 display/present；顶层 presentation type=image、image_url=photo_url、channel=iphone；观察窗 endpoint=`edge-node-JzvEe287`（非 capture 边 `x0OjfixA`）；事后 GET endpoint=`""` |
| N1 | 现在几点了 | 57 | clock.now | status=2，`time_text=23:01:11` | succeeded @6s | **通过**；presentation type=text + 时刻 |
| N2 | 用语音告诉我现在几点了 | 58 | clock → speak | 两步 status=2 | succeeded @22s | **通过** |
| N3 | TTS你好 | 59 | notify.speak | status=2 | succeeded @22s | **通过**：无 present；顶层 presentation 无 |
| N4 | 一加一 | 60 | query.content | status=2 `一加一等于二。` | succeeded @31s | **通过** |
| N5 | 晋字几画 | 61 | query.content | status=2，有 answer_text | succeeded @65s | **通过**；顶层 presentation type=image（query 图） |
| N6 | 猫叫什么 | 62 | query.content | status=2，诚实不知道 | succeeded @31s | **通过** |
| N7 | 客厅适合看书吗语音 | 63 | **camera → vision.ask → speak** | 三步 status=2 | succeeded @62s | **不符合**：看书补拍且 ask |
| N8 | 开窗帘 | 64 | 空 plan | — | failed，msg=空 plan 无法调度 | **通过** |
| N9 | 拍张照 | 65 | camera.capture | status=2 有图 | succeeded @136s | **通过**；presentation type=image |
| N10 | 拍照投电视 | 66 | camera → display.photo | capture=2；display=3 Cast 503 / wait 15s | **failed** | **部分**：规划对；投屏超时；整单已 failed |
| N11 | 拍照看人语音 | 68 | camera → vision.perceive | capture=2；perceive=3 `download image failed: timed out` | **failed** | **部分**：已是 perceive 不是 ask；无 speak；整单 failed |
| N12 | 画台灯投电视 | 70 | query → display.photo | query=2；display=3 Cast 503 | **failed** | **部分** |
| N13 | 放陈奕迅十年 | 72 | music.play | 步 status 空，`assigned_edge_id` 空 | **intent_parsed**（240s 观察 + 23:21 再 GET 仍 parsed） | **不符合**：有 music.play 但未离 parsed |
| N14 | 投到电视上 | 73 | 空 plan | — | failed | **通过** |
| N15 | 轮播刚才的照片 | 74 | 空 plan | — | failed | **通过** |
| N16 | 一分钟后该喝水了 | 75 | notify.speak delay | status=2 | succeeded @79s | **通过** |
| N17 | take_photo | 76 | camera.capture | status=2 有图 | succeeded @63s | **通过**；终态 presentation.endpoint=`""` |
| N18 | 拍张照但不要拍照 | 77 | 空 plan | — | failed | **通过**（未拍照） |
| N19 | 地球到月球 | 78 | query.content | status=3 ark timeout + request_id | **failed** @100s | **部分**：失败有 msg；整单已 failed（不再 running） |
| N20 | 天气适合散步吗 | 79 | query.content | status=2 诚实不知道 | succeeded @102s | **通过**；endpoint=`""` |
| 71 | 客厅里有几个人 voice | 71 | camera → perceive | 两步 status=2 | succeeded | GET：presentation **type=text**，无 image_url，text=summary「客厅内一名未穿上衣的男子…」；endpoint=`""` |

### 相对 21:44 的变化（事实）

1. **整单收口**：步全 status=2 的本轮均 `succeeded`；步 failed 的本轮均 `failed`（N19 不再停 running）。例外 N13 停 `intent_parsed`。
2. **顶层 presentation** 在问钟/问答/拍照成功单上出现（type=text 或 image）。纯 TTS（N3/N16）无顶层 presentation。
3. **拍照看一下**（56）plan 仅 `camera.capture`。观察窗 `presentation.endpoint=edge-node-JzvEe287`；约 20 分钟后 GET 该字段为空。现行 `/api/v1/edges` 仅 3 个 runtime，未见该 id。
4. **投屏** 仍 Cast HTTP 503 / wait 15s；整单 failed。
5. **放歌** 本轮 plan 为 `music.play`（不再空 plan），但 240s+ 仍 `intent_parsed`、无 assigned_edge。
6. **看书** 仍补拍 + `vision.ask`。看人（N11）已是 `vision.perceive`。

不结案。

---

## 2026-08-19 09:01 011 assets / asset_grants

dba 请验收（chat id 17）：011 加 `assets` / `asset_grants`，**无新对外路由**。黑盒只打既有 `POST /api/v1/intent` + `GET /api/v1/intent_detail`（及既有 `GET /api/v1/intent/{id}`）。不结案。

| 步骤 | 结果 |
|------|------|
| GET `/health` | **200** `ok=true` `jobs=100` `pending_intents=1` `registered=5` `db=/root/chat-gateway/data/brain.sqlite3`。**无 version / schema_version 字段，看不到 version=11。** |
| POST `/api/v1/intent` `{"text":"现在几点了","source":"text"}`（无 execution_plan） | **200** `intent_id=101` `intent_status=intent_received` |
| GET `/api/v1/intent_detail?intent_id=101` | **200** 有 body；终态 `succeeded` |
| GET `/api/v1/intent/101` | **200** 同 body |
| GET `/api/v1/assets`（可选，非验收项） | **404** |

现象（事实）：plan 仍为 `clock.now`（status=2）；顶层 `presentation` type=text，`time_text=2026年8月19日 09:01:28（CST，UTC+08:00）`。既有 intent 读写 200，未要求新公开路由。health **不能**用来确认生产已跑 011。

记录：[`log.md`](log.md) 同日 09:01 节。不结案。

---

## 2026-08-18 21:44 环境恢复重测

用户称环境已恢复。本轮 POST N1–N20（intent **25–52**），事后 `GET intent_detail` + `GET /intent/{id}`（均为 200）。快照 [`run_results_n20_live.json`](run_results_n20_live.json)。相对 17:32：**拍照/问钟/问答步已能 status=2 并有产出**；**整单常仍停在 `running`**（步已成功也不 `succeeded`）；投屏 Cast **503**；仍无顶层 `presentation`。

| ID | 指令 | intent | plan | 步 | 整单 | 对照 |
|----|------|--------|------|----|------|------|
| N1 | 现在几点了 | 25 | clock.now | status=2，`time_text=21:44:01` | **running** | 部分：钟对；无顶层 presentation；未收口 |
| N2 | 用语音告诉我现在几点了 | 26 | clock.now → notify.speak | 两步 status=2 | running | 部分：末步已是 speak 不是 present |
| N3 | 用语音说：你好，这是TTS测试 | 27 | notify.speak | status=2 | running | 部分：纯提醒未再派 present |
| N4 | 一加一等于几 | 28 | query.content | status=2，`一加一等于二。` | running | 部分 |
| N5 | 晋字一共几画 | 30 | query.content | status=2，10画+汉典 citations+图 | running | 部分 |
| N6 | 我家里那只猫叫什么名字 | 31 | query.content | status=2，诚实不知道 | running | 部分 |
| N7 | 客厅现在适合看书吗，用语音告诉我 | 32 | **camera → perceive → speak** | 三步 status=2，两 edge | running | 不符合：看书补拍 |
| N8 | 把客厅窗帘打开 | 33 | 空 plan | — | failed，msg=空 plan 无法调度 | **通过**（干净失败，未硬套 speak） |
| N9 | 拍张照 | 34 | camera.capture | status=2，有 LAN `photo_url` | running | 部分：拍照已恢复 |
| N10 | 拍张照投到电视上 | 36 | camera → display.photo | capture=2；display=3 **Cast 503 / wait 15s** | failed | 部分：规划对；投屏超时 |
| N11 | 拍张照看看客厅有没有人 | 38 | camera → **vision.ask** → speak | 三步 status=2，两 edge | running | 不符合：应用 perceive |
| N12 | 画台灯示意图投电视 | 39 | query → display.photo | query=2 已出图；display=3 Cast 503 | failed | 部分 |
| N13 | 播放陈奕迅的十年 | 40 | 空 plan | — | failed 空 plan | 不符合：未见 music.play |
| N14 | 投到电视上 | 41 | 空 plan | — | failed 空 plan | **通过**（不该成功） |
| N15 | 轮播刚才那些照片 | 42 | 空 plan | — | failed 空 plan | **通过** |
| N16 | 一分钟后用语音说：该喝水了 | 43 | notify.speak delay | status=2 | running | 部分：delay 对，未收口 |
| N17 | 用 take_photo 拍一张 | 45 | camera.capture | status=2，有图 | running | 部分：已映射成 capture |
| N18 | 拍张照，但是不要拍照 | 47 | notify.speak | status=2 | running | 部分：未拍照 |
| N19 | 地球到月球大约多远 | 49 | query.content | status=3，ark timeout | **仍 running** | 不符合：失败步有 msg 但整单未 failed |
| N20 | 今天天气适合散步吗 | 52 | query.content | 步 status 空 | **intent_dispatched** | 不符合：未执行 |

### 相对 17:32 的变化（事实）

1. **拍照回来了**：N9/N10/N11/N17 有 `camera.capture` 且产出 LAN 图（home-server `edge-node-x0OjfixA`，后续步在 laptop `9tkgMTtn`）。
2. **问钟/问答步能成功**，且 N2/N3 不再默认塞 `endpoint.present`。
3. **窗帘不再 TTS**，与缺图投屏一样空 plan + 可读 msg。
4. **整单不收口**：多单步已全部 status=2，detail 仍 `running`，无顶层 `presentation`。
5. **投屏** display.photo 失败 msg 为 Cast HTTP 503 / wait 15s。
6. **放歌** 仍空 plan；看书仍补拍；看人仍用 `vision.ask`。

不结案。

对照口径：问钟应 `clock.now` 且可读时刻出现；问答应 `query.content` 且有 `answer_text`；拍照应 `camera.capture`；投电视应 `display.*`；放歌应 `music.play`；无能力应干净失败且不要硬套 speak；失败有可读 `msg`；Brain 顶层 `presentation`（执行结果 ≠ 用户可见结果）；物流应到 `succeeded`/`failed`，不得在观察窗停在 `intent_parsed` / `intent_dispatched` / `running`。

---

## 2026-08-18 N1–N20

| ID | 指令 | intent | plan | 观察窗终态 | 事后 GET | 对照 |
|----|------|--------|------|------------|----------|------|
| N1 | 现在几点了 | 5 | clock.now → endpoint.present | 91s 停 `intent_parsed` | **succeeded**；`time_text` 在 step_outputs；无顶层 presentation | 部分：能力对，物流晚于观察窗；仍派 present |
| N2 | 用语音告诉我现在几点了 | 6 | clock.now → endpoint.present | succeeded 9s | 有 `time_text`；present 产出 channel=iphone text | 部分：时刻对；未说 iPhone 却 channel=iphone；无顶层 presentation |
| N3 | 用语音说：你好，这是TTS测试 | 7 | notify.speak → endpoint.present | failed | speak status=2；present status=3 msg=context 无可呈现 | 不符合：纯提醒不应再派 present 把整单打失败 |
| N4 | 一加一等于几 | 8 | query.content → endpoint.present | succeeded 77s | answer_text=一加一等于二。 | 部分：问答对；无顶层 presentation |
| N5 | 晋字一共几画 | 9 | query → present | 120s 仍 **running**（query status=1） | — | 不符合：超时无终态 |
| N6 | 我家里那只猫叫什么名字 | 10 | query → present | 122s 停 **intent_dispatched** | — | 不符合 |
| N7 | 客厅现在适合看书吗，用语音告诉我 | 11 | query.content → notify.speak | succeeded 89s | answer 为不知道（无客厅实况） | **通过** |
| N8 | 把客厅窗帘打开 | 12 | notify.speak → endpoint.present | failed | 无窗帘能力却先 speak 成功，present 缺内容失败 | 不符合：应拒无能力，不应 TTS |
| N9 | 拍张照 | 13 | notify.speak → endpoint.present | failed | **未见 camera.capture** | 不符合 |
| N10 | 拍张照投到电视上 | 14 | 空 plan | failed 6s msg=`execution_plan 为空，无法调度` | 无 camera/display | 不符合 |
| N11 | 拍张照看看客厅有没有人，语音告诉我 | 15 | query → **vision.ask** → speak → present | failed | 无 camera；ask 缺 `$photo_url`（有 msg） | 不符合：应 capture+perceive |
| N12 | 画台灯示意图投电视 | 16 | query.content → display.photo | failed 110s | query msg=`upload failed: ... timed out` | 部分：规划对；执行上传超时 |
| N13 | 播放陈奕迅的十年 | 17 | query.content → present | 92s 停 **intent_dispatched** | 无 music.play | 不符合 |
| N14 | 投到电视上 | 18 | notify.speak | 76s 停 **intent_dispatched** | 无 display | 不符合 |
| N15 | 刚才那些照片做成轮播投电视 | 19 | 空 plan | failed 6s 空 plan 无法调度 | 有可读 msg | 部分：终态失败符合「没列表不该成功」；空 plan 而非 slideshow 失败 |
| N16 | 一分钟后用语音说：该喝水了 | 20 | notify.speak timing=**delay** | succeeded 86s | 单步 speak | **通过** |
| N17 | 用 take_photo 拍一张 | 21 | 空 plan | failed 空 plan | 未见 camera.capture | 不符合 |
| N18 | 拍张照，但是不要拍照 | 22 | query → present | failed | query msg=`refused=true but answer_text does not say 我不知道 (fix prompt)` | 部分：有终态+msg；走了 query 不是拒拍 |
| N19 | 地球到月球大约多远 | 23 | query → present | 122s 仍 **running** | — | 不符合 |
| N20 | 今天天气适合散步吗 | 24 | query → present | 122s 停 **intent_dispatched** | — | 不符合 |

`GET /api/v1/intent/{id}` 本轮均为 **200**（与此前生产 404 不同）。detail 与 path **均无顶层 `presentation`**；成功问钟/算术的 presentation 对象在 `step_outputs["2"].presentation`。

### 现象（事实，不归归属）

1. **物流不稳：** N1 观察 91s 停 parsed，事后已 succeeded。N5/N19 观察结束仍 running；N6/N13/N14/N20 停 dispatched。
2. **规划仍派 `endpoint.present`** 作为末步；Participant Model 要求 Presentation 由 Brain 决议，不作为 Capability 步。纯 TTS（N3）因 present 失败整单 failed。
3. **拍照指令未派 `camera.capture`（N9/N10/N11/N17）。** 看人用了 `vision.ask` 且无图。
4. **无能力 / 缺图源** 有时空 plan 立刻 failed 且有 msg（N10/N15/N17）；有时硬套 `notify.speak`（N8/N9/N14）。
5. **放歌未派 `music.play`，派了 query（N13）。**
6. **顶层 `presentation` 未出现**；成功产出在 `step_outputs`。

不结案。
