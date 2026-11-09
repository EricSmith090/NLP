from __future__ import annotations

from hannom.cosegment import cosegment_pair, qn_sentence_spans

NOM = "付𡥵尼朱鬼典𣈜𢖖𠊛𧘇生𦋦特𡥵𤳇卒𫅜𠊛些𧡊時𢜠麻𠸦雙離媄奴時盆連爲汝𠳒𣈜𠠩典𣈜繩𧘇㐌𢀲𢧚𨑮𠄩歲時鬼現旦共媄奴𦓡𠳨浪𡥵眉㐌付朱蚤𢆥"
VI = ("Phó con này cho quỷ, đến ngày sau người ấy sinh ra được con trai tốt lành người ta thấy thì mừng và khen. "
       "Song le mẹ nó thì buồn và lo lắng. Nó đến trước mặt quan ấy mà xin.")

def test_spans_are_monotonic_and_non_overlapping():
    spans = qn_sentence_spans(VI)
    assert spans, "expected at least one span"
    for (a, b, _), (c, _, _) in zip(spans, spans[1:]):
        assert b <= c
    for a, b, t in spans:
        assert a < b and t >= 1


def test_cosegment_pairs_are_in_order_and_cover_all_text():
    pairs = cosegment_pair(NOM, VI)
    assert pairs, "expected 1-1 chunks"
    joined_nom = "".join(n for n, _ in pairs)
    # every Nôm character is preserved in order
    assert joined_nom.replace(" ", "") == NOM.replace(" ", "")
    assert len(pairs) >= 2


def test_cosegment_falls_back_on_garbage_input():
    assert cosegment_pair("", VI) is None
    assert cosegment_pair("短", VI) is None
    assert cosegment_pair(NOM, "no punctuation anywhere in this string and it is long enough to fail structurally") is None


def test_cosegment_expands_to_at_least_two_chunks_for_realistic_input():
    out = cosegment_pair(NOM, VI)
    assert out is not None
    assert len(out) >= 2
