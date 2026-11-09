from __future__ import annotations

from hannom.cosegment import PageUnit, stream_cosegment

NOM = "付𡥵尼朱鬼典𣈜𢖖𠊛𧘇生𦋦特𡥵𤳇卒𫅜𠊛些𧡊時𢜠麻𠸦雙離媄奴時盆連爲汝𠳒𣈜𠠩典𣈜繩𧘇㐌𢀲𢧚𨑮𠄩歲時鬼現旦共媄奴𦓡𠳨浪𡥵眉㐌付"
VI = (
    "Phó con này cho quỷ, đến ngày sau người ấy sinh ra được con trai tốt lành người ta thấy thì mừng và khen. "
    "Song le mẹ nó thì buồn và lo lắng. Nó đến trước mặt quan ấy mà xin."
)


def test_stream_cosegment_produces_matching_lists():
    nom_units = [PageUnit("T.001.jpg", NOM)]
    qn_units = [PageUnit("T.002.jpg", VI)]
    stream = stream_cosegment(nom_units, qn_units)
    assert stream is not None
    nom_segs, qn_segs = stream
    assert len(nom_segs) == len(qn_segs) >= 2
    # Every Nôm character is preserved in order
    joined_nom = "".join(s.text for s in nom_segs).replace(" ", "")
    assert joined_nom == NOM.replace(" ", "")
    # Ordering index matches list position
    assert [s.order_no for s in nom_segs] == list(range(len(nom_segs)))
    assert [s.order_no for s in qn_segs] == list(range(len(qn_segs)))


def test_stream_cosegment_spans_page():
    half = len(NOM) // 2
    nom_units = [PageUnit("T.001.jpg", NOM[:half]), PageUnit("T.002.jpg", NOM[half:])]
    qn_units = [PageUnit("T.003.jpg", VI)]
    stream = stream_cosegment(nom_units, qn_units)
    assert stream is not None
    nom_segs, qn_segs = stream
    assert len(nom_segs) == len(qn_segs)
    # Text still matches across the page break
    joined_nom = "".join(s.text for s in nom_segs).replace(" ", "")
    assert joined_nom == NOM.replace(" ", "")


def test_stream_cosegment_rejects_insufficient_input():
    stream = stream_cosegment([PageUnit("T.001.jpg", "短")], [PageUnit("T.003.jpg", VI)])
    assert stream is None
    stream = stream_cosegment([], [PageUnit("T.003.jpg", VI)])
    assert stream is None
    stream = stream_cosegment([PageUnit("T.001.jpg", NOM)], [])
    assert stream is None


def test_stream_cosegment_page_attribution():
    nom_units = [
        PageUnit("T.001.jpg", NOM[: len(NOM) // 2]),
        PageUnit("T.002.jpg", NOM[len(NOM) // 2 :]),
    ]
    qn_units = [
        PageUnit("T.003.jpg", VI[: len(VI) // 3]),
        PageUnit("T.004.jpg", VI[len(VI) // 3 :]),
    ]
    stream = stream_cosegment(nom_units, qn_units)
    assert stream is not None
    nom_segs, qn_segs = stream
    all_names = {name for s in nom_segs for name in s.image_names}
    assert {"T.001.jpg", "T.002.jpg"} <= all_names
