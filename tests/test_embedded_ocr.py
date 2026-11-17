"""Embedded-OCR (2-call) flow: structure-classification carries the full
image-ocr payload; the client must reuse it instead of calling image-ocr
when ``api.embedded_ocr`` is enabled, and fall back to image-ocr otherwise.
"""

from __future__ import annotations

from pathlib import Path

from hannom.config import ApiSettings, BookConfig, OCRSettings, ProjectConfig
from hannom.models import PageRecord
from hannom.ocr.kimhannom import ApiResponse, KimHanNomClient
from hannom.state import State

TOKEN_ENV = "HANNOM_TEST_EMBEDDED_TOKEN"


def _project(tmp_path: Path, *, embedded_ocr: bool) -> ProjectConfig:
    ocr = OCRSettings(nom=("embedded",), quoc_ngu=("local",), api_mode="always")
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
            token_env=TOKEN_ENV,
            user_agent="test",
            limits={"per_minute": 25, "per_hour": 50, "per_day": 10000, "per_week": 600},
            embedded_ocr=embedded_ocr,
        ),
        quality={"minimum_similarity": 95.0},
        ocr_config={"engines": {"embedded": {"kind": "api"}}, "routing": {}},
    )


def _page(tmp_path: Path, sha256: str = "a" * 64) -> PageRecord:
    return PageRecord(
        book_id="T1_Test",
        page_no=1,
        image_name="Test.001.jpg",
        pdf_page=1,
        sha256=sha256,
        width=800,
        height=1135,
        path=Path(tmp_path / "Test.001.jpg"),
        script="nom",
        folder="ch",
    )


BOX1 = [[624.0, 965.0], [646.0, 965.0], [646.0, 995.0], [624.0, 995.0]]
BOX2 = [[291.0, 154.0], [317.0, 154.0], [318.0, 526.0], [292.0, 526.0]]


def _classify_payload(*, with_embedded: bool) -> dict:
    payload = {
        "ocr_id": 1,
        "lang_type": 2,
        "reading_direction": 1,
        "is_sino_nom": True,
        "doc_type": 6,
    }
    if with_embedded:
        payload["result"] = {
            "result_file_name": "temp_embedded.jpg",
            "result_ocr_text": ["汉", "祭靈魂"],
            "result_bbox": [
                [BOX1, ["汉", 0.9004]],
                [BOX2, ["祭靈魂", 0.9602]],
            ],
            "details": {
                "file_name": "",
                "details": [
                    {"transcription": "汉", "points": BOX1, "difficult": False},
                    {"transcription": "祭靈魂", "points": BOX2, "difficult": True},
                ],
            },
        }
    return payload


def _image_ocr_response() -> ApiResponse:
    data = {
        "result_file_name": "temp_image_ocr.jpg",
        "result_ocr_text": ["独", "立调用"],
        "result_bbox": [
            [BOX1, ["独", 0.5]],
            [BOX2, ["立调用", 0.6]],
        ],
        "details": {
            "file_name": "",
            "details": [
                {"transcription": "独", "points": BOX1, "difficult": False},
                {"transcription": "立调用", "points": BOX2, "difficult": False},
            ],
        },
    }
    return ApiResponse(endpoint="image-ocr", data=data, raw={"code": "000000"}, cached=False)


def _client(tmp_path, monkeypatch, *, embedded_ocr, with_embedded):
    monkeypatch.setenv(TOKEN_ENV, "dummy-token")
    project = _project(tmp_path, embedded_ocr=embedded_ocr)
    project.data_dir.mkdir(parents=True, exist_ok=True)
    state = State(project.data_dir / "state.sqlite3")
    client = KimHanNomClient(project, state)
    monkeypatch.setattr(client, "upload", lambda *a, **k: "temp_fake.jpg")
    monkeypatch.setattr(
        client,
        "classify",
        lambda *a, **k: ApiResponse(
            endpoint="structure-classification",
            data=_classify_payload(with_embedded=with_embedded),
            raw={"code": "000000"},
            cached=False,
        ),
    )
    return client


def test_embedded_result_reused_and_image_ocr_not_called(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, embedded_ocr=True, with_embedded=True)

    def _boom(*a, **k):
        raise AssertionError("image-ocr must not be called when embedded payload exists")

    monkeypatch.setattr(client, "ocr", _boom)
    result = client.recognize_page(_page(tmp_path), "nom")

    assert [ln.text for ln in result.lines] == ["汉", "祭靈魂"]
    assert [ln.confidence for ln in result.lines] == [0.9004, 0.9602]
    assert [ln.difficult for ln in result.lines] == [False, True]
    assert result.raw["source"] == "structure-classification.embedded"


def test_embedded_disabled_calls_image_ocr(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, embedded_ocr=False, with_embedded=True)
    calls = []
    monkeypatch.setattr(client, "ocr", lambda *a, **k: calls.append((a, k)) or _image_ocr_response())
    result = client.recognize_page(_page(tmp_path), "nom")

    assert calls, "image-ocr must be called when embedded_ocr is disabled"
    assert [ln.text for ln in result.lines] == ["独", "立调用"]


def test_embedded_absent_falls_back_to_image_ocr(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, embedded_ocr=True, with_embedded=False)
    calls = []
    monkeypatch.setattr(client, "ocr", lambda *a, **k: calls.append((a, k)) or _image_ocr_response())
    result = client.recognize_page(_page(tmp_path), "nom")

    assert calls, "image-ocr must be the fallback when no embedded payload is present"
    assert [ln.text for ln in result.lines] == ["独", "立调用"]
