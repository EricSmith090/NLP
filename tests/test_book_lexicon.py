"""Lexicon learning safety (Issue C)."""

from __future__ import annotations

import json

from hannom.dictionary.book_lexicon import BookLexicon
from hannom.models import AlignmentRow


def _row(ch: str, vi: str, flags: list[str]) -> AlignmentRow:
    return AlignmentRow(
        img_id="Book.001.jpg",
        sentence_id="Book.001.1",
        ch_txt=ch,
        vi_txt=vi,
        text_diff=None,
        confidence=0.9,
        flags=list(flags),
    )


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
        [_row("之", "thì", []), _row("可", "là", ["ALIGN_LOW_CONF"])], dictionary=None
    )
    assert stats["learned_pairs"] == 0
    assert stats["skipped_unreviewed"] == 2
    assert lexicon.readings("之") == []


def test_blocking_flags_prevent_learning(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows(
        [
            _row("之", "thì", ["HUMAN_REVIEWED", "NON_ONE_TO_ONE"]),
            _row("之", "thì", ["HUMAN_REVIEWED", "UNMATCHED_NOM"]),
            _row("之", "thì", ["HUMAN_REVIEWED", "ALIGN_LOW_CONF"]),
            _row("之", "thì", ["HUMAN_REVIEWED", "COSEGMENTED_UNANCHORED"]),
            _row("之", "thì", ["HUMAN_REVIEWED", "REVIEW_METADATA_MISSING"]),
        ],
        dictionary=None,
    )
    assert stats["learned_pairs"] == 0
    assert stats["skipped_blocked"] == 5


def test_human_reviewed_single_token_learns_with_provenance(tmp_path):
    path = tmp_path / "lexicon.json"
    lexicon = BookLexicon(path)
    stats = lexicon.learn_from_rows([_row("之", "thì", ["HUMAN_REVIEWED"])], dictionary=None)
    assert stats["learned_pairs"] == 1
    assert lexicon.readings("之") == ["thì"]
    provenance = lexicon.provenance_for("之", "thì")
    assert len(provenance) == 1
    assert provenance[0]["source"] == "human_reviewed_row"
    assert provenance[0]["evidence"] == "single_token"
    assert provenance[0]["sentence_id"] == "Book.001.1"

    # Provenance survives a save/reload cycle.
    lexicon.save()
    reloaded = BookLexicon(path)
    assert reloaded.readings("之") == ["thì"]
    assert reloaded.provenance_for("之", "thì") == provenance


def test_human_reviewed_dictionary_reading_learns(tmp_path):
    dictionary = StubDictionary({"之": ["thì", "chi"]})
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows(
        [_row("之", "thì mà để", ["HUMAN_REVIEWED"])], dictionary=dictionary
    )
    assert stats["learned_pairs"] == 1
    assert lexicon.readings("之") == ["thì"]


def test_ambiguous_human_reviewed_row_does_not_learn(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows(
        [_row("之其", "thì thế", ["HUMAN_REVIEWED"])], dictionary=StubDictionary({})
    )
    assert stats["learned_pairs"] == 0
    assert stats["skipped_ambiguous"] == 1


def test_multiple_dictionary_readings_do_not_guess(tmp_path):
    dictionary = StubDictionary({"之": ["thì", "thế"]})
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    stats = lexicon.learn_from_rows(
        [_row("之", "thì thế", ["HUMAN_REVIEWED"])], dictionary=dictionary
    )
    # Both candidate readings appear in the row: the correspondence is
    # not unambiguous, so nothing is learned.
    assert stats["learned_pairs"] == 0
    assert stats["skipped_ambiguous"] == 1


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
