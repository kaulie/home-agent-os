-- Replace edges with participants (Participant + Role + Contract).
-- Do not edit 001–003 (already applied).

CREATE TABLE participants (
  participant_id TEXT PRIMARY KEY,
  client_hint TEXT,
  display_name TEXT,
  device_type TEXT,
  room TEXT,
  app_version TEXT,
  status TEXT NOT NULL,
  registered_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  role_intent_source INTEGER NOT NULL DEFAULT 0,
  role_runtime INTEGER NOT NULL DEFAULT 0,
  role_endpoint INTEGER NOT NULL DEFAULT 0,
  role_observer INTEGER NOT NULL DEFAULT 0,
  services TEXT,
  intent_sources TEXT,
  endpoints TEXT,
  observer_events TEXT,
  online_status TEXT,
  health TEXT,
  client_time_ms INTEGER,
  brain_time_ms INTEGER,
  clock_skew_ms INTEGER,
  schedule_eligible INTEGER,
  schedule_reject_reason TEXT,
  reported_at REAL,
  server_received_at REAL
);

INSERT INTO participants (
  participant_id, client_hint, display_name, device_type, room, app_version,
  status, registered_at, updated_at,
  role_intent_source, role_runtime, role_endpoint, role_observer,
  services, intent_sources, endpoints, observer_events,
  online_status, health, client_time_ms, brain_time_ms, clock_skew_ms,
  schedule_eligible, schedule_reject_reason, reported_at, server_received_at
)
SELECT
  edge_id,
  json_extract(registration_json, '$.client_hint'),
  json_extract(registration_json, '$.display_name'),
  json_extract(registration_json, '$.device_type'),
  json_extract(registration_json, '$.room'),
  json_extract(registration_json, '$.app_version'),
  COALESCE(json_extract(registration_json, '$.status'), 'approved'),
  COALESCE(json_extract(registration_json, '$.registered_at'), updated_at),
  updated_at,
  CASE WHEN json_array_length(json_extract(registration_json, '$.intent_sources')) > 0 THEN 1 ELSE 0 END,
  CASE WHEN json_array_length(COALESCE(
    CASE WHEN json_array_length(json_extract(registration_json, '$.services')) > 0
         THEN json_extract(registration_json, '$.services') END,
    json_extract(heartbeat_json, '$.services')
  )) > 0 THEN 1 ELSE 0 END,
  CASE WHEN json_array_length(json_extract(registration_json, '$.endpoints')) > 0 THEN 1 ELSE 0 END,
  CASE WHEN json_array_length(json_extract(registration_json, '$.observer_events')) > 0 THEN 1 ELSE 0 END,
  COALESCE(
    CASE WHEN json_array_length(json_extract(registration_json, '$.services')) > 0
         THEN json_extract(registration_json, '$.services') END,
    json_extract(heartbeat_json, '$.services')
  ),
  json_extract(registration_json, '$.intent_sources'),
  json_extract(registration_json, '$.endpoints'),
  json_extract(registration_json, '$.observer_events'),
  json_extract(heartbeat_json, '$.online_status'),
  json_extract(heartbeat_json, '$.health'),
  json_extract(heartbeat_json, '$.client_time_ms'),
  json_extract(heartbeat_json, '$.brain_time_ms'),
  json_extract(heartbeat_json, '$.clock_skew_ms'),
  json_extract(heartbeat_json, '$.schedule_eligible'),
  json_extract(heartbeat_json, '$.schedule_reject_reason'),
  json_extract(heartbeat_json, '$.reported_at'),
  COALESCE(
    json_extract(heartbeat_json, '$.server_received_at'),
    json_extract(registration_json, '$.server_received_at')
  )
FROM edges;

DROP TABLE edges;

CREATE INDEX idx_participants_room ON participants(room);
CREATE INDEX idx_participants_runtime ON participants(role_runtime);
CREATE INDEX idx_participants_online ON participants(online_status);
