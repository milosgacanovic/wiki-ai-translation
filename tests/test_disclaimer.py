from bot.translate_page import _insert_disclaimer


def test_insert_disclaimer_with_anchor():
    anchors = {
        "Welcome_to_the_DanceResource_Wiki": {
            "sr": "Anchor line"
        }
    }
    text = "Intro\nAnchor line\nAfter"
    out = _insert_disclaimer(
        text, "DISCLAIMER", "Welcome_to_the_DanceResource_Wiki", "sr", anchors, None
    )
    assert "Anchor line\n\nDISCLAIMER\n\nAfter" in out


def test_insert_disclaimer_fallback():
    out = _insert_disclaimer("Body", "DISCLAIMER", "Other", "sr", None, None)
    assert out.startswith("DISCLAIMER\n\nBody")


def test_insert_disclaimer_marker():
    text = "Intro\n<!--BOT_DISCLAIMER-->\nAfter"
    out = _insert_disclaimer(
        text, "DISCLAIMER", "<!--BOT_DISCLAIMER-->", "Any", "sr", None
    )
    assert "DISCLAIMER" in out
    assert "<!--BOT_DISCLAIMER-->" not in out


def test_disclaimer_marker_in_later_segment():
    segments = {
        "1": "First segment",
        "2": "Second\n<!--BOT_DISCLAIMER-->\nTail",
    }
    out = {}
    inserted = False
    for key in ["1", "2"]:
        if "<!--BOT_DISCLAIMER-->" in segments[key] and not inserted:
            out[key] = _insert_disclaimer(
                segments[key],
                "DISCLAIMER",
                "<!--BOT_DISCLAIMER-->",
                "Any",
                "sr",
                None,
            )
            inserted = True
        else:
            out[key] = segments[key]
    assert "DISCLAIMER" in out["2"]
