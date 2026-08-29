"""Mac Edge local NetEase song catalog (ncm-cli search records)."""

from mac_edge.ncm_songs.store import (
    NcmSongsError,
    db_path,
    find_by_norm,
    get_song,
    init_db,
    list_library,
    list_recent_played,
    mark_played,
    normalize_text,
    upsert_record,
)

__all__ = [
    "NcmSongsError",
    "db_path",
    "find_by_norm",
    "get_song",
    "init_db",
    "list_library",
    "list_recent_played",
    "mark_played",
    "normalize_text",
    "upsert_record",
]
