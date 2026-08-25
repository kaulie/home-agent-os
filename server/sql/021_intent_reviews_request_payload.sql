-- Persist the Ark HTTP request body and full API JSON for model replay/compare.
-- Assistant text stays in raw_response. Do not store Authorization / API keys.
-- Do not edit 001–020. No secondary indexes.

ALTER TABLE intent_reviews ADD COLUMN request_payload TEXT;
ALTER TABLE intent_reviews ADD COLUMN response_json TEXT;
