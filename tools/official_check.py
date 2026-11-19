"""Release gate: run the instructors' checker (`ocr-nom-align` v0.2.0) offline on each book.

Doc/FIX_PLAN_v24.md §6 / T1.4 / gates G1-G3. For every book it stages a copy
of what `package` ships (ch/Label.txt, vi/Label.txt, <Book>.csv,
<Book>_image_map.json, and <Book>.xlsx when present) and runs, with the
network blocked:
    check-diff <csv> --ch --vi --image-map [--xlsx] --final
    score <csv> --min <minimum>
Exit code 0 only if every book passes both. Never uses `run`, `--similar`
or `--ch-fallback`.

    python tools/official_check.py                 # all books, min 95
    python tools/official_check.py --book T1_SuaLoiQuyen --min 0
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hannom.config import load_config  # noqa: E402

TOOLS_ZIP = ROOT / "instructor's reference" / "tools-16-11-2026.zip"
RUNNER = ROOT / "tools" / "official_nom_cli_offline.py"


def ensure_tool(cache: Path) -> Path:
    """Extract the checker once; return its `src` directory."""
    src = cache / "ocr-nom-align-main" / "src"
    if (src / "ocr_nom_align" / "cli.py").exists():
        return src
    if not TOOLS_ZIP.exists():
        raise SystemExit(f"missing {TOOLS_ZIP}")
    cache.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(TOOLS_ZIP) as outer:
        inner = [n for n in outer.namelist() if n.endswith("ocr-nom-align-main.zip")]
        if not inner:
            raise SystemExit("ocr-nom-align-main.zip not found inside the tools zip")
        outer.extract(inner[0], cache)
    with zipfile.ZipFile(cache / inner[0]) as z:
        z.extractall(cache)
    if not (src / "ocr_nom_align" / "cli.py").exists():
        raise SystemExit(f"unexpected tool layout under {cache}")
    return src


def stage_book(project, book, stage_root: Path) -> dict[str, Path]:
    data = project.data_dir
    dest = stage_root / book.book_name
    if dest.exists():
        shutil.rmtree(dest)
    files = {
        "ch": (data / "labels" / book.book_id / "ch" / "Label.txt", dest / "ch" / "Label.txt"),
        "vi": (data / "labels" / book.book_id / "vi" / "Label.txt", dest / "vi" / "Label.txt"),
        "csv": (data / "align" / book.book_id / f"{book.book_name}.csv", dest / f"{book.book_name}.csv"),
        "map": (data / "layout" / book.book_id / "image_map.json", dest / f"{book.book_name}_image_map.json"),
        "xlsx": (data / "align" / book.book_id / f"{book.book_name}.xlsx", dest / f"{book.book_name}.xlsx"),
    }
    out: dict[str, Path] = {}
    for key, (src, dst) in files.items():
        if not src.exists():
            if key == "xlsx":
                continue
            raise SystemExit(f"{book.book_id}: missing {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        out[key] = dst
    return out


def run_tool(tool_src: Path, args: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-I", str(RUNNER), str(tool_src), *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", action="append", help="book_id (repeatable; default: all)")
    ap.add_argument("--min", type=float, default=95.0, dest="minimum")
    ap.add_argument("--no-xlsx", action="store_true", help="do not pass the XLSX to check-diff")
    args = ap.parse_args()
    project = load_config(ROOT / args.config)
    diag = project.data_dir / "diagnostics"
    tool_src = ensure_tool(diag / "ocr-nom-align")
    books = [b for b in project.books if not args.book or b.book_id in args.book]
    report = {}
    ok_all = True
    for book in books:
        staged = stage_book(project, book, diag / "official_check")
        cwd = staged["csv"].parent
        diff_args = ["check-diff", staged["csv"].name, "--ch", "ch/Label.txt", "--vi", "vi/Label.txt",
                     "--image-map", staged["map"].name, "--final"]
        if "xlsx" in staged and not args.no_xlsx:
            diff_args += ["--xlsx", staged["xlsx"].name]
        rc_diff, out_diff = run_tool(tool_src, diff_args, cwd)
        rc_score, out_score = run_tool(tool_src, ["score", staged["csv"].name, "--min", str(args.minimum)], cwd)
        try:
            stats = json.loads(out_score[: out_score.rindex("}") + 1])
        except ValueError:
            stats = None
        ok = rc_diff == 0 and rc_score == 0
        ok_all &= ok
        lines = out_diff.splitlines()
        report[book.book_id] = {
            "ok": ok, "check_diff_exit": rc_diff, "check_diff_head": lines[:40], "check_diff_lines": len(lines),
            "score_exit": rc_score, "score": stats, "score_output": None if stats else out_score[-2000:],
        }
        sim = stats.get("similarity") if isinstance(stats, dict) else None
        print(f"{book.book_id}: {'PASS' if ok else 'FAIL'}  check-diff exit={rc_diff} ({len(lines)} lines)  "
              f"similarity={sim}  score exit={rc_score}")
        for line in lines[:8]:
            print("   ", line[:220])
    out = diag / "official_check" / "report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
