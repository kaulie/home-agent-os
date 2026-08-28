# Agent Bridge

Mac 本地 **Cursor Agent** HTTP 桥接服务：手机或 Brain 通过 HTTP 下发开发任务，daemon 空闲时等待，收到指令后唤醒 Cursor Agent 执行。

## 能力

- `POST /api/v1/command` — 下发任务（异步，立即返回 `run_id`；可选 `target_handle` 直达 Fleet worker）
- `GET /api/v1/runs/<run_id>` — 查询任务状态与输出事件
- `GET /api/v1/status` — 查看 Agent 连接状态与 Fleet 摘要
- `GET /api/v1/agents` — 各 handle 的 `agent_id`、是否在跑、最近唤醒时间
- `POST /api/v1/agents/<handle>/wake` — 唤醒指定 Fleet worker
- 持久化每 handle 的 `agent_id`（`data/agents/{handle}.json`），daemon 重启后可恢复

## 快速开始

```bash
cd /Users/gaolei/Projects/smart_home_control/agent-bridge
cp .env.example .env
# 编辑 .env，填入 CURSOR_API_KEY

./run.sh
```

默认监听 `http://127.0.0.1:9540`，工作目录为仓库根目录 `smart_home_control/`。

## API

### 下发任务

```bash
curl -s -X POST http://127.0.0.1:9540/api/v1/command \
  -H 'Content-Type: application/json' \
  -d '{"text":"列出 server/ 目录结构"}'
```

返回 `202`：

```json
{
  "run_id": "abc123...",
  "status": "queued",
  "text": "列出 server/ 目录结构"
}
```

### 查询进度

```bash
curl -s http://127.0.0.1:9540/api/v1/runs/<run_id>
```

`status` 依次为 `queued` → `running` → `finished` / `error`。`events` 里包含 Agent 流式输出片段。

### 鉴权

设置 `AGENT_BRIDGE_TOKEN` 后，请求需带：

```http
Authorization: Bearer <token>
```

## 环境变量

见 [`.env.example`](.env.example)。

| 变量 | 默认 | 说明 |
|------|------|------|
| `CURSOR_API_KEY` | — | Cursor API Key（可选；未设置时用 `cursor-agent` CLI） |
| `AGENT_BRIDGE_HOST` | `127.0.0.1` | 监听地址 |
| `AGENT_BRIDGE_PORT` | `9540` | 监听端口 |
| `AGENT_BRIDGE_CWD` | 仓库根目录 | Agent 工作目录 |
| `AGENT_BRIDGE_MODEL` | `composer-2.5` | 本地 Agent 模型 |
| `AGENT_BRIDGE_TOKEN` | — | HTTP Bearer Token |

## 架构

```text
Phone / Brain ──POST /command──▶ agent-bridge (Mac daemon)
                                      │
                                      ▼
                               Cursor SDK (local)
                               Agent.resume / send
                                      │
                                      ▼
                               smart_home_control/
```

## Brain 集成

手机发 `source=dev` 的 intent（或在聊天框输入 `/dev 你的任务`），Brain 会转发到本机 bridge 并轮询结果；手机照旧拉 `intent_detail` 看进度。

在 `server/.env` 配置：

```bash
AGENT_BRIDGE_URL=http://127.0.0.1:9540
# AGENT_BRIDGE_TOKEN=...   # 与 bridge 一致
# AGENT_BRIDGE_POLL_SEC=2
```

## 外网：SSH 反向隧道（云 Brain → 家里 Mac）

手机在外连云 Brain `http://115.190.153.53:9527` 时，Brain 需要访问你家里 Mac 上的 bridge。家里 Mac 主动 SSH 到云服务器，把本机 `9540` 映射到云上的 `127.0.0.1:19540`。

```text
iPhone ──► 云 Brain :9527 ──► 127.0.0.1:19540（云上）
                                  │ SSH 反向隧道
                                  ▼
                            家里 Mac agent-bridge :9540
```

### 1. 家里 Mac：bridge + 隧道

`.env` 里配置 `AGENT_BRIDGE_TOKEN`（与云 Brain 一致）。启动 bridge：

```bash
./run.sh
```

启动反向隧道（或安装 launchd 自启）：

```bash
./tunnel/reverse-tunnel.sh

# 开机自启（可选）
launchctl bootstrap gui/$(id -u) tunnel/com.gaolei.agent-bridge-tunnel.plist
```

隧道脚本使用 `~/.ssh/config` 里的 `cloud-server` 主机别名。

### 2. 云 Brain：`server/.env`

```bash
AGENT_BRIDGE_URL=http://127.0.0.1:19540
AGENT_BRIDGE_TOKEN=<与 bridge .env 相同>
AGENT_BRIDGE_ENABLED=1
```

改完后 `systemctl restart doubao_skill.service`。

### 3. 验证

在云服务器上：

```bash
curl -s http://127.0.0.1:19540/health
```

应返回 `{"ok":true,"service":"agent-bridge"}`。

## 测试

```bash
cd agent-bridge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m unittest discover -s tests -v
```
