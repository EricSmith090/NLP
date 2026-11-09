"""OCR warning propagation into page review metadata (Issue G)."""

from __future__ import annotations

from pathlib import Path

from hannom.config import ApiSettings, BookConfig, OCRSettings, ProjectConfig
from hannom.models import OCRLine, OCRResult, PageRecord
from hannom.ocr.base import OCREngine
from hannom.ocr.router import OCRRouter, promote_review_flags
from hannom.state import State


def test_band_retry_warning_is_promoted():
    flags = promote_review_flags(["BAND_RETRY_AFTER_FULLPAGE_FAILURE"], [])
    assert "BAND_RETRY_AFTER_FULLPAGE_FAILURE" in flags


def test_existing_and_new_propagations_coexist():
    flags = promote_review_flags(
        ["OCR_ENGINE_DISAGREE:kimhannom:vintern:0.31", "BAND_RETRY_AFTER_FULLPAGE_FAILURE"],
        ["PREEXISTING"],
    )
    assert "PREEXISTING" in flags
    assert "OCR_ENGINE_DISAGREE" in flags
    assert "BAND_RETRY_AFTER_FULLPAGE_FAILURE" in flags


def test_duplicate_codes_are_not_repeated():
    flags = promote_review_flags(
        ["BAND_RETRY_AFTER_FULLPAGE_FAILURE", "BAND_RETRY_AFTER_FULLPAGE_FAILURE"], []
    )
    assert flags.count("BAND_RETRY_AFTER_FULLPAGE_FAILURE") == 1


def test_unrelated_warnings_are_not_promoted():
    assert promote_review_flags(["UNRELATED_WARNING:x"], []) == []


class _BandRetryEngine(OCREngine):
    name = "vintern_1b_v2"

    def is_available(self) -> bool:
        return True

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        return OCRResult(
            book_id=page.book_id,
            page_no=page.page_no,
            image_name=page.image_name,
            image_sha256=page.sha256,
            engine=self.name,
            lines=[
                OCRLine(
                    "Sửa Lưới",
                    ((0, 0), (10, 0), (10, 10), (0, 10)),
                    None,
                    script,
                )
            ],
            raw={"band_retry": True},
            warnings=["BAND_RETRY_AFTER_FULLPAGE_FAILURE"],
        )


class _BandRetryRouter(OCRRouter):
    def build_engine(self, name: str):
        return _BandRetryEngine()

    def load_result(self, page: PageRecord):
        return None


def _project(tmp_path: Path) -> ProjectConfig:
    ocr = OCRSettings(nom=("local",), quoc_ngu=("local",), api_mode="local_only")
    book = BookConfig(
        book_id="T1_Test",
        pdf=tmp_path / "Test.pdf",
        layout="T1",
        expected_pages=1,
        nom_start_hint=1,
        nom_end_hint=1,
        translation_start=2,
        translation_end=1,
        ocr=ocr,
    )
    return ProjectConfig(
        root=tmp_path,
        project_name="test",
        deadline="",
        zip_stem="test",
        report_name="test_report.pdf",
        one_zip_for_all_books=True,
        data_dir=tmp_path / "data",
        artifacts_dir=tmp_path / "artifacts",
        output_dir=tmp_path / "out",
        dictionaries_dir=tmp_path / "dict",
        models_dir=tmp_path / "models",
        books=(book,),
        api=ApiSettings(
            base_url="https://example.invalid",
            token_env="TOKEN",
            user_agent="test",
            limits={"per_minute": 25, "per_hour": 50, "per_day": 200, "per_week": 600},
        ),
        quality={"minimum_similarity": 95.0},
        ocr_config={"engines": {"local": {"kind": "mock"}}, "routing": {}},
    )


def test_page_review_flags_retain_band_retry(tmp_path):
    project = _project(tmp_path)
    state = State(tmp_path / "state.sqlite3")
    state.upsert_page(
        PageRecord(
            book_id="T1_Test",
            page_no=1,
            image_name="Test.001.jpg",
            pdf_page=1,
            sha256="0" * 64,
            width=800,
            height=1135,
            path=Path("Test.001.jpg"),
            script="qn",
            folder="vi",
        )
    )
    router = _BandRetryRouter(project, project.books[0], state)
    router.run_page(state.page("T1_Test", 1))
    page = state.page("T1_Test", 1)
    assert "BAND_RETRY_AFTER_FULLPAGE_FAILURE" in page.review_flags
    state.close()
