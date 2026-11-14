"""Adapter for the optional official ``entries/*.jsonl`` dictionary files.

The shared Entry/v1 schema (verified against the 2026-11-04 drop) is::

    {"id": ..., "source": ..., "kind": "char"|"word", "head": <NFC>,
     "script": "han"|"nom"|"qn"|...,
     "readings": [{"value": ..., "system": "qn"|"hv"|"nom"|"pinyin"|...}],
     "senses":   [{"text": ..., "lang": "vi"|"en"|"zh"|...}], ...}

The reader also accepts the common flat spelling variants and ignores
records it cannot interpret. Malformed lines are counted, not turned into
invented senses. Char records whose head is a single code point and whose
script is Han/Nôm are indexed for per-character lookups; word records and
``forms`` spellings (e.g. Nôm spellings on a QN head in dnqatv) are indexed
separately so they are not silently discarded.
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
# Entry/v1 allowed values (Mô tả dữ liệu v1, §Quy tắc kiểm tra).
ALLOWED_KINDS = {"char", "word"}
ALLOWED_SCRIPTS = {"han", "nom", "qn", "kana", "hangul", "latin", "other"}
ALLOWED_SYSTEMS = {"qn", "hv", "nom", "pinyin", "jyutping", "on", "kun", "hangul", "other"}
# Only these systems count as Quốc ngữ phonetic evidence ("Không suy đoán").
QN_SYSTEMS = {"qn", "hv", "nom"}
_VS_RANGES = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))


def _strip_vs(text: str) -> str:
    return "".join(ch for ch in text if not any(lo <= ord(ch) <= hi for lo, hi in _VS_RANGES))


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
    text, _systems = _readings_structured(record)
    return text


def _readings_structured(record: dict[str, Any]) -> tuple[str, list[str]]:
    """Join only QN-usable systems (qn/hv/nom); missing system ⇒ qn per spec."""
    readings = record.get("readings")
    if isinstance(readings, list):
        values: list[str] = []
        systems: list[str] = []
        for item in readings:
            if isinstance(item, dict):
                value = item.get("value") or item.get("text") or item.get("pinyin")
                if not value:
                    continue
                system = str(item.get("system") or "qn").strip().casefold() or "qn"
                if system not in QN_SYSTEMS:
                    continue
                values.append(str(value))
                if system not in systems:
                    systems.append(system)
            elif isinstance(item, str):
                values.append(item)
                if "qn" not in systems:
                    systems.append("qn")
        return ", ".join(dict.fromkeys(values)), systems
    flat = _flatten(_first(record, READING_KEYS))
    return flat, (["qn"] if flat else [])


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
        self.skipped_unencoded = 0
        self.duplicate_ids = 0
        self.invalid_freq = 0
        self.invalid_enum = 0
        self._seen_ids: set[str] = set()
        self._index: dict[str, list[Sense]] | None = None
        self._word_index: dict[str, list[Sense]] | None = None

    def available(self) -> bool:
        return self.path.exists()

    def _load(self) -> dict[str, list[Sense]]:
        index, _words = self._load_all()
        return index

    def _load_all(self) -> tuple[dict[str, list[Sense]], dict[str, list[Sense]]]:
        if self._index is not None:
            return self._index, self._word_index or {}
        index: dict[str, list[Sense]] = {}
        word_index: dict[str, list[Sense]] = {}
        if not self.path.exists():
            self._index = index
            self._word_index = word_index
            return index, word_index
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
                # Entry/v1 validation (counts, never raises).
                rec_id = record.get("id")
                if isinstance(rec_id, str) and rec_id:
                    if rec_id in self._seen_ids:
                        self.duplicate_ids += 1
                    else:
                        self._seen_ids.add(rec_id)
                freq = record.get("freq")
                if freq is not None and (not isinstance(freq, int) or freq < 0 or freq > 1000):
                    self.invalid_freq += 1
                kind = record.get("kind")
                script = record.get("script")
                if isinstance(kind, str) and kind not in ALLOWED_KINDS:
                    self.invalid_enum += 1
                if isinstance(script, str) and script not in ALLOWED_SCRIPTS:
                    self.invalid_enum += 1
                if isinstance(record.get("readings"), list):
                    for item in record["readings"]:
                        if isinstance(item, dict):
                            sys_ = item.get("system")
                            if isinstance(sys_, str) and sys_ not in ALLOWED_SYSTEMS:
                                self.invalid_enum += 1
                if record.get("unencoded") is True:
                    self.skipped_unencoded += 1
                    continue
                raw_char = _first(record, CHAR_KEYS)
                if not isinstance(raw_char, str) or not raw_char:
                    self.malformed += 1
                    continue
                head = unicodedata.normalize("NFC", raw_char)
                reading_text, systems = _readings_structured(record)
                sense = Sense(
                    source=str(record.get("source", self.name)),
                    definition=_definition(record),
                    reading=reading_text,
                    gloss=_flatten(record.get("gloss", "")),
                    raw=record,
                    systems=tuple(systems),
                    kind=str(kind) if isinstance(kind, str) else "",
                    head=head,
                )

                def _index_head(h: str) -> None:
                    base = _strip_vs(h)
                    if kind == "word" or len(base) != 1:
                        word_index.setdefault(h, []).append(sense)
                    else:
                        index.setdefault(h, []).append(sense)

                # Primary head: han/nom char → per-char index; word → word index.
                if isinstance(script, str) and script and script not in INDEXED_SCRIPTS and script != "qn":
                    # kana/hangul/latin/other heads are not Han/Nôm evidence.
                    self.skipped_script += 1
                    continue
                if script == "qn":
                    # QN head: do not index the QN spelling itself as a Nom char.
                    # Its Nom spelling lives in `forms` below.
                    pass
                elif kind == "char":
                    base = _strip_vs(head)
                    if len(base) != 1:
                        self.skipped_multi += 1
                        continue
                    index.setdefault(head, []).append(sense)
                elif kind == "word":
                    word_index.setdefault(head, []).append(sense)
                else:
                    # Unknown kind: treat single-code-point han/nom as char.
                    if script in INDEXED_SCRIPTS and len(_strip_vs(head)) == 1:
                        index.setdefault(head, []).append(sense)
                    else:
                        self.skipped_non_char += 1
                        continue
                # forms: alternate spellings. For a QN head these are Nom
                # spellings and round-trip to the per-char index.
                forms = record.get("forms")
                if isinstance(forms, list):
                    for form in forms:
                        if not isinstance(form, dict):
                            continue
                        ftext = form.get("text")
                        if not isinstance(ftext, str) or not ftext:
                            continue
                        ftext = unicodedata.normalize("NFC", ftext)
                        if len(_strip_vs(ftext)) == 1:
                            index.setdefault(ftext, []).append(sense)
                        else:
                            word_index.setdefault(ftext, []).append(sense)
        self._index = index
        self._word_index = word_index
        return index, word_index

    def lookup(self, char: str) -> list[Sense]:
        return list(self._load().get(char, []))

    def lookup_word(self, head: str) -> list[Sense]:
        _idx, words = self._load_all()
        # Single-code-point heads live in the char index; word heads here.
        if len(_strip_vs(head)) == 1:
            return list(self._load().get(head, []))
        return list(words.get(head, []))
