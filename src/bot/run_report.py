from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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
            (mode, target_langs, skip_prefixes, cfg.disclaimer_marker, "running"),
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


def write_report_file(conn, run_id: int, directory: str = "docs/runs") -> Path:
    summary = fetch_summary(conn, run_id)
    errors = fetch_errors(conn, run_id)

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

    lines.append("## Errors")
    if not errors:
        lines.append("- none")
    else:
        for err in errors:
            lines.append(
                f"- {err['kind']} {err['page_title']} {err['lang']}: {err['message']}"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def report_last_run(conn) -> str:
    run_id = last_run_id(conn)
    if run_id is None:
        return "No runs recorded."
    summary = fetch_summary(conn, run_id)
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
    }
    return json.dumps(payload, indent=2)
