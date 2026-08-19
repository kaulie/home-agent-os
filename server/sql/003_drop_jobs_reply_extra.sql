-- Drop unused jobs columns. Do not edit 001/002 (already applied).

ALTER TABLE jobs DROP COLUMN reply;
ALTER TABLE jobs DROP COLUMN extra_json;
