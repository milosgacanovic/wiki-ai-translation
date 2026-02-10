from bot.update_sidebar import SIDEBAR_BY_LANG, normalize_wikitext, update_sidebar


class FakeClient:
    def __init__(self, current: str | None = None):
        self.current = current or ""
        self.edits: list[tuple[str, str, str, bool]] = []

    def get_page_wikitext(self, title: str):
        return self.current, 123, title

    def edit(self, title: str, text: str, summary: str, bot: bool = True):
        self.edits.append((title, text, summary, bot))
        return 456


def test_normalize_wikitext_adds_trailing_newline():
    assert normalize_wikitext("* navigation\n") == "* navigation\n"
    assert normalize_wikitext("* navigation") == "* navigation\n"
    assert normalize_wikitext("* navigation\r\n") == "* navigation\n"


def test_update_sidebar_skips_when_unchanged():
    lang = "da"
    desired = normalize_wikitext(SIDEBAR_BY_LANG[lang])
    client = FakeClient(current=desired)

    changed = update_sidebar(lang, client, summary="Update", force=False)

    assert changed is False
    assert client.edits == []


def test_update_sidebar_edits_when_changed():
    lang = "da"
    client = FakeClient(current="* navigation\n")

    changed = update_sidebar(lang, client, summary="Update", force=False)

    assert changed is True
    assert client.edits
    title, text, summary, bot = client.edits[0]
    assert title == "MediaWiki:Sidebar/da"
    assert text == normalize_wikitext(SIDEBAR_BY_LANG[lang])
    assert summary == "Update"
    assert bot is True


def test_update_sidebar_force_edits():
    lang = "da"
    desired = normalize_wikitext(SIDEBAR_BY_LANG[lang])
    client = FakeClient(current=desired)

    changed = update_sidebar(lang, client, summary="Update", force=True)

    assert changed is True
    assert client.edits


def test_update_sidebar_unknown_lang():
    client = FakeClient()

    try:
        update_sidebar("xx", client, summary="Update", force=False)
    except KeyError as exc:
        assert "Unsupported language code" in str(exc)
    else:
        assert False, "Expected KeyError"
