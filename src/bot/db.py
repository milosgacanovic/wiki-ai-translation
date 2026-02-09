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
