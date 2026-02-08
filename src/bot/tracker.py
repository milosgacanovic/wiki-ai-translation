from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import psycopg

log = logging.getLogger("bot.tracker")


@dataclass
class PageRecord:
    title: str
    source_lang: str
    last_source_rev: int | None


def upsert_page(conn: psycopg.Connection, title: str, source_lang: str, rev_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pages (title, source_lang, last_source_rev)
            VALUES (%s, %s, %s)
            ON CONFLICT (title)
            DO UPDATE SET last_source_rev = EXCLUDED.last_source_rev
            """,
            (title, source_lang, rev_id),
        )


def get_page(conn: psycopg.Connection, title: str) -> PageRecord | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT title, source_lang, last_source_rev FROM pages WHERE title = %s",
            (title,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return PageRecord(*row)
