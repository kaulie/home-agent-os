"""Audio abstractions for mac_voice (provider-agnostic)."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2  # bytes (16-bit)

    @property
    def bits(self) -> int:
        return self.sample_width * 8


PCM_16K_MONO = AudioFormat()


@dataclass
class AudioUtterance:
    """One recognisable clip. Prefer pcm; path is optional cache/source."""

    format: AudioFormat = PCM_16K_MONO
    pcm: bytes | None = None
    path: Path | None = None
    speech_start: float | None = None  # monotonic; energy crossed threshold
    speech_end: float | None = None  # monotonic; last voice before trailing silence

    @classmethod
    def from_wav_path(cls, path: str | Path) -> AudioUtterance:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"WAV not found: {p}")
        with wave.open(str(p), "rb") as wf:
            fmt = AudioFormat(
                sample_rate=wf.getframerate(),
                channels=wf.getnchannels(),
                sample_width=wf.getsampwidth(),
            )
            pcm = wf.readframes(wf.getnframes())
        return cls(format=fmt, pcm=pcm, path=p)

    @classmethod
    def from_pcm(
        cls,
        pcm: bytes,
        *,
        format: AudioFormat = PCM_16K_MONO,
        speech_start: float | None = None,
        speech_end: float | None = None,
    ) -> AudioUtterance:
        return cls(
            format=format,
            pcm=pcm,
            path=None,
            speech_start=speech_start,
            speech_end=speech_end,
        )

    def ensure_pcm(self) -> bytes:
        if self.pcm is not None:
            return self.pcm
        if self.path is not None:
            loaded = self.from_wav_path(self.path)
            self.pcm = loaded.pcm
            self.format = loaded.format
            return self.pcm or b""
        raise ValueError("AudioUtterance has neither pcm nor path")

    def materialize_wav(self, dest: Path) -> Path:
        """Write a standard WAV file for backends that only accept paths."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        pcm = self.ensure_pcm()
        fmt = self.format
        with wave.open(str(dest), "wb") as wf:
            wf.setnchannels(fmt.channels)
            wf.setsampwidth(fmt.sample_width)
            wf.setframerate(fmt.sample_rate)
            wf.writeframes(pcm)
        return dest


class AudioSource(Protocol):
    """Device → PCM chunks. Optional for Phase 1 (file CLI is enough)."""

    def open(self) -> None: ...

    def close(self) -> None: ...

    def iter_pcm(self, chunk_ms: int = 100) -> Iterator[bytes]: ...
