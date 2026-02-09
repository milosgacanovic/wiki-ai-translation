from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PlaceholderResult:
    text: str
    placeholders: dict[str, str]


REF_BLOCK_RE = re.compile(r"<ref\b[^>]*>.*?</ref>", re.IGNORECASE | re.DOTALL)
REF_SELF_RE = re.compile(r"<ref\b[^>]*/\s*>", re.IGNORECASE)
REFERENCES_BLOCK_RE = re.compile(r"<references\b[^>]*>.*?</references>", re.IGNORECASE | re.DOTALL)
REFERENCES_SELF_RE = re.compile(r"<references\b[^>]*/\s*>", re.IGNORECASE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
URL_RE = re.compile(r"https?://\S+")
MAGIC_WORD_RE = re.compile(r"__([A-Z0-9_]+)__")
FILE_LINK_FULL_RE = re.compile(r"\[\[(?:File|Image):[^\]]+\]\]", re.IGNORECASE)


def _extract_balanced(text: str, open_tok: str, close_tok: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    i = 0
    depth = 0
    start = None
    while i < len(text) - 1:
        if text.startswith(open_tok, i):
            if depth == 0:
                start = i
            depth += 1
            i += len(open_tok)
            continue
        if text.startswith(close_tok, i) and depth > 0:
            depth -= 1
            i += len(close_tok)
            if depth == 0 and start is not None:
                spans.append((start, i))
                start = None
            continue
        i += 1
    return spans


def _replace_spans(text: str, spans: list[tuple[int, int]], placeholders: dict[str, str]) -> str:
    if not spans:
        return text
    out = []
    last = 0
    for idx, (s, e) in enumerate(spans):
        key = f"__PH{len(placeholders)}__"
        placeholders[key] = text[s:e]
        out.append(text[last:s])
        out.append(key)
        last = e
    out.append(text[last:])
    return "".join(out)


def protect_wikitext(text: str, protect_links: bool = True) -> PlaceholderResult:
    placeholders: dict[str, str] = {}

    # Protect refs first
    def _sub_ref(match: re.Match) -> str:
        key = f"__PH{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    # Protect HTML comments (e.g., BOT_DISCLAIMER markers)
    def _sub_comment(match: re.Match) -> str:
        key = f"__PH{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    # Protect MediaWiki magic words like __NOTOC__
    def _sub_magic(match: re.Match) -> str:
        key = f"__PH{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    # Protect File/Image links so nothing inside changes
    def _sub_file_link(match: re.Match) -> str:
        key = f"__PH{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    text = REFERENCES_BLOCK_RE.sub(_sub_ref, text)
    text = REFERENCES_SELF_RE.sub(_sub_ref, text)
    text = REF_BLOCK_RE.sub(_sub_ref, text)
    text = REF_SELF_RE.sub(_sub_ref, text)
    text = COMMENT_RE.sub(_sub_comment, text)
    text = MAGIC_WORD_RE.sub(_sub_magic, text)
    text = FILE_LINK_FULL_RE.sub(_sub_file_link, text)

    # Protect templates and links (balanced)
    template_spans = _extract_balanced(text, "{{", "}}")
    text = _replace_spans(text, template_spans, placeholders)

    if protect_links:
        link_spans = _extract_balanced(text, "[[", "]]")
        text = _replace_spans(text, link_spans, placeholders)

    # Protect URLs
    def _sub_url(match: re.Match) -> str:
        key = f"__PH{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    text = URL_RE.sub(_sub_url, text)

    return PlaceholderResult(text=text, placeholders=placeholders)


def restore_wikitext(text: str, placeholders: dict[str, str]) -> str:
    if not placeholders:
        return text
    # Replace in deterministic order to avoid partial overlaps
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text
