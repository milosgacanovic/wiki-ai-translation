CREATE UNIQUE INDEX IF NOT EXISTS jobs_unique_queued
ON jobs (type, page_title, lang)
WHERE status = 'queued';
