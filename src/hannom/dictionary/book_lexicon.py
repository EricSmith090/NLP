"""Per-book learned character-to-syllable evidence.

A phonetic translation is evidence, not proof. This lexicon records only
readings that can be tied to a dictionary reading or to an unambiguous
one-character row. It never invents a reading for an unknown character.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from ..clean import is_nom_char

QN_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def qn_syllables(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).casefold()
    return [m.group(0) for m in QN_TOKEN_RE.finditer(text)]


def _reading_forms(reading: str) -> set[str]:
    value = reading.strip().casefold()
    forms = {value, strip_diacritics(value)}
    forms.update(x for x in re.split(r"[\s,;/]+", value) if x)
    forms.update(strip_diacritics(x) for x in list(forms))
    return {x for x in forms if x}


class BookLexicon:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, dict[str, int]] = {}
        self.meta: dict[str, Any] = {}
        if self.path.exists():
            self.load()

    def available(self) -> bool:
        return bool(self.data) or self.path.exists()

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.data = {
            str(char): {str(k): int(v) for k, v in readings.items()}
            for char, readings in (raw.get("readings", {}) or {}).items()
        }
        self.meta = raw.get("meta", {}) or {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "meta": self.meta,
            "readings": {
                char: dict(sorted(readings.items(), key=lambda kv: (-kv[1], kv[0])))
                for char, readings in sorted(self.data.items())
            },
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, char: str, syllable: str, count: int = 1) -> None:
        if len(char) != 1 or not is_nom_char(char):
            return
        syllable = syllable.strip().casefold()
        if not syllable:
            return
        bucket = self.data.setdefault(char, {})
        bucket[syllable] = bucket.get(syllable, 0) + max(1, int(count))

    def readings(self, char: str) -> list[str]:
        return [
            reading
            for reading, _count in sorted(
                self.data.get(char, {}).items(), key=lambda kv: (-kv[1], kv[0])
            )
        ]

    def learn_from_rows(
        self,
        rows: Iterable[Any],
        dictionary: Any | None = None,
    ) -> dict[str, int]:
        """Learn conservative reading evidence from aligned rows.

        ``rows`` may be AlignmentRow objects or mappings with ch_txt/vi_txt.
        Without a dictionary reading, only an unambiguous one-character row
        is learned. This avoids mapping every Nôm character to every syllable
        of a whole sentence.
        """
        learned = 0
        for row in rows:
            if hasattr(row, "ch_txt"):
                ch_text = row.ch_txt
                vi_text = row.vi_txt
            else:
                ch_text = str(row.get("ch_txt", ""))
                vi_text = str(row.get("vi_txt", ""))
            chars = [ch for ch in ch_text if is_nom_char(ch)]
            syllables = qn_syllables(vi_text)
            if not chars or not syllables:
                continue
            syllable_set = set(syllables)
            syllable_flat = {strip_diacritics(s) for s in syllables}
            if len(chars) == 1 and len(syllables) == 1:
                self.add(chars[0], syllables[0])
                learned += 1
                continue
            if dictionary is None:
                continue
            for char in chars:
                lookup = dictionary.lookup(char)
                for reading in lookup.readings:
                    exact_hits = [
                        form
                        for form in _reading_forms(reading)
                        if form in syllable_set
                    ]
                    if exact_hits:
                        self.add(char, exact_hits[0])
                        learned += 1
                        break
        self.meta["learned_pairs"] = int(self.meta.get("learned_pairs", 0)) + learned
        return {"learned_pairs": learned, "characters": len(self.data)}
