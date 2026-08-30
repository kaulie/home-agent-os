# 黑盒执行记录

旧轮次结果已于 2026-08-18 清空。本文件只记 N1–N20。

Brain（下轮）：`http://127.0.0.1:9527`（本机 LAN Brain。下列历史条目当时打的是云 `http://115.190.153.53:9527`）  
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

---

## 2026-08-19 15:32 再复测（intent 130–149）

`GET /health` 200 `jobs=129` `pending_intents=1` `registered=5`。无 `participant_id` 的 runner 先全部 400，见 [`run_results_n20_round4_nopid.json`](run_results_n20_round4_nopid.json)。带测试 issuer `edge-node-CiqVl9ZB` 后 POST N1–N20。快照 [`run_results_n20_round4.json`](run_results_n20_round4.json)。边：执行步均为 `edge-node-9tkgMTtn`。home-server `x0OjfixA` 当时 offline。Chromecast `ZeECgaki` `schedule_eligible=false`。`GET /intent/{id}` 本轮未逐条打；`intent_detail` 均为 200。

### 门闸（无 intent id）
- POST `{"text":"现在几点了","source":"text"}` → 400 `participant_id is required; register and heartbeat first`
- POST `participant_id=no-such-node` → 401 `unknown participant_id; register first`
- POST `participant_id=edge-node-9tkgMTtn` → 403 `participant did not declare intent_source`
- POST `participant_id=edge-node-JzvEe287` → 403 `participant heartbeat required`

### N1 intent_id=130 — 现在几点了
- 9s succeeded；clock.now status=2；`time_text=2026年8月19日 15:41:18（CST，UTC+08:00）`
- presentation `{"type":"text","from":"time_text","text":"…15:41:18…","channel":"iphone","endpoint":"edge-node-CiqVl9ZB"}`；无 image_url / asset_ref

### N2 intent_id=131 — 用语音告诉我现在几点了
- 15s succeeded；仅 clock.now status=2；`time_text=15:41:33`
- presentation type=audio from=time_text 同时刻；无 notify.speak；无 pending_delivery 字段

### N3 intent_id=132 — 用语音说：你好，这是TTS测试
- 21s succeeded；notify.speak status=2
- presentation type=audio from=state endpoint=`""`

### N4 intent_id=133 — 一加一等于几
- 82s succeeded；query `answer_text=在常规十进制数学运算中，一加一等于二。`
- presentation type=text from=answer_text

### N5 intent_id=134 — 晋字一共几画
- 52s succeeded；answer_text 10画+汉典；outputs.asset_ref=`asset_1eb63678d328788804064dec`
- 顶层 presentation type=text，无 image_url、无 asset_ref

### N6 intent_id=135 — 我家里那只猫叫什么名字
- 46s succeeded；诚实不知道

### N7 intent_id=136 — 客厅现在适合看书吗，用语音告诉我
- 12s failed；空 plan
- msg=`需要先拍摄或获取客厅当前画面的 AssetRef，才能用视觉能力判断光线、环境是否适合看书；当前没有任何拍照/取图能力。`
- 无 query.content / camera.capture

### N8 intent_id=137 — 把客厅窗帘打开
- 9s failed；空 plan；msg=无窗帘能力；未派 speak

### N9 intent_id=138 — 拍张照
- 28s failed；空 plan；msg=无拍照能力；无 camera.capture

### N10 intent_id=139 — 拍张照投到电视上
- 9s failed；空 plan；msg=无拍照能力；无 camera / display

### N11 intent_id=140 — 拍张照看看客厅里有没有人，然后用语音告诉我
- 12s failed；空 plan；msg=无拍照能力；无 capture / perceive / speak

### N12 intent_id=141 — 画一张客厅台灯的示意图，投到电视上
- 52s succeeded；query.content status=2 + display.photo status=2
- outputs.1 asset_ref=`asset_8505a848fca15b2cf44bb2b9`
- presentation `{"type":"image","from":"asset_ref","asset_ref":{"asset_id":"asset_8505a848fca15b2cf44bb2b9","type":"image","mime_type":"image/png"},"channel":"iphone","endpoint":"edge-node-CiqVl9ZB"}`；无 image_url

### N13 intent_id=142 — 播放陈奕迅的十年
- 9s failed；空 plan；msg=`当前 Available Capabilities 中没有可调用的 music.play 能力`
- 未停 intent_parsed；无 music.play 步

### N14 intent_id=143 — 投到电视上
- 15s failed；空 plan；msg=缺少待投屏内容 / asset_ref

### N15 intent_id=144 — 把刚才拍的那些照片做成轮播投到电视
- 12s failed；空 plan；msg=无法列出最近照片给 slideshow

### N16 intent_id=145 — 一分钟后用语音说：该喝水了
- 64s succeeded；notify.speak timing=delay status=2
- presentation type=audio from=state endpoint=`""`

### N17 intent_id=146 — 用 take_photo 拍一张
- 9s failed；空 plan；msg=无拍照能力；无 camera.capture

### N18 intent_id=147 — 拍张照，但是不要拍照
- 9s failed；空 plan；msg=无拍照能力；未拍照

### N19 intent_id=148 — 地球到月球大约多远
- 观察窗 101s failed；query.content status=3 msg=`ark responses.create failed: Request timed out.` 含 request_id
- 事后 GET：顶层 status=succeeded；步仍 status=3；step_outputs.1 空；presentation type=text from=answer_text 无 text 字段

### N20 intent_id=149 — 今天天气适合散步吗
- 67s succeeded；诚实不知道缺实时天气；presentation type=text

不结案。

---

## 2026-08-26 C10c — 拍照给我看（composite，对标 intent 1450）

- **时间**：2026-08-26 上午
- **指令**：`拍张照片我看一下`
- **下发**：本轮 **未** 对 LAN `http://127.0.0.1:9527` POST（P2 会动相机；当时 Brain 进程未带本改动；`GET /api/v1/capabilities` 无 `camera.capture` / `camera.capture_and_upload`）
- **自动化**：Flask 单测代替现场快门，见 [`capture_and_upload.md`](capture_and_upload.md)
  - mock LLM 两步 capture@android + upload@iphone → 入队 **仅一步** `camera.capture_and_upload` `assigned_edge_id=android-1`
  - iPhone capture unavailable 时不得再拆边
  - 无 composite 广告且分边 → 入队失败（可读 msg）
  - 独立「传到云上」仍可只派 `asset.upload`
- **规划**：单测符合 C10c 期望 plan；现场物流待 Runtime 心跳带上三条 cap 后再 POST
- **结论**：Brain sanitize/选边/catalog **已验收（单测）**；现场终态 `presentation.type=image` + `asset_id` **未跑快门，不结案**

---

## 2026-08-28 VL1 — video.live_stream 含音频（@ui #91 / sha ce42234）

- **前置**：Mac ingest `http://127.0.0.1:8790` 200；artifact `video_stream_258b158e.ts`（3889156 B，~12.5s，23:43）
- **bytes_received**：停流后 stream 不在 registry；未现场 3s×poll；文件体积表明开流期间有写入
- **ffprobe TS**：`codec_name=h264` + `codec_name=aac`（PID 0x101）；aac `channels=0` `sample_rate=0`；警告 *no TS found at start*
- **TS 包计数**：PID 0x100 → 20661 包；**PID 0x101 → 0 包**（PMT 有 audio，payload 未 mux）
- **mp4**：`ffmpeg -c copy` → video 3673 KiB，**audio 0 KiB**；mp4 无 audio stream
- **结论**：**失败**（非 VL1 通过）；需 `@ui` 修 AAC 帧写入 mux 后重测。快照 [`run_results_video_live_vl1.json`](run_results_video_live_vl1.json)

---

## 2026-08-29 VL1 复测（#109 / deploy a174070；最新 fix e4502a9）

- **云部署**：#109 确认 a174070 仅 iOS，无 `home_brain` 变更 → 未 rsync（与 VL1 无关）
- **现场**：00:28 轮询 2min，无 23:45 后新 `.ts`；`bytes_received` 无增长
- **artifact**：仍 `video_stream_68f21751.ts`（33.7MB，~104s，**23:45 修复前**）
- **ffprobe / 包计数**：h264 OK（178930 包 @0x100）；**PID 0x101 → 0 包**；mp4 audio 0 KiB
- **结论**：**失败** — 无法验收 a174070/5ad4b99/e4502a9 修复；需新包 **视频+音频** Start/Stop 后再测

---

## 2026-08-29 C15 — music.play（@capability #178 / sha d426dab）

- **指令**：`播放陈奕迅的十年`
- **下发**：LAN `POST /api/v1/intent` → intent **364**（participant `edge-node-blackbox-q01`）
- **plan**：单步 `music.play` → `edge-node-SJZ1SMuX`（netease.music）；`song=十年` `artist=陈奕迅` `appliance=网易云音乐`
- **物流**：received → parsed（~10s）→ scheduled → dispatched → running → **succeeded** @~27s；步 status=2
- **现场播音**：API 未证实（执行未证实）
- **结论**：**通过** C15 P2。快照 [`run_results_music_play_c15.json`](run_results_music_play_c15.json)

---

## 2026-08-29 C15 复验 — music.play（#184 / sha 13ec60e）

- **指令**：`播放陈奕迅的十年`
- **下发**：intent **365**；plan 单步 `music.play` → `edge-node-SJZ1SMuX`；`song=十年` `artist=陈奕迅`
- **物流**：parsed → scheduled → dispatched → running → **succeeded** @~36s；步 status=2
- **备注**：Mac Edge 仍未广告 `netease.music`（Brain prefer-Mac 未提交/未部署）；选边仍 Chromecast
- **现场播音**：执行未证实
- **结论**：**通过**（Chromecast 旧选边；无独立快照）

---

## 2026-08-29 C15 — music.play prefer-Mac（#188 / sha b088131）

- **指令**：`播放陈奕迅的十年` → intent **366**
- **plan**：`music.play` → **edge-node-SJZ1SMuX**（Chromecast，非 Mac）
- **物流**：**succeeded** @~36s；步 status=2
- **b088131 验收项**：prefer-Mac **未达** — Mac Edge（`IAtuhLSy`）未广告 `netease.music`；云 Brain `b088131` deploy 未见 `[release] stage=deployed`
- **结论**：**失败**（相对 b088131 选边目标）；C15 执行面仍 succeeded。366 无独立快照

---

## 2026-08-29 C15 — LAN prefer-Mac（#193 / Mac Edge 重启）

- **指令**：`播放陈奕迅的十年` → intent **368**（LAN `127.0.0.1:9527`）
- **选边**：`music.play` → **edge-node-IAtuhLSy**（客厅 · Mac Edge）✓
- **入参**：`song=十年` `artist=陈奕迅`
- **物流**：**succeeded** @~69s；步 status=2
- **现场播音**：#207 @boss 确认出声（PID 66842）
- **结论**：**通过** prefer-Mac + C15。canonical 快照见 #205 intent 371

---

## 2026-08-29 C15 prefer-Mac 正式复验（#200 / b088131 + 13ec60e）

- **指令**：`播放陈奕迅的十年` → intent **370**
- **选边**：**edge-node-IAtuhLSy**（非 SJZ1SMuX）✓
- **物流**：succeeded @~48s；步 status=2
- **结论**：**通过**。canonical 快照见 #205 intent 371

---

## 2026-08-29 C15 prefer-Mac 新跑（#205 / 勿复用 366）

- **指令**：`播放陈奕迅的十年` → intent **371**
- **选边**：**edge-node-IAtuhLSy**（非 SJZ1SMuX）✓
- **物流**：succeeded；步 status=2
- **结论**：**通过**。快照 [`run_results_music_play_c15_b088131.json`](run_results_music_play_c15_b088131.json)（覆盖 366 失败快照）
- **现场播音**：#207 @boss 确认 intent 368/369 本机网易云已出声（PID 66842）

---

## 2026-08-29 music.cache + issue#9 双 Brain（#309 / sha 89b7535）

- **范围**：4G 云建单 `music.cache` + 双 Brain 状态回写（#309）
- **云 Brain**：`115.190.153.53:9527` **不可达**（curl http_code=000）；**未验收** 4G 路径
- **89b7535 探针**：LAN `intent_detail?intent_id=999999999` 仍 200+`err_msg`（非 404）→ Brain/Mac 侧 fix **未部署/未重启**
- **LAN 烟测**：`下载刘德华的歌5首` → intent **399**；`music.cache` → **IAtuhLSy**；succeeded ~36s；步 status=2
- **结论**：**失败**（相对 #309 云 4G + dual-brain 验收）；LAN music.cache 执行面通过。快照 [`run_results_music_cache_lan_smoke.json`](run_results_music_cache_lan_smoke.json)

---

## 2026-08-29 music.cache 云 Brain 复测（#318 / sha 89b7535，deploy 8bd2ba6）

- **云**：`115.190.153.53:9527` health=200；缺 intent `intent_detail` → **404** ✓
- **指令**：`下载刘德华的歌5首` → cloud intent **1516**（`intent_origin=cloud`）
- **plan**：`music.cache` → **edge-node-IAtuhLSy**；succeeded ~36s；步 status=2
- **双 Brain 回写**：云侧 `intent_detail` 见终态 succeeded（非卡 dispatched）
- **结论**：**通过**。快照 [`run_results_music_cache_cloud.json`](run_results_music_cache_cloud.json)
- **#321 核对**：cloud intent 1516 在云 `succeeded` step=2；LAN 同 id → **404**（step_status 落 origin Brain）

---

## 2026-08-29 music.cache 云 dual-brain 新跑（#323 / sha 8bd2ba6）

- **前置**：云+LAN 缺 intent → **404** ✓
- **指令**：`下载刘德华的歌5首` → cloud intent **1517**（`origin=cloud`）
- **plan**：`music.cache` → **IAtuhLSy**；succeeded ~36s；步 status=2
- **dual-brain**：云 detail succeeded；LAN 同 id → **404**
- **结论**：**通过**。快照 [`run_results_music_cache_cloud.json`](run_results_music_cache_cloud.json)

---

## 2026-08-30 Dev cloud_calls usage API（#9c17848 / dba 026）

- **范围**：`GET /api/v1/admin/dev_task/usage?period=day` → `usage.cloud_calls.{period,all_time}`
- **前置**：LAN Brain 原进程无 `cloud_calls` 字段；本机 `db.init_db()`（026）+ 重启 `home_brain.py` 后验收
- **C1 schema**：HTTP 200；每行 `{service_id,label,count,ok,fail}`；7 个 v1 id 均在 period（含 count=0）
- **C2 heartbeat**：`edge-node-blackbox-cloud-usage` POST `cloud_usage_delta` `[{ark.vision, ok:1}]` → period `ark.vision` count **0→1**
- **结论**：**通过**。脚本 [`run_cloud_usage.py`](run_cloud_usage.py)；快照 [`run_results_cloud_usage.json`](run_results_cloud_usage.json)

