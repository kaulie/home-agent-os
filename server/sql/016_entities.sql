-- Entity Registry V1: World Model anchors (Device only).
-- Orthogonal to participants / assets / capabilities.
-- No secondary indexes. No FK. Do not edit 001–015.

CREATE TABLE entities (
  entity_id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type = 'device'),
  name TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  state_json TEXT NOT NULL DEFAULT '{}',
  references_json TEXT NOT NULL DEFAULT '{}',
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL
);

-- Seed: real living-room objects the system can already act on (not fiction).
-- Timestamps fixed so re-apply / IGNORE is stable.
INSERT OR IGNORE INTO entities(
  entity_id, type, name, metadata_json, state_json, references_json,
  created_at_ms, updated_at_ms
) VALUES
(
  'ent_dev_livingroom_ac',
  'device',
  '客厅空调',
  '{"room":"living-room","vendor":"hisense","kind_hint":"climate"}',
  '{}',
  '{"capability_ids":["climate.set"]}',
  1787295600000,
  1787295600000
),
(
  'ent_dev_livingroom_ceiling_light',
  'device',
  '客厅大灯',
  '{"room":"living-room","kind_hint":"light"}',
  '{}',
  '{"capability_ids":["light.set"]}',
  1787295600000,
  1787295600000
),
(
  'ent_dev_livingroom_gopro',
  'device',
  '客厅 GoPro',
  '{"room":"living-room","vendor":"gopro","kind_hint":"camera"}',
  '{}',
  '{"capability_ids":["camera.capture","camera.take_video"]}',
  1787295600000,
  1787295600000
),
(
  'ent_dev_livingroom_tv',
  'device',
  '客厅电视',
  '{"room":"living-room","kind_hint":"display"}',
  '{}',
  '{"capability_ids":["display.photo","display.slideshow"]}',
  1787295600000,
  1787295600000
);
