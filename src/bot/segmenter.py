from __future__ import annotations

import re
from dataclasses import dataclass


SEGMENT_RE = re.compile(r"<!--T:(\d+)-->")
TRANSLATE_TAG_RE = re.compile(r"</?translate>")


@dataclass(frozen=True)
class Segment:
    key: str
    text: str


def split_translate_units(wikitext: str) -> list[Segment]:
    matches = list(SEGMENT_RE.finditer(wikitext))
    segments: list[Segment] = []
    if not matches:
        return segments

    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(wikitext)
        raw = wikitext[start:end]
        cleaned = TRANSLATE_TAG_RE.sub("", raw).strip()
        if cleaned:
            segments.append(Segment(key=match.group(1), text=cleaned))
    return segments
