import os
import pytest

from bot.config import load_config


def test_load_config_requires_env(monkeypatch):
    monkeypatch.delenv("MW_API_URL", raising=False)
    monkeypatch.delenv("MW_USERNAME", raising=False)
    monkeypatch.delenv("MW_PASSWORD", raising=False)

    with pytest.raises(RuntimeError):
        load_config()


def test_load_config_reads_values(monkeypatch):
    monkeypatch.setenv("MW_API_URL", "https://example.org/api.php")
    monkeypatch.setenv("MW_USERNAME", "bot")
    monkeypatch.setenv("MW_PASSWORD", "secret")
    monkeypatch.setenv("BOT_TARGET_LANGS", "sr,it")
    monkeypatch.setenv("BOT_TRANSLATE_MARK_PARAMS", "{\"page\":\"{title}\"}")

    cfg = load_config()
    assert cfg.mw_api_url.endswith("api.php")
    assert cfg.target_langs == ("sr", "it")
    assert cfg.translate_mark_params == {"page": "{title}"}
    assert cfg.resource_row_preserve_fields == ("title", "url", "creator")
    assert cfg.resource_row_translate_fields == ("year", "format", "access", "tags", "notes")


def test_load_config_reads_resource_row_fields(monkeypatch):
    monkeypatch.setenv("MW_API_URL", "https://example.org/api.php")
    monkeypatch.setenv("MW_USERNAME", "bot")
    monkeypatch.setenv("MW_PASSWORD", "secret")
    monkeypatch.setenv("BOT_RESOURCE_ROW_PRESERVE_FIELDS", "title,url,doi")
    monkeypatch.setenv("BOT_RESOURCE_ROW_TRANSLATE_FIELDS", "creator,notes,tags")

    cfg = load_config()
    assert cfg.resource_row_preserve_fields == ("title", "url", "doi")
    assert cfg.resource_row_translate_fields == ("creator", "notes", "tags")
