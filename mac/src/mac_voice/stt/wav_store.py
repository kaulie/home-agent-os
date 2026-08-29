"""STT WAV materialize path + retention for mac_voice."""

from __future__ import annotations

import logging
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mac_voice.audio.types import AudioUtterance

log = logging.getLogger("mac_voice.stt.wav_store")

_WAV_NAME = re.compile(r"^mac_voice_.+\.wav$", re.IGNORECASE)


@dataclass(frozen=True)
class SttWavStore:
    """Where to write STT input WAVs and how long to keep them.

    dir=None → system temp (historical default).
    keep=False → delete after STT (even if dir is set).
    Retention prune applies to fixed dir only (mac_voice_*.wav).
    """

    directory: Path | None
    keep: bool
    max_age_hours: float
    max_files: int
    max_mb: float

    def ensure_dir(self) -> None:
        if self.directory is None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)

    def materialize(self, utterance: AudioUtterance) -> tuple[Path, bool]:
        """Return (wav_path, owned). owned=True means caller may delete after STT."""
        if utterance.path is not None and utterance.path.is_file():
            return utterance.path, False

        self.ensure_dir()
        if self.directory is None:
            tmp = tempfile.NamedTemporaryFile(prefix="mac_voice_", suffix=".wav", delete=False)
            tmp.close()
            path = Path(tmp.name)
            utterance.materialize_wav(path)
            return path, not self.keep

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        ingress = (utterance.ingress or "unk").replace("/", "_")[:24]
        pid = (utterance.input_participant_id or "nopid").replace("/", "_")[:32]
        name = f"mac_voice_{stamp}_{ingress}_{pid}.wav"
        path = self.directory / name
        utterance.materialize_wav(path)
        self.prune()
        return path, not self.keep

    def release(self, path: Path, *, owned: bool) -> None:
        if not owned:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("failed to delete STT wav %s", path)

    def prune(self) -> None:
        if self.directory is None or not self.directory.is_dir():
            return
        files = [
            p
            for p in self.directory.iterdir()
            if p.is_file() and _WAV_NAME.match(p.name)
        ]
        if not files:
            return

        now = time.time()
        if self.max_age_hours > 0:
            cutoff = now - self.max_age_hours * 3600.0
            kept: list[Path] = []
            for p in files:
                try:
                    if p.stat().st_mtime < cutoff:
                        p.unlink(missing_ok=True)
                    else:
                        kept.append(p)
                except OSError:
                    kept.append(p)
            files = kept

        files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0)

        if self.max_files > 0 and len(files) > self.max_files:
            for p in files[: len(files) - self.max_files]:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            files = files[-self.max_files :]

        if self.max_mb > 0:
            budget = int(self.max_mb * 1024 * 1024)
            total = 0
            survivors: list[Path] = []
            for p in reversed(files):
                try:
                    size = p.stat().st_size
                except OSError:
                    continue
                if total + size > budget and survivors:
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue
                total += size
                survivors.append(p)
            # oldest excess already removed; nothing else
