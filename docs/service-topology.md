# 本机服务拓扑（LAN Mac）

家里这台 Mac（`192.168.3.84`）上跑哪些进程、端口、怎么起。地址数字以 [`config/endpoints.json`](../config/endpoints.json) 为准。

**没有 launchd / systemd 自启。** 电脑重启后这些进程全停，按下面「开机拉起」再开一遍。改了端口、角色或启停方式，同步改本文。

## 这台 Mac 上现在该有的

| 服务 | 端口 | 健康检查 | 怎么起 |
|------|------|----------|--------|
| LAN Brain | 9527 | `GET http://127.0.0.1:9527/health` | `cd server && BRAIN_ORIGIN=lan nohup .venv/bin/python home_brain.py >> llm_logs/brain.nohup.log 2>&1 &` |
| Mac Edge | （无独立 HTTP；带起下面几个口） | 日志里 `heartbeat OK` | `cd mac && nohup ./run_mac_edge.sh >> data/mac_edge.out 2>&1 &` |
| mac_voice（Edge 拉起） | 8792 手机拾音 | 进程 `-m mac_voice --live` | 随 Mac Edge（`MAC_EDGE_VOICE=1`） |
| 视频直播 ingest | 8790 | `GET http://127.0.0.1:8790/api/v1/video-live/status` | 随 Mac Edge |
| 小度 TTS HTTP | 8000 | 监听 `*:8000` | 随 Mac Edge |
| img-server | 8080 | `GET http://127.0.0.1:8080/health` | `python3 img-server/serve.py` |
| ocr-service | 9188 | `GET http://127.0.0.1:9188/health` | `cd ocr-service && ./run.sh`（必须用自带 pyenv，勿用系统 python3） |
| character-service | 9189 | `GET http://127.0.0.1:9189/health` | 先起 ocr-service，再 `cd character-service && ./run.sh`（必须用 `local-rt/venv` 的 python3.11） |
| Agent Chatbox | 8787 | `GET http://127.0.0.1:8787/` | `python3 chat/serve.py` |
| agent-bridge | 9540 | `GET http://127.0.0.1:9540/health` | `cd agent-bridge && ./run.sh` |
| 现场 Admin | 8788 | `GET http://127.0.0.1:8788/` | `python3 admin/serve.py`（代理本机 Brain `/api/v1/admin/*`） |

Mac Edge 双 Brain：LAN `http://127.0.0.1:9527` + 云 `http://115.190.153.53:9527`（见 `mac/.env` 的 `MAC_EDGE_BRAIN_URL`）。

识字链路：**character-service 依赖本机 ocr-service :9188**。只起 9189、不起 9188，指字会失败。

## 开机拉起（顺序）

1. LAN Brain（9527）
2. Chatbox、Admin、agent-bridge（可并行）
3. img-server、ocr-service（可并行）
4. character-service（等 9188 health 200）
5. Mac Edge（等 9527 health 200；会再拉 mac_voice / 8790 / 8000）

```bash
ROOT=/Users/gaolei/Projects/smart_home_control

cd "$ROOT/server" && BRAIN_ORIGIN=lan nohup .venv/bin/python home_brain.py >> llm_logs/brain.nohup.log 2>&1 &
cd "$ROOT" && nohup python3 chat/serve.py >> /tmp/chatbox.log 2>&1 &
cd "$ROOT" && nohup python3 admin/serve.py >> /tmp/admin.log 2>&1 &
cd "$ROOT/agent-bridge" && nohup ./run.sh >> data/bridge.console.log 2>&1 &
cd "$ROOT" && nohup python3 img-server/serve.py >> /tmp/img-server.log 2>&1 &
cd "$ROOT/ocr-service" && nohup ./run.sh >> /tmp/ocr-service.log 2>&1 &
# wait: curl -sf http://127.0.0.1:9188/health
cd "$ROOT/character-service" && nohup ./run.sh >> /tmp/character-service.log 2>&1 &
# wait: curl -sf http://127.0.0.1:9527/health
cd "$ROOT/mac" && nohup ./run_mac_edge.sh >> data/mac_edge.out 2>&1 &
```

## 这台默认不跑

| 服务 | 端口 | 说明 |
|------|------|------|
| 云 Brain | 云 `:9527` | 不随本机重启；`GET http://115.190.153.53:9527/health` |
| pronunciation-service | 9190 | 发音打分 sidecar；`cd pronunciation-service && ./run.sh`。未点名不要当常驻 |
| Cast Receiver `:9095` | 9095 | Edge 里配了 `MAC_EDGE_CAST_DISPLAY_URL`；独立 Receiver 进程另开 |
| img-server 旧 home-server | 曾 `192.168.3.65:8080` | 现默认本机 `192.168.3.84:8080` |
| Ollama | 本机 App | 与 Home Agent 栈无关 |

laptop 角色的 Mac Edge **不广告** GoPro / img-server（img-server 是独立 HTTP，不是 capability）。

## 云上（对照，不在这台起）

| 服务 | 说明 |
|------|------|
| Brain | `/root/chat-gateway`，`systemctl restart doubao_skill` |
| character-service | 云上 Docker，绑 `127.0.0.1:9189` |
| ocr-service | 云上 Docker，绑 `127.0.0.1:9188` |
| 云静态图 | `http://115.190.153.53:8080`（不是本机 img-server） |

部署约定见 [`.cursor/rules/cloud-deploy.mdc`](../.cursor/rules/cloud-deploy.mdc)。

## 巡检

```bash
for u in \
  http://127.0.0.1:9527/health \
  http://127.0.0.1:8787/ \
  http://127.0.0.1:9540/health \
  http://127.0.0.1:8788/ \
  http://127.0.0.1:8080/health \
  http://127.0.0.1:9188/health \
  http://127.0.0.1:9189/health \
  http://127.0.0.1:8790/api/v1/video-live/status
 do
  echo -n "$u "
  curl -sS -m 2 -o /dev/null -w '%{http_code}\n' "$u" || echo 000
done
```

## 维护

- `@sre` / `@controller` 改启停、换端口、换机器时改本文。
- 只改 IP/端口数字时先改 `config/endpoints.json`，再跑 `python3 tools/sync_endpoints.py`，再改本文表格。
- 不要把密钥写进本文。
