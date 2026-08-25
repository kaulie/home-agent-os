"""Upload dest → backend (img_server / cloud implemented; gdrive / dropbox slots)."""

from __future__ import annotations

from pathlib import Path

from mac_edge.asset.img_upload import (
    ImgUploadError,
    UploadResult,
    _upload_once,
    normalize_upload_dest,
)

IMPLEMENTED = frozenset({"lan", "cloud"})
STUBS = frozenset({"gdrive", "dropbox"})


def upload_file(path: Path, dest: str) -> UploadResult:
    """Push a local file to the named dest. Stubs fail with a readable msg."""
    canonical = normalize_upload_dest(dest)
    if canonical == "gdrive":
        from mac_edge.asset.backends import gdrive

        return gdrive.upload_file(path)
    if canonical == "dropbox":
        from mac_edge.asset.backends import dropbox

        return dropbox.upload_file(path)
    if canonical not in IMPLEMENTED:
        raise ImgUploadError(f"unsupported upload dest={dest!r}")
    return _upload_once(path, canonical)
