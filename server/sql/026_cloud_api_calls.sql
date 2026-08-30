-- Append-only cloud API call counters for Dev Console stats.
-- Do not edit 001–025 (already applied). No FK.

CREATE TABLE cloud_api_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_id TEXT NOT NULL,
  occurred_at REAL NOT NULL,
  ok INTEGER NOT NULL,
  source TEXT NOT NULL
);

CREATE INDEX idx_cloud_api_calls_occurred_service
  ON cloud_api_calls(occurred_at, service_id);
CREATE INDEX idx_cloud_api_calls_service_occurred
  ON cloud_api_calls(service_id, occurred_at);
