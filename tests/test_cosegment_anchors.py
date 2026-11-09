"""Reading-anchor co-segmentation (Issue E, strict-uniqueness anchors)."""

from __future__ import annotations

from hannom.anchors import anchor_diagnostics, find_reading_anchors, token_items
from hannom.cosegment import PageUnit, qn_sentence_spans, stream_cosegment


class StubLexicon:
    def __init__(self, mapping: dict[str, list[str]]):
        self.mapping = mapping

    def readings(self, char: str) -> list[str]:
        return list(self.mapping.get(char, []))


def _units(nom: str, qn: str) -> tuple[list[PageUnit], list[PageUnit]]:
    return [PageUnit("T.001.jpg", nom)], [PageUnit("T.002.jpg", qn)]


# A stream with three unique anchor characters and noise around them.
# 之 → thì (occurs once), 其 → bóng (occurs once), 渝 → xà (occurs once).
# The filler character 沛 has no readings and can never anchor.
NOM = "沛沛沛沛沛沛沛之沛沛沛沛其沛沛沛渝沛沛沛"
QN = "Thì bóng. Xà kia mà."
LEX = {"之": ["thì"], "其": ["bóng"], "渝": ["xà"]}


def test_unique_unique_anchors_found():
    lexicon = StubLexicon(LEX)
    nom_items = [[reading for reading in lexicon.readings(ch)] for ch in NOM]
    tokens = token_items(QN)
    anchors = find_reading_anchors(nom_items, tokens)
    assert anchors == [(7, 0), (12, 1), (16, 2)]
    diag = anchor_diagnostics(nom_items, tokens)
    assert diag["anchors"] == 3
    assert diag["unique_unique_pairs"] == 3


def test_repeated_qn_tokens_do_not_anchor():
    lexicon = StubLexicon({"字": ["thì"]})
    # Every Nôm char matches both QN tokens; every QN token matches both
    # Nôm chars. Neither side is unique → no anchors.
    nom_items = [["thì"], ["thì"]]
    tokens = token_items("thì thì")
    assert find_reading_anchors(nom_items, tokens) == []
    diag = anchor_diagnostics(nom_items, tokens)
    assert diag["anchors"] == 0
    assert diag["dropped_ambiguous_items"] == 2


def test_competing_characters_sharing_one_token_do_not_anchor():
    lexicon = StubLexicon({"之": ["thì"], "其": ["thì"]})
    nom_items = [["thì"], ["thì"]]
    tokens = token_items("thì bóng")  # only one 'thì'
    # Both chars can anchor token 0; the token is contested → no anchor.
    assert find_reading_anchors(nom_items, tokens) == []


def test_ambiguous_dictionary_readings_do_not_anchor():
    lexicon = StubLexicon({"之": ["thì", "thế", "là", "cho", "và"]})
    nom_items = [[reading for reading in lexicon.readings(ch)] for ch in "之之之"]
    tokens = token_items("thì thế là cho và thêm nhiều nữa")
    assert find_reading_anchors(nom_items, tokens) == []


def test_mixed_unique_and_ambiguous_retains_only_unique():
    # 之→thì appears at two QN positions → ambiguous, dropped.
    # 沛→bóng appears once → unique, kept.
    lexicon = StubLexicon({"之": ["thì"], "沛": ["bóng"]})
    nom_items = [["thì"], ["thì"], ["bóng"]]
    tokens = token_items("thì thế thì bóng")
    anchors = find_reading_anchors(nom_items, tokens)
    assert (2, 3) in anchors
    assert all(i == 2 for i, _ in anchors)


def test_local_interpolation_does_not_cross_excessive_gap():
    lexicon = StubLexicon(LEX)
    nom_units, qn_units = _units(NOM, "Thì bóng. Xà kia mà.")
    stream = stream_cosegment(nom_units, qn_units, lexicon=lexicon, max_anchor_gap_tokens=0)
    # The two bracketing anchors are one token apart; with a gap limit of
    # zero the boundary cannot be interpolated → proportional fallback.
    assert stream is not None
    nom_segs, qn_segs = stream
    for segment in nom_segs + qn_segs:
        assert "COSEGMENTED_UNANCHORED" in segment.flags


def test_fallback_segments_are_flagged_unanchored():
    nom_units, qn_units = _units(NOM, QN)
    stream = stream_cosegment(nom_units, qn_units)  # no lexicon/dictionary
    assert stream is not None
    nom_segs, qn_segs = stream
    for segment in nom_segs + qn_segs:
        assert "COSEGMENTED_UNANCHORED" in segment.flags
        assert "COSEGMENTED_ANCHORED" not in segment.flags


def test_anchored_boundaries_surface_anchor_flags():
    nom_units, qn_units = _units(NOM, QN)
    lexicon = StubLexicon(LEX)
    anchored = stream_cosegment(nom_units, qn_units, lexicon=lexicon)
    assert anchored is not None
    nom_anchored, qn_anchored = anchored
    assert any("COSEGMENTED_ANCHORED" in s.flags for s in nom_anchored)
    assert not any("COSEGMENTED_UNANCHORED" in s.flags for s in nom_anchored)


def test_anchor_diagnostics_counts_competing_tokens():
    lexicon = StubLexicon({"之": ["thì"]})
    nom_items = [["thì"], ["thì"]]
    tokens = token_items("thì bóng")
    diag = anchor_diagnostics(nom_items, tokens)
    assert diag["competing_token_positions"] == 1
    assert diag["dropped_competing_tokens"] == 1
    assert diag["anchors"] == 0
