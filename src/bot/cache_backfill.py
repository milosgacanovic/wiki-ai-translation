from __future__ import annotations

import argparse
import logging

from .config import load_config
from .db import get_conn, upsert_segment, upsert_translation
from .logging import configure_logging
from .mediawiki import MediaWikiClient, MediaWikiError
from .translate_page import _checksum
from .ingest import is_translation_subpage


def _iter_unit_definitions(client: MediaWikiClient, group_id: str, lang: str) -> dict[str, str]:
    items = client.get_message_collection(group_id, lang)
    definitions: dict[str, str] = {}
    for item in items:
        key = str(item.get("key") or "")
        unit_key = key.split("/")[-1]
        if not unit_key.isdigit():
            continue
        definition = item.get("definition")
        if definition is None:
            continue
        definitions[unit_key] = str(definition)
    return definitions


def _iter_unit_translations(client: MediaWikiClient, group_id: str, lang: str) -> dict[str, str]:
    items = client.get_message_collection(group_id, lang)
    translations: dict[str, str] = {}
    for item in items:
        key = str(item.get("key") or "")
        unit_key = key.split("/")[-1]
        if not unit_key.isdigit():
            continue
        translation = item.get("translation")
        if translation is None:
            continue
        text = str(translation).strip()
        if not text:
            continue
        translations[unit_key] = text
    return translations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--langs", default=None, help="comma-separated target langs (default: BOT_TARGET_LANGS)")
    parser.add_argument("--limit-pages", type=int, default=None)
    parser.add_argument("--prefix", default=None, help="only pages with this title prefix")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    langs = cfg.target_langs
    if args.langs:
        langs = tuple(lang.strip() for lang in args.langs.split(",") if lang.strip())

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    processed = 0
    apcontinue = None
    while True:
        titles, next_cursor = client.all_pages_page(namespace=0, apcontinue=apcontinue)
        if not titles:
            break
        for title in titles:
            if is_translation_subpage(title, langs):
                continue
            if args.prefix and not title.startswith(args.prefix):
                continue
            group_id = f"page-{title}"
            try:
                source_defs = _iter_unit_definitions(client, group_id, cfg.source_lang)
            except MediaWikiError as exc:
                logging.getLogger("cache_backfill").warning(
                    "skip %s: %s", title, exc
                )
                continue
            if not source_defs:
                continue
            with get_conn(cfg.pg_dsn) as conn:
                for key, source_text in source_defs.items():
                    checksum = _checksum(source_text)
                    upsert_segment(conn, title, key, source_text, checksum)
                for lang in langs:
                    try:
                        trans = _iter_unit_translations(client, group_id, lang)
                    except MediaWikiError:
                        continue
                    for key, text in trans.items():
                        segment_key = f"{title}::{key}"
                        upsert_translation(conn, segment_key, lang, text, "backfill")
            processed += 1
            if args.limit_pages is not None and processed >= args.limit_pages:
                return
        apcontinue = next_cursor
        if not apcontinue:
            break


if __name__ == "__main__":
    main()
