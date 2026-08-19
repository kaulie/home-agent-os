"""Asset identity generation."""

from __future__ import annotations

import secrets


def new_asset_id() -> str:
    return "asset_" + secrets.token_hex(12)
