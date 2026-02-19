ALTER TABLE translations
ADD COLUMN IF NOT EXISTS source_checksum TEXT;

CREATE INDEX IF NOT EXISTS idx_translations_lang_source_checksum
ON translations (lang, source_checksum);
