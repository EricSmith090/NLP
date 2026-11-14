"""Unmatched-segment transitions in the alignment DP (Issue B)."""

from __future__ import annotations

from hannom.align import AlignConfig, TextSegment, align_segments


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


def test_reliable_one_to_one_alignment_still_works():
    nom = [_seg("之", "B.001.jpg", 1, 0, "nom")]
    qn = [_seg("thì", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({"之": ["thì"]}))
    assert len(rows) == 1
    assert "ALIGNED" in rows[0].flags
    assert "NON_ONE_TO_ONE" not in rows[0].flags
    assert rows[0].text_diff == []  # matched identity; not unverified
    assert rows[0].confidence > 0.9


def test_segment_without_counterpart_stays_unmatched():
    nom = [
        _seg("之", "B.001.jpg", 1, 0, "nom"),
        _seg("其其其其其其其其", "B.002.jpg", 2, 1, "nom"),
    ]
    qn = [_seg("thì", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({"之": ["thì"], "其": ["thế"]}))
    nom_rows = [row for row in rows if row.ch_txt == "之"]
    unmatched = [row for row in rows if "UNMATCHED_NOM" in row.flags]
    assert nom_rows and nom_rows[0].vi_txt == "thì"
    assert unmatched and unmatched[0].ch_txt == "其其其其其其其其"
    assert unmatched[0].vi_txt == ""
    assert unmatched[0].text_diff is None
    assert "NON_ONE_TO_ONE" in unmatched[0].flags


def test_unmatched_qn_segment_stays_unmatched():
    nom = [_seg("之", "B.001.jpg", 1, 0, "nom")]
    qn = [
        _seg("thì", "B.101.jpg", 1, 0, "qn"),
        _seg("thế nào mà thấy rõ ràng là vậy đâu", "B.102.jpg", 2, 1, "qn"),
    ]
    rows = align_segments(nom, qn, lexicon=StubLexicon({"之": ["thì"]}))
    unmatched = [row for row in rows if "UNMATCHED_QN" in row.flags]
    assert unmatched and "thế nào" in unmatched[0].vi_txt
    assert unmatched[0].ch_txt == ""
    assert unmatched[0].text_diff is None


def test_one_to_many_is_flagged_and_not_scored():
    nom = [_seg("之其", "B.001.jpg", 1, 0, "nom")]
    qn = [_seg("thì", "B.101.jpg", 1, 0, "qn"), _seg("thế", "B.102.jpg", 2, 1, "qn")]
    cfg = AlignConfig(unmatched_nom_penalty=1000.0, unmatched_qn_penalty=1000.0)
    rows = align_segments(nom, qn, config=cfg, lexicon=StubLexicon({"之": ["thì"], "其": ["thế"]}))
    assert len(rows) == 1
    assert "ALIGNED_ONE_TO_MANY" in rows[0].flags
    assert "NON_ONE_TO_ONE" in rows[0].flags
    assert rows[0].text_diff is None


def test_many_to_many_ambiguity_is_flagged():
    nom = [_seg("字字字字字", "B.001.jpg", 1, 0, "nom"), _seg("字字", "B.002.jpg", 2, 1, "nom")]
    qn = [_seg("từ từ từ", "B.101.jpg", 1, 0, "qn"), _seg("từ", "B.102.jpg", 2, 1, "qn")]
    cfg = AlignConfig(
        many_to_many_penalty=0.0,
        one_to_many_penalty=100.0,
        many_to_one_penalty=100.0,
        unmatched_nom_penalty=1000.0,
        unmatched_qn_penalty=1000.0,
    )
    rows = align_segments(nom, qn, config=cfg)
    assert len(rows) == 1
    assert "ALIGNED_MANY_TO_MANY" in rows[0].flags
    assert "NON_ONE_TO_ONE" in rows[0].flags
    assert rows[0].text_diff is None


def test_unmatched_transition_preferred_over_forced_correspondence():
    # Five Nôm chars against three QN tokens: forcing a 1-1 grouping costs
    # longer than leaving the residue unmatched.
    nom = [
        _seg("之", "B.001.jpg", 1, 0, "nom"),
        _seg("其其其其", "B.002.jpg", 2, 1, "nom"),
    ]
    qn = [_seg("thì", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({"之": ["thì"], "其": ["khing"]}))
    assert any("UNMATCHED_NOM" in row.flags for row in rows)
    # With punitive skip costs the DP falls back to a forced correspondence.
    cfg = AlignConfig(unmatched_nom_penalty=1000.0, unmatched_qn_penalty=1000.0)
    rows = align_segments(nom, qn, config=cfg, lexicon=StubLexicon({"之": ["thì"], "其": ["khing"]}))
    assert not any("UNMATCHED_NOM" in row.flags for row in rows)


def test_skip_penalties_are_configurable():
    cfg = AlignConfig(unmatched_nom_penalty=3.0, unmatched_qn_penalty=3.0)
    assert cfg.unmatched_nom_penalty == 3.0
    assert cfg.unmatched_qn_penalty == 3.0
