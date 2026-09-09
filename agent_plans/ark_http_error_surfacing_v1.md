# Plan：ARK 规划 HTTP 错误（403/AccountOverdue 等）透传到 intent 失败信息

> 落盘：task-54b2ed92 · 开发分支 `fix/task-54b2ed92` · 交付方式：PR 到 main
> 触发：intent 668/669（URL→PDF）规划失败，真实原因是火山方舟 ARK `HTTP 403
> AccountOverdueError`（账号欠费），但系统只展示“execution_plan 为空，无法调度”，
> 误导排查。

## 1. 目标

`call_ark` 已把非 200 的 ARK HTTP 错误体（`http_status` + `error.code/message`）
解析进 `_ark_result().response_json`，但 `_process_llm_task` 只在 `ans == "__ARK_HTTP_401__"`
时给出“规划服务 401，检查 ARK_API_KEY”，其余（403 等）统一回退 `_empty_plan_failure_msg()`
→ “execution_plan 为空，无法调度”。

本次只做一件事：**当且仅当 ARK 调用自身返回 HTTP 错误（>=400）时，把该错误转成
明确的用户可见文案写进 intent 的 `msg/error/presentation`**；合法空 plan（LLM 认为
无能力可做）仍走原有 missing-capability/reason 诊断，语义不变。

## 2. 已确认决策

| 维度 | 决策 |
|---|---|
| 主路径 | `server/home_brain.py::_process_llm_task` 失败分支 |
| 新增函数 | `_ark_http_error_msg(response_json) -> str \| None` |
| 判定 | `http_status >= 400` 才透传；否则返回 `None` 保留原逻辑 |
| 文案 | 401 保持现文案；`AccountOverdueError` 明确“账号欠费/余额”；其它按 `HTTP {status}（{code}）：{message}` |
| 截断 | 用户可见 message 截断 ~240 字符 |
| `call_ark` | 不改主逻辑（response_json 已由 `_ark_http_error_json` 填充） |
| 测试 | `server/tests/test_home_brain.py`：单测 helper + `_process_llm_task` 集成 |

## 3. 改动文件

- `server/home_brain.py`：新增 `_ark_http_error_msg()`（放在 `_empty_plan_failure_msg` 附近），
  修改 `_process_llm_task` 空 plan 分支优先用该 helper。
- `server/tests/test_home_brain.py`：新增对应单测/集成测试。

## 4. 验收

- 403 AccountOverdueError → intent `failed`，`msg/error/presentation.text` 含
  “403 / AccountOverdueError / 欠费”。
- 其它 `>=400`（如 429）→ 文案含 HTTP 码与错误 message。
- 非 HTTP 错误的空 plan（response_json 为 None/无 http_status）→ 仍是原
  `_empty_plan_failure_msg` 结果（回归不受影响）。
- 相关单测通过（`test_home_brain.py` 失败路径用例）。
