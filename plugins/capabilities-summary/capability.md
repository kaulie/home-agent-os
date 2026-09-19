# Service: system.capabilities（capability: capabilities.summary）

把当前 **在线、可调度** Runtime 能力的 **自描述**（`planner_recognize` / `role`）收成一段 **给用户听** 的口语介绍。

`kind=system`：控制面检索，由 **Brain 就地执行**，不绑任何 Runtime。

## 能

- 问「你可以做什么 / 你会什么 / 有哪些能力 / 你可以控制空调吗 / 你会开灯吗」时，产出短 `answer_text`。
- 素材来自 Brain 在线 Runtime 能力集合里各能力自己的结构化广告。
- **提炼 / 汇总**：按 group 收束、口语化，适合听；**禁止**逐条朗读整段自描述，**禁止**在答语里点名其它 capability id / 技术名。

## 不能

- 不当知识问答；不执行开灯或开空调；不拍照。
- 不读手机系统能力列表；不编造未广告的能力。

| plugin id | `capabilities-summary` |
| service_id | `system.capabilities` |
| group | `meta` |
| wire capability | `capabilities.summary` |
| kind | `system` |
| 执行方 | Brain（`server/system_capabilities.py`） |

Presentation：语音问法优先 `type=audio`，`from=answer_text`。

## 开发者 / 运维：完整目录在「能力集市」

`capabilities.summary` 给**用户听**的是一段口语介绍；要给**人查/对比/排账**的完整目录在这里：

- 仓库：<https://github.com/kaulie/home-agent-capabilty-marketplace>
- 网页（可搜 / 按 group·服务·关键字·宿主筛）：`index.html`；机器可读：`catalog/capabilities.json`
- 内容由集市的两步同步产出（**不要手改生成物**）：
  ```bash
  # 1) 本仓代码 → 导出声明（只读、无副作用）
  python3 mac/scripts/export_capability_catalog.py --out <marketplace 检出目录>
  # 2) 集市侧：导出 → 入库 → 回写仓库 → 自检
  <marketplace>/scripts/sync.sh <本仓检出目录>
  ```
- 定位：集市是**能力展示与技能介绍**，只登记声明（能力/服务/条件挂载/参数/触发语/文档 + 人工策展：
  描述、关键字、适用宿主），**不保存实时状态**（在线/设备/探测结果）。要看实时状态用 Brain
  `GET /api/v1/capabilities`；要看代码与目录有没有漂移：`<marketplace>/scripts/sync.sh <本仓> --check`。


