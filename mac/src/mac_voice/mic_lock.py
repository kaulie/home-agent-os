"""Exclusive lock so only one mac_voice --live holds the USB mic."""

from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path
from typing import IO, TextIO

log = logging.getLogger("mac_voice.mic_lock")


def acquire_listen_lock(path: Path) -> IO[str]:
    """Block until this process owns ``path`` (fcntl LOCK_EX). Released on close()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh: TextIO = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.seek(0)
        holder = (fh.read() or "").strip() or "?"
        log.warning(
            "waiting for exclusive mic lock held by pid %s (%s)",
            holder,
            path,
        )
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        log.info("acquired mic lock after wait")
    fh.seek(0)
    fh.truncate()
    fh.write(f"{os.getpid()}\n")
    fh.flush()
    return fh
