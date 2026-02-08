from __future__ import annotations

import argparse
import json
import logging

from .config import load_config
from .engines.google_v3 import GoogleTranslateV3
from .logging import configure_logging
from .mediawiki import MediaWikiClient
from .segmenter import split_translate_units


def _resolve_project_id(cfg_project_id: str | None, credentials_path: str | None) -> str | None:
    if cfg_project_id:
        return cfg_project_id
    if not credentials_path:
        return None
    try:
        with open(credentials_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("project_id")
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--lang", default="sr")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    wikitext, rev_id, _ = client.get_page_wikitext(args.title)
    segments = split_translate_units(wikitext)

    logging.getLogger("probe").info(
        "page=%s rev_id=%s segments=%s", args.title, rev_id, len(segments)
    )

    project_id = _resolve_project_id(cfg.gcp_project_id, cfg.gcp_credentials_path)
    if not project_id:
        raise SystemExit("GCP project id is required (set GCP_PROJECT_ID or ensure in credentials)")

    engine = GoogleTranslateV3(
        project_id=project_id,
        location=cfg.gcp_location,
        credentials_path=cfg.gcp_credentials_path,
    )

    sample = segments[: args.limit]
    if not sample:
        raise SystemExit("no segments found")

    translated = engine.translate([s.text for s in sample], cfg.source_lang, args.lang)

    output = []
    for seg, tr in zip(sample, translated):
        output.append({"key": seg.key, "source": seg.text, "translation": tr.text})

    print(json.dumps({"title": args.title, "lang": args.lang, "items": output}, indent=2))


if __name__ == "__main__":
    main()
