from __future__ import annotations

import argparse
import json
import logging
import time
import re

from .config import load_config
from .engines.google_v3 import GoogleTranslateV3
from .logging import configure_logging
from .mediawiki import MediaWikiClient
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


def _is_safe_internal_link(target: str) -> bool:
    return ":" not in target


def _tokenize_links(
    text: str, lang: str
) -> tuple[str, dict[str, str], list[tuple[str, str]]]:
    placeholders: dict[str, str] = {}
    link_meta: list[tuple[str, str]] = []

    def _replace(match: re.Match) -> str:
        target = match.group(1)
        display = match.group(2)
        if not _is_safe_internal_link(target):
            return match.group(0)

        page, anchor = (target.split("#", 1) + [""])[:2]
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
        link_meta.append((new_target, display))
        return f"[[{token}|{display}]]"

    return LINK_RE.sub(_replace, text), placeholders, link_meta


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


def _fetch_unit_sources(
    client: MediaWikiClient, norm_title: str, keys: list[str]
) -> list[Segment]:
    segments: list[Segment] = []
    for key in keys:
        unit_title = f"Translations:{norm_title}/{key}/en"
        text, _, _ = client.get_page_wikitext(unit_title)
        segments.append(Segment(key=key, text=text.strip()))
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
    parser.add_argument("--sleep-ms", type=int, default=200)
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--auto-review", action="store_true", default=False)
    parser.add_argument("--no-auto-review", action="store_false", dest="auto_review")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    wikitext, rev_id, norm_title = client.get_page_wikitext(args.title)
    unit_keys = client.list_translation_unit_keys(norm_title)
    if unit_keys:
        segments = _fetch_unit_sources(client, norm_title, unit_keys)
    else:
        segments = split_translate_units(wikitext)
    if not segments:
        raise SystemExit("no segments found; is the page marked for translation?")

    logging.getLogger("translate").info(
        "page=%s rev_id=%s segments=%s", args.title, rev_id, len(segments)
    )

    project_id = _resolve_project_id(cfg.gcp_project_id, cfg.gcp_credentials_path)
    if not project_id:
        raise SystemExit("GCP project id is required (set GCP_PROJECT_ID or ensure in credentials)")

    engine = GoogleTranslateV3(
        project_id=project_id,
        location=cfg.gcp_location,
        credentials_path=cfg.gcp_credentials_path,
    )

    # Translate page title for DISPLAYTITLE
    engine_lang = args.engine_lang or args.lang
    title_translation = engine.translate([norm_title], cfg.source_lang, engine_lang)[0].text
    if engine_lang == "sr-Latn":
        title_translation = sr_cyrillic_to_latin(title_translation)

    if args.start_key is not None:
        segments = [s for s in segments if int(s.key) >= args.start_key]

    protected = []
    link_display_requests: dict[str, str] = {}
    for seg in segments:
        link_text, link_placeholders, link_meta = _tokenize_links(seg.text, args.lang)
        result = protect_wikitext(link_text)
        result.placeholders.update(link_placeholders)
        for target, display in link_meta:
            link_display_requests[target] = display
        protected.append((seg, result))

    translated = engine.translate(
        [p.text for _, p in protected], cfg.source_lang, engine_lang
    )

    # Translate link display texts to ensure localized anchors
    link_display_translated: dict[str, str] = {}
    if link_display_requests:
        displays = list(link_display_requests.values())
        translated_displays = engine.translate(displays, cfg.source_lang, engine_lang)
        for (target, _), tr in zip(link_display_requests.items(), translated_displays):
            link_display_translated[target] = tr.text

    translated_by_key: dict[str, str] = {}
    for idx, ((seg, ph), tr) in enumerate(zip(protected, translated)):
        restored = restore_wikitext(tr.text, ph.placeholders)
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
        if idx == 0:
            disclaimer = args.disclaimer or _build_disclaimer(norm_title, args.lang)
            displaytitle = f"{{{{DISPLAYTITLE:{title_translation}}}}}"
            restored = f"{displaytitle}\n{disclaimer}\n\n{restored}"
        # Mark as fuzzy to indicate machine translation if enabled
        if args.fuzzy:
            restored = f"!!FUZZY!!\n{restored}"
        translated_by_key[seg.key] = restored
        unit_title = _unit_title(norm_title, seg.key, args.lang)
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
        _, assembled_rev, _ = client.get_page_wikitext(assembled_title)
        client.approve_revision(assembled_rev)
        logging.getLogger("translate").info("approved assembled page %s", assembled_title)


if __name__ == "__main__":
    main()
