CREATE INDEX IF NOT EXISTS idx_segments_checksum ON segments (checksum);
CREATE INDEX IF NOT EXISTS idx_translations_lang_created_at ON translations (lang, created_at DESC);
