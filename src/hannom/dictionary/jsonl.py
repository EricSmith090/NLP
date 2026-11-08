"""Adapter for the optional official ``entries/*.jsonl`` dictionary files.

The shared Entry/v1 schema (verified against the 2026-11-04 drop) is::

    {"id": ..., "source": ..., "kind": "char"|"word", "head": <NFC>,
     "script": "han"|"nom"|"qn"|...,
     "readings": [{"value": ..., "system": "qn"|"hv"|"nom"|"pinyin"|...}],
     "senses":   [{"text": ..., "lang": "vi"|"en"|"zh"|...}], ...}

The reader also accepts the common flat spelling variants and ignores
records it cannot interpret. Malformed lines are counted, not turned into
invented senses. Only ``kind == "char"`` records whose head is a single
code point and whose script is Han/Nôm are indexed, because the review
and red rules are per character.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from .index import Sense

CHAR_KEYS = ("char", "character", "han", "han_char", "nom", "word", "headword", "head")
READING_KEYS = ("reading", "readings", "pronunciation", "pinyin", "vietnamese", "am")
DEFINITION_KEYS = ("definition", "definitions", "meaning", "gloss", "vi", "definition_vi", "explanation")
INDEXED_SCRIPTS = {"han", "nom"}


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


def _readings(record: dict[str, Any]) -> str:
    readings = record.get("readings")
    if isinstance(readings, list):
        values: list[str] = []
        for item in readings:
            if isinstance(item, dict):
                value = item.get("value") or item.get("text") or item.get("pinyin")
                if value:
                    values.append(str(value))
            elif isinstance(item, str):
                values.append(item)
        return ", ".join(dict.fromkeys(values))
    return _flatten(_first(record, READING_KEYS))


def _definition(record: dict[str, Any]) -> str:
    senses = record.get("senses")
    if isinstance(senses, list):
        texts: list[str] = []
        for item in senses:
            if isinstance(item, dict):
                text = item.get("text") or item.get("def") or item.get("definition")
                if text:
                    texts.append(str(text))
        return "; ".join(texts)
    return _flatten(_first(record, DEFINITION_KEYS))


class JsonlDictionary:
    def __init__(self, path: str | Path, name: str | None = None):
        self.path = Path(path)
        self.name = name or f"jsonl:{self.path.stem}"
        self.malformed = 0
        self.skipped_non_char = 0
        self.skipped_script = 0
        self.skipped_multi = 0
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
                raw_char = unicodedata.normalize("NFC", raw_char)
                # Only index single code points because the review/red rules
                # are per character.
                if len(raw_char) != 1:
                    self.skipped_multi += 1
                    continue
                kind = record.get("kind")
                if isinstance(kind, str) and kind != "char":
                    self.skipped_non_char += 1
                    continue
                script = record.get("script")
                if isinstance(script, str) and script and script not in INDEXED_SCRIPTS:
                    self.skipped_script += 1
                    continue
                sense = Sense(
                    source=str(record.get("source", self.name)),
                    definition=_definition(record),
                    reading=_readings(record),
                    gloss=_flatten(record.get("gloss", "")),
                    raw=record,
                )
                index.setdefault(raw_char, []).append(sense)
        self._index = index
        return index

    def lookup(self, char: str) -> list[Sense]:
        return list(self._load().get(char, []))
