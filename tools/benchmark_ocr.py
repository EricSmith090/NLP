"""Benchmark local OCR engines on a stratified page sample.

This tool never downloads model weights and never sends images to the Kim
Hán Nôm API unless ``--allow-api`` is explicitly passed. It reports
time/page, mean box confidence, and GPU memory when torch is available.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hannom.config import load_config  # noqa: E402
from hannom.models import PageRecord  # noqa: E402
from hannom.ocr.router import OCRRouter  # noqa: E402
from hannom.state import State  # noqa: E402


def _sample(pages: list[PageRecord], count: int) -> list[PageRecord]:
    useful = [p for p in pages if p.folder in {"ch", "vi"}]
    if len(useful) <= count:
        return useful
    # Stratified: take evenly spaced pages from both scripts.
    step = max(1, len(useful) // count)
    sample = useful[::step][:count]
    return sample


def _gpu_memory() -> dict[str, float] | None:
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            return {
                "free_mb": round(free / 1024 / 1024, 1),
                "total_mb": round(total / 1024 / 1024, 1),
                "allocated_mb": round(torch.cuda.memory_allocated() / 1024 / 1024, 1),
            }
    except Exception:
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", default="T1_SuaLoiQuyen")
    parser.add_argument("--pages", type=int, default=20)
    parser.add_argument("--engine", action="append", default=None)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--project", default=str(ROOT / "configs" / "project.yaml"))
    parser.add_argument("--output", default=str(ROOT / "artifacts" / "benchmark" / "ocr_benchmark.json"))
    args = parser.parse_args(argv)

    project = load_config(args.project)
    book = project.book(args.book)
    state = State(project.data_dir / "state.sqlite3")
    try:
        pages = state.pages(book.book_id)
    finally:
        state.close()
    if not pages:
        print("No extracted pages. Run intake/extract/classify first.", file=sys.stderr)
        return 2
    sample = _sample(pages, args.pages)
    engines = args.engine or list(book.ocr.nom)
    if any(name == "kimhannom" for name in engines) and not args.allow_api:
        print("Refusing to call Kim Hán Nôm without --allow-api.", file=sys.stderr)
        return 2

    results = []
    for name in engines:
        state = State(project.data_dir / "state.sqlite3")
        try:
            router = OCRRouter(project, book, state)
            engine = router.build_engine(name)
            if not engine.is_available():
                results.append({"engine": name, "available": False, "pages": []})
                continue
            page_results = []
            for page in sample:
                script = "nom" if page.folder == "ch" else "qn"
                started = time.perf_counter()
                try:
                    result = engine.recognize_page(page, script)
                    elapsed = time.perf_counter() - started
                    confidences = [line.confidence for line in result.lines if line.confidence is not None]
                    page_results.append(
                        {
                            "page_no": page.page_no,
                            "script": script,
                            "seconds": round(elapsed, 3),
                            "lines": len(result.lines),
                            "mean_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
                            "warnings": result.warnings,
                            "gpu": _gpu_memory(),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    page_results.append(
                        {
                            "page_no": page.page_no,
                            "script": script,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
            results.append({"engine": name, "available": True, "pages": page_results})
        finally:
            state.close()

    payload = {
        "book": book.book_id,
        "sample_pages": [p.page_no for p in sample],
        "engines": results,
        "notes": [
            "Local-only unless --allow-api was passed.",
            "No model weights are downloaded by this tool.",
            "Use this output to choose the primary Nôm engine before mass OCR.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
