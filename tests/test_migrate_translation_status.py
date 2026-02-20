from bot.migrate_translation_status import _iter_base_titles


class _FakeClient:
    def __init__(self):
        self.requested_source_lang: str | None = None

    def iter_translation_base_titles(self, source_lang: str = "en"):
        self.requested_source_lang = source_lang
        return ["Main Page"]


def test_iter_base_titles_uses_configured_source_lang():
    client = _FakeClient()
    out = _iter_base_titles(client, None, "fr")
    assert out == ["Main Page"]
    assert client.requested_source_lang == "fr"


def test_iter_base_titles_prefers_only_title():
    client = _FakeClient()
    out = _iter_base_titles(client, "Only Page", "fr")
    assert out == ["Only Page"]
    assert client.requested_source_lang is None
