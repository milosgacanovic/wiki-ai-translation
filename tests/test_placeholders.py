from bot.placeholders import protect_wikitext, restore_wikitext


def test_comment_placeholder_roundtrip():
    text = "Intro <!--BOT_DISCLAIMER--> Tail"
    result = protect_wikitext(text)
    assert "<!--BOT_DISCLAIMER-->" not in result.text
    restored = restore_wikitext(result.text, result.placeholders)
    assert restored == text


def test_file_link_filename_preserved():
    text = "[[File:Arjan bouw.jpg|alt=Arjan Bouw|thumb|Photo: Luna Burger]]"
    result = protect_wikitext(text)
    restored = restore_wikitext(result.text, result.placeholders)
    assert restored == text
