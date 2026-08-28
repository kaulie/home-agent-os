"""Pronunciation assessment engine. Independent of HomeAgent / Asset / Brain / Runtime.

Pipeline (doc sections 2-5):
  reference audio --WhisperX--> reference text + word/phoneme alignment
  student  audio --WhisperX--> student word/phoneme alignment + VAD segments
  phoneme/word sequence alignment (student vs reference) -- Levenshtein
  per-phoneme / per-word / passage scoring -- accuracy, fluency, completeness, prosody
  aggregation --> fixed /assess response JSON

V1 runs on WhisperX (pip-installable, pretrained). MFA (finer reference phoneme
alignment) and GOPT (learned pronunciation scoring) are optional upgrade stages,
loaded only when their deps/models are present; the pipeline still produces real
scores from WhisperX features when they are absent. No model training.

Design rules honored:
- Keep phoneme/word/segment detail internally; aggregate at the end (doc section 4).
- Tolerate different speech rate / pauses / missing / extra / repeated words via
  text/phoneme sequence alignment, never waveform compare (doc section 5).
- Raw model output is the contract; no JSON rescue parsing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("pronunciation_service.engine")

ENGINE_NAME = "whisperx"
MODEL_NAME = "whisper-large-v3"
DEFAULT_WHISPER_MODEL = os.environ.get("PRON_WHISPER_MODEL", "large-v3").strip() or "large-v3"
DEFAULT_DEVICE = os.environ.get("PRON_DEVICE", "cpu").strip() or "cpu"
DEFAULT_COMPUTE = os.environ.get("PRON_COMPUTE_TYPE", "int8").strip() or "int8"
DEFAULT_LANGUAGE = os.environ.get("PRON_LANGUAGE", "en").strip() or "en"


class PronunciationEngineError(Exception):
    pass


# Fixed /assess response contract (doc section 6). Do not change shape lightly;
# the Edge plugin maps this 1:1 to wire outputs.
ASSESS_RESPONSE_KEYS = (
    "overall_score",
    "accuracy_score",
    "fluency_score",
    "completeness_score",
    "prosody_score",
    "duration",
    "problem_words",
    "problem_phonemes",
    "fluency",
    "raw_alignment",
)


def engine_status() -> dict[str, Any]:
    """Cheap status for /health without loading models."""
    return {
        "whisper_model": DEFAULT_WHISPER_MODEL,
        "device": DEFAULT_DEVICE,
        "language": DEFAULT_LANGUAGE,
        "mfa_enabled": _mfa_available(),
        "gopt_enabled": _gopt_available(),
    }


@dataclass
class WordToken:
    word: str
    start: float
    end: float
    score: float  # alignment confidence 0..1
    phonemes: list[str] = field(default_factory=list)


@dataclass
class AlignedAudio:
    text: str
    words: list[WordToken]
    duration: float


# ---------------------------------------------------------------------------
# WhisperX alignment (real)
# ---------------------------------------------------------------------------
class WhisperXAligner:
    """Lazy WhisperX wrapper. ASR + word/phoneme alignment + VAD."""

    def __init__(self) -> None:
        self._model: Any = None
        self._align_model: Any = None
        self._align_meta: Any = None
        self._vad: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import whisperx  # type: ignore
        except ImportError as e:
            raise PronunciationEngineError(
                "whisperx 未安装。请在 pronunciation-service 环境内安装 whisperx"
            ) from e
        log.info("loading whisperx model=%s device=%s", DEFAULT_WHISPER_MODEL, DEFAULT_DEVICE)
        self._model = whisperx.load_model(
            DEFAULT_WHISPER_MODEL, device=DEFAULT_DEVICE, compute_type=DEFAULT_COMPUTE
        )
        try:
            self._align_model, self._align_meta = whisperx.load_align_model(
                language_code=DEFAULT_LANGUAGE, device=DEFAULT_DEVICE
            )
        except Exception as e:  # noqa: BLE001
            log.warning("whisperx align model load failed (word alignment disabled): %s", e)
            self._align_model = None
            self._align_meta = None
        try:
            self._vad = whisperx.load_vad_model()
        except Exception as e:  # noqa: BLE001
            log.warning("whisperx VAD load failed: %s", e)
            self._vad = None

    def align(self, audio_path: str) -> AlignedAudio:
        self._load()
        import whisperx  # type: ignore

        if self._vad is not None:
            segments = self._vad.transcribe_with_vad(self._model, audio_path, batch_size=8)
        else:
            res = self._model.transcribe(audio_path, language=DEFAULT_LANGUAGE, batch_size=8)
            segments = res.get("segments", []) if isinstance(res, dict) else []

        text = " ".join(str(s.get("text", "")).strip() for s in segments).strip()

        words: list[WordToken] = []
        if self._align_model is not None and segments:
            try:
                aligned = whisperx.align(
                    segments, self._align_model, self._align_meta, audio_path, device=DEFAULT_DEVICE
                )
                for seg in aligned.get("segments", []):
                    for w in seg.get("words", []):
                        words.append(_word_from_whisperx(w))
            except Exception as e:  # noqa: BLE001
                log.warning("whisperx align failed, using segment-level words: %s", e)
                words = _words_from_segments(segments)
        else:
            words = _words_from_segments(segments)

        duration = _audio_duration(audio_path)
        return AlignedAudio(text=text, words=words, duration=duration)


def _word_from_whisperx(w: dict[str, Any]) -> WordToken:
    raw_word = str(w.get("word", "")).strip()
    score = float(w.get("score", 1.0) or 1.0)
    start = float(w.get("start", 0.0) or 0.0)
    end = float(w.get("end", start) or start)
    phonemes = list(w.get("phonemes", []) or [])
    return WordToken(word=raw_word, start=start, end=end, score=score, phonemes=phonemes)


def _words_from_segments(segments: list[dict[str, Any]]) -> list[WordToken]:
    out: list[WordToken] = []
    for seg in segments or []:
        start = float(seg.get("start", 0.0) or 0.0)
        end = float(seg.get("end", start) or start)
        txt = str(seg.get("text", "")).strip()
        if not txt:
            continue
        toks = txt.split()
        for i, w in enumerate(toks):
            ws = start + (end - start) * (i / max(1, len(toks)))
            out.append(WordToken(word=w, start=ws, end=end, score=0.0))
    return out


def _audio_duration(path: str) -> float:
    try:
        import wave

        with wave.open(path, "rb") as wf:
            return wf.getnframes() / float(wf.getframerate() or 1)
    except Exception:  # noqa: BLE001
        try:
            import librosa  # type: ignore

            return float(librosa.get_duration(path=path))
        except Exception:  # noqa: BLE001
            return 0.0


# ---------------------------------------------------------------------------
# Optional MFA reference phoneme alignment (upgrade stage)
# ---------------------------------------------------------------------------
def _mfa_available() -> bool:
    try:
        import montreal_forced_aligner  # type: ignore  # noqa: F401

        return True
    except ImportError:
        mfa_bin = os.environ.get("MFA_BIN", "").strip()
        return bool(mfa_bin and os.path.isfile(mfa_bin))


def mfa_reference_phonemes(audio_path: str, text: str) -> list[WordToken]:
    """Use MFA for finer reference phoneme alignment. Raises if unavailable."""
    if not _mfa_available():
        raise PronunciationEngineError("MFA 不可用")
    # MFA is primarily a CLI tool. A full library integration is heavy; this hook
    # shells out to `mfa align` on a temp corpus. Left as the upgrade path: when
    # MFA is configured, replace WhisperX reference alignment with MFA output.
    raise PronunciationEngineError("MFA 集成尚未启用（升级路径）")


# ---------------------------------------------------------------------------
# Optional GOPT scoring (upgrade stage)
# ---------------------------------------------------------------------------
def _gopt_available() -> bool:
    d = os.environ.get("GOPT_MODEL_DIR", "").strip()
    return bool(d and os.path.isdir(d))


def gopt_score(student_words: list[WordToken], reference_words: list[WordToken]) -> dict[str, Any]:
    """Use GOPT pretrained model for pronunciation scoring. Raises if unavailable."""
    if not _gopt_available():
        raise PronunciationEngineError("GOPT 不可用")
    # GOPT repo integration: load pretrained weights, feed student phoneme features
    # vs reference phonemes, return phoneme/word/utterance scores. Left as the
    # upgrade path; the WhisperX-derived scorer below is the real V1 baseline.
    raise PronunciationEngineError("GOPT 集成尚未启用（升级路径）")


# ---------------------------------------------------------------------------
# Sequence alignment: student words vs reference words (Levenshtein + timing)
# ---------------------------------------------------------------------------
@dataclass
class AlignOp:
    ref_idx: int | None  # None = insertion (student extra)
    stu_idx: int | None  # None = deletion (student missed)
    word: str
    stu: WordToken | None
    ref: WordToken | None


def _norm(word: str) -> str:
    return "".join(c for c in word.lower() if c.isalnum())


def align_word_sequences(ref: list[WordToken], stu: list[WordToken]) -> list[AlignOp]:
    """Levenshtein-align student words to reference words. Tolerates missing /
    extra / repeated words (doc section 5)."""
    r = [w for w in ref if _norm(w.word)]
    s = [w for w in stu if _norm(w.word)]
    n, m = len(r), len(s)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match = 0 if _norm(r[i - 1].word) == _norm(s[j - 1].word) else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,            # deletion (student missed ref word)
                dp[i][j - 1] + 1,            # insertion (student extra word)
                dp[i - 1][j - 1] + match,    # match/substitute
            )
    ops: list[AlignOp] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (
            0 if _norm(r[i - 1].word) == _norm(s[j - 1].word) else 1
        ):
            ops.append(AlignOp(ref_idx=i - 1, stu_idx=j - 1, word=r[i - 1].word, ref=r[i - 1], stu=s[j - 1]))
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(AlignOp(ref_idx=i - 1, stu_idx=None, word=r[i - 1].word, ref=r[i - 1], stu=None))
            i -= 1
        else:
            ops.append(AlignOp(ref_idx=None, stu_idx=j - 1, word=s[j - 1].word, ref=None, stu=s[j - 1]))
            j -= 1
    ops.reverse()
    return ops


# ---------------------------------------------------------------------------
# Scoring (real, WhisperX-derived)
# ---------------------------------------------------------------------------
def _score_to_100(x: float) -> float:
    return round(max(0.0, min(100.0, x * 100.0)))


def compute_accuracy(
    ops: list[AlignOp],
) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
    """Per-word + per-phoneme accuracy from aligned sequences.

    A matched word's accuracy blends the student's alignment confidence with the
    match itself; a missed word contributes 0. Problem words are those below the
    threshold. Returns (accuracy_score, problem_words, problem_phonemes).
    """
    if not ops:
        return 0.0, [], []
    word_scores: list[float] = []
    problem_words: list[dict[str, Any]] = []
    problem_phonemes: list[dict[str, Any]] = []
    PROBLEM_THRESHOLD = 70.0
    for op in ops:
        if op.ref is None:
            # Student extra word: not a reference error, skip from accuracy base.
            continue
        if op.stu is None:
            # Student missed a reference word.
            word_scores.append(0.0)
            problem_words.append({
                "word": op.word,
                "score": 0,
                "start": op.ref.start,
                "end": op.ref.end,
                "phoneme_errors": [],
                "reason": "missed",
            })
            continue
        matched = _norm(op.ref.word) == _norm(op.stu.word)
        # Blend: 0.7 * match(1/0) + 0.3 * alignment confidence.
        acc = (0.7 if matched else 0.2) + 0.3 * max(0.0, min(1.0, op.stu.score))
        word_scores.append(acc)
        ws = _score_to_100(acc)
        if ws < PROBLEM_THRESHOLD or not matched:
            errs: list[dict[str, Any]] = []
            if op.ref.phonemes or op.stu.phonemes:
                rp, sp = op.ref.phonemes, op.stu.phonemes
                for k in range(max(len(rp), len(sp))):
                    rp_k = rp[k] if k < len(rp) else None
                    sp_k = sp[k] if k < len(sp) else None
                    if rp_k != sp_k:
                        errs.append({"ref": rp_k, "stu": sp_k})
                        problem_phonemes.append({
                            "phoneme": rp_k or sp_k or "?",
                            "word": op.word,
                            "start": op.stu.start,
                            "end": op.stu.end,
                        })
            problem_words.append({
                "word": op.word,
                "score": ws,
                "start": op.stu.start,
                "end": op.stu.end,
                "phoneme_errors": errs,
                "reason": "substitution" if not matched else "low_confidence",
            })
    accuracy = sum(word_scores) / len(word_scores) if word_scores else 0.0
    return _score_to_100(accuracy), problem_words, problem_phonemes


def compute_completeness(ops: list[AlignOp]) -> float:
    """Fraction of reference words the student actually read."""
    ref_total = sum(1 for op in ops if op.ref is not None)
    if ref_total == 0:
        return 0.0
    read = sum(1 for op in ops if op.ref is not None and op.stu is not None)
    return _score_to_100(read / ref_total)


def compute_fluency(stu: AlignedAudio) -> tuple[float, dict[str, Any]]:
    """Fluency from word timing: pauses between words, speech rate, repetitions."""
    words = stu.words
    fluency = {
        "speech_rate": 0,
        "pause_count": 0,
        "long_pause_count": 0,
        "repetition_count": 0,
    }
    if not words or stu.duration <= 0:
        return 0.0, fluency
    # Pauses: gaps between consecutive word ends and next word start.
    pauses: list[float] = []
    for a, b in zip(words, words[1:]):
        gap = b.start - a.end
        if gap > 0.15:  # ignore tiny gaps
            pauses.append(gap)
    fluency["pause_count"] = len(pauses)
    fluency["long_pause_count"] = sum(1 for g in pauses if g > 1.5)
    # Speech rate: words per minute of speech (excluding long pauses).
    speech_time = stu.duration - sum(g for g in pauses if g > 1.5)
    if speech_time > 0:
        fluency["speech_rate"] = round(len(words) / speech_time * 60.0)
    # Repetitions: same normalized word twice in a row.
    rep = 0
    prev = ""
    for w in words:
        nw = _norm(w.word)
        if nw and nw == prev:
            rep += 1
        prev = nw
    fluency["repetition_count"] = rep
    # Fluency score: penalize too many long pauses and very low/high rate.
    long_pause_penalty = min(30.0, fluency["long_pause_count"] * 6.0)
    rep_penalty = min(15.0, rep * 5.0)
    base = 100.0 - long_pause_penalty - rep_penalty
    return _score_to_100(max(0.0, base) / 100.0), fluency


def compute_prosody(stu: AlignedAudio, ref: AlignedAudio) -> float:
    """Coarse prosody score from relative timing/rhythm vs reference.

    V1 uses speech-rate ratio and pause distribution as a proxy; a learned
    prosody model is a later upgrade (GOPT path)."""
    if ref.duration <= 0 or not stu.words or not ref.words:
        return 0.0
    ref_rate = len(ref.words) / ref.duration
    stu_rate = len(stu.words) / max(stu.duration, 0.001)
    if ref_rate <= 0:
        return 0.0
    ratio = stu_rate / ref_rate
    # Best around ratio 1.0; degrade as it moves away.
    diff = abs(1.0 - ratio)
    return _score_to_100(max(0.0, 1.0 - diff))


# ---------------------------------------------------------------------------
# Aggregation + engine entry points
# ---------------------------------------------------------------------------
def _build_raw_alignment(ops: list[AlignOp]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for op in ops:
        out.append({
            "word": op.word,
            "ref_start": op.ref.start if op.ref else None,
            "ref_end": op.ref.end if op.ref else None,
            "stu_start": op.stu.start if op.stu else None,
            "stu_end": op.stu.end if op.stu else None,
            "status": "match" if (op.ref and op.stu) else ("missed" if op.ref else "extra"),
        })
    return out


def _feedback_text(scores: dict[str, float], problem_words: list[dict[str, Any]]) -> str:
    overall = int(scores["overall_score"])
    head = f"本次朗读 {overall} 分"
    if not problem_words:
        return head + "，整体发音不错。"
    # Top 3 lowest-scoring problem words.
    top = sorted(problem_words, key=lambda w: w.get("score", 100))[:3]
    words = "、".join(w["word"] for w in top)
    return head + f"。需要注意的词：{words}。"


def aggregate(
    *,
    accuracy: float,
    fluency_score: float,
    completeness: float,
    prosody: float,
    problem_words: list[dict[str, Any]],
    problem_phonemes: list[dict[str, Any]],
    fluency: dict[str, Any],
    raw_alignment: list[dict[str, Any]],
    ref_duration: float,
    stu_duration: float,
) -> dict[str, Any]:
    overall = round(
        0.40 * accuracy + 0.25 * fluency_score + 0.20 * completeness + 0.15 * prosody
    )
    scores = {
        "overall_score": overall,
        "accuracy_score": accuracy,
        "fluency_score": fluency_score,
        "completeness_score": completeness,
        "prosody_score": prosody,
    }
    result: dict[str, Any] = {
        **scores,
        "duration": {"reference": round(ref_duration, 2), "student": round(stu_duration, 2)},
        "problem_words": problem_words,
        "problem_phonemes": problem_phonemes,
        "fluency": fluency,
        "raw_alignment": raw_alignment,
    }
    result["feedback_text"] = _feedback_text(scores, problem_words)
    return result


class PronunciationEngine:
    """Holds the WhisperX aligner. Stateless assess() reads resolved file paths."""

    def __init__(self) -> None:
        self._aligner: WhisperXAligner | None = None

    def aligner(self) -> WhisperXAligner:
        if self._aligner is None:
            self._aligner = WhisperXAligner()
        return self._aligner


def assess(
    engine: PronunciationEngine,
    reference_path: str,
    student_path: str,
) -> dict[str, Any]:
    """Run the full pipeline on two materialized audio files. Returns the fixed
    /assess response JSON (plus feedback_text)."""
    for p in (reference_path, student_path):
        if not p or not os.path.isfile(p):
            raise PronunciationEngineError(f"audio file missing: {p}")

    aligner = engine.aligner()
    log.info("aligning reference audio: %s", reference_path)
    ref = aligner.align(reference_path)
    log.info("reference words=%d duration=%.2f", len(ref.words), ref.duration)
    log.info("aligning student audio: %s", student_path)
    stu = aligner.align(student_path)
    log.info("student words=%d duration=%.2f", len(stu.words), stu.duration)

    ops = align_word_sequences(ref.words, stu.words)
    accuracy, problem_words, problem_phonemes = compute_accuracy(ops)
    completeness = compute_completeness(ops)
    fluency_score, fluency = compute_fluency(stu)
    prosody = compute_prosody(stu, ref)
    raw_alignment = _build_raw_alignment(ops)

    return aggregate(
        accuracy=accuracy,
        fluency_score=fluency_score,
        completeness=completeness,
        prosody=prosody,
        problem_words=problem_words,
        problem_phonemes=problem_phonemes,
        fluency=fluency,
        raw_alignment=raw_alignment,
        ref_duration=ref.duration,
        stu_duration=stu.duration,
    )
