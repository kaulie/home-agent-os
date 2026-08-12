"""Synced Brain wall clock for timingDue / miss-window (not raw local wall clock)."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class BrainTimeSync:
    brain_time_ms: int | None = None
    local_mono_at_sync: float | None = None

    def apply_heartbeat(self, brain_time_ms: int | None) -> None:
        if brain_time_ms is None:
            return
        try:
            ms = int(brain_time_ms)
        except (TypeError, ValueError):
            return
        if ms <= 0:
            return
        self.brain_time_ms = ms
        self.local_mono_at_sync = time.monotonic()

    def now_ms(self) -> int:
        """Brain time + monotonic elapsed since last heartbeat sync."""
        if self.brain_time_ms is None or self.local_mono_at_sync is None:
            return int(time.time() * 1000)
        elapsed = time.monotonic() - self.local_mono_at_sync
        return int(self.brain_time_ms + elapsed * 1000)


# Process-wide clock used by executor eligibility.
BRAIN_CLOCK = BrainTimeSync()
