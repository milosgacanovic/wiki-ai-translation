from __future__ import annotations

import argparse
import logging

from .config import load_config
from .logging import configure_logging
from .mediawiki import MediaWikiClient
from .db import get_conn
from .jobs import next_jobs, mark_job_done, mark_job_error
from .ingest import ingest_all, ingest_title
from .scheduler import run_poll_loop
from .translate_page import main as translate_page_main


def _engine_lang_for(lang: str) -> str:
    if lang == "sr":
        return "sr-Latn"
    return lang


def process_queue(cfg, client) -> None:
    with get_conn(cfg.pg_dsn) as conn:
        jobs = next_jobs(conn, limit=5)
        for job in jobs:
            try:
                if job.type == "translate_page":
                    import sys
                    sys.argv = [
                        "translate_page",
                        "--title",
                        job.page_title,
                        "--lang",
                        job.lang,
                        "--engine-lang",
                        _engine_lang_for(job.lang),
                        "--auto-approve",
                        "--sleep-ms",
                        "800",
                    ]
                    translate_page_main()
                mark_job_done(conn, job.id)
            except Exception as exc:
                mark_job_error(conn, job.id, str(exc))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-title", help="process only a specific title")
    parser.add_argument("--ingest-title", help="ingest a single title (wrap + enqueue)")
    parser.add_argument("--ingest-all", action="store_true", help="ingest all main namespace pages")
    parser.add_argument("--ingest-limit", type=int, default=None)
    parser.add_argument("--ingest-sleep-ms", type=int, default=0)
    parser.add_argument("--poll", action="store_true", help="run recentchanges poller")
    args, _ = parser.parse_known_args()

    configure_logging()
    cfg = load_config()

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    if args.ingest_title:
        with get_conn(cfg.pg_dsn) as conn:
            ingest_title(cfg, client, conn, args.ingest_title)
        return

    if args.ingest_all:
        with get_conn(cfg.pg_dsn) as conn:
            ingest_all(
                cfg,
                client,
                conn,
                sleep_ms=args.ingest_sleep_ms,
                limit=args.ingest_limit,
            )
        return

    if args.only_title:
        # run translation pipeline for a single page
        import sys
        for lang in cfg.target_langs:
            sys.argv = [
                "translate_page",
                "--title",
                args.only_title,
                "--lang",
                lang,
                "--engine-lang",
                _engine_lang_for(lang),
                "--auto-approve",
                "--sleep-ms",
                "800",
            ]
            translate_page_main()
        return

    if args.poll:
        run_poll_loop(cfg, client)
        return

    process_queue(cfg, client)


if __name__ == "__main__":
    main()
