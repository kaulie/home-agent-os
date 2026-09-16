"""paper.read Explain 模式（证据约束讲解）—— **v1 保留、未交付**。

用户确认的 v1 范围：**先做 original 原文模式**，explain 保留（接口、schema、prompt 结构
都留在设计里，见 ``agent_plans/paper_read_v1.md`` §6），等下一个版本再实现。

本模块的存在只为两件事：

1. 把 explain 的**契约固定下来**（``depth`` 三层、输出 schema、失败口径），避免以后改动
   `paper.read` 的 wire 契约；
2. explain 被调用时给出**明确中文失败**（不静默降级成 original，也不产半成品音频）——
   这正是设计里的决策点 C：失败就明说，不猜。

实现要点（留给下一版，写在这里当交接）：

- LLM 走 edge 既有 ``mac_edge.plugins.query_providers``（默认 ARK）；**不复用** ``query.content``
  的 prompt（自带 prompt + 自带输出 schema），温度 0.2、只输出一层 JSON；
- ``depth`` 决定喂哪些 section：``overview`` = Abstract + Intro 首尾段 + Conclusion + 主结果段；
  ``method`` = Method/Approach 全节；``deep`` = Method + Experiment + Ablation + Limitations（v1.1）；
- 输出 ``{"narration":[{"section":…,"kind":"fact|synthesis|inference","text":…}]}``，行文按顺序
  拼成 spoken script；``inference`` 必须显式标注，不能写成作者观点；
- 硬约束（prompt + 代码双保险）：每个数字/指标/数据集/对比必须能在原文找到（代码白名单校验，
  命中不了就丢该句并记 warning）；原文没写就直说「论文里没有写」；不补论文外知识；
  公式只讲「在算什么」。
"""

from __future__ import annotations

from typing import Any

# depth 三层（wire 契约的一部分，v1 就固定：planner 现在写 explain 也不会改契约）。
EXPLAIN_DEPTHS = ("overview", "method", "deep")
DEFAULT_EXPLAIN_DEPTH = "overview"
# v1 设计里的目标范围（实现随 explain 一起交付）。
PLANNED_V1_DEPTHS = ("overview", "method")

# 输出 schema（讲解稿最终拼成 spoken script，再复用 paper.read 的 TTS 路径）。
NARRATION_KINDS = ("fact", "synthesis", "inference")


class PaperExplainError(Exception):
    """explain 模式明确中文失败（v1 未交付 / 以后：无 key / 超时 / JSON 解析失败）。"""


def explain_script(
    structure: Any,
    *,
    depth: str = DEFAULT_EXPLAIN_DEPTH,
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """v1 保留：explain 讲解稿生成（未实现）→ 明确中文失败，绝不静默降级。"""
    mode = str(depth or DEFAULT_EXPLAIN_DEPTH).strip().lower()
    if mode not in EXPLAIN_DEPTHS:
        raise PaperExplainError(
            f"explain 的 depth 只能是 {'/'.join(EXPLAIN_DEPTHS)}，收到 {depth!r}"
        )
    raise PaperExplainError(
        "paper.read 的 explain 模式（论文讲解）尚未交付：v1 只上线 original 原文听读"
        "（详见 agent_plans/paper_read_v1.md §6，接口已保留）。"
        "请改用 mode=original 做原文听读"
    )
