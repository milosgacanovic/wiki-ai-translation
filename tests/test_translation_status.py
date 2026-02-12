from bot.translate_page import (
    _parse_status_template,
    _upsert_status_template,
    _remove_disclaimer_tables,
)


def test_parse_status_template():
    text = "{{Translation_status|status=reviewed|source_rev_at_translation=123|reviewed_by=Admin}}\nBody"
    params = _parse_status_template(text)
    assert params["status"] == "reviewed"
    assert params["source_rev_at_translation"] == "123"
    assert params["reviewed_by"] == "Admin"


def test_upsert_status_template_replaces_existing():
    text = "{{Translation_status|status=reviewed|source_rev_at_translation=10}}\nLine"
    out = _upsert_status_template(
        text,
        status="outdated",
        source_rev_at_translation="10",
        reviewed_by="Admin",
        outdated_source_rev="11",
    )
    assert out.startswith(
        "{{Translation_status|status=outdated|source_rev_at_translation=10|reviewed_by=Admin|outdated_source_rev=11}}"
    )
    assert "status=reviewed" not in out


def test_remove_disclaimer_tables():
    text = (
        "{| class=\"translation-disclaimer\"\n|-\n| old disclaimer\n|}\n\n"
        "Body"
    )
    assert _remove_disclaimer_tables(text) == "Body"
