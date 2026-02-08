from bot.mediawiki import MediaWikiClient, parse_translation_unit_title


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.requests = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.requests.append(("GET", url, params))
        return FakeResponse(self.responses.pop(0))

    def post(self, url, data=None, headers=None, timeout=None):
        self.requests.append(("POST", url, data))
        return FakeResponse(self.responses.pop(0))


def test_login_sets_csrf_token():
    responses = [
        {"query": {"tokens": {"logintoken": "LOGIN"}}},
        {"login": {"result": "Success"}},
        {"query": {"tokens": {"csrftoken": "CSRF"}}},
    ]
    session = FakeSession(responses)
    client = MediaWikiClient("https://example.org/api.php", "ua", session)

    client.login("user", "pass")

    assert client.csrf_token == "CSRF"
    assert session.requests[0][0] == "GET"
    assert session.requests[1][0] == "POST"
    assert session.requests[2][0] == "GET"


def test_parse_translation_unit_title():
    assert parse_translation_unit_title("Translations:Foo/1/en", "en") == "Foo"
    assert parse_translation_unit_title("Translations:Foo/2/it", "en") is None
    assert parse_translation_unit_title("Translations:Foo/abc/en", "en") is None
    assert parse_translation_unit_title("Translations:Foo/1/en", "it") is None
    assert parse_translation_unit_title("Talk:Foo", "en") is None


def test_request_retries_on_ratelimit():
    responses = [
        {"error": {"code": "ratelimited", "info": "rate limit"}},
        {"query": {"tokens": {"logintoken": "LOGIN"}}},
    ]
    session = FakeSession(responses)
    client = MediaWikiClient("https://example.org/api.php", "ua", session)

    token = client.get_login_token()

    assert token == "LOGIN"
    assert len(session.requests) == 2
