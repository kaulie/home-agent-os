"""Shared errors for music_recognize package."""


class MusicRecognizeError(Exception):
    """User-visible failure of a music.recognize step (spoken via Brain)."""


class MusicCaptureError(MusicRecognizeError):
    """Mic capture could not be opened/run (hardware/device)."""
