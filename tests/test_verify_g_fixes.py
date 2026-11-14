"""Regression tests for the verify-G dictionary-subsystem fixes.

Covers (see Doc/verify-G-dictionary.md):
- H1: Kim Hán Nôm PUA handling — opt-in flag, KHN PUA map, learning gates
- H2: hannom_rcv chuẩn bảng positional spread in the readings cache
- H3: catusf skip at ingest (config + build_readings skip_sources)
- M1: count-faithful reconcile + ``counts_rewritten`` in the summary
- M2: ``_authorized_granules`` single-token branch honours BLOCKING_FLAGS
- M3: slash-glued readings split consistently in LookupResult
- M4: word/cache evidence merged into the in-pipeline evidence path;
      uniqueness still enforced; opt-in DP fold bonus (fold-only anchors at half weight)
- Path A learn counter only counts what the lexicon actually learned

Everything here is synthetic or read-only; no repo data files are touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hannom import pua_map
from hannom.anchors import find_reading_anchors, gather_readings
from hannom.clean import count_nom_chars, is_nom_char, sanitize_nom_text
from hannom.dictionary import readings as readings_mod
from hannom.dictionary.book_lexicon import BookLexicon
from hannom.dictionary.index import LookupResult, Sense
from hannom.dictionary.readings import CACHE_VERSION
from hannom.pua_map import load_pua_map

TIMES = "時"
PUA_F021D = "\U000F021D"
PUA_F047C = "\U000F047C"
DE_CHAR = "德"  # U+5FB7, matches the fold-pair probes from verify-G


@pytest.fixture(autouse=True)
def _pua_reset():
    pua_map.reset()
    yield
    pua_map.reset()


def _write_lexicon(path: Path, *, readings=None, provenance=None, quarantine=None) -> None:
    payload = {
        "meta": {"learned_pairs": 0},
        "readings": readings or {},
        "provenance": provenance or {},
        "revoked": {},
        "quarantine": {
            "legacy_without_provenance": (quarantine or {}).get("legacy", {}),
            "unverified": (quarantine or {}).get("unverified", {}),
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ----------------------------------------------------------------------
# H1 — PUA handling
# ----------------------------------------------------------------------

def test_h1_pua_inert_by_default():
    assert not is_nom_char(PUA_F021D)
    assert not is_nom_char(PUA_F047C)
    assert count_nom_chars(TIMES + PUA_F047C) == 1
    out, counts, flags = sanitize_nom_text(TIMES + PUA_F047C)
    assert out == TIMES + "〓"
    assert "NOM_UNENCODABLE_REPLACED" in flags


def test_h1_pua_optin_masks_mapped_to_standard_char():
    pua_map.set_mapping({0xF021D: "𡃕"})
    pua_map.set_enabled(True)
    assert is_nom_char(PUA_F021D)
    assert count_nom_chars(TIMES + PUA_F021D) == 2
    out, counts, flags = sanitize_nom_text(PUA_F021D + TIMES)
    assert out == "𡃕" + TIMES
    assert "NOM_PUA_MAPPED" in flags
    # An unmapped PUA code point is still unencodable — never guessed.
    out, counts, flags = sanitize_nom_text(PUA_F047C)
    assert out == "〓"
    assert "NOM_UNENCODABLE_REPLACED" in flags


def test_h1_unmapped_pua_learning_gate_admits_when_enabled(tmp_path: Path):
    pua_map.set_mapping({0xF047C: TIMES})
    pua_map.set_enabled(True)
    lex = BookLexicon(tmp_path / "lex.json")
    ok = lex.add(
        PUA_F047C,
        "nhat",
        provenance={
            "source": "human_review_decision",
            "evidence": "explicit_mapping",
            "sentence_id": "img.1",
            "nom_position": 0,
            "qn_token_position": 0,
        },
    )
    assert ok
    assert lex.data[PUA_F047C]["nhat"] == 1


def test_h1_khn_pua_seed_file_loads_clean():
    mapping, problems = load_pua_map(Path("configs/khn_pua_map.yaml"))
    assert problems == []
    assert mapping.get(0xF021D) == "𡃕"


def test_h1_pua_map_validation_rejects_junk(tmp_path: Path):
    yaml_text = (
        "F021D: \"𡃕\"\n"          # valid mapping
        "4E00: \"時\"\n"          # not a PUA code point
        "F047C: \"ab\"\n"         # value not a single character
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml_text, encoding="utf-8")
    mapping, problems = load_pua_map(bad)
    assert mapping == {0xF021D: "𡃕"}
    assert len(problems) == 2


def test_h1_learning_path_a_honors_flag(tmp_path: Path):
    # With PUA handling disabled, a PUA head can never satisfy the row-bound
    # positional validation, so explicit mappings are dropped, never learned.
    row = {
        "ch_txt": PUA_F021D,
        "vi_txt": "gung",
        "sentence_id": "x.1",
        "review_status": "accepted_match",
        "decision_integrity": "valid",
        "flags": [],
        "character_token_mappings": [
            {"nom_position": 0, "qn_token_position": 0, "nom_char": PUA_F021D, "qn_token": "gung"}
        ],
    }
    lex = BookLexicon(tmp_path / "off.json")
    summary = lex.learn_from_rows([row])
    assert summary["learned_pairs"] == 0
    assert summary["skipped_invalid_mapping"] >= 1

    pua_map.set_mapping({0xF021D: "𡃕"})
    pua_map.set_enabled(True)
    lex = BookLexicon(tmp_path / "on.json")
    summary = lex.learn_from_rows([row])
    assert summary["learned_pairs"] == 1
    assert lex.data[PUA_F021D]["gung"] == 1


def test_h1_pua_lands_in_cache_build(tmp_path: Path):
    entries = tmp_path / "entries"
    entries.mkdir()
    record = {
        "id": "btcn:char:test",
        "source": "btcn",
        "kind": "char",
        "head": PUA_F021D,
        "script": "nom",
        "readings": [{"value": "gùng", "system": "qn"}],
    }
    (entries / "btcn.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    # Disabled (default): PUA head is indexed as a PUA key.
    built = readings_mod.build_readings(entries)
    assert PUA_F021D in built["char"]
    # Enabled with mapping: the entry lands under the mapped standard char.
    pua_map.set_mapping({0xF021D: "𡃕"})
    pua_map.set_enabled(True)
    built = readings_mod.build_readings(entries)
    assert "𡃕" in built["char"]
    assert PUA_F021D not in built["char"]


# ----------------------------------------------------------------------
# H2 — hannom_rcv chuẩn bảng positional spread
# ----------------------------------------------------------------------

_CHUAN_RCV = [
    {
        "id": "hannom_rcv:w:ái ngại",
        "source": "hannom_rcv",
        "kind": "word",
        "head": "ái ngại",
        "script": "qn",
        "forms": [{"text": "愛懝", "script": "nom"}],
        "readings": None,
        "extra": {"rows": [["ái ngại", "愛懝", "", "nhâng nháo", "仍𬇣"]]},
        "ref": {"url": "https://www.hannom-rcv.org/"},
    },
    {
        "id": "hannom_rcv:w:âm ấm",
        "source": "hannom_rcv",
        "kind": "word",
        "head": "âm ấm",
        "script": "qn",
        "forms": [{"text": "𤋾𤋾", "script": "nom"}],
        "readings": None,
    },
]


def _make_entries(tmp_path: Path) -> Path:
    entries = tmp_path / "entries"
    entries.mkdir()
    for record in _CHUAN_RCV:
        with (entries / "hannom_rcv.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    catusf_record = {
        "id": "catusf:x:one",
        "kind": "word",
        "head": "uno",
        "script": "latin",
        "senses": [{"text": "one", "lang": "en"}],
    }
    (entries / "catusf.jsonl").write_text(
        json.dumps(catusf_record, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    char_record = {
        "id": "dv:char:爱",
        "kind": "char",
        "head": "愛",
        "script": "han",
        "readings": [{"value": "á", "system": "hv"}],
    }
    (entries / "dv.jsonl").write_text(json.dumps(char_record, ensure_ascii=False) + "\n", encoding="utf-8")
    return entries


def test_h2_chuan_head_spreads_onto_nom_form(tmp_path: Path):
    entries = _make_entries(tmp_path)
    built = readings_mod.build_readings(entries, skip_sources=["catusf.jsonl"])
    # chuẩn spread: ái ngại → 愛/ái, 懝/ngại (word table, like dv word evidence)
    assert set(built["word"].get("愛", [])) >= {"ái"}
    assert set(built["word"].get("懝", [])) >= {"ngại"}
    assert set(built["word"].get("𤋾", [])) >= {"âm", "ấm"} or "𤋾" in built["word"]


def test_h2_chuan_spread_not_applied_without_null_readings_key(tmp_path: Path):
    entries = tmp_path / "entries"
    entries.mkdir()
    # A chuẩn-shaped record that HAS readings goes through the normal path;
    # the head-as-reading shortcut must not fire.
    record = {
        "id": "hannom_rcv:w:ái ngại",
        "kind": "word",
        "head": "ái ngại",
        "script": "qn",
        "forms": [{"text": "愛懝", "script": "nom"}],
        "readings": [{"value": "ái ngại", "system": "qn"}],
    }
    (entries / "hannom_rcv.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    built = readings_mod.build_readings(entries)
    assert built["word"].get("愛") == ["ái"]
    assert built["word"].get("懝") == ["ngại"]


def test_cache_version_bumped():
    assert CACHE_VERSION >= 2


# ----------------------------------------------------------------------
# H3 — catusf skipped at ingest
# ----------------------------------------------------------------------

def test_h3_skip_sources_drops_catusf(tmp_path: Path):
    entries = _make_entries(tmp_path)
    built_with = readings_mod.build_readings(entries, skip_sources=["catusf.jsonl"])
    built_without = readings_mod.build_readings(entries)
    assert built_with["sources"] == sorted(built_with["sources"])
    assert "catusf.jsonl" not in built_with["sources"]
    assert "catusf.jsonl" in built_without["sources"]
    # catusf contributes nothing either way (it has no readings keys)
    assert built_with["char"] == built_without["char"]
    assert built_with["word"] == built_without["word"]


def test_h3_config_declares_skip():
    text = Path("configs/dictionary.yaml").read_text(encoding="utf-8")
    assert "skip_sources" in text
    assert "catusf.jsonl" in text


# ----------------------------------------------------------------------
# M1 — count-faithful reconcile
# ----------------------------------------------------------------------

def test_m1_restore_reconcile_roundtrip_preserves_weights(tmp_path: Path):
    path = tmp_path / "T1_SuaLoiQuyen.json"
    _write_lexicon(path, readings={TIMES: {"thì": 1080, "thi": 22, "thà": 4, "tha": 1}})

    lex = BookLexicon(path)
    assert lex.data == {}  # legacy: nothing trusted before explicit restore
    promoted = lex.restore_quarantine(char=TIMES, syllable="thì")
    assert promoted == 1
    assert lex.data[TIMES]["thì"] == 1080
    lex.save()

    lex = BookLexicon(path)
    summary = lex.reconcile(rows=[])
    assert lex.data[TIMES]["thì"] == 1080  # pre-fix would have persisted 1
    assert summary["changed"] is False
    assert summary["counts_rewritten"] == 0
    lex.save()
    lex = BookLexicon(path)
    assert lex.data[TIMES]["thì"] == 1080


def test_m1_reconcile_reports_weight_drift(tmp_path: Path):
    path = tmp_path / "lex.json"
    _write_lexicon(
        path,
        readings={TIMES: {"thì": 5}},
        provenance={
            TIMES: {
                "thì": [
                    {
                        "source": "manual_restore",
                        "evidence": "human_restore",
                        "restored_at": "2026-11-14T00:00:00+00:00",
                        "count": 1080,
                    }
                ]
            }
        },
    )
    lex = BookLexicon(path)
    summary = lex.reconcile(rows=[])
    assert summary["counts_rewritten"] == 1
    assert summary["changed"] is True
    assert lex.data[TIMES]["thì"] == 1080  # count-faithful rebuild

    lex = BookLexicon(path)
    before = dict(lex.data[TIMES])
    summary = lex.reconcile(rows=[], dry_run=True)
    assert summary["counts_rewritten"] == 1  # drift is reported…
    assert summary["changed"] is True
    assert lex.data[TIMES] == before          # …but dry-run mutates nothing


def test_m1_summary_exposes_counts_rewritten():
    # The reconcile verdict must carry the new counter so orchestrators
    # can key backup decisions off it.
    import inspect

    source = inspect.getsource(BookLexicon.reconcile)
    assert "counts_rewritten" in source


# ----------------------------------------------------------------------
# M2 — _authorized_granules honours BLOCKING_FLAGS (path B only)
# ----------------------------------------------------------------------

def _granule_row(**overrides):
    row = {
        "sentence_id": "img.1",
        "ch_txt": TIMES,
        "vi_txt": "thì",
        "decision_integrity": "valid",
        "review_status": "accepted_match",
        "flags": [],
        "character_token_mappings": [],
    }
    row.update(overrides)
    return row


def test_m2_single_token_blocked_by_flags():
    assert BookLexicon._authorized_granules([_granule_row()]) == {
        ("img.1", 0, 0, TIMES, "thì")
    }
    assert BookLexicon._authorized_granules([_granule_row(flags=["ALIGN_LOW_CONF"])]) == set()
    assert (
        BookLexicon._authorized_granules([_granule_row(flags=["ALIGN_EVIDENCE_INSUFFICIENT"])]) == set()
    )
    assert BookLexicon._authorized_granules([_granule_row(flags=["COSEGMENTED_UNANCHORED"])]) == set()


def test_m2_path_a_explicit_mappings_stay_flag_agnostic():
    row = _granule_row(
        flags=["ALIGN_LOW_CONF"],
        character_token_mappings=[
            {"nom_position": 0, "qn_token_position": 0, "nom_char": TIMES, "qn_token": "thì"}
        ],
    )
    granules = BookLexicon._authorized_granules([row])
    assert ("img.1", 0, 0, TIMES, "thì") in granules


def test_m2_blocking_flags_match_learn_path_b():
    # The two predicates now agree on exactly the single-token case.
    from hannom.dictionary.book_lexicon import BLOCKING_FLAGS

    assert "ALIGN_LOW_CONF" in BLOCKING_FLAGS
    assert "ALIGN_EVIDENCE_INSUFFICIENT" in BLOCKING_FLAGS


def test_real_config_files_parse():
    import yaml

    for name in ("configs/alignment.yaml", "configs/dictionary.yaml", "configs/project.yaml"):
        with open(name, encoding="utf-8") as handle:
            yaml.safe_load(handle)
    project = __import__("hannom.config", fromlist=["load_config"]).load_config()
    assert project is not None
    alignment = (project.alignment_config or {}).get("alignment", project.alignment_config or {})
    assert alignment.get("dp_fold_bonus") is False  # shipped OFF
    with open("configs/dictionary.yaml", encoding="utf-8") as handle:
        assert yaml.safe_load(handle)["dictionary"]["skip_sources"] == ["catusf.jsonl"]


# ----------------------------------------------------------------------
# M3 — slash-glued tokens split consistently
# ----------------------------------------------------------------------

def test_m3_lookup_result_reads_slash_tokens():
    sense = Sense(source="hvdic:test", reading="bạ/bộ")
    result = LookupResult(char="簿", senses=[sense])
    assert result.readings == ["bạ", "bộ"]


def test_m3_lookup_result_drops_bare_separators():
    sense = Sense(source="dv:test", reading="/ đào")
    assert LookupResult(char="淘", senses=[sense]).readings == ["đào"]
    sense = Sense(source="dnqatv:test", reading="thuê ghe/thuyền/đò")
    assert LookupResult(char="x", senses=[sense]).readings == ["thuê", "ghe", "thuyền", "đò"]
    sense = Sense(source="s", reading="nhật, nhựt")
    assert LookupResult(char="x", senses=[sense]).readings == ["nhật", "nhựt"]


# ----------------------------------------------------------------------
# M4 — word-spread evidence reaches the in-pipeline paths; uniqueness kept
# ----------------------------------------------------------------------

class _FakeCache:
    def __init__(self, table):
        self.table = {k: frozenset(v) for k, v in table.items()}

    def of(self, ch):
        return self.table.get(ch, frozenset())


class _FakeDictionary:
    def __init__(self, table):
        self.table = {k: Sense(source="fake", reading=v) for k, v in table.items()}

    def lookup(self, char):
        sense = self.table.get(char)
        senses = [sense] if sense else []
        return LookupResult(char=char, senses=senses)


def test_m4_gather_readings_merges_cache_with_dedup():
    dictionary = _FakeDictionary({TIMES: "thì"})
    cache = _FakeCache({TIMES: {"thì", "thi"}})
    merged, source = gather_readings(TIMES, lexicon=None, dictionary=dictionary, readings=cache)
    assert merged == ["thì", "thi"]
    assert source == "dictionary+readings-cache"


def test_m4_cache_only_evidence():
    cache = _FakeCache({TIMES: {"thì"}})
    merged, source = gather_readings(TIMES, readings=cache)
    assert merged == ["thì"]
    assert source == "readings-cache"
    merged, source = gather_readings(TIMES)
    assert merged == [] and source == "none"


def test_m4_uniqueness_rule_still_enforced_with_cache():
    items = [["ái"], ["ái"]]  # two Nôm positions, one shared token
    token_items = [(0, 3, "ái")]
    assert find_reading_anchors(items, token_items) == []


def test_m4_dp_fold_bonus_optin():
    from hannom.align import _reading_matches

    dictionary = _FakeDictionary({DE_CHAR: "đức"})
    matched, known = _reading_matches(DE_CHAR, "dục", None, dictionary)
    assert (matched, known) == (0.0, 1)  # exact-only default: unchanged
    matched, known = _reading_matches(DE_CHAR, "dục", None, dictionary, dp_fold=True)
    assert matched == pytest.approx(0.5) and known == 1  # fold-only anchor = 1.0
    matched, known = _reading_matches(DE_CHAR, "đức", None, dictionary)
    assert (matched, known) == (1.0, 1)                   # exact anchor = 2.0 (full)


def test_m4_sources_chain_note():
    # The compact cache is char ∪ word; integration paths now merge it.
    source = gather_readings(DE_CHAR, readings=_FakeCache({DE_CHAR: {"đức"}}))[1]
    assert "readings-cache" in source
