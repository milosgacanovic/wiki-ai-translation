from bot.config import Config
from bot.ingest import ingest_title
from bot.translate_page import _fetch_unit_sources


class _UnitClient:
    def __init__(self):
        self.unit_titles: list[str] = []

    def get_page_wikitext(self, title: str):
        self.unit_titles.append(title)
        return "Segment text", 100, title


def test_fetch_unit_sources_uses_configured_source_lang():
    client = _UnitClient()
    segments = _fetch_unit_sources(client, "Main Page", ["1"], "fr")
    assert [s.key for s in segments] == ["1"]
    assert [s.text for s in segments] == ["Segment text"]
    assert client.unit_titles == ["Translations:Main Page/1/fr"]


class _IngestClientWithUnits:
    def __init__(self):
        self.list_source_langs: list[str] = []

    def get_page_revision_id(self, title: str):
        return 10, title

    def list_translation_unit_keys(self, norm_title: str, source_lang: str = "en"):
        _ = norm_title
        self.list_source_langs.append(source_lang)
        return ["1"]


class _IngestClientNoUnits:
    def __init__(self):
        self.list_source_langs: list[str] = []

    def get_page_revision_id(self, title: str):
        return 10, title

    def list_translation_unit_keys(self, norm_title: str, source_lang: str = "en"):
        _ = norm_title
        self.list_source_langs.append(source_lang)
        return []

    def get_page_wikitext(self, title: str):
        _ = title
        return "<translate>\nBody\n</translate>\n", 10, "Main Page"


def _cfg() -> Config:
    return Config(
        mw_api_url="https://example.org/api.php",
        mw_username="bot",
        mw_password="secret",
        mw_user_agent="ua",
        pg_dsn=None,
        source_lang="fr",
        target_langs=("sr",),
        auto_wrap=True,
    )


def test_ingest_title_uses_configured_source_lang_for_existing_units(monkeypatch):
    client = _IngestClientWithUnits()
    enqueued: list[str] = []
    monkeypatch.setattr("bot.ingest.get_page", lambda conn, title: None)
    monkeypatch.setattr(
        "bot.ingest.enqueue_translations",
        lambda cfg, conn, title: enqueued.append(title),
    )

    ingest_title(_cfg(), client, object(), "Main Page")

    assert client.list_source_langs == ["fr"]
    assert enqueued == ["Main Page"]


def test_ingest_title_uses_configured_source_lang_for_post_wrap_check(monkeypatch):
    client = _IngestClientNoUnits()
    monkeypatch.setattr("bot.ingest.get_page", lambda conn, title: None)

    ingest_title(_cfg(), client, object(), "Main Page", dry_run=True)

    assert client.list_source_langs == ["fr", "fr"]
