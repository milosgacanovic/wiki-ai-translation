from bot.scheduler import poll_recent_changes


class _FakeClient:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def _request(self, method, params):
        self.calls.append((method, params))
        return self._responses[len(self.calls) - 1]


def test_poll_recent_changes_paginates():
    client = _FakeClient(
        [
            {
                "query": {
                    "recentchanges": [
                        {"title": "Page A", "revid": 10, "timestamp": "2026-02-14T10:00:00Z"},
                    ]
                },
                "continue": {"rccontinue": "20260214100100|11", "continue": "-||"},
            },
            {
                "query": {
                    "recentchanges": [
                        {"title": "Page B", "revid": 11, "timestamp": "2026-02-14T10:01:00Z"},
                    ]
                }
            },
        ]
    )

    changes, new_since = poll_recent_changes(client, "2026-02-14T09:59:00Z")

    assert [c.title for c in changes] == ["Page A", "Page B"]
    assert new_since == "2026-02-14T10:01:00Z"
    assert len(client.calls) == 2
    # second call must include rccontinue to fetch the next batch
    assert client.calls[1][1]["rccontinue"] == "20260214100100|11"


def test_poll_recent_changes_respects_limit():
    client = _FakeClient(
        [
            {
                "query": {
                    "recentchanges": [
                        {"title": "Page A", "revid": 10, "timestamp": "2026-02-14T10:00:00Z"},
                        {"title": "Page B", "revid": 11, "timestamp": "2026-02-14T10:01:00Z"},
                    ]
                },
                "continue": {"rccontinue": "20260214100100|12", "continue": "-||"},
            },
            {
                "query": {
                    "recentchanges": [
                        {"title": "Page C", "revid": 12, "timestamp": "2026-02-14T10:02:00Z"},
                    ]
                }
            },
        ]
    )

    changes, new_since = poll_recent_changes(client, "2026-02-14T09:59:00Z", limit=1)

    assert [c.title for c in changes] == ["Page A"]
    assert new_since == "2026-02-14T10:00:00Z"
    assert len(client.calls) == 1
