-- Pull queue is jobs.status. Copy queue-only rows into jobs, then drop intent_queue.
-- Do not edit 001–004 (already applied).

INSERT OR IGNORE INTO jobs (
  intent_id, job_id, status, text, source, edge_id, assigned_edge_id,
  scheduler_node, command_id, base_time, intent_base_time,
  created_at, updated_at, execution_plan, steps, step_log, status_log,
  ctx_param, context, outputs, step_outputs, presentation, pending_delivery
)
SELECT
  intent_id,
  intent_id,
  COALESCE(NULLIF(status, ''), 'intent_parsed'),
  json_extract(payload_json, '$.text'),
  json_extract(payload_json, '$.source'),
  json_extract(payload_json, '$.edge_id'),
  COALESCE(assigned_edge_id, json_extract(payload_json, '$.assigned_edge_id')),
  json_extract(payload_json, '$.scheduler_node'),
  json_extract(payload_json, '$.command_id'),
  json_extract(payload_json, '$.base_time'),
  json_extract(payload_json, '$.intent_base_time'),
  updated_at,
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
  json_extract(payload_json, '$.pending_delivery')
FROM intent_queue;

DROP TABLE intent_queue;
