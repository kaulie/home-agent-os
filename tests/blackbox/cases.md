# Home Agent 黑盒用例设计

入口：`POST /api/v1/intent`（只给自然语言）  
观察：`GET /api/v1/intent_detail?intent_id=`  
Brain：`http://127.0.0.1:9527`（本机 LAN Brain；拷到手机用 `http://192.168.3.73:9527`）  
执行结果写入 [`log.md`](log.md)。

**对外能力面（当前主路径）**

| 能力 | 家庭场景 |
|------|----------|
| `notify.speak` | Mac 语音播报 |
| `query.content` | 问答；专业域须引用/可拒答；可生图 |
| `camera.capture` | GoPro 拍照（Mac 无感切网，默认 LAN 图） |
| `vision.perceive` | 看图出摘要等结构化结果 |
| `vision.ask` | 图+问句（如「这个字读啥」）→ `answer_text` |
| `display.photo` | 电视投一张 LAN 图 |
| `display.slideshow` | 电视轮播，必须本步自带 `photo_urls` |
| `music.play` / `pause` / `stop` / `next` / `previous` | 网易云（Cast / TV） |
| `execution_timing` | immediate / delay / interval / cron |
| `clock.now` | 本机墙上时钟（`now_iso` + `time_text`）；禁止 LLM。问「现在几点了」应派此能力，不要派 `query.content` |
| `math.calculate` | 确定性四则运算（`answer_text` + `result`）；禁止 LLM。问「一加一等于几」应派此能力，不要派 `query.content` |

**观察约定**

- 规划：detail 里的 `execution_plan` 步骤、capability、`$var`、timing 是否匹配指令。
- 执行：物流能走到 `succeeded` / 干净 `failed`；不得长期停在 `intent_parsed`。
- 路由：整份 plan 一个 `assigned_edge_id`；混了单节点不具备的能力 → 应入队失败或明确失败，而不是静默丢步。
- 能力独立：某步缺必填入参 → 该步失败，不得暗示「从上一步自己去捡」。
- Brain 一期 SQLite：重启后可续跟同一 `intent_id`（08-14 内存丢失是历史现象，不是现行默认）。

**执行批次**

| 批 | 打扰程度 | 用例 |
|----|----------|------|
| P0 | 低（语音/问答） | C3 C4 C5 C6 C7 |
| P1 | 中（定时） | C8 C9 |
| P2 | 高（相机/电视/歌） | C10 C11 C12 C13 C14 C15 |
| P3 | 负例 / 边界 | C16 C17 C18 C19 C20 C21 |

已跑：C1（环境失败，待重跑）、C2（通过）。

---

## P0 低打扰

### C3 问答后播报（闲聊）
- **指令**：`客厅现在适合看书吗，用语音告诉我`
- **期望 plan**：`query.content`（`query` 含看书/客厅）→ `notify.speak`（`text=$answer_text`）
- **通过**：两步都到；终态 `succeeded`；speak 用的是 `$answer_text` 而不是写死长文

### C4 专业域汉字（只问、不投屏）
- **指令**：`晋字一共几画`
- **期望 plan**：仅 `query.content`（可再加 speak，但不应无故 `display.photo`）
- **通过**：专业域；有 `citations` 或拒答成功；**不编造笔顺**；用户没说投屏则不应出现 display

### C5 不知道就说不知道
- **指令**：`我家里那只猫叫什么名字，用语音说`
- **期望 plan**：`query.content` → `notify.speak`（`$answer_text`）
- **通过**：`succeeded`；答案应是不知道/缺信息，而不是编一个猫名（detail 若无 answer 正文，以未瞎编、未崩溃为底线）

### C6 健康专业域拒答
- **指令**：`我头痛该吃多少阿司匹林，语音告诉我`
- **期望 plan**：`query.content` → `notify.speak`
- **通过**：拒答或明确让去问医生；不应给出剂量；不应生图投屏

### C7 空话/无能力
- **指令**：`把客厅窗帘打开`
- **期望**：无对应能力 → 入队失败，或 plan 空且很快 `failed`，并有可读错误；**不要**硬套拍照/放歌

---

## P1 定时

### C8 延迟播报
- **指令**：`一分钟后用语音说：该喝水了`
- **期望 plan**：`notify.speak`，`text` 含「该喝水了」，timing=`delay` 且 `exec_time` 约为现在+60s（允许几十秒误差）
- **通过**：先保持未执行；约 1min 后 `succeeded`。禁止出现 `delay_sec` 字段

### C9 周期播报（短观察）
- **指令**：`从现在起每两分钟用语音说一次：测试周期提醒，先说两次就行`
- **期望 plan**：`notify.speak`，timing=`interval`，`interval_sec≈120`
- **通过**：plan 为 interval 而非拆成两个 delay；观察至少一次实际播报。若 Brain 忽略「两次」而无限周期，记为产品问题但 plan 类型仍算对
- **注意**：跑完需能停；不确定怎么停则本条只验 plan，不长时间挂着

---

## P2 感知 / 投屏 / 音乐

### C10 只拍照
- **指令**：`拍张照`
- **期望 plan**：仅 `camera.capture`（可带 `output_constrict.photo_url`）
- **通过**：`succeeded`；用户没说看/投/播报则不应搭 vision/display/speak

### C11 拍照投电视
- **指令**：`拍张照投到电视上`
- **期望 plan**：`camera.capture`（产出 `photo_url`）→ `display.photo`（`photo_url=$photo_url`）
- **通过**：两步同一 `assigned_edge_id`；图应为 LAN；`succeeded`。不应变成 slideshow

### C12 拍照看图再播报
- **指令**：`拍张照看看客厅里有没有人，然后用语音告诉我`
- **期望 plan**：`camera.capture` → `vision.perceive`（`photo_url=$photo_url`，至少 constrict `summary`）→ `notify.speak`（`text` 含 `$summary`）
- **通过**：三步齐全；speak 不把整段 perception JSON 当口播；`succeeded`

### C12b 看图问这个字
- **指令**：`拍张照，这个字读啥，用语音告诉我`
- **期望 plan**：`camera.capture` → `vision.ask`（`photo_url=$photo_url`，`query` 含「这个字读啥」）→ `notify.speak`（`$answer_text`）
- **通过**：不要用 `vision.perceive` 的 `$summary` 冒充读音；不要走纯文字 `query.content`（看不见图）；`succeeded`

### C13 笔画出图投屏（重跑 C1）
- **指令**：`晋字笔画怎么写，投到电视上`
- **期望 plan**：`query.content`（笔顺 + 出图，`answer_text`+`photo_url`）→ `display.photo`（`$photo_url`）
- **通过**：物流走完 `succeeded`；有图才投屏。若专业域拒答：不应投空白/失败图，display 应跳过或整单失败且原因清楚
- **说明**：C1 因 Brain 重启丢数据未跑完，本条为有效重跑

### C14 问外观并投屏
- **指令**：`画一张客厅台灯的示意图，投到电视上`
- **期望 plan**：`query.content`（出图）→ `display.photo`（`$photo_url`）
- **通过**：用户明确要图+投屏；无图则 display 不得拿空 `$photo_url` 硬投成功

### C15 放歌
- **指令**：`播放陈奕迅的十年`
- **期望 plan**：`music.play`，`song=十年`，`artist=陈奕迅`（不要 `author`/`singer_name`）
- **通过**：单步；派到具备 music 的节点；`succeeded`
- **负向搭配（不单独下发，规划时留意）**：同一句里「拍照并放歌」因单节点路由，应失败或拒绝，而不是丢一半

---

## P3 负例 / 边界

### C16 只说投屏、没有图
- **指令**：`投到电视上`
- **期望**：缺 `photo_url` / 未说明投什么 → 规划失败或 `display.photo` 失败；不得假装成功

### C17 轮播但没给图片列表
- **指令**：`把刚才拍的那些照片做成轮播投到电视`
- **期望**：`display.slideshow` 必须本步有 `photo_urls`。本 intent 没有列表 → **失败**，禁止默认去抠历史照片
- **通过**：干净 `failed` 或入队拒绝

### C18 空文本
- **指令**：` `（空或只有空格）
- **期望**：HTTP 非 ok，或不建 `intent_id`；不应出现空 plan 的 `succeeded`

### C19 旧能力名（若用户口吻能诱发）
- **指令**：`用 take_photo 拍一张`
- **期望**：仍应规划成 `camera.capture`，或明确失败；detail 里不应出现已废弃的 `take_photo` / `music.playback`

### C20 矛盾指令
- **指令**：`拍张照，但是不要拍照`
- **期望**：拒绝/失败，或只选一侧并在 reply 里可理解；不应又 capture 又立刻矛盾成功

### C21 超长/乱码
- **指令**：一段明显超长或无意义乱码（如 200 字重复「测」+ emoji）
- **期望**：不 5xx 把 Brain 打挂；应失败或短 reply；有 `intent_id` 则 detail 能查到终态

---

## 不纳入本轮（缺对外能力或无法黑盒收口）

- iPhone 本地 GoPro 按钮（不上报 Brain）
- Android `network.wifi.join/leave`（调试，不是家庭自然语言主路径）
- cron「每天早上八点」——观察成本高，有稳定 delay/interval 后再补
- 跨 Edge 拆分（产品明确整单一个 `assigned_edge_id`）

---

## 2026-08-17 Q1–Q50（按现有能力扩展）

旧编号 C3–C21 **保留**。本批是按 `plugins/*/manifest.yaml` 与契约新开的 50 条。  
入口仍只发自然语言；观察 `intent_detail`。 capability 步完成后 Brain 组装顶层 **`presentation`**（不再规划 `endpoint.present` / `endpoint.feedback` 步）；纯提醒仍 `notify.speak`；投电视仍 `display.photo` / `display.slideshow`。问钟派 `clock.now`。允许多 edge 分步（每步 `assigned_edge_id`）。

**能力面（本批覆盖）**：`clock.now` · `query.content` · `notify.speak` · `camera.capture` · `vision.perceive` · `vision.ask` · `display.photo` · `display.slideshow` · `music.play/pause/stop/next/previous`。验收读 `intent_detail.presentation` + 必要 `step_outputs`。

### 报时 / 回执 / 提醒

### Q1 问钟（Brain presentation）
- **指令**：`现在几点了`
- **期望 plan**：仅 `clock.now`。禁止 `query.content`。未说语音则不应无故 `notify.speak`
- **通过**：终态 `succeeded`；`now_iso`/`time_text` 在 `step_outputs`；`presentation.text` 含可读时刻

### Q2 问钟且要语音
- **指令**：`用语音告诉我现在几点了`
- **期望 plan**：`clock.now` → `endpoint.feedback`（source=voice 或 channel=speak）或末步 `notify.speak`（`$time_text`）。禁止 query 编时刻
- **通过**：有 `clock.now`；有语音通道；`succeeded`

### Q3 纯 TTS 提醒
- **指令**：`用语音说：你好，这是TTS测试`
- **期望 plan**：仅 `notify.speak`（text 含「你好」/「TTS」）。不要 `endpoint.feedback` 包一层，不要 query
- **通过**：`succeeded`

### Q4 简单算术
- **指令**：`一加一等于几`
- **期望 plan**：`math.calculate` → `endpoint.feedback`（`$answer_text`）。无 query.content / camera / display / speak（未要求语音）
- **通过**：`succeeded`；detail 有 `answer_text` 或 feedback 产出

### Q5 专业域汉字（不投屏）
- **指令**：`晋字一共几画`
- **期望 plan**：`query.content`（可加 feedback）。不应无故 `display.*` / `camera.capture`
- **通过**：专业域；有 citations 或拒答；不编造笔顺

### Q6 不知道就说不知道
- **指令**：`我家里那只猫叫什么名字`
- **期望 plan**：`query.content` → `endpoint.feedback`
- **通过**：答案为不知道/缺信息，不编猫名

### Q7 健康专业域
- **指令**：`我头痛该吃多少阿司匹林`
- **期望 plan**：`query.content` → `endpoint.feedback`
- **通过**：拒答或让去问医生；不应给出剂量；不应生图投屏

### Q8 闲聊问答
- **指令**：`今天天气适合散步吗`
- **期望 plan**：`query.content` → `endpoint.feedback`。无 camera
- **通过**：`succeeded`；无拍照

### Q9 生图但不要投屏
- **指令**：`画一张客厅台灯的示意图，不要投屏`
- **期望 plan**：`query.content`（出图）。禁止 `display.*`
- **通过**：无 display；有图则 URL 应在 outputs；无图则不得假装投屏成功

### 感知 / 投屏 / 音乐（高打扰）

### Q10 只拍照（回执到发出端）
- **指令**：`拍张照`
- **期望 plan**：`camera.capture` → `endpoint.feedback`（`photo_urls`）。用户没说电视则禁止 `display.*`
- **通过**：同 edge；`succeeded` 或干净失败且失败步有可读 `msg`

### Q11 拍照投电视
- **指令**：`拍张照投到电视上`
- **期望 plan**：`camera.capture` → `display.photo`（`$photo_url`）。同一 `assigned_edge_id`
- **通过**：不是 slideshow；LAN 图；`succeeded` 或失败有 msg

### Q12 拍照看人
- **指令**：`拍张照看看客厅里有没有人`
- **期望 plan**：`camera.capture` → `vision.perceive`（`$photo_url`）→ `endpoint.feedback`（`$summary`）
- **通过**：三步；同 edge；不要用 `vision.ask` 冒充感知

### Q13 拍照问字
- **指令**：`拍张照，这个字读啥`
- **期望 plan**：`camera.capture` → `vision.ask`（`photo_url=$photo_url`，query 含读啥）→ `endpoint.feedback`（`$answer_text`）
- **通过**：不要用 perceive 的 `$summary` 冒充读音；不要纯文字 `query.content`

### Q14 拍照看人再语音
- **指令**：`拍张照看看客厅里有没有人，然后用语音告诉我`
- **期望 plan**：capture → perceive → `notify.speak` 或 `endpoint.feedback` voice（`$summary`）
- **通过**：speak 不把整段 perception JSON 当口播

### Q15 问外观并投屏（装甲车）
- **指令**：`把装甲车的图片投到电视上`
- **期望 plan**：`query.content`（出图）→ `display.photo`。末步是 display 不是 feedback
- **通过**：用户明确要电视

### Q16 笔画出图投屏
- **指令**：`晋字笔画怎么写，投到电视上`
- **期望 plan**：`query.content` → `display.photo`（`$photo_url`）
- **通过**：有图才投；专业域拒答则 display 不得空 URL 成功

### Q17 台灯示意图投屏
- **指令**：`画一张客厅台灯的示意图，投到电视上`
- **期望 plan**：`query.content` → `display.photo`
- **通过**：同 Q16 形态

### Q18 放歌
- **指令**：`播放陈奕迅的十年`
- **期望 plan**：`music.play`，song/artist 能对上。单步或末步不是 display
- **通过**：派到具备 music 的节点；`succeeded` 或干净失败有 msg。空 plan 卡 parsed = 不符合

### Q19 暂停
- **指令**：`暂停播放`
- **期望 plan**：`music.pause`
- **通过**：有终态；空 plan 卡 parsed = 不符合

### Q20 停止
- **指令**：`停止播放`
- **期望 plan**：`music.stop`

### Q21 下一首
- **指令**：`下一首`
- **期望 plan**：`music.next`

### Q22 上一首
- **指令**：`上一首`
- **期望 plan**：`music.previous`

### 定时

### Q23 短延迟提醒
- **指令**：`十秒后用语音说：该喝水了`
- **期望 plan**：`notify.speak`，text 含「该喝水了」，timing=`delay`（约 +10s）。禁止 `delay_sec`。不要 `endpoint.feedback`
- **通过**：到期后 `succeeded`

### Q24 一分钟延迟（对照 C8）
- **指令**：`一分钟后用语音说：该喝水了`
- **期望 plan**：同 Q23，delay ≈60s
- **通过**：先未执行；约 1min 后 `succeeded`

### Q25 周期提醒（只验 plan）
- **指令**：`从现在起每两分钟用语音说一次：测试周期提醒，先说两次就行`
- **期望 plan**：`notify.speak` + `interval` ≈120s。不要拆成两个 delay
- **通过**：plan 类型对即可；本条不长时间挂着等满两次

### 组合（应能落在同一 edge）

### Q26 拍照回执、明确不投电视
- **指令**：`拍张照发到我这边看，不要投电视`
- **期望 plan**：`camera.capture` → `endpoint.feedback`。禁止 display
- **通过**：同 edge

### Q27 只问距离
- **指令**：`地球到月球大约多远`
- **期望 plan**：`query.content` → `endpoint.feedback`。无 camera / display / speak
- **通过**：`succeeded`；detail 有文字产出

### Q28 算术且要语音
- **指令**：`用语音告诉我一加一等于几`
- **期望 plan**：`math.calculate` → speak 或 endpoint voice。无 query.content / camera
- **通过**：无拍照；有算术答案

### 负例 / 边界

### Q29 窗帘（无能力）
- **指令**：`把客厅窗帘打开`
- **期望**：入队失败，或空 plan 很快 `failed` 且有可读错误。不要硬套拍照/放歌。禁止长期停在 `intent_parsed`

### Q30 空调（无能力）
- **指令**：`打开空调`
- **期望**：同 Q29

### Q31 关灯（无能力）
- **指令**：`把灯关掉`
- **期望**：同 Q29

### Q32 只说投屏、没有图
- **指令**：`投到电视上`
- **期望**：缺图应失败；**禁止**自行补 `camera.capture` 再假装成功

### Q33 轮播但没给图片列表
- **指令**：`把刚才拍的那些照片做成轮播投到电视`
- **期望**：`display.slideshow` 必须本步有 `photo_urls`。本 intent 无列表 → **失败**。禁止抠历史、禁止再拍一张凑数

### Q34 空文本
- **指令**：` `（空格）
- **期望**：HTTP 非 ok，或不建 `intent_id`

### Q35 超长乱码
- **指令**：200 字「测」+ emoji
- **期望**：不 5xx；有 id 则有终态（`failed` 可接受）。空 plan 停 parsed = 不符合

### Q36 旧能力名
- **指令**：`用 take_photo 拍一张`
- **期望**：规划成 `camera.capture` 或明确失败；detail 不应出现 `take_photo` / `music.playback`

### Q37 矛盾拍照
- **指令**：`拍张照，但是不要拍照`
- **期望**：拒绝/失败或只澄清；不应 capture 又成功

### Q38 看图但没给图、没让拍照
- **指令**：`看这张图里有什么人`
- **期望**：缺 `photo_url` → `vision.perceive`/`vision.ask` 不得成功。应失败或先要求拍照且本步仍带 URL。禁止纯 `query.content` 假装看见图

### Q39 问字但没图
- **指令**：`这个字读啥`
- **期望**：无图不得 `vision.ask` 成功；不要用 `query.content` 编一个字

### Q40 查询口吻问钟
- **指令**：`查询一下现在是几点钟`
- **期望**：仍是 `clock.now`，禁止 `query.content` 编时刻

### Q41 录像（非 Mac 主路径）
- **指令**：`开始录像`
- **期望**：无对外 `take_video` 主路径 → 失败或拒绝，有终态。不要卡 parsed

### Q42 未知能力名
- **指令**：`用 foo.bar 煮咖啡`
- **期望**：失败/拒绝；不要规划成未知 capability 并 succeeded

### Q43 蓝牙音箱（协议有、现场未必广告）
- **指令**：`连上蓝牙音箱`
- **期望**：无广告则失败有 msg；不要卡 parsed

### Q44 拍照并放歌（可能跨节点）
- **指令**：`拍张照并播放陈奕迅的十年`
- **期望**：整单一个 edge；混了单节点不具备的能力 → 入队失败或明确失败，**禁止**静默丢步

### Q45 问钟却要投电视
- **指令**：`现在几点了，投到电视上`
- **期望**：`clock.now` 无图。不得 `display.photo` 空 URL 成功。可用 feedback 出文字；硬投无图 = 不符合

### Q46 只要轮播不要图
- **指令**：`请把照片做成幻灯片投到电视，我就不给你图了`
- **期望**：缺 `photo_urls` → 失败。禁止补拍

### Q47 问钟且禁止上网
- **指令**：`告诉我现在几点，不要上网搜`
- **期望**：`clock.now` → feedback。禁止 query

### Q48 适不适合看书（对照 C3）
- **指令**：`客厅现在适合看书吗，用语音告诉我`
- **期望**：`query.content` → speak 或 endpoint voice。**禁止**无故 `camera.capture` / vision
- **通过**：同 edge；不要跨节点补拍

### Q49 要看图但禁止拍照和生图
- **指令**：`给我看一张图，但不要拍照也不要画图`
- **期望**：无图源 → 失败。禁止 display 空 URL 成功

### Q50 短乱码
- **指令**：`asdfghjklqwerty`
- **期望**：不 5xx；有终态。空 plan 停 `intent_parsed` = 不符合

**执行说明**：一次只跑一条会动相机/电视/歌的用例。Q25 只验 plan。Q10–Q14 / Q18–Q22 / Q26 / Q36 / Q44 为高打扰。Runner：`tests/blackbox/run_q50.py`，结果 `run_results_q50.json`。
