from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .config import Config


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    started_at: str
    finished_at: str | None
    status: str | None
    mode: str
    target_langs: str
    skip_title_prefixes: str
    disclaimer_marker: str | None
    totals: dict[str, int]


def start_run(conn, mode: str, cfg: Config) -> int:
    target_langs = ",".join(cfg.target_langs)
    skip_prefixes = ",".join(cfg.skip_title_prefixes)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO translation_runs (mode, target_langs, skip_title_prefixes, disclaimer_marker, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (mode, target_langs, skip_prefixes, None, "running"),
        )
        run_id = cur.fetchone()[0]
    return int(run_id)


def finish_run(conn, run_id: int, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE translation_runs
            SET finished_at = NOW(), status = %s
            WHERE id = %s
            """,
            (status, run_id),
        )


def log_item(
    conn,
    run_id: int,
    kind: str,
    status: str,
    page_title: str | None = None,
    lang: str | None = None,
    message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO run_items (run_id, kind, page_title, lang, status, message)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (run_id, kind, page_title, lang, status, message),
        )


def last_run_id(conn) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM translation_runs ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None
        return int(row[0])


def fetch_summary(conn, run_id: int) -> RunSummary:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, started_at, finished_at, status, mode, target_langs, skip_title_prefixes, disclaimer_marker
            FROM translation_runs
            WHERE id = %s
            """,
            (run_id,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"Run {run_id} not found")

    totals: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kind, status, COUNT(*)
            FROM run_items
            WHERE run_id = %s
            GROUP BY kind, status
            ORDER BY kind, status
            """,
            (run_id,),
        )
        for kind, status, count in cur.fetchall():
            totals[f"{kind}:{status}"] = int(count)

    started = row[1].astimezone(timezone.utc).isoformat()
    finished = row[2].astimezone(timezone.utc).isoformat() if row[2] else None

    return RunSummary(
        run_id=int(row[0]),
        started_at=started,
        finished_at=finished,
        status=row[3],
        mode=row[4],
        target_langs=row[5],
        skip_title_prefixes=row[6],
        disclaimer_marker=row[7],
        totals=totals,
    )


def fetch_errors(conn, run_id: int) -> list[dict[str, str | None]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kind, page_title, lang, status, message
            FROM run_items
            WHERE run_id = %s AND status = 'error'
            ORDER BY id ASC
            """,
            (run_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "kind": r[0],
            "page_title": r[1],
            "lang": r[2],
            "status": r[3],
            "message": r[4],
        }
        for r in rows
    ]


def fetch_items_by_status(conn, run_id: int) -> dict[str, list[dict[str, str | None]]]:
    items: dict[str, list[dict[str, str | None]]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kind, page_title, lang, status, message
            FROM run_items
            WHERE run_id = %s
            ORDER BY id ASC
            """,
            (run_id,),
        )
        rows = cur.fetchall()
    for kind, page_title, lang, status, message in rows:
        key = f"{kind}:{status}"
        items.setdefault(key, []).append(
            {
                "kind": kind,
                "page_title": page_title,
                "lang": lang,
                "status": status,
                "message": message,
            }
        )
    return items


def fetch_translate_ok_pairs(conn, run_id: int) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT page_title, lang
            FROM run_items
            WHERE run_id = %s AND kind = 'translate' AND status = 'ok'
              AND page_title IS NOT NULL AND lang IS NOT NULL
            ORDER BY page_title, lang
            """,
            (run_id,),
        )
        rows = cur.fetchall()
    return [(str(r[0]), str(r[1])) for r in rows]


def fetch_translated_source_pages(conn, run_id: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT page_title
            FROM run_items
            WHERE run_id = %s
              AND kind = 'translate'
              AND status = 'ok'
              AND page_title IS NOT NULL
            ORDER BY page_title
            """,
            (run_id,),
        )
        rows = cur.fetchall()
    return [str(r[0]) for r in rows]


def _wiki_base_url() -> str:
    api = os.getenv("MW_API_URL", "").strip()
    if api:
        if api.endswith("/api.php"):
            return api[: -len("/api.php")]
        if api.endswith("api.php"):
            return api[: -len("api.php")].rstrip("/")
    return "https://wiki.danceresource.org"


def _title_to_absolute_url(base_url: str, title: str) -> str:
    return f"{base_url}/{quote(title.replace(' ', '_'), safe='/_-()')}"


def fetch_stats(conn, run_id: int) -> dict[str, int]:
    stats: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(DISTINCT page_title)
            FROM run_items
            WHERE run_id = %s AND kind = 'translate' AND status = 'ok'
            """,
            (run_id,),
        )
        stats["pages_translated"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(DISTINCT page_title)
            FROM run_items
            WHERE run_id = %s AND kind = 'translate' AND status = 'error'
            """,
            (run_id,),
        )
        stats["pages_failed"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*)
            FROM run_items
            WHERE run_id = %s AND kind = 'translate' AND status = 'error'
            """,
            (run_id,),
        )
        stats["translate_errors"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*)
            FROM run_items
            WHERE run_id = %s AND kind = 'translate' AND status = 'warning'
            """,
            (run_id,),
        )
        stats["translate_warnings"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*)
            FROM run_items
            WHERE run_id = %s AND kind = 'ingest' AND status = 'ok'
            """,
            (run_id,),
        )
        stats["ingest_ok"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*)
            FROM run_items
            WHERE run_id = %s AND kind = 'ingest' AND status = 'skip'
            """,
            (run_id,),
        )
        stats["ingest_skipped"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*)
            FROM run_items
            WHERE run_id = %s AND kind = 'ingest' AND status = 'error'
            """,
            (run_id,),
        )
        stats["ingest_errors"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*)
            FROM run_items
            WHERE run_id = %s AND kind = 'ingest' AND status = 'ok'
              AND message ILIKE '%%queued%%'
            """,
            (run_id,),
        )
        stats["translations_requested"] = int(cur.fetchone()[0])
    return stats


def write_report_file(conn, run_id: int, directory: str = "docs/runs") -> Path:
    summary = fetch_summary(conn, run_id)
    errors = fetch_errors(conn, run_id)
    stats = fetch_stats(conn, run_id)
    items = fetch_items_by_status(conn, run_id)
    source_pages = fetch_translated_source_pages(conn, run_id)
    base_url = _wiki_base_url()

    Path(directory).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    path = Path(directory) / f"run-{summary.run_id}-{timestamp}.md"

    lines: list[str] = []
    lines.append(f"# Translation Run {summary.run_id}")
    lines.append("")
    lines.append(f"- started_at: {summary.started_at}")
    lines.append(f"- finished_at: {summary.finished_at}")
    lines.append(f"- status: {summary.status}")
    lines.append(f"- mode: {summary.mode}")
    lines.append(f"- target_langs: {summary.target_langs}")
    lines.append(f"- skip_title_prefixes: {summary.skip_title_prefixes}")
    lines.append(f"- disclaimer_marker: {summary.disclaimer_marker}")
    lines.append("")
    lines.append("## Totals")
    for key in sorted(summary.totals.keys()):
        lines.append(f"- {key}: {summary.totals[key]}")
    lines.append("")

    lines.append("## Statistics")
    for key in sorted(stats.keys()):
        lines.append(f"- {key}: {stats[key]}")
    lines.append("")

    lines.append("## Errors")
    if not errors:
        lines.append("- none")
    else:
        for err in errors:
            lines.append(
                f"- {err['kind']} {err['page_title']} {err['lang']}: {err['message']}"
            )
    lines.append("")

    lines.append("## Source Pages Translated (Absolute URLs)")
    if not source_pages:
        lines.append("- none")
    else:
        for title in source_pages:
            lines.append(f"- {_title_to_absolute_url(base_url, title)}")
    lines.append("")

    lines.append("## Items")
    for key in sorted(items.keys()):
        lines.append(f"- {key}: {len(items[key])}")
    lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def report_last_run(conn) -> str:
    run_id = last_run_id(conn)
    if run_id is None:
        return "No runs recorded."
    summary = fetch_summary(conn, run_id)
    stats = fetch_stats(conn, run_id)
    payload = {
        "run_id": summary.run_id,
        "started_at": summary.started_at,
        "finished_at": summary.finished_at,
        "status": summary.status,
        "mode": summary.mode,
        "target_langs": summary.target_langs,
        "skip_title_prefixes": summary.skip_title_prefixes,
        "disclaimer_marker": summary.disclaimer_marker,
        "totals": summary.totals,
        "stats": stats,
    }
    return json.dumps(payload, indent=2)
