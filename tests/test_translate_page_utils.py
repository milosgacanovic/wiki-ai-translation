from bot.translate_page import (
    _strip_empty_paragraphs,
    _apply_termbase,
    _apply_termbase_safe,
    _is_redirect_wikitext,
    _missing_required_tokens,
    _strip_unresolved_placeholders,
    _tokenize_links,
    _fix_broken_links,
    _restore_file_links,
    _restore_html_tags,
    _restore_internal_link_targets,
    _source_title_for_displaytitle,
    _normalize_leading_status_directives,
    _compact_leading_metadata_preamble,
    _upsert_status_template,
    _toggle_trailing_newline,
    _normalize_heading_body_spacing,
)
from bot.segmenter import Segment


def test_strip_empty_paragraphs():
    text = "Hello<p><br></p>World"
    assert _strip_empty_paragraphs(text) == "HelloWorld"
    text = "{{DISPLAYTITLE:Foo}}\n<p><br></p>\nBody"
    assert _strip_empty_paragraphs(text) == "{{DISPLAYTITLE:Foo}}\nBody"


def test_apply_termbase():
    entries = [{"term": "kuriranih", "preferred": "odabranih"}]
    assert _apply_termbase("Biblioteka kuriranih resursa", entries) == "Biblioteka odabranih resursa"
    text = "[[Conscious Dance Practices/5Rhythms/sr|5Rhythms]]"
    entries = [{"term": "5Rhythms", "preferred": "5Ritmova"}]
    assert (
        _apply_termbase_safe(text, entries)
        == "[[Conscious Dance Practices/5Rhythms/sr|5Ritmova]]"
    )


def test_is_redirect_wikitext():
    assert _is_redirect_wikitext("#REDIRECT [[Target]]")
    assert _is_redirect_wikitext("  #redirect [[Target]]")
    assert not _is_redirect_wikitext("Regular content")


def test_strip_unresolved_placeholders():
    text = "Hello __PH0__ world __LINK1__"
    assert _strip_unresolved_placeholders(text) == "Hello  world "


def test_fix_broken_links():
    text = "[[__PH0__|Arjan Bouw]]"
    assert _fix_broken_links(text, "sr") == "[[Arjan Bouw/sr|Arjan Bouw]]"


def test_restore_file_links():
    source = "[[File:Arjan bouw.jpg|alt=Arjan Bouw|thumb|Photo: Luna Burger]]"
    translated = "[[File:Arjan Bouw.jpg|alt=Arjan Bou|slika|Fotografija: Luna Burger]]"
    assert _restore_file_links(source, translated) == source


def test_restore_html_tags_preserves_class_names():
    source = '<div class="dr-hero"><div class="dr-hero-inner">Text</div></div>'
    translated = '<div class="dr-eroe"><div class="dr-eroe-interno">Testo</div></div>'
    assert (
        _restore_html_tags(source, translated)
        == '<div class="dr-hero"><div class="dr-hero-inner">Testo</div></div>'
    )


def test_source_title_for_displaytitle_prefers_first_numeric_segment():
    segments = [Segment(key="8", text="{{DISPLAYTITLE:InnerMotion - The Guidebook - Acknowledgment}}")]
    assert (
        _source_title_for_displaytitle(
            "Conscious Dance Practices/InnerMotion/The Guidebook/Acknowledgment",
            "",
            segments,
        )
        == "InnerMotion - The Guidebook - Acknowledgment"
    )


def test_source_title_for_displaytitle_falls_back_to_leaf_title():
    segments = [Segment(key="2", text="Body only")]
    assert (
        _source_title_for_displaytitle(
            "Conscious Dance Practices/InnerMotion/The Guidebook/Acknowledgment",
            "No display title in source",
            segments,
        )
        == "Acknowledgment"
    )


def test_normalize_leading_status_directives():
    text = (
        "{{Translation_status|status=machine|source_rev_at_translation=5996}}\n"
        "{{DISPLAYTITLE:InnerMotion – Vodič – Zahvalnica}}\n\n"
        "__NOTOC__\n"
        "[[File:InnerMotion - The Guidebook - Acknowledgment.jpg|right|frameless]]\n"
        "Body"
    )
    out = _normalize_leading_status_directives(text)
    assert out.startswith(
        "{{Translation_status|status=machine|source_rev_at_translation=5996}}"
        "{{DISPLAYTITLE:InnerMotion – Vodič – Zahvalnica}}"
        "__NOTOC__"
        "[[File:InnerMotion - The Guidebook - Acknowledgment.jpg|right|frameless]]"
    )


def test_tokenize_links_keeps_label_translatable_and_protects_markup():
    text = "[[Conscious Dance Practices/InnerMotion/The Guidebook|reading the InnerMotion Guidebook]]"
    tokenized, placeholders, _, _, required = _tokenize_links(text, "it")
    assert tokenized.startswith("ZZZLINK")
    assert any(t.startswith("ZZZLINK") for t in required)
    assert "[[" not in tokenized and "]]" not in tokenized
    assert any(v.startswith("[[Conscious Dance Practices/InnerMotion/The Guidebook/it|") for v in placeholders.values())


def test_missing_required_tokens_detects_dropped_link_tokens():
    required = {"ZZZLINK0ZZZ", "ZZZLINK1ZZZ"}
    assert _missing_required_tokens("x ZZZLINK0ZZZ y", required) == {"ZZZLINK1ZZZ"}


def test_compact_leading_metadata_preamble_with_notoc_file_same_line():
    text = (
        "{{Translation_status|status=machine}}{{DISPLAYTITLE:InnerMotion - The Guidebook}}\n\n"
        "__NOTOC__[[File:InnerMotion - The Guide - Cover.jpg|border|right|frameless]]\n"
        "Body"
    )
    out = _compact_leading_metadata_preamble(text)
    assert out.startswith(
        "{{Translation_status|status=machine}}{{DISPLAYTITLE:InnerMotion - The Guidebook}}"
        "__NOTOC__[[File:InnerMotion - The Guide - Cover.jpg|border|right|frameless]]"
    )


def test_upsert_status_template_compacts_displaytitle_notoc_gap():
    text = "{{DISPLAYTITLE:InnerMotion - The Guidebook}}\n\n__NOTOC__\nBody"
    out = _upsert_status_template(text, status="machine")
    assert out.startswith(
        "{{Translation_status|status=machine}}{{DISPLAYTITLE:InnerMotion - The Guidebook}}__NOTOC__"
    )


def test_toggle_trailing_newline():
    assert _toggle_trailing_newline("A") == "A\n"
    assert _toggle_trailing_newline("A\n") == "A"


def test_restore_internal_link_targets_preserves_source_target_slug():
    source = "[[Future Directions and Vision|Future Directions and Vision]]"
    translated = "[[Future Directions & Vision/sr|Budući pravci i vizija]]"
    assert (
        _restore_internal_link_targets(source, translated, "sr")
        == "[[Future Directions and Vision/sr|Budući pravci i vizija]]"
    )


def test_normalize_heading_body_spacing():
    text = "==== [[Page|Heading]] ====\n\n\nBody"
    assert _normalize_heading_body_spacing(text) == "==== [[Page|Heading]] ====\nBody"
