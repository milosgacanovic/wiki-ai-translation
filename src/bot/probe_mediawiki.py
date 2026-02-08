from __future__ import annotations

import json
import logging

from .config import load_config
from .logging import configure_logging
from .mediawiki import MediaWikiClient


def main() -> None:
    configure_logging()
    cfg = load_config()

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    general = client.site_info()
    logging.getLogger("probe").info(
        "connected wiki: %s (version=%s)", general.get("sitename"), general.get("generator")
    )

    print(json.dumps(general, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
