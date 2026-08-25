-- jobs.intent_origin: which Brain accepted the intent (lan | cloud).
-- Control-plane origin of this process, not the user's physical location.
-- Do not edit 001–018. No secondary indexes. Historical rows stay NULL.

ALTER TABLE jobs ADD COLUMN intent_origin TEXT;
