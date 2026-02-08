from __future__ import annotations

import logging
import time

from .config import load_config
from .logging import configure_logging


log = logging.getLogger("bot")


def main() -> None:
    configure_logging()
    cfg = load_config()

    log.info("starting bot poll loop")
    log.info("mw_api_url=%s", cfg.mw_api_url)
    log.info("source_lang=%s target_langs=%s", cfg.source_lang, ",".join(cfg.target_langs))

    # MVP scaffold: no-op poll loop until core modules are implemented.
    while True:
        log.info("tick")
        time.sleep(cfg.poll_interval_seconds)


if __name__ == "__main__":
    main()
