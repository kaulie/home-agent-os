"""chat.smalltalk: text in → reply out."""

from __future__ import annotations

import unittest

from mac_edge.plugins.chat_smalltalk import (
    ChatSmalltalkError,
    smalltalk_from_params,
    smalltalk_reply,
)


class ChatSmalltalkTests(unittest.TestCase):
    def test_morning(self) -> None:
        out = smalltalk_reply(text="早啊")
        self.assertTrue(out["reply"])

    def test_hello(self) -> None:
        out = smalltalk_reply(text="你好啊")
        self.assertTrue(out["reply"])

    def test_thanks(self) -> None:
        out = smalltalk_reply(text="谢谢")
        self.assertIn(out["reply"], ("不客气～", "没事儿～", "应该的。"))

    def test_not_smalltalk(self) -> None:
        with self.assertRaises(ChatSmalltalkError):
            smalltalk_reply(text="为什么天是蓝的")

    def test_from_params(self) -> None:
        msg, out = smalltalk_from_params({"text": "嗨"})
        self.assertIn("chat.smalltalk", msg)
        self.assertTrue(out["reply"])


if __name__ == "__main__":
    unittest.main()
