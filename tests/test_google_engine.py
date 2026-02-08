import pytest

from bot.engines.google_v3 import GoogleTranslateV3


def test_google_engine_requires_project_id():
    engine = GoogleTranslateV3(project_id="")
    with pytest.raises(RuntimeError):
        engine.translate(["hello"], "en", "sr")
