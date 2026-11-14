"""Tests for hannom.charstream (charalign-projected sentence segmentation)."""

from __future__ import annotations

from types import SimpleNamespace

from hannom.align import align_book
from hannom.charstream import stream_segments_by_charalign
from hannom.clean import CleanedPage
from hannom.t1_map import Pair


class StubDictionary:
    """Lookup-compatible stub dictionary for the reading matcher."""

    def __init__(self, readings: dict[str, list[str]]):
        self._readings = {c: list(v) for c, v in readings.items()}

    def lookup(self, char: str):
        return SimpleNamespace(readings=list(self._readings.get(char, [])))

    @property
    def source_names(self):
        return list(self._readings)


READINGS = {"的": ["de"], "我": ["wo"]}
DICTIONARY = StubDictionary(READINGS)


def make_fixture():
    nom_1 = "的" * 25
    nom_2 = "我" * 18
    qn_1 = "De de de de de de de de de de de de de ."
    qn_2 = "Wo wo wo wo wo wo wo wo wo wo wo wo wo ."
    pairs = [
        Pair(ch=("B.001.jpg",), vi=("A.001.jpg",)),
        Pair(ch=("B.002.jpg",), vi=("A.002.jpg",)),
    ]
    cleaned = {
        "B.001.jpg": CleanedPage("B", 1, "B.001.jpg", "nom", nom_1, [nom_1]),
        "B.002.jpg": CleanedPage("B", 2, "B.002.jpg", "nom", nom_2, [nom_2]),
        "A.001.jpg": CleanedPage("A", 1, "A.001.jpg", "qn", qn_1, [qn_1]),
        "A.002.jpg": CleanedPage("A", 2, "A.002.jpg", "qn", qn_2, [qn_2]),
    }
    return pairs, cleaned


def test_stream_segments_share_boundaries():
    pairs, cleaned = make_fixture()
    result = stream_segments_by_charalign(pairs, cleaned, dictionary=DICTIONARY)
    assert result is not None
    nom_segments, qn_segments, warnings = result
    assert len(nom_segments) == len(qn_segments) >= 1
    for nom_segment in nom_segments:
        assert "COSEGMENTED_STREAM_ALIGNED" in nom_segment.flags
        assert nom_segment.script == "nom"
    for qn_segment in qn_segments:
        assert "COSEGMENTED_STREAM_ALIGNED" in qn_segment.flags
        assert qn_segment.script == "qn"


def test_align_book_with_charalign_segmentation():
    pairs, cleaned = make_fixture()
    config = {"alignment": {"segmentation": "charalign", "strip_texts": [], "per_book": {}}}
    rows, warnings = align_book(
        "B", pairs, cleaned, config=config, lexicon=None, dictionary=DICTIONARY,
    )
    assert len(rows) >= 1
    for row in rows:
        assert "COSEGMENTED_STREAM_ALIGNED" in row.flags
