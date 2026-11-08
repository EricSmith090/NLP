"""Adapter for the optional official ``entries/*.jsonl`` dictionary files.

The schema was never confirmed, so the reader accepts the common spelling
variants and ignores records it cannot interpret. Malformed lines are
counted, not turned into invented senses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .index import Sense

CHAR_KEYS = ("char", "character", "han", "han_char", "nom", "word", "headword")
READING_KEYS = ("reading", "readings", "pronunciation", "pinyin", "vietnamese", "am")
DEFINITION_KEYS = ("definition", "definitions", "meaning", "gloss", "vi", "definition_vi", "explanation")


def _first(record: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, "", [], {}):
            return record[key]
    return None


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "; ".join(_flatten(v) for v in value if v is not None)
    if isinstance(value, dict):
        return "; ".join(_flatten(v) for v in value.values())
    return str(value)


class JsonlDictionary:
    def __init__(self, path: str | Path, name: str | None = None):
        self.path = Path(path)
        self.name = name or f"jsonl:{self.path.stem}"
        self.malformed = 0
        self._index: dict[str, list[Sense]] | None = None

    def available(self) -> bool:
        return self.path.exists()

    def _load(self) -> dict[str, list[Sense]]:
        if self._index is not None:
            return self._index
        index: dict[str, list[Sense]] = {}
        if not self.path.exists():
            self._index = index
            return index
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    self.malformed += 1
                    continue
                if not isinstance(record, dict):
                    self.malformed += 1
                    continue
                raw_char = _first(record, CHAR_KEYS)
                if not isinstance(raw_char, str) or not raw_char:
                    self.malformed += 1
                    continue
                # Some files put a word/phrase in `word`; only index single
                # code points because the review/red rules are per character.
                if len(raw_char) != 1:
                    continue
                sense = Sense(
                    source=str(record.get("source", self.name)),
                    definition=_flatten(_first(record, DEFINITION_KEYS)),
                    reading=_flatten(_first(record, READING_KEYS)),
                    gloss=_flatten(record.get("gloss", "")),
                    raw=record,
                )
                index.setdefault(raw_char, []).append(sense)
        self._index = index
        return index

    def lookup(self, char: str) -> list[Sense]:
        return list(self._load().get(char, []))
