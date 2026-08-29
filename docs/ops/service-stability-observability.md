# 服务稳定性观测与 Dev Console【服务】Tab

**状态：** 方案定稿（P0 待实现）  
**主导：** `@sre`  
**实现分工：** `@ui` 页面 · `@brain` 只读 Admin API · `@dba` 落库 schema · `@runtime` Edge 探针字段  

相关：[`architecture/three-consoles-debug-gateway.md`](../architecture/three-consoles-debug-gateway.md) · [`architecture/dual-brain-runtime.md`](../architecture/dual-brain-runtime.md) · Dev tabs `ios/HomeAgentDev/HomeAgentDev/RootTabView.swift`

---

## 1. 目标

1. **持续观测** Home Agent 开发/运行栈中各服务的可用性，记录每次 **downtime**（起止、时长、根因分类）。
2. **HomeAgentDev** 新增 **【服务】** Tab：以「每个服务」为粒度展示当前状态、近期 uptime、最近故障摘要。
3. 与 **Fleet / Deploy / 统计 / 连接** Tab 职责分离，不重复造轮子。

---

## 2. 服务清单（观测边界）

按 **可独立探活、对开发/验收有明确影响** 划定 P0 范围。不在 P0 的标为 P1 候选。

### 2.1 P0（必观测）

| `service_id` | 显示名 | 角色 | 默认探针目标 | 备注 |
|--------------|--------|------|--------------|------|
| `lan_brain` | LAN Brain | 控制面（局域网） | `GET {lan_brain_url}/health` | 开发机/客厅 Mac 上的 Brain；`brain_origin` 应为 `lan` |
| `cloud_brain` | Cloud Brain | 控制面（云端） | `GET {cloud_brain_url}/health` | 公网 VPS；与 LAN 独立进程 |
| `mac_edge` | Mac Edge | Runtime Agent | Brain `registrations` 心跳 + 本机进程 | 见 §3.2 |
| `mac_voice` | Mac Voice | 语音 STT | 本机进程 + `listen.lock` 持有者 | 与 Edge 解耦监督 |
| `agent_bridge` | agent-bridge | Fleet / Dev Task | `GET :9540/health` | 开发编排，非产品路径 |
| `chatbox` | Agent Chatbox | Agent 协调 | `GET :8787/health` | 协调面，非 Brain DB |
| `img_server` | LAN 图片服务 | Asset 上传 | `GET :8080/health` | Mac 本机 `img-server` |
| `cast_display` | Cast 展示 HTTP | Endpoint 呈现 | `GET :9095/health` 或进程 | HomeAgentRelay / Cast 本地页 |

### 2.2 P1（扩展）

| `service_id` | 显示名 | 探针 |
|--------------|--------|------|
| `character_service` | 指人服务 | `GET :9189/health` |
| `pronunciation_service` | 发音评测 | `GET :9190/health` |
| `ocr_service` | OCR | `GET :9188/health`（端口以 manifest 为准） |
| `local_rt` | 本地 LLM RT | `GET :8081/health`（以 `local-rt` 配置为准） |
| `chromecast_receiver` | TV Receiver | 心跳或 Cast 会话探针（需 `@ui` 约定） |
| `ncm_cli` | 网易云依赖 | 经 Mac Edge capability 广告间接探测 |

### 2.3 明确不纳入本 Tab

| 对象 | 归属 Tab / 模块 |
|------|----------------|
| Cursor Fleet worker、`@brain` 等 agent 会话 | **Fleet** Tab（`GET /api/v1/admin/agent_fleet`） |
| `[release]` 流水线、rsync、批准上线 | **Deploy** Tab |
| LLM token 用量 | **统计** Tab（`dev_task` usage API） |
| Dev Client 选哪台 Brain URL | **连接** Tab |
| 单个 Intent / Issue 成败 | **Issue** Tab |
| 业务 Console「节点健康度」汇总 | Phase 3 Business Console（见 three-consoles） |

---

## 3. 观测信号与状态定义

### 3.1 探针类型

| 类型 | 说明 | 适用 |
|------|------|------|
| `http_health` | `GET /health`，解析 JSON `ok` | Brain、bridge、chat、img-server、各 sidecar |
| `http_ping` | `GET /api/v1/ping`，校验 `server_time_ms` | Brain 轻量可达（可选与 health 二选一） |
| `process` | 本机 PID / `pgrep` 匹配预期命令行 | mac_edge、mac_voice |
| `lock_file` | 锁文件存在且 PID 存活 | `mac_voice` `listen.lock` |
| `brain_registration` | Brain DB：`registrations` 最近 `heartbeat_at` | mac_edge 与 Brain 契约对齐 |
| `log_tail` | 日志关键字（失败计数，非结构主信号） | P1 根因辅助 |

### 3.2 采样与判定

| 参数 | P0 默认 |
|------|---------|
| 轮询间隔 | **30s**（Observer 单进程循环） |
| HTTP 超时 | **5s** |
| 连续失败升格 | **2 次**（约 60s）→ `down` |
| 恢复确认 | **1 次**成功 → `up` |
| 保留原始探针 | 每次写入 `probe_samples`（P0 可只保留 24h） |

**状态枚举 `status`：**

| 值 | 含义 |
|----|------|
| `up` | 探针成功，且（若有）Brain health 中 `db` 可用、无 crash-loop 特征 |
| `degraded` | 进程在但功能受损：如 health `ok` 但 `registered=0`、Edge 心跳滞后 > **3×** 注册间隔、`music_mode` 导致 STT 静音、响应 > **3s** |
| `down` | 连续失败、进程不存在、health HTTP ≥500 或连接拒绝 |
| `unknown` | 尚未完成首次探针或 Observer 自身不可用 |

**Downtime 事件：** 从「up / degraded」变为 `down` 时记 `started_at`；回到 `up` 记 `ended_at` 并闭合 incident。`degraded` 单独记 **degraded incident**（可选，P0 可合并进 downtime 备注）。

### 3.3 与现有信号的关系

- **Edge heartbeat**（`registrations`）：Runtime 已上报；Observer **读取** LAN Brain 的 registration 快照，不替代 Edge 上报逻辑（`@runtime` 不改契约，只保证字段稳定）。
- **intranet_ping**（`mac/logs/intranet_ping.log`）：网络层参考；P1 可关联到 `root_cause=network`。
- **Brain `/health`**：已有 `ok`、`brain_origin`、`db`、`registered`、`jobs`、`pending_intents`（见 `server/home_brain.py`）。

---

## 4. Downtime 记录模型

### 4.1 存储位置（定稿）

| 层 | 职责 |
|----|------|
| **Service Observer（本机 Mac）** | **写入主库**；Brain 挂掉时仍能记 LAN 侧故障 |
| **Brain `brain.sqlite3`** | **不存** P0 明细（避免运维数据污染意图库、避免空库迁移踩坑） |
| **Brain Admin API** | **只读聚合**；代理读本机 Observer 或读缓存快照 |

**库文件（P0）：** `mac/data/service_observability.sqlite3`（或仓库根 `data/ops/service_observability.sqlite3`，与 Observer 同机）。

**P2 可选：** 云侧长期归档表（`@dba` 新 migration），由 Observer 定时 push 摘要；非 P0。

### 4.2 表结构（SQLite）

**`services`** — 配置行（与 §2 清单同步）

| 列 | 类型 | 说明 |
|----|------|------|
| `service_id` | TEXT PK | 如 `lan_brain` |
| `display_name` | TEXT | 中文显示名 |
| `tier` | TEXT | `p0` / `p1` |
| `probe_kind` | TEXT | `http_health` / `process` / … |
| `probe_target` | TEXT | URL 或进程匹配规则 JSON |
| `enabled` | INTEGER | 1/0 |

**`probe_samples`**（可选 P0 精简：仅保留最近 N 条）

| 列 | 说明 |
|----|------|
| `id` | 自增 |
| `service_id` | FK |
| `at_ms` | 采样时间 |
| `status` | up/down/degraded/unknown |
| `latency_ms` | HTTP 或探针耗时 |
| `detail_json` | 原始 health 片段、HTTP 状态码 |

**`incidents`** — downtime / degraded 记录

| 列 | 类型 | 说明 |
|----|------|------|
| `incident_id` | TEXT PK | `inc-{uuid}` |
| `service_id` | TEXT | FK |
| `kind` | TEXT | `downtime` / `degraded` |
| `started_at_ms` | INTEGER | 进入 down/degraded |
| `ended_at_ms` | INTEGER NULL | 恢复时间；NULL=进行中 |
| `duration_sec` | INTEGER | 闭合时计算 |
| `root_cause` | TEXT | 枚举，见下表 |
| `summary` | TEXT | 一行人读摘要（≤200 字） |
| `evidence_json` | TEXT | 日志路径、health body、chat msg id、release sha |
| `created_by` | TEXT | 固定 `service_observer`；P1 可 `sre_manual` |

**根因分类 `root_cause`（P0 枚举）：**

| 值 | 典型场景 |
|----|----------|
| `crash_loop` | 进程反复退出（如空 `brain.sqlite3`） |
| `stale_db` | DB 文件存在但 schema 不可用 |
| `orphan_lock` | 锁被僵尸 PID 占用（mac_voice） |
| `dual_brain_split` | Edge/Client 与 Runner 指向不同 Brain |
| `network_unreachable` | TCP/HTTP 超时、公网不可达 |
| `dependency_missing` | ncm-cli、sidecar 未起 |
| `config_drift` | URL/端口与预期不符 |
| `manual_restart` | 人工重启后恢复（evidence 含操作者备注） |
| `unknown` | 待 P1 分析 |

**谁写库：** 仅 **Service Observer** 自动写；`@sre` P1 可提供 CLI 补 `summary` / 改 `root_cause`。

---

## 5. 采集架构

```
┌─────────────────┐     30s poll      ┌──────────────────────────┐
│ Service Observer│ ────────────────► │ mac/data/                │
│ (Mac 本机守护)   │                   │ service_observability.sqlite3
└────────┬────────┘                   └────────────┬─────────────┘
         │ GET /health, process, …                  │
         ▼                                        │ read
  LAN/Cloud Brain, bridge, chat, …               ▼
                                         ┌─────────────────────┐
                                         │ ops read API :8799   │
                                         │ GET /api/v1/ops/…    │
                                         └──────────┬──────────┘
                                                    │ LAN 代理
                                                    ▼
                                         ┌─────────────────────┐
                                         │ Brain Admin (只读)   │
                                         │ GET /api/v1/admin/   │
                                         │     services*        │
                                         └──────────┬──────────┘
                                                    │
                                                    ▼
                                         HomeAgentDev 【服务】Tab
```

**Observer 进程（P0 交付物，`@sre`）：**

- 路径建议：`scripts/ops/service_observer.py` + `scripts/ops/service_observer_config.yaml`
- 启动：Mac `launchd` 或 dev 栈 `run.sh` 同级文档说明
- 读 API：`scripts/ops/service_observability_serve.py` 监听 `127.0.0.1:8799`（与 Chatbox 8787 错开）

**Brain 代理（P0，`@brain`）：**

- `GET /api/v1/admin/services` → 转发本机 `http://127.0.0.1:8799/api/v1/ops/services`（失败时返回 `observer_unreachable` + 上次缓存若存在）
- 需 Dev Admin 鉴权（与现有 `admin/*` 一致）

---

## 6. Dev Console【服务】Tab

### 6.1 信息架构

| 层级 | 内容 |
|------|------|
| 列表页 | 按 P0 服务排序；状态色点（up=绿、degraded=黄、down=红、unknown=灰）；**当前状态**、**24h uptime %**、**最近 incident 一行摘要**、最后探针时间 |
| 详情页 | 服务说明、探针目标（脱敏）、当前 `detail` JSON 折叠、**incident 时间线**（最近 20 条）、关联 `evidence` 链接（日志路径仅展示不可点，P1 可做 deep link） |
| 空态 | Observer 不可达：提示「观测服务未运行」+ 重试 |

**Tab 位置：** `RootTabView` 在 **统计** 与 **连接** 之间插入 `services`（`Label("服务", systemImage: "server.rack")`）。

**轮询：** 前台 **15s**（与 Fleet 类似）；切 Tab 启停，遵循现有 `syncPolling` 模式。

### 6.2 API 契约（给 `@ui`）

基址：与 Dev Client 当前 **Brain URL** 一致（`DevStore.brainURL`），路径前缀 `/api/v1/admin/services`。

#### `GET /api/v1/admin/services`

查询：`?tier=p0`（可选）

响应：

```json
{
  "ok": true,
  "observer_at_ms": 1710000000000,
  "services": [
    {
      "service_id": "lan_brain",
      "display_name": "LAN Brain",
      "tier": "p0",
      "status": "up",
      "status_since_ms": 1709990000000,
      "last_probe_at_ms": 1710000000000,
      "last_probe_latency_ms": 42,
      "uptime_24h_pct": 99.2,
      "uptime_7d_pct": 98.5,
      "last_incident": {
        "incident_id": "inc-abc",
        "kind": "downtime",
        "started_at_ms": 1709900000000,
        "ended_at_ms": 1709900120000,
        "duration_sec": 120,
        "root_cause": "stale_db",
        "summary": "空 brain.sqlite3 导致 crash-loop"
      },
      "active_incident": null,
      "detail": {
        "brain_origin": "lan",
        "registered": 3,
        "pending_intents": 0
      }
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `up` \| `degraded` \| `down` \| `unknown` |
| `uptime_24h_pct` | number | 过去 24h 非 down 时间占比 |
| `last_incident` | object \| null | 最近已闭合 incident |
| `active_incident` | object \| null | 进行中 down/degraded |
| `detail` | object | 探针原始摘要，服务各异 |

#### `GET /api/v1/admin/services/{service_id}`

单服务详情 + `incidents` 数组（默认 `limit=20`）。

#### `GET /api/v1/admin/services/{service_id}/incidents?limit=20&cursor=`

分页 incident 列表；`cursor` 为上一页最后 `incident_id`。

**错误：**

| HTTP | `error` |
|------|---------|
| 503 | `observer_unreachable` |
| 404 | `unknown_service_id` |

**Swift 模型建议：** `DevServicesSnapshot`、`DevServiceRow`、`DevServiceIncident` 放 `FleetModels.swift` 或新 `ServiceModels.swift`；请求放 `DevClient.swift`；状态放 `DevStore` + `startServicesPolling()`。

---

## 7. 与现有 Tab 的边界（摘要）

| Tab | 问什么 | 【服务】不问什么 |
|-----|--------|------------------|
| Fleet | Agent bridge 里谁在跑、wake worker | bridge **进程**是否存活（归【服务】） |
| Deploy | 哪次 commit 待批准、是否已上云 | 部署动作本身；仅 incident `evidence` 可挂 `release_sha` |
| 统计 | Token 花了多少 | 服务是否在线 |
| 连接 | 当前 Dev Client 连哪台 Brain | 两台 Brain 是否都健康 |
| Issue | 某次用户报 bug | 基础设施连续运行时间 |

---

## 8. 分阶段交付

### P0 — 观测 + 落库 + 只读 Tab（目标：2 周）

| 任务 | Owner |
|------|-------|
| Observer 守护进程 + SQLite schema + 读 API :8799 | `@sre` |
| `GET /api/v1/admin/services*` 代理与鉴权 | `@brain` |
| `service_observability` 建表 SQL / migration 脚本 | `@dba` |
| 【服务】Tab UI + 轮询 + 模型 | `@ui` |
| Edge registration 字段稳定、文档注明心跳间隔 | `@runtime`（若无变更则仅确认） |
| 黑盒：Admin API 200 + 字段契约 | `@quality`（P0 末尾） |

**验收：** 人工停 LAN Brain 60s → Tab 显示 `down` → 恢复后 incident 闭合且含 `duration_sec`。

### P1 — 根因辅助

- 日志 tail 规则 → 自动建议 `root_cause`
- `@sre` CLI：`service-incident annotate --id inc-xxx --cause crash_loop`
- 关联 Chatbox msg id、`[release] sha` 写入 `evidence_json`
- degraded 独立时间线；7d/30d uptime 图表

### P2 — 告警

- Chatbox `@sre` / `@boss`：某服务 down > **5min**
- 可选：Business Console 只读镜像
- 可选：云归档 + 跨地域 Observer

---

## 9. 分工清单（定稿后开干）

### `@sre`（主导）

- [ ] 实现 `service_observer` + config（§2 清单）
- [ ] SQLite schema + `service_observability_serve.py`
- [ ] Mac 启动说明（`docs/ops/service-observer-runbook.md`，P0 可附录本节）
- [ ] 与 `@brain` 对齐代理 URL 与缓存策略

### `@ui`

- [ ] `DevTab.services` + `DevServicesView` / 详情
- [ ] `DevClient` + `DevStore` 轮询
- [ ] 状态色与手机可读布局（短段、少宽表）

### `@brain`

- [ ] `GET /api/v1/admin/services`、`/services/<id>`、`/incidents`
- [ ] 代理本机 Observer；503 契约
- [ ] 单测：mock observer 响应

### `@dba`

- [ ] 审阅 schema；提供 `sql/migrations/0xx_service_observability.sql`（本机库，非 brain.sqlite3）
- [ ] 文档索引写入 `docs/db-schema.md` 一节「运维库」

### `@runtime`

- [ ] 确认 `registrations.heartbeat_at` / Edge 注册间隔文档化
- [ ] 若需：health 旁路暴露 Edge 本机 PID（P1，非必须）

### `@quality`

- [ ] P0 完成后：Admin services API 契约测试（可进 `server/tests/`）

### `@deploy`

- P0 **无需**上云；Observer 仅开发机。若将来云侧也部署 Observer，走独立 runbook。

---

## 10. 配置示例（Observer）

```yaml
# scripts/ops/service_observer_config.yaml
poll_interval_sec: 30
http_timeout_sec: 5
fail_threshold: 2
db_path: mac/data/service_observability.sqlite3
services:
  - service_id: lan_brain
    display_name: LAN Brain
    tier: p0
    probe_kind: http_health
    probe_target: "http://127.0.0.1:9527/health"
  - service_id: cloud_brain
    display_name: Cloud Brain
    tier: p0
    probe_kind: http_health
    probe_target: "http://115.190.153.53:9527/health"
  - service_id: agent_bridge
    display_name: agent-bridge
    tier: p0
    probe_kind: http_health
    probe_target: "http://127.0.0.1:9540/health"
  # … 其余见 §2
```

---

## 11. 修订记录

| 日期 | 作者 | 说明 |
|------|------|------|
| 2026-08-30 | `@sre` | 初稿：清单、信号、落库、API、分阶段、分工 |
