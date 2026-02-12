from __future__ import annotations

import os
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    mw_api_url: str
    mw_username: str
    mw_password: str
    mw_user_agent: str

    pg_dsn: str | None

    poll_interval_seconds: int = 60
    max_retries: int = 5
    auto_wrap: bool = True

    source_lang: str = "en"
    target_langs: tuple[str, ...] = ("sr", "it")

    mt_primary: str = "google"
    mt_fallback: str = "azure"

    gcp_project_id: str | None = None
    gcp_location: str = "global"
    gcp_credentials_path: str | None = None
    gcp_glossaries: dict[str, str] | None = None
    translate_mark_action: str | None = None
    translate_mark_params: dict[str, str] | None = None
    skip_title_prefixes: tuple[str, ...] = ()
    skip_translation_subpages: bool = True


def load_config() -> Config:
    def _load_mark_params() -> dict[str, str] | None:
        raw = os.getenv("BOT_TRANSLATE_MARK_PARAMS")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("BOT_TRANSLATE_MARK_PARAMS must be valid JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("BOT_TRANSLATE_MARK_PARAMS must be a JSON object")
        return {str(k): str(v) for k, v in data.items()}

    def _load_skip_prefixes() -> tuple[str, ...]:
        raw = os.getenv("BOT_SKIP_TITLE_PREFIXES", "")
        prefixes = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            prefixes.append(part.replace("_", " "))
        return tuple(prefixes)

    def _load_gcp_glossaries() -> dict[str, str] | None:
        raw = os.getenv("BOT_GCP_GLOSSARIES")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("BOT_GCP_GLOSSARIES must be valid JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("BOT_GCP_GLOSSARIES must be a JSON object")
        return {str(k): str(v) for k, v in data.items()}

    def req(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"Missing required env var: {name}")
        return value

    target_langs = tuple(
        lang.strip()
        for lang in os.getenv("BOT_TARGET_LANGS", "sr,it").split(",")
        if lang.strip()
    )

    cfg = Config(
        mw_api_url=req("MW_API_URL"),
        mw_username=req("MW_USERNAME"),
        mw_password=req("MW_PASSWORD"),
        mw_user_agent=os.getenv("MW_USER_AGENT", "DanceResourceTranslationBot/0.1"),
        pg_dsn=os.getenv("DATABASE_URL"),
        poll_interval_seconds=int(os.getenv("BOT_POLL_INTERVAL", "60")),
        max_retries=int(os.getenv("BOT_MAX_RETRIES", "5")),
        auto_wrap=os.getenv("BOT_AUTO_WRAP", "1") not in ("0", "false", "False"),
        source_lang=os.getenv("BOT_SOURCE_LANG", "en"),
        target_langs=target_langs,
        mt_primary=os.getenv("BOT_MT_PRIMARY", "google"),
        mt_fallback=os.getenv("BOT_MT_FALLBACK", "azure"),
        gcp_project_id=os.getenv("GCP_PROJECT_ID"),
        gcp_location=os.getenv("GCP_LOCATION", "global"),
        gcp_credentials_path=os.getenv("GCP_CREDENTIALS_PATH")
        or os.getenv("GCP_CREDENTIALS_JSON"),
        gcp_glossaries=_load_gcp_glossaries(),
        translate_mark_action=os.getenv("BOT_TRANSLATE_MARK_ACTION"),
        translate_mark_params=_load_mark_params(),
        skip_title_prefixes=_load_skip_prefixes(),
        skip_translation_subpages=os.getenv("BOT_SKIP_TRANSLATION_SUBPAGES", "1")
        not in ("0", "false", "False"),
    )
    return cfg
