from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from hannom.config import ApiSettings, BookConfig, OCRSettings, ProjectConfig
from hannom.models import OCRLine, OCRResult, PageRecord
from hannom.ocr.base import OCREngine
from hannom.ocr.router import OCRRouter, page_confidence, sample_page_numbers
from hannom.state import State


class FakeEngine(OCREngine):
    def __init__(self, name: str, confidence: float, calls: list[str]):
        self.name = name
        self.confidence = confidence
        self.calls = calls

    def is_available(self) -> bool:
        return True

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        self.calls.append(self.name)
        return OCRResult(
            book_id=page.book_id,
            page_no=page.page_no,
            image_name=page.image_name,
            image_sha256=page.sha256,
            engine=self.name,
            lines=[
                OCRLine(
                    text="字",
                    points=((0, 0), (10, 0), (10, 10), (0, 10)),
                    confidence=self.confidence,
                    script=script,
                )
            ],
        )


class FakeRouter(OCRRouter):
    def __init__(self, *args, local_confidence: float = 0.95, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[str] = []
        self.local_confidence = local_confidence
        self.saved: list[OCRResult] = []

    def build_engine(self, name: str):
        if name == "api":
            return FakeEngine("api", 0.90, self.calls)
        return FakeEngine("local", self.local_confidence, self.calls)

    def load_result(self, page: PageRecord):
        return None

    def save_result(self, result: OCRResult):
        self.saved.append(result)
        return Path("memory.json")


def _project(tmp_path: Path, ocr: OCRSettings) -> ProjectConfig:
    book = BookConfig(
        book_id="T1_Test",
        pdf=tmp_path / "Test.pdf",
        layout="T1",
        expected_pages=20,
        nom_start_hint=1,
        nom_end_hint=20,
        translation_start=21,
        translation_end=20,
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
        ocr_config={
            "engines": {
                "local": {"kind": "local"},
                "api": {"kind": "api"},
            },
            "routing": {
                "nom": {"low_confidence_threshold": 0.70, "agreement_threshold": 0.85},
                "quoc_ngu": {"low_confidence_threshold": 0.75, "agreement_threshold": 0.85},
            },
        },
    )


def _seed(state: State, count: int = 20) -> None:
    for page_no in range(1, count + 1):
        state.upsert_page(
            PageRecord(
                book_id="T1_Test",
                page_no=page_no,
                image_name=f"Test.{page_no:03d}.jpg",
                pdf_page=page_no,
                sha256=f"{page_no:064d}",
                width=800,
                height=1135,
                path=Path(f"Test.{page_no:03d}.jpg"),
                script="nom",
                folder="ch",
            )
        )


def _router(tmp_path: Path, *, mode: str, sample: int, confidence: float = 0.95):
    ocr = OCRSettings(
        nom=("local", "api"),
        quoc_ngu=("local",),
        api_mode=mode,
        sample_pages=sample,
    )
    return _project(tmp_path, ocr)


def test_sample_pages_are_stratified():
    assert sample_page_numbers(range(1, 21), 3) == {1, 10, 20}
    assert sample_page_numbers(range(1, 21), 0) == set()
    assert sample_page_numbers(range(1, 21), 100) == set(range(1, 21))


def test_high_confidence_unsampled_page_skips_api(tmp_path: Path):
    project = _router(tmp_path, mode="sample_then_low_confidence", sample=3)
    state = State(tmp_path / "state.sqlite3")
    _seed(state)
    router = FakeRouter(project, project.books[0], state, local_confidence=0.95)
    result = router.run_page(state.page("T1_Test", 5))
    assert router.calls == ["local"]
    assert result.raw["routing"]["api_called"] is False
    state.close()


def test_sampled_page_calls_api(tmp_path: Path):
    project = _router(tmp_path, mode="sample_then_low_confidence", sample=3)
    state = State(tmp_path / "state.sqlite3")
    _seed(state)
    router = FakeRouter(project, project.books[0], state, local_confidence=0.95)
    result = router.run_page(state.page("T1_Test", 10))
    assert router.calls == ["local", "api"]
    assert result.raw["routing"]["api_called"] is True
    state.close()


def test_low_confidence_page_calls_api(tmp_path: Path):
    project = _router(tmp_path, mode="sample_then_low_confidence", sample=3)
    state = State(tmp_path / "state.sqlite3")
    _seed(state)
    router = FakeRouter(project, project.books[0], state, local_confidence=0.40)
    router.run_page(state.page("T1_Test", 5))
    assert router.calls == ["local", "api"]
    state.close()


def test_local_only_mode_never_calls_api(tmp_path: Path):
    project = _router(tmp_path, mode="local_only", sample=3)
    state = State(tmp_path / "state.sqlite3")
    _seed(state)
    router = FakeRouter(project, project.books[0], state, local_confidence=0.10)
    router.run_page(state.page("T1_Test", 10))
    assert router.calls == ["local"]
    state.close()


def test_explicit_engine_override_calls_api(tmp_path: Path):
    project = _router(tmp_path, mode="local_only", sample=3)
    state = State(tmp_path / "state.sqlite3")
    _seed(state)
    router = FakeRouter(project, project.books[0], state, local_confidence=0.95)
    router.run_page(state.page("T1_Test", 5), engines=["api"])
    assert router.calls == ["api"]
    state.close()


def test_page_confidence_is_mean_of_lines():
    result = OCRResult(
        book_id="b",
        page_no=1,
        image_name="x.jpg",
        image_sha256="0",
        engine="e",
        lines=[
            OCRLine("a", ((0, 0),) * 4, confidence=0.8),
            OCRLine("b", ((0, 0),) * 4, confidence=0.4),
        ],
    )
    assert page_confidence([result]) == pytest.approx(0.6)
