from __future__ import annotations

import argparse
import logging
import time

import requests

from .config import load_config
from .logging import configure_logging
from .mediawiki import MediaWikiClient
from .translate_page import (
    _collapse_blank_lines,
    _compact_leading_metadata_preamble,
    _normalize_leading_directives,
    _normalize_leading_div,
    _normalize_leading_status_directives,
    _parse_status_template,
    _remove_disclaimer_tables,
    _translation_status_from_ai_info,
    _translation_status_from_props,
    _translation_status_from_unit1,
    _unit_title,
    _upsert_status_template,
)


log = logging.getLogger("bot.backfill_ai_translation_props")


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
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--compact-template", action="store_true", default=True)
    parser.add_argument("--no-compact-template", action="store_false", dest="compact_template")
    parser.add_argument("--sleep-ms", type=int, default=0, help="sleep between write operations")
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

    titles = [args.only_title] if args.only_title else client.iter_translation_base_titles(source_lang=cfg.source_lang)

    scanned = 0
    missing = 0
    ai_written = 0
    ai_skipped = 0
    template_edited = 0
    errors = 0

    for base in titles:
        try:
            source_rev, norm_title = client.get_page_revision_id(base)
        except Exception:
            continue
        source_rev_s = str(source_rev)

        for lang in langs:
            if args.limit is not None and scanned >= args.limit:
                print(
                    f"summary scanned={scanned} missing={missing} ai_written={ai_written} "
                    f"ai_skipped={ai_skipped} template_edited={template_edited} errors={errors}"
                )
                return

            translated_title = f"{norm_title}/{lang}"
            try:
                client.get_page_revision_id(translated_title)
            except Exception:
                missing += 1
                continue

            scanned += 1
            try:
                ai_info = client.get_ai_translation_info(translated_title)
            except Exception:
                ai_info = {}
            props, _, _ = client.get_page_props(translated_title)
            status_meta = _translation_status_from_ai_info(ai_info)
            status_meta = {**_translation_status_from_props(props), **status_meta}
            if "dr_translation_status" not in status_meta:
                status_meta = {**status_meta, **_translation_status_from_unit1(client, norm_title, lang)}

            status = status_meta.get("dr_translation_status", "").strip().lower() or "machine"
            if status not in ("machine", "reviewed", "outdated"):
                status = "machine"

            source_rev_for_meta = (
                status_meta.get("dr_source_rev_at_translation", "").strip() or source_rev_s
            )
            outdated_rev_for_meta = None
            if status == "outdated":
                outdated_rev_for_meta = (
                    status_meta.get("dr_outdated_source_rev", "").strip() or source_rev_s
                )

            try:
                current_ai_status = str(ai_info.get("status") or "").strip().lower()
                current_ai_source_rev = str(ai_info.get("source_rev") or "").strip()
                current_ai_source_title = str(ai_info.get("source_title") or "").strip()
                current_ai_source_lang = str(ai_info.get("source_lang") or "").strip()
                current_ai_outdated = str(ai_info.get("outdated_source_rev") or "").strip()
                needs_ai = (
                    current_ai_status != status
                    or current_ai_source_rev != source_rev_for_meta
                    or current_ai_source_title != norm_title
                    or current_ai_source_lang != cfg.source_lang
                    or (status == "outdated" and current_ai_outdated != str(outdated_rev_for_meta or ""))
                )
                if needs_ai:
                    if args.dry_run:
                        log.info("DRY RUN ai update %s status=%s source_rev=%s", translated_title, status, source_rev_for_meta)
                    else:
                        client.set_ai_translation_status(
                            title=translated_title,
                            status=status,
                            source_rev=source_rev_for_meta,
                            outdated_source_rev=outdated_rev_for_meta,
                            source_title=norm_title,
                            source_lang=cfg.source_lang,
                        )
                        ai_written += 1
                        if args.sleep_ms > 0:
                            time.sleep(args.sleep_ms / 1000.0)
                else:
                    ai_skipped += 1
            except Exception as exc:
                errors += 1
                log.warning("ai props write failed for %s: %s", translated_title, exc)

            if not args.compact_template:
                continue

            unit1_title = _unit_title(norm_title, "1", lang)
            try:
                unit1_text, _, _ = client.get_page_wikitext(unit1_title)
            except Exception:
                continue
            existing = _parse_status_template(unit1_text)
            desired_status = existing.get("status", "").strip().lower() or status
            updated = _upsert_status_template(
                unit1_text,
                status=desired_status,
            )
            updated = _normalize_unit1(updated)
            if updated.strip() == unit1_text.strip():
                continue
            if args.dry_run:
                log.info("DRY RUN edit %s", unit1_title)
            else:
                try:
                    client.edit(
                        unit1_title,
                        updated,
                        "Bot: compact Translation_status template (status-only)",
                        bot=True,
                    )
                    template_edited += 1
                    if args.sleep_ms > 0:
                        time.sleep(args.sleep_ms / 1000.0)
                except Exception as exc:
                    errors += 1
                    log.warning("template compact failed %s: %s", unit1_title, exc)

    print(
        f"summary scanned={scanned} missing={missing} ai_written={ai_written} "
        f"ai_skipped={ai_skipped} template_edited={template_edited} errors={errors}"
    )


if __name__ == "__main__":
    main()
