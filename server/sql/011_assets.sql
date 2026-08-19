-- Asset catalog + execution-scoped grants. Identity is asset_id.
-- Do not edit 001–010 (already applied). No secondary indexes. No blob/URL identity.

CREATE TABLE assets (
  asset_id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  mime_type TEXT,
  size INTEGER,
  status TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  expires_at REAL,
  creator TEXT,
  owner TEXT,
  intent_id TEXT,
  source_asset_id TEXT,
  producer TEXT,
  execution_id TEXT,
  metadata TEXT,
  storage TEXT
);

CREATE TABLE asset_grants (
  grant_id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT NOT NULL,
  execution_id TEXT NOT NULL,
  capability_id TEXT,
  permission TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL
);
