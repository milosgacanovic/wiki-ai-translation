CREATE TABLE IF NOT EXISTS pages (
  title TEXT PRIMARY KEY,
  source_lang TEXT NOT NULL,
  last_source_rev BIGINT
);

CREATE TABLE IF NOT EXISTS jobs (
  id BIGSERIAL PRIMARY KEY,
  type TEXT NOT NULL,
  page_title TEXT NOT NULL,
  lang TEXT NOT NULL,
  status TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  retries INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS segments (
  id BIGSERIAL PRIMARY KEY,
  page_title TEXT NOT NULL,
  segment_key TEXT NOT NULL,
  source_text TEXT NOT NULL,
  checksum TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (page_title, segment_key)
);

CREATE TABLE IF NOT EXISTS translations (
  id BIGSERIAL PRIMARY KEY,
  segment_key TEXT NOT NULL,
  lang TEXT NOT NULL,
  text TEXT NOT NULL,
  engine TEXT NOT NULL,
  qa_status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (segment_key, lang)
);

CREATE TABLE IF NOT EXISTS termbase (
  id BIGSERIAL PRIMARY KEY,
  lang TEXT NOT NULL,
  term TEXT NOT NULL,
  preferred TEXT NOT NULL,
  forbidden BOOLEAN NOT NULL DEFAULT FALSE,
  notes TEXT,
  UNIQUE (lang, term)
);

CREATE TABLE IF NOT EXISTS style_guides (
  id BIGSERIAL PRIMARY KEY,
  lang TEXT NOT NULL UNIQUE,
  rules_json JSONB NOT NULL
);
