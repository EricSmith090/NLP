"""Tests for the OCR run options: --only, wait_on_quota, classify=False."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from hannom import cli
from hannom.config import OCRSettings
from hannom.models import PageRecord
from hannom.ocr import kimhannom as kim_module
from hannom.ocr.kimhannom import ApiResponse, KimHanNomClient
from hannom.ocr.quota import QuotaExceeded, QuotaSnapshot
from hannom.state import State

from test_ocr_routing import _project, _seed


def _page(folder: str, page_no: int):
    return SimpleNamespace(folder=folder, page_no=page_no)


def test_filter_pages_by_script_keeps_only_requested_folders():
    pages = [_page("intro", 1), _page("vi", 9), _page("toc", 541), _page("ch", 277), _page("blank", 276)]
    assert [p.page_no for p in cli.filter_pages_by_script(pages, "nom")] == [277]
    assert [p.page_no for p in cli.filter_pages_by_script(pages, "qn")] == [1, 9, 541]


def _client(tmp_path: Path, **api_overrides) -> tuple[KimHanNomClient, State]:
    project = _project(tmp_path, OCRSettings(nom=("api",), quoc_ngu=("local",)))
    project = replace(project, api=replace(project.api, min_delay_seconds=0, **api_overrides))
    state = State(tmp_path / "state.sqlite3")
    return KimHanNomClient(project, state, token="test-token"), state


def _quota_error() -> QuotaExceeded:
    snap = QuotaSnapshot(minute=0, hour=50, day=50, week=50, limits={})
    return QuotaExceeded("quota reached for: hour", retry_after=12.0, snapshot=snap)


def test_quota_full_stops_by_default(tmp_path: Path, monkeypatch):
    client, state = _client(tmp_path)
    monkeypatch.setattr(client.ledger, "check", lambda: (_ for _ in ()).throw(_quota_error()))
    with pytest.raises(QuotaExceeded):
        client._check_quota()
    state.close()


def test_wait_on_quota_sleeps_then_resumes(tmp_path: Path, monkeypatch):
    client, state = _client(tmp_path, wait_on_quota=True)
    outcomes = [_quota_error(), None]

    def check():
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome

    sleeps: list[float] = []
    monkeypatch.setattr(client.ledger, "check", check)
    monkeypatch.setattr(kim_module.time, "sleep", sleeps.append)
    client._check_quota()
    assert sleeps == [17.0]  # retry_after 12 s + 5 s margin
    assert outcomes == []
    state.close()


def _stub_api(client: KimHanNomClient, monkeypatch, calls: list[str]):
    monkeypatch.setattr(client, "upload", lambda path, sha, force=False: calls.append("upload") or "tmp.jpg")

    def classify(file_name, sha):
        calls.append("classify")
        return ApiResponse("structure-classification", {"ocr_id": 2, "reading_direction": 1}, {})

    def ocr(file_name, sha, **kwargs):
        calls.append(f"ocr:{kwargs['ocr_id']}:{kwargs['lang_type']}:{kwargs['reading_direction']}")
        return ApiResponse("image-ocr", {"result_ocr_text": [], "result_bbox": []}, {})

    monkeypatch.setattr(client, "classify", classify)
    monkeypatch.setattr(client, "ocr", ocr)


def test_classify_true_keeps_original_three_calls(tmp_path: Path, monkeypatch):
    client, state = _client(tmp_path)
    _seed(state, count=1)
    calls: list[str] = []
    _stub_api(client, monkeypatch, calls)
    client.recognize_page(state.page("T1_Test", 1), "nom")
    assert calls == ["upload", "classify", "ocr:2:2:1"]
    state.close()


def test_classify_false_skips_classification_and_uses_fixed_layout(tmp_path: Path, monkeypatch):
    client, state = _client(tmp_path, classify=False, fixed_ocr_id=1, fixed_reading_direction=1)
    _seed(state, count=1)
    calls: list[str] = []
    _stub_api(client, monkeypatch, calls)
    client.recognize_page(state.page("T1_Test", 1), "nom")
    assert calls == ["upload", "ocr:1:2:1"]
    state.close()


def test_upscale_uploads_enlarged_copy_and_maps_boxes_back(tmp_path: Path, monkeypatch):
    client, state = _client(tmp_path, classify=False, upscale=2)
    img_path = tmp_path / "page.jpg"
    Image.new("RGB", (40, 60), "white").save(img_path)
    page = PageRecord(
        book_id="T1_Test", page_no=1, image_name="Test.001.jpg", pdf_page=1, sha256="0" * 64,
        width=40, height=60, path=img_path, script="nom", folder="ch",
    )
    uploaded: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        client, "upload", lambda path, sha, force=False: uploaded.append((Path(path), sha)) or "tmp.jpg"
    )
    box_in_enlarged_image = [[20, 10], [40, 10], [40, 100], [20, 100]]
    monkeypatch.setattr(
        client,
        "ocr",
        lambda file_name, sha, **kw: ApiResponse(
            "image-ocr", {"result_ocr_text": ["字"], "result_bbox": [[box_in_enlarged_image, ["字", 0.9]]]}, {}
        ),
    )
    result = client.recognize_page(page, "nom")
    ((up_path, up_sha),) = uploaded
    with Image.open(up_path) as im:
        assert im.size == (80, 120)
    assert up_sha != page.sha256
    assert result.lines[0].points == ((10.0, 5.0), (20.0, 5.0), (20.0, 50.0), (10.0, 50.0))
    assert result.raw["upload_scale"] == 2
    # A second run reuses the same enlarged file (same hash -> API cache hit).
    client.recognize_page(page, "nom")
    assert uploaded[1] == uploaded[0]
    state.close()


def test_ocr_cli_rejects_bad_options():
    from typer.testing import CliRunner

    runner = CliRunner()
    assert runner.invoke(cli.app, ["ocr", "--only", "all"]).exit_code != 0
    assert runner.invoke(cli.app, ["ocr", "--upscale", "0"]).exit_code != 0
