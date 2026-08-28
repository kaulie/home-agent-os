# 各能力标准回归测试流程

> **读者**：`@boss`、评审、`@quality`、`@capability`  
> **性质**：**L3 黑盒**按能力细则（标准句、plan、通过标准）；**L0–L2** 契约/单测/算法见 [`docs/capability-regression-standard.md`](../../docs/capability-regression-standard.md)  
> **用例索引**：[`cases.md`](cases.md)（含 **§7 缺口补 case**：DS1/OCR1/CAP1/CL1 等）· 执行 [`log.md`](log.md) · 环境 [`agent-brief.md`](agent-brief.md)

---

## 1. 通用回归流程（所有能力）

### 1.1 黑盒入口（`@quality`）

| 步骤 | 动作 | 通过条件 |
|------|------|----------|
| 0 | 确认 Brain URL 与 Edge `intentServerURL` **同一棵 Brain**（见 agent-brief §2 双 Brain） | `GET /health` 200；`brain_origin` 与 edge 路由一致 |
| 1 | `POST /api/v1/intent` | body：`{"text":"<自然语言>","source":"text","participant_id":"<intent_source>"}` → **200**，有 `intent_id` |
| 2 | 轮询 `GET /api/v1/intent_detail?intent_id=` | **200**；记录 `execution_plan`、物流、`step_outputs`、`presentation` |
| 3 | 可选 `GET /api/v1/intent/{id}` | 与 detail 同 body（200） |
| 4 | 写入 `log.md` + 快照 JSON | 见 agent-brief §4 材料清单 |

**禁止**：替 Brain 指定 `execution_plan`；无 `participant_id` 时不得把 400 当产品失败（门闸）。

### 1.2 四层验收口径

| 层 | 检查什么 | 不符合示例 |
|----|----------|--------------|
| **规划** | plan 里 capability、timing、`$var` 是否匹配用户话 | 问钟派 `query.content`；没说投屏却加 `display.*` |
| **路由** | 每步 `assigned_edge_id` 具备该 capability 且在线 | 混了单节点不具备的能力却静默丢步 |
| **执行** | 离开 `intent_parsed` → 终态 `succeeded`/`failed`；失败有可读 `msg` | 数分钟仍 `intent_parsed`；`failed` 但 `msg` 空 |
| **产出** | 成功步必填字段在 `step_outputs`；Brain 顶层 `presentation` 可读 | `succeeded` 却无 `answer_text`/`asset_ref`/`time_text` |

### 1.3 批次与打扰程度

| 批次 | 打扰 | 何时跑 |
|------|------|--------|
| **P0** | 低（问答/报时/寒暄） | 每次 Brain/规划器/deploy 后优先 |
| **P1** | 中（定时 delay/interval） | 动到时序逻辑后 |
| **P2** | 高（相机/电视/歌/扫描/空调） | **征得现场允许**；一次只跑一条 |
| **P3** | 负例/边界 | 改入队门闸、规划拒绝逻辑后 |

### 1.4 插件单测（`@capability`）

每个 `plugins/<id>/` 应有：

- 契约文档 `capability.md` 与 `manifest.yaml` 一致
- Edge 侧单测（如 `mac/tests/test_*.py`、iOS/Android 对应测试）
- **不替代黑盒**：单测通过 ≠ 规划/物流/路由通过

---

## 2. 按能力分类的标准流程

下列「标准句」为回归首选；可增负例句。Case ID 指向 [`cases.md`](cases.md)。

---

### 2.1 报时 · `clock.now`

| 项 | 内容 |
|----|------|
| **插件** | `clock-now` |
| **标准句** | `现在几点了`（Q1 / N1） |
| **期望 plan** | 仅 `clock.now`；**禁止** `query.content` |
| **前置** | Mac Edge 在线并广告 `clock.now` |
| **观察窗** | ≤90s |
| **通过** | 终态 `succeeded`；`step_outputs` 含 `time_text`/`now_iso`；`presentation.text` 含可读时刻 |
| **负例** | `查询一下现在是几点钟`（Q40）仍须 `clock.now` |
| **单测** | 读本机钟，无 LLM |

---

### 2.2 算术 · `math.calculate`

| 项 | 内容 |
|----|------|
| **插件** | `math-calculate` |
| **标准句** | `一加一等于几`（Q4 / N4） |
| **期望 plan** | 仅 `math.calculate`；**禁止** `query.content` |
| **通过** | `answer_text` 或 `result` 正确；`presentation` 有文本 |
| **负例** | 复杂开放问答不应派本能力 |
| **单测** | AST 白名单求值 |

---

### 2.3 问答 · `query.content`

| 项 | 内容 |
|----|------|
| **插件** | `query-content` |
| **标准句 P0** | `晋字一共几画`（C4/Q5）；`我家里那只猫叫什么名字`（C5/Q6） |
| **期望 plan** | `query.content`；用户要语音则 + `notify.speak`（`$answer_text`） |
| **观察窗** | 30–120s（生图更长） |
| **通过** | 专业域有 `citations` 或拒答；**不编造**私有事实/剂量；无图时不要无故 `display.*` |
| **负例** | 问钟/算术/寒暄不得派本能力 |
| **环境** | Ark 代理可能导致超时——记环境，不直接判产品失败 |

---

### 2.4 寒暄 · `chat.smalltalk`

| 项 | 内容 |
|----|------|
| **插件** | `chat-smalltalk` |
| **标准句** | `早啊` |
| **期望 plan** | 仅 `chat.smalltalk`；**禁止** `query.content` |
| **通过** | 步 status=2；`step_outputs.reply` + `presentation.text` 为寒暄回复（规则随机候选均可） |
| **负例** | `为什么天是蓝的` 不得派本能力 |
| **单测** | `mac/tests/test_chat_smalltalk.py` |

---

### 2.5 语音播报 · `notify.speak`

| 项 | 内容 |
|----|------|
| **插件** | Mac TTS / Edge |
| **标准句** | `用语音说：你好，这是TTS测试`（Q3 / N3） |
| **期望 plan** | 仅 `notify.speak` |
| **通过** | `succeeded`；`presentation.type=audio` 或约定 channel |
| **定时** | `一分钟后用语音说：该喝水了`（C8/Q24）→ timing=`delay`，约 +60s |
| **负例** | 无能力硬套 speak 掩盖失败 |

---

### 2.6 拍照 · `camera.capture`

| 项 | 内容 |
|----|------|
| **插件** | `gopro-camera` |
| **标准句** | `拍张照`（C10 / Q10） |
| **期望 plan** | 仅 `camera.capture`（用户没说看/投/播） |
| **前置** | GoPro 在线节点（常为 home-server 或 Android）；**P2 需允许动相机** |
| **观察窗** | ≤180s |
| **通过** | 步 status=2；产出含图（`photo_url` 或 `asset_ref`，以当轮契约为准） |
| **负例** | `用 take_photo 拍一张`（C19）应映射 `camera.capture` 或干净失败 |

---

### 2.7 拍照上传 · `camera.capture_and_upload`

| 项 | 内容 |
|----|------|
| **标准句** | `拍张照片我看一下`（C10c） |
| **期望 plan** | **单步** `camera.capture_and_upload`（禁止拆成 capture + upload 跨边） |
| **通过** | `presentation.type=image`，`from=asset_ref`，有 `asset_id` |
| **前置** | Runtime 心跳同时广告 capture、upload、composite |

---

### 2.8 资产上传 · `asset.upload`

| 项 | 内容 |
|----|------|
| **回归方式** | 通常由 `camera.capture_and_upload` / `document.scan` 覆盖；独立句：`传到云上`（若有广告） |
| **通过** | 产出 `asset_ref`；禁止 `photo_url` 永久 URL 作身份 |

---

### 2.9 资产清单 · `asset.inventory`

| 项 | 内容 |
|----|------|
| **插件** | `asset-inventory` |
| **标准句** | `我今天拍了几张照片` |
| **期望 plan** | `asset.inventory`（常为 system 步） |
| **通过** | `answer_text` 含 count；或 `asset_ref` 当 `include_refs` |
| **语义** | 计数口径归产品/asset 契约；黑盒只记事实 |

---

### 2.10 文档扫描 · `document.scan` / `visual.input`

| 项 | 内容 |
|----|------|
| **插件** | `document-scanner` |
| **标准句** | `扫描一下这个小票` |
| **期望 plan** | 单步 `document.scan` → iPhone `edge-node-JzvEe287` |
| **前置** | **双 Brain 路由对齐**（agent-brief §2）；iPhone 广告 `document.scan` |
| **观察窗** | ≤120s；期间 **完成系统扫描、勿取消** |
| **通过（成功路径）** | `parsed`→`running`→`waiting`→`succeeded`；`step_outputs.asset_ref` + `presentation` 含图 |
| **通过（取消路径）** | `failed`，`msg=已取消`，`status=cancelled` |
| **Chat 主路径** | 点「扫描」→ `POST /assets/upload`（可另验，不经 planner） |

---

### 2.11 看图理解 · `vision.perceive`

| 项 | 内容 |
|----|------|
| **插件** | `vision-perceive` |
| **标准句** | `拍张照看看客厅里有没有人`（Q12 前两步） |
| **期望 plan** | `camera.capture` → `vision.perceive`（`$photo_url`） |
| **通过** | `summary` 在 outputs；**禁止**用 `vision.ask` 冒充 |
| **负例** | 无图不得 perceive 成功（Q38） |

---

### 2.12 看图问答 · `vision.ask`

| 项 | 内容 |
|----|------|
| **插件** | `vision-ask` |
| **标准句** | `拍张照，这个字读啥`（Q13 / C12b） |
| **期望 plan** | capture → `vision.ask`（`query` 含问句）→ speak/feedback |
| **通过** | `answer_text` 在 outputs；禁止纯 `query.content` 编字 |
| **负例** | `这个字读啥` 无图（Q39）必须失败 |

---

### 2.13 OCR · `image.ocr`

| 项 | 内容 |
|----|------|
| **标准句** | 依产品触发（常与阅读模式/指字组合） |
| **期望** | 有图入参；产出文字字段在 `step_outputs` |
| **通过** | 不经 LLM 拆包兜底；结构不对就失败 |

---

### 2.14 阅读指字 · `reading.point_to_character` 等

| 项 | 内容 |
|----|------|
| **标准句 A** | 阅读模式 + `这个字怎么读`（C12c） |
| **标准句 B** | `看下最新的一张照片里手指的那个字是什么` |
| **期望 plan B** | `asset.inventory` → `reading.point_to_character` → speak；**无** capture |
| **前置** | `开启阅读模式` shortcut；sidecar/模型在线 |
| **通过** | 不经 LLM；finger 缺失时失败 msg 可读 |

---

### 2.15 单图投屏 · `display.photo`

| 项 | 内容 |
|----|------|
| **插件** | `chromecast-display` / `xiaomi-tv-display` |
| **标准句** | `拍张照投到电视上`（C11 / Q11） |
| **期望 plan** | `camera.capture` → `display.photo`（`asset_ref` 或 `$photo_url`） |
| **前置** | Cast/TV 在线；**P2** |
| **通过** | 同 edge 或合法 handoff；`presentation` 含图 |
| **负例** | `投到电视上` 无图（C16/Q32）必须失败 |

---

### 2.16 轮播投屏 · `display.slideshow`

| 项 | 内容 |
|----|------|
| **标准句** | `把刚才拍的那些照片做成轮播投到电视`（C17/Q33） |
| **期望** | 本步必填 `asset_refs`/`photo_urls`；**禁止**从前序 capture 自己拼 |
| **负例** | 无列表 → 干净 `failed` |

---

### 2.17 音乐 · `music.play` / `pause` / `stop` / `next` / `previous` / `resume`

| 项 | 内容 |
|----|------|
| **插件** | `netease-music` |
| **标准句** | `播放陈奕迅的十年`（C15/Q18）；`暂停播放`（Q19） |
| **期望 plan** | 单步对应 capability；`song`/`artist` 字段合理 |
| **前置** | music 节点在线 + Cast；**P2** |
| **通过** | `succeeded` 或干净失败（无能力 msg 可读） |
| **负例** | 空 plan 卡 `intent_parsed` |

---

### 2.18 灯光 · `light.set`

| 项 | 内容 |
|----|------|
| **插件** | `livingroom-ceiling-light` |
| **标准句** | `把客厅灯打开` / `关灯`（契约 `state=on|off`） |
| **期望 plan** | `light.set` |
| **前置** | Mac 或 iPhone 心跳广告 `light.set` |
| **通过** | 步 status=2；现场可听/可见为「执行未证实」备注 |

---

### 2.19 空调 · `climate.set`

| 项 | 内容 |
|----|------|
| **插件** | `hisense-ac` |
| **标准句** | `打开空调` / `空调调到 26 度` |
| **期望 plan** | `climate.set` |
| **前置** | iPhone **海信账号已绑定**；心跳广告 `climate.set` |
| **通过** | 规划+执行终态；无绑定时不应 silently 成功 |
| **状态** | 绑定前黑盒记「无 capability」为预期 |

---

### 2.20 鱼缸 · `aquarium.set` · 门锁 · `lock.status`

| 能力 | 标准句 | 通过要点 |
|------|--------|----------|
| `aquarium.set` | `打开鱼缸喂食` | 有设备广告则 plan 匹配；否则干净失败 |
| `lock.status` | `门锁什么状态` | `step_outputs` 含状态字段 |

---

### 2.21 能力介绍 · `capabilities.summary`

| 项 | 内容 |
|----|------|
| **标准句** | `你会什么` / `你能做什么` |
| **期望** | `capabilities.summary`（system 或 Mac） |
| **通过** | 文本产出；**禁止**派 `query.content` 编造 |

---

### 2.22 搜图 · `search.images`

| 项 | 内容 |
|----|------|
| **标准句** | 依 `typical_triggers` |
| **通过** | 产出图列表或 `asset_ref`；与 `query.content` 生图区分 |

---

### 2.23 游戏 · `game.launch` / `game.input`

| 项 | 内容 |
|----|------|
| **标准句** | `打开接金币游戏`（G-Plan） |
| **期望** | 单步 `game.launch`，`game_id=coin_catcher` |
| **补充** | HTTP 命令链见 [`game_mvp_demo.md`](game_mvp_demo.md) |

---

### 2.24 发音评测 · `pronunciation.assess`

| 项 | 内容 |
|----|------|
| **标准句** | context 带 `reference_audio` + `student_audio`（P1） |
| **期望** | 仅 `pronunciation.assess`；无录音/投屏步 |
| **通过** | `overall_score` 等必填；`presentation.text` 含分数 |
| **负例** | 缺 `student_audio`（P2）；sidecar 不可达（P3） |

---

### 2.25 调试/现场专用（非 P0 主路径）

| 能力 | 说明 |
|------|------|
| `network.wifi.join/leave` | 调试；不纳入家庭自然语言主回归 |
| `bluetooth.connect/disconnect` | 无广告则失败有 msg（Q43） |
| `voice.stream` / `video.live_stream` | 按插件契约单测 + 点名黑盒；直播音频见 [`video_live_stream.md`](video_live_stream.md) **VL1** |
| `xiaodu.speak` / `voicewakeup.echo` | 设备在场时补 case |
| `phone.call` / `voice_test.run_trial` | 现场专用 |

---

## 3. 回归套餐（建议执行顺序）

### 3.1 冒烟（每次 deploy 后，~15 min）

1. `GET /health` 200  
2. P0 任选 3 条：`clock.now`（Q1）+ `math.calculate`（Q4）+ `chat.smalltalk`（早啊）  
3. 一条负例：Q29 窗帘  

### 3.2 标准回归（发版前，~1–2 h）

- 跑完 **P0**（C3–C7 或 Q1–Q9）  
- **P1** 抽 1 条 delay（C8）  
- **P2** 按现场允许选：C10 / C11 / C15 / document.scan 成功路径  
- 结果写入 `log.md` + `report.md`  

### 3.3 全量

- [`cases.md`](cases.md) C3–C21 + Q1–Q50 + 专项（game / pronunciation / document.scan）  
- Runner：`run_n20.py`、`run_q50.py`、`run_suite.py`  

---

## 4. 分工

| 角色 | 职责 |
|------|------|
| **@quality** | 只打 `POST /api/v1/intent` + `GET intent_detail`；写 `log.md` / `report.md`；不判「谁的 bug」 |
| **@capability** | 维护 `plugins/*/capability.md`、manifest、Edge 单测；规划广告字段与 `do_not_dispatch` |
| **@runtime** | 心跳广告、拉单执行、双 Brain 路由装包 |
| **@ui** | Intent Source、LivingRoomEdge 路由锁定、扫描/阅读模式 UI |
| **@boss** | P2 现场允许；iPhone 完成扫描勿取消；海信绑定 |

---

## 5. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-08-28 | 初版：`@boss` #68 要求；合并 cases.md、agent-brief、document.scan/chat.smalltalk 现场结论 |
