-- Flatten jobs.payload_json into columns. Arrays/objects stay JSON per field.
-- Do not edit 001_init.sql (already applied).

CREATE TABLE jobs_flat (
  intent_id TEXT PRIMARY KEY,
  job_id TEXT,
  status TEXT NOT NULL,
  text TEXT,
  source TEXT,
  edge_id TEXT,
  assigned_edge_id TEXT,
  edge_node_id TEXT,
  scheduler_node TEXT,
  reply TEXT,
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
  pending_delivery TEXT,
  extra_json TEXT
);

INSERT INTO jobs_flat (
  intent_id, job_id, status, text, source, edge_id, assigned_edge_id,
  edge_node_id, scheduler_node, reply, error, msg, detail, command_id,
  base_time, intent_base_time, created_at, updated_at,
  execution_plan, steps, step_log, status_log, ctx_param, context,
  outputs, step_outputs, presentation, pending_delivery, extra_json
)
SELECT
  intent_id,
  COALESCE(json_extract(payload_json, '$.job_id'), intent_id),
  COALESCE(
    NULLIF(json_extract(payload_json, '$.intent_status'), ''),
    NULLIF(json_extract(payload_json, '$.status'), ''),
    status
  ),
  json_extract(payload_json, '$.text'),
  json_extract(payload_json, '$.source'),
  json_extract(payload_json, '$.edge_id'),
  COALESCE(json_extract(payload_json, '$.assigned_edge_id'), assigned_edge_id),
  json_extract(payload_json, '$.edge_node_id'),
  json_extract(payload_json, '$.scheduler_node'),
  json_extract(payload_json, '$.reply'),
  json_extract(payload_json, '$.error'),
  json_extract(payload_json, '$.msg'),
  json_extract(payload_json, '$.detail'),
  json_extract(payload_json, '$.command_id'),
  json_extract(payload_json, '$.base_time'),
  json_extract(payload_json, '$.intent_base_time'),
  created_at,
  updated_at,
  COALESCE(json_extract(payload_json, '$.execution_plan'), '[]'),
  json_extract(payload_json, '$.steps'),
  json_extract(payload_json, '$.step_log'),
  json_extract(payload_json, '$.status_log'),
  json_extract(payload_json, '$.ctx_param'),
  json_extract(payload_json, '$.context'),
  json_extract(payload_json, '$.outputs'),
  json_extract(payload_json, '$.step_outputs'),
  json_extract(payload_json, '$.presentation'),
  json_extract(payload_json, '$.pending_delivery'),
  NULL
FROM jobs;

DROP TABLE jobs;
ALTER TABLE jobs_flat RENAME TO jobs;

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_assigned ON jobs(assigned_edge_id);
