"""Vintern-1B-v3.5 adapter helpers (no GPU needed) and OCR flag replacement."""

from pathlib import Path

from PIL import Image

from hannom.models import OCRLine, OCRResult, PageRecord
from hannom.ocr.base import OCREngine
from hannom.ocr.local_vintern import (
    Vintern35Engine,
    VinternEngine,
    needs_retry,
    prefer_retry,
    qn_text_quality,
    stitch_overlapping,
    strip_meta_lines,
)
from hannom.ocr.router import OCRRouter
from hannom.state import State

from test_ocr_warning_propagation import _project


def test_quality_counts_loop_once():
    sent = "Ngày thứ nhất ban sớm mai ngắm về sự cấm phòng là thể nào"
    q = qn_text_quality(" ".join([sent] * 6))
    assert q["syllables"] == 14 * 6
    assert q["rep8"] >= 4
    assert q["effective"] < 14 * 2
    clean = qn_text_quality(sent)
    assert clean == {"syllables": 14, "effective": 14, "rep8": 1}


def test_strip_meta_lines_only_whole_lines():
    text = "Phần văn bản được nhận dạng là:\nKẻ nói nhiều lời chẳng khỏi tội.\n```\nvăn bản này dạy rằng"
    out, n = strip_meta_lines(text)
    assert n == 2
    assert out == "Kẻ nói nhiều lời chẳng khỏi tội.\nvăn bản này dạy rằng"
    assert strip_meta_lines("- 25 - (260)\nNgày thứ nhất")[1] == 0


def test_stitch_removes_overlap_and_keeps_short_coincidence():
    a = "một hai ba bốn năm sáu bảy"
    b = "năm sáu bảy tám chín"
    assert stitch_overlapping([a, b]) == "một hai ba bốn năm sáu bảy tám chín"
    # an overlap shorter than 3 words is not trusted
    assert stitch_overlapping(["a b c", "b c d"]) == "a b c b c d"


def test_retry_policy():
    short = {"syllables": 3, "effective": 3, "rep8": 0}
    good = {"syllables": 230, "effective": 230, "rep8": 1}
    loop = {"syllables": 1800, "effective": 120, "rep8": 40}
    assert needs_retry(short, 0) and needs_retry(loop, 0) and needs_retry(good, 1)
    assert not needs_retry(good, 0)
    assert prefer_retry(short, good)
    assert prefer_retry(loop, good)
    assert not prefer_retry(good, loop)
    assert not prefer_retry(good, {"syllables": 240, "effective": 240, "rep8": 1})


def test_engine_config_matches_benchmark():
    e = Vintern35Engine()
    assert e.name == "vintern_1b_v3_5"
    assert (e.max_num, e.num_beams, e.repetition_penalty, e.use_flash_attn) == (6, 3, 2.5, False)
    assert e.revision == "b98f263eab246eb5269ade64edbdca8a887dc44d"
    v2 = VinternEngine()
    assert (v2.max_num, v2.num_beams, v2.repetition_penalty, v2.use_flash_attn) == (12, 1, 1.2, None)


def test_load_image_honours_max_num(tmp_path):
    p = tmp_path / "page.png"
    Image.new("RGB", (800, 613), "white").save(p)
    # 800x613 half page: 6 tiles max -> 3x2 grid + thumbnail; 12 -> 4x3 + thumbnail
    assert VinternEngine._load_image(str(p), 6).shape[0] == 7
    assert VinternEngine._load_image(str(p), 12).shape[0] == 13
    full = tmp_path / "full.png"
    Image.new("RGB", (800, 1135), "white").save(full)
    assert VinternEngine._load_image(str(full), 6).shape[0] == 7
    assert VinternEngine._load_image(str(full), 24).shape[0] == 7


class _Fresh(OCREngine):
    name = "vintern_1b_v3_5"

    def is_available(self) -> bool:
        return True

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        return OCRResult(
            book_id=page.book_id, page_no=page.page_no, image_name=page.image_name,
            image_sha256=page.sha256, engine=self.name,
            lines=[OCRLine("Sửa Lưới", ((0, 0), (10, 0), (10, 10), (0, 10)), None, script)],
            raw={}, warnings=[],
        )


class _FreshRouter(OCRRouter):
    def build_engine(self, name: str):
        return _Fresh()

    def load_result(self, page: PageRecord):
        return None


def test_fresh_ocr_replaces_stale_ocr_flags_only(tmp_path):
    project = _project(tmp_path)
    state = State(tmp_path / "state.sqlite3")
    state.upsert_page(PageRecord(
        book_id="T1_Test", page_no=1, image_name="Test.001.jpg", pdf_page=1, sha256="0" * 64,
        width=800, height=1135, path=Path("Test.001.jpg"), script="qn", folder="vi",
        review_flags=["BAND_RETRY_AFTER_FULLPAGE_FAILURE", "OCR_EMPTY", "PAGE_NUMBER_REMOVED"],
    ))
    _FreshRouter(project, project.books[0], state).run_page(state.page("T1_Test", 1), force=True)
    flags = state.page("T1_Test", 1).review_flags
    assert "BAND_RETRY_AFTER_FULLPAGE_FAILURE" not in flags and "OCR_EMPTY" not in flags
    assert "PAGE_NUMBER_REMOVED" in flags
    state.close()


def test_trim_loop_keeps_text_before_second_cycle():
    from hannom.ocr.local_vintern import trim_loop

    head = "Kẻ nói nhiều lời chẳng khỏi tội đâu.\nVì chung lưỡi ta"
    cycle = " là giống Đức Chúa Trời sinh ra mà cầm lưỡi, kẻo cắn ai."
    text, cut = trim_loop(head + cycle * 5)
    assert cut
    assert text == (head + cycle).rstrip()
    assert "\n" in text  # original line breaks are kept
    clean = head + cycle
    assert trim_loop(clean) == (clean, False)
