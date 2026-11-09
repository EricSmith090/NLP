"""Lexicon learning safety (Issue C, refined by 2026-11-09 audit).

Learning requires an explicit, non-stale verifying review decision with
positional correspondence: either a reviewer-recorded character-to-token
mapping, or a single Nôm character paired with a single explicitly
accepted QN token. Sentence-level dictionary membership never suffices.
"""

from __future__ import annotations

import json

from hannom.dictionary.book_lexicon import BookLexicon
from hannom.models import AlignmentRow

REVIEWER = "reviewer.one"


def _row(
    ch: str,
    vi: str,
    *,
    status: str | None = "accepted_match",
    mappings: list[dict] | None = None,
    flags: tuple[str, ...] = (),
) -> AlignmentRow:
    return AlignmentRow(
        img_id="Book.001.jpg",
        sentence_id="Book.001.1",
        ch_txt=ch,
        vi_txt=vi,
        text_diff=None,
        confidence=0.9,
        flags=list(flags),
        review_status=status,
        review_reviewer=REVIEWER,
        character_token_mappings=mappings or [],
    )


def _mapping(char: str, nom_pos: int, token: str, token_pos: int) -> dict:
    return {
        "nom_char": char,
        "nom_position": nom_pos,
        "qn_token": token,
        "qn_token_position": token_pos,
    }


class StubDictionary:
    def __init__(self, readings: dict[str, list[str]]):
        self.readings_by_char = readings

    def lookup(self, char: str):
        class Result:
            pass

        result = Result()
        result.readings = list(self.readings_by_char.get(char, []))
        return result


def test_unreviewed_rows_never_learn(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows(
        [_row("之", "thì", status=None), _row("可", "là", status=None)],
        dictionary=None,
    )
    assert stats["learned_pairs"] == 0
    assert stats["skipped_unreviewed"] == 2
    assert lexicon.readings("之") == []


def test_single_char_single_token_acceptance_learns(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows([_row("之", "thì")], dictionary=None)
    assert stats["learned_pairs"] == 1
    assert lexicon.readings("之") == ["thì"]
    provenance = lexicon.provenance_for("之", "thì")
    assert len(provenance) == 1
    assert provenance[0]["evidence"] == "single_token_accepted"
    assert provenance[0]["reviewer"] == REVIEWER
    assert provenance[0]["decision_status"] == "accepted_match"
    assert provenance[0]["sentence_id"] == "Book.001.1"


def test_multi_token_row_without_positional_mapping_does_not_learn(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows(
        [_row("之", "thì mà để")], dictionary=StubDictionary({"之": ["thì"]})
    )
    assert stats["learned_pairs"] == 0
    assert stats["skipped_no_positional_evidence"] == 1


def test_dictionary_reading_in_sentence_is_not_positional_evidence(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    # 之's reading 'thì' appears in the sentence, but nothing ties 之 to it.
    stats = lexicon.learn_from_rows(
        [_row("之", "thì mà để")], dictionary=StubDictionary({"之": ["thì", "chi"]})
    )
    assert stats["learned_pairs"] == 0
    assert lexicon.readings("之") == []


def test_repeated_readings_do_not_establish_correspondence(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows(
        [_row("之", "thì thế thì")], dictionary=StubDictionary({"之": ["thì"]})
    )
    assert stats["learned_pairs"] == 0
    assert lexicon.readings("之") == []


def test_complex_row_with_two_characters_does_not_learn(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows(
        [_row("之其", "thì thế")], dictionary=StubDictionary({})
    )
    assert stats["learned_pairs"] == 0
    assert stats["skipped_no_positional_evidence"] == 1


def test_explicit_positional_mapping_learns_expected_reading(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    row = _row(
        "之其",
        "thì mà thế",
        mappings=[_mapping("之", 0, "thì", 0), _mapping("其", 1, "thế", 2)],
    )
    stats = lexicon.learn_from_rows([row], dictionary=None)
    assert stats["learned_pairs"] == 2
    assert lexicon.readings("之") == ["thì"]
    assert lexicon.readings("其") == ["thế"]
    for char, syllable in (("之", "thì"), ("其", "thế")):
        for record in lexicon.provenance_for(char, syllable):
            assert record["evidence"] == "explicit_mapping"
            assert record["reviewer"] == REVIEWER


def test_invalid_mapping_does_not_learn(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    # Character does not match the Nôm text at the declared position.
    row = _row("之", "thì mà để", mappings=[_mapping("其", 0, "thì", 0)])
    stats = lexicon.learn_from_rows([row], dictionary=None)
    assert stats["learned_pairs"] == 0
    assert stats["skipped_invalid_mapping"] == 1
    # Token does not match the QN text at the declared position.
    row = _row("之", "thì mà để", mappings=[_mapping("之", 0, "thế", 2)])
    stats = lexicon.learn_from_rows([row], dictionary=None)
    assert stats["learned_pairs"] == 0
    assert stats["skipped_invalid_mapping"] == 1


def test_mapping_with_repeating_candidates_is_allowed_when_reviewer_confirmed(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    # 'thì' occurs twice; the reviewer picked the second occurrence.
    row = _row("之", "thì thế thì", mappings=[_mapping("之", 0, "thì", 2)])
    stats = lexicon.learn_from_rows([row], dictionary=None)
    assert stats["learned_pairs"] == 1
    assert lexicon.readings("之") == ["thì"]
    provenance = lexicon.provenance_for("之", "thì")
    assert provenance[0]["qn_token_position"] == 2


def test_blocked_status_does_not_learn_even_with_mapping_absent(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows(
        [_row("之", "thì", status="unresolved")], dictionary=None
    )
    assert stats["learned_pairs"] == 0
    assert stats["skipped_unreviewed"] == 1


def test_blocking_flags_prevent_single_token_learning(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows(
        [
            _row("之", "thì", flags=("NON_ONE_TO_ONE",)),
            _row("之", "thì", flags=("UNMATCHED_NOM",)),
            _row("之", "thì", flags=("ALIGN_LOW_CONF",)),
            _row("之", "thì", flags=("ALIGN_EVIDENCE_INSUFFICIENT",)),
            _row("之", "thì", flags=("COSEGMENTED_UNANCHORED",)),
            _row("之", "thì", flags=("REVIEW_METADATA_MISSING",)),
            _row("之", "thì", flags=("REVIEW_DECISION_STALE",)),
        ],
        dictionary=None,
    )
    assert stats["learned_pairs"] == 0
    assert stats["skipped_blocked"] == 7


def test_explicit_mapping_learning_is_allowed_on_flagged_rows(tmp_path):
    # A reviewer with explicit positional evidence overrides machine flags.
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    row = _row("之", "thì mà để", flags=("ALIGN_LOW_CONF",), mappings=[_mapping("之", 0, "thì", 0)])
    stats = lexicon.learn_from_rows([row], dictionary=None)
    assert stats["learned_pairs"] == 1


def test_provenance_survives_serialization_and_reload(tmp_path):
    path = tmp_path / "lexicon.json"
    lexicon = BookLexicon(path)
    row = _row("之其", "thì thế", mappings=[_mapping("之", 0, "thì", 0), _mapping("其", 1, "thế", 1)])
    stats = lexicon.learn_from_rows([row], dictionary=None)
    assert stats["learned_pairs"] == 2
    lexicon.save()
    reloaded = BookLexicon(path)
    for char, syllable in (("之", "thì"), ("其", "thế")):
        assert reloaded.readings(char) == [syllable]
        records = reloaded.provenance_for(char, syllable)
        assert records and records[0]["evidence"] == "explicit_mapping"
        assert records[0]["reviewer"] == REVIEWER


def test_legacy_entries_are_quarantined_on_load_and_never_trusted(tmp_path):
    path = tmp_path / "lexicon.json"
    path.write_text(
        json.dumps(
            {
                "meta": {"learned_pairs": 2},
                "readings": {"之": {"thì": 3}, "沛": {"eusebe": 1}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lexicon = BookLexicon(path)
    assert lexicon.readings("之") == []
    assert lexicon.readings("沛") == []
    summary = lexicon.quarantine_summary()
    assert summary["legacy_without_provenance_pairs"] == 4
    assert summary["trusted_pairs"] == 0

    # Legacy entries are preserved, not deleted.
    lexicon.save()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["quarantine"]["legacy_without_provenance"]["之"]["thì"] == 3


def test_restore_quarantine_is_explicit(tmp_path):
    path = tmp_path / "lexicon.json"
    path.write_text(
        json.dumps({"meta": {}, "readings": {"之": {"thì": 2}}}), encoding="utf-8"
    )
    lexicon = BookLexicon(path)
    promoted = lexicon.restore_quarantine(char="之")
    assert promoted == 1
    assert lexicon.readings("之") == ["thì"]


def test_unverified_additions_go_to_quarantine(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    assert lexicon.add("之", "thì", 5) is False
    assert lexicon.readings("之") == []
    assert lexicon.quarantine_summary()["unverified_pairs"] == 5
