-- Brain SQLite v1 (phase 1). Nested wire payloads stay JSON; queryable keys are columns.
-- Contract: docs/db-schema.md

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO meta(key, value) VALUES ('next_intent_id', '1');

-- Logistics / intent_detail (_JOBS)
CREATE TABLE IF NOT EXISTS jobs (
  intent_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  assigned_edge_id TEXT,
  payload_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_assigned ON jobs(assigned_edge_id);

-- Edge pull queue (_PENDING_INTENTS). FIFO by position. Pop deletes the row.
CREATE TABLE IF NOT EXISTS intent_queue (
  intent_id TEXT PRIMARY KEY,
  position INTEGER NOT NULL,
  status TEXT NOT NULL,
  assigned_edge_id TEXT,
  payload_json TEXT NOT NULL,
  updated_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_intent_queue_position ON intent_queue(position);
CREATE INDEX IF NOT EXISTS idx_intent_queue_status ON intent_queue(status);
CREATE INDEX IF NOT EXISTS idx_intent_queue_assigned ON intent_queue(assigned_edge_id);

-- Register archive + last heartbeat snapshot
CREATE TABLE IF NOT EXISTS edges (
  edge_id TEXT PRIMARY KEY,
  registration_json TEXT NOT NULL,
  heartbeat_json TEXT,
  updated_at REAL NOT NULL
);
