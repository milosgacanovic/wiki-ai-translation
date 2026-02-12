from __future__ import annotations

import argparse
import logging
import time

import requests

from .config import load_config
from .db import fetch_termbase, get_conn
from .engines.google_v3 import GoogleTranslateV3
from .logging import configure_logging
from .mediawiki import MediaWikiClient
from .translate_page import (
    DISPLAYTITLE_RE,
    _apply_termbase,
    _build_no_translate_terms,
    _collapse_blank_lines,
    _compact_leading_metadata_preamble,
    _fetch_messagecollection_segments,
    _normalize_leading_directives,
    _normalize_leading_div,
    _normalize_leading_status_directives,
    _source_title_for_displaytitle,
    _unit_title,
    _upsert_page_display_title_unit,
    split_translate_units,
    sr_cyrillic_to_latin,
)

log = logging.getLogger("bot.repair_display_titles")
NAME_STOPWORDS = {"and", "to", "of", "for", "in", "on", "our", "the", "&"}


def _engine_lang_for(lang: str) -> str:
    if lang == "sr":
        return "sr-Latn"
    return lang


def _find_current_page_display_title(
    client: MediaWikiClient,
    norm_title: str,
    lang: str,
) -> str | None:
    try:
        items = client.get_message_collection(f"page-{norm_title}", lang)
        key = f"{norm_title.replace(' ', '_')}/Page_display_title"
        for item in items:
            if str(item.get("key", "")) == key:
                val = str(item.get("translation") or "").strip()
                if val:
                    return val
                break
    except Exception:
        pass

    try:
        unit1, _, _ = client.get_page_wikitext(_unit_title(norm_title, "1", lang))
        m = DISPLAYTITLE_RE.search(unit1)
        if not m:
            return None
        raw = m.group(0)
        return raw.split(":", 1)[-1].rstrip("}").rstrip("}").strip()
    except Exception:
        return None


def _looks_like_person_name(title: str) -> bool:
    # Conservative heuristic to avoid translating names:
    # 2-3 tokens, all title-cased, no connector words.
    tokens = [t for t in title.replace("–", " ").replace("-", " ").split() if t]
    if len(tokens) < 2 or len(tokens) > 3:
        return False
    lowered = {t.lower() for t in tokens}
    if lowered & NAME_STOPWORDS:
        return False
    return all(t[:1].isupper() for t in tokens)


def _replace_displaytitle_in_unit1(unit1_text: str, display_title: str) -> str:
    base = DISPLAYTITLE_RE.sub("", unit1_text).lstrip()
    updated = f"{{{{DISPLAYTITLE:{display_title}}}}}\n{base}".strip()
    updated = _normalize_leading_directives(updated)
    updated = _normalize_leading_status_directives(updated)
    updated = _normalize_leading_div(updated)
    updated = _compact_leading_metadata_preamble(updated)
    updated = _collapse_blank_lines(updated)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--langs", default=None, help="comma-separated langs; defaults to BOT_TARGET_LANGS")
    parser.add_argument("--only-title", default=None)
    parser.add_argument("--sleep-ms", type=int, default=150)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    langs = tuple(
        l.strip() for l in (args.langs.split(",") if args.langs else cfg.target_langs) if l.strip()
    )
    if not langs:
        raise SystemExit("no target languages configured")

    session = requests.Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    project_id = cfg.gcp_project_id
    if not project_id:
        raise SystemExit("GCP_PROJECT_ID is required for title repair")
    engine = GoogleTranslateV3(
        project_id=project_id,
        location=cfg.gcp_location,
        credentials_path=cfg.gcp_credentials_path,
    )

    titles = [args.only_title] if args.only_title else client.iter_translation_base_titles(source_lang=cfg.source_lang)

    scanned = 0
    repaired = 0
    skipped = 0
    errors = 0

    for base in titles:
        try:
            wikitext, _, norm_title = client.get_page_wikitext(base)
        except Exception:
            continue

        try:
            source_segments = _fetch_messagecollection_segments(client, norm_title, cfg.source_lang)
        except Exception:
            source_segments = []
        if not source_segments:
            source_segments = split_translate_units(wikitext)
        source_display = _source_title_for_displaytitle(norm_title, wikitext, source_segments).strip()
        if not source_display:
            continue

        for lang in langs:
            translated_title = f"{norm_title}/{lang}"
            try:
                client.get_page_revision_id(translated_title)
            except Exception:
                continue
            scanned += 1

            current_display = (_find_current_page_display_title(client, norm_title, lang) or "").strip()
            if not current_display or current_display != source_display:
                skipped += 1
                continue
            if _looks_like_person_name(source_display):
                skipped += 1
                continue

            termbase_entries = []
            if cfg.pg_dsn:
                try:
                    with get_conn(cfg.pg_dsn) as conn:
                        termbase_entries = fetch_termbase(conn, lang)
                except Exception:
                    termbase_entries = []
            no_translate_terms = _build_no_translate_terms(termbase_entries)

            target_display = None
            for term, preferred in no_translate_terms:
                if source_display.lower() == term.lower():
                    target_display = preferred
                    break
            if target_display is None:
                out = engine.translate(
                    [source_display],
                    cfg.source_lang,
                    _engine_lang_for(lang),
                    glossary_id=(cfg.gcp_glossaries or {}).get(lang) if cfg.gcp_glossaries else None,
                )[0].text
                target_display = sr_cyrillic_to_latin(out) if lang == "sr" else out
                if termbase_entries:
                    target_display = _apply_termbase(target_display, termbase_entries)
            target_display = target_display.strip()

            if not target_display or target_display == current_display:
                skipped += 1
                continue

            try:
                if args.dry_run:
                    log.info("DRY RUN repair title: %s/%s -> %s", norm_title, lang, target_display)
                    repaired += 1
                    continue
                unit_title = _upsert_page_display_title_unit(client, norm_title, lang, target_display)
                log.info("edited %s", unit_title)
                unit1_title = _unit_title(norm_title, "1", lang)
                unit1_text, _, _ = client.get_page_wikitext(unit1_title)
                updated_unit1 = _replace_displaytitle_in_unit1(unit1_text, target_display)
                if updated_unit1.strip() != unit1_text.strip():
                    client.edit(unit1_title, updated_unit1, "Bot: repair translated display title", bot=True)
                    log.info("edited %s", unit1_title)
                repaired += 1
                if args.sleep_ms > 0:
                    time.sleep(args.sleep_ms / 1000.0)
            except Exception as exc:
                errors += 1
                log.warning("repair failed for %s/%s: %s", norm_title, lang, exc)

    print(f"summary scanned={scanned} repaired={repaired} skipped={skipped} errors={errors}")


if __name__ == "__main__":
    main()
