from __future__ import annotations

from hannom.cosegment import qn_sentence_spans

VI = ("Phó con này cho quỷ, đến ngày sau người ấy sinh ra được con trai tốt lành người ta thấy thì mừng và khen. "
       "Song le mẹ nó thì buồn và lo lắng. Nó đến trước mặt quan ấy mà xin.")


def test_spans_are_monotonic_and_non_overlapping():
    spans = qn_sentence_spans(VI)
    assert spans, "expected at least one span"
    for (a, b, _), (c, _, _) in zip(spans, spans[1:]):
        assert b <= c
    for a, b, t in spans:
        assert a < b and t >= 1


def test_spans_split_on_uppercase_vietnamese_after_stop():
    spans = qn_sentence_spans(VI)
    assert len(spans) >= 2


def test_spans_do_not_split_inside_abbreviation():
    text = "Mr. Smith đến. Ông ấy đi."
    spans = qn_sentence_spans(text)
    assert len(spans) == 2
    assert spans[0][0] == 0
    # The "Mr." token belongs to the first sentence, not its own span.
    assert "Smith" in text[spans[0][0]:spans[0][1]]


def test_spans_do_not_split_after_vietnamese_abbreviation():
    text = "Thời tiết Tp. Hồ Chí Minh hôm nay đẹp. Mai ngày mưa."
    spans = qn_sentence_spans(text)
    assert len(spans) == 2
    assert spans[0][1] == len("Thời tiết Tp. Hồ Chí Minh hôm nay đẹp.")


def test_spans_treat_ascii_and_vietnamese_uppercase_equally():
    assert len(qn_sentence_spans("Kết thúc. Đây là câu tiếp.")) == 2
    assert len(qn_sentence_spans("Kết thúc. Đây là câu tiếp. Và thêm.")) == 3


def test_spans_uppercase_class_rejects_non_latin_scripts():
    # Greek and Cyrillic uppercase letters must not trigger sentence splits.
    assert len(qn_sentence_spans("Hết sức bình thường!!!Ω συνηθισμένο. Βλαβερό.")) == 1
    assert len(qn_sentence_spans("Hết sức bình thường!!!Я обычный. Ещё.")) == 1
