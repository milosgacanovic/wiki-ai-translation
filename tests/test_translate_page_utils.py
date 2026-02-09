from bot.translate_page import _strip_empty_paragraphs, _apply_termbase, _is_redirect_wikitext


def test_strip_empty_paragraphs():
    text = "Hello<p><br></p>World"
    assert _strip_empty_paragraphs(text) == "HelloWorld"
    text = "{{DISPLAYTITLE:Foo}}\n<p><br></p>\nBody"
    assert _strip_empty_paragraphs(text) == "{{DISPLAYTITLE:Foo}}\nBody"


def test_apply_termbase():
    entries = [{"term": "kuriranih", "preferred": "odabranih"}]
    assert _apply_termbase("Biblioteka kuriranih resursa", entries) == "Biblioteka odabranih resursa"


def test_is_redirect_wikitext():
    assert _is_redirect_wikitext("#REDIRECT [[Target]]")
    assert _is_redirect_wikitext("  #redirect [[Target]]")
    assert not _is_redirect_wikitext("Regular content")
