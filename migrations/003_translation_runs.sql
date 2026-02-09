CREATE TABLE IF NOT EXISTS translation_runs (
    id BIGSERIAL PRIMARY KEY,
    mode TEXT NOT NULL,
    target_langs TEXT NOT NULL,
    skip_title_prefixes TEXT NOT NULL,
    disclaimer_marker TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT
);

CREATE TABLE IF NOT EXISTS run_items (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES translation_runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    page_title TEXT,
    lang TEXT,
    status TEXT NOT NULL,
    message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS run_items_run_id_idx ON run_items(run_id);
CREATE INDEX IF NOT EXISTS run_items_status_idx ON run_items(status);
