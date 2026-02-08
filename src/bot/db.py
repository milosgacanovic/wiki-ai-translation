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
