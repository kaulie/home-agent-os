"""TTS 语音合成底层：文本 → 可播放音频文件（只合成，不播放）。

被 `pdf.reader`（PDF 长文朗读）复用；`notify.speak`（播报一句话，合成即播放）
保持自己的合成+播放路径，本模块不改它。

后端（`MAC_EDGE_PDF_READER_TTS_BACKEND`，默认 `edge`）：

- `edge`：edge-tts 神经音色（中文默认 `zh-CN-XiaoxiaoNeural`，英文默认
  `en-US-AvaMultilingualNeural`）。长文按句切块，逐块合成 mp3 后按 MP3 帧拼接成
  一个 mp3（不需要 ffmpeg）→ mime `audio/mpeg`。

**音色选择（`lang` / `voice` 的优先级）**：显式 `voice` → 环境变量
`MAC_EDGE_PDF_READER_VOICE` → 显式 `lang` → 按**正文语言**自动判定
（`detect_lang`：CJK 字数 vs 拉丁词数）→ 该语言的默认音色
（env `MAC_EDGE_PDF_READER_VOICE_ZH` / `..._VOICE_EN` 可换）。

> 为什么要有自动判定：一篇英文论文若用中文音色朗读，会带明显口音、语调也不对，
> 听感「不自然」。`lang` 缺省（`None` / `"auto"`）时按正文判定，中英混排也不会翻错。
- `say`：macOS 本机 `say`（离线、无网络），一次性合成 AAC/m4a → mime `audio/mp4`。

edge 合成失败且 `MAC_EDGE_PDF_READER_TTS_FALLBACK_SAY` 非 `0`（默认开）时自动回退
`say`：`TtsResult.engine` 说明实际使用的引擎，`fallback_reason` 记下回退原因。

本模块只产出音频文件：不播放、不上传（上传登记由调用方经 CapAsset 完成）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mac_edge.plugins.text_lang import detect_lang, normalize_lang

log = logging.getLogger("mac_edge.tts_file")

DEFAULT_EDGE_VOICE_ZH = "zh-CN-XiaoxiaoNeural"
# 英文长文听读默认音色：multilingual 系列比 Aria/Jenny 等更接近真人播讲
DEFAULT_EDGE_VOICE_EN = "en-US-AvaMultilingualNeural"

VOICE_ENV_ANY = "MAC_EDGE_PDF_READER_VOICE"
VOICE_ENV_ZH = "MAC_EDGE_PDF_READER_VOICE_ZH"
VOICE_ENV_EN = "MAC_EDGE_PDF_READER_VOICE_EN"

SAY_BIN = "/usr/bin/say"
DEFAULT_SAY_RATE_WPM = 180

# 单块字数上限：块越大，块间接缝（每块一次独立合成的语气重置 + 尾静音）越少，
# 长文听感越连贯；单块合成耗时实测约 字数/220 秒，3000 字 ≈ 14s，仍远低于块超时。
DEFAULT_CHUNK_CHARS = 3000
DEFAULT_CHUNK_TIMEOUT_SEC = 30.0
# 单次合成总时长上限：必须小于 Edge 的 MAC_EDGE_CAPABILITY_TIMEOUT_SEC（默认 300s），
# 这样超时先出明确中文失败，而不是被 executor 硬杀。
DEFAULT_TOTAL_TIMEOUT_SEC = 240.0

MIN_SPEED = 0.5
MAX_SPEED = 2.0
MIN_AUDIO_BYTES = 512

_SENTENCE_END = "。！？；!?;\n"
_DURATION_RE = re.compile(r"estimated duration:\s*([0-9.]+)\s*sec")


class TtsFileError(Exception):
    """TTS 合成层明确中文失败（缺依赖 / 空文案 / 合成失败 / 超时）。"""


@dataclass(frozen=True)
class TtsResult:
    """合成产物：本地音频文件 + 实际引擎/音色/时长。"""

    path: Path
    mime_type: str
    engine: str
    voice: str
    duration_sec: float | None = None
    chunks: int = 1
    fallback_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "mime_type": self.mime_type,
            "engine": self.engine,
            "voice": self.voice,
            "duration_sec": self.duration_sec,
            "chunks": self.chunks,
            "fallback_reason": self.fallback_reason,
        }


def tts_backend() -> str:
    """合成后端：MAC_EDGE_PDF_READER_TTS_BACKEND=edge（默认）/ say。"""
    raw = (os.environ.get("MAC_EDGE_PDF_READER_TTS_BACKEND") or "edge").strip().lower()
    return raw if raw in ("edge", "say") else "edge"


def edge_available() -> bool:
    try:
        import edge_tts  # type: ignore  # noqa: F401

        return True
    except Exception:  # pragma: no cover - 缺依赖分支
        return False


def say_available() -> bool:
    return bool(shutil.which("say") or Path(SAY_BIN).exists())


def backend_available(backend: str) -> bool:
    chosen = str(backend or "").strip().lower()
    if chosen == "say":
        return say_available()
    if chosen == "edge":
        return edge_available()
    return False


def tts_available() -> bool:
    """本机有没有可用的朗读引擎（广告门控用）：edge-tts 或 macOS say。"""
    return edge_available() or say_available()


def clamp_speed(raw: Any) -> float:
    """语速倍率归一化（0.5–2.0）；非法值明确中文失败。"""
    text = str(raw if raw is not None else "").strip()
    if not text:
        return 1.0
    try:
        value = float(text)
    except (TypeError, ValueError) as e:
        raise TtsFileError(f"speed 必须是数字（{MIN_SPEED}–{MAX_SPEED}）：{raw!r}") from e
    if value <= 0:
        raise TtsFileError(f"speed 必须大于 0：{raw!r}")
    return max(MIN_SPEED, min(value, MAX_SPEED))


def resolve_edge_voice(voice: str | None, lang: str | None, *, text: str | None = None) -> str:
    """edge-tts 音色：显式 voice > env 全语言音色 > env 分语言音色 > 该语言默认。

    `lang` 为空（None / "" / "auto"）时按 `text` 正文语言自动判定。
    """
    explicit = str(voice or "").strip() or (os.environ.get(VOICE_ENV_ANY) or "").strip()
    if explicit:
        return explicit
    eff = normalize_lang(lang) or detect_lang(text or "")
    env_key = VOICE_ENV_ZH if eff.startswith("zh") else VOICE_ENV_EN
    env_voice = (os.environ.get(env_key) or "").strip()
    if env_voice:
        return env_voice
    return DEFAULT_EDGE_VOICE_ZH if eff.startswith("zh") else DEFAULT_EDGE_VOICE_EN


def resolve_say_voice(voice: str | None, lang: str | None, *, text: str | None = None) -> str | None:
    """macOS say 音色：显式 voice / env 全语言音色 > 按语言挑本机音色。

    分语言 env（`..._VOICE_ZH` / `..._VOICE_EN`）里放的是 edge 音色名，say 用不了，
    故本函数不读它们。
    """
    explicit = str(voice or "").strip() or (os.environ.get(VOICE_ENV_ANY) or "").strip()
    if explicit:
        return explicit
    eff = normalize_lang(lang) or detect_lang(text or "")
    from mac_edge.plugins.notify_speak import _pick_say_voice

    return _pick_say_voice(eff or "zh_CN")


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；!?;\n])", text or "")
    return [p.strip() for p in parts if p and p.strip()]


def split_text_for_tts(text: str, *, max_chars: int = DEFAULT_CHUNK_CHARS) -> list[str]:
    """长文按句切块（尽量不切断句子）；单句超长时硬切。"""
    limit = max(200, int(max_chars or DEFAULT_CHUNK_CHARS))
    out: list[str] = []
    buf = ""
    for sentence in _split_sentences(text):
        if len(sentence) > limit:
            if buf:
                out.append(buf)
                buf = ""
            for i in range(0, len(sentence), limit):
                piece = sentence[i : i + limit].strip()
                if piece:
                    out.append(piece)
            continue
        if buf and len(buf) + len(sentence) > limit:
            out.append(buf)
            buf = sentence
        else:
            buf += sentence
    if buf:
        out.append(buf)
    return out


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    """按字数上限截断（尽量落在句子边界）；max_chars<=0 视为不截断。"""
    body = (text or "").strip()
    limit = int(max_chars or 0)
    if limit <= 0 or len(body) <= limit:
        return body, False
    window = body[:limit]
    cut = max((window.rfind(ch) for ch in _SENTENCE_END), default=-1)
    if cut >= limit // 2:
        return window[: cut + 1].strip(), True
    return window.strip(), True


def _strip_id3v2(data: bytes) -> bytes:
    if len(data) < 10 or data[:3] != b"ID3":
        return data
    size = (
        (data[6] & 0x7F) << 21
        | (data[7] & 0x7F) << 14
        | (data[8] & 0x7F) << 7
        | (data[9] & 0x7F)
    )
    total = 10 + size
    if data[5] & 0x10:  # footer present
        total += 10
    return data[total:] if 0 < total < len(data) else data


def _strip_id3v1(data: bytes) -> bytes:
    if len(data) >= 128 and data[-128:-125] == b"TAG":
        return data[:-128]
    return data


def concat_mp3(parts: list[Path], dest: Path) -> Path:
    """把同一次合成的多个 mp3 按 MP3 帧拼接成一个文件（无需 ffmpeg）。

    后续分块去掉 ID3v2/ID3v1 标签（首块保留），只拼裸帧——MP3 帧可安全串接，
    afplay / AVPlayer / 浏览器均可整段播放。
    """
    if not parts:
        raise TtsFileError("合成失败：没有可拼接的音频段")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        for idx, part in enumerate(parts):
            data = Path(part).read_bytes()
            if idx > 0:
                data = _strip_id3v2(data)
            fh.write(_strip_id3v1(data))
    if not dest.is_file() or dest.stat().st_size < MIN_AUDIO_BYTES:
        raise TtsFileError("合成失败：拼接后的音频为空")
    return dest


def probe_duration_sec(path: str | Path) -> float | None:
    """音频时长（秒）：ffprobe 优先，macOS 回退 afinfo；都不可用返回 None。"""
    target = Path(path)
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            proc = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0 and (proc.stdout or "").strip():
                return round(float((proc.stdout or "").strip()), 3)
        except Exception as e:  # pragma: no cover - 探测失败不影响主流程
            log.debug("ffprobe duration failed: %s", e)
    afinfo = shutil.which("afinfo") or "/usr/bin/afinfo"
    if Path(afinfo).exists():
        try:
            proc = subprocess.run(
                [afinfo, str(target)], capture_output=True, text=True, timeout=10, check=False
            )
            match = _DURATION_RE.search(proc.stdout or "")
            if match:
                return round(float(match.group(1)), 3)
        except Exception as e:  # pragma: no cover
            log.debug("afinfo duration failed: %s", e)
    return None


def _edge_rate(speed: float) -> str:
    return f"{int(round((speed - 1.0) * 100)):+d}%"


async def _edge_save(edge_tts_mod: Any, text: str, out: Path, *, voice: str, rate: str) -> None:
    communicate = edge_tts_mod.Communicate(text, voice, rate=rate)
    await communicate.save(str(out))


def _total_timeout_sec() -> float:
    raw = (os.environ.get("MAC_EDGE_PDF_READER_TIMEOUT_SEC") or "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            log.warning("invalid MAC_EDGE_PDF_READER_TIMEOUT_SEC=%r — use default", raw)
    return DEFAULT_TOTAL_TIMEOUT_SEC


def _say_fallback_enabled() -> bool:
    raw = (os.environ.get("MAC_EDGE_PDF_READER_TTS_FALLBACK_SAY") or "1").strip().lower()
    return raw not in ("0", "off", "false", "no")


def _synthesize_edge(
    text: str,
    out_dir: Path,
    *,
    stem: str,
    voice: str | None,
    speed: float,
    lang: str,
    total_timeout_sec: float,
    chunk_timeout_sec: float,
    chunk_chars: int,
) -> TtsResult:
    try:
        import edge_tts  # type: ignore
    except ImportError as e:
        raise TtsFileError("本机未安装 edge-tts（pip install edge-tts），无法用神经音色朗读") from e

    pick = resolve_edge_voice(voice, lang, text=text)
    rate = _edge_rate(speed)
    chunks = split_text_for_tts(text, max_chars=chunk_chars)
    if not chunks:
        raise TtsFileError("朗读失败：没有可合成的文字")
    deadline = time.monotonic() + max(5.0, float(total_timeout_sec))
    parts: list[Path] = []
    for index, chunk in enumerate(chunks, start=1):
        if time.monotonic() > deadline:
            raise TtsFileError(
                f"edge-tts 合成超时：已完成 {len(parts)}/{len(chunks)} 段"
                f"（上限 {total_timeout_sec:.0f}s）"
            )
        out = out_dir / f"{stem}-part{index:03d}.mp3"
        try:
            asyncio.run(
                asyncio.wait_for(
                    _edge_save(edge_tts, chunk, out, voice=pick, rate=rate),
                    timeout=chunk_timeout_sec,
                )
            )
        except TimeoutError as e:
            raise TtsFileError(
                f"edge-tts 合成第 {index}/{len(chunks)} 段超时（{chunk_timeout_sec:.0f}s）"
            ) from e
        except Exception as e:
            raise TtsFileError(f"edge-tts 合成第 {index}/{len(chunks)} 段失败：{e}") from e
        if not out.is_file() or out.stat().st_size < MIN_AUDIO_BYTES:
            raise TtsFileError(f"edge-tts 合成第 {index}/{len(chunks)} 段失败：音频为空")
        parts.append(out)
    mp3 = concat_mp3(parts, out_dir / f"{stem}.mp3")
    log.info(
        "edge-tts ok voice=%s lang=%s rate=%s chunks=%s bytes=%s",
        pick,
        lang or "auto",
        rate,
        len(chunks),
        mp3.stat().st_size,
    )
    return TtsResult(
        path=mp3,
        mime_type="audio/mpeg",
        engine="edge",
        voice=pick,
        duration_sec=probe_duration_sec(mp3),
        chunks=len(chunks),
    )


def _synthesize_say(
    text: str,
    out_dir: Path,
    *,
    stem: str,
    voice: str | None,
    speed: float,
    lang: str,
    timeout_sec: float,
) -> TtsResult:
    say_bin = shutil.which("say") or SAY_BIN
    if not say_bin or not Path(say_bin).exists():
        raise TtsFileError("本机找不到 macOS say，无法合成朗读音频")
    pick = resolve_say_voice(voice, lang, text=text)
    rate = int(round(DEFAULT_SAY_RATE_WPM * speed))
    out = out_dir / f"{stem}.m4a"
    text_path = out_dir / f"{stem}-text.txt"
    text_path.write_text(text, encoding="utf-8")
    cmd = [say_bin]
    if pick:
        cmd.extend(["-v", pick])
    cmd.extend(
        [
            "-r",
            str(rate),
            "--file-format=m4af",
            "--data-format=aac",
            "-o",
            str(out),
            "-f",
            str(text_path),
        ]
    )
    log.info("tts say voice=%s rate=%s chars=%s", pick or "(default)", rate, len(text))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(5.0, float(timeout_sec)),
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise TtsFileError(f"say 合成超时（{timeout_sec:.0f}s）") from e
    except OSError as e:
        raise TtsFileError(f"say 启动失败：{e}") from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise TtsFileError(f"say 合成失败：{err}")
    if not out.is_file() or out.stat().st_size < MIN_AUDIO_BYTES:
        raise TtsFileError("say 合成失败：音频为空")
    return TtsResult(
        path=out,
        mime_type="audio/mp4",
        engine="say",
        voice=pick or "default",
        duration_sec=probe_duration_sec(out),
        chunks=1,
    )


def synthesize_speech(
    text: str,
    work_dir: str | Path,
    *,
    stem: str = "speech",
    backend: str | None = None,
    voice: str | None = None,
    speed: Any = None,
    lang: str | None = None,
    total_timeout_sec: float | None = None,
    chunk_timeout_sec: float = DEFAULT_CHUNK_TIMEOUT_SEC,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    allow_say_fallback: bool | None = None,
) -> TtsResult:
    """把 text 合成成一个可播放音频文件（只合成，不播放、不上传）。

    backend 缺省取 `tts_backend()`（env `MAC_EDGE_PDF_READER_TTS_BACKEND`）。
    lang 缺省（None / "" / "auto"）时按正文语言自动判定音色（见模块 docstring）。
    """
    body = (text or "").strip()
    if not body:
        raise TtsFileError("朗读失败：没有可合成的文字")
    out_dir = Path(work_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r"[^A-Za-z0-9一-鿿_-]", "-", str(stem or "speech")).strip("-") or "speech"
    chosen = str(backend or "").strip().lower() or tts_backend()
    spd = clamp_speed(speed)
    total = float(total_timeout_sec) if total_timeout_sec is not None else _total_timeout_sec()
    eff_lang = normalize_lang(lang) or detect_lang(body)

    if chosen == "say":
        return _synthesize_say(
            body, out_dir, stem=safe_stem, voice=voice, speed=spd, lang=eff_lang, timeout_sec=total
        )
    if chosen != "edge":
        raise TtsFileError(f"未知 TTS 后端 {chosen!r}：支持 edge / say")

    try:
        return _synthesize_edge(
            body,
            out_dir,
            stem=safe_stem,
            voice=voice,
            speed=spd,
            lang=eff_lang,
            total_timeout_sec=total,
            chunk_timeout_sec=chunk_timeout_sec,
            chunk_chars=chunk_chars,
        )
    except TtsFileError as e:
        fallback = _say_fallback_enabled() if allow_say_fallback is None else bool(allow_say_fallback)
        if not fallback or not say_available():
            raise
        log.warning("edge-tts 合成失败（%s）— 回退 macOS say", e)
        result = _synthesize_say(
            body, out_dir, stem=safe_stem, voice=voice, speed=spd, lang=eff_lang, timeout_sec=total
        )
        return replace(result, fallback_reason=str(e))
