from __future__ import annotations

import logging
import time

from .config import Config
from .mediawiki import MediaWikiClient, MediaWikiError
from .tracker import upsert_page, get_page
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


def enqueue_translations(cfg: Config, conn, title: str) -> None:
    for lang in cfg.target_langs:
        enqueue_job(conn, "translate_page", title, lang, priority=0)


def _apply_placeholders(params: dict[str, str], title: str, revision: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in params.items():
        out[key] = value.replace("{title}", title).replace("{revision}", str(revision))
    return out


def ingest_title(cfg: Config, client: MediaWikiClient, conn, title: str) -> None:
    rev_id, norm_title = client.get_page_revision_id(title)
    record = get_page(conn, norm_title)
    upsert_page(conn, norm_title, cfg.source_lang, rev_id)

    unit_keys = client.list_translation_unit_keys(norm_title)
    if unit_keys:
        enqueue_translations(cfg, conn, norm_title)
        return

    if record and record.last_source_rev == rev_id:
        return

    if not is_main_namespace(norm_title):
        log.info("skip non-main namespace page: %s", norm_title)
        return

    if not cfg.auto_wrap:
        log.info("auto wrap disabled; skipping %s", norm_title)
        return

    wikitext, _, _ = client.get_page_wikitext(norm_title)
    already_wrapped = is_translation_wrapped(wikitext)
    if already_wrapped:
        log.info("page already wrapped but no units yet: %s", norm_title)
    else:
        wrapped = wrap_with_translate(wikitext)
        summary = "Wrap page in <translate> for machine translation"
        client.edit(norm_title, wrapped, summary, bot=True)
        log.info("wrapped page for translation: %s", norm_title)

        new_rev_id, _ = client.get_page_revision_id(norm_title)
        rev_id = new_rev_id
        upsert_page(conn, norm_title, cfg.source_lang, new_rev_id)

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
        try:
            client._request("POST", params)
        except MediaWikiError as exc:
            log.error("translate mark API failed: %s", exc)
            return

        for _ in range(5):
            unit_keys = client.list_translation_unit_keys(norm_title)
            if unit_keys:
                enqueue_translations(cfg, conn, norm_title)
                return
            time.sleep(0.5)

    unit_keys = client.list_translation_unit_keys(norm_title)
    if unit_keys:
        enqueue_translations(cfg, conn, norm_title)
    else:
        log.info("no translation units detected after wrap: %s", norm_title)


def ingest_all(
    cfg: Config,
    client: MediaWikiClient,
    conn,
    sleep_ms: int = 0,
    limit: int | None = None,
) -> None:
    cursor = get_ingest_cursor(conn, "main")
    processed = 0
    while True:
        titles, next_cursor = client.all_pages_page(namespace=0, apcontinue=cursor)
        if not titles:
            break
        for title in titles:
            try:
                ingest_title(cfg, client, conn, title)
            except Exception as exc:
                log.error("ingest failed for %s: %s", title, exc)
            processed += 1
            if limit is not None and processed >= limit:
                set_ingest_cursor(conn, "main", cursor)
                return
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
        cursor = next_cursor
        set_ingest_cursor(conn, "main", cursor)
        if not cursor:
            break
