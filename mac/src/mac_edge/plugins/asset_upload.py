"""Mac Edge capability: asset.upload — push inbox capture or existing Asset to dest.

Only sees this step's resolved params (capture_ref / asset_ref + dest).
Does not scan img-server directories, step_outputs, or phone albums.

Storage backends live in Runtime Asset Manager. Google Drive / Dropbox are
slots that fail with a readable msg until implemented.
"""

from __future__ import annotations

import logging
from typing import Any

from mac_edge.asset.img_upload import (
    ImgUploadError,
    display_upload_dest,
    normalize_upload_dest,
)
from mac_edge.asset.sdk import CapAsset
from mac_edge.asset.types import AssetError
from mac_edge.capture import store as capture_store
from mac_edge.capture.store import CaptureStoreError

log = logging.getLogger("mac_edge.asset_upload")


class AssetUploadError(Exception):
    pass


def upload_from_params(
    params: dict[str, Any] | None,
    *,
    asset: CapAsset,
) -> tuple[str, dict[str, Any]]:
    raw = params if isinstance(params, dict) else {}
    if asset is None:
        raise AssetUploadError("asset.upload requires CapAsset (Runtime SDK)")
    dest_raw = raw.get("dest") or raw.get("upload_dest") or "img_server"
    dest = normalize_upload_dest(str(dest_raw))
    wire_dest = display_upload_dest(dest)

    cid = capture_store.parse_capture_id(raw.get("capture_ref"))
    parsed_asset = None
    if raw.get("asset_ref") is not None:
        parsed_asset = asset.parse_ref(raw.get("asset_ref"))
    if cid is None and parsed_asset is None:
        try:
            cid = capture_store.unique_pending(wire_dest)
        except CaptureStoreError as e:
            raise AssetUploadError(str(e)) from e

    if cid:
        try:
            path = capture_store.open_jpeg(cid)
        except CaptureStoreError as e:
            raise AssetUploadError(str(e)) from e
        try:
            new_ref = asset.upload_local_file(path, dest=dest)
        except ImgUploadError as e:
            raise AssetUploadError(str(e)) from e
        except AssetError as e:
            raise AssetUploadError(str(e)) from e
        capture_store.mark_uploaded(cid, wire_dest)
        outputs: dict[str, Any] = {
            "asset_ref": new_ref.to_dict(),
            "dest": wire_dest,
        }
        msg = (
            f"asset.upload dest={wire_dest}\n"
            f"asset_id: {new_ref.asset_id}"
        )
        log.info(
            "asset.upload ok dest=%s asset_id=%s capture_id=%s",
            wire_dest,
            new_ref.asset_id,
            cid,
        )
        return msg, outputs

    try:
        ref = asset.require_ref(raw)
    except AssetError as e:
        raise AssetUploadError(str(e)) from e
    try:
        new_ref = asset.upload_to(ref, dest=dest)
    except ImgUploadError as e:
        raise AssetUploadError(str(e)) from e
    except AssetError as e:
        raise AssetUploadError(str(e)) from e
    outputs = {
        "asset_ref": new_ref.to_dict(),
        "dest": wire_dest,
    }
    msg = (
        f"asset.upload dest={wire_dest}\n"
        f"asset_id: {new_ref.asset_id}"
    )
    log.info("asset.upload ok dest=%s asset_id=%s", wire_dest, new_ref.asset_id)
    return msg, outputs
