from __future__ import annotations

import argparse
import logging
import hashlib
from datetime import datetime

from .config import load_config
from .logging import configure_logging, attach_file_logging
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
from .sync_translation_status import main as sync_translation_status_main
from .state import get_ingest_cursor, set_ingest_cursor
from .translate_page import main as translate_page_main
from .tracker import upsert_page
from .segmenter import split_translate_units
from .run_report import (
    start_run,
    finish_run,
    log_item,
    write_report_file,
    report_last_run,
    last_run_id,
    fetch_translate_ok_pairs,
    close_stale_running_runs,
)


def _engine_lang_for(lang: str) -> str:
    if lang == "sr":
        return "sr-Latn"
    return lang


def _recentchanges_cursor_name(cfg) -> str:
    langs = ",".join(sorted(set(cfg.target_langs)))
    return f"recentchanges:{langs}"


def _recentchanges_cursor_name_for_lang(lang: str) -> str:
    return f"recentchanges:{lang}"


def _collect_poll_changes(
    cfg,
    client,
    cursors: dict[str, str | None],
    limit: int | None,
) -> tuple[list, dict[str, str | None]]:
    # Single-language mode keeps existing cursor behavior.
    langs = sorted(set(cfg.target_langs))
    if len(langs) <= 1:
        cursor_name = _recentchanges_cursor_name(cfg)
        since = cursors.get(cursor_name)
        changes, new_since = poll_recent_changes(client, since, limit=limit)
        return changes, {cursor_name: new_since}

    # Multi-language mode: union recentchanges from each language cursor so
    # "all languages" behaves as sum of individual language windows.
    merged: dict[str, object] = {}
    new_since_by_cursor: dict[str, str | None] = {}
    for lang in langs:
        cursor_name = _recentchanges_cursor_name_for_lang(lang)
        since = cursors.get(cursor_name)
        changes, new_since = poll_recent_changes(client, since, limit=limit)
        new_since_by_cursor[cursor_name] = new_since
        for change in changes:
            current = merged.get(change.title)
            if current is None or getattr(current, "timestamp", "") < change.timestamp:
                merged[change.title] = change
    out = list(merged.values())
    out.sort(key=lambda c: (getattr(c, "timestamp", ""), getattr(c, "title", "")))
    return out, new_since_by_cursor


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plan_page_segment_delta(cfg, client: MediaWikiClient, title: str) -> tuple[int, int] | None:
    try:
        source_wikitext, _rev_id, norm_title = client.get_page_wikitext(title)
    except Exception:
        return None

    segments: list[tuple[str, str]] = []
    unit_keys = client.list_translation_unit_keys(norm_title, cfg.source_lang)
    if unit_keys:
        for key in sorted(set(unit_keys), key=lambda k: int(k)):
            unit_title = f"Translations:{norm_title}/{key}/{cfg.source_lang}"
            try:
                unit_text, _, _ = client.get_page_wikitext(unit_title)
                segments.append((key, unit_text))
            except Exception:
                # If any unit fetch fails, fall back to parser-based segmentation.
                segments = []
                break

    if not segments:
        parsed = split_translate_units(source_wikitext)
        dedup: dict[str, str] = {}
        for seg in parsed:
            dedup[seg.key] = seg.text
        segments = sorted(dedup.items(), key=lambda kv: int(kv[0]))

    total = len(segments)
    if total == 0 or not cfg.pg_dsn:
        return (total, total)

    existing_checksums: dict[str, str] = {}
    try:
        from .db import fetch_segment_checksums

        with get_conn(cfg.pg_dsn) as conn:
            existing_checksums = fetch_segment_checksums(conn, norm_title)
    except Exception:
        existing_checksums = {}

    if not existing_checksums:
        return (total, total)

    current_keys = {key for key, _ in segments}
    if set(existing_checksums.keys()) != current_keys:
        return (total, total)

    changed = 0
    for key, text in segments:
        if existing_checksums.get(key) != _checksum(text):
            changed += 1
    return (changed, total)


def process_queue(
    cfg,
    client,
    run_id: int | None = None,
    progress: dict[str, int] | None = None,
    max_keys: int | None = None,
    no_cache: bool = False,
    rebuild_only: bool = False,
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
                    if no_cache:
                        sys.argv.append("--no-cache")
                    if rebuild_only:
                        sys.argv.append("--rebuild-only")
                    result = translate_page_main()
                    result_status = None
                    if isinstance(result, dict):
                        result_status = str(result.get("status", "")).strip().lower()
                    if isinstance(result, dict):
                        page_title = str(result.get("title") or "").strip()
                        source_rev = str(result.get("source_rev") or "").strip()
                        if page_title and source_rev.isdigit() and result_status not in ("", "error"):
                            upsert_page(conn, page_title, cfg.source_lang, int(source_rev))
                    if run_id is not None:
                        status = "ok"
                        message = None
                        if isinstance(result, dict):
                            if result_status and result_status.startswith("locked_"):
                                status = "skip"
                                message = result_status
                            elif result_status == "outdated":
                                status = "warning"
                                message = "status changed to outdated"
                        log_item(conn, run_id, "translate", status, job.page_title, job.lang, message)
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
    parser.add_argument(
        "--force-retranslate",
        dest="force_retranslate",
        action="store_true",
        default=True,
        help="enqueue translations even if source unchanged (default: on)",
    )
    parser.add_argument(
        "--no-force-retranslate",
        dest="force_retranslate",
        action="store_false",
        help="do not enqueue when source revision is unchanged",
    )
    parser.add_argument("--max-keys", type=int, default=None, help="translate only first N segments per page")
    parser.add_argument("--run-all", action="store_true", help="ingest all then process queue")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="deprecated alias for --dry-run (works with --poll-once)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview delta queue from recentchanges; no queue/process/cursor updates",
    )
    parser.add_argument("--report-last", action="store_true", help="print last run summary as JSON")
    parser.add_argument("--retry-approve", action="store_true", help="retry approvals for assembled pages")
    parser.add_argument(
        "--clear-queue",
        action="store_true",
        help="clear queued translate jobs before running",
    )
    parser.add_argument("--no-cache", action="store_true", help="ignore cached translations and retranslate")
    parser.add_argument("--rebuild-only", action="store_true", help="use cached translations only; no MT calls")
    parser.add_argument("--poll-once", action="store_true", help="process recentchanges once and exit")
    parser.add_argument("--poll", action="store_true", help="run recentchanges poller")
    parser.add_argument(
        "--include-missing",
        action="store_true",
        help="with --poll-once, also queue missing translations for unchanged source pages",
    )
    parser.add_argument(
        "--poll-limit",
        type=int,
        default=None,
        help="max recentchanges entries to process in one poll cycle",
    )
    parser.add_argument(
        "--sync-reviewed-status",
        action="store_true",
        help="sync source_rev_at_translation for reviewed pages",
    )
    args, _ = parser.parse_known_args()

    configure_logging()
    cfg = load_config()

    def _setup_run_log(conn, run_id: int) -> str:
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        log_path = f"docs/runs/raw/run-{run_id}-{stamp}.log"
        attach_file_logging(log_path)
        log_item(conn, run_id, "run", "info", None, None, f"raw_log={log_path}")
        return log_path

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
        args.dry_run = True

    if args.no_cache and args.rebuild_only:
        raise SystemExit("--no-cache cannot be used with --rebuild-only")
    if args.dry_run and not args.poll_once:
        raise SystemExit("--dry-run is currently supported with --poll-once")
    if args.clear_queue and args.dry_run:
        raise SystemExit("--clear-queue cannot be combined with --dry-run")

    if args.clear_queue:
        with get_conn(cfg.pg_dsn) as conn:
            deleted = delete_queued_jobs(conn, job_type="translate_page")
        print(f"cleared_queued_translate_jobs={deleted}")

    with get_conn(cfg.pg_dsn) as conn:
        stale = close_stale_running_runs(conn)
        for stale_id in stale:
            write_report_file(conn, stale_id)
            logging.getLogger("runner").warning(
                "closed stale run as interrupted and wrote report: run_id=%s",
                stale_id,
            )

    if args.report_last:
        with get_conn(cfg.pg_dsn) as conn:
            print(report_last_run(conn))
        return

    if args.sync_reviewed_status:
        import sys

        sys.argv = ["sync_translation_status"]
        sync_translation_status_main()
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
            _setup_run_log(conn, run_id)
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
                _setup_run_log(conn, run_id)

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
                process_queue(cfg, client, run_id=run_id, progress=progress, max_keys=args.max_keys, no_cache=args.no_cache, rebuild_only=args.rebuild_only)
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
        cursor_name = _recentchanges_cursor_name(cfg)
        if args.dry_run:
            existing_queued = 0
            cursors: dict[str, str | None] = {}
            with get_conn(cfg.pg_dsn) as conn:
                existing_queued = count_jobs(conn, status="queued", job_type="translate_page")
                langs = sorted(set(cfg.target_langs))
                if len(langs) <= 1:
                    cursors[cursor_name] = get_ingest_cursor(conn, cursor_name)
                else:
                    for lang in langs:
                        lang_cursor_name = _recentchanges_cursor_name_for_lang(lang)
                        cursors[lang_cursor_name] = get_ingest_cursor(conn, lang_cursor_name)
            changes, _new_since_by_cursor = _collect_poll_changes(
                cfg, client, cursors, limit=args.poll_limit
            )
            plan_pages: set[str] = set()
            seen_titles: set[str] = set()
            with get_conn(cfg.pg_dsn) as conn:
                def _record(
                    kind: str,
                    status: str,
                    page_title: str,
                    lang: str | None,
                    message: str,
                ) -> None:
                    if kind == "plan" and status == "queue":
                        plan_pages.add(page_title)

                for change in changes:
                    if change.title in seen_titles:
                        continue
                    seen_titles.add(change.title)
                    ingest_title(
                        cfg,
                        client,
                        conn,
                        change.title,
                        record=_record,
                        force=args.force_retranslate,
                        dry_run=True,
                        enqueue_missing_when_unchanged=args.include_missing,
                    )
            print(f"would_process_changes={len(changes)}")
            print(f"would_queue_pages={len(plan_pages)}")
            print(f"existing_queued_jobs={existing_queued}")
            if existing_queued > 0:
                print(
                    "WARNING: queued translate_page jobs already exist; a normal --poll-once run will process them too."
                )
            for title in sorted(plan_pages):
                stats = _plan_page_segment_delta(cfg, client, title)
                if stats is None:
                    print(f"{title} (reason=unknown)")
                    continue
                changed, total = stats
                reason = "delta" if changed > 0 else "forced"
                print(f"{title} ({changed}/{total}, reason={reason})")
            return

        run_id = None
        try:
            cursors: dict[str, str | None] = {}
            with get_conn(cfg.pg_dsn) as conn:
                run_id = start_run(conn, "poll-once", cfg)
                _setup_run_log(conn, run_id)
                langs = sorted(set(cfg.target_langs))
                if len(langs) <= 1:
                    cursors[cursor_name] = get_ingest_cursor(conn, cursor_name)
                else:
                    for lang in langs:
                        lang_cursor_name = _recentchanges_cursor_name_for_lang(lang)
                        cursors[lang_cursor_name] = get_ingest_cursor(conn, lang_cursor_name)
            changes, new_since_by_cursor = _collect_poll_changes(
                cfg, client, cursors, limit=args.poll_limit
            )
            if changes:
                seen_titles: set[str] = set()
                with get_conn(cfg.pg_dsn) as conn:
                    for change in changes:
                        if change.title in seen_titles:
                            continue
                        seen_titles.add(change.title)
                        try:
                            ingest_title(
                                cfg,
                                client,
                                conn,
                                change.title,
                                record=lambda *a, **k: None,
                                force=args.force_retranslate,
                                enqueue_missing_when_unchanged=args.include_missing,
                            )
                            log_item(conn, run_id, "ingest", "ok", change.title, None, None)
                        except Exception as exc:
                            log_item(conn, run_id, "ingest", "error", change.title, None, str(exc))
            with get_conn(cfg.pg_dsn) as conn:
                total_jobs = count_jobs(conn, status="queued", job_type="translate_page")
            progress = {"done": 0, "total": max(total_jobs, 1)}
            while True:
                with get_conn(cfg.pg_dsn) as conn:
                    if not next_jobs(conn, limit=1):
                        break
                process_queue(
                    cfg,
                    client,
                    run_id=run_id,
                    progress=progress,
                    max_keys=args.max_keys,
                    no_cache=args.no_cache,
                    rebuild_only=args.rebuild_only,
                )
            # Advance poll cursor only after successful completion.
            with get_conn(cfg.pg_dsn) as conn:
                for c_name, c_value in new_since_by_cursor.items():
                    set_ingest_cursor(conn, c_name, c_value)
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

    if args.poll:
        run_poll_loop(cfg, client)
        return

    process_queue(cfg, client, max_keys=args.max_keys, no_cache=args.no_cache, rebuild_only=args.rebuild_only)


if __name__ == "__main__":
    main()
