-- jobs.intent_id TEXT -> INTEGER PRIMARY KEY AUTOINCREMENT.
-- Do not edit 001–012.

CREATE TABLE jobs_v13 (
  intent_id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  status TEXT NOT NULL,
  text TEXT,
  source TEXT,
  edge_id TEXT,
  assigned_edge_id TEXT,
  edge_node_id TEXT,
  scheduler_node TEXT,
  error TEXT,
  msg TEXT,
  detail TEXT,
  command_id TEXT,
  base_time INTEGER,
  intent_base_time INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  execution_plan TEXT NOT NULL DEFAULT '[]',
  steps TEXT,
  step_log TEXT,
  status_log TEXT,
  ctx_param TEXT,
  context TEXT,
  outputs TEXT,
  step_outputs TEXT,
  presentation TEXT,
  pending_delivery TEXT
);

INSERT INTO jobs_v13 (
  intent_id, job_id, status, text, source, edge_id, assigned_edge_id,
  edge_node_id, scheduler_node, error, msg, detail, command_id,
  base_time, intent_base_time, created_at, updated_at,
  execution_plan, steps, step_log, status_log, ctx_param, context,
  outputs, step_outputs, presentation, pending_delivery
)
SELECT
  CAST(intent_id AS INTEGER),
  job_id, status, text, source, edge_id, assigned_edge_id,
  edge_node_id, scheduler_node, error, msg, detail, command_id,
  base_time, intent_base_time, created_at, updated_at,
  execution_plan, steps, step_log, status_log, ctx_param, context,
  outputs, step_outputs, presentation, pending_delivery
FROM jobs;

DROP TABLE jobs;
ALTER TABLE jobs_v13 RENAME TO jobs;

INSERT INTO sqlite_sequence(name, seq)
SELECT 'jobs', (SELECT COALESCE(MAX(intent_id), 0) FROM jobs)
WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'jobs');

UPDATE sqlite_sequence
SET seq = (SELECT COALESCE(MAX(intent_id), 0) FROM jobs)
WHERE name = 'jobs';
