from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    mw_api_url: str
    mw_username: str
    mw_password: str
    mw_user_agent: str

    pg_dsn: str

    poll_interval_seconds: int = 60
    max_retries: int = 5

    source_lang: str = "en"
    target_langs: tuple[str, ...] = ("sr", "it")

    mt_primary: str = "google"
    mt_fallback: str = "azure"

    gcp_project_id: str | None = None
    gcp_location: str = "global"
    gcp_credentials_path: str | None = None


def load_config() -> Config:
    def req(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"Missing required env var: {name}")
        return value

    target_langs = tuple(
        lang.strip() for lang in os.getenv("BOT_TARGET_LANGS", "sr,it").split(",") if lang.strip()
    )

    return Config(
        mw_api_url=req("MW_API_URL"),
        mw_username=req("MW_USERNAME"),
        mw_password=req("MW_PASSWORD"),
        mw_user_agent=os.getenv("MW_USER_AGENT", "DanceResourceTranslationBot/0.1"),
        pg_dsn=req("DATABASE_URL"),
        poll_interval_seconds=int(os.getenv("BOT_POLL_INTERVAL", "60")),
        max_retries=int(os.getenv("BOT_MAX_RETRIES", "5")),
        source_lang=os.getenv("BOT_SOURCE_LANG", "en"),
        target_langs=target_langs,
        mt_primary=os.getenv("BOT_MT_PRIMARY", "google"),
        mt_fallback=os.getenv("BOT_MT_FALLBACK", "azure"),
        gcp_project_id=os.getenv("GCP_PROJECT_ID"),
        gcp_location=os.getenv("GCP_LOCATION", "global"),
        gcp_credentials_path=os.getenv("GCP_CREDENTIALS_PATH")
        or os.getenv("GCP_CREDENTIALS_JSON"),
    )
