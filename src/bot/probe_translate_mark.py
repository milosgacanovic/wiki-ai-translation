from __future__ import annotations

import argparse
import json
import logging

from .config import load_config
from .logging import configure_logging
from .mediawiki import MediaWikiClient


def _parse_params(items: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"invalid param '{item}', expected key=value")
        key, value = item.split("=", 1)
        params[key] = value
    return params


def _apply_placeholders(params: dict[str, str], title: str, revision: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in params.items():
        out[key] = value.replace("{title}", title).replace("{revision}", str(revision))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--action", default=None)
    parser.add_argument("--revision", type=int, default=None)
    parser.add_argument("--param", action="append", default=[])
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    action = args.action or cfg.translate_mark_action
    if not action:
        raise SystemExit("translate mark action is required (--action or BOT_TRANSLATE_MARK_ACTION)")

    rev_id = args.revision
    if rev_id is None:
        rev_id, _ = client.get_page_revision_id(args.title)

    params = dict(cfg.translate_mark_params or {})
    params.update(_parse_params(args.param))
    params = _apply_placeholders(params, args.title, rev_id)
    if "title" not in params and "page" not in params and "target" not in params:
        params["page"] = args.title
    if "revision" not in params:
        params["revision"] = str(rev_id)
    params["token"] = client.csrf_token
    params["action"] = action

    logging.getLogger("probe").info("calling action=%s params=%s", action, params)
    data = client._request("POST", params)
    print(json.dumps(data, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
