"""Tests for structured Dev Agent analysis parsing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import debug_agent_analysis as daa  # noqa: E402


class FixRecommendationParserTests(unittest.TestCase):
    def test_parse_structured_items(self) -> None:
        text = """
### 建议 1：Brain 规划补 clock 步
- 优先级：P0
- 负责人：@brain
- 作用：报时类 intent 不再误派 query.content
- 预期收益：「现在几点」可稳定回答
- 改法：更新 planner prompt，加 clock.now 示例

### 建议 2：Runtime hydrate 失败 msg
优先级：P1
负责人：@runtime
作用：失败步返回可读错误
预期收益：用户反馈可定位到具体步
改法：executor 缺参时写 msg 字段
"""
        items = daa.parse_fix_recommendations(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "Brain 规划补 clock 步")
        self.assertEqual(items[0].priority, "P0")
        self.assertEqual(items[0].owner, "@brain")
        self.assertIn("clock.now", items[0].approach)
        self.assertEqual(items[1].priority, "P1")
        self.assertEqual(items[1].owner, "@runtime")


if __name__ == "__main__":
    unittest.main()
