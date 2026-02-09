import os
import pytest
import psycopg

from bot.config import Config
from bot.run_report import start_run, finish_run, log_item, write_report_file, report_last_run


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set")
def test_run_report_writes_file(tmp_path):
    dsn = os.getenv("DATABASE_URL")
    cfg = Config(
        mw_api_url="https://example.org/api.php",
        mw_username="bot",
        mw_password="secret",
        mw_user_agent="Test",
        pg_dsn=dsn,
    )

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
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
                """
            )
            cur.execute(
                """
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
                """
            )
        conn.commit()

        run_id = start_run(conn, "test", cfg)
        log_item(conn, run_id, "translate", "ok", "Page", "sr", None)
        finish_run(conn, run_id, "done")
        conn.commit()

        path = write_report_file(conn, run_id, directory=str(tmp_path))
        assert path.exists()
        assert "Translation Run" in path.read_text(encoding="utf-8")
        assert "translate:ok" in path.read_text(encoding="utf-8")

        report = report_last_run(conn)
        assert "run_id" in report
