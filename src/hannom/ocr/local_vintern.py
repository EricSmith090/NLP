"""Lazy local Vintern-1B-v2 adapter for Quốc ngữ.

Vintern is a vision-language OCR model. Its output is typically page text,
not four-point boxes. The pipeline therefore treats a text-only result as a
second opinion and keeps PaddleOCR's boxes for Label.txt. If Vintern is used
as the primary engine, a detection stage must supply boxes; this adapter
flags BBOX_MISSING rather than fabricating them.
"""

from __future__ import annotations

import importlib.util

from ..models import OCRLine, OCRResult, PageRecord
from .base import OCREngine, OCRUnavailable


class VinternEngine(OCREngine):
    name = "vintern_1b_v2"

    def __init__(self, model_id: str = "5CD-AI/Vintern-1B-v2", device: str = "cuda"):
        self.model_id = model_id
        self.device = device
        self._model = None
        self._tokenizer = None

    def is_available(self) -> bool:
        return importlib.util.find_spec("transformers") is not None and importlib.util.find_spec("torch") is not None

    def _load(self):
        if self._model is not None:
            return self._model, self._tokenizer
        if not self.is_available():
            raise OCRUnavailable(
                "transformers/torch are not installed. Install the pinned OCR extra "
                "and download the approved local weights."
            )
        from transformers import AutoModel, AutoTokenizer  # type: ignore

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=True)
        self._model = AutoModel.from_pretrained(
            self.model_id,
            trust_remote_code=True,
            torch_dtype="auto",
            device_map=self.device,
        ).eval()
        return self._model, self._tokenizer

    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        # The exact Vintern prompt/processor differs by release. Do not
        # silently invent a call signature; require the adapter to be
        # calibrated during the benchmark step.
        raise OCRUnavailable(
            "Vintern adapter requires the benchmark-calibrated prompt/processor. "
            "Run tools/benchmark_ocr.py and pin the working revision before use."
        )
