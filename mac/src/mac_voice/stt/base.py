"""Speech-to-text provider interface."""

from __future__ import annotations

from typing import Protocol

from mac_voice.audio.types import AudioUtterance


class SpeechToText(Protocol):
    async def transcribe(self, utterance: AudioUtterance) -> str:
        """Return final transcript text (may be empty)."""
        ...
