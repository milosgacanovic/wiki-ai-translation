from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import psycopg

log = logging.getLogger("bot.jobs")


@dataclass
class Job:
    id: int
    type: str
    page_title: str
    lang: str
    status: str
    priority: int
    retries: int


def enqueue_job(
    conn: psycopg.Connection,
    job_type: str,
    page_title: str,
    lang: str,
    priority: int = 0,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM jobs
            WHERE status = 'queued' AND type = %s AND page_title = %s AND lang = %s
            LIMIT 1
            """,
            (job_type, page_title, lang),
        )
        if cur.fetchone():
            log.info(
                "skip enqueue duplicate queued job: type=%s page=%s lang=%s",
                job_type,
                page_title,
                lang,
            )
            return
        cur.execute(
            """
            INSERT INTO jobs (type, page_title, lang, status, priority)
            VALUES (%s, %s, %s, 'queued', %s)
            ON CONFLICT DO NOTHING
            """,
            (job_type, page_title, lang, priority),
        )


def next_jobs(conn: psycopg.Connection, limit: int = 10) -> list[Job]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, type, page_title, lang, status, priority, retries
            FROM jobs
            WHERE status = 'queued'
            ORDER BY priority DESC, id ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [Job(*row) for row in rows]


def count_jobs(
    conn: psycopg.Connection,
    status: str = "queued",
    job_type: str | None = None,
) -> int:
    with conn.cursor() as cur:
        if job_type:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM jobs
                WHERE status = %s AND type = %s
                """,
                (status, job_type),
            )
        else:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM jobs
                WHERE status = %s
                """,
                (status,),
            )
        return int(cur.fetchone()[0])


def delete_jobs_not_in_langs(
    conn: psycopg.Connection, langs: Iterable[str], job_type: str | None = None
) -> int:
    lang_list = list(langs)
    if not lang_list:
        return 0
    with conn.cursor() as cur:
        if job_type:
            cur.execute(
                """
                DELETE FROM jobs
                WHERE status = 'queued' AND type = %s AND lang <> ALL(%s)
                """,
                (job_type, lang_list),
            )
        else:
            cur.execute(
                """
                DELETE FROM jobs
                WHERE status = 'queued' AND lang <> ALL(%s)
                """,
                (lang_list,),
            )
        return int(cur.rowcount)


def delete_queued_jobs(conn: psycopg.Connection, job_type: str | None = None) -> int:
    with conn.cursor() as cur:
        if job_type:
            cur.execute(
                """
                DELETE FROM jobs
                WHERE status = 'queued' AND type = %s
                """,
                (job_type,),
            )
        else:
            cur.execute(
                """
                DELETE FROM jobs
                WHERE status = 'queued'
                """
            )
        return int(cur.rowcount)


def mark_job_done(conn: psycopg.Connection, job_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status = 'done', updated_at = NOW() WHERE id = %s",
            (job_id,),
        )


def mark_job_error(conn: psycopg.Connection, job_id: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'error', retries = retries + 1, error = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (error, job_id),
        )
