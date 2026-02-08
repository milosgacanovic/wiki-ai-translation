from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from google.cloud import translate

from .base import TranslationResult


@dataclass
class GoogleTranslateV3:
    project_id: str
    location: str = "global"
    credentials_path: str | None = None

    name: str = "google_v3"

    def _client(self) -> translate.TranslationServiceClient:
        if self.credentials_path:
            return translate.TranslationServiceClient.from_service_account_file(
                self.credentials_path
            )
        return translate.TranslationServiceClient()

    def translate(
        self, texts: list[str], source_lang: str, target_lang: str
    ) -> list[TranslationResult]:
        if not texts:
            return []
        if not self.project_id:
            raise RuntimeError("GCP project_id is required for Google Translate v3")

        client = self._client()
        parent = f"projects/{self.project_id}/locations/{self.location}"

        response = client.translate_text(
            request={
                "parent": parent,
                "contents": list(texts),
                "mime_type": "text/plain",
                "source_language_code": source_lang,
                "target_language_code": target_lang,
            }
        )

        return [
            TranslationResult(text=t.translated_text, engine=self.name)
            for t in response.translations
        ]


def translate_batch(
    engine: GoogleTranslateV3,
    texts: Iterable[str],
    source_lang: str,
    target_lang: str,
) -> list[TranslationResult]:
    return engine.translate(list(texts), source_lang, target_lang)
