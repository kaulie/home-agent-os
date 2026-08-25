"""Deterministic regexes for V1 feature extraction. No LLM, no jieba."""

from __future__ import annotations

import re

# Longer alternatives first: Python's `|` is left-first, not longest-match.
ACTION_RE = re.compile(
    r"打开|开启|关掉|关闭|开灯|关灯|开台灯|关台灯|调到|"
    r"打电话|打个电话|拨打|"
    r"拍一张|拍张照|拍张|拍照|拍一|拍|"
    r"投屏|投到|"
    r"放一首|播放|"
    r"告诉我|告诉|"
    r"大声念|念给|念出|播报|"
    r"扫描|扫一下|"
    r"计算|"
    r"连接|"
    r"暂停|"
    r"喂鱼|喂"
)

CONDITION_RE = re.compile(
    r"如果|要是|除非|否则|只有.{0,8}才|当.{0,8}时"
)

SEQUENCE_RE = re.compile(
    r"然后|之后|接着|再(?!见)|完成后|先.{0,12}再"
)

PARALLEL_RE = re.compile(
    r"同时|一起|分别|一边.{0,12}一边|全部|(?<![一不])都"
)

TEMPORAL_RE = re.compile(
    r"马上|现在|\d+\s*分钟后|晚上?\d+\s*点|每天|每周|明天|周末|后天"
)

CONTEXT_RE = re.compile(
    r"刚才|之前拍的|之前|那个|这个|上一个|最近的|刚刚|昨天|最后一张"
)

# Vague deixis / underspecified dimming without a device noun.
DEMONSTRATIVE_RE = re.compile(r"弄亮一点|弄暗一点|把它")

RECOGNIZE_SPLIT_RE = re.compile(r"[/、\s]+")

CJK_RE = re.compile(r"[\u3400-\u9fff]")
