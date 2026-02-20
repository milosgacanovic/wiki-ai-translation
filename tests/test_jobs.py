from bot.jobs import next_jobs


class _FakeCursor:
    def __init__(self):
        self.sql = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()

    def cursor(self):
        return self.cur


def test_next_jobs_uses_skip_locked_query():
    conn = _FakeConn()
    out = next_jobs(conn, limit=3)
    assert out == []
    assert "FOR UPDATE SKIP LOCKED" in " ".join(conn.cur.sql.split()).upper()
    assert conn.cur.params == (3,)
