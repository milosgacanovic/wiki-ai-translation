from __future__ import annotations

import psycopg


def get_ingest_cursor(conn: psycopg.Connection, name: str = "main") -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT apcontinue FROM ingest_state WHERE name = %s", (name,))
        row = cur.fetchone()
        if not row:
            return None
        return row[0]


def set_ingest_cursor(
    conn: psycopg.Connection, name: str = "main", apcontinue: str | None = None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingest_state (name, apcontinue, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (name)
            DO UPDATE SET apcontinue = EXCLUDED.apcontinue, updated_at = NOW()
            """,
            (name, apcontinue),
        )
