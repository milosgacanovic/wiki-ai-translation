from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .config import Config
from .mediawiki import MediaWikiClient
from .db import get_conn
from .ingest import ingest_title

log = logging.getLogger("bot.scheduler")


@dataclass
class Change:
    title: str
    rev_id: int
    timestamp: str


def poll_recent_changes(client: MediaWikiClient, since: str | None) -> tuple[list[Change], str | None]:
    changes = []
    data = client._request(
        "GET",
        {
            "action": "query",
            "list": "recentchanges",
            "rcprop": "title|ids|timestamp",
            "rctype": "edit|new",
            "rcshow": "!bot",
            "rclimit": 50,
            "rcdir": "newer",
            **({"rcstart": since} if since else {}),
        },
    )
    for rc in data.get("query", {}).get("recentchanges", []):
        changes.append(Change(title=rc["title"], rev_id=int(rc["revid"]), timestamp=rc["timestamp"]))
    # use last timestamp as new cursor
    new_since = changes[-1].timestamp if changes else since
    return changes, new_since


def enqueue_for_change(cfg: Config, client: MediaWikiClient, conn, title: str, rev_id: int) -> None:
    ingest_title(cfg, client, conn, title)


def run_poll_loop(cfg: Config, client: MediaWikiClient) -> None:
    since = None
    while True:
        changes, since = poll_recent_changes(client, since)
        if changes:
            with get_conn(cfg.pg_dsn) as conn:
                for change in changes:
                    enqueue_for_change(cfg, client, conn, change.title, change.rev_id)
        time.sleep(cfg.poll_interval_seconds)
