# Agent Chatbox

本机协调服务：传统对话替代 Markdown 信箱。**不是 Brain**，库文件也不是 `server/data/brain.sqlite3`。

## 启动

```bash
python3 chat/serve.py
```

浏览器打开 <http://127.0.0.1:8787/>。

环境变量：`CHAT_HOST`（默认 `127.0.0.1`）、`CHAT_PORT`（默认 `8787`）、`CHAT_DB_PATH`（默认 `chat/data/agent_chat.sqlite3`）。

约定：[`docs/agent-coordination.md`](../docs/agent-coordination.md)。

## 接口

```bash
# 用户笔记（agent 的 pull_msg 拿不到）
curl -s -X POST http://127.0.0.1:8787/api/v1/push_msg \
  -H 'Content-Type: application/json' \
  --data '{"from":"boss","body":"只是笔记"}'

# 派给 brain
curl -s -X POST http://127.0.0.1:8787/api/v1/push_msg \
  -H 'Content-Type: application/json' \
  --data '{"from":"boss","body":"@brain 去看 intent 71"}'

# 全员
curl -s -X POST http://127.0.0.1:8787/api/v1/push_msg \
  -H 'Content-Type: application/json' \
  --data '{"from":"boss","body":"@all 对齐 Asset"}'

# agent 拉取自己的公共 + 私有消息（推进水位）
curl -s 'http://127.0.0.1:8787/api/v1/pull_msg?handle=brain'

# agent 回复
curl -s -X POST http://127.0.0.1:8787/api/v1/push_msg \
  -H 'Content-Type: application/json' \
  --data '{"from":"brain","body":"@boss 已看 intent 71"}'

# 页面时间线（含已读/未读，不推进水位）
curl -s 'http://127.0.0.1:8787/api/v1/messages?since_id=0'

# 1 分钟内且无人看过时可撤回
curl -s -X POST http://127.0.0.1:8787/api/v1/recall_msg \
  -H 'Content-Type: application/json' \
  --data '{"from":"boss","id":1}'
```

页面每 5 秒请求 `/api/v1/messages` 并刷新已读状态。用户未 `@` 任何人时，agent **不处理**。agent `pull_msg` 成功即对该批消息已读。自己发的消息在 1 分钟内、且还没有人看过时，可点「撤回」。

## 测试

```bash
python3 -m unittest chat.tests.test_chat
```
