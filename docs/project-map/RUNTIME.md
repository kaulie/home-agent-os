# RUNTIME

项目怎么真正跑起来。LAN 进程与开机顺序以 [docs/service-topology.md](../service-topology.md) 为准；地址数字以 [config/endpoints.json](../../config/endpoints.json) 为准。

没有根 Makefile，没有根 docker-compose。LAN Mac **没有** launchd/systemd 自启；重启后按「开机拉起」再开一遍。

## 怎么启动

### 开机顺序（LAN Mac）

1. LAN Brain（9527）
2. Chatbox、Admin、agent-bridge（可并行）
3. img-server、ocr-service（可并行）
4. character-service（等 9188 health 200）
5. Mac Edge（等 9527 health 200；会再拉 mac_voice / 8790 / 8000）

拓扑文档里的 nohup 块可直接用。开发时也可以前台跑（Ctrl-C 停）。

### 各服务

| 服务 | 端口 | 启动 |
|------|------|------|
| LAN Brain | 9527 | `cd server && BRAIN_ORIGIN=lan nohup .venv/bin/python home_brain.py >> llm_logs/brain.nohup.log 2>&1 &` 或前台 `python home_brain.py` |
| Chatbox | 8787 | `python3 chat/serve.py` |
| Admin HTML | 8788 | `python3 admin/serve.py`（不上云） |
| agent-bridge | 9540 | `cd agent-bridge && ./run.sh` |
| img-server | 8080 | `python3 img-server/serve.py` |
| ocr-service | 9188 | `cd ocr-service && ./run.sh`（自带 pyenv，勿用系统 python3） |
| character-service | 9189 | `cd character-service && ./run.sh`（必须 `local-rt/venv` 的 python3.11） |
| Mac Edge | 无独立 HTTP | `cd mac && ./run_mac_edge.sh` |
| mac_voice | 8792 | 默认随 Edge；或 `PYTHONPATH=src python -m mac_voice --live --post-intent` |
| 视频 ingest | 8790 | 随 Mac Edge |
| 小度 TTS | 8000 | 随 Mac Edge |
| Cloud Brain | 云 9527 | 不随本机重启；`ssh cloud-server` 上 systemd |
| pronunciation | 9190 | 可选，非常驻：`cd pronunciation-service && ./run.sh` |
| local-rt llama | **8082** | `local-rt/run_llama.sh`（`LLAMA_PORT` 可改） |

根入口 [`home_brain.py`](../../home_brain.py) 只是转发到 `server/home_brain.py`（云 systemd 用这个）。

健康检查：

```bash
curl -sf http://127.0.0.1:9527/health
curl -sf http://127.0.0.1:8787/
curl -sf http://127.0.0.1:9540/health
curl -sf http://127.0.0.1:8080/health
curl -sf http://127.0.0.1:9188/health
curl -sf http://127.0.0.1:9189/health
```

### iOS / Android

iOS：各 App 目录 `python3 generate_xcodeproj.py` 后 `open *.xcodeproj`。主 Console 是 `ios/LivingRoomEdge/`。

Android：`android/` Gradle 多模块。主路径文档为 `:living-room-android`。

### Cast Receiver

自定义 CAF Receiver HTML：`plugins/chromecast-display/receiver/`。本地预览：`python3 -m http.server 8765`。生产需 HTTPS + Cast App ID `F7649303`。

Mac 环境变量里有 `MAC_EDGE_CAST_DISPLAY_URL=http://127.0.0.1:9095/endpoint/display`。**[UNKNOWN]：** 仓库内没有启动 `:9095` 进程的脚本。Presentation 主路径是 iPhone Cast Sender，不是这个口。

## 怎么停止 / 重启

| 服务 | 做法 |
|------|------|
| LAN Brain | `server/deploy/deploy_lan_brain.sh` **默认本机** `pkill` 再拉起（不 SSH）；远程须显式 `BRAIN_HOST=…`；前台则 Ctrl-C |
| Cloud Brain | `ssh cloud-server 'systemctl restart doubao_skill'` |
| Mac Edge | `mac/stop_mac_edge.sh`；或杀进程 |
| local-rt | `run_llama.sh` 会先 `lsof` 杀同端口 |
| 其余 | **[UNKNOWN]** 无统一 stop 脚本 — 按 PID / `lsof -iTCP:<port>` / Ctrl-C |
| 整机 | 重启后全部停；按开机顺序再拉 |

agent-bridge 收到 SIGINT/SIGTERM 会走 shutdown。

## 怎么看日志

| 日志 | 位置 |
|------|------|
| Brain 滚动日志 | `llm_logs/brain.log`（`BRAIN_LOG_DIR`，否则若仓库根已有 `llm_logs/` 用它，否则 `server/llm_logs/`） |
| Brain nohup | `server/llm_logs/brain.nohup.log` |
| 云部署审计 | `/root/chat-gateway/agent_access.log`（UTC+8；不要 rsync） |
| Chatbox nohup | `/tmp/chatbox.log` |
| Admin nohup | `/tmp/admin.log` |
| bridge nohup | `agent-bridge/data/bridge.console.log` |
| Mac Edge | `mac/data/mac_edge.out` |
| mac_voice 监督 | `mac/logs/mac_voice.supervised.out.log` |
| img/ocr/character nohup | `/tmp/img-server.log`、`/tmp/ocr-service.log`、`/tmp/character-service.log` |
| local-rt | `local-rt/logs/llama_cpu.log` |
| 云 systemd | **[UNKNOWN]** 仓库无 unit 文件；操作上用 `journalctl -u doubao_skill` |

故障时：先 `/health`，再对应 nohup / `brain.log`，Mac 看 heartbeat 是否 OK。

## 怎么跑测试

无 Makefile。无仓库根 `pytest.ini`。

```bash
# Brain（跳过真实 Ark worker）
cd server && BRAIN_SKIP_LLM_WORKER=1 python -m unittest discover -s tests -v

# Mac Edge
cd mac && python3 -m unittest discover -s tests -p 'test_*.py' -q

# Chatbox
python3 -m unittest chat.tests.test_chat

# agent-bridge
cd agent-bridge && PYTHONPATH=src python -m unittest discover -s tests -v

# character-service
cd character-service && python3 -m pytest tests/test_geometry.py tests/test_stages.py -q

# 对外黑盒（需要 Brain 已起；许多用例要 BLACKBOX_PARTICIPANT_ID）
python3 tests/blackbox/run_suite.py
python3 tests/blackbox/run_p0_dual_brain.py
python3 tests/blackbox/run_n20.py
python3 tests/blackbox/run_q50.py

# XCUITest
cd ios/HomeAgentDev
xcodebuild test -scheme HomeAgentDev \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -only-testing:HomeAgentDevUITests/HomeAgentDevSmokeUITests
```

黑盒结果写 `tests/blackbox/report.md` / `run_results_*.json`。能力回归流程：[docs/capability-regression-standard.md](../capability-regression-standard.md)。

## 怎么部署

### 云 Brain（`@deploy`）

规则：[`.cursor/rules/cloud-deploy.mdc`](../../.cursor/rules/cloud-deploy.mdc)。门禁：已 commit + 已测（或老板书面豁免）。禁止同步未提交工作区。

- SSH：`ssh cloud-server`
- 远程树：`/root/chat-gateway` = 本仓库根
- 同步：`server/home_brain.py`、`server/prompts/`、根 `home_brain.py`。相对路径保持不变
- **不要** rsync：`db.py`、`sql/`、`data/`、`admin/`、`.venv`、`.env`、`gopropics/`、`llm_logs/`、`agent_access.log`
- 重启：`systemctl restart doubao_skill`
- `WorkingDirectory=/root/chat-gateway`，`ExecStart=/usr/bin/python3 home_brain.py`
- 密钥只在云 `.env` 的 `ARK_API_KEY`
- 操作后追加一行 `agent_access.log`（含 commit sha）

回滚：检出上一已测 sha，再按同样范围 rsync + restart。

### LAN Brain

[`server/deploy/deploy_lan_brain.sh`](../../server/deploy/deploy_lan_brain.sh) **默认重启本机 checkout**（`pkill` + `BRAIN_ORIGIN=lan` nohup，不是 systemd）。旧 home-server 才设 `BRAIN_HOST`（如 `lan-brain`）走 rsync + SSH。

### OCR / character 上云

各目录 Docker Compose，绑定 `127.0.0.1:9188` / `:9189`。不是 `doubao_skill` 的一部分。

### 端上 App

按该面既有方式（Xcode / Gradle / 各 `deploy_ios12.sh`）。部署前正文带 sha。

## 环境变量（必填 / 常改）

| 变量 | 哪里 | 作用 |
|------|------|------|
| `ARK_API_KEY` | `server/.env`、云 `.env` | 真实规划 |
| `AGENT_BRIDGE_TOKEN` | bridge + Brain `.env` | Bearer。**不是**规则里偶尔出现的 `BRIDGE_AUTH_TOKEN` |
| `AGENT_BRIDGE_URL` | Brain | 默认 `http://127.0.0.1:9540`；云隧道 `…:19540` |
| `BRAIN_ORIGIN` | Brain | `lan` / `cloud` |
| `BRAIN_ADMIN_TOKEN` | Brain / Admin App | 可选 |
| `OCR_SERVICE_URL` | Brain | 如 `http://127.0.0.1:9188` |
| `MAC_EDGE_BRAIN_URL` | `mac/.env` | 单 URL 或双 Brain JSON |
| `MAC_EDGE_ROLE` | mac | `laptop` / `home-server` |
| `CURSOR_API_KEY` | bridge | CLI 已登录则可空 |

样例：`server/.env.example`、`mac/.env.example`、`agent-bridge/.env.example`。

## 端口速查

权威 LAN/Cloud Brain 身份在 `config/endpoints.json`（LAN 用 mDNS 名，不写死家用 IP）。改 hostname/端口/云地址：先改该文件，再 `python3 tools/sync_endpoints.py`，再改 topology 与客户端。

| 端口 | 服务 |
|------|------|
| 9527 | Brain |
| 8787 | Chatbox |
| 8788 | Admin HTML |
| 9540 | agent-bridge |
| 19540 | 云上隧道到本机 bridge |
| 8080 | img-server |
| 8790 | 视频 ingest |
| 8792 | 语音拾音 |
| 8000 | 小度 TTS |
| 9188 / 9189 / 9190 | ocr / character / pronunciation |
| 8082 | local-rt llama（脚本默认） |
| 9095 | 遗留 Cast HTTP，**[UNKNOWN]** 如何拉起 |
| 8799 | 可观测性 API — 文档有、`scripts/ops/` **目录缺失** → 视为未落地 |

## 开发环境怎么进

1. 读 [README.md](README.md) 启动协议。
2. 起 LAN Brain + 你要改的那一层进程（不必起全套）。
3. 改规划：只动 `server/prompts/`。
4. 改 Edge：`mac/` venv + `PYTHONPATH=src`。
5. 改 iOS：先 `generate_xcodeproj.py`。

## 发生故障之后怎么看

1. 进程在不在、端口在不在（上表 health）。
2. Brain：`jobs.status`、`msg`、`llm_logs/brain.log`。
3. Edge：heartbeat 是否在 60s TTL 内；Mac `mac_edge.out`。
4. 规划失败：prompt 与 Ark 错误，不要先改 plugin。
5. 投屏：先看 iPhone Cast Sender / Receiver，不要假设 `:9095` 一定在跑。
