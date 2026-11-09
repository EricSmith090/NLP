"""Reading-anchor co-segmentation (Issue E)."""

from __future__ import annotations

from hannom.anchors import find_reading_anchors, token_items
from hannom.cosegment import PageUnit, qn_sentence_spans, stream_cosegment


class StubLexicon:
    def __init__(self, mapping: dict[str, list[str]]):
        self.mapping = mapping

    def readings(self, char: str) -> list[str]:
        return list(self.mapping.get(char, []))


def _units(nom: str, qn: str) -> tuple[list[PageUnit], list[PageUnit]]:
    return [PageUnit("T.001.jpg", nom)], [PageUnit("T.002.jpg", qn)]


# 24 Nôm characters; the QN text carries two matching landmark syllables.
NOM = "之之其其之之其其之之其其之之其其之之其其之之其其"
QN = "Trời làm nên rồi thì. Thế nào thì thế mà."


def test_anchors_follow_readings():
    lexicon = StubLexicon({"之": ["thì"], "其": ["thế"]})
    nom_items = [[reading for reading in lexicon.readings(ch)] for ch in NOM]
    tokens = token_items(QN)
    anchors = find_reading_anchors(nom_items, tokens)
    assert anchors, "anchors must exist when readings match"
    token_indices = [a[1] for a in anchors]
    assert token_indices == sorted(token_indices), "anchors must be monotone"


def test_repeated_qn_tokens_are_not_unique_anchors():
    lexicon = StubLexicon({"之": ["thì"]})
    nom_items = [[reading for reading in lexicon.readings(ch)] for ch in NOM]
    # Every QN token is 'thì': every anchor is possible, so the chain can
    # use each token at most once and must stay monotone.
    tokens = token_items("thì thì thì thì")
    anchors = find_reading_anchors(nom_items, tokens)
    token_used = [a[1] for a in anchors]
    assert len(token_used) == len(set(token_used)), "each token anchors at most one character"
    assert [a[0] for a in anchors] == sorted(a[0] for a in anchors), "anchors must be monotone"
    assert [a[1] for a in anchors] == sorted(a[1] for a in anchors), "token assignment must be monotone"
    assert len(anchors) <= 4


def test_ambiguous_readings_are_not_trusted():
    lexicon = StubLexicon({"之": ["thì", "thế", "là", "cho", "và"]})
    nom_items = [[reading for reading in lexicon.readings(ch)] for ch in "之之之"]
    tokens = token_items("thì thế là cho và thêm nhiều nữa")
    assert find_reading_anchors(nom_items, tokens) == []


def test_fallback_segments_are_flagged_unanchored():
    nom_units, qn_units = _units(NOM, QN)
    stream = stream_cosegment(nom_units, qn_units)  # no lexicon/dictionary
    assert stream is not None
    nom_segs, qn_segs = stream
    for segment in nom_segs + qn_segs:
        assert "COSEGMENTED_UNANCHORED" in segment.flags
        assert "COSEGMENTED_ANCHORED" not in segment.flags


def test_anchored_boundaries_surface_anchor_flags():
    # The QN text contains two anchor landmarks (thì, bừa) surrounded by
    # uninformative trivia; segmentation is driven by those anchors.
    nom = "之" * 24
    qn = "Trời mê hoặc một câu hiểm ác nhất thiên hạ thì. Bừa vào cho thế nào thật hay."
    lexicon = StubLexicon({"之": ["thì", "bừa"]})
    nom_units, qn_units = _units(nom, qn)
    anchored = stream_cosegment(nom_units, qn_units, lexicon=lexicon)
    assert anchored is not None
    nom_anchored, qn_anchored = anchored
    assert any("COSEGMENTED_ANCHORED" in s.flags for s in nom_anchored)
    assert all("COSEGMENTED_UNANCHORED" not in s.flags for s in nom_anchored)


def test_empty_anchor_evidence_recovers_proportionally():
    nom_units, qn_units = _units(NOM, QN)
    stream = stream_cosegment(nom_units, qn_units, lexicon=StubLexicon({}), dictionary=None)
    assert stream is not None
    for segment in stream[0] + stream[1]:
        assert "COSEGMENTED_UNANCHORED" in segment.flags
