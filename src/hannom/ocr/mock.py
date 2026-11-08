"""Fixture-only OCR engine. Never use it to produce submission data."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import OCRLine, OCRResult, PageRecord
from .base import OCREngine


class MockOCREngine(OCREngine):
    name = "mock"

    def __init__(self, fixture_dir: str | Path = "data/ocr/fixtures"):
        self.fixture_dir = Path(fixture_dir)

    def is_available(self) -> bool:
        return True

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        fixture = self.fixture_dir / page.book_id / f"{page.page_no:04d}.json"
        if not fixture.exists():
            return OCRResult(
                book_id=page.book_id,
                page_no=page.page_no,
                image_name=page.image_name,
                image_sha256=page.sha256,
                engine=self.name,
                lines=[],
                warnings=["MOCK_EMPTY_FIXTURE"],
            )
        data = json.loads(fixture.read_text(encoding="utf-8"))
        lines = [
            OCRLine(
                text=str(item.get("text", "")),
                points=tuple(tuple(float(v) for v in pt) for pt in item["points"]),
                confidence=item.get("confidence"),
                script=item.get("script", script),
                difficult=item.get("difficult"),
            )
            for item in data.get("lines", [])
        ]
        return OCRResult(
            book_id=page.book_id,
            page_no=page.page_no,
            image_name=page.image_name,
            image_sha256=page.sha256,
            engine=self.name,
            lines=lines,
            raw=data,
            warnings=["MOCK_ENGINE_NOT_FOR_SUBMISSION"],
        )
