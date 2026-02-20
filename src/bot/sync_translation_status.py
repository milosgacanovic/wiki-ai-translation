from __future__ import annotations

import argparse
import logging

import requests

from .config import load_config
from .ingest import is_translation_subpage
from .logging import configure_logging
from .mediawiki import MediaWikiClient
from .translate_page import (
    _collapse_blank_lines,
    _compact_leading_metadata_preamble,
    _normalize_leading_directives,
    _normalize_leading_div,
    _normalize_leading_status_directives,
    _remove_disclaimer_tables,
    _translation_status_from_ai_info,
    _translation_status_from_props,
    _translation_status_from_unit1,
    _unit_title,
    _upsert_status_template,
)


log = logging.getLogger("bot.sync_translation_status")


def _normalize_unit1(text: str) -> str:
    text = _remove_disclaimer_tables(text)
    text = _normalize_leading_directives(text)
    text = _normalize_leading_status_directives(text)
    text = _normalize_leading_div(text)
    text = _compact_leading_metadata_preamble(text)
    return _collapse_blank_lines(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-title")
    parser.add_argument("--langs", default=None, help="comma-separated langs; defaults to BOT_TARGET_LANGS")
    parser.add_argument("--approve", action="store_true", help="approve translated page after metadata sync")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()
    langs = tuple(
        l.strip() for l in (args.langs.split(",") if args.langs else cfg.target_langs) if l.strip()
    )
    if not langs:
        raise SystemExit("no languages configured")

    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, requests.Session())
    client.login(cfg.mw_username, cfg.mw_password)

    titles = [args.only_title] if args.only_title else client.iter_main_namespace_titles()

    scanned = 0
    edited = 0
    skipped = 0
    missing = 0
    approved = 0
    errors = 0

    for src_title in titles:
        if is_translation_subpage(src_title, langs):
            continue
        try:
            source_rev, norm_title = client.get_page_revision_id(src_title)
        except Exception:
            continue
        source_rev_s = str(source_rev)

        for lang in langs:
            translated_title = f"{norm_title}/{lang}"
            try:
                translated_rev, _ = client.get_page_revision_id(translated_title)
            except Exception:
                missing += 1
                continue

            scanned += 1
            ai_info = {}
            try:
                ai_info = client.get_ai_translation_info(translated_title)
            except Exception:
                ai_info = {}
            props, _, _ = client.get_page_props(translated_title)
            status_meta = _translation_status_from_ai_info(ai_info)
            status_meta = {**_translation_status_from_props(props), **status_meta}
            if "dr_translation_status" not in status_meta:
                status_meta = {
                    **status_meta,
                    **_translation_status_from_unit1(
                        client, norm_title, lang, source_lang=cfg.source_lang
                    ),
                }
            status = status_meta.get("dr_translation_status", "").strip().lower()
            if status != "reviewed":
                skipped += 1
                continue

            unit1 = _unit_title(norm_title, "1", lang)
            try:
                unit1_text, _, _ = client.get_page_wikitext(unit1)
            except Exception as exc:
                errors += 1
                log.warning("read failed %s: %s", unit1, exc)
                continue

            updated = _upsert_status_template(
                unit1_text,
                status="reviewed",
            )
            updated = _normalize_unit1(updated)

            if updated.strip() != unit1_text.strip():
                if args.dry_run:
                    log.info("DRY RUN edit %s", unit1)
                else:
                    try:
                        client.edit(
                            unit1,
                            updated,
                            "Bot: sync reviewed translation status metadata",
                            bot=True,
                        )
                        edited += 1
                        log.info("edited %s", unit1)
                    except Exception as exc:
                        errors += 1
                        log.warning("edit failed %s: %s", unit1, exc)
                        continue
            else:
                skipped += 1

            if not args.dry_run:
                try:
                    client.set_ai_translation_status(
                        title=translated_title,
                        status="reviewed",
                        source_rev=source_rev_s,
                        source_title=norm_title,
                        source_lang=cfg.source_lang,
                    )
                except Exception as exc:
                    errors += 1
                    log.warning("ai props write failed %s: %s", translated_title, exc)

            if args.approve and not args.dry_run:
                try:
                    translated_rev, _ = client.get_page_revision_id(translated_title)
                    client.approve_revision(translated_rev)
                    approved += 1
                except Exception as exc:
                    errors += 1
                    log.warning("approve failed %s: %s", translated_title, exc)

    print(
        f"summary scanned={scanned} edited={edited} skipped={skipped} "
        f"missing={missing} approved={approved} errors={errors}"
    )


if __name__ == "__main__":
    main()
