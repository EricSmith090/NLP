"""Lazy local PaddleOCR adapter.

This file deliberately imports paddleocr only inside recognize_page(). The
core test suite and the extraction/classification stages must run on a
machine without paddle installed.

PaddleOCR 3.x (paddlex) is supported; the 2.x call pattern is not. On this
project's CPU-only Windows host the server models are unusable (~313 s/page;
the PIR oneDNN path crashes with ``ConvertPirAttribute2RuntimeAttribute``),
so the adapter disables paddlex's default mkldnn run mode and uses the
PP-OCRv5 **mobile** det/rec models (~6-7 s/page at 800x1135). Override with
the constructor arguments if the runtime supports the server models.

The models were downloaded automatically from the official model hosters on
2026-11-08 as part of the benchmark; no weights are committed to this repo.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from ..models import OCRLine, OCRResult, PageRecord
from .base import OCREngine, OCRUnavailable

DEFAULT_DET = "PP-OCRv5_mobile_det"
DEFAULT_REC = "PP-OCRv5_mobile_rec"


class PaddleOCREngine(OCREngine):
    name = "paddleocr_vl"

    def __init__(self, lang: str = "ch", use_gpu: bool = False,
                 det_model: str = DEFAULT_DET, rec_model: str = DEFAULT_REC):
        self.lang = lang
        self.use_gpu = use_gpu
        self.det_model = det_model
        self.rec_model = rec_model
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
        # paddlex defaults to mkldnn/oneDNN on CPU, which crashes on these
        # models (PIR attribute conversion, oneDNN instruction).
        os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "false")
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import PaddleOCR  # type: ignore

        self._ocr = PaddleOCR(
            lang=self.lang,
            text_detection_model_name=self.det_model,
            text_recognition_model_name=self.rec_model,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            # Vertical Nôm columns: do not flip text lines.
            use_textline_orientation=False,
        )
        return self._ocr

    @staticmethod
    def _res(out):
        if hasattr(out, "json"):
            data = out.json
        else:
            data = out
        if isinstance(data, dict) and "res" in data:
            return data["res"]
        return data

    @staticmethod
    def _points(res, index):
        polys = res.get("rec_polys") or []
        boxes = res.get("rec_boxes") or []
        if index < len(polys) and polys[index] and len(polys[index]) == 4:
            return tuple((float(x), float(y)) for x, y in polys[index])
        if index < len(boxes):
            x0, y0, x1, y1 = (float(v) for v in boxes[index])
            return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        return ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0))

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        ocr = self._load()
        outs = ocr.predict(str(page.path))
        lines: list[OCRLine] = []
        raw_texts: list[str] = []
        for out in outs:
            res = self._res(out)
            if not isinstance(res, dict):
                continue
            texts = res.get("rec_texts") or []
            scores = res.get("rec_scores") or []
            for index, text in enumerate(texts):
                if not str(text).strip():
                    continue
                confidence = float(scores[index]) if index < len(scores) else None
                raw_texts.append(str(text))
                lines.append(
                    OCRLine(
                        text=str(text),
                        points=self._points(res, index),
                        confidence=confidence,
                        script=script,
                    )
                )
        warnings = [] if lines else ["OCR_EMPTY"]
        return OCRResult(
            book_id=page.book_id,
            page_no=page.page_no,
            image_name=page.image_name,
            image_sha256=page.sha256,
            engine=self.name,
            lines=lines,
            raw={"texts": raw_texts},
            warnings=warnings,
        )
