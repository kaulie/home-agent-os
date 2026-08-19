-- Align assets / asset_grants to Asset Manager design v2.
-- No photo_url dual-write. Do not edit 001–011.

DROP TABLE IF EXISTS asset_grants;
DROP TABLE IF EXISTS assets;

CREATE TABLE assets (
  asset_id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  mime_type TEXT,
  status TEXT NOT NULL,
  producer_capability TEXT,
  producer_edge_id TEXT,
  origin_intent_id TEXT,
  origin_step INTEGER,
  size_bytes INTEGER,
  metadata TEXT,
  storage TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  expires_at REAL
);

CREATE TABLE asset_grants (
  asset_id TEXT NOT NULL,
  intent_id TEXT NOT NULL,
  granted_at REAL NOT NULL,
  PRIMARY KEY (asset_id, intent_id)
);
