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
