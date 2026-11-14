"""Compact Hán/Nôm character -> Quốc ngữ readings index.

Built once from the official Entry/v1 dictionary drop (``entries/*.jsonl``,
~3 GB) and cached as a small JSON file. Only reading systems that are
Quốc ngữ evidence count (``qn``, ``hv``, ``nom``; a missing system means
``qn``) - pinyin/jyutping/on/kun are never used to match a QN syllable.

Two kinds of evidence are kept apart:

- ``char``: the entry's head is the character itself (``kind: char``);
- ``word``: a multi-character head or ``forms`` spelling whose reading has
  exactly as many syllables as characters, so each character gets the
  syllable at its position (e.g. 德主𡗶 "Đức Chúa Trời" -> 𡗶 "trời").
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

QN_SYSTEMS = {"qn", "hv", "nom"}
_VS_RE = re.compile("[︀-️\U000e0100-\U000e01ef]")
_SYLLABLE_RE = re.compile(r"[^\W\d_]+")
_SPLIT_RE = re.compile(r"[,;/|]")
CACHE_VERSION = 2
# Sources whose ``kind=word script=qn`` records carry their Nom spelling in
# ``forms`` and the Quốc ngữ head itself as the reading, with
# ``readings: null`` (hannom-rcv.org chuẩn bảng). For these one validated
# positional spread is applied: the qn head is used as the reading value and
# distributed over the form's characters (syllables == characters required,
# via ``_spread_word``). No other source is spread this way.
SPREAD_QN_HEAD_SOURCES = frozenset({"hannom_rcv.jsonl"})


def is_ideograph(ch: str) -> bool:
    """CJK ideograph, private-use code (Kim Hán Nôm PUA) or the 〓 placeholder."""
    if len(ch) != 1:
        return False
    code = ord(ch)
    if ch == "〓":
        return True
    if 0xE000 <= code <= 0xF8FF or 0xF0000 <= code <= 0x10FFFD:
        return True
    from ..clean import is_nom_char

    return is_nom_char(ch)


def norm_reading(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip()).casefold()


def split_reading_tokens(value: str) -> list[str]:
    """Split a reading string into per-part tokens.

    Splits on the separators found in the official drop (comma, semicolon,
    slash, pipe), normalises NFC/casefold and drops empty fragments — the
    same splitting used for the cache build (verify-G M3). Bare ``/``
    fragments yield no token, never a glued one.
    """
    out: list[str] = []
    for part in _SPLIT_RE.split(value):
        part = norm_reading(part)
        if part:
            out.append(part)
    return out


def syllable_tokens(value: str) -> list[str]:
    """Extract every plain QN syllable from a reading string.

    Used by the JSONL-adapter ``LookupResult`` path so matchers see the
    same syllable granularity as the compact cache: NFC/casefold, then
    collect runs of QN syllable characters. Slash-glued (``bạ/bộ``) and
    comma-joined (``nhật, nhựt``) values decompose into exactly the
    syllables a Quốc ngữ token can match (verify-G M3).
    """
    return _SYLLABLE_RE.findall(unicodedata.normalize("NFC", value).casefold())


def _qn_readings(record: dict) -> list[str]:
    out: list[str] = []
    for item in record.get("readings") or []:
        if isinstance(item, dict):
            value = item.get("value")
            system = str(item.get("system") or "qn").strip().casefold() or "qn"
        else:
            value, system = item, "qn"
        if system not in QN_SYSTEMS or not isinstance(value, str):
            continue
        out.extend(split_reading_tokens(value))
    return out


def _qn_head_as_reading(record: dict) -> str | None:
    """Treat a qn word head itself as the phonetic reading (chuẩn bảng).

    Only for ``SPREAD_QN_HEAD_SOURCES`` records with ``readings`` missing:
    the head is a Quốc ngữ word (``"ái ngại"``) whose syllables align
    positionally with the Nom form (``愛懝``). Returns the normalised
    reading string, or None when the record is not a spread candidate
    (wrong kind/script, single syllable or no qn glyphs at all).
    """
    if record.get("unencoded"):
        return None
    if str(record.get("kind", "")).strip().casefold() != "word":
        return None
    script = str(record.get("script", "qn")).strip().casefold()
    if script not in {"qn", "other"}:
        return None
    head = unicodedata.normalize("NFC", str(record.get("head") or "")).strip()
    syllables = _SYLLABLE_RE.findall(norm_reading(head))
    if len(syllables) < 2:
        return None
    return " ".join(syllables)


def _add(table: dict[str, set[str]], char: str, reading: str) -> None:
    table.setdefault(char, set()).add(reading)


def _map_pua_str(text: str) -> str:
    """Re-encode Kim Hán Nôm PUA code points to their standard Nôm glyph.

    Only active when a human operator enabled the PUA map (default off).
    Unmapped PUA code points pass through unchanged.
    """
    from ..pua_map import is_enabled, mapped_pua

    if not is_enabled():
        return text
    return "".join(mapped_pua(ch) or ch for ch in text)


def _spread_word(table: dict[str, set[str]], text: str, reading: str) -> None:
    chars = [c for c in _VS_RE.sub("", _map_pua_str(unicodedata.normalize("NFC", text))) if not c.isspace()]
    if len(chars) < 2 or not all(is_ideograph(c) for c in chars):
        return
    syllables = _SYLLABLE_RE.findall(reading)
    if len(syllables) != len(chars):
        return
    for char, syllable in zip(chars, syllables):
        _add(table, char, syllable)


def build_readings(
    entries_dir: Path,
    sources: Iterable[Path] | None = None,
    *,
    skip_sources: Iterable[str] | None = None,
) -> dict:
    """Build the compact readings index from the Entry/v1 drop.

    ``sources=None`` discovers ``entries_dir/*.jsonl``; names listed in
    ``skip_sources`` are dropped (the official drop ships the full catusf
    dump — 3,541,369 records with no ``readings`` key at all — which costs
    a full parse per rebuild and contributes zero entries; see verify-G H3).
    Callers passing ``sources`` explicitly control the list themselves.
    """
    char_table: dict[str, set[str]] = {}
    word_table: dict[str, set[str]] = {}
    if sources is not None:
        files = sorted(sources)
    else:
        skip = {str(name) for name in (skip_sources or [])}
        files = [path for path in sorted(Path(entries_dir).glob("*.jsonl")) if path.name not in skip]
    used: list[str] = []
    for path in files:
        used.append(path.name)
        path_name = path.name.lower()
        is_spread_source = path_name in SPREAD_QN_HEAD_SOURCES
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                # Regexes deliberately broad: the prefilter must never reject
                # a record that the structured parse below would accept.
                if '"readings"' not in line and not is_spread_source:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("unencoded"):
                    continue
                readings = _qn_readings(record)
                if not readings and is_spread_source:
                    # chuẩn bảng: readings=null; the qn head IS the reading.
                    head_reading = _qn_head_as_reading(record)
                    if head_reading is not None:
                        readings = [head_reading]
                if not readings:
                    continue
                head = _map_pua_str(_VS_RE.sub("", unicodedata.normalize("NFC", str(record.get("head") or ""))))
                if record.get("kind") == "char" and len(head) == 1 and is_ideograph(head):
                    for reading in readings:
                        for syllable in _SYLLABLE_RE.findall(reading) or [reading]:
                            _add(char_table, head, syllable)
                    continue
                for reading in readings:
                    _spread_word(word_table, head, reading)
                    for form in record.get("forms") or []:
                        text = form.get("text") if isinstance(form, dict) else form
                        if isinstance(text, str):
                            _spread_word(word_table, text, reading)
    return {
        "version": CACHE_VERSION,
        "sources": used,
        "char": {c: sorted(v) for c, v in char_table.items()},
        "word": {c: sorted(v - char_table.get(c, set())) for c, v in word_table.items() if v - char_table.get(c, set())},
    }


class Readings:
    """Lookup of dictionary readings for one character."""

    def __init__(self, data: dict):
        self.char = {c: frozenset(v) for c, v in data.get("char", {}).items()}
        self.word = {c: frozenset(v) for c, v in data.get("word", {}).items()}
        self.sources = list(data.get("sources", []))

    def of(self, ch: str) -> frozenset[str]:
        return self.char.get(ch, frozenset()) | self.word.get(ch, frozenset())

    def known(self, ch: str) -> bool:
        return ch in self.char or ch in self.word

    def __len__(self) -> int:
        return len(set(self.char) | set(self.word))


def load_readings(
    entries_dir: Path,
    cache_path: Path,
    rebuild: bool = False,
    *,
    skip_sources: Iterable[str] | None = None,
) -> Readings:
    """Load the cached index, building it from ``entries_dir`` when missing."""
    cache_path = Path(cache_path)
    if cache_path.exists() and not rebuild:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data.get("version") == CACHE_VERSION:
            return Readings(data)
    entries_dir = Path(entries_dir)
    if not entries_dir.exists():
        return Readings({})
    data = build_readings(entries_dir, skip_sources=skip_sources)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache_path)
    return Readings(data)
