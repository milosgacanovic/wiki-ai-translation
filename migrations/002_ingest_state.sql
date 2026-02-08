CREATE TABLE IF NOT EXISTS ingest_state (
  name TEXT PRIMARY KEY,
  apcontinue TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
