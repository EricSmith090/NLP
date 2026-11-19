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


def test_segment_without_counterpart_is_absorbed_not_one_sided():
    # v2.4 forbids rows with an empty side (official EMPTY check, FIX_PLAN
    # T3.3): the DP may still prefer the unmatched transition, but the
    # residue is folded into the neighbouring row and flagged for review.
    nom = [
        _seg("之", "B.001.jpg", 1, 0, "nom"),
        _seg("其其其其其其其其", "B.002.jpg", 2, 1, "nom"),
    ]
    qn = [_seg("thì", "B.101.jpg", 1, 0, "qn")]
    rows = align_segments(nom, qn, lexicon=StubLexicon({"之": ["thì"], "其": ["thế"]}))
    assert all(row.ch_txt and row.vi_txt for row in rows)
    assert len(rows) == 1
    (row,) = rows
    assert row.ch_txt == "之其其其其其其其其" and row.vi_txt == "thì"
    assert row.img_id == "B.001.jpg"
    assert "MERGED_ONE_SIDED" in row.flags and "NON_ONE_TO_ONE" in row.flags
    assert row.text_diff is None


def test_unmatched_qn_segment_is_absorbed_not_one_sided():
    nom = [_seg("之", "B.001.jpg", 1, 0, "nom")]
    qn = [
        _seg("thì", "B.101.jpg", 1, 0, "qn"),
        _seg("thế nào mà thấy rõ ràng là vậy đâu", "B.102.jpg", 2, 1, "qn"),
    ]
    rows = align_segments(nom, qn, lexicon=StubLexicon({"之": ["thì"]}))
    assert all(row.ch_txt and row.vi_txt for row in rows)
    (row,) = rows
    assert row.ch_txt == "之" and row.vi_txt.startswith("thì") and "thế nào" in row.vi_txt
    assert "MERGED_ONE_SIDED" in row.flags
    assert row.text_diff is None


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
    # The DP took the unmatched transition; the residue was absorbed (no
    # one-sided row) and the row says so.
    assert any("MERGED_ONE_SIDED" in row.flags for row in rows)
    assert all(row.ch_txt and row.vi_txt for row in rows)
    # With punitive skip costs the DP falls back to a forced correspondence.
    cfg = AlignConfig(unmatched_nom_penalty=1000.0, unmatched_qn_penalty=1000.0)
    rows = align_segments(nom, qn, config=cfg, lexicon=StubLexicon({"之": ["thì"], "其": ["khing"]}))
    assert not any("MERGED_ONE_SIDED" in row.flags for row in rows)


def test_charalign_pairs_with_an_empty_side_are_folded():
    from hannom.align import absorb_one_sided_segments

    nom = [
        _seg("天主", "B.276.jpg", 276, 0, "nom"),
        _seg("", "B.276.jpg", 276, 1, "nom"),
        _seg("聖神", "B.276.jpg", 276, 2, "nom"),
    ]
    qn = [
        _seg("Thiên Chúa.", "B.013.jpg", 13, 0, "qn"),
        _seg("Hoặc có kẻ hỏi rằng:", "B.013.jpg", 13, 1, "qn"),
        _seg("Thánh Thần.", "B.013.jpg", 13, 2, "qn"),
    ]
    n2, q2 = absorb_one_sided_segments(nom, qn)
    assert [s.text for s in n2] == ["天主", "聖神"]
    assert [s.text for s in q2] == ["Thiên Chúa. Hoặc có kẻ hỏi rằng:", "Thánh Thần."]
    assert "MERGED_ONE_SIDED" in q2[0].flags
    # a leading one-sided pair folds forward; limit of 3 sentences per side
    n3, q3 = absorb_one_sided_segments(nom[1:], qn[1:])
    assert [s.text for s in n3] == ["聖神"] and q3[0].text == "Hoặc có kẻ hỏi rằng: Thánh Thần."
    full = [_seg("x", "B.1.jpg", 1, i, "nom") for i in range(3)] + [_seg("", "B.1.jpg", 1, 3, "nom")]
    fq = [_seg(f"s{i}.", "B.9.jpg", 9, i, "qn") for i in range(4)]
    n4, q4 = absorb_one_sided_segments(full, fq, max_side=1)
    # over the limit: merged anyway (no empty cell), flagged for review
    assert len(n4) == 3 and q4[-1].text == "s2. s3." and "MERGED_OVER_LIMIT" in q4[-1].flags
    # a lone one-sided pair has no neighbour: kept and flagged
    n5, q5 = absorb_one_sided_segments(nom[1:2], qn[1:2])
    assert len(n5) == 1 and "ONE_SIDED_UNRESOLVED" in n5[0].flags


def test_skip_penalties_are_configurable():
    cfg = AlignConfig(unmatched_nom_penalty=3.0, unmatched_qn_penalty=3.0)
    assert cfg.unmatched_nom_penalty == 3.0
    assert cfg.unmatched_qn_penalty == 3.0
