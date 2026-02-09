from bot.placeholders import protect_wikitext, restore_wikitext


def test_comment_placeholder_roundtrip():
    text = "Intro <!--BOT_DISCLAIMER--> Tail"
    result = protect_wikitext(text)
    assert "<!--BOT_DISCLAIMER-->" not in result.text
    restored = restore_wikitext(result.text, result.placeholders)
    assert restored == text
