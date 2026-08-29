"""Mac Edge local NetEase song catalog (ncm-cli search records)."""

from mac_edge.ncm_songs.store import (
    NcmSongsError,
    connect,
    db_path,
    find_by_name_artist,
    find_by_norm,
    find_index_by_name_artist,
    find_index_by_norm,
    get_index_song,
    get_song,
    init_db,
    list_library,
    list_recent_played,
    normalize_text,
    record_play,
    upsert_record,
)

__all__ = [
    "NcmSongsError",
    "connect",
    "db_path",
    "find_by_name_artist",
    "find_by_norm",
    "find_index_by_name_artist",
    "find_index_by_norm",
    "get_index_song",
    "get_song",
    "init_db",
    "list_library",
    "list_recent_played",
    "normalize_text",
    "record_play",
    "upsert_record",
]
