"""OCR engine interface and errors."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import OCRResult, PageRecord


class OCRUnavailable(RuntimeError):
    """The engine is configured but its runtime/model/credentials are absent."""


class OCREngine(ABC):
    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def recognize_page(self, page: PageRecord, script: str) -> OCRResult:
        raise NotImplementedError

    def describe(self) -> dict[str, str]:
        return {"name": self.name, "available": str(self.is_available())}
