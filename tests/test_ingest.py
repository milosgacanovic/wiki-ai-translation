from bot.ingest import (
    is_main_namespace,
    is_translation_wrapped,
    wrap_with_translate,
    should_skip_title,
    is_translation_subpage,
    is_redirect_wikitext,
    ingest_all,
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


class _PagedClient:
    def __init__(self):
        self.calls = []

    def all_pages_page(self, namespace=0, limit=200, apcontinue=None):
        self.calls.append((namespace, limit, apcontinue))
        return ["Page A"], "cursor-next"


def test_ingest_all_limit_updates_cursor_to_next_page(monkeypatch):
    client = _PagedClient()
    set_calls = []

    monkeypatch.setattr("bot.ingest.get_ingest_cursor", lambda conn, name="main": "cursor-start")
    monkeypatch.setattr(
        "bot.ingest.set_ingest_cursor",
        lambda conn, name="main", apcontinue=None: set_calls.append((name, apcontinue)),
    )
    monkeypatch.setattr(
        "bot.ingest.ingest_title",
        lambda cfg, client, conn, title, record=None, force=False, dry_run=False: None,
    )

    ingest_all(object(), client, object(), limit=1)

    assert client.calls == [(0, 1, "cursor-start")]
    assert set_calls == [("main", "cursor-next")]
