from contextlib import contextmanager
from types import SimpleNamespace

import bot.runner as runner
from bot.jobs import Job


def test_process_queue_marks_job_error_on_system_exit(monkeypatch):
    cfg = SimpleNamespace(
        pg_dsn="postgresql://example",
        target_langs=("sr",),
        source_lang="en",
    )
    marks: dict[str, list[tuple[int, str]]] = {"done": [], "error": []}

    @contextmanager
    def _fake_get_conn(dsn):
        assert dsn == cfg.pg_dsn
        yield object()

    def _raise_system_exit():
        raise SystemExit("no segments found")

    monkeypatch.setattr(runner, "get_conn", _fake_get_conn)
    monkeypatch.setattr(
        runner,
        "next_jobs",
        lambda conn, limit=5: [Job(7, "translate_page", "Main Page", "sr", "queued", 0, 0)],
    )
    monkeypatch.setattr(runner, "translate_page_main", _raise_system_exit)
    monkeypatch.setattr(runner, "mark_job_done", lambda conn, job_id: marks["done"].append((job_id, "")))
    monkeypatch.setattr(
        runner,
        "mark_job_error",
        lambda conn, job_id, error: marks["error"].append((job_id, error)),
    )

    runner.process_queue(cfg, client=object())

    assert marks["done"] == []
    assert marks["error"] == [(7, "no segments found")]
