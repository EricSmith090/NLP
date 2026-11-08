"""Adapters for small, openly available offline dictionary files.

These are optional. The pipeline does not download or scrape any source;
the user may drop the official files into ``dictionaries/``. If a file is
absent, the adapter reports unavailable and review records that fact.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .index import Sense

UNIHAN_FIELDS = {
    "kVietnamese": "reading",
    "kDefinition": "definition",
    "kMandarin": "reading",
    "kHanyuPinyin": "reading",
    "kCantonese": "reading",
}


def _codepoint(char: str) -> str:
    return f"U+{ord(char):04X}"


class UnihanAdapter:
    def __init__(self, path: str | Path, name: str | None = None):
        self.path = Path(path)
        self.name = name or f"unihan:{self.path.name}"
        self._index: dict[str, list[Sense]] | None = None
        self.malformed = 0

    def available(self) -> bool:
        return self.path.exists()

    def _load(self) -> dict[str, list[Sense]]:
        if self._index is not None:
            return self._index
        index: dict[str, list[Sense]] = {}
        if not self.path.exists():
            self._index = index
            return index
        with self.path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    self.malformed += 1
                    continue
                cp, field, value = parts[0], parts[1], parts[2]
                if not cp.startswith("U+"):
                    self.malformed += 1
                    continue
                try:
                    char = chr(int(cp[2:], 16))
                except ValueError:
                    self.malformed += 1
                    continue
                if len(char) != 1:
                    continue
                key = UNIHAN_FIELDS.get(field)
                if key is None:
                    continue
                sense = Sense(
                    source=self.name,
                    definition=value if key == "definition" else "",
                    reading=value if key == "reading" else "",
                    gloss=value if key not in {"definition", "reading"} else "",
                    raw={"field": field, "value": value},
                )
                index.setdefault(char, []).append(sense)
        self._index = index
        return index

    def lookup(self, char: str) -> list[Sense]:
        return list(self._load().get(char, []))


class CcCedictAdapter:
    def __init__(self, path: str | Path, name: str = "cc_cedict"):
        self.path = Path(path)
        self.name = name
        self._index: dict[str, list[Sense]] | None = None
        self.malformed = 0
        self.line_re = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s*/(.*)/\s*$")

    def available(self) -> bool:
        return self.path.exists()

    def _load(self) -> dict[str, list[Sense]]:
        if self._index is not None:
            return self._index
        index: dict[str, list[Sense]] = {}
        if not self.path.exists():
            self._index = index
            return index
        with self.path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = self.line_re.match(line)
                if not match:
                    self.malformed += 1
                    continue
                traditional, simplified, pinyin, definitions = match.groups()
                gloss = "; ".join(x.strip() for x in definitions.split("/") if x.strip())
                for char in {traditional, simplified}:
                    if len(char) != 1:
                        continue
                    index.setdefault(char, []).append(
                        Sense(source=self.name, reading=pinyin, gloss=gloss, raw={"line": line})
                    )
        self._index = index
        return index

    def lookup(self, char: str) -> list[Sense]:
        return list(self._load().get(char, []))


class MakeMeAHanziAdapter:
    def __init__(self, path: str | Path, name: str = "makemeahanzi"):
        self.path = Path(path)
        self.name = name
        self._index: dict[str, list[Sense]] | None = None
        self.malformed = 0

    def available(self) -> bool:
        return self.path.exists()

    def _record(self, record: dict[str, Any]) -> tuple[str, Sense] | None:
        char = record.get("character")
        if not isinstance(char, str) or len(char) != 1:
            return None
        definition = record.get("definition", "")
        pinyin = record.get("pinyin", "")
        decomposition = record.get("decomposition", "")
        if isinstance(pinyin, list):
            pinyin = " ".join(str(x) for x in pinyin)
        if isinstance(definition, list):
            definition = "; ".join(str(x) for x in definition)
        raw = {k: record.get(k) for k in ("radical", "decomposition", "etymology")}
        return char, Sense(
            source=self.name,
            definition=str(definition or ""),
            reading=str(pinyin or ""),
            gloss=str(decomposition or ""),
            raw=raw,
        )

    def _load(self) -> dict[str, list[Sense]]:
        if self._index is not None:
            return self._index
        index: dict[str, list[Sense]] = {}
        if not self.path.exists():
            self._index = index
            return index
        text = self.path.read_text(encoding="utf-8", errors="replace")
        records: list[dict[str, Any]] = []
        try:
            whole = json.loads(text)
            if isinstance(whole, list):
                records = [x for x in whole if isinstance(x, dict)]
            elif isinstance(whole, dict):
                records = [whole]
        except json.JSONDecodeError:
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    self.malformed += 1
                    continue
                if isinstance(value, dict):
                    records.append(value)
        for record in records:
            parsed = self._record(record)
            if parsed is None:
                self.malformed += 1
                continue
            char, sense = parsed
            index.setdefault(char, []).append(sense)
        self._index = index
        return index

    def lookup(self, char: str) -> list[Sense]:
        return list(self._load().get(char, []))


class CjkviAdapter:
    """IDS decomposition and variant evidence from CJKVI text files."""

    def __init__(
        self,
        ids_path: str | Path | None = None,
        variants_path: str | Path | None = None,
        name: str = "cjkvi",
    ):
        self.ids_path = Path(ids_path) if ids_path else None
        self.variants_path = Path(variants_path) if variants_path else None
        self.name = name
        self._index: dict[str, list[Sense]] | None = None
        self.malformed = 0

    def available(self) -> bool:
        return bool(
            (self.ids_path and self.ids_path.exists())
            or (self.variants_path and self.variants_path.exists())
        )

    @staticmethod
    def _split_char(line: str) -> tuple[str, str] | None:
        if "\t" in line:
            left, right = line.split("\t", 1)
        elif " " in line:
            left, right = line.split(" ", 1)
        else:
            return None
        left = left.strip()
        if left.startswith("U+"):
            try:
                left = chr(int(left[2:], 16))
            except ValueError:
                return None
        if len(left) != 1:
            return None
        return left, right.strip()

    def _load(self) -> dict[str, list[Sense]]:
        if self._index is not None:
            return self._index
        index: dict[str, list[Sense]] = {}
        for path, kind in ((self.ids_path, "IDS"), (self.variants_path, "variants")):
            if not path or not path.exists():
                continue
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if not line.strip() or line.startswith("#"):
                        continue
                    parsed = self._split_char(line.rstrip("\n"))
                    if parsed is None:
                        self.malformed += 1
                        continue
                    char, value = parsed
                    index.setdefault(char, []).append(
                        Sense(source=self.name, gloss=f"{kind}: {value}", raw={"kind": kind, "value": value})
                    )
        self._index = index
        return index

    def lookup(self, char: str) -> list[Sense]:
        return list(self._load().get(char, []))
