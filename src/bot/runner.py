from __future__ import annotations

import argparse
import logging

from .config import load_config
from .logging import configure_logging
from .mediawiki import MediaWikiClient
from .db import get_conn
from .jobs import (
    next_jobs,
    mark_job_done,
    mark_job_error,
    count_jobs,
    delete_jobs_not_in_langs,
    delete_queued_jobs,
)
from .ingest import ingest_all, ingest_title
from .scheduler import run_poll_loop, poll_recent_changes
from .state import get_ingest_cursor, set_ingest_cursor
from .translate_page import main as translate_page_main
from .run_report import (
    start_run,
    finish_run,
    log_item,
    write_report_file,
    report_last_run,
    last_run_id,
    fetch_translate_ok_pairs,
)


def _engine_lang_for(lang: str) -> str:
    if lang == "sr":
        return "sr-Latn"
    return lang


def process_queue(
    cfg,
    client,
    run_id: int | None = None,
    progress: dict[str, int] | None = None,
    max_keys: int | None = None,
) -> None:
    with get_conn(cfg.pg_dsn) as conn:
        jobs = next_jobs(conn, limit=5)
        for job in jobs:
            try:
                if job.type == "translate_page":
                    if job.lang not in cfg.target_langs:
                        mark_job_done(conn, job.id)
                        if run_id is not None:
                            log_item(
                                conn,
                                run_id,
                                "translate",
                                "skip",
                                job.page_title,
                                job.lang,
                                "lang not in target_langs",
                            )
                        continue
                    if progress is not None:
                        progress["done"] += 1
                        total = progress["total"]
                        current = progress["done"]
                        print(f"{current}/{total} translate {job.page_title} ({job.lang})")
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
                    if max_keys is not None and max_keys > 0:
                        sys.argv.extend(["--max-keys", str(max_keys)])
                    if args.no_cache:
                        sys.argv.append("--no-cache")
                    if args.rebuild_only:
                        sys.argv.append("--rebuild-only")
                    translate_page_main()
                    if run_id is not None:
                        log_item(conn, run_id, "translate", "ok", job.page_title, job.lang, None)
                mark_job_done(conn, job.id)
            except Exception as exc:
                mark_job_error(conn, job.id, str(exc))
                if run_id is not None:
                    log_item(conn, run_id, "translate", "error", job.page_title, job.lang, str(exc))


def retry_approve_from_run(cfg, client, source_run_id: int, log_run_id: int) -> None:
    with get_conn(cfg.pg_dsn) as conn:
        pairs = fetch_translate_ok_pairs(conn, source_run_id)
    if not pairs:
        return
    for page_title, lang in pairs:
        if lang not in cfg.target_langs:
            continue
        import sys
        sys.argv = [
            "translate_page",
            "--title",
            page_title,
            "--lang",
            lang,
            "--approve-only",
            "--retry-approve",
        ]
        result = translate_page_main()
        status = "ok"
        message = None
        if isinstance(result, dict):
            approve_status = result.get("approve_status")
            if approve_status == "no_revisions":
                status = "warning"
                message = "no revisions for assembled page"
        with get_conn(cfg.pg_dsn) as conn:
            log_item(conn, log_run_id, "approve", status, page_title, lang, message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-title", help="process only a specific title")
    parser.add_argument("--ingest-title", help="ingest a single title (wrap + enqueue)")
    parser.add_argument("--ingest-all", action="store_true", help="ingest all main namespace pages")
    parser.add_argument("--ingest-limit", type=int, default=None)
    parser.add_argument("--ingest-sleep-ms", type=int, default=0)
    parser.add_argument("--force-retranslate", action="store_true", help="enqueue translations even if source unchanged")
    parser.add_argument("--max-keys", type=int, default=None, help="translate only first N segments per page")
    parser.add_argument("--run-all", action="store_true", help="ingest all then process queue")
    parser.add_argument("--plan", action="store_true", help="dry-run: show how many translations would be queued")
    parser.add_argument("--report-last", action="store_true", help="print last run summary as JSON")
    parser.add_argument("--retry-approve", action="store_true", help="retry approvals for assembled pages")
    parser.add_argument("--no-cache", action="store_true", help="ignore cached translations and retranslate")
    parser.add_argument("--rebuild-only", action="store_true", help="use cached translations only; no MT calls")
    parser.add_argument("--poll-once", action="store_true", help="process recentchanges once and exit")
    parser.add_argument("--poll", action="store_true", help="run recentchanges poller")
    args, _ = parser.parse_known_args()

    configure_logging()
    cfg = load_config()

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    if args.ingest_title:
        with get_conn(cfg.pg_dsn) as conn:
            ingest_title(cfg, client, conn, args.ingest_title, force=args.force_retranslate)
        return

    if args.ingest_all:
        with get_conn(cfg.pg_dsn) as conn:
            ingest_all(
                cfg,
                client,
                conn,
                sleep_ms=args.ingest_sleep_ms,
                limit=args.ingest_limit,
                force=args.force_retranslate,
            )
        return

    if args.plan:
        plan_pages: set[str] = set()
        with get_conn(cfg.pg_dsn) as conn:
            def _record(kind: str, status: str, page_title: str, lang: str | None, message: str) -> None:
                if kind == "plan" and status == "queue":
                    plan_pages.add(page_title)

            ingest_all(
                cfg,
                client,
                conn,
                sleep_ms=args.ingest_sleep_ms,
                limit=args.ingest_limit,
                force=args.force_retranslate,
                record=_record,
                dry_run=True,
            )
        print(f"would_queue_pages={len(plan_pages)}")
        return

    if args.no_cache and args.rebuild_only:
        raise SystemExit("--no-cache cannot be used with --rebuild-only")

    if args.report_last:
        with get_conn(cfg.pg_dsn) as conn:
            print(report_last_run(conn))
        return

    if args.retry_approve and not args.run_all:
        source_run_id = None
        with get_conn(cfg.pg_dsn) as conn:
            source_run_id = last_run_id(conn)
        if source_run_id is None:
            raise SystemExit("no previous runs found to retry approvals")
        run_id = None
        with get_conn(cfg.pg_dsn) as conn:
            run_id = start_run(conn, "retry-approve", cfg)
        retry_approve_from_run(cfg, client, source_run_id, run_id)
        with get_conn(cfg.pg_dsn) as conn:
            finish_run(conn, run_id, "done")
            write_report_file(conn, run_id)
        return

    if args.run_all:
        run_id: int | None = None
        try:
            with get_conn(cfg.pg_dsn) as conn:
                run_id = start_run(conn, "run-all", cfg)

                def _record(
                    kind: str,
                    status: str,
                    page_title: str,
                    lang: str | None,
                    message: str,
                ) -> None:
                    log_item(conn, run_id, kind, status, page_title, lang, message)

                ingest_all(
                    cfg,
                    client,
                    conn,
                    sleep_ms=args.ingest_sleep_ms,
                    limit=args.ingest_limit,
                    record=_record,
                    force=args.force_retranslate,
                )
                delete_jobs_not_in_langs(conn, cfg.target_langs, job_type="translate_page")
            with get_conn(cfg.pg_dsn) as conn:
                total_jobs = count_jobs(conn, status="queued", job_type="translate_page")
            progress = {"done": 0, "total": max(total_jobs, 1)}
            while True:
                with get_conn(cfg.pg_dsn) as conn:
                    if not next_jobs(conn, limit=1):
                        break
                process_queue(cfg, client, run_id=run_id, progress=progress, max_keys=args.max_keys)
            if args.retry_approve:
                retry_approve_from_run(cfg, client, run_id, run_id)
            with get_conn(cfg.pg_dsn) as conn:
                finish_run(conn, run_id, "done")
                report_path = write_report_file(conn, run_id)
            print(str(report_path))
        except Exception as exc:
            if run_id is not None:
                with get_conn(cfg.pg_dsn) as conn:
                    finish_run(conn, run_id, "error")
                    log_item(conn, run_id, "run", "error", None, None, str(exc))
                    write_report_file(conn, run_id)
            raise
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
            if args.max_keys is not None and args.max_keys > 0:
                sys.argv.extend(["--max-keys", str(args.max_keys)])
            if args.no_cache:
                sys.argv.append("--no-cache")
            if args.rebuild_only:
                sys.argv.append("--rebuild-only")
            translate_page_main()
        return

    if args.poll_once:
        run_id = None
        with get_conn(cfg.pg_dsn) as conn:
            run_id = start_run(conn, "poll-once", cfg)
            since = get_ingest_cursor(conn, "recentchanges")
        changes, new_since = poll_recent_changes(client, since)
        if changes:
            with get_conn(cfg.pg_dsn) as conn:
                for change in changes:
                    try:
                        ingest_title(cfg, client, conn, change.title, record=lambda *a, **k: None)
                        log_item(conn, run_id, "ingest", "ok", change.title, None, None)
                    except Exception as exc:
                        log_item(conn, run_id, "ingest", "error", change.title, None, str(exc))
        with get_conn(cfg.pg_dsn) as conn:
            set_ingest_cursor(conn, "recentchanges", new_since)
        with get_conn(cfg.pg_dsn) as conn:
            total_jobs = count_jobs(conn, status="queued", job_type="translate_page")
        progress = {"done": 0, "total": max(total_jobs, 1)}
        while True:
            with get_conn(cfg.pg_dsn) as conn:
                if not next_jobs(conn, limit=1):
                    break
            process_queue(cfg, client, run_id=run_id, progress=progress, max_keys=args.max_keys)
        with get_conn(cfg.pg_dsn) as conn:
            finish_run(conn, run_id, "done")
            report_path = write_report_file(conn, run_id)
        print(str(report_path))
        return

    if args.poll:
        run_poll_loop(cfg, client)
        return

    process_queue(cfg, client, max_keys=args.max_keys)


if __name__ == "__main__":
    main()
