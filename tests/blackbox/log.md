# 黑盒执行记录

旧轮次结果已于 2026-08-18 清空。本文件只记 N1–N20。

Brain：`http://115.190.153.53:9527`  
`POST /api/v1/intent` `source=text`，不带 `edge_id`。  
原始 [`run_results_n20.json`](run_results_n20.json)。边均为 `edge-node-9tkgMTtn`（空 plan 单除外）。

---

## 2026-08-18 N1–N20

### N1 intent_id=5 — 现在几点了
- 观察窗 91s：`intent_parsed`，plan=`clock.now`→`endpoint.present`，步 status 空
- 事后 GET：`succeeded`；outputs.1 `time_text=2026年8月18日 17:33:04（CST）`；outputs.2 presentation type=text channel=iphone；无顶层 presentation
- GET `/intent/5`：200

### N2 intent_id=6 — 用语音告诉我现在几点了
- 9s `succeeded`；clock status=2 → present status=2
- outputs.1 `time_text=2026年8月18日 17:33:13`；outputs.2 presentation text 同时刻 channel=iphone
- GET `/intent/6`：200

### N3 intent_id=7 — 用语音说：你好，这是TTS测试
- speak status=2；present status=3 msg=`context 里没有可呈现的 text / time_text / answer_text / summary / 图 / 视频`
- 终态 failed @21s

### N4 intent_id=8 — 一加一等于几
- query status=2 `answer_text=一加一等于二。`；present status=2 text=`一加一等于2。`
- succeeded @77s

### N5 intent_id=9 — 晋字一共几画
- 120s 仍 running；query status=1；present 未跑

### N6 intent_id=10 — 我家里那只猫叫什么名字
- 122s 停 intent_dispatched；步 status 空

### N7 intent_id=11 — 客厅现在适合看书吗，用语音告诉我
- query→speak 均 status=2；answer 为不知道（无客厅实况）
- succeeded @89s；无 endpoint.present

### N8 intent_id=12 — 把客厅窗帘打开
- speak status=2；present status=3 同 N3 缺可呈现内容
- failed @24s；无窗帘类能力

### N9 intent_id=13 — 拍张照
- 与 N8 相同 speak→present failed；**无 camera.capture**

### N10 intent_id=14 — 拍张照投到电视上
- 空 plan；failed @6s msg=`execution_plan 为空，无法调度`

### N11 intent_id=15 — 拍张照看看客厅里有没有人，然后用语音告诉我
- query status=2；vision.ask status=3 msg=`缺少上下文变量 $photo_url，无法执行`；无 camera
- failed @28s

### N12 intent_id=16 — 画一张客厅台灯的示意图，投到电视上
- query.content → display.photo
- query status=3 msg=`upload failed: <urlopen error [Errno 60] Operation timed out>`
- failed @110s

### N13 intent_id=17 — 播放陈奕迅的十年
- plan=query→present；无 music.play
- 92s 停 intent_dispatched

### N14 intent_id=18 — 投到电视上
- 仅 notify.speak；76s 停 intent_dispatched

### N15 intent_id=19 — 把刚才拍的那些照片做成轮播投到电视
- 空 plan；failed @6s msg=`execution_plan 为空，无法调度`

### N16 intent_id=20 — 一分钟后用语音说：该喝水了
- notify.speak timing=delay；succeeded @86s；speak status=2

### N17 intent_id=21 — 用 take_photo 拍一张
- 空 plan；failed @6s 空 plan 无法调度；无 camera.capture

### N18 intent_id=22 — 拍张照，但是不要拍照
- query status=3 msg=`refused=true but answer_text does not say 我不知道 (fix prompt)`
- failed @52s

### N19 intent_id=23 — 地球到月球大约多远
- 122s 仍 running；query status=1

### N20 intent_id=24 — 今天天气适合散步吗
- 122s 停 intent_dispatched；query→present 未开始执行

---

## 2026-08-18 21:44 环境恢复重测（intent 25–52）

事后 GET。`GET /intent/{id}` 均为 200。边：camera=`edge-node-x0OjfixA`，其余常为 `edge-node-9tkgMTtn`。

### N1 id=25 现在几点了
- clock.now status=2，`time_text=2026年8月18日 21:44:01`；整单 **running**；无顶层 presentation

### N2 id=26 用语音告诉我现在几点了
- clock.now + notify.speak 均 status=2；`time_text=21:45:35`；running

### N3 id=27 TTS
- notify.speak status=2；无 present；running

### N4 id=28 一加一
- query status=2 `answer_text=一加一等于二。`；running

### N5 id=30 晋字几画
- query status=2，10画 + 汉典 citations + LAN 图；running

### N6 id=31 猫叫什么
- query status=2，诚实不知道；running

### N7 id=32 客厅适合看书吗
- camera.capture（x0OjfixA status=2 有图）→ vision.perceive（status=2）→ notify.speak（status=2）；running

### N8 id=33 打开窗帘
- 空 plan；failed；msg=`execution_plan 为空，无法调度`

### N9 id=34 拍张照
- camera.capture status=2，`photo_url=http://192.168.3.65:8080/2df0f9a2_...`；running

### N10 id=36 拍张照投到电视上
- capture status=2；display.photo status=3 msg=`cast service HTTP 503` / wait 15s；failed

### N11 id=38 拍张照看有没有人
- capture + vision.ask + speak 均 status=2；running

### N12 id=39 画台灯投电视
- query status=2 已出图；display.photo status=3 Cast 503；failed

### N13 id=40 播放十年
- 空 plan；failed；msg=空 plan 无法调度

### N14 id=41 投到电视上
- 空 plan；failed

### N15 id=42 轮播
- 空 plan；failed

### N16 id=43 一分钟后该喝水了
- notify.speak timing=delay status=2；running

### N17 id=45 take_photo
- camera.capture status=2 有图；running

### N18 id=47 拍张照但是不要拍照
- notify.speak status=2；running

### N19 id=49 地球到月球
- query status=3 msg=`ark responses.create failed: Request timed out.`；整单仍 running

### N20 id=52 天气适合散步吗
- query 步 status 空；整单 intent_dispatched

---

## 2026-08-18 23:00 再测一轮（intent 56 + 57–79）

`GET /health` 200。事前 GET 25–52 已全终态（succeeded 19 / failed 9）。本轮仍重新 POST。原始 [`run_results_n20_round3.json`](run_results_n20_round3.json)。边：camera=`edge-node-x0OjfixA`，其余常 `edge-node-9tkgMTtn`。`GET /intent/{id}` 均为 200。

### P intent_id=56 — 拍张照片我看一下（source=voice，无 participant_id）
- POST 200；64s `succeeded`；plan 仅 `camera.capture` status=2
- 观察窗顶层 presentation：`{"type":"image","channel":"iphone","endpoint":"edge-node-JzvEe287","image_url":"http://192.168.3.65:8080/f69d2920_20260818_230023_GOPR1171.JPG"}`
- image_url 与 context `photo_url` 相同；无 display.photo / endpoint.present
- 23:22 再 GET：presentation.endpoint=`""`，其余字段仍在

### N1 intent_id=57 — 现在几点了
- 6s succeeded；clock.now status=2；presentation type=text `2026年8月18日 23:01:11（CST，UTC+08:00）` endpoint=JzvEe287

### N2 intent_id=58 — 用语音告诉我现在几点了
- 22s succeeded；clock + speak 均 2；presentation text 同时刻

### N3 intent_id=59 — 用语音说：你好，这是TTS测试
- 22s succeeded；notify.speak status=2；无顶层 presentation

### N4 intent_id=60 — 一加一等于几
- 31s succeeded；query `answer_text=一加一等于二。`；presentation type=text 同文

### N5 intent_id=61 — 晋字一共几画
- 65s succeeded；query status=2 有 answer_text；presentation type=image（query png）

### N6 intent_id=62 — 我家里那只猫叫什么名字
- 31s succeeded；answer 诚实不知道；presentation type=text

### N7 intent_id=63 — 客厅现在适合看书吗，用语音告诉我
- 62s succeeded；camera.capture（x0OjfixA）→ vision.ask → notify.speak 均 2；presentation type=image

### N8 intent_id=64 — 把客厅窗帘打开
- 3s failed；空 plan；msg=`execution_plan 为空，无法调度`

### N9 intent_id=65 — 拍张照
- 136s succeeded；camera.capture status=2；presentation type=image LAN 图

### N10 intent_id=66 — 拍张照投到电视上
- 59s failed；capture=2；display.photo=3 msg=`cast service HTTP 503` / wait 15s；presentation type=image 仍在

### N11 intent_id=68 — 拍张照看看客厅里有没有人，然后用语音告诉我
- 102s failed；capture=2；vision.perceive=3 msg=`download image failed: timed out`；无 speak；presentation type=image endpoint=`""`

### GET intent 71 — 客厅里有几个人（非本 runner POST，source=voice）
- succeeded；camera + perceive 均 2
- presentation type=text、无 image_url、text=`客厅内一名未穿上衣的男子在远端书桌前。`、endpoint=`""`

### N12 intent_id=70 — 画一张客厅台灯的示意图，投到电视上
- 50s failed；query=2 已出图；display.photo=3 Cast 503；presentation type=image endpoint=`""`

### N13 intent_id=72 — 播放陈奕迅的十年
- 240s 停 intent_parsed；plan=`music.play`，status 空，assigned_edge_id 空
- 23:21 再 GET 仍 intent_parsed

### N14 intent_id=73 — 投到电视上
- 7s failed；空 plan

### N15 intent_id=74 — 把刚才拍的那些照片做成轮播投到电视
- 7s failed；空 plan

### N16 intent_id=75 — 一分钟后用语音说：该喝水了
- 79s succeeded；notify.speak timing=delay status=2；无顶层 presentation

### N17 intent_id=76 — 用 take_photo 拍一张
- 63s succeeded；camera.capture status=2 有图；presentation type=image endpoint=`""`

### N18 intent_id=77 — 拍张照，但是不要拍照
- 6s failed；空 plan

### N19 intent_id=78 — 地球到月球大约多远
- 100s failed；query status=3 msg=`ark responses.create failed: Request timed out.` 含 request_id

### N20 intent_id=79 — 今天天气适合散步吗
- 102s succeeded；query 诚实不知道缺实时天气；presentation type=text endpoint=`""`

---

## 2026-08-19 09:01 011 assets/asset_grants 黑盒（dba 请验收，chat id 17）

范围：无新对外路由。只验 `POST /api/v1/intent` 后 `GET intent_detail` 仍 200。生产需跑完 011（version=11）。不结案。

Brain：`http://115.190.153.53:9527`  
墙钟：2026-08-19 09:01 CST（UTC+8）

### GET `/health` — 200
```json
{"app":"brain","db":"/root/chat-gateway/data/brain.sqlite3","jobs":100,"ok":true,"pending_intents":1,"registered":5}
```
- 无 `schema_version` / `db_version` / `version` 字段；**health 看不到 version=11**。

### POST `/api/v1/intent` `{"text":"现在几点了","source":"text"}` — 200
- 不带 `execution_plan`
- body：`ok=true`，`intent_id=101`，`intent_status=intent_received`

### GET `/api/v1/intent_detail?intent_id=101` — 200
- 即时 GET 已有完整 body；`intent_status=succeeded`
- plan：`clock.now` step status=2，边 `edge-node-9tkgMTtn`
- 产出：`step_outputs.1.time_text=2026年8月19日 09:01:28（CST，UTC+08:00）`
- 顶层 `presentation`：type=text，text 同时刻，channel=iphone，endpoint=`""`

### GET `/api/v1/intent/101` — 200
- 与 intent_detail 同 body。

### GET `/api/v1/assets`（可选观察，非验收路由）— 404
- 与「无新对外路由」一致。

不结案。验收未证明 011 已落到生产库（health 无 version）。
