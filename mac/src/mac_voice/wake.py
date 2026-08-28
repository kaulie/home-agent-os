"""STT wake-word gate: require the name repeated N times before posting an intent."""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Sequence

DEFAULT_WAKE_WORD = "面条"
DEFAULT_WAKE_REPEAT = 2
DEFAULT_WAKE_ALIASES = ("miantiao", "棉条", "面跳", "免条")
DEFAULT_COMMAND_WINDOW_MS = 5000
DEFAULT_PARTIAL_WAKE_MS = 2500
DEFAULT_WAKE_ACK = "又咋了"
# Give up waiting for 又咋了 and open the 5s command window anyway.
DEFAULT_ACK_WAIT_MS = 15000
# One 面条 is ~0.4–0.7s. Two in one utterance is typically ≥1.1s; STT often
# collapses 「面条面条」 to one token, so duration is the second vote.
DEFAULT_DOUBLE_WAKE_MS = 1100
# Drop TTS-echo clips that only spill a little past 又咋了; keep 几点了 that
# starts during the last syllable but ends well after the window opens.
_ECHO_OVERLAP_S = 0.45

# TTS/STT often doubles 又 or adds 啊/？ (「又又咋了？」).
_ACK_ECHO = re.compile(r"^((我)?在呢|又+咋[了啦][啊呀吗嘛]?|咋了[啊呀吗嘛]?)$")
# Speaker bleed mixed into a longer STT line (not a full-utterance match).
_ACK_EMBEDDED = re.compile(r"(我在呢|又+咋[了啦][啊呀吗嘛]?)")
# Same clip: 又咋了 immediately followed by the command.
_ACK_PREFIX = re.compile(r"^((我)?在呢|又+咋[了啦][啊呀吗嘛]?|咋了[啊呀吗嘛]?)")

_TRAILING_PUNCT = " \t.,!?;:，。！？、；：·…\"'“”‘’()（）[]【】"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").strip().lower()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def _unique_tokens(word: str, aliases: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in (word, *aliases):
        tok = normalize(raw)
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    out.sort(key=len, reverse=True)
    return tuple(out)


def _token_pattern(token: str) -> re.Pattern[str]:
    return re.compile(r"\s*".join(re.escape(ch) for ch in token), re.IGNORECASE)


def extract_wake(
    text: str,
    *,
    word: str = DEFAULT_WAKE_WORD,
    aliases: Sequence[str] = DEFAULT_WAKE_ALIASES,
) -> tuple[int, str]:
    """Return (wake_hit_count, leftover command). Hits are non-overlapping."""
    tokens = _unique_tokens(word, aliases)
    if not tokens:
        leftover = (text or "").strip()
        return 0, leftover

    norm = normalize(text)
    hits = 0
    i = 0
    rem_chars: list[str] = []
    while i < len(norm):
        matched = False
        for tok in tokens:
            if norm.startswith(tok, i):
                hits += 1
                i += len(tok)
                matched = True
                break
        if not matched:
            rem_chars.append(norm[i])
            i += 1
    norm_remainder = "".join(rem_chars)

    leftover = text or ""
    for tok in tokens:
        leftover = _token_pattern(tok).sub(" ", leftover)
    leftover = " ".join(leftover.split()).strip(_TRAILING_PUNCT)
    if not leftover:
        leftover = norm_remainder
    return hits, leftover


def _compact_ack_text(text: str) -> str:
    return re.sub(r"[\s，。！？,.!?\"'“”‘’]", "", text or "")


def looks_like_ack_echo(text: str) -> bool:
    compact = _compact_ack_text(text)
    return bool(_ACK_ECHO.match(compact))


_LIGHT_COMMAND_ECHO = frozenset(
    {normalize(x) for x in ("小书小书", "小书", "开灯", "关灯")}
)


def looks_like_light_command_echo(text: str) -> bool:
    """Drop light.set speaker bleed (开灯/关灯/小书小书) from mac_voice STT."""
    compact = normalize(text)
    return bool(compact) and compact in _LIGHT_COMMAND_ECHO


def contains_ack_echo(text: str) -> bool:
    """True when our spoken reply is in the transcript (alone or mixed)."""
    compact = _compact_ack_text(text)
    if not compact:
        return False
    if _ACK_ECHO.match(compact):
        return True
    return bool(_ACK_EMBEDDED.search(compact))


def strip_ack_echo(text: str) -> str:
    """Remove 又咋了 / 我在呢 so leftover can be the user's command."""
    raw = text or ""
    leftover = _ACK_EMBEDDED.sub(" ", raw)
    if leftover == raw:
        return raw.strip()
    leftover = " ".join(leftover.split()).strip(_TRAILING_PUNCT)
    return leftover


def command_after_ack_prefix(text: str) -> str:
    """If STT is 「又咋了」then the command in one line, return the command."""
    compact = _compact_ack_text(text)
    match = _ACK_PREFIX.match(compact)
    if not match:
        return ""
    rest = compact[match.end() :].strip()
    if not rest:
        return ""
    leftover = strip_ack_echo(text).strip()
    return leftover if leftover else rest


class WakeGate:
    """idle → partial → acking → listening; feed() returns a command or None.

    A wake sentence never posts leftover words. The 5s command window starts
    when STT recognizes 又咋了 (ack echo), or at arm_after_ack if that is
    later. Echo is never posted; it restarts the window from STT time so
    recognition latency does not eat the 5s. A standalone idle 「又咋了」 is
    not a wake. Late STT still counts when speech_start was inside the
    window, even if expire_if_needed already fired.
    """

    def __init__(
        self,
        *,
        word: str = DEFAULT_WAKE_WORD,
        repeat: int = DEFAULT_WAKE_REPEAT,
        aliases: Sequence[str] = DEFAULT_WAKE_ALIASES,
        command_window_ms: int = DEFAULT_COMMAND_WINDOW_MS,
        partial_wake_ms: int = DEFAULT_PARTIAL_WAKE_MS,
        double_wake_ms: int = DEFAULT_DOUBLE_WAKE_MS,
        ack_wait_ms: int = DEFAULT_ACK_WAIT_MS,
    ) -> None:
        self.word = (word or DEFAULT_WAKE_WORD).strip() or DEFAULT_WAKE_WORD
        self.repeat = max(1, int(repeat))
        self.aliases = tuple(aliases) if aliases else DEFAULT_WAKE_ALIASES
        self.command_window_s = max(0.2, command_window_ms / 1000.0)
        self.partial_wake_s = max(0.2, partial_wake_ms / 1000.0)
        self.double_wake_s = max(0.4, double_wake_ms / 1000.0)
        self.ack_wait_s = max(1.0, ack_wait_ms / 1000.0)
        self.state = "idle"
        self.should_ack = False
        self.last_hits = 0
        self._deadline = 0.0
        self._window_open_at = 0.0
        self._partial_hits = 0
        self._late_until = 0.0

    def _reset(self, *, keep_late_window: bool = False) -> None:
        late = (
            self._deadline
            if keep_late_window and self.state == "listening" and self._deadline > 0
            else 0.0
        )
        self.state = "idle"
        self.should_ack = False
        self.last_hits = 0
        self._deadline = 0.0
        self._window_open_at = 0.0
        self._partial_hits = 0
        self._late_until = late

    def expire_if_needed(
        self,
        now: float | None = None,
        *,
        hold: bool = False,
    ) -> str | None:
        """Close an empty command window. None unless the window just expired.

        ``hold`` when the mic is in an utterance or high-energy speech: do not
        expire. Timer expire keeps ``_late_until`` so a late STT whose
        speech_start was inside the window still posts.
        """
        t = time.monotonic() if now is None else now
        if hold:
            return None
        if self.state == "acking" and t > self._deadline:
            self._arm_command_window(self._deadline)
            return None
        if self.state == "listening" and t > self._deadline:
            self._reset(keep_late_window=True)
            return "command_window_expired"
        return None

    def consume_ack(self) -> bool:
        """True once per wake; caller must POST then forget the flag."""
        ack = self.should_ack
        self.should_ack = False
        return ack

    def arm_after_ack(self, now: float | None = None) -> None:
        """Fallback: open the window when local echo() returns.

        If the mic already heard 又咋了, keep that later deadline — TTS
        return can be earlier than the user actually hears the reply.
        """
        if self.state == "listening":
            return
        if self.state != "acking":
            return
        t = time.monotonic() if now is None else now
        self._arm_command_window(t)

    def _arm_command_window(self, t: float) -> None:
        self.state = "listening"
        self._partial_hits = 0
        self._window_open_at = t
        self._deadline = t + self.command_window_s
        self._late_until = 0.0

    def _heard_ack_echo(self, speech_end: float, now: float) -> None:
        """Full 5s after we recognize 又咋了 — not from the clip's speech_end."""
        self._arm_command_window(max(speech_end, now))

    def _enter_partial(self, speech_end: float, hits: int) -> None:
        self.state = "partial"
        self._partial_hits = hits
        self._deadline = speech_end + self.partial_wake_s

    def feed(
        self,
        text: str,
        now: float | None = None,
        *,
        speech_start: float | None = None,
        speech_end: float | None = None,
    ) -> str | None:
        now = time.monotonic() if now is None else now
        start = now if speech_start is None else speech_start
        end = now if speech_end is None else speech_end
        self.should_ack = False
        text = (text or "").strip()
        if not text:
            self.last_hits = 0
            return None

        if (
            self.state == "idle"
            and self._late_until > 0
            and start <= self._late_until
        ):
            self.state = "listening"
            self._deadline = self._late_until
            self._window_open_at = max(0.0, self._deadline - self.command_window_s)
            self._late_until = 0.0
            self._partial_hits = 0

        if self.state == "acking" and start > self._deadline:
            self._arm_command_window(self._deadline)
        elif self.state in ("partial", "listening") and start > self._deadline:
            self._reset()

        hits, remainder = extract_wake(text, word=self.word, aliases=self.aliases)
        duration = max(0.0, end - start)
        if (
            self.repeat >= 2
            and hits == 1
            and not remainder.strip()
            and duration >= self.double_wake_s
        ):
            hits = 2
        self.last_hits = hits
        if self.state == "listening":
            return self._on_listening(hits, remainder, end, text, start, now)
        if self.state == "acking":
            return self._on_acking(hits, end, text, remainder, start, now)
        if self.state == "partial":
            return self._on_partial(hits, end, text, now)
        return self._on_idle(hits, end, text, now)

    def _finish_wake(self, speech_end: float) -> None:
        """Wait for the spoken reply; leftover words are not posted."""
        self.state = "acking"
        self._partial_hits = 0
        self._deadline = speech_end + self.ack_wait_s
        self.should_ack = True

    def _on_idle(self, hits: int, speech_end: float, original: str, now: float) -> str | None:
        if hits >= self.repeat:
            self._finish_wake(speech_end)
            return None
        if hits > 0:
            self._enter_partial(speech_end, hits)
            return None
        same_clip = command_after_ack_prefix(original)
        if same_clip and not looks_like_ack_echo(same_clip):
            self._reset()
            return same_clip
        # TTS 又咋了 (maybe STT missed 面条面条) — open the window from STT time.
        if contains_ack_echo(original):
            self._arm_command_window(max(speech_end, now))
            return None
        return None

    def _on_partial(self, hits: int, speech_end: float, original: str, now: float) -> str | None:
        if hits == 0:
            same_clip = command_after_ack_prefix(original)
            if same_clip and not looks_like_ack_echo(same_clip):
                self._reset()
                return same_clip
            if contains_ack_echo(original):
                self._arm_command_window(max(speech_end, now))
                return None
            self._reset()
            return None
        total = self._partial_hits + hits
        if total >= self.repeat:
            self._finish_wake(speech_end)
            return None
        self._enter_partial(speech_end, total)
        return None

    def _on_acking(
        self,
        hits: int,
        speech_end: float,
        original: str,
        remainder: str,
        speech_start: float,
        now: float,
    ) -> str | None:
        if looks_like_ack_echo(original) or looks_like_ack_echo(remainder):
            self._heard_ack_echo(speech_end, now)
            return None
        if hits >= self.repeat:
            self._finish_wake(speech_end)
            return None
        leftover = strip_ack_echo(original).strip()
        if not leftover or looks_like_ack_echo(leftover):
            return None
        # User already said the command while Brain/TTS was still on 又咋了.
        self._reset()
        return leftover

    def _on_listening(
        self,
        hits: int,
        remainder: str,
        speech_end: float,
        original: str,
        speech_start: float,
        now: float,
    ) -> str | None:
        leftover = strip_ack_echo(original).strip()
        same_clip = command_after_ack_prefix(original)
        if same_clip and not looks_like_ack_echo(same_clip):
            self._reset()
            return same_clip
        if looks_like_ack_echo(original) or looks_like_ack_echo(remainder):
            self._heard_ack_echo(speech_end, now)
            return None
        if not leftover:
            return None
        # Echo of 又咋了 starts before the window. A real command (几点了) often
        # starts on the last syllable but finishes after arm_after_ack.
        before = self._window_open_at - speech_start
        after = speech_end - self._window_open_at
        if (
            speech_start < self._window_open_at
            and after <= _ECHO_OVERLAP_S
            and before >= after
        ):
            return None
        if hits >= self.repeat:
            self._finish_wake(speech_end)
            return None
        self._reset()
        return leftover
