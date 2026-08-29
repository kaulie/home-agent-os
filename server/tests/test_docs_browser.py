"""Tests for docs_browser."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from docs_browser import (  # noqa: E402
    DocsBrowserError,
    list_documents,
    read_document,
    resolve_doc_path,
)


class DocsBrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "agent-coordination.md").write_text("# Coord\n", encoding="utf-8")
        sub = self.root / "docs" / "architecture"
        sub.mkdir(parents=True)
        (sub / "dual-brain.md").write_text("## Brain\n", encoding="utf-8")
        skip = self.root / "pyenv" / "lib"
        skip.mkdir(parents=True)
        (skip / "ignored.md").write_text("nope\n", encoding="utf-8")
        self._old = __import__("os").environ.get("DOCS_ROOT")
        __import__("os").environ["DOCS_ROOT"] = str(self.root)

    def tearDown(self) -> None:
        if self._old is None:
            __import__("os").environ.pop("DOCS_ROOT", None)
        else:
            __import__("os").environ["DOCS_ROOT"] = self._old
        self.tmp.cleanup()

    def test_list_documents(self) -> None:
        docs = list_documents()
        paths = {d["path"] for d in docs}
        self.assertEqual(
            paths,
            {"agent-coordination.md", "docs/architecture/dual-brain.md"},
        )

    def test_read_document(self) -> None:
        doc = read_document("docs/architecture/dual-brain.md")
        self.assertIn("Brain", doc["content"])
        self.assertEqual(doc["path"], "docs/architecture/dual-brain.md")

    def test_reject_traversal(self) -> None:
        with self.assertRaises(DocsBrowserError):
            resolve_doc_path("../secrets.md")

    def test_reject_non_markdown(self) -> None:
        with self.assertRaises(DocsBrowserError):
            read_document("agent-coordination.txt")


if __name__ == "__main__":
    unittest.main()
