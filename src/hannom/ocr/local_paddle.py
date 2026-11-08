"""Lazy local PaddleOCR adapter.

This file deliberately imports paddleocr only inside recognize_page(). The
core test suite and the extraction/classification stages must run on a
machine without paddle installed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ..models import OCRLine, OCRResult, PageRecord
from .base import OCREngine, OCRUnavailable


class PaddleOCREngine(OCREngine):
    name = "paddleocr_vl"

    def __init__(self, lang: str = "ch", use_gpu: bool = True):
        self.lang = lang
        self.use_gpu = use_gpu
        self._ocr = None

    def is_available(self) -> bool:
        return importlib.util.find_spec("paddleocr") is not None

    def _load(self):
        if self._ocr is not None:
            return self._ocr
        if not self.is_available():
            raise OCRUnavailable(
                "paddleocr is not installed. Install and pin an OCR extra, then rerun; "
                "see README/USER_GUIDE."
            )
        from paddleocr import PaddleOCR  # type: ignore

        # PaddleOCR APIs differ between 2.x and 3.x. Keep the call minimal and
        # fail loudly if the installed version is unsupported.
        self._ocr = PaddleOCR(use_angle_cls=True, lang=self.lang, show_log=False)
        return self._ocr

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        ocr = self._load()
        result = ocr.ocr(str(page.path), cls=True)
        lines: list[OCRLine] = []
        raw_boxes: list = []
        # PaddleOCR 2.x returns [[ [points, (text, conf)], ... ]].
        if result and isinstance(result, list) and result[0]:
            for item in result[0]:
                try:
                    points, (text, confidence) = item[0], item[1]
                except (TypeError, ValueError):
                    continue
                if not text:
                    continue
                lines.append(
                    OCRLine(
                        text=str(text),
                        points=tuple((float(x), float(y)) for x, y in points),
                        confidence=float(confidence),
                        script=script,
                    )
                )
                raw_boxes.append(item)
        warnings = [] if lines else ["OCR_EMPTY"]
        return OCRResult(
            book_id=page.book_id,
            page_no=page.page_no,
            image_name=page.image_name,
            image_sha256=page.sha256,
            engine=self.name,
            lines=lines,
            raw={"result": raw_boxes},
            warnings=warnings,
        )
