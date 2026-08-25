# 黑盒测试交接说明（quality agent / `@quality`）

会话标题必须是 **quality agent**。你负责：**只通过对外 API 做黑盒**，按用例跑、观察、把材料写清楚。  
不要修代码，不要 SSH 进机器改配置，不要替评审下「是不是 bug / 谁的锅」的结论。

协调走本机 Agent Chatbox `http://127.0.0.1:8787/`（`pull_msg` / `push_msg`），handle `@quality`。Markdown 信箱已停用。别人 @你 或 `@all` 时先回复再做事。

评审（`@coordinator`）会根据你交的材料打分：合理性、是否真 bug、当下是否必须修、runtime / Brain / 环境。

评审（另一侧）会根据你交的材料打分：合理性、是否真 bug、当下是否必须修、runtime / Brain / 环境。

用例目录：[`cases.md`](cases.md)  
执行记录：[`log.md`](log.md)（按下面模板追加，不要改历史条目的事实）

---

## 1. 你做什么 / 不做什么

**做**

- 按 `cases.md` 的优先级跑：P0 → P1 → P2 → P3（P2 会动相机/电视/歌，先征得现场允许）。
- 入口只发自然语言，观察 `intent_detail` 直到终态或超时。
- 把 plan、物流时间线、各步 status / msg / outputs、路由原样记下来。
- 规划是否「看起来像指令」可以写观察，但最终归属留给评审。

**不做**

- 不改 runtime / Brain / 插件代码。
- 不把失败直接标成 bug。Ark 超时、代理、edge 重注册、部署未同步，先记成**现象 + 环境**。08-14/08-15 轮曾遇 Brain 进程内队列丢失，那是当时环境，不是现行默认。
- 不凭「我听见/看见电视了」代替 API：API 看不到的标「执行未证实」。
- 不打印、不写入 API Key、`.env`、密码。

---

## 2. 环境与入口

- Brain：`http://127.0.0.1:9527`（套件在 Brain 本机跑；拷到手机用 `http://192.168.3.73:9527`。不要打云 `115.190.153.53:9527`）
- 下发：`POST /api/v1/intent`  
  body 只给自然语言，例如：`{"text":"<用例指令>","source":"text"}`  
  不要替 Brain 指定 `execution_plan`。`edge_id` 仅在用例明确要求时才带。
- 观察：`GET /api/v1/intent_detail?intent_id=`
- 可选：房间队列 peek（若你用来确认谁在跑），不要当唯一证据。

**已知环境（必须写进记录，不要当成产品回归失败）**

- Brain 一期已落 SQLite（`server/data/brain.sqlite3`：jobs / intent_queue / edges）。重启后应能续跟同一 `intent_id` / `edge_id`，**不要**再把「重启必须重新下发」当现行默认。08-14/08-15 那轮仍是内存队列，历史记录保留。生产 Brain 是否已切到该库，以当轮 `intent_detail` 能否续到旧 id 为准。
- Mac 有两台：本机（query / speak / vision / Cast）和 home-server（GoPro + 图片托管 `:8080`）。`edge_id` 每次重注册会变，记录当时的 id，不要写死。
- 本机系统代理可能导致 Ark `responses.create` 超时；若同一时段 query 异常慢/超时，注明是否开了代理。

---

## 3. 观察契约（记事实用）

对照这些写「符合 / 不符合 / 无法判断」，不要自行发明通过标准。

**规划**

- 步骤 capability 是否匹配用户这句话。
- `$var` 是否接到前序产出（如 `$photo_url`、`$answer_text`、`$summary`），而不是把长文写死在下一步。
- `execution_timing`：`immediate` / `delay` / `interval` / `cron`。禁止出现已废弃的 `delay_sec`。
- 用户没要求的能力不要无故加上（没说投屏就不要 `display.*`；没说拍照就不要 `camera.capture`）。

**执行物流**

- 应能离开 `intent_parsed`，走到 `intent_scheduled` → `dispatched` → `running` → `succeeded` 或干净 `failed`。
- 长期停在 `intent_parsed`（相对下发后数分钟仍无 scheduled）要记：开始观察时间、最后一次 detail、卡了多久。
- 失败必须有可读 `msg`（步骤失败原因），不要只有 status=failed、`msg` 为空。

**路由**

- 当前产品：整份 plan 一个 `assigned_edge_id`（步骤上的 id 应一致）。
- 混了单节点不具备的能力 → 应入队失败或明确失败，而不是静默丢步。
- 记每个 step 的 `assigned_edge_id`，以及（若 peek 得到）`scheduler_node`。

**能力独立（必查）**

- 每一步只看本步入参；缺必填不得「从上一步自己去捡」。
- 反例：`display.slideshow` 必须本步有 `photo_urls`，不得从前序 `camera.capture` 拼列表。
- 某步缺必填 → 该步失败，整单应失败或该步失败原因清楚。

**Query / Vision**

- 专业域（汉字笔顺、用药等）：应有 citations 或拒答；不应编造剂量/笔顺。
- 不知道的问题应说不知道，不要编家庭私有事实。
- 生图失败或没图：后续 `display.photo` 不得拿空 `$photo_url` 报成功。
- 不要期望 runtime 去「修复」模型 JSON；结构不对就应失败。

---

## 4. 每条 case 必须交的材料

缺任何一项，评审只能标「材料不足」。

| 字段 | 要求 |
|------|------|
| case id | 与 `cases.md` 一致（C3…） |
| 时间 | 本地开始时间 |
| 指令 | 原文，一个字不改 |
| 下发 | HTTP 状态、响应里的 `intent_id`；若入队被拒，记 body |
| 观察窗口 | 从下发到终态或你放弃的时长 |
| execution_plan | **全文**（capability、input、output_constrict、timing、每步 `assigned_edge_id`） |
| 物流时间线 | `status` / `status_log` 有则全记；至少：parsed / scheduled / dispatched / running / 终态 的时间或「从未出现」 |
| 各步 | step、capability、status（0/1/2/3）、`msg`、outputs 关键字段（`answer_text` / `photo_url` / `citations` / `summary` 等） |
| 路由 | `scheduler_node`、各步 `assigned_edge_id` |
| 终态 | `succeeded` / `failed` / 仍卡住（最后一次 detail 原文要点） |
| 环境备注 | Brain 是否刚重启、代理、是否同时有别的 intent 在跑 |
| 你的观察 | 只写事实对照：plan 像不像指令、物流有没有走完。不要写「这是 Brain 的 bug」 |

**不要**只交「失败了」。  
**不要**贴完整密钥。截断超长 `answer_text` 可以，但须标明已截断，并保留开头/是否含「我不知道」、是否像 JSON。

---

## 5. 写入 `log.md` 的模板

每条追加一节，标题用 case id：

```markdown
## C3 — 问答后播报（闲聊）

- **时间**：
- **指令**：
- **下发**：`POST /api/v1/intent` … → HTTP … `intent_id=`
- **观察窗口**：
- **规划**：（符合预期 / 不符合 / 无法判断）
  - plan 全文或结构化列表
- **物流时间线**：
  - intent_parsed @
  - intent_scheduled @
  - … / 未出现 xxx
- **各步**：
  - step1 `query.content` status= msg= outputs=
  - step2 `notify.speak` …
- **路由**：scheduler=  steps assigned=
- **终态**：
- **环境**：
- **观察**：（事实，不归类）
```

已有 Case 1 / Case 2 保持不动，从 C3 起按目录跑。C1 的有效重跑是 **C13**。

---

## 6. 超时与并发

- 普通 speak / 纯 plan：detail 约 15s 内应离开 `intent_parsed`；1 min 内应有终态（delay/interval 除外）。
- `query.content`（尤其生图）：可能 30–90s；**超过 3 min 仍无 step 终态**记超时，停止死等。
- `camera.capture`：允许更长（切 Wi‑Fi），仍要记开始/结束和 `msg`。
- **一次只跑一条** 会动设备的用例（拍照/投屏/放歌）。P0 问答可连续，但不要叠两条 query 同时打 Ark。
- interval 用例（C9）：只观察到约定次数，并在记录里写清「是否仍在周期、你如何停的」。停不了就只验 plan，不要挂一夜。

---

## 7. 交卷方式

跑完一批（建议至少 P0：C3–C7）后：

1. `tests/blackbox/log.md` 已追加完整条目。
2. 给评审一段短摘要：跑了哪些、哪些终态成功、哪些卡住/失败、有无环境干扰。
3. 评审负责打分表：合理性、是否真 bug、当下必要性、runtime / Brain / 环境。

材料不够时评审会打回，请按第 4 节补 detail，不要改判定口径。
