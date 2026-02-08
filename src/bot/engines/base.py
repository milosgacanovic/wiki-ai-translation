from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranslationResult:
    text: str
    engine: str


class TranslationEngine(Protocol):
    name: str

    def translate(
        self, texts: list[str], source_lang: str, target_lang: str
    ) -> list[TranslationResult]:
        ...
