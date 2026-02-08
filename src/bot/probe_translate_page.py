from __future__ import annotations

import argparse
import json
import logging

from .config import load_config
from .logging import configure_logging
from .mediawiki import MediaWikiClient, MediaWikiError


def _guess_group_id(title: str) -> str:
    return f"page-{title}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True, help="Page title to probe")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    title = args.title

    wikitext, rev_id, norm_title = client.get_page_wikitext(title)
    logging.getLogger("probe").info(
        "page=%s norm_title=%s rev_id=%s bytes=%s", title, norm_title, rev_id, len(wikitext)
    )

    group_id = _guess_group_id(title)
    logging.getLogger("probe").info("trying message group id: %s", group_id)

    try:
        data = client._request(
            "GET",
            {
                "action": "query",
                "prop": "messagecollection",
                "mcgroup": group_id,
                "mclanguage": cfg.source_lang,
                "mclimit": "max",
            },
        )
        mc = data.get("query", {}).get("messagecollection")
        if mc is None:
            raise MediaWikiError(f"unexpected response: {data}")
    except MediaWikiError as exc:
        logging.getLogger("probe").error("messagecollection failed: %s", exc)
        logging.getLogger("probe").info("listing message groups to locate correct id")
        data = client._request(
            "GET", {"action": "query", "meta": "messagegroups", "mgprop": "id|label"}
        )
        groups = data.get("query", {}).get("messagegroups", [])
        matches = [g for g in groups if title in g.get("id", "") or title in g.get("label", "")]
        print(json.dumps({"matches": matches}, indent=2, sort_keys=True))
        raise SystemExit(2) from exc

    summary = {
        "group_id": group_id,
        "messages": len(mc.get("messages", [])),
        "source_lang": cfg.source_lang,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
