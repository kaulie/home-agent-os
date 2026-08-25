-- Admin operation log (policy toggles / bulk replace). Not heartbeats or GETs.
-- Do not edit 001–016. No secondary indexes. No FK.

CREATE TABLE admin_op_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  actor TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL,
  participant_id TEXT NOT NULL DEFAULT '',
  target_kind TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '',
  extra TEXT,
  result TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT ''
);
