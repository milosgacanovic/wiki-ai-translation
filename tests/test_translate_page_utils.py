from bot.translate_page import (
    _strip_empty_paragraphs,
    _apply_termbase,
    _apply_termbase_safe,
    _is_redirect_wikitext,
    _strip_unresolved_placeholders,
    _fix_broken_links,
    _restore_file_links,
)


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
