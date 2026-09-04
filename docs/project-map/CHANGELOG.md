# CHANGELOG

记录**结构性**变化，方便新 Agent 不用翻完全部 git history。不是版本发布流水，也不是每次 bugfix。

维护约定：架构 / 模块职责 / 运行方式 / 边界发生变化时，在本文件顶部追加日期条目，并改对应 Map。

---

## 2026-09-03

- 建立 `docs/project-map/`（本地图）。Agent 进入仓库先读 [README.md](README.md)。
- 未加 Cursor 常驻规则（按当次决定）；入口挂在根 README 文档索引。

## 已核实的结构事实（地图建立时的基线）

这些不是今天才发生的，但是理解当前代码必须知道的「已经发生过的结构」：

- **双 Brain**：同一 Runtime 向 LAN / Cloud 分别 Registration；Heartbeat 属于 Registration。文档：[docs/architecture/dual-brain-runtime.md](../architecture/dual-brain-runtime.md)。
- **Participant 四角色**：Intent Source / Runtime Agent / Endpoint / Observer。设备类型不是核心抽象。[docs/participant-model.md](../participant-model.md)。
- **三控制台**：User Console / Business Admin / Dev Console，互不塞控件。[docs/architecture/three-consoles-debug-gateway.md](../architecture/three-consoles-debug-gateway.md)。
- **Chatbox 取代 Markdown 信箱**：协调走 `http://127.0.0.1:8787/`。[docs/agent-mailbox.md](../agent-mailbox.md) 停用。
- **`@intent` / `@endpoint` 合并为 `@ui`**。Fleet 只保留一个 UI handle。
- **Planner 提示词只维护 md**：`server/prompts/task_planner_system_prompt.md.en`。禁止在 `home_brain.py` 内联规划长文。
- **Brain 仍是单体** `server/home_brain.py`（约 8k 行）。拆分方案 [docs/architecture/brain-simplification-plan.md](../architecture/brain-simplification-plan.md) 为规划-only。
- **Asset 身份是 `asset_id`**；步间禁止 `photo_url` 双写。跨节点复制未完。
- **Capability 独立**：plugin 不读前序 step；hydrate 归 Runtime。
- **发布链路**：commit → test → deploy，Chatbox `[release]` 留痕。云树 `/root/chat-gateway`，unit `doubao_skill`。
- **LAN 地址权威**：`config/endpoints.json` 写 mDNS 名（`brain.local` / `gateway.local` / `img-server.local`），不写死家用 IP。

## 2026-09 前后近期结构向提交（摘）

来自 git log，只摘会影响「去哪改」的：

- mDNS 局域网服务发现（Brain 发布 + 客户端发现 + 设置页 DNS）。DHCP 换 IP 后不再只信写死地址。
- 语音唤醒按 participant 隔离窗口（Home Mic / 本机麦不要抢同一段）。
- Chat 正式 `@` vs `cc`、recv/got 徽章、`work_board` 与 Fleet `phase` 对齐。
- `@coordinator` 默认静默；结案禁止正式 `@` 回环。
- `video.live_stream` HLS 整场回放。

更细的功能提交不要往这里堆；需要时 `git log`。
