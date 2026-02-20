from __future__ import annotations

import argparse
import json
import logging
import time
import re
import hashlib
import difflib
import unicodedata
from urllib.parse import urlparse, urlunparse

from .config import load_config
from .db import (
    get_conn,
    fetch_termbase,
    fetch_segment_checksums,
    fetch_cached_translation,
    fetch_cached_translation_by_checksum,
    upsert_segment,
    upsert_translation,
)
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
NS_LINK_RE = re.compile(r"\[\[\s*([^|\]:#]+)\s*:(.*?)\]\]")
HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*?>")
EMPTY_P_RE = re.compile(r"<p>\s*(?:<br\s*/?>\s*)+</p>", re.IGNORECASE)
REDIRECT_RE = re.compile(r"^\s*#redirect\b", re.IGNORECASE)
UNRESOLVED_PLACEHOLDER_RE = re.compile(r"__PH\d+__|__LINK\d+__")
BROKEN_LINK_RE = re.compile(r"\[\[(?:__PH\d+__|__LINK\d+__)\|([^\]]+)\]\]")
DISPLAYTITLE_RE = re.compile(r"\{\{\s*DISPLAYTITLE\s*:[^}]+\}\}", re.IGNORECASE)
REF_TOKEN_RE = re.compile(r"<ref\b[^>]*>.*?</ref>|<ref\b[^>]*/\s*>", re.IGNORECASE | re.DOTALL)
UNDER_DEVELOPMENT_RE = re.compile(r"\{\{\s*UnderDevelopment\s*\}\}", re.IGNORECASE)
MAGIC_WORD_RE = re.compile(r"__([A-Z0-9_]+)__")
DISCLAIMER_TABLE_RE = re.compile(
    r"\{\|\s*class=\"translation-disclaimer\".*?\|\}", re.DOTALL
)
TRANSLATION_STATUS_TEMPLATE_RE = re.compile(
    r"\{\{\s*Translation_status\b[^{}]*\}\}\s*",
    re.IGNORECASE,
)
LEADING_META_TOKEN_RE = re.compile(
    r"(?:\{\{[^{}\n]+\}\}|__[A-Z0-9_]+__|\[\[(?:File|Image):[^\]]+\]\]|<!--.*?-->)",
    re.IGNORECASE,
)
LEADING_META_LINE_RE = re.compile(
    r"(?:\{\{[^{}\n]+\}\}|__[A-Z0-9_]+__|\[\[(?:File|Image):[^\]]+\]\]|<!--.*?-->)+",
    re.IGNORECASE,
)
RESOURCE_ROW_START_RE = re.compile(r"\{\{\s*ResourceRow\b", re.IGNORECASE)
RESOURCE_ROW_PARAM_RE = re.compile(r"(?mi)^(\s*\|\s*)([^=\n]+?)(\s*=\s*)")


def _is_safe_internal_link(target: str) -> bool:
    return ":" not in target


def _strip_known_lang_suffix(page: str, known_langs: set[str]) -> str:
    if "/" not in page:
        return page
    head, tail = page.rsplit("/", 1)
    if tail in known_langs:
        return head
    return page


def _normalize_param_key(name: str) -> str:
    return re.sub(r"[\s_]+", "", name).strip().lower()


def _append_lang_suffix_to_internal_page(
    page: str, lang: str, known_langs: set[str] | None = None
) -> str:
    known_langs = known_langs or set()
    page = page.strip()
    if not page:
        return page
    if ":" in page:
        # Namespaced/special links are left untouched.
        return page
    base_page = _strip_known_lang_suffix(page, known_langs)
    if page.endswith(f"/{lang}"):
        return page
    return f"{base_page}/{lang}"


def _append_lang_suffix_to_internal_url(url: str, lang: str, mw_api_url: str) -> str:
    raw = url.strip()
    if not raw:
        return url
    try:
        parsed = urlparse(raw)
        api_parsed = urlparse(mw_api_url)
    except Exception:
        return url
    if parsed.scheme not in ("http", "https"):
        return url
    if not api_parsed.netloc or parsed.netloc != api_parsed.netloc:
        return url
    if parsed.query or parsed.fragment:
        return url
    path = parsed.path.rstrip("/")
    if not path or path.endswith(f"/{lang}") or path.endswith("/api.php"):
        return url
    new_path = f"{path}/{lang}"
    rebuilt = urlunparse((parsed.scheme, parsed.netloc, new_path, "", "", ""))
    lead = re.match(r"^\s*", url).group(0)
    trail = re.search(r"\s*$", url).group(0)
    return f"{lead}{rebuilt}{trail}"


def _localize_resource_row_internal_targets(
    text: str,
    *,
    lang: str,
    mw_api_url: str,
    known_langs: set[str] | None = None,
) -> str:
    if "{{" not in text:
        return text
    known_langs = known_langs or set()
    out: list[str] = []
    pos = 0
    while True:
        m = RESOURCE_ROW_START_RE.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        start = m.start()
        end = _find_balanced_template_end(text, start)
        if end is None:
            out.append(text[pos:])
            break
        out.append(text[pos:start])
        tpl = text[start:end]
        body = tpl[:-2]
        matches = list(RESOURCE_ROW_PARAM_RE.finditer(body))
        if not matches:
            out.append(tpl)
            pos = end
            continue
        rebuilt_parts: list[str] = []
        cursor = 0
        for idx, pm in enumerate(matches):
            value_start = pm.end()
            value_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
            rebuilt_parts.append(body[cursor:value_start])
            key = _normalize_param_key(pm.group(2))
            value = body[value_start:value_end]
            if key == "url":
                value = _append_lang_suffix_to_internal_url(value, lang, mw_api_url)
            elif key == "creatorlink":
                lead = re.match(r"^\s*", value).group(0)
                trail = re.search(r"\s*$", value).group(0)
                core = value.strip()
                localized = _append_lang_suffix_to_internal_page(core, lang, known_langs=known_langs)
                value = f"{lead}{localized}{trail}"
            rebuilt_parts.append(value)
            cursor = value_end
        rebuilt_parts.append(body[cursor:])
        out.append("".join(rebuilt_parts) + "}}")
        pos = end
    return "".join(out)


def _find_balanced_template_end(text: str, start: int) -> int | None:
    i = start
    depth = 0
    n = len(text)
    while i < n - 1:
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i) and depth > 0:
            depth -= 1
            i += 2
            if depth == 0:
                return i
            continue
        i += 1
    return None


def _translate_resource_row_templates(
    text: str,
    *,
    engine: GoogleTranslateV3 | None,
    source_lang: str,
    target_lang: str,
    glossary_id: str | None,
    no_translate_terms: list[tuple[str, str]],
    termbase_entries: list[dict],
    engine_lang: str,
    preserve_fields: tuple[str, ...],
    translate_fields: tuple[str, ...],
) -> str:
    if engine is None or "{{" not in text:
        return text
    preserve = {_normalize_param_key(k) for k in preserve_fields}
    allowed = {_normalize_param_key(k) for k in translate_fields if k.strip()}
    out: list[str] = []
    pos = 0
    changed = False
    while True:
        m = RESOURCE_ROW_START_RE.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        start = m.start()
        end = _find_balanced_template_end(text, start)
        if end is None:
            out.append(text[pos:])
            break
        out.append(text[pos:start])
        tpl = text[start:end]
        body = tpl[:-2]
        matches = list(RESOURCE_ROW_PARAM_RE.finditer(body))
        if not matches:
            out.append(tpl)
            pos = end
            continue
        rebuilt_parts: list[str] = []
        cursor = 0
        for idx, pm in enumerate(matches):
            value_start = pm.end()
            value_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
            rebuilt_parts.append(body[cursor:value_start])
            key = _normalize_param_key(pm.group(2))
            value = body[value_start:value_end]
            should_translate = key not in preserve and (not allowed or key in allowed)
            if should_translate and value.strip():
                lead = re.match(r"^\s*", value).group(0)
                trail = re.search(r"\s*$", value).group(0)
                core = value.strip()
                ph = protect_wikitext(core, protect_links=True)
                protected_text, nt_placeholders = _protect_terms(ph.text, no_translate_terms)
                translated_core = engine.translate(
                    [protected_text], source_lang, target_lang, glossary_id=glossary_id
                )[0].text
                restored_core = restore_wikitext(
                    translated_core, {**ph.placeholders, **nt_placeholders}
                )
                if engine_lang == "sr-Latn":
                    restored_core = sr_cyrillic_to_latin(restored_core)
                if termbase_entries:
                    restored_core = _apply_termbase_safe(restored_core, termbase_entries)
                value = f"{lead}{restored_core}{trail}"
                changed = True
            rebuilt_parts.append(value)
            cursor = value_end
        rebuilt_parts.append(body[cursor:])
        out.append("".join(rebuilt_parts) + "}}")
        pos = end
    if not changed:
        return text
    return "".join(out)


def _restore_resource_row_preserve_fields(
    source_text: str,
    translated_text: str,
    preserve_fields: tuple[str, ...],
) -> str:
    preserve = {_normalize_param_key(k) for k in preserve_fields}
    if not preserve:
        return translated_text

    def _extract_templates(text: str) -> list[str]:
        out: list[str] = []
        pos = 0
        while True:
            m = RESOURCE_ROW_START_RE.search(text, pos)
            if not m:
                break
            start = m.start()
            end = _find_balanced_template_end(text, start)
            if end is None:
                break
            out.append(text[start:end])
            pos = end
        return out

    source_templates = _extract_templates(source_text)
    trans_templates = _extract_templates(translated_text)
    if not source_templates or not trans_templates:
        return translated_text

    def _parse_param_values(tpl: str) -> dict[str, str]:
        body = tpl[:-2] if tpl.endswith("}}") else tpl
        matches = list(RESOURCE_ROW_PARAM_RE.finditer(body))
        out: dict[str, str] = {}
        for idx, m in enumerate(matches):
            key = _normalize_param_key(m.group(2))
            start = m.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
            out[key] = body[start:end]
        return out

    rebuilt = translated_text
    for src_tpl, tr_tpl in zip(source_templates, trans_templates):
        src_vals = _parse_param_values(src_tpl)
        tr_body = tr_tpl[:-2] if tr_tpl.endswith("}}") else tr_tpl
        matches = list(RESOURCE_ROW_PARAM_RE.finditer(tr_body))
        if not matches:
            continue
        parts: list[str] = []
        cursor = 0
        for idx, m in enumerate(matches):
            start = m.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(tr_body)
            parts.append(tr_body[cursor:start])
            key = _normalize_param_key(m.group(2))
            value = tr_body[start:end]
            if key in preserve and key in src_vals:
                value = src_vals[key]
            parts.append(value)
            cursor = end
        parts.append(tr_body[cursor:])
        patched_tpl = "".join(parts) + "}}"
        rebuilt = rebuilt.replace(tr_tpl, patched_tpl, 1)
    return rebuilt


def _tokenize_links(
    text: str, lang: str, known_langs: set[str] | None = None
) -> tuple[str, dict[str, str], list[tuple[str, str]], set[str], set[str]]:
    placeholders: dict[str, str] = {}
    link_meta: list[tuple[str, str]] = []
    source_targets: set[str] = set()
    required_tokens: set[str] = set()

    known_langs = known_langs or set()

    def _replace(match: re.Match) -> str:
        target = match.group(1)
        display = match.group(2)
        if not _is_safe_internal_link(target):
            return match.group(0)

        page, anchor = (target.split("#", 1) + [""])[:2]
        base_page = _strip_known_lang_suffix(page, known_langs)
        source_targets.add(base_page)
        if page.endswith(f"/{lang}"):
            new_target = page
        else:
            new_target = f"{base_page}/{lang}"
        if anchor:
            new_target = f"{new_target}#{anchor}"

        token = f"ZZZLINK{len(placeholders)}ZZZ"
        if display is None:
            # Implicit display: keep full link protected to avoid changing names.
            placeholders[token] = f"[[{new_target}]]"
        else:
            # Explicit display is translated separately via link_display_translated.
            placeholders[token] = f"[[{new_target}|{display}]]"
            link_meta.append((new_target, display))
        required_tokens.add(token)
        return token

    return LINK_RE.sub(_replace, text), placeholders, link_meta, source_targets, required_tokens




def _strip_empty_paragraphs(text: str) -> str:
    sentinel = "__EMPTY_PARAGRAPH__"
    cleaned = EMPTY_P_RE.sub(sentinel, text)
    cleaned = re.sub(rf"\n[ \t]*{re.escape(sentinel)}[ \t]*\n", "\n", cleaned)
    cleaned = cleaned.replace(sentinel, "")
    return cleaned.strip()

def _collapse_blank_lines(text: str) -> str:
    # Collapse 3+ newlines to 2 and trim leading blank lines.
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.lstrip("\n")


def _strip_unresolved_placeholders(text: str) -> str:
    return UNRESOLVED_PLACEHOLDER_RE.sub("", text)


def _is_nonlinguistic_segment(text: str) -> bool:
    # Treat markup-only/structural units as copy-through to avoid unnecessary MT calls.
    # Source language is English, so ASCII letters are a sufficient prose signal.
    return re.search(r"[A-Za-z]", text) is None


def _restore_missing_refs_from_source(source: str, translated: str) -> str:
    # MT can occasionally drop <ref> blocks; enforce source ref preservation.
    refs = REF_TOKEN_RE.findall(source)
    if not refs:
        return translated
    out = translated
    for ref in refs:
        if ref not in out:
            out = f"{out}\n{ref}"
    return out


def _restore_underdevelopment_from_source(source: str, translated: str) -> str:
    # Keep {{UnderDevelopment}} when present in source segment.
    if not UNDER_DEVELOPMENT_RE.search(source):
        return translated
    if UNDER_DEVELOPMENT_RE.search(translated):
        return translated
    return f"{translated}\n{{{{UnderDevelopment}}}}"


def _has_template(text: str, template_name: str) -> bool:
    if not template_name.strip():
        return False
    # Allow underscores/spaces in both source and configured template names.
    token = re.escape(template_name.strip()).replace(r"\ ", r"[ _]+")
    pattern = re.compile(r"\{\{\s*" + token + r"\b", re.IGNORECASE)
    return bool(pattern.search(text))


def _cache_compatible_with_source(
    source: str,
    cached: str,
    strict_templates: tuple[str, ...],
) -> bool:
    # Keep cache strict for structural templates that must mirror source.
    # Configurable by BOT_CACHE_STRICT_TEMPLATES (comma-separated names).
    for template_name in strict_templates:
        if _has_template(source, template_name) != _has_template(cached, template_name):
            return False
    return True


def _restore_magic_words_from_source(source: str, translated: str) -> str:
    # Preserve MediaWiki magic words (for example __NOTOC__) if MT drops them.
    source_words = {m.group(0) for m in MAGIC_WORD_RE.finditer(source)}
    if not source_words:
        return translated
    out = translated
    for word in sorted(source_words):
        if word in out:
            continue
        out = f"{out}{word}"
    return out


def _missing_required_tokens(text: str, required_tokens: set[str]) -> set[str]:
    missing: set[str] = set()
    for token in required_tokens:
        if token not in text:
            missing.add(token)
    return missing


def _dedupe_displaytitle(text: str) -> str:
    matches = list(DISPLAYTITLE_RE.finditer(text))
    if len(matches) <= 1:
        return text
    first = matches[0].group(0)
    # remove all displaytitles, then prepend the first one
    cleaned = DISPLAYTITLE_RE.sub("", text).strip()
    return f"{first}\n{cleaned}"


def _extract_displaytitle(text: str) -> str | None:
    match = DISPLAYTITLE_RE.search(text)
    if not match:
        return None
    raw = match.group(0)
    # {{DISPLAYTITLE:...}}
    inner = raw.split(":", 1)[-1].rstrip("}").rstrip("}")
    return inner.strip()


def _source_title_for_displaytitle(
    norm_title: str, wikitext: str, segments: list[Segment]
) -> str:
    # Prefer source DISPLAYTITLE from the first numeric source unit, then full source wikitext.
    numeric = sorted((int(seg.key), seg) for seg in segments if str(seg.key).isdigit())
    if numeric:
        value = _extract_displaytitle(numeric[0][1].text)
        if value:
            return value
    value = _extract_displaytitle(wikitext)
    if value:
        return value
    # Fallback: use the leaf title, not full path.
    return norm_title.rsplit("/", 1)[-1].strip()


def _page_display_title_unit_titles(norm_title: str, lang: str) -> list[str]:
    page_title_variants = [norm_title]
    underscored = norm_title.replace(" ", "_")
    if underscored != norm_title:
        page_title_variants.append(underscored)
    unit_key_variants = ["Page display title", "Page_display_title"]
    out: list[str] = []
    for page_variant in page_title_variants:
        for unit_key in unit_key_variants:
            out.append(f"Translations:{page_variant}/{unit_key}/{lang}")
    # Keep order but de-duplicate.
    seen: set[str] = set()
    ordered: list[str] = []
    for title in out:
        if title in seen:
            continue
        seen.add(title)
        ordered.append(title)
    return ordered


def _upsert_page_display_title_unit(
    client: MediaWikiClient, norm_title: str, lang: str, displaytitle_value: str
) -> str:
    candidates = _page_display_title_unit_titles(norm_title, lang)
    chosen = candidates[0]
    existing_text: str | None = None
    for candidate in candidates:
        try:
            text, _, _ = client.get_page_wikitext(candidate)
            chosen = candidate
            existing_text = text
            break
        except Exception:
            continue
    if existing_text is not None and existing_text.strip() == displaytitle_value.strip():
        return chosen
    summary = "Machine translation by bot"
    client.edit(chosen, displaytitle_value, summary, bot=True)
    return chosen


def _remove_disclaimer_tables(text: str) -> str:
    return DISCLAIMER_TABLE_RE.sub("", text).strip()


def _parse_status_template(text: str) -> dict[str, str]:
    match = TRANSLATION_STATUS_TEMPLATE_RE.search(text)
    if not match:
        return {}
    raw = match.group(0).strip().lstrip("{").rstrip("}")
    parts = raw.split("|")[1:]
    params: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        params[key.strip()] = value.strip()
    return params


def _build_status_template(
    status: str,
    source_rev_at_translation: str | None = None,
    reviewed_at: str | None = None,
    reviewed_by: str | None = None,
    outdated_source_rev: str | None = None,
) -> str:
    parts = [f"status={status}"]
    if source_rev_at_translation:
        parts.append(f"source_rev_at_translation={source_rev_at_translation}")
    if reviewed_at:
        parts.append(f"reviewed_at={reviewed_at}")
    if reviewed_by:
        parts.append(f"reviewed_by={reviewed_by}")
    if outdated_source_rev:
        parts.append(f"outdated_source_rev={outdated_source_rev}")
    return "{{Translation_status|" + "|".join(parts) + "}}"


def _upsert_status_template(
    text: str,
    status: str,
    source_rev_at_translation: str | None = None,
    reviewed_at: str | None = None,
    reviewed_by: str | None = None,
    outdated_source_rev: str | None = None,
) -> str:
    base = TRANSLATION_STATUS_TEMPLATE_RE.sub("", text).lstrip()
    tpl = _build_status_template(
        status=status,
        source_rev_at_translation=source_rev_at_translation,
        reviewed_at=reviewed_at,
        reviewed_by=reviewed_by,
        outdated_source_rev=outdated_source_rev,
    )
    if base.startswith("{{DISPLAYTITLE:"):
        out = f"{tpl}{base}".strip()
    else:
        out = f"{tpl}\n{base}".strip()
    out = _normalize_leading_status_directives(out)
    out = _compact_leading_metadata_preamble(out)
    out = _normalize_leading_div(out)
    return out


def _translation_status_from_props(props: dict[str, object]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in (
        "dr_translation_status",
        "dr_source_rev_at_translation",
        "dr_reviewed_at",
        "dr_reviewed_by",
        "dr_outdated_source_rev",
    ):
        value = props.get(key)
        if value is None:
            continue
        out[key] = str(value).strip()
    return out


def _translation_status_from_ai_info(info: dict[str, object]) -> dict[str, str]:
    out: dict[str, str] = {}
    status = info.get("status")
    if status:
        out["dr_translation_status"] = str(status).strip()
    source_rev = info.get("source_rev")
    if source_rev is not None and str(source_rev).strip():
        out["dr_source_rev_at_translation"] = str(source_rev).strip()
    outdated_source_rev = info.get("outdated_source_rev")
    if outdated_source_rev is not None and str(outdated_source_rev).strip():
        out["dr_outdated_source_rev"] = str(outdated_source_rev).strip()
    reviewed_by = info.get("reviewed_by")
    if reviewed_by:
        out["dr_reviewed_by"] = str(reviewed_by).strip()
    reviewed_at = info.get("reviewed_at")
    if reviewed_at:
        out["dr_reviewed_at"] = str(reviewed_at).strip()
    return out


def _write_ai_status_with_retry(
    client: MediaWikiClient,
    translated_title: str,
    status: str,
    source_rev: str | None = None,
    outdated_source_rev: str | None = None,
    source_title: str | None = None,
    source_lang: str | None = None,
) -> None:
    logger = logging.getLogger("translate")
    for attempt in range(2):
        try:
            client.set_ai_translation_status(
                title=translated_title,
                status=status,
                source_rev=source_rev,
                outdated_source_rev=outdated_source_rev,
                source_title=source_title,
                source_lang=source_lang,
            )
            logger.info(
                "updated ai metadata for %s (status=%s, source_rev=%s)",
                translated_title,
                status,
                source_rev or "",
            )
            return
        except Exception as exc:
            if attempt == 0:
                time.sleep(1)
                continue
            logger.warning(
                "failed to update ai translation metadata for %s (status=%s, source_rev=%s): %s",
                translated_title,
                status,
                source_rev or "",
                exc,
            )


def _translation_status_from_unit1(
    client: MediaWikiClient, norm_title: str, lang: str, source_lang: str = "en"
) -> dict[str, str]:
    try:
        unit_key = _first_source_unit_key(client, norm_title, source_lang)
        unit1_title = _unit_title(norm_title, unit_key, lang)
        unit1_text, _, _ = client.get_page_wikitext(unit1_title)
        params = _parse_status_template(unit1_text)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for key in ("status", "source_rev_at_translation", "reviewed_at", "reviewed_by", "outdated_source_rev"):
        if params.get(key):
            out_key = "dr_translation_status" if key == "status" else f"dr_{key}"
            out[out_key] = str(params[key]).strip()
    return out


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


def _restore_html_tags(source: str, translated: str) -> str:
    source_tags = HTML_TAG_RE.findall(source)
    if not source_tags:
        return translated
    translated_tags = HTML_TAG_RE.findall(translated)
    if not translated_tags:
        return translated
    out = translated
    for src, tr in zip(source_tags, translated_tags):
        out = out.replace(tr, src, 1)
    return out


def _restore_category_namespace(source: str, translated: str) -> str:
    source_category_count = len(
        re.findall(r"\[\[\s*Category\s*:", source, flags=re.IGNORECASE)
    )
    if source_category_count == 0:
        return translated

    remaining = source_category_count

    def _repl(match: re.Match) -> str:
        nonlocal remaining
        if remaining <= 0:
            return match.group(0)
        ns = match.group(1).strip().lower()
        # Keep non-category namespaces untouched.
        if ns in {"file", "image", "media", "template"}:
            return match.group(0)
        rest = match.group(2)
        remaining -= 1
        return f"[[Category:{rest}]]"

    return NS_LINK_RE.sub(_repl, translated)


def _restore_internal_link_targets(
    source: str, translated: str, lang: str, known_langs: set[str] | None = None
) -> str:
    known_langs = known_langs or set()
    source_links = [m for m in LINK_RE.finditer(source) if _is_safe_internal_link(m.group(1))]
    translated_links = [m for m in LINK_RE.finditer(translated) if _is_safe_internal_link(m.group(1))]
    if not source_links or not translated_links:
        return translated
    out = translated
    for src, tr in zip(source_links, translated_links):
        src_target = src.group(1)
        src_page, src_anchor = (src_target.split("#", 1) + [""])[:2]
        src_base_page = _strip_known_lang_suffix(src_page, known_langs)
        if src_page.endswith(f"/{lang}"):
            new_page = src_page
        else:
            new_page = f"{src_base_page}/{lang}"
        new_target = f"{new_page}#{src_anchor}" if src_anchor else new_page
        tr_display = tr.group(2)
        replacement = f"[[{new_target}|{tr_display}]]" if tr_display is not None else f"[[{new_target}]]"
        out = out.replace(tr.group(0), replacement, 1)
    return out


def _normalize_heading_body_spacing(text: str) -> str:
    # Keep only one newline between a heading line and the following body line.
    text = re.sub(r"(={2,6}[^\n]*={2,6})\n{2,}", r"\1\n", text)
    # If MT glues heading and body on one line, split after closing heading marker.
    text = re.sub(r"(={2,6}[^\n]*={2,6})[ \t]+([^\n])", r"\1\n\2", text)
    # If MT splits a heading across lines, merge back to one valid heading line.
    text = re.sub(
        r"(?m)^([ \t]*)(={2,6})[ \t]*\n[ \t]*([^\n]+?)[ \t]*(\2)[ \t]*$",
        r"\1\2 \3 \4",
        text,
    )
    return text


def _strip_accidental_preformat(source: str, translated: str) -> str:
    # MediaWiki treats leading-space lines as <pre>. Remove accidental indentation
    # when source line doesn't use preformat and translation is uniformly indented.
    src_lines = [ln for ln in source.splitlines() if ln.strip()]
    tr_lines = [ln for ln in translated.splitlines() if ln.strip()]
    if not tr_lines:
        return translated
    if any(ln.startswith(" ") for ln in src_lines):
        return translated
    if all(ln.startswith(" ") for ln in tr_lines):
        return "\n".join(ln[1:] if ln.startswith(" ") else ln for ln in translated.splitlines())
    return translated


def _first_source_unit_key(client: MediaWikiClient, norm_title: str, source_lang: str) -> str:
    try:
        keys = client.list_translation_unit_keys(norm_title, source_lang)
        numeric = sorted((int(k) for k in keys if str(k).isdigit()))
        if numeric:
            return str(numeric[0])
    except Exception:
        pass
    return "1"


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _toggle_trailing_newline(text: str) -> str:
    if text.endswith("\n"):
        return text.rstrip("\n")
    return text + "\n"


def _normalized_text_equivalent(text: str) -> str:
    # MediaWiki can normalize Unicode combining marks on save (for example
    # Hebrew niqqud order). Compare canonicalized text to avoid false mismatches.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text).strip()


def _fix_broken_links(text: str, lang: str) -> str:
    def _repl(match: re.Match) -> str:
        display = match.group(1)
        return f"[[{display}/{lang}|{display}]]"
    return BROKEN_LINK_RE.sub(_repl, text)


def _rewrite_internal_links_to_lang_with_source(
    text: str,
    lang: str,
    source_targets: set[str],
    implicit_display_by_target: dict[str, str] | None = None,
    known_langs: set[str] | None = None,
) -> str:
    implicit_display_by_target = implicit_display_by_target or {}
    known_langs = set(known_langs or set())
    known_langs.add(lang)

    def _trim_lang_suffix(value: str) -> str:
        return _strip_known_lang_suffix(value, known_langs)

    def _repl(match: re.Match) -> str:
        target = match.group(1)
        display_raw = match.group(2)
        has_explicit_display = display_raw is not None
        display = display_raw or target
        if not _is_safe_internal_link(target):
            return match.group(0)
        page, anchor = (target.split("#", 1) + [""])[:2]
        base_page = _trim_lang_suffix(page)
        if page.endswith(f"/{lang}") or base_page not in source_targets:
            new_target = page
        else:
            new_target = f"{page}/{lang}"
        if anchor:
            new_target = f"{new_target}#{anchor}"
        if not has_explicit_display:
            localized = implicit_display_by_target.get(base_page)
            if localized:
                return f"[[{new_target}|{localized}]]"
            return f"[[{new_target}]]"

        localized = implicit_display_by_target.get(base_page)
        if localized and (display == page or display == base_page or display == target):
            display = localized

        if display == target or display == new_target:
            display = _trim_lang_suffix(display)
        return f"[[{new_target}|{display}]]"
    return LINK_RE.sub(_repl, text)


def _translated_target_display_title(
    client: MediaWikiClient, target_page: str, lang: str
) -> str | None:
    candidates = _page_display_title_unit_titles(target_page, lang)
    for candidate in candidates:
        try:
            text, _, _ = client.get_page_wikitext(candidate)
            value = (text or "").strip()
            if value:
                return value
        except Exception:
            continue
    return None


def _translation_status_meta_for_page(
    client: MediaWikiClient,
    norm_title: str,
    lang: str,
    source_lang: str = "en",
) -> dict[str, str]:
    translated_page_title = f"{norm_title}/{lang}"
    out: dict[str, str] = {}
    try:
        out = _translation_status_from_ai_info(client.get_ai_translation_info(translated_page_title))
    except Exception:
        out = {}
    try:
        props, _, _ = client.get_page_props(translated_page_title)
        out = {**_translation_status_from_props(props), **out}
    except Exception:
        pass
    if "dr_translation_status" not in out:
        out = {**out, **_translation_status_from_unit1(client, norm_title, lang, source_lang=source_lang)}
    return out


def _build_no_translate_terms(
    entries: list[dict[str, str | bool | None]]
) -> list[tuple[str, str]]:
    terms: list[tuple[str, str]] = []
    for entry in entries:
        if not entry.get("forbidden"):
            continue
        term = (entry.get("term") or "").strip()
        preferred = (entry.get("preferred") or "").strip()
        if term and preferred:
            terms.append((term, preferred))
    return terms


def _protect_terms(text: str, terms: list[tuple[str, str]]) -> tuple[str, dict[str, str]]:
    if not terms:
        return text, {}
    placeholders: dict[str, str] = {}
    for term, preferred in sorted(terms, key=lambda t: len(t[0]), reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)

        def _repl(match: re.Match) -> str:
            token = f"__NT{len(placeholders)}__"
            placeholders[token] = preferred
            return token

        text = pattern.sub(_repl, text)
    return text, placeholders


def _should_translate_display(display: str, terms: list[tuple[str, str]]) -> bool:
    if not terms:
        return True
    display_norm = display.strip().lower()
    for term, _ in terms:
        if display_norm == term.strip().lower():
            return False
    return True


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


def _normalize_leading_div(text: str) -> str:
    # Avoid leading blank line/paragraph before a top-level div.
    text = re.sub(r"(__NOTOC__)\s*\n+\s*(<div\b)", r"\1\2", text, count=1)
    text = re.sub(r"(\{\{DISPLAYTITLE:[^}]+\}\})\s*\n+\s*(__NOTOC__)\s*\n+\s*(<div\b)", r"\1__NOTOC__\3", text, count=1)
    return text


def _normalize_leading_status_directives(text: str) -> str:
    # Compact top metadata/directives into a single leading line:
    # {{Translation_status...}}{{DISPLAYTITLE:...}}__NOTOC__[[File:...]]
    text = re.sub(
        r"(\{\{\s*Translation_status\b[^{}]*\}\})\s*\n+\s*(\{\{DISPLAYTITLE:[^}]+\}\})",
        r"\1\2",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(\{\{DISPLAYTITLE:[^}]+\}\})\s*\n+\s*(__NOTOC__)",
        r"\1__NOTOC__",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(__NOTOC__)\s*\n+\s*(\[\[File:[^\]]+\]\])",
        r"\1\2",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(__NOTOC__)\s+(?=\S)",
        r"\1",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    # Do not leave an empty spacer line before content after top metadata.
    text = re.sub(
        r"^((?:\{\{\s*Translation_status\b[^{}]*\}\})?(?:\{\{DISPLAYTITLE:[^}]+\}\})(?:__NOTOC__)?(?:\[\[File:[^\]]+\]\])?)\s*\n{2,}",
        r"\1\n",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    return text


def _compact_leading_metadata_preamble(text: str) -> str:
    # Keep leading metadata directives contiguous with no blank line before content.
    lines = text.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1

    preamble: list[str] = []
    while i < len(lines):
        line = lines[i].strip()
        if line == "":
            i += 1
            continue
        if LEADING_META_LINE_RE.fullmatch(line):
            preamble.append(line)
            i += 1
            continue
        break

    if not preamble:
        return text.lstrip("\n")

    while i < len(lines) and lines[i].strip() == "":
        i += 1

    rest = "\n".join(lines[i:])
    # Avoid preformatted rendering caused by a leading space immediately after
    # metadata directives (__NOTOC__/DISPLAYTITLE/Translation_status).
    rest = rest.lstrip(" \t")
    if rest:
        return "".join(preamble) + rest
    return "".join(preamble)


def _normalize_heading_lines(text: str) -> str:
    def _repl(match: re.Match) -> str:
        eq = match.group(1)
        title = match.group(2).strip()
        return f"\n{eq} {title} {eq}\n"

    return re.sub(r"[ \t]*(={2,6})[ \t]*([^\n]*?)[ \t]*\1[ \t]*", _repl, text)


def _strip_heading_list_prefix(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if re.match(r"^\s*[*#:;]\s*={2,6}", line):
            line = re.sub(r"^\s*[*#:;]\s*", "", line)
        lines.append(line)
    return "\n".join(lines)


def _align_list_markers(source: str, translated: str) -> str:
    source_lines = source.splitlines()
    translated_lines = translated.splitlines()
    markers = ("*", "#", ";", ":")
    fixed = list(translated_lines)
    t_idx = 0
    for src_line in source_lines:
        src_strip = src_line.lstrip()
        if src_strip == "":
            continue
        while t_idx < len(fixed) and fixed[t_idx].strip() == "":
            t_idx += 1
        if t_idx >= len(fixed):
            break
        tr_strip = fixed[t_idx].lstrip()
        if src_strip.startswith("="):
            while t_idx < len(fixed) and not fixed[t_idx].lstrip().startswith("="):
                t_idx += 1
                while t_idx < len(fixed) and fixed[t_idx].strip() == "":
                    t_idx += 1
            if t_idx >= len(fixed):
                break
            t_idx += 1
            continue
        if src_strip.startswith(markers):
            if not tr_strip.startswith(markers):
                marker = src_strip[0]
                fixed[t_idx] = f"{marker} {tr_strip}".rstrip()
            t_idx += 1
            continue
        if tr_strip.startswith(markers):
            fixed[t_idx] = tr_strip.lstrip("*#;:").lstrip()
        t_idx += 1
    return "\n".join(fixed)


def _is_redirect_wikitext(text: str) -> bool:
    return bool(REDIRECT_RE.search(text.lstrip("\ufeff")))


def _fetch_unit_sources(
    client: MediaWikiClient, norm_title: str, keys: list[str], source_lang: str
) -> list[Segment]:
    segments: list[Segment] = []
    for key in keys:
        unit_title = f"Translations:{norm_title}/{key}/{source_lang}"
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
    matches = list(re.finditer(r"<!--T:(\d+)-->", wikitext))
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
    parser.add_argument("--fuzzy", action="store_true", default=False)
    parser.add_argument("--no-fuzzy", action="store_false", dest="fuzzy")
    parser.add_argument("--start-key", type=int, default=None)
    parser.add_argument("--max-keys", type=int, default=None)
    parser.add_argument("--sleep-ms", type=int, default=200)
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--clear-fuzzy", action="store_true", default=True)
    parser.add_argument("--no-clear-fuzzy", action="store_false", dest="clear_fuzzy")
    parser.add_argument("--approve-only", action="store_true", help="only approve assembled page")
    parser.add_argument("--retry-approve", action="store_true", help="retry approve if assembled page missing")
    parser.add_argument("--rebuild-only", action="store_true", help="use cached translations only; no MT calls")
    parser.add_argument("--no-cache", action="store_true", help="ignore cached translations and retranslate")
    parser.add_argument("--auto-review", action="store_true", default=False)
    parser.add_argument("--no-auto-review", action="store_false", dest="auto_review")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    if args.rebuild_only and args.no_cache:
        raise SystemExit("--rebuild-only cannot be used with --no-cache")

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

    source_wikitext_en, rev_id, norm_title = client.get_page_wikitext(args.title)
    if _is_redirect_wikitext(source_wikitext_en):
        logging.getLogger("translate").info("skip redirect page: %s", norm_title)
        return {"status": "skip_redirect", "title": norm_title, "source_rev": str(rev_id)}
    source_rev = str(rev_id)
    translated_page_title = f"{norm_title}/{args.lang}"
    ai_info: dict[str, object] = {}
    try:
        ai_info = client.get_ai_translation_info(translated_page_title)
    except Exception as exc:
        logging.getLogger("translate").warning(
            "failed to read ai translation metadata for %s: %s",
            translated_page_title,
            exc,
        )
    props, _, _ = client.get_page_props(translated_page_title)
    status_meta = _translation_status_meta_for_page(
        client, norm_title, args.lang, source_lang=cfg.source_lang
    )
    status = status_meta.get("dr_translation_status", "").strip().lower() or "machine"
    if status not in ("machine", "reviewed", "outdated"):
        status = "machine"
    if status in ("reviewed", "outdated"):
        source_at_translation = status_meta.get("dr_source_rev_at_translation", "").strip()
        if status == "reviewed" and source_at_translation != source_rev:
            logging.getLogger("translate").info(
                "status lock: %s is reviewed and source changed (%s -> %s); marking outdated",
                translated_page_title,
                source_at_translation or "?",
                source_rev,
            )
            try:
                metadata_key = _first_source_unit_key(client, norm_title, cfg.source_lang)
                unit1_title = _unit_title(norm_title, metadata_key, args.lang)
                unit1_text, _, _ = client.get_page_wikitext(unit1_title)
                updated_unit1 = _upsert_status_template(
                    _remove_disclaimer_tables(unit1_text),
                    status="outdated",
                )
                if not args.dry_run:
                    client.edit(
                        unit1_title,
                        updated_unit1,
                        "Bot: mark translation status as outdated (source changed)",
                        bot=True,
                    )
                    logging.getLogger("translate").info("edited %s", unit1_title)
                    _write_ai_status_with_retry(
                        client=client,
                        translated_title=translated_page_title,
                        status="outdated",
                        source_rev=source_at_translation or source_rev,
                        outdated_source_rev=source_rev,
                        source_title=norm_title,
                        source_lang=cfg.source_lang,
                    )
            except Exception as exc:
                logging.getLogger("translate").warning(
                    "failed to mark outdated for %s: %s", translated_page_title, exc
                )
            return {"status": "outdated", "title": norm_title, "source_rev": source_rev}
        logging.getLogger("translate").info(
            "status lock: skip translation for %s (status=%s)",
            translated_page_title,
            status,
        )
        return {"status": f"locked_{status}", "title": norm_title, "source_rev": source_rev}
    segments = _fetch_messagecollection_segments(client, norm_title, cfg.source_lang)
    if not segments:
        unit_keys = client.list_translation_unit_keys(norm_title, cfg.source_lang)
        if unit_keys:
            unit_keys = sorted(set(unit_keys), key=lambda k: int(k))
            segments = _fetch_unit_sources(
                client, norm_title, unit_keys, cfg.source_lang
            )
            if not segments:
                segments = split_translate_units(source_wikitext_en)
        else:
            segments = split_translate_units(source_wikitext_en)
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

    # Optional reviewed-language pivot, e.g. hr <- sr when sr is reviewed.
    pivot_source_lang = cfg.pivot_reviewed_map.get(args.lang) if cfg.pivot_reviewed_map else None
    pivot_active = False
    if pivot_source_lang and pivot_source_lang != cfg.source_lang and status == "machine":
        pivot_meta = _translation_status_meta_for_page(
            client, norm_title, pivot_source_lang, source_lang=cfg.source_lang
        )
        if pivot_meta.get("dr_translation_status", "").strip().lower() == "reviewed":
            pivoted: list[Segment] = []
            pivot_missing = 0
            for seg in segments:
                unit_title = _unit_title(norm_title, seg.key, pivot_source_lang)
                try:
                    pivot_text, _, _ = client.get_page_wikitext(unit_title)
                    pivot_text = TRANSLATION_STATUS_TEMPLATE_RE.sub("", pivot_text).strip()
                    if pivot_text:
                        pivoted.append(Segment(key=seg.key, text=pivot_text))
                    else:
                        pivot_missing += 1
                        pivoted.append(seg)
                except Exception:
                    pivot_missing += 1
                    pivoted.append(seg)
            segments = pivoted
            logging.getLogger("translate").info(
                "pivot source enabled for %s/%s: %s->%s (missing_units=%s)",
                norm_title,
                args.lang,
                pivot_source_lang,
                args.lang,
                pivot_missing,
            )
            pivot_active = True

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

    no_translate_terms = _build_no_translate_terms(termbase_entries)

    segments = sorted(segments, key=lambda s: int(s.key))
    metadata_key = segments[0].key if segments else "1"
    if args.start_key is not None:
        segments = [s for s in segments if int(s.key) >= args.start_key]
    if args.max_keys is not None and args.max_keys > 0:
        segments = segments[: args.max_keys]

    segment_checksums: dict[str, str] = {}
    cached_by_key: dict[str, str] = {}
    cached_source_by_key: dict[str, str] = {}
    existing_checksums: dict[str, str] = {}
    fuzzy_keys: set[str] = set()
    untranslated_keys: set[str] = set()
    try:
        lang_items = client.get_message_collection(
            f"page-{norm_title}", args.lang, include_properties=True
        )
        for item in lang_items:
            key = str(item.get("key", ""))
            unit_key = key.split("/")[-1]
            if not unit_key.isdigit():
                continue
            props = item.get("properties") or {}
            item_status = str(props.get("status", "")).strip().lower()
            if item_status == "fuzzy":
                fuzzy_keys.add(unit_key)
            if item_status == "untranslated":
                untranslated_keys.add(unit_key)
    except Exception:
        fuzzy_keys = set()
        untranslated_keys = set()
    disable_cache = False
    if cfg.pg_dsn and not args.no_cache:
        try:
            with get_conn(cfg.pg_dsn) as conn:
                existing_checksums = fetch_segment_checksums(conn, norm_title)
        except Exception:
            existing_checksums = {}
    if existing_checksums:
        current_keys = {seg.key for seg in segments}
        if set(existing_checksums.keys()) != current_keys:
            disable_cache = True
            logging.getLogger("translate").warning(
                "segment keys changed for %s; bypassing cache for this run",
                norm_title,
            )

    for seg in segments:
        checksum = _checksum(seg.text)
        segment_checksums[seg.key] = checksum
        if _is_nonlinguistic_segment(seg.text):
            cached_by_key[seg.key] = seg.text
            cached_source_by_key[seg.key] = "source-copy"
            continue
        if disable_cache:
            # Unit map changed after re-marking (keys added/removed/split/merged).
            # Skip checksum cache for this run to avoid reusing stale context.
            pass
        elif not args.no_cache and cfg.pg_dsn:
            try:
                with get_conn(cfg.pg_dsn) as conn:
                    cached = None
                    # L1: exact page/key cache hit when unit map is stable.
                    if existing_checksums.get(seg.key) == checksum:
                        cached = fetch_cached_translation(
                            conn, f"{norm_title}::{seg.key}", args.lang, checksum
                        )
                        if cached:
                            if _cache_compatible_with_source(
                                seg.text, cached, cfg.cache_strict_templates
                            ):
                                cached_by_key[seg.key] = cached
                                cached_source_by_key[seg.key] = "db-key"
                                continue
                            logging.getLogger("translate").info(
                                "cache incompatible %s key=%s source=db-key; bypassing cache",
                                norm_title,
                                seg.key,
                            )
                    # L2: cross-page content cache hit by source checksum.
                    cached = fetch_cached_translation_by_checksum(conn, checksum, args.lang)
                if cached:
                    if _cache_compatible_with_source(
                        seg.text, cached, cfg.cache_strict_templates
                    ):
                        cached_by_key[seg.key] = cached
                        cached_source_by_key[seg.key] = "db-checksum"
                    else:
                        logging.getLogger("translate").info(
                            "cache incompatible %s key=%s source=db-checksum; bypassing cache",
                            norm_title,
                            seg.key,
                        )
            except Exception:
                pass
        if args.rebuild_only and seg.key not in cached_by_key:
            unit_title = f"Translations:{norm_title}/{seg.key}/{args.lang}"
            try:
                unit_text, _, _ = client.get_page_wikitext(unit_title)
                if unit_text.strip():
                    if _cache_compatible_with_source(
                        seg.text, unit_text, cfg.cache_strict_templates
                    ):
                        cached_by_key[seg.key] = unit_text
                        cached_source_by_key[seg.key] = "wiki"
                    else:
                        logging.getLogger("translate").info(
                            "cache incompatible %s key=%s source=wiki; bypassing cache",
                            norm_title,
                            seg.key,
                        )
            except MediaWikiError:
                pass

    to_translate = [seg for seg in segments if seg.key not in cached_by_key]
    to_translate_keys = {seg.key for seg in to_translate}
    if args.rebuild_only and to_translate:
        missing = ", ".join(seg.key for seg in to_translate)
        raise SystemExit(f"rebuild-only: missing cached translations for keys {missing}")

    engine_lang = args.engine_lang or args.lang
    translate_source_lang = pivot_source_lang if pivot_active else cfg.source_lang
    # Project default: Serbian is published in Latin script.
    if args.lang == "sr" and engine_lang in {"sr", "sr-Cyrl"}:
        engine_lang = "sr-Latn"
    engine = None
    glossary_id = None
    if to_translate:
        project_id = _resolve_project_id(cfg.gcp_project_id, cfg.gcp_credentials_path)
        if not project_id:
            raise SystemExit("GCP project id is required (set GCP_PROJECT_ID or ensure in credentials)")
        engine = GoogleTranslateV3(
            project_id=project_id,
            location=cfg.gcp_location,
            credentials_path=cfg.gcp_credentials_path,
        )
        if cfg.gcp_glossaries:
            glossary_id = cfg.gcp_glossaries.get(args.lang)

    # Translate page title for DISPLAYTITLE (only if MT is enabled)
    source_display_title = _source_title_for_displaytitle(norm_title, source_wikitext_en, segments)
    title_translation = None
    title_locked_by_termbase = False
    for term, preferred in no_translate_terms:
        if source_display_title.strip().lower() == term.strip().lower():
            title_translation = preferred
            title_locked_by_termbase = True
            break
    if title_translation is None and engine is not None:
        title_translation = engine.translate(
            [source_display_title], translate_source_lang, engine_lang, glossary_id=glossary_id
        )[0].text
    if title_translation is None:
        title_translation = source_display_title
    if engine_lang == "sr-Latn":
        title_translation = sr_cyrillic_to_latin(title_translation)
    if termbase_entries:
        title_translation = _apply_termbase(title_translation, termbase_entries)

    known_langs = set(cfg.target_langs) | {cfg.source_lang}
    if pivot_active and pivot_source_lang:
        known_langs.add(pivot_source_lang)

    protected = []
    link_display_requests: dict[str, str] = {}
    required_link_tokens_by_key: dict[str, set[str]] = {}
    source_by_key: dict[str, str] = {}
    source_targets: set[str] = set()
    for seg in segments:
        (
            link_text,
            link_placeholders,
            link_meta,
            seg_targets,
            required_link_tokens,
        ) = _tokenize_links(seg.text, args.lang, known_langs=known_langs)
        source_targets.update(seg_targets)
        required_link_tokens_by_key[seg.key] = required_link_tokens
        source_by_key[seg.key] = seg.text
        if seg.key in cached_by_key:
            continue
        link_text, no_translate_placeholders = _protect_terms(link_text, no_translate_terms)
        result = protect_wikitext(link_text, protect_links=False)
        result.placeholders.update(link_placeholders)
        result.placeholders.update(no_translate_placeholders)
        for target, display in link_meta:
            if _should_translate_display(display, no_translate_terms):
                link_display_requests[target] = display
        protected.append((seg, result))

    translated = []
    if protected and engine is not None:
        translated = engine.translate(
            [p.text for _, p in protected], translate_source_lang, engine_lang, glossary_id=glossary_id
        )
    protected_map: dict[str, tuple[object, object]] = {}
    for (seg, ph), tr in zip(protected, translated):
        protected_map[seg.key] = (ph, tr)

    # Translate link display texts to ensure localized anchors
    link_display_translated: dict[str, str] = {}
    if link_display_requests and engine is not None:
        displays = list(link_display_requests.values())
        translated_displays = engine.translate(
            displays, translate_source_lang, engine_lang, glossary_id=glossary_id
        )
        for (target, _), tr in zip(link_display_requests.items(), translated_displays):
            link_display_translated[target] = tr.text

    implicit_targets: set[str] = set()
    for seg in segments:
        for m in LINK_RE.finditer(seg.text):
            tgt = m.group(1)
            disp = m.group(2)
            if disp is None and _is_safe_internal_link(tgt):
                page = tgt.split("#", 1)[0]
                implicit_targets.add(page)
    # Localized display titles for linked pages. We use this for:
    # - implicit links [[Page]]
    # - explicit links where display still equals the source title [[Page|Page]]
    localized_display_by_target: dict[str, str] = {}
    display_targets = set(implicit_targets) | set(source_targets)
    for target_page in sorted(display_targets):
        translated_display = _translated_target_display_title(client, target_page, args.lang)
        if translated_display:
            localized_display_by_target[target_page] = translated_display
    # Fallback for newly added languages: if target page translation does not
    # exist yet, translate the link label itself so users do not see English UI labels.
    missing_targets = [t for t in sorted(display_targets) if t not in localized_display_by_target]
    if missing_targets and engine is not None:
        fallback_labels: list[str] = []
        fallback_targets: list[str] = []
        for target_page in missing_targets:
            label = target_page.rsplit("/", 1)[-1].replace("_", " ").strip()
            if not label:
                continue
            if not _should_translate_display(label, no_translate_terms):
                continue
            fallback_targets.append(target_page)
            fallback_labels.append(label)
        if fallback_labels:
            fallback_translated = engine.translate(
                fallback_labels, translate_source_lang, engine_lang, glossary_id=glossary_id
            )
            for target_page, tr in zip(fallback_targets, fallback_translated):
                value = tr.text
                if engine_lang == "sr-Latn":
                    value = sr_cyrillic_to_latin(value)
                if termbase_entries:
                    value = _apply_termbase(value, termbase_entries)
                localized_display_by_target[target_page] = value

    translated_by_key: dict[str, str] = {}
    ordered_keys: list[str] = []
    # Delta default: only changed units are rewritten.
    # Segment 1 is always eligible because status/source-rev metadata is stored there.
    if args.rebuild_only:
        writable_keys: set[str] = {seg.key for seg in segments}
    elif disable_cache:
        # Unit map changed (for example after re-marking with new T-keys):
        # write all current keys even when using checksum cache so new unit
        # titles get populated.
        writable_keys = {seg.key for seg in segments}
        writable_keys.add(metadata_key)
    else:
        writable_keys = set(to_translate_keys)
        writable_keys.add(metadata_key)
    writable_keys.update(fuzzy_keys)
    # If Translate reports untranslated units, always write them in this run,
    # even if cache says "unchanged" for the source checksum.
    writable_keys.update(untranslated_keys)
    for seg in segments:
        if seg.key in cached_by_key:
            # Keep cached unit text verbatim in delta mode. This prevents churn where
            # unchanged units are repeatedly rewritten due normalization passes.
            translated_by_key[seg.key] = cached_by_key[seg.key]
            ordered_keys.append(seg.key)
            continue

        ph, tr = protected_map[seg.key]
        missing_link_tokens = _missing_required_tokens(
            tr.text, required_link_tokens_by_key.get(seg.key, set())
        )
        if missing_link_tokens:
            logging.getLogger("translate").warning(
                "link placeholder loss in segment %s for %s/%s: %s; retrying with fully protected links",
                seg.key,
                norm_title,
                args.lang,
                ", ".join(sorted(missing_link_tokens)),
            )
            if engine is None:
                raise RuntimeError(
                    f"link placeholder loss in segment {seg.key} for {norm_title}/{args.lang}: "
                    f"{', '.join(sorted(missing_link_tokens))}"
                )
            fallback_ph = protect_wikitext(seg.text, protect_links=True)
            fallback_tr = engine.translate(
                [fallback_ph.text], translate_source_lang, engine_lang, glossary_id=glossary_id
            )[0]
            tr_text = fallback_tr.text
            ph = fallback_ph
        else:
            tr_text = tr.text

        restored = restore_wikitext(tr_text, ph.placeholders)
        # Safety: restore any leftover placeholders in case MT preserved tokens
        for token, value in ph.placeholders.items():
            if token in restored:
                restored = restored.replace(token, value)
        restored = _restore_missing_refs_from_source(seg.text, restored)
        restored = _restore_underdevelopment_from_source(seg.text, restored)
        restored = _restore_magic_words_from_source(seg.text, restored)
        restored = _strip_accidental_preformat(seg.text, restored)
        restored = _restore_file_links(seg.text, restored)
        restored = _restore_html_tags(seg.text, restored)
        restored = _restore_category_namespace(seg.text, restored)
        restored = _restore_internal_link_targets(seg.text, restored, args.lang)
        restored = _strip_heading_list_prefix(restored)
        restored = _normalize_heading_lines(restored)
        restored = _normalize_heading_body_spacing(restored)
        restored = _align_list_markers(seg.text, restored)
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
            restored,
            args.lang,
            source_targets,
            localized_display_by_target,
            known_langs=known_langs,
        )
        restored = _restore_resource_row_preserve_fields(
            seg.text,
            restored,
            cfg.resource_row_preserve_fields,
        )
        restored = _localize_resource_row_internal_targets(
            restored,
            lang=args.lang,
            mw_api_url=cfg.mw_api_url,
            known_langs=known_langs,
        )
        restored = _translate_resource_row_templates(
            restored,
            engine=engine,
            source_lang=translate_source_lang,
            target_lang=engine_lang,
            glossary_id=glossary_id,
            no_translate_terms=no_translate_terms,
            termbase_entries=termbase_entries,
            engine_lang=engine_lang,
            preserve_fields=cfg.resource_row_preserve_fields,
            translate_fields=cfg.resource_row_translate_fields,
        )
        if termbase_entries:
            restored = _apply_termbase_safe(restored, termbase_entries)
        # Termbase substitutions can still touch preserved ResourceRow fields
        # (for example "5Rhythms" in title/creator). Re-apply preserved source
        # values as a final guard.
        restored = _restore_resource_row_preserve_fields(
            seg.text,
            restored,
            cfg.resource_row_preserve_fields,
        )
        restored = _localize_resource_row_internal_targets(
            restored,
            lang=args.lang,
            mw_api_url=cfg.mw_api_url,
            known_langs=known_langs,
        )
        restored = _strip_empty_paragraphs(restored)
        # Mark as fuzzy to indicate machine translation if enabled
        if args.fuzzy:
            restored = f"!!FUZZY!!\n{restored}"
        translated_by_key[seg.key] = restored
        ordered_keys.append(seg.key)

    # Remove any displaytitles from translated segments and add a single one.
    if ordered_keys and metadata_key in ordered_keys:
        displaytitle_value = None
        try:
            items = client.get_message_collection(f"page-{norm_title}", args.lang)
            for item in items:
                if str(item.get("key", "")) == f"{norm_title.replace(' ', '_')}/Page_display_title":
                    if item.get("translation"):
                        displaytitle_value = str(item.get("translation")).strip()
                    break
        except Exception:
            displaytitle_value = None
        if displaytitle_value is not None or not args.rebuild_only:
            for key in ordered_keys:
                translated_by_key[key] = DISPLAYTITLE_RE.sub("", translated_by_key[key]).strip()
        if title_locked_by_termbase:
            # If title is protected by termbase no-translate rules, force the
            # preferred value even when a previous Page display title exists.
            displaytitle_value = title_translation
        elif displaytitle_value is None and not args.rebuild_only:
            displaytitle_value = title_translation
        if displaytitle_value:
            if not args.dry_run:
                try:
                    unit_title = _upsert_page_display_title_unit(
                        client, norm_title, args.lang, displaytitle_value
                    )
                    logging.getLogger("translate").info(
                        "edited %s", unit_title
                    )
                except Exception as exc:
                    logging.getLogger("translate").warning(
                        "failed to upsert page display title unit for %s/%s: %s",
                        norm_title,
                        args.lang,
                        exc,
                    )
            displaytitle = f"{{{{DISPLAYTITLE:{displaytitle_value}}}}}"
            translated_by_key[metadata_key] = f"{displaytitle}\n{translated_by_key[metadata_key]}"
        translated_by_key[metadata_key] = _strip_empty_paragraphs(translated_by_key[metadata_key])
        translated_by_key[metadata_key] = _normalize_leading_directives(
            translated_by_key[metadata_key]
        )
        translated_by_key[metadata_key] = _normalize_leading_status_directives(
            translated_by_key[metadata_key]
        )
        translated_by_key[metadata_key] = _normalize_leading_div(
            translated_by_key[metadata_key]
        )
        translated_by_key[metadata_key] = _collapse_blank_lines(
            translated_by_key[metadata_key]
        )

    if metadata_key in translated_by_key:
        translated_by_key[metadata_key] = _upsert_status_template(
            _remove_disclaimer_tables(translated_by_key[metadata_key]),
            status="machine",
        )

    for key in ordered_keys:
        translated_by_key[key] = _strip_empty_paragraphs(translated_by_key[key])
        translated_by_key[key] = _remove_disclaimer_tables(translated_by_key[key])
        if termbase_entries and key in to_translate_keys:
            translated_by_key[key] = _apply_termbase_safe(
                translated_by_key[key], termbase_entries
            )
        if key in to_translate_keys:
            translated_by_key[key] = _align_list_markers(
                source_by_key.get(key, ""), translated_by_key[key]
            )
        translated_by_key[key] = _strip_unresolved_placeholders(translated_by_key[key])

    # Final pass after status/displaytitle insertion
    for key in ordered_keys:
        translated_by_key[key] = _strip_unresolved_placeholders(translated_by_key[key])

    for key in ordered_keys:
        if key not in writable_keys:
            continue
        restored = translated_by_key[key]
        source_text = source_by_key.get(key, "")
        restored = _restore_missing_refs_from_source(source_text, restored)
        restored = _restore_underdevelopment_from_source(source_text, restored)
        restored = _restore_magic_words_from_source(source_text, restored)
        restored = _strip_accidental_preformat(source_text, restored)
        restored = _restore_file_links(source_text, restored)
        restored = _restore_html_tags(source_text, restored)
        restored = _restore_category_namespace(source_text, restored)
        restored = _rewrite_internal_links_to_lang_with_source(
            restored,
            args.lang,
            source_targets,
            localized_display_by_target,
            known_langs=known_langs,
        )
        restored = _restore_internal_link_targets(
            source_text, restored, args.lang, known_langs=known_langs
        )
        restored = _normalize_heading_body_spacing(restored)
        if key == metadata_key:
            restored = _compact_leading_metadata_preamble(restored)
        unit_title = _unit_title(norm_title, key, args.lang)
        summary = "Machine translation by bot"

        if args.dry_run:
            logging.getLogger("translate").info("DRY RUN edit %s", unit_title)
            continue

        current_revid_before = 0
        try:
            current_text, current_revid_before, _ = client.get_page_wikitext(unit_title)
            if _normalized_text_equivalent(current_text) == _normalized_text_equivalent(restored):
                if key in fuzzy_keys:
                    # Force a harmless edit to clear fuzzy state for this unit.
                    restored = _toggle_trailing_newline(current_text)
                else:
                    logging.getLogger("translate").info("skip unchanged %s", unit_title)
                    continue
        except MediaWikiError:
            # Unit might not exist yet; continue with edit.
            pass

        unit_saved = False
        last_verify_error: Exception | None = None
        for attempt in range(2):
            newrev = client.edit(unit_title, restored, summary, bot=True)
            verify_revid = 0
            try:
                verify_text, verify_revid, _ = client.get_page_wikitext(unit_title)
                last_verify_error = None
            except Exception as exc:
                verify_text = ""
                last_verify_error = exc
            if (
                last_verify_error is None
                and _normalized_text_equivalent(verify_text)
                == _normalized_text_equivalent(restored)
            ):
                # If edit API did not return newrevid and rev did not change,
                # treat this as a no-op success (already at desired content).
                # Some MediaWiki installs can report Success without a new rev.
                if newrev == 0 and verify_revid == current_revid_before:
                    unit_saved = True
                    break
                unit_saved = True
                break
            else:
                if last_verify_error is not None:
                    logging.getLogger("translate").warning(
                        "edit verify read failed for %s (attempt %d/2): %s",
                        unit_title,
                        attempt + 1,
                        last_verify_error,
                    )
                else:
                    diff = "\n".join(
                        difflib.unified_diff(
                            restored.splitlines(),
                            verify_text.splitlines(),
                            fromfile="expected",
                            tofile="saved",
                            lineterm="",
                            n=1,
                        )
                    )
                    if diff:
                        logging.getLogger("translate").warning(
                            "edit verify diff for %s (attempt %d/2):\n%s",
                            unit_title,
                            attempt + 1,
                            diff[:2500],
                        )
                    logging.getLogger("translate").warning(
                        "edit verify mismatch for %s (attempt %d/2); retrying",
                        unit_title,
                        attempt + 1,
                    )
            time.sleep(0.25)

        if not unit_saved:
            raise RuntimeError(
                f"failed to verify persisted unit edit for {unit_title}"
            )

        logging.getLogger("translate").info("edited %s", unit_title)
        if args.auto_review and newrev:
            client.translation_review(newrev)
            logging.getLogger("translate").info("reviewed %s", unit_title)
        if cfg.pg_dsn:
            try:
                with get_conn(cfg.pg_dsn) as conn:
                    upsert_segment(
                        conn,
                        norm_title,
                        key,
                        source_text,
                        segment_checksums.get(key, _checksum(source_text)),
                    )
                    segment_key = f"{norm_title}::{key}"
                    engine_used = cached_source_by_key.get(key, cfg.mt_primary)
                    upsert_translation(
                        conn,
                        segment_key,
                        args.lang,
                        restored,
                        engine_used,
                        segment_checksums.get(key, _checksum(source_text)),
                    )
            except Exception:
                pass
        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    if args.clear_fuzzy and not args.dry_run:
        # Re-fetch fuzzy status after edits because Translate may mark units fuzzy
        # asynchronously after mark-for-translation; initial snapshot can miss them.
        fuzzy_after: set[str] = set()
        try:
            lang_items = client.get_message_collection(
                f"page-{norm_title}", args.lang, include_properties=True
            )
            for item in lang_items:
                key = str(item.get("key", ""))
                unit_key = key.split("/")[-1]
                if not unit_key.isdigit():
                    continue
                props = item.get("properties") or {}
                if str(props.get("status", "")).strip().lower() == "fuzzy":
                    fuzzy_after.add(unit_key)
        except Exception:
            fuzzy_after = set()

        for key in sorted(fuzzy_after, key=lambda x: int(x)):
            unit_title = _unit_title(norm_title, key, args.lang)
            try:
                current_text, _, _ = client.get_page_wikitext(unit_title)
            except Exception:
                continue
            toggled = _toggle_trailing_newline(current_text)
            if toggled == current_text:
                continue
            try:
                client.edit(
                    unit_title,
                    toggled,
                    "Bot: clear fuzzy on machine translation",
                    bot=True,
                )
                logging.getLogger("translate").info("cleared fuzzy %s", unit_title)
            except Exception as exc:
                logging.getLogger("translate").warning(
                    "failed to clear fuzzy for %s: %s", unit_title, exc
                )

    if (
        not args.dry_run
        and ordered_keys
        and metadata_key not in ordered_keys
    ):
        try:
            unit1_title = _unit_title(norm_title, metadata_key, args.lang)
            unit1_text, _, _ = client.get_page_wikitext(unit1_title)
            unit1_updated = _upsert_status_template(
                _remove_disclaimer_tables(unit1_text),
                status="machine",
            )
            unit1_updated = _compact_leading_metadata_preamble(unit1_updated)
            client.edit(
                unit1_title,
                unit1_updated,
                "Bot: sync translation status metadata",
                bot=True,
            )
            logging.getLogger("translate").info("edited %s", unit1_title)
        except Exception as exc:
            logging.getLogger("translate").warning(
                "failed to sync status template for %s/%s: %s",
                norm_title,
                args.lang,
                exc,
            )

    if args.auto_approve:
        assembled_title = f"{norm_title}/{args.lang}"
        try:
            _, assembled_rev, _ = client.get_page_wikitext(assembled_title)
        except MediaWikiError as exc:
            logging.getLogger("translate").warning(
                "skip approve: %s", exc
            )
            return {"status": "skip_approve_no_revisions", "title": norm_title, "source_rev": source_rev}
        client.approve_revision(assembled_rev)
        logging.getLogger("translate").info(
            "approved assembled page %s", assembled_title
        )
        try:
            client.purge(assembled_title, forcelinkupdate=True)
            logging.getLogger("translate").info("purged %s", assembled_title)
        except Exception as exc:
            logging.getLogger("translate").warning(
                "failed to purge %s: %s", assembled_title, exc
            )

    if not args.dry_run:
        _write_ai_status_with_retry(
            client=client,
            translated_title=translated_page_title,
            status="machine",
            source_rev=source_rev,
            source_title=norm_title,
            source_lang=cfg.source_lang,
        )

    return {"status": "ok", "title": norm_title, "source_rev": source_rev}


if __name__ == "__main__":
    main()
