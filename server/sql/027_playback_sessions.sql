-- Current playback state per (scene, edge_id): TV PDF cast today, music etc. later.
-- Latest-wins upsert keyed on (scene, edge_id); not an append-only event log.
-- position/total are scene-specific: tv_pdf = page/page_count; music = seconds/duration.

CREATE TABLE playback_sessions (
  session_id INTEGER PRIMARY KEY AUTOINCREMENT,
  scene TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  target TEXT,
  asset_id TEXT,
  position INTEGER,
  total INTEGER,
  state TEXT NOT NULL,
  payload TEXT,
  last_intent_id TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(scene, edge_id)
);
