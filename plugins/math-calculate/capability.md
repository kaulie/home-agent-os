# Service: local.math

确定性本地算术插件（`math-calculate`），group=`math`。  
**无 LLM**；只解析固定形式的算式并本地求值。

**Brain 不执行**；只通过心跳结构化 planner 字段选边：
`role` / `planner_recognize` / `typical_triggers` / `do_not_dispatch`（加 schemas）。
`description` 散文 **不再** 作为规划契约。

Planner **必须**先判断用户问的是不是本能力支持的形式；不是则 **不要派** `math.calculate`。

**与 `query.content` 独立**：禁止 import 共享。算不了的题由 Brain 改派 `query.content`，不是本能力失败后让 query 补救同一步。

## 规划自描述（心跳结构化字段）

| 字段 | 值 |
|------|-----|
| role | 确定性算术求值器 |
| planner_recognize | 计算简单、可解析的数学表达式 |
| typical_triggers | `1+1等于几`、`根号4`、`3×5` |
| do_not_dispatch | 应用题、复杂数学、单位换算、知识问答 |

### 能（仅以下形式 — 满足才派本能力）

| 类别 | 示例 |
|------|------|
| 四则 | `1+1`、`三乘以五`、`12除以3`、Unicode `×` `÷` |
| 括号 | `(2+3)*4` |
| 次方 | `二的三次方`、`3的平方`、`二的立方` |
| 根号 | `根号4`、`根号下九`、`√9` |
| 问句包装 | `一加一等于几`（剥壳后仍是上表形式） |

产出：`answer_text`（如「一加一等于二。」）、`result`（如 `2`）。

### 不能（必须路由到其它 capability）

| 用户意图 | 应派 |
|----------|------|
| 应用题、文字推理（「小明有3个苹果…」） | `query.content` |
| 方程、不等式、三角/对数/微积分 | `query.content` |
| 单位换算（「1英里等于多少公里」） | `query.content` |
| 汉字笔顺、几画、百科事实 | `query.content` |
| 现在几点 | `clock.now` |
| 要图、投屏、TTS、拍照、开灯 | 对应 display / notify / camera / light 能力 |

**禁止**把非纯算式塞给 `math.calculate` 指望失败后再改 plan。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `math-calculate` |
| service_id | `local.math` |
| group | `math` |
| wire capability | `math.calculate` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.math_calculate`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `expression`（必填）：算式或算术问句 |
| **输出** | `answer_text`（必填）；`result`（必填，数值字符串） |

本能力 **只看本步入参**。缺 `expression` 或 **无法按上表规则解析** → 失败（可读 `msg`），禁止猜测、禁止 LLM。

## Wire

```json
{
  "capability": "math.calculate",
  "step": 1,
  "assigned_edge_id": "<laptop-edge-id>",
  "input_constrict": {
    "expression": { "type": "string", "value": "一加一等于几" }
  },
  "output_constrict": {
    "answer_text": { "type": "string", "data_dest": "context" },
    "result": { "type": "string", "data_dest": "context" }
  }
}
```

## 入口

- Mac：`mac/src/mac_edge/plugins/math_calculate.py` + `arithmetic_shortcut.py`；`services.py` 广告 `local.math`
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["math.calculate"]`
