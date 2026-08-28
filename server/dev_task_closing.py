"""Dev Task closing summary: Markdown draft, validation, and agent instructions."""

from __future__ import annotations

from typing import Any

# Appended to every agent turn. Not a closing summary — only work notes + optional 派单.
WORK_TURN_INSTRUCTION = """
## Dev Task turn output (mandatory)
Write your work notes as Markdown. This is **not** the closing summary — the boss will
request a closing summary later when the issue is confirmed solved or the task is closed early.

Include when useful:
## 结论
## 做了什么
## 遗留与风险（如有）

### 派单（mandatory）
If other Fleet handles must continue, list them so the system can wake follow-up Dev Tasks.
Do **not** only "建议" in prose.

Format (one line per handle; use a colon):
- @capability: concrete task for that agent

If nobody else needs to be woken, write exactly:
- 无

Valid handles: @brain @runtime @ui @capability @quality @deploy @sre @dba @coordinator
Do not list @controller.

Do not push this turn output to Chatbox unless asked.
""".strip()

# Kept for imports / close-time generation prompts.
CLOSING_INSTRUCTION = """
## Dev Task closing summary (mandatory)
Produce a **Markdown closing summary** for the Dev Task record (boss confirmed resolve or early close).

Use this structure:
## 结论
## 做了什么
## 变更范围（如有）
## 验收说明
## 遗留与风险（如有）

For cancel / early close: ## 结论: 已取消 / ## 原因 / ## 当时进度.

Do not push this summary to Chatbox.
""".strip()


def looks_like_markdown_summary(text: str) -> bool:
    body = str(text or "").strip()
    if not body:
        return False
    if body.startswith("## "):
        return True
    if "\n## " in body:
        return True
    if body.startswith("# ") and "\n" in body:
        return True
    return False


def wrap_summary_draft(raw: str, *, outcome: str, task_text: str = "") -> str:
    text = str(raw or "").strip()
    if looks_like_markdown_summary(text):
        return text
    headline = {
        "succeeded": "已完成",
        "failed": "未完成",
        "cancelled": "已取消",
    }.get(outcome, "收尾")
    lines = [
        f"## 结论\n{headline}",
        "",
        "## 说明",
        text or "（无 agent 正文输出）",
    ]
    if task_text.strip():
        lines.extend(["", "## 原任务", task_text.strip()[:2000]])
    return "\n".join(lines)


def brief_cancel_summary(*, task_text: str = "", reason: str = "") -> str:
    reason_text = str(reason or "用户中断").strip()
    progress = str(task_text or "").strip()[:500]
    parts = [
        "## 结论",
        "已取消。",
        "",
        "## 原因",
        reason_text,
    ]
    if progress:
        parts.extend(["", "## 当时进度", progress])
    return "\n".join(parts)


def extract_closing_draft(run: dict[str, Any], *, outcome: str, task_text: str = "") -> str:
    result = str(run.get("result") or "").strip()
    if result:
        return wrap_summary_draft(result, outcome=outcome, task_text=task_text)
    events = run.get("events") or []
    if isinstance(events, list):
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            if event.get("type") == "assistant":
                text = str(event.get("text") or "").strip()
                if text:
                    return wrap_summary_draft(text, outcome=outcome, task_text=task_text)
    if outcome == "cancelled":
        error = str(run.get("error") or "").strip()
        return brief_cancel_summary(task_text=task_text, reason=error or "用户中断")
    if outcome == "failed":
        error = str(run.get("error") or "dev task failed").strip()
        return wrap_summary_draft(error, outcome=outcome, task_text=task_text)
    return wrap_summary_draft("", outcome=outcome, task_text=task_text)


def build_close_summary_draft(
    *,
    outcome: str,
    task_text: str = "",
    work_result: str = "",
    error: str = "",
    note: str = "",
) -> str:
    """Compose a closing draft when boss confirms resolve / early close."""
    outcome_key = str(outcome or "succeeded").strip().lower()
    if outcome_key == "error":
        outcome_key = "failed"
    note_text = str(note or "").strip()
    work = str(work_result or "").strip()
    err = str(error or "").strip()

    if outcome_key == "cancelled":
        base = brief_cancel_summary(task_text=task_text, reason=note_text or err or "用户提前关闭")
        if work and "当时进度" not in base:
            base = base.rstrip() + "\n\n## Agent 回合输出\n" + work[:4000]
        return base

    if looks_like_markdown_summary(work):
        draft = work
    else:
        draft = wrap_summary_draft(work or err, outcome=outcome_key, task_text=task_text)

    if note_text:
        draft = draft.rstrip() + f"\n\n## 关闭说明\n{note_text}"
    return draft
