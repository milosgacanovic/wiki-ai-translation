from __future__ import annotations

import argparse
import logging

import requests

from .config import load_config
from .logging import configure_logging
from .mediawiki import MediaWikiClient, MediaWikiError
from .translate_page import (
    _collapse_blank_lines,
    _normalize_leading_directives,
    _normalize_leading_div,
    _normalize_leading_status_directives,
    _remove_disclaimer_tables,
    _upsert_status_template,
    _unit_title,
)

log = logging.getLogger("bot.migrate_translation_status")


def _iter_base_titles(client: MediaWikiClient, only_title: str | None) -> list[str]:
    if only_title:
        return [only_title]
    return client.iter_translation_base_titles(source_lang="en")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-title")
    parser.add_argument("--langs", default=None, help="comma-separated langs; defaults to BOT_TARGET_LANGS")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    langs = tuple(
        l.strip() for l in (args.langs.split(",") if args.langs else cfg.target_langs) if l.strip()
    )
    if not langs:
        raise SystemExit("no languages configured")

    session = requests.Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    base_titles = _iter_base_titles(client, args.only_title)
    done = 0
    edited = 0
    skipped = 0
    errors = 0

    for base in base_titles:
        try:
            source_rev, norm_title = client.get_page_revision_id(base)
        except Exception as exc:
            log.warning("skip source %s: %s", base, exc)
            continue
        for lang in langs:
            if args.limit is not None and done >= args.limit:
                print(f"summary done={done} edited={edited} skipped={skipped} errors={errors}")
                return
            done += 1
            translated_title = f"{norm_title}/{lang}"
            try:
                client.get_page_revision_id(translated_title)
            except MediaWikiError:
                skipped += 1
                log.info("skip missing translated page: %s", translated_title)
                continue
            unit1 = _unit_title(norm_title, "1", lang)
            try:
                unit1_text, _, _ = client.get_page_wikitext(unit1)
            except Exception as exc:
                errors += 1
                log.error("error reading %s: %s", unit1, exc)
                continue
            updated = _upsert_status_template(
                _remove_disclaimer_tables(unit1_text),
                status="machine",
                source_rev_at_translation=str(source_rev),
            )
            # Keep top metadata/directives compact and avoid extra blank lines.
            updated = _normalize_leading_directives(updated)
            updated = _normalize_leading_status_directives(updated)
            updated = _normalize_leading_div(updated)
            updated = _collapse_blank_lines(updated)
            if updated.strip() == unit1_text.strip():
                skipped += 1
                log.info("skip unchanged %s", unit1)
                continue
            if args.dry_run:
                edited += 1
                log.info("DRY RUN edit %s", unit1)
                continue
            try:
                client.edit(
                    unit1,
                    updated,
                    "Bot: migrate to Translation_status metadata",
                    bot=True,
                )
                edited += 1
                log.info("edited %s", unit1)
            except Exception as exc:
                errors += 1
                log.error("error editing %s: %s", unit1, exc)

    print(f"summary done={done} edited={edited} skipped={skipped} errors={errors}")


if __name__ == "__main__":
    main()
