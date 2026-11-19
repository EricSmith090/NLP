"""Resumable Quốc ngữ re-OCR (Doc/FIX_PLAN_v24.md T2.3).

Re-runs the local QN engine on the QN pages (vi/intro/toc/ref) of each book,
skipping pages whose cached result already comes from that engine, unless the
cached result carries one of the --redo-warning codes. Uses only the local
engine (never the Kim Hán Nôm API). Safe to stop and restart.

    python tools/reocr_qn.py --book T1_SuaLoiQuyen --redo-warning QN_REPETITION
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from hannom.cli import filter_pages_by_script  # noqa: E402
from hannom.config import load_config  # noqa: E402
from hannom.ocr.router import OCRRouter  # noqa: E402
from hannom.orchestrator import open_state  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", action="append")
    ap.add_argument("--engine", default="vintern_1b_v3_5")
    ap.add_argument("--redo-warning", action="append", default=[], help="warning code prefix to redo")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    project = load_config(ROOT / args.config)
    with open_state(project) as state:
        for book in project.books:
            if args.book and book.book_id not in args.book:
                continue
            router = OCRRouter(project, book, state)
            pages = filter_pages_by_script(state.pages(book.book_id), "qn")
            todo = []
            for page in pages:
                cached = router.load_result(page)
                redo = cached is None or cached.engine != args.engine or any(
                    str(w).startswith(code) for w in cached.warnings for code in args.redo_warning
                )
                if redo:
                    todo.append(page)
            if args.limit is not None:
                todo = todo[: args.limit]
            print(f"[{book.book_id}] {len(todo)}/{len(pages)} QN pages to OCR with {args.engine}", flush=True)
            for i, page in enumerate(todo, 1):
                t0 = time.time()
                result = router.run_page(page, engines=[args.engine], force=True)
                print(f"[{book.book_id}] OCR {i}/{len(todo)} p{page.page_no} ({result.engine}) "
                      f"{time.time() - t0:.1f}s {','.join(result.warnings)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
