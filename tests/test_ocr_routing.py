from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from hannom.config import ApiSettings, BookConfig, OCRSettings, ProjectConfig
from hannom.models import OCRLine, OCRResult, PageRecord
from hannom.ocr.base import OCREngine
from hannom.ocr.router import OCRRouter, page_confidence, sample_page_numbers
from hannom.state import State


class FakeRouter(OCRRouter):
    def __init__(self, *args, local_confidence: float = 0.95, api_error: Exception | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[str] = []
        self.local_confidence = local_confidence
        self.api_error = api_error
        self.saved: list[OCRResult] = []
        self.saved_fallback: list[bool] = []

    def build_engine(self, name: str):
        if name == "api":
            return FakeEngine("api", 0.90, self.calls, error=self.api_error)
        return FakeEngine("local", self.local_confidence, self.calls)

    def load_result(self, page: PageRecord):
        return None

    def save_result(self, result: OCRResult, local_fallback: bool = False):
        self.saved.append(result)
        self.saved_fallback.append(local_fallback)
        return Path("local_fallback.json" if local_fallback else "memory.json")


class FakeEngine(OCREngine):
    def __init__(self, name: str, confidence: float, calls: list[str], error: Exception | None = None):
        self.name = name
        self.confidence = confidence
        self.calls = calls
        self.error = error

    def is_available(self) -> bool:
        return True

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        self.calls.append(self.name)
        if self.error is not None:
            raise self.error
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


def test_consensus_prefers_mean_confidence_over_first_line_fluke():
    from hannom.ocr.agreement import choose_consensus

    folio = OCRLine("- 65 -", ((0, 0), (10, 0), (10, 10), (0, 10)), confidence=0.99)
    folioish2 = OCRLine("雜", ((0, 10), (10, 10), (10, 20), (0, 20)), confidence=0.70)
    folioish3 = OCRLine("亂", ((0, 20), (10, 20), (10, 30), (0, 30)), confidence=0.50)
    paddle = OCRResult(
        book_id="b",
        page_no=1,
        image_name="x.jpg",
        image_sha256="0",
        engine="paddleocr_vl",
        lines=[folio, folioish2, folioish3],
        raw={},
        warnings=[],
        cached=False,
    )
    api_col = OCRLine("𥚇𦓡𠸦德主", ((0, 0), (10, 0), (10, 120), (0, 120)), confidence=0.98)
    api_tail = OCRLine("阿綿", ((0, 120), (10, 120), (10, 140), (0, 140)), confidence=0.99)
    api = OCRResult(
        book_id="b",
        page_no=1,
        image_name="x.jpg",
        image_sha256="0",
        engine="kimhannom",
        lines=[api_col, api_tail],
        raw={},
        warnings=[],
        cached=False,
    )
    best, _ = choose_consensus([paddle, api], "nom", 0.85)
    assert best.engine == "kimhannom", "first-line folio confidence must not outvote mean line confidence"


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


def _seed_vi(state: State, count: int = 20) -> None:
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
                script="qn",
                folder="vi",
            )
        )


def test_api_first_uses_api_and_skips_local(tmp_path: Path):
    project = _router(tmp_path, mode="api_first", sample=0)
    state = State(tmp_path / "state.sqlite3")
    _seed(state)
    router = FakeRouter(project, project.books[0], state, local_confidence=0.95)
    result = router.run_page(state.page("T1_Test", 5))
    assert router.calls == ["api"]
    assert result.raw["routing"]["api_called"] is True
    assert result.raw["routing"]["local_fallback"] is False
    assert router.saved_fallback == [False]
    state.close()


def test_api_first_falls_back_to_local_on_quota(tmp_path: Path):
    from hannom.ocr.quota import QuotaExceeded, QuotaSnapshot

    error = QuotaExceeded(
        "weekly limit",
        3600.0,
        QuotaSnapshot(
            minute=25,
            hour=50,
            day=200,
            week=600,
            limits={"per_minute": 25, "per_hour": 50, "per_day": 200, "per_week": 600},
        ),
    )
    project = _router(tmp_path, mode="api_first", sample=0)
    state = State(tmp_path / "state.sqlite3")
    _seed(state)
    router = FakeRouter(project, project.books[0], state, local_confidence=0.95, api_error=error)
    result = router.run_page(state.page("T1_Test", 5))
    assert router.calls == ["api", "local"]
    assert result.engine == "local"
    assert result.raw["routing"]["api_called"] is False
    assert result.raw["routing"]["local_fallback"] is True
    assert router.saved_fallback == [True]
    state.close()


def test_api_first_falls_back_to_local_when_api_unavailable(tmp_path: Path):
    from hannom.ocr.base import OCRUnavailable

    project = _router(tmp_path, mode="api_first", sample=0)
    state = State(tmp_path / "state.sqlite3")
    _seed(state)
    router = FakeRouter(
        project, project.books[0], state, local_confidence=0.95, api_error=OCRUnavailable("no token")
    )
    result = router.run_page(state.page("T1_Test", 5))
    assert router.calls == ["api", "local"]
    assert result.engine == "local"
    assert router.saved_fallback == [True]
    state.close()


def test_api_first_never_routes_qn_to_api(tmp_path: Path):
    project = _router(tmp_path, mode="api_first", sample=0)
    state = State(tmp_path / "state.sqlite3")
    _seed_vi(state)
    router = FakeRouter(project, project.books[0], state, local_confidence=0.95)
    result = router.run_page(state.page("T1_Test", 5))
    assert router.calls == ["local"]
    assert router.saved_fallback == [False]
    state.close()


def test_load_result_prefers_api_file_over_local_fallback(tmp_path: Path):
    project = _router(tmp_path, mode="api_first", sample=0)
    state = State(tmp_path / "state.sqlite3")
    _seed(state, 1)
    page = state.page("T1_Test", 1)
    router = OCRRouter(project, project.books[0], state)

    def _res(engine: str, text: str) -> OCRResult:
        return OCRResult(
            book_id="T1_Test",
            page_no=1,
            image_name="Test.001.jpg",
            image_sha256=f"{1:064d}",
            engine=engine,
            lines=[
                OCRLine(
                    text,
                    ((0, 0), (10, 0), (10, 10), (0, 10)),
                    confidence=0.9,
                    script="nom",
                )
            ],
            raw={},
            warnings=[],
        )

    router.save_result(_res("paddleocr_vl", "local"), local_fallback=True)
    router.save_result(_res("kimhannom", "api"))
    assert router.load_result(page).engine == "kimhannom"
    assert (router.engine_dir / "0001.json").exists()
    assert (router.engine_dir / "local_fallback" / "0001.json").exists()
    (router.engine_dir / "0001.json").unlink()
    assert router.load_result(page).engine == "paddleocr_vl"
    state.close()
