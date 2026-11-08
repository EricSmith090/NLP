"""Tests for the official Entry/v1 JSONL dictionary adapter.

Fixtures mirror the verified 2026-11-04 drop schema; no test touches the
real multi-GB dataset.
"""

from __future__ import annotations

import json
from pathlib import Path

from hannom.dictionary import build_dictionary_index
from hannom.dictionary.jsonl import JsonlDictionary


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    return path


def _entry(head: str, **overrides) -> dict:
    base = {
        "id": f"test:{head}",
        "source": "test",
        "kind": "char",
        "head": head,
        "script": "nom",
        "readings": [{"value": "nhất", "system": "qn"}],
        "senses": [{"text": "một; a number", "lang": "vi"}],
    }
    base.update(overrides)
    return base


def test_lookup_parses_entry_v1_schema(tmp_path: Path):
    path = _write(tmp_path / "test.jsonl", [_entry("一")])
    dictionary = JsonlDictionary(path)
    assert dictionary.available()
    senses = dictionary.lookup("一")
    assert len(senses) == 1
    assert "nhất" in senses[0].reading
    assert "một" in senses[0].definition
    assert senses[0].source == "test"


def test_word_records_and_multi_codepoint_heads_are_skipped(tmp_path: Path):
    path = _write(
        tmp_path / "test.jsonl",
        [_entry("一二", id="test:word"), _entry("經", kind="word", id="test:kind"), _entry("經")],
    )
    dictionary = JsonlDictionary(path)
    assert dictionary.lookup("經"), "char record must survive"
    assert dictionary.lookup("一") == []
    assert dictionary.skipped_non_char == 1
    assert dictionary.skipped_multi == 1


def test_non_han_nom_scripts_are_skipped(tmp_path: Path):
    path = _write(
        tmp_path / "test.jsonl",
        [_entry("あ", script="kana"), _entry("社", script="han")],
    )
    dictionary = JsonlDictionary(path)
    assert dictionary.lookup("あ") == []
    assert dictionary.lookup("社")
    assert dictionary.skipped_script == 1


def test_malformed_lines_are_counted_not_raised(tmp_path: Path):
    path = tmp_path / "test.jsonl"
    path.write_text(
        "not json\n" + json.dumps(_entry("经"), ensure_ascii=False) + "\n" + '{"kind": "char"}\n',
        encoding="utf-8",
    )
    dictionary = JsonlDictionary(path)
    assert dictionary.lookup("经"), "valid line must still be indexed"
    assert dictionary.malformed == 2


def test_unknown_character_lookup_is_empty_not_error(tmp_path: Path):
    path = _write(tmp_path / "test.jsonl", [_entry("一")])
    assert JsonlDictionary(path).lookup("\uffff") == []


def test_build_dictionary_index_discovers_entries_dir(tmp_path: Path):
    entries = tmp_path / "dictionaries-04-11-2026" / "entries"
    entries.mkdir(parents=True)
    _write(entries / "btcn.jsonl", [_entry("经", source="btcn")])
    index = build_dictionary_index(tmp_path, {"dictionary": {"entries_dir": "dictionaries-04-11-2026/entries"}})
    result = index.lookup("经")
    assert result.found
    assert any(name == "jsonl:btcn" for name in result.sources_present)
    assert "jsonl:btcn" in result.sources_checked
    assert index.lookup("一").found is False
    assert index.configured_sources  # presence accounting still reported
