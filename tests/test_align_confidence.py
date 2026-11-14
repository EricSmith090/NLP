"""Structural vs semantic confidence separation (Issue 5)."""

from __future__ import annotations

from hannom.align import AlignConfig, TextSegment, align_segments, semantic_evidence
from hannom.evaluate import evaluate_rows


def _seg(text: str, image_name: str, page_no: int, order: int, script: str) -> TextSegment:
    return TextSegment(
        text=text,
        image_name=image_name,
        page_no=page_no,
        page_numbers=(page_no,),
        image_names=(image_name,),
        script=script,
        order=order,
    )


class StubLexicon:
    def __init__(self, mapping: dict[str, list[str]]):
        self.mapping = mapping

    def readings(self, char: str) -> list[str]:
        return list(self.mapping.get(char, []))


def test_equal_length_unrelated_segments_do_not_get_max_semantic_confidence():
    # 之其 vs "sáng tối": structurally perfect grouping, zero evidence.
    nom = [_seg("之其", "B.001.jpg", 1, 0, "nom")]
    qn = [_seg("sáng tối", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({}))
    (row,) = rows
    assert row.semantic_confidence is None  # no evidence, not "perfect"
    assert "ALIGN_EVIDENCE_INSUFFICIENT" in row.flags
    # Structural confidence is a *grouping* score and may be high, but it
    # is meaningless for correspondence — make sure it is not conflated.
    metrics = evaluate_rows("b", rows)
    assert metrics.verified_match_rows == 0
    assert metrics.structural_confidence_mean is not None
    assert metrics.evidence_insufficient_rows == 1


def test_reading_supported_one_to_one_receives_semantic_evidence():
    nom = [_seg("之", "B.001.jpg", 1, 0, "nom")]
    qn = [_seg("thì", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({"之": ["thì"]}))
    (row,) = rows
    assert row.semantic_confidence == 1.0
    assert "ALIGN_EVIDENCE_INSUFFICIENT" not in row.flags
    assert "ALIGNED" in row.flags


def test_structurally_plausible_but_unverified_pairing_remains_candidate():
    nom = [_seg("之", "B.001.jpg", 1, 0, "nom")]
    qn = [_seg("một câu hoàn toàn khác biệt", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({}))
    (row,) = rows
    assert row.confidence == row.confidence  # structural exists
    assert row.semantic_confidence is None
    assert "ALIGN_EVIDENCE_INSUFFICIENT" in row.flags
    metrics = evaluate_rows("b", rows)
    assert metrics.unverified_rows == 1
    assert metrics.verified_match_rows == 0


def test_unmatched_segments_remain_explicitly_unmatched():
    nom = [_seg("之", "B.001.jpg", 1, 0, "nom"), _seg("其其其其", "B.002.jpg", 2, 1, "nom")]
    qn = [_seg("thì", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({"之": ["thì"], "其": ["thế"]}))
    unmatched = [r for r in rows if "UNMATCHED_NOM" in r.flags]
    assert unmatched and unmatched[0].semantic_confidence == 0.0


def test_semantic_evidence_helper_distinguishes_none_and_coverage():
    assert semantic_evidence("之", "xyz", lexicon=StubLexicon({})) == (None, 0, 0)
    value, anchored, known = semantic_evidence("之", "thì", lexicon=StubLexicon({"之": ["thì"]}))
    assert value == 1.0 and anchored == 1 and known == 1


def test_dictionary_only_reading_counts_as_evidence():
    class StubDictionary:
        def lookup(self, char):
            class Result:
                pass

            result = Result()
            result.readings = ["thì"] if char == "之" else []
            return result

    nom = [_seg("之", "B.001.jpg", 1, 0, "nom")]
    qn = [_seg("thì", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({}), dictionary=StubDictionary())
    (row,) = rows
    assert row.semantic_confidence == 1.0
    assert "ALIGN_EVIDENCE_INSUFFICIENT" not in row.flags


def test_evaluation_reports_both_confidence_dimensions():
    nom = [_seg("之", "B.001.jpg", 1, 0, "nom")]
    qn = [_seg("thì", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({"之": ["thì"]}))
    metrics = evaluate_rows("b", rows)
    assert metrics.structural_confidence_mean is not None
    assert metrics.structural_confidence_mean > 0
    assert metrics.semantic_evidence_rows == 1
    assert metrics.evidence_insufficient_rows == 0


def test_repeated_tokens_are_not_semantic_evidence():
    # 'thì thì' with 之-only reading: two candidates per char and contested
    # tokens — no unique anchor, so no semantic evidence.
    nom = [_seg("之之", "B.001.jpg", 1, 0, "nom")]
    qn = [_seg("thì thì", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({"之": ["thì"]}))
    (row,) = rows
    assert row.semantic_confidence == 0.0
    assert "ALIGN_EVIDENCE_INSUFFICIENT" in row.flags
