from bot.ingest import is_main_namespace, is_translation_wrapped, wrap_with_translate


def test_is_main_namespace():
    assert is_main_namespace("Main_Page")
    assert not is_main_namespace("Category:Foo")


def test_wrap_translate_round_trip():
    text = "Hello world\n==Header==\nContent."
    wrapped = wrap_with_translate(text)
    assert is_translation_wrapped(wrapped)
    assert wrapped.startswith("<translate>")
    assert wrapped.endswith("</translate>\n")
