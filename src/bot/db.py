from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg

log = logging.getLogger("bot.db")


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn)


@contextmanager
def get_conn(dsn: str) -> Iterator[psycopg.Connection]:
    conn = connect(dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(dsn: str) -> None:
    # no-op placeholder; migrations should be applied externally
    log.info("db schema assumed ready")


def fetch_termbase(conn: psycopg.Connection, lang: str) -> list[dict[str, str | bool | None]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT term, preferred, forbidden, notes
            FROM termbase
            WHERE lang = %s
            ORDER BY term ASC
            """,
            (lang,),
        )
        rows = cur.fetchall()
    return [
        {
            "term": row[0],
            "preferred": row[1],
            "forbidden": row[2],
            "notes": row[3],
        }
        for row in rows
    ]


def fetch_segment_checksums(
    conn: psycopg.Connection, page_title: str
) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT segment_key, checksum
            FROM segments
            WHERE page_title = %s
            """,
            (page_title,),
        )
        rows = cur.fetchall()
    return {row[0]: row[1] for row in rows}


def upsert_segment(
    conn: psycopg.Connection,
    page_title: str,
    segment_key: str,
    source_text: str,
    checksum: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO segments (page_title, segment_key, source_text, checksum)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (page_title, segment_key)
            DO UPDATE SET source_text = EXCLUDED.source_text, checksum = EXCLUDED.checksum
            """,
            (page_title, segment_key, source_text, checksum),
        )


def fetch_cached_translation(
    conn: psycopg.Connection, segment_key: str, lang: str
) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT text
            FROM translations
            WHERE segment_key = %s AND lang = %s
            """,
            (segment_key, lang),
        )
        row = cur.fetchone()
    if not row:
        return None
    return row[0]


def upsert_translation(
    conn: psycopg.Connection,
    segment_key: str,
    lang: str,
    text: str,
    engine: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO translations (segment_key, lang, text, engine)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (segment_key, lang)
            DO UPDATE SET text = EXCLUDED.text, engine = EXCLUDED.engine
            """,
            (segment_key, lang, text, engine),
        )
