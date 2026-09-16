"""tts_file — 文本 → 可播放音频（切块 / 截断 / MP3 拼接 / 双引擎）。

风格对齐 test_pdf_to_images.py：不依赖网络（edge 用假 edge_tts 模块），
say 路径 mock subprocess；断言失败信息是明确中文。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.plugins import tts_file
from mac_edge.plugins.tts_file import (
    TtsFileError,
    TtsResult,
    clamp_speed,
    concat_mp3,
    resolve_edge_voice,
    split_text_for_tts,
    synthesize_speech,
    truncate_text,
)

_AUDIO_BYTES = b"\xff\xfb\x90\x00" + b"M" * 2000


def _fake_edge_tts() -> types.SimpleNamespace:
    class Communicate:
        def __init__(self, text: str, voice: str, rate: str | None = None) -> None:
            self.text = text
            self.voice = voice
            self.rate = rate

        async def save(self, path: str) -> None:
            if not str(self.text).strip():
                raise ValueError("empty text")
            Path(path).write_bytes(_AUDIO_BYTES)

    return types.SimpleNamespace(Communicate=Communicate)


class SplitTests(unittest.TestCase):
    def test_splits_long_text_at_sentence_boundary(self) -> None:
        text = "第一句。" * 200
        chunks = split_text_for_tts(text, max_chars=200)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks[:-1]:
            self.assertLessEqual(len(chunk), 200)
            self.assertTrue(chunk.endswith("。"))
        self.assertEqual("".join(chunks), text)

    def test_short_text_is_single_chunk(self) -> None:
        self.assertEqual(split_text_for_tts("一句话。"), ["一句话。"])

    def test_empty_text(self) -> None:
        self.assertEqual(split_text_for_tts("   "), [])

    def test_overlong_sentence_is_hard_split(self) -> None:
        chunks = split_text_for_tts("甲" * 500, max_chars=200)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(c) <= 200 for c in chunks))


class TruncateTests(unittest.TestCase):
    def test_no_truncation_under_limit(self) -> None:
        self.assertEqual(truncate_text("很短。", 100), ("很短。", False))

    def test_zero_limit_means_no_truncation(self) -> None:
        text = "甲" * 500
        self.assertEqual(truncate_text(text, 0), (text, False))

    def test_truncates_on_sentence_boundary(self) -> None:
        text = "一二三。四五六。七八九。"
        body, truncated = truncate_text(text, 5)
        self.assertTrue(truncated)
        self.assertEqual(body, "一二三。")

    def test_hard_cut_when_no_boundary(self) -> None:
        body, truncated = truncate_text("甲" * 100, 10)
        self.assertTrue(truncated)
        self.assertEqual(body, "甲" * 10)


class SpeedAndVoiceTests(unittest.TestCase):
    def test_speed_default_and_clamp(self) -> None:
        self.assertEqual(clamp_speed(None), 1.0)
        self.assertEqual(clamp_speed("1.5"), 1.5)
        self.assertEqual(clamp_speed(9), tts_file.MAX_SPEED)
        self.assertEqual(clamp_speed(0.1), tts_file.MIN_SPEED)

    def test_invalid_speed_is_chinese(self) -> None:
        with self.assertRaises(TtsFileError) as ctx:
            clamp_speed("快一点")
        self.assertIn("speed", str(ctx.exception))
        with self.assertRaises(TtsFileError):
            clamp_speed(0)

    def test_edge_voice_by_lang_and_env(self) -> None:
        with patch.dict("os.environ", {"MAC_EDGE_PDF_READER_VOICE": ""}, clear=False):
            self.assertEqual(resolve_edge_voice(None, "zh_CN"), tts_file.DEFAULT_EDGE_VOICE_ZH)
            self.assertEqual(resolve_edge_voice(None, "en_US"), tts_file.DEFAULT_EDGE_VOICE_EN)
            self.assertEqual(resolve_edge_voice("zh-CN-YunxiNeural", "zh_CN"), "zh-CN-YunxiNeural")
        with patch.dict("os.environ", {"MAC_EDGE_PDF_READER_VOICE": "自定义音色"}, clear=False):
            self.assertEqual(resolve_edge_voice(None, "zh_CN"), "自定义音色")


class ConcatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _part(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def _id3v2(self, payload: bytes, size: int) -> bytes:
        header = b"ID3\x03\x00\x00" + bytes(
            [(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]
        )
        return header + b"\x00" * size + payload

    def test_concatenates_frames_and_strips_later_tags(self) -> None:
        first = self._part("a.mp3", _AUDIO_BYTES)
        second = self._part("b.mp3", self._id3v2(_AUDIO_BYTES, 16))
        dest = concat_mp3([first, second], self.root / "all.mp3")
        data = dest.read_bytes()
        self.assertEqual(data, _AUDIO_BYTES + _AUDIO_BYTES)

    def test_strips_id3v1_tail(self) -> None:
        first = self._part("a.mp3", _AUDIO_BYTES + b"TAG" + b"\x00" * 125)
        dest = concat_mp3([first], self.root / "all.mp3")
        self.assertEqual(dest.read_bytes(), _AUDIO_BYTES)

    def test_empty_parts_fail(self) -> None:
        with self.assertRaises(TtsFileError):
            concat_mp3([], self.root / "all.mp3")


class SynthesizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_empty_text_fails(self) -> None:
        with self.assertRaises(TtsFileError) as ctx:
            synthesize_speech("   ", self.root, backend="say")
        self.assertIn("没有可合成的文字", str(ctx.exception))

    def test_unknown_backend_fails(self) -> None:
        with self.assertRaises(TtsFileError) as ctx:
            synthesize_speech("你好。", self.root, backend="whisper")
        self.assertIn("未知 TTS 后端", str(ctx.exception))

    def test_edge_backend_chunks_and_concats(self) -> None:
        with patch.dict(sys.modules, {"edge_tts": _fake_edge_tts()}):
            result = synthesize_speech(
                "第一句。第二句。第三句。",
                self.root,
                stem="doc",
                backend="edge",
                chunk_chars=200,
            )
        self.assertIsInstance(result, TtsResult)
        self.assertEqual(result.engine, "edge")
        self.assertEqual(result.mime_type, "audio/mpeg")
        self.assertEqual(result.voice, tts_file.DEFAULT_EDGE_VOICE_ZH)
        self.assertTrue(result.path.is_file())
        self.assertTrue(result.path.name.endswith(".mp3"))
        self.assertGreaterEqual(result.path.stat().st_size, tts_file.MIN_AUDIO_BYTES)

    def test_edge_failure_falls_back_to_say(self) -> None:
        if not tts_file.say_available():
            self.skipTest("macOS say not installed")
        with patch.object(tts_file, "_synthesize_edge", side_effect=TtsFileError("edge 挂了")):
            with patch.object(
                tts_file,
                "_synthesize_say",
                return_value=TtsResult(
                    path=self.root / "x.m4a",
                    mime_type="audio/mp4",
                    engine="say",
                    voice="Tingting",
                ),
            ) as say:
                result = synthesize_speech("你好。", self.root, backend="edge")
        self.assertEqual(result.engine, "say")
        self.assertEqual(result.fallback_reason, "edge 挂了")
        say.assert_called_once()

    def test_edge_failure_without_fallback_raises(self) -> None:
        with patch.object(tts_file, "_synthesize_edge", side_effect=TtsFileError("edge 挂了")):
            with self.assertRaises(TtsFileError):
                synthesize_speech(
                    "你好。", self.root, backend="edge", allow_say_fallback=False
                )

    def test_say_backend_writes_aac_m4a(self) -> None:
        if not tts_file.say_available():
            self.skipTest("macOS say not installed")
        calls: list[list[str]] = []

        def _fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append([str(c) for c in cmd])
            if "-o" in cmd:
                Path(cmd[cmd.index("-o") + 1]).write_bytes(_AUDIO_BYTES)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch.object(tts_file.subprocess, "run", side_effect=_fake_run):
            result = synthesize_speech(
                "你好，这是测试。", self.root, stem="saydoc", backend="say", speed=1.5
            )
        self.assertEqual(result.engine, "say")
        self.assertEqual(result.mime_type, "audio/mp4")
        self.assertTrue(result.path.name.endswith(".m4a"))
        cmd = next(c for c in calls if "-o" in c)
        self.assertIn("--file-format=m4af", cmd)
        self.assertIn("--data-format=aac", cmd)
        self.assertIn("-f", cmd)  # 长文经文件传入，不走命令行
        self.assertEqual(cmd[cmd.index("-r") + 1], str(int(tts_file.DEFAULT_SAY_RATE_WPM * 1.5)))
        # 合成用的文字文件保留在工作目录，便于排查
        self.assertTrue((self.root / "saydoc-text.txt").is_file())

    def test_say_timeout_is_chinese(self) -> None:
        if not tts_file.say_available():
            self.skipTest("macOS say not installed")
        with patch.object(
            tts_file.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="say", timeout=1),
        ):
            with self.assertRaises(TtsFileError) as ctx:
                synthesize_speech("你好。", self.root, backend="say")
        self.assertIn("超时", str(ctx.exception))

