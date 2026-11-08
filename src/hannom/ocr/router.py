"""OCR routing, caching, and book-level runs."""

from __future__ import annotations

import importlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from ..config import BookConfig, ProjectConfig
from ..models import OCRLine, OCRResult, PageRecord
from ..state import State
from .agreement import choose_consensus
from .base import OCREngine, OCRUnavailable
from .kimhannom import KimHanNomClient
from .mock import MockOCREngine


def sample_page_numbers(page_numbers: Iterable[int], count: int) -> set[int]:
    """Choose an evenly spaced, deterministic sample including both ends."""
    numbers = sorted(set(int(n) for n in page_numbers))
    count = max(0, int(count))
    if count <= 0 or not numbers:
        return set()
    if count >= len(numbers):
        return set(numbers)
    if count == 1:
        return {numbers[len(numbers) // 2]}
    indices = [int(i * (len(numbers) - 1) / (count - 1)) for i in range(count)]
    return {numbers[index] for index in indices}


def page_confidence(results: Iterable[OCRResult]) -> float | None:
    """Mean line confidence, so one very low line still pulls the page down."""
    confidences = [
        float(line.confidence)
        for result in results
        for line in result.lines
        if line.confidence is not None
    ]
    if not confidences:
        return None
    return sum(confidences) / len(confidences)



def _load_adapter(path: str) -> type[OCREngine]:
    module_name, class_name = path.split(":", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return cls


class OCRRouter:
    def __init__(self, project: ProjectConfig, book: BookConfig, state: State):
        self.project = project
        self.book = book
        self.state = state
        self.engine_dir = project.data_dir / "ocr" / book.book_id
        self.engine_dir.mkdir(parents=True, exist_ok=True)

    def _engine_configs(self) -> dict[str, Any]:
        return (self.project.ocr_config or {}).get("engines", {})

    def build_engine(self, name: str) -> OCREngine:
        configs = self._engine_configs()
        cfg = configs.get(name)
        if cfg is None:
            raise OCRUnavailable(f"Unknown OCR engine '{name}'")
        kind = cfg.get("kind")
        if kind == "mock":
            return MockOCREngine(self.project.data_dir / "ocr" / "fixtures")
        if kind == "api":
            return KimHanNomClient(self.project, self.state)
        if kind == "local":
            adapter = cfg.get("adapter")
            if not adapter:
                raise OCRUnavailable(f"Local engine '{name}' has no adapter")
            cls = _load_adapter(adapter)
            return cls()
        raise OCRUnavailable(f"Unsupported OCR engine kind: {kind}")

    def available(self, script: str) -> list[str]:
        names = self.book.ocr.nom if script == "nom" else self.book.ocr.quoc_ngu
        out: list[str] = []
        for name in names:
            try:
                engine = self.build_engine(name)
                if engine.is_available():
                    out.append(name)
            except Exception:
                continue
        return out

    def _path(self, page: PageRecord) -> Path:
        return self.engine_dir / f"{page.page_no:04d}.json"

    def load_result(self, page: PageRecord) -> OCRResult | None:
        path = self._path(page)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return OCRResult(
            book_id=data["book_id"],
            page_no=data["page_no"],
            image_name=data["image_name"],
            image_sha256=data["image_sha256"],
            engine=data["engine"],
            lines=[
                OCRLine(
                    text=line["text"],
                    points=tuple(tuple(float(v) for v in pt) for pt in line["points"]),
                    confidence=line.get("confidence"),
                    script=line.get("script"),
                    difficult=line.get("difficult"),
                    extra=line.get("extra", {}),
                )
                for line in data.get("lines", [])
            ],
            raw=data.get("raw", {}),
            warnings=list(data.get("warnings", [])),
            cached=True,
        )

    def save_result(self, result: OCRResult) -> Path:
        path = self._path_for(result.page_no)
        payload = asdict(result)
        payload["lines"] = [
            {
                "text": line.text,
                "points": [list(p) for p in line.points],
                "confidence": line.confidence,
                "script": line.script,
                "difficult": line.difficult,
                "extra": line.extra,
            }
            for line in result.lines
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _path_for(self, page_no: int) -> Path:
        return self.engine_dir / f"{page_no:04d}.json"

    def _engine_kind(self, name: str) -> str:
        cfg = self._engine_configs().get(name) or {}
        return str(cfg.get("kind", ""))

    def _split_engines(self, names: Iterable[str]) -> tuple[list[str], list[str]]:
        local: list[str] = []
        api: list[str] = []
        for name in names:
            if self._engine_kind(name) == "api":
                api.append(name)
            else:
                local.append(name)
        return local, api

    def _threshold(self, script: str) -> float:
        routing = (self.project.ocr_config or {}).get("routing", {})
        key = "nom" if script == "nom" else "quoc_ngu"
        default = 0.70 if script == "nom" else 0.75
        return float((routing.get(key) or {}).get("low_confidence_threshold", default))

    def _sample_set(self, script: str) -> set[int]:
        """Lazily derive the API sample from the current book pages."""
        if not hasattr(self, "_api_samples"):
            self._api_samples: dict[str, set[int]] = {}
        if script not in self._api_samples:
            folder = "ch" if script == "nom" else "vi"
            numbers = [
                page.page_no
                for page in self.state.pages(self.book.book_id)
                if str(page.folder) == folder
            ]
            self._api_samples[script] = sample_page_numbers(numbers, self.book.ocr.sample_pages)
        return self._api_samples[script]

    def _should_call_api(self, script: str, page_no: int, local_results: list[OCRResult]) -> bool:
        """Call the approved API only for the sample or weak local output."""
        if not local_results:
            return True
        confidence = page_confidence(local_results)
        threshold = self._threshold(script)
        if confidence is None or confidence < threshold:
            return True
        if any(
            line.confidence is not None and float(line.confidence) < threshold
            for result in local_results
            for line in result.lines
        ):
            return True
        return page_no in self._sample_set(script)

    def run_page(
        self,
        page: PageRecord,
        engines: list[str] | None = None,
        force: bool = False,
    ) -> OCRResult:
        if page.folder in {"blank", "misc"}:
            raise OCRUnavailable(f"Page {page.page_no} is {page.folder}; no OCR needed")
        if not force:
            cached = self.load_result(page)
            if cached is not None:
                return cached

        script = "nom" if page.folder == "ch" else "qn"
        explicit = engines is not None
        names = list(engines) if explicit else (
            list(self.book.ocr.nom) if script == "nom" else list(self.book.ocr.quoc_ngu)
        )
        api_mode = (self.book.ocr.api_mode or "sample_then_low_confidence").strip().lower()
        local_names, api_names = self._split_engines(names)
        unknown_mode = False
        if not explicit:
            if api_mode in {"never", "disabled", "local_only", "local-only"}:
                api_names = []
            elif api_mode not in {"always", "all", "sample_then_low_confidence", "sample_then_low_conf"}:
                # A typo must not silently spend quota. Be local-only and
                # record the reason in the result metadata.
                api_names = []
                unknown_mode = True

        results: list[OCRResult] = []
        unavailable: list[str] = []
        api_called = False

        def run_engines(selected: Iterable[str]) -> None:
            for name in selected:
                try:
                    engine = self.build_engine(name)
                    if not engine.is_available():
                        unavailable.append(f"{name}: unavailable")
                        continue
                    result = engine.recognize_page(page, script)
                    results.append(result)
                except OCRUnavailable as exc:
                    unavailable.append(f"{name}: {exc}")
                except Exception as exc:  # keep the pipeline honest and resumable
                    unavailable.append(f"{name}: {type(exc).__name__}: {exc}")

        if explicit or api_mode in {"always", "all"}:
            run_engines(local_names)
            if api_names:
                api_called = True
                run_engines(api_names)
        elif api_mode in {"sample_then_low_confidence", "sample_then_low_conf"}:
            run_engines(local_names)
            if api_names and self._should_call_api(script, page.page_no, results):
                api_called = True
                run_engines(api_names)
        else:
            # Local-only mode, including an unknown api_mode.
            run_engines(local_names)

        if not results:
            raise OCRUnavailable(
                f"No OCR engine available for {page.book_id} p{page.page_no} ({script}). "
                + "; ".join(unavailable)
            )

        threshold = 0.85
        routing = (self.project.ocr_config or {}).get("routing", {})
        if script == "nom":
            threshold = float((routing.get("nom") or {}).get("agreement_threshold", 0.85))
        else:
            threshold = float((routing.get("quoc_ngu") or {}).get("agreement_threshold", 0.85))
        result, warnings = choose_consensus(results, script, threshold)
        if unavailable:
            result.warnings.extend(f"ENGINE_UNAVAILABLE:{u}" for u in unavailable)
        if unknown_mode:
            result.warnings.append(f"OCR_ROUTING_UNKNOWN_MODE:{api_mode}")
        result.warnings = sorted(set(result.warnings))
        result.raw = dict(result.raw or {})
        result.raw["routing"] = {
            "api_mode": api_mode,
            "api_called": api_called,
            "engines_requested": names,
            "engines_unavailable": unavailable,
            "api_sample_pages": sorted(self._sample_set(script)) if api_names else [],
        }
        self.save_result(result)

        confidence = page_confidence(results)
        flags = list(page.review_flags)
        for warning in result.warnings:
            code = warning.split(":", 1)[0]
            if code in {"OCR_ENGINE_DISAGREE", "BBOX_MISSING", "OCR_EMPTY", "BBOX_INVALID", "OCR_TEXT_BBOX_COUNT_MISMATCH"}:
                if code not in flags:
                    flags.append(code)
        self.state.update_page(
            page.book_id,
            page.page_no,
            status="ocr_done",
            ocr_engine=result.engine,
            ocr_confidence=confidence,
            review_flags=flags,
        )
        return result

    def run_book(
        self,
        pages: Iterable[PageRecord] | None = None,
        engines: list[str] | None = None,
        force: bool = False,
        limit: int | None = None,
    ) -> list[OCRResult]:
        pages = list(pages or self.state.pages(self.book.book_id))
        targets = [p for p in pages if p.folder in {"ch", "vi", "intro", "toc", "ref"}]
        if limit is not None:
            targets = targets[:limit]
        # Compute samples from the exact target set, not from unclassified
        # pages or pages excluded by --limit.
        self._api_samples = {}
        for script, folder in (("nom", "ch"), ("qn", "vi")):
            numbers = [p.page_no for p in targets if str(p.folder) == folder]
            self._api_samples[script] = sample_page_numbers(numbers, self.book.ocr.sample_pages)
        out: list[OCRResult] = []
        for page in targets:
            out.append(self.run_page(page, engines=engines, force=force))
        return out
