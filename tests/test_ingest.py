from bot.ingest import (
    is_main_namespace,
    is_translation_wrapped,
    wrap_with_translate,
    should_skip_title,
    is_translation_subpage,
    is_redirect_wikitext,
)


def test_is_main_namespace():
    assert is_main_namespace("Main_Page")
    assert not is_main_namespace("Category:Foo")


def test_wrap_translate_round_trip():
    text = "Hello world\n==Header==\nContent."
    wrapped = wrap_with_translate(text)
    assert is_translation_wrapped(wrapped)
    assert wrapped.startswith("<translate>")
    assert wrapped.endswith("</translate>\n")


def test_should_skip_title_prefix():
    prefixes = ("Conscious Dance Practices/InnerMotion/The Guidebook/",)
    assert should_skip_title(
        "Conscious Dance Practices/InnerMotion/The Guidebook/Chapter_1", prefixes
    )
    assert not should_skip_title("Conscious Dance Practices/InnerMotion", prefixes)


def test_translation_subpage_detection():
    langs = ("sr", "it")
    assert is_translation_subpage("Appendices/sr", langs)
    assert is_translation_subpage("Future Directions and Vision/sr-el", langs)
    assert not is_translation_subpage("Core Values of DanceResource", langs)


def test_redirect_detection():
    assert is_redirect_wikitext("#REDIRECT [[Target]]")
    assert is_redirect_wikitext("   #redirect [[Target]]")
    assert not is_redirect_wikitext("Regular content")
