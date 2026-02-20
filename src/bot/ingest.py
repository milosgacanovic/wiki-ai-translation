from __future__ import annotations

import logging
import time
import re

from .config import Config
from .mediawiki import MediaWikiClient, MediaWikiError
from .tracker import get_page
from .jobs import enqueue_job
from .state import get_ingest_cursor, set_ingest_cursor

log = logging.getLogger("bot.ingest")


def is_main_namespace(title: str) -> bool:
    return ":" not in title


def is_translation_wrapped(wikitext: str) -> bool:
    return "<translate>" in wikitext and "</translate>" in wikitext


def wrap_with_translate(wikitext: str) -> str:
    if wikitext.endswith("\n"):
        body = wikitext.rstrip("\n")
    else:
        body = wikitext
    return f"<translate>\n{body}\n</translate>\n"


def is_redirect_wikitext(wikitext: str) -> bool:
    stripped = wikitext.lstrip("\ufeff \t\r\n")
    return stripped.lower().startswith("#redirect")


def should_skip_title(title: str, prefixes: tuple[str, ...]) -> bool:
    if not prefixes:
        return False
    norm = title.replace("_", " ")
    return any(norm.startswith(prefix) for prefix in prefixes)


def is_translation_subpage(title: str, target_langs: tuple[str, ...]) -> bool:
    if "/" not in title:
        return False
    suffix = title.split("/")[-1]
    if suffix in target_langs:
        return True
    if re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]+)*", suffix):
        return True
    return False


def enqueue_translations(cfg: Config, conn, title: str) -> None:
    for lang in cfg.target_langs:
        enqueue_job(conn, "translate_page", title, lang, priority=0)


def enqueue_missing_translations(cfg: Config, client: MediaWikiClient, conn, title: str) -> int:
    queued = 0
    group_id = f"page-{title}"
    for lang in cfg.target_langs:
        try:
            missing_units = client.count_missing_translations(group_id, lang)
        except Exception:
            missing_units = 0
        if missing_units > 0:
            enqueue_job(conn, "translate_page", title, lang, priority=0)
            queued += 1
            continue
        try:
            client.get_page_revision_id(f"{title}/{lang}")
            continue
        except MediaWikiError:
            enqueue_job(conn, "translate_page", title, lang, priority=0)
            queued += 1
    return queued


def _apply_placeholders(params: dict[str, str], title: str, revision: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in params.items():
        out[key] = value.replace("{title}", title).replace("{revision}", str(revision))
    return out


def ingest_title(
    cfg: Config,
    client: MediaWikiClient,
    conn,
    title: str,
    record=None,
    force: bool = False,
    dry_run: bool = False,
    enqueue_missing_when_unchanged: bool = True,
) -> None:
    record_cb = record
    would_queue = False

    def _record(status: str, message: str) -> None:
        if record_cb is not None:
            record_cb("ingest", status, title, None, message)

    def _record_plan_queue() -> None:
        if dry_run and would_queue and record_cb is not None:
            record_cb("plan", "queue", title, None, "would queue translation")

    rev_id, norm_title = client.get_page_revision_id(title)
    page_record = get_page(conn, norm_title)

    if should_skip_title(norm_title, cfg.skip_title_prefixes):
        log.info("skip translation for %s due to prefix rule", norm_title)
        _record("skip", "skip prefix rule")
        return
    if cfg.skip_translation_subpages and is_translation_subpage(norm_title, cfg.target_langs):
        log.info("skip translation subpage: %s", norm_title)
        _record("skip", "translation subpage")
        return

    unit_keys = client.list_translation_unit_keys(norm_title, cfg.source_lang)
    if unit_keys:
        source_changed = not page_record or page_record.last_source_rev != rev_id
        if not force and page_record and page_record.last_source_rev == rev_id:
            if not enqueue_missing_when_unchanged:
                _record("skip", "units exist; no source changes")
                return
            if dry_run:
                queued = 0
                group_id = f"page-{norm_title}"
                for lang in cfg.target_langs:
                    missing_units = client.count_missing_translations(group_id, lang)
                    if missing_units > 0:
                        queued += 1
                        continue
                    try:
                        client.get_page_revision_id(f"{norm_title}/{lang}")
                    except MediaWikiError:
                        queued += 1
            else:
                queued = enqueue_missing_translations(cfg, client, conn, norm_title)
            if queued:
                _record("ok", "units exist; queued missing translations")
                would_queue = True
                _record_plan_queue()
            else:
                _record("skip", "units exist; no source changes")
            return
        if source_changed and cfg.translate_mark_action:
            params = dict(cfg.translate_mark_params or {})
            params = _apply_placeholders(params, norm_title, rev_id)
            if "title" not in params and "page" not in params and "target" not in params:
                params["page"] = norm_title
            if "revision" not in params:
                params["revision"] = str(rev_id)
            if "token" not in params:
                params["token"] = client.csrf_token
            params["action"] = cfg.translate_mark_action
            log.info(
                "refreshing translation units via %s for %s rev=%s",
                cfg.translate_mark_action,
                norm_title,
                rev_id,
            )
            if not dry_run:
                try:
                    client._request("POST", params)
                except MediaWikiError as exc:
                    log.error("translate mark API failed: %s", exc)
                    _record("error", f"mark for translation failed: {exc}")
                    return
            else:
                _record("ok", "would mark for translation")
        if not dry_run:
            enqueue_translations(cfg, conn, norm_title)
        _record("ok", "units already exist; queued translation")
        would_queue = True
        _record_plan_queue()
        return

    if not is_main_namespace(norm_title):
        log.info("skip non-main namespace page: %s", norm_title)
        _record("skip", "non-main namespace")
        return

    if not cfg.auto_wrap:
        log.info("auto wrap disabled; skipping %s", norm_title)
        _record("skip", "auto wrap disabled")
        return

    wikitext, _, _ = client.get_page_wikitext(norm_title)
    if is_redirect_wikitext(wikitext):
        log.info("skip redirect page: %s", norm_title)
        _record("skip", "redirect page")
        return
    already_wrapped = is_translation_wrapped(wikitext)
    if already_wrapped:
        log.info("page already wrapped but no units yet: %s", norm_title)
        _record("ok", "already wrapped")
    else:
        if not dry_run:
            wrapped = wrap_with_translate(wikitext)
            summary = "Wrap page in <translate> for machine translation"
            client.edit(norm_title, wrapped, summary, bot=True)
            log.info("wrapped page for translation: %s", norm_title)
            _record("ok", "wrapped")

            new_rev_id, _ = client.get_page_revision_id(norm_title)
            rev_id = new_rev_id
        else:
            _record("ok", "would wrap")
            would_queue = True

    if cfg.translate_mark_action:
        params = dict(cfg.translate_mark_params or {})
        params = _apply_placeholders(params, norm_title, rev_id)
        if "title" not in params and "page" not in params and "target" not in params:
            params["page"] = norm_title
        if "revision" not in params:
            params["revision"] = str(rev_id)
        if "token" not in params:
            params["token"] = client.csrf_token
        params["action"] = cfg.translate_mark_action
        log.info("calling translate mark action=%s page=%s rev=%s", cfg.translate_mark_action, norm_title, rev_id)
        if not dry_run:
            try:
                client._request("POST", params)
            except MediaWikiError as exc:
                log.error("translate mark API failed: %s", exc)
                _record("error", f"mark for translation failed: {exc}")
                return
        else:
            _record("ok", "would mark for translation")
            would_queue = True

        if not dry_run:
            for _ in range(5):
                unit_keys = client.list_translation_unit_keys(
                    norm_title, cfg.source_lang
                )
                if unit_keys:
                    enqueue_translations(cfg, conn, norm_title)
                    _record("ok", "units created; queued translation")
                    _record_plan_queue()
                    return
                time.sleep(0.5)

    unit_keys = client.list_translation_unit_keys(norm_title, cfg.source_lang)
    if unit_keys:
        if not dry_run:
            enqueue_translations(cfg, conn, norm_title)
        _record("ok", "units created; queued translation")
        would_queue = True
    else:
        log.info("no translation units detected after wrap: %s", norm_title)
        _record("error", "no translation units detected after wrap")
    _record_plan_queue()


def ingest_all(
    cfg: Config,
    client: MediaWikiClient,
    conn,
    sleep_ms: int = 0,
    limit: int | None = None,
    record=None,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    cursor = get_ingest_cursor(conn, "main")
    processed = 0
    page_size = 1 if limit is not None else 200
    while True:
        titles, next_cursor = client.all_pages_page(
            namespace=0, limit=page_size, apcontinue=cursor
        )
        if not titles:
            break
        for title in titles:
            try:
                ingest_title(cfg, client, conn, title, record=record, force=force, dry_run=dry_run)
            except Exception as exc:
                log.error("ingest failed for %s: %s", title, exc)
                if record is not None:
                    record("ingest", "error", title, None, f"exception: {exc}")
            processed += 1
            if limit is not None and processed >= limit:
                if not dry_run:
                    set_ingest_cursor(conn, "main", next_cursor)
                return
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
        cursor = next_cursor
        if not dry_run:
            set_ingest_cursor(conn, "main", cursor)
        if not cursor:
            break
