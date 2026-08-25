"""Dropbox upload backend — slot only."""

from __future__ import annotations

from pathlib import Path

from mac_edge.asset.img_upload import ImgUploadError, UploadResult


def upload_file(path: Path) -> UploadResult:
    raise ImgUploadError(
        "dest=dropbox is not implemented yet (Dropbox is a plugin slot only)"
    )
