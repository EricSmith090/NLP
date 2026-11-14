"""Dictionary-assisted text comparison (Issue F)."""

from __future__ import annotations

from hannom.textdiff import DiffResult, auto_text_diff


class StubDictionary:
    def __init__(self, readings: dict[str, list[str]]):
        self.readings_by_char = readings
        self.source_names = [name for name, r in readings.items() if r]

    def lookup(self, char: str):
        class Result:
            def __init__(self, readings):
                self.readings = readings

        return Result(list(self.readings_by_char.get(char, [])))


class StubLexicon:
    def __init__(self, mapping: dict[str, list[str]]):
        self.mapping = mapping

    def readings(self, char: str) -> list[str]:
        return list(self.mapping.get(char, []))


NOM_TEXT = "之之其"
VI_TEXT = "thì thì thế"


def test_dictionary_reading_without_lexicon_contributes():
    dictionary = StubDictionary({"之": ["thì"], "其": ["thế"]})
    result = auto_text_diff(NOM_TEXT, VI_TEXT, lexicon=None, dictionary=dictionary)
    assert result.known_nom_chars == 3
    assert result.matched_readings == 3
    assert result.dictionary_matched_readings == 3
    assert result.lexicon_matched_readings == 0
    assert "DIFF_READINGS_FROM_DICTIONARY" in result.flags
    assert result.elements == []


def test_multiple_dictionary_readings_are_retained_not_collapsed():
    dictionary = StubDictionary({"之": ["thì", "chi", "thế"]})
    lexicon = StubLexicon({"之": ["thì"]})
    result = auto_text_diff("之", "thì", lexicon=lexicon, dictionary=dictionary)
    assert result.known_nom_chars == 1
    # All three dictionary forms remain candidates; the anchor resolves
    # on the one the QN text actually carries. Exactly one is matchable,
    # so no ambiguity is flagged.
    assert result.matched_readings == 1
    assert result.ambiguous_nom_chars == 0
    assert result.elements == []


def test_ambiguous_readings_are_flagged():
    # Both dictionary readings of 之 appear as tokens in the sentence;
    # evidence exists, but it is ambiguous and cannot verify the row.
    dictionary = StubDictionary({"之": ["thì", "thế"]})
    result = auto_text_diff("之", "thì thế", lexicon=None, dictionary=dictionary)
    assert "DIFF_AMBIGUOUS_READINGS" in result.flags


def test_ambiguous_evidence_with_unmatched_text_stays_unverified_flagged():
    dictionary = StubDictionary({"之": ["thì", "thế"], "其": ["thế"]})
    result = auto_text_diff("其", "thì", lexicon=None, dictionary=dictionary)
    assert "DIFF_AMBIGUOUS_READINGS" not in result.flags  # 其 has one form
    assert result.ambiguous_nom_chars == 0


def test_dictionary_known_but_lexically_invisible():
    dictionary = StubDictionary({"之": ["một"]})
    lexicon = StubLexicon({"之": ["khôngcó"]})
    # Lexicon has no matchable reading; dictionary carries the one used.
    result = auto_text_diff("之", "một", lexicon=lexicon, dictionary=dictionary)
    assert result.matched_readings == 1
    assert result.dictionary_matched_readings == 1
    assert result.elements == []


def test_lexicon_evidence_is_retained():
    lexicon = StubLexicon({"之": ["thì"]})
    result = auto_text_diff("之", "thì", lexicon=lexicon, dictionary=None)
    assert result.lexicon_matched_readings == 1
    assert result.dictionary_matched_readings == 0
