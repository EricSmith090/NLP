"""Dictionary adapter interface.

No adapter is required for the pipeline to run. A lookup result records
which sources were actually present and consulted so a missing source can
never be mistaken for evidence that a character is invalid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

from .readings import syllable_tokens


@dataclass(frozen=True)
class Sense:
    source: str
    definition: str = ""
    reading: str = ""
    gloss: str = ""
    raw: dict[str, Any] = field(default_factory=dict, compare=False)
    # Reading systems present on the source record (Entry/v1 `system`).
    # Only {qn, hv, nom} are usable as Quốc ngữ evidence per the
    # "Không suy đoán" rule; pinyin/jyutping/on/kun/hangul must not match QN.
    systems: tuple[str, ...] = ()
    # Entry kind ("char"/"word") and head for word-level lookups.
    kind: str = ""
    head: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "source": self.source,
            "definition": self.definition,
            "reading": self.reading,
            "gloss": self.gloss,
        }
        if self.systems:
            out["systems"] = list(self.systems)
        if self.kind:
            out["kind"] = self.kind
        if self.head:
            out["head"] = self.head
        return out


@dataclass
class LookupResult:
    char: str
    senses: list[Sense] = field(default_factory=list)
    sources_checked: list[str] = field(default_factory=list)
    sources_present: list[str] = field(default_factory=list)
    book_readings: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        # A structural-only sense (IDS/variant gloss with no reading or
        # definition, e.g. cjkvi_ids) is not phonetic evidence.
        has_evidence = any(s.reading or s.definition for s in self.senses)
        return bool(has_evidence or self.book_readings)

    @property
    def readings(self) -> list[str]:
        out: list[str] = []
        for reading in self.book_readings + [s.reading for s in self.senses]:
            for token in syllable_tokens(reading):
                if token and token not in out:
                    out.append(token)
        return out

    @property
    def definitions(self) -> list[str]:
        return [s.definition or s.gloss for s in self.senses if s.definition or s.gloss]

    def to_dict(self) -> dict[str, Any]:
        return {
            "char": self.char,
            "found": self.found,
            "senses": [s.to_dict() for s in self.senses],
            "sources_checked": list(self.sources_checked),
            "sources_present": list(self.sources_present),
            "book_readings": list(self.book_readings),
        }


@runtime_checkable
class DictionaryAdapter(Protocol):
    name: str

    def available(self) -> bool: ...

    def lookup(self, char: str) -> list[Sense]: ...


class DictionaryIndex:
    """Combine optional adapters and a per-book learned lexicon."""

    def __init__(
        self,
        adapters: Iterable[DictionaryAdapter] = (),
        book_lexicon: Any | None = None,
        *,
        configured_sources: Iterable[str] = (),
    ):
        self.adapters = list(adapters)
        self.book_lexicon = book_lexicon
        self.configured_sources = list(configured_sources)
        self._cache: dict[str, LookupResult] = {}

    @property
    def source_names(self) -> list[str]:
        names = [a.name for a in self.adapters if a.available()]
        if self.book_lexicon is not None:
            names.append("book_lexicon")
        return names

    def lookup(self, char: str, *, use_cache: bool = True) -> LookupResult:
        if len(char) != 1:
            raise ValueError("lookup expects one Unicode code point")
        if use_cache and char in self._cache:
            return self._cache[char]
        present: list[str] = []
        checked: list[str] = []
        senses: list[Sense] = []
        readings: list[str] = []
        for adapter in self.adapters:
            checked.append(adapter.name)
            if not adapter.available():
                continue
            present.append(adapter.name)
            senses.extend(adapter.lookup(char))
        if self.book_lexicon is not None:
            checked.append("book_lexicon")
            if self.book_lexicon.available():
                present.append("book_lexicon")
                readings.extend(self.book_lexicon.readings(char))
        result = LookupResult(
            char=char,
            senses=senses,
            sources_checked=checked or self.configured_sources,
            sources_present=present,
            book_readings=readings,
        )
        if use_cache:
            self._cache[char] = result
        return result

    def lookup_text(self, text: str) -> dict[str, LookupResult]:
        return {ch: self.lookup(ch) for ch in text if ch.strip()}

    def lookup_word(self, head: str) -> LookupResult:
        """Word-level lookup for multi-code-point Nom heads (kind=word)."""
        present: list[str] = []
        checked: list[str] = []
        senses: list[Sense] = []
        for adapter in self.adapters:
            checked.append(adapter.name)
            if not adapter.available():
                continue
            present.append(adapter.name)
            lookup_word = getattr(adapter, "lookup_word", None)
            if callable(lookup_word):
                senses.extend(lookup_word(head))
        result = LookupResult(
            char=head,
            senses=senses,
            sources_checked=checked or self.configured_sources,
            sources_present=present,
            book_readings=[],
        )
        return result

    def unknown_chars(self, text: str) -> list[str]:
        out: list[str] = []
        for ch in text:
            if ch == "[" or ch in "]MASK" or ch.isspace():
                continue
            from ..clean import is_nom_char

            if not is_nom_char(ch):
                continue
            if not self.lookup(ch).found and ch not in out:
                out.append(ch)
        return out


def build_dictionary_index(
    project_root: str | Path,
    dictionary_config: dict[str, Any],
    *,
    book_id: str | None = None,
) -> DictionaryIndex:
    """Construct every adapter that has a readable file on disk.

    Missing files are skipped silently but remain in ``configured_sources``
    so review output can say what was unavailable.
    """
    from .book_lexicon import BookLexicon
    from .jsonl import JsonlDictionary
    from .open_sources import (
        CcCedictAdapter,
        CjkviAdapter,
        MakeMeAHanziAdapter,
        UnihanAdapter,
    )

    root = Path(project_root)
    cfg = dictionary_config.get("dictionary", dictionary_config)
    adapters: list[DictionaryAdapter] = []
    configured: list[str] = []

    entries_dir = root / str(cfg.get("entries_dir", "dictionaries/entries"))
    for path in sorted(entries_dir.glob("*.jsonl")):
        configured.append(f"jsonl:{path.stem}")
        adapters.append(JsonlDictionary(path, name=f"jsonl:{path.stem}"))

    unihan_dir = root / str(cfg.get("unihan_dir", "dictionaries/unihan"))
    if unihan_dir.exists():
        for path in sorted(unihan_dir.glob("Unihan_*")):
            configured.append(f"unihan:{path.name}")
            adapters.append(UnihanAdapter(path, name=f"unihan:{path.name}"))

    cedict = root / str(cfg.get("cedict_path", "dictionaries/cc_cedict.txt"))
    configured.append("cc_cedict")
    if cedict.exists():
        adapters.append(CcCedictAdapter(cedict))

    makemeahanzi = root / str(cfg.get("makemeahanzi_path", "dictionaries/makemeahanzi.txt"))
    configured.append("makemeahanzi")
    if makemeahanzi.exists():
        adapters.append(MakeMeAHanziAdapter(makemeahanzi))

    ids = root / str(cfg.get("cjkvi_ids_path", "dictionaries/cjkvi_ids.txt"))
    variants = root / str(cfg.get("cjkvi_variants_path", "dictionaries/cjkvi_variants.txt"))
    configured.append("cjkvi")
    if ids.exists() or variants.exists():
        adapters.append(CjkviAdapter(ids if ids.exists() else None, variants if variants.exists() else None))

    lexicon = BookLexicon(
        root / str(cfg.get("book_lexicons_dir", "data/dictionary/book_lexicons"))
        / f"{book_id}.json"
    ) if book_id else None

    return DictionaryIndex(adapters, lexicon, configured_sources=configured)
