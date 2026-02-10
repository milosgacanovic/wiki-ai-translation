from __future__ import annotations

import argparse
import json
import logging
import time
import re

from .config import load_config
from .db import get_conn, fetch_termbase
from .engines.google_v3 import GoogleTranslateV3
from .logging import configure_logging
from .mediawiki import MediaWikiClient, MediaWikiError
from .placeholders import protect_wikitext, restore_wikitext
from .segmenter import split_translate_units, Segment
from .transliteration import sr_cyrillic_to_latin


def _resolve_project_id(cfg_project_id: str | None, credentials_path: str | None) -> str | None:
    if cfg_project_id:
        return cfg_project_id
    if not credentials_path:
        return None
    try:
        with open(credentials_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("project_id")
    except Exception:
        return None


def _unit_title(page_title: str, unit_key: str, lang: str) -> str:
    return f"Translations:{page_title}/{unit_key}/{lang}"


LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
FILE_LINK_RE = re.compile(r"\[\[(?:File|Image):[^\]]+\]\]", re.IGNORECASE)
EMPTY_P_RE = re.compile(r"<p>\s*(?:<br\s*/?>\s*)+</p>", re.IGNORECASE)
REDIRECT_RE = re.compile(r"^\s*#redirect\b", re.IGNORECASE)
UNRESOLVED_PLACEHOLDER_RE = re.compile(r"__PH\d+__|__LINK\d+__")
BROKEN_LINK_RE = re.compile(r"\[\[(?:__PH\d+__|__LINK\d+__)\|([^\]]+)\]\]")
DISPLAYTITLE_RE = re.compile(r"\{\{\s*DISPLAYTITLE\s*:[^}]+\}\}", re.IGNORECASE)


def _is_safe_internal_link(target: str) -> bool:
    return ":" not in target


def _tokenize_links(
    text: str, lang: str
) -> tuple[str, dict[str, str], list[tuple[str, str]], set[str]]:
    placeholders: dict[str, str] = {}
    link_meta: list[tuple[str, str]] = []
    source_targets: set[str] = set()

    def _replace(match: re.Match) -> str:
        target = match.group(1)
        display = match.group(2)
        if not _is_safe_internal_link(target):
            return match.group(0)

        page, anchor = (target.split("#", 1) + [""])[:2]
        source_targets.add(page)
        if page.endswith(f"/{lang}"):
            new_target = page
        else:
            new_target = f"{page}/{lang}"
        if anchor:
            new_target = f"{new_target}#{anchor}"

        token = f"__LINK{len(placeholders)}__"
        placeholders[token] = new_target

        if display is None:
            display = target
            # Implicit display: do not translate to avoid changing names
        else:
            link_meta.append((new_target, display))
        return f"[[{token}|{display}]]"

    return LINK_RE.sub(_replace, text), placeholders, link_meta, source_targets




DISCALIMER_TEXT_BY_LANG = {
    "sr": (
        "Ova stranica je automatski prevedena. "
        "Ovaj prevod može sadržati greške ili netačnosti. "
        "<br />Možete pomoći da se poboljša tako što ćete {link}."
    ),
    "it": (
        "Questa pagina è stata tradotta automaticamente. "
        "Questa traduzione può contenere errori o imprecisioni. "
        "<br />Puoi aiutare a migliorarla {link}."
    ),
    "en": (
        "This page was automatically translated. "
        "This translation may contain errors or inaccuracies. "
        "<br />You can help improve it by {link}."
    ),
}


def _translate_page_link(norm_title: str, lang: str, link_text: str) -> str:
    group = f"page-{norm_title.replace(' ', '+')}"
    href = (
        "https://wiki.danceresource.org/index.php?"
        f"title=Special:Translate&group={group}&action=page&filter=&language={lang}"
    )
    return f"[{href} {link_text}]"


def _build_disclaimer(norm_title: str, lang: str) -> str:
    text = DISCALIMER_TEXT_BY_LANG.get(lang, DISCALIMER_TEXT_BY_LANG["en"])
    link_text = {
        "sr": "urediti stranicu",
        "it": "modificando la pagina",
        "en": "editing the page",
    }.get(lang, "editing the page")
    link = _translate_page_link(norm_title, lang, link_text)
    body = text.format(link=link)
    return (
        "{| class=\"translation-disclaimer\"\n"
        "|-\n"
        f"| {body}\n"
        "|}"
    )


def _strip_empty_paragraphs(text: str) -> str:
    cleaned = EMPTY_P_RE.sub("", text)
    return cleaned.strip()


def _strip_unresolved_placeholders(text: str) -> str:
    return UNRESOLVED_PLACEHOLDER_RE.sub("", text)


def _restore_file_links(source: str, translated: str) -> str:
    source_links = FILE_LINK_RE.findall(source)
    if not source_links:
        return translated
    translated_links = FILE_LINK_RE.findall(translated)
    if not translated_links:
        prefix = "\n".join(source_links)
        return f"{prefix}\n{translated}" if translated else prefix
    out = translated
    for src, tr in zip(source_links, translated_links):
        out = out.replace(tr, src, 1)
    if len(source_links) > len(translated_links):
        extra = "\n".join(source_links[len(translated_links):])
        out = f"{extra}\n{out}"
    return out


def _fix_broken_links(text: str, lang: str) -> str:
    def _repl(match: re.Match) -> str:
        display = match.group(1)
        return f"[[{display}/{lang}|{display}]]"
    return BROKEN_LINK_RE.sub(_repl, text)


def _rewrite_internal_links_to_lang_with_source(
    text: str, lang: str, source_targets: set[str]
) -> str:
    def _repl(match: re.Match) -> str:
        target = match.group(1)
        display = match.group(2) or target
        if not _is_safe_internal_link(target):
            return match.group(0)
        page, anchor = (target.split("#", 1) + [""])[:2]
        if page.endswith(f"/{lang}") or page not in source_targets:
            new_target = page
        else:
            new_target = f"{page}/{lang}"
        if anchor:
            new_target = f"{new_target}#{anchor}"
        return f"[[{new_target}|{display}]]"
    return LINK_RE.sub(_repl, text)


def _apply_termbase(text: str, entries: list[dict[str, str | bool | None]]) -> str:
    updated = text
    for entry in entries:
        term = entry.get("term") or ""
        preferred = entry.get("preferred") or ""
        if not term or not preferred:
            continue
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        updated = pattern.sub(preferred, updated)
    return updated


def _protect_link_targets(text: str) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}

    def _repl(match: re.Match) -> str:
        target = match.group(1)
        display = match.group(2)
        if not _is_safe_internal_link(target):
            return match.group(0)
        token = f"__LT{len(placeholders)}__"
        placeholders[token] = target
        if display is None:
            return f"[[{token}]]"
        return f"[[{token}|{display}]]"

    return LINK_RE.sub(_repl, text), placeholders


def _apply_termbase_safe(text: str, entries: list[dict[str, str | bool | None]]) -> str:
    if not entries:
        return text
    protected, placeholders = _protect_link_targets(text)
    updated = _apply_termbase(protected, entries)
    return restore_wikitext(updated, placeholders)


def _normalize_leading_directives(text: str) -> str:
    pattern = re.compile(
        r"(\{\{DISPLAYTITLE:[^}]+\}\})\s*\n+\s*(__NOTOC__)?\s*\n+\s*(\[\[File:[^\]]+\]\])",
        re.IGNORECASE,
    )

    def _repl(match: re.Match) -> str:
        display = match.group(1)
        notoc = match.group(2) or ""
        filetag = match.group(3)
        return f"{display}{notoc}{filetag}"

    return pattern.sub(_repl, text, count=1)


def _is_redirect_wikitext(text: str) -> bool:
    return bool(REDIRECT_RE.search(text.lstrip("\ufeff")))


def _insert_disclaimer(
    text: str,
    disclaimer: str,
    marker: str | None,
    norm_title: str,
    lang: str,
    anchors: dict[str, dict[str, str]] | None,
) -> str:
    if marker and marker in text:
        return text.replace(marker, f"\n\n{disclaimer}\n\n", 1)
    if anchors and norm_title in anchors and lang in anchors[norm_title]:
        anchor = anchors[norm_title][lang]
        idx = text.find(anchor)
        if idx != -1:
            insert_at = idx + len(anchor)
            return text[:insert_at] + "\n\n" + disclaimer + "\n\n" + text[insert_at:]
    return f"{disclaimer}\n\n{text}"


def _fetch_unit_sources(
    client: MediaWikiClient, norm_title: str, keys: list[str]
) -> list[Segment]:
    segments: list[Segment] = []
    for key in keys:
        unit_title = f"Translations:{norm_title}/{key}/en"
        try:
            text, _, _ = client.get_page_wikitext(unit_title)
        except MediaWikiError as exc:
            logging.getLogger("translate").warning(
                "missing translation unit %s: %s", unit_title, exc
            )
            return []
        segments.append(Segment(key=key, text=text.strip()))
    return segments


def _fetch_messagecollection_segments(
    client: MediaWikiClient, norm_title: str, source_lang: str
) -> list[Segment]:
    group_id = f"page-{norm_title}"
    items = client.get_message_collection(group_id, source_lang)
    segments: list[Segment] = []
    for item in items:
        key = item.get("key") or ""
        unit_key = key.split("/")[-1]
        if not unit_key.isdigit():
            continue
        text = (item.get("definition") or "").strip()
        segments.append(Segment(key=unit_key, text=text))
    return segments


def assemble_translated_page(wikitext: str, translations: dict[str, str]) -> str:
    output = []
    matches = list(re.finditer(r"<!--T:(\\d+)-->", wikitext))
    if not matches:
        return wikitext

    cursor = 0
    for idx, match in enumerate(matches):
        output.append(wikitext[cursor:match.start()])
        key = match.group(1)
        translated = translations.get(key, "")
        output.append(translated)
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(wikitext)
        cursor = end

    output.append(wikitext[cursor:])
    combined = "".join(output)
    combined = re.sub(r"</?translate>", "", combined)
    return combined.strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--lang", default="sr")
    parser.add_argument("--engine-lang", default=None)
    parser.add_argument("--disclaimer", default="")
    parser.add_argument("--fuzzy", action="store_true", default=False)
    parser.add_argument("--no-fuzzy", action="store_false", dest="fuzzy")
    parser.add_argument("--start-key", type=int, default=None)
    parser.add_argument("--max-keys", type=int, default=None)
    parser.add_argument("--sleep-ms", type=int, default=200)
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--approve-only", action="store_true", help="only approve assembled page")
    parser.add_argument("--retry-approve", action="store_true", help="retry approve if assembled page missing")
    parser.add_argument("--auto-review", action="store_true", default=False)
    parser.add_argument("--no-auto-review", action="store_false", dest="auto_review")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    if args.approve_only:
        _, norm_title = client.get_page_revision_id(args.title)
        assembled_title = f"{norm_title}/{args.lang}"
        backoff = [1, 2, 4, 8] if args.retry_approve else []
        attempts = len(backoff) + 1
        for idx in range(attempts):
            try:
                _, assembled_rev, _ = client.get_page_wikitext(assembled_title)
                client.approve_revision(assembled_rev)
                logging.getLogger("translate").info(
                    "approved assembled page %s", assembled_title
                )
                return {"approve_status": "approved"}
            except MediaWikiError as exc:
                if "no revisions" in str(exc).lower():
                    if idx < len(backoff):
                        wait = backoff[idx]
                        logging.getLogger("translate").warning(
                            "approve retry: %s (waiting %ss)", exc, wait
                        )
                        time.sleep(wait)
                        continue
                    logging.getLogger("translate").warning(
                        "skip approve: %s", exc
                    )
                    return {"approve_status": "no_revisions"}
                raise

    wikitext, rev_id, norm_title = client.get_page_wikitext(args.title)
    if _is_redirect_wikitext(wikitext):
        logging.getLogger("translate").info("skip redirect page: %s", norm_title)
        return
    segments = _fetch_messagecollection_segments(client, norm_title, cfg.source_lang)
    if not segments:
        unit_keys = client.list_translation_unit_keys(norm_title, cfg.source_lang)
        if unit_keys:
            unit_keys = sorted(set(unit_keys), key=lambda k: int(k))
            segments = _fetch_unit_sources(client, norm_title, unit_keys)
            if not segments:
                segments = split_translate_units(wikitext)
        else:
            segments = split_translate_units(wikitext)
    if not segments:
        raise SystemExit("no segments found; is the page marked for translation?")

    deduped: list[Segment] = []
    seen_keys: set[str] = set()
    for seg in segments:
        if seg.key in seen_keys:
            continue
        seen_keys.add(seg.key)
        deduped.append(seg)
    segments = deduped

    logging.getLogger("translate").info(
        "page=%s rev_id=%s segments=%s", args.title, rev_id, len(segments)
    )

    termbase_entries: list[dict[str, str | bool | None]] = []
    if cfg.pg_dsn:
        try:
            with get_conn(cfg.pg_dsn) as conn:
                termbase_entries = fetch_termbase(conn, args.lang)
        except Exception:
            termbase_entries = []

    logging.getLogger("translate").info("termbase entries=%s", len(termbase_entries))

    project_id = _resolve_project_id(cfg.gcp_project_id, cfg.gcp_credentials_path)
    if not project_id:
        raise SystemExit("GCP project id is required (set GCP_PROJECT_ID or ensure in credentials)")

    engine = GoogleTranslateV3(
        project_id=project_id,
        location=cfg.gcp_location,
        credentials_path=cfg.gcp_credentials_path,
    )
    glossary_id = None
    if cfg.gcp_glossaries:
        glossary_id = cfg.gcp_glossaries.get(args.lang)

    # Translate page title for DISPLAYTITLE
    engine_lang = args.engine_lang or args.lang
    title_translation = engine.translate(
        [norm_title], cfg.source_lang, engine_lang, glossary_id=glossary_id
    )[0].text
    if engine_lang == "sr-Latn":
        title_translation = sr_cyrillic_to_latin(title_translation)
    if termbase_entries:
        title_translation = _apply_termbase(title_translation, termbase_entries)

    segments = sorted(segments, key=lambda s: int(s.key))
    if args.start_key is not None:
        segments = [s for s in segments if int(s.key) >= args.start_key]
    if args.max_keys is not None and args.max_keys > 0:
        segments = segments[: args.max_keys]

    protected = []
    link_display_requests: dict[str, str] = {}
    source_by_key: dict[str, str] = {}
    marker_key: str | None = None
    source_targets: set[str] = set()
    for seg in segments:
        if cfg.disclaimer_marker and cfg.disclaimer_marker in seg.text and marker_key is None:
            marker_key = seg.key
        link_text, link_placeholders, link_meta, seg_targets = _tokenize_links(seg.text, args.lang)
        source_targets.update(seg_targets)
        result = protect_wikitext(link_text, protect_links=False)
        result.placeholders.update(link_placeholders)
        for target, display in link_meta:
            link_display_requests[target] = display
        protected.append((seg, result))
        source_by_key[seg.key] = seg.text

    translated = engine.translate(
        [p.text for _, p in protected], cfg.source_lang, engine_lang, glossary_id=glossary_id
    )

    # Translate link display texts to ensure localized anchors
    link_display_translated: dict[str, str] = {}
    if link_display_requests:
        displays = list(link_display_requests.values())
        translated_displays = engine.translate(
            displays, cfg.source_lang, engine_lang, glossary_id=glossary_id
        )
        for (target, _), tr in zip(link_display_requests.items(), translated_displays):
            link_display_translated[target] = tr.text

    translated_by_key: dict[str, str] = {}
    ordered_keys: list[str] = []
    for idx, ((seg, ph), tr) in enumerate(zip(protected, translated)):
        restored = restore_wikitext(tr.text, ph.placeholders)
        # Safety: restore any leftover placeholders in case MT preserved tokens
        for token, value in ph.placeholders.items():
            if token in restored:
                restored = restored.replace(token, value)
        restored = _restore_file_links(seg.text, restored)
        if engine_lang == "sr-Latn":
            restored = sr_cyrillic_to_latin(restored)
        if link_display_translated:
            def _rewrite_display(match: re.Match) -> str:
                target = match.group(1)
                display = match.group(2) or target
                if target in link_display_translated:
                    new_display = link_display_translated[target]
                    if engine_lang == "sr-Latn":
                        new_display = sr_cyrillic_to_latin(new_display)
                    return f"[[{target}|{new_display}]]"
                return f"[[{target}|{display}]]"

            restored = LINK_RE.sub(_rewrite_display, restored)
        restored = _fix_broken_links(restored, args.lang)
        restored = _rewrite_internal_links_to_lang_with_source(
            restored, args.lang, source_targets
        )
        if termbase_entries:
            restored = _apply_termbase_safe(restored, termbase_entries)
        restored = _strip_empty_paragraphs(restored)
        # Mark as fuzzy to indicate machine translation if enabled
        if args.fuzzy:
            restored = f"!!FUZZY!!\n{restored}"
        translated_by_key[seg.key] = restored
        ordered_keys.append(seg.key)

    disclaimer = args.disclaimer or _build_disclaimer(norm_title, args.lang)
    inserted = False
    if cfg.disclaimer_marker:
        for key in ordered_keys:
            text = translated_by_key[key]
            if cfg.disclaimer_marker in text:
                translated_by_key[key] = _insert_disclaimer(
                    text, disclaimer, cfg.disclaimer_marker, norm_title, args.lang, cfg.disclaimer_anchors
                )
                inserted = True
                break

    if not inserted and marker_key and marker_key in translated_by_key:
        translated_by_key[marker_key] = _insert_disclaimer(
            translated_by_key[marker_key],
            disclaimer,
            cfg.disclaimer_marker,
            norm_title,
            args.lang,
            cfg.disclaimer_anchors,
        )
        inserted = True

    if not inserted and ordered_keys:
        first_key = ordered_keys[0]
        translated_by_key[first_key] = _insert_disclaimer(
            translated_by_key[first_key],
            disclaimer,
            cfg.disclaimer_marker,
            norm_title,
            args.lang,
            cfg.disclaimer_anchors,
        )

    if cfg.disclaimer_marker:
        for key in ordered_keys:
            translated_by_key[key] = translated_by_key[key].replace(cfg.disclaimer_marker, "")

    has_displaytitle = any(DISPLAYTITLE_RE.search(text) for text in source_by_key.values())
    if ordered_keys and not has_displaytitle:
        displaytitle = f"{{{{DISPLAYTITLE:{title_translation}}}}}"
        translated_by_key[ordered_keys[0]] = f"{displaytitle}\n{translated_by_key[ordered_keys[0]]}"
        translated_by_key[ordered_keys[0]] = _strip_empty_paragraphs(translated_by_key[ordered_keys[0]])
        translated_by_key[ordered_keys[0]] = _normalize_leading_directives(
            translated_by_key[ordered_keys[0]]
        )

    for key in ordered_keys:
        translated_by_key[key] = _strip_empty_paragraphs(translated_by_key[key])
        if termbase_entries:
            translated_by_key[key] = _apply_termbase_safe(
                translated_by_key[key], termbase_entries
            )
        translated_by_key[key] = _strip_unresolved_placeholders(translated_by_key[key])

    # Final pass after disclaimer/displaytitle insertion
    for key in ordered_keys:
        translated_by_key[key] = _strip_unresolved_placeholders(translated_by_key[key])

    for key in ordered_keys:
        restored = translated_by_key[key]
        source_text = source_by_key.get(key, "")
        restored = _restore_file_links(source_text, restored)
        unit_title = _unit_title(norm_title, key, args.lang)
        summary = "Machine translation by bot (draft, needs review)"

        if args.dry_run:
            logging.getLogger("translate").info("DRY RUN edit %s", unit_title)
            continue

        newrev = client.edit(unit_title, restored, summary, bot=True)
        logging.getLogger("translate").info("edited %s", unit_title)
        if args.auto_review and newrev:
            client.translation_review(newrev)
            logging.getLogger("translate").info("reviewed %s", unit_title)
        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    if args.auto_approve:
        assembled_title = f"{norm_title}/{args.lang}"
        try:
            _, assembled_rev, _ = client.get_page_wikitext(assembled_title)
        except MediaWikiError as exc:
            logging.getLogger("translate").warning(
                "skip approve: %s", exc
            )
            return
        client.approve_revision(assembled_rev)
        logging.getLogger("translate").info(
            "approved assembled page %s", assembled_title
        )


if __name__ == "__main__":
    main()
