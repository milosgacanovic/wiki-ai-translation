from types import SimpleNamespace

from bot import sync_translation_status


class _FakeClient:
    def __init__(self):
        self.revision_requests: list[str] = []

    def login(self, username: str, password: str) -> None:
        _ = username, password

    def iter_main_namespace_titles(self):
        return ["Source", "Source/fr"]

    def get_page_revision_id(self, title: str):
        self.revision_requests.append(title)
        if title == "Source":
            return 100, "Source"
        raise RuntimeError("missing")


def test_sync_translation_status_skips_translation_subpages(monkeypatch):
    fake = _FakeClient()
    cfg = SimpleNamespace(
        mw_api_url="https://example.org/api.php",
        mw_user_agent="ua",
        mw_username="bot",
        mw_password="secret",
        target_langs=("sr", "it"),
        source_lang="en",
    )

    monkeypatch.setattr(sync_translation_status, "configure_logging", lambda: None)
    monkeypatch.setattr(sync_translation_status, "load_config", lambda: cfg)
    monkeypatch.setattr(sync_translation_status, "MediaWikiClient", lambda *args, **kwargs: fake)
    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args",
        lambda self: SimpleNamespace(
            only_title=None,
            langs=None,
            approve=False,
            dry_run=True,
        ),
    )

    sync_translation_status.main()

    assert "Source/fr" not in fake.revision_requests
