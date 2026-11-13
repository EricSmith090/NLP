"""Pre-hand-in image verification (Area A step 5).

Read-only. Checks, per book:
  1. every page in the state DB exists on disk under ``data/pages/<book>/native/``;
  2. every image decodes, is .jpg, named ``<Tên sách>.NNN[_i].jpg``, contiguous from 1;
  3. sha256 and dimensions match the state DB;
  4. no non-.jpg files in image folders;
  5. per-book page accounting: union of image page numbers == 1..expected_pages
     (ch/ and missing/ch/ double placement counted once; missing/vi excluded from vi/);
     native layer always must reconcile, packaged layer via --book-dir.
  6. --book-dir <packaged folder>: repeat checks against the packaged tree
     (decode/sha/accounting), including intro/ref/toc/missing placement rules.

Usage:
    python tools/verify_images.py                         # native layer, all books
    python tools/verify_images.py --book T1_SuaLoiQuyen
    python tools/verify_images.py --book-dir "data/output/T1_SuaLoiQuyen/T1_Sửa Lưỡi Quyển"
    python tools/verify_images.py --json                  # machine-readable report
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hannom.config import load_config  # noqa: E402
from hannom.intake import sha256_file  # noqa: E402
from hannom.package import PackageIssue  # noqa: E402
from hannom.preflight import IMAGE_RE, check_book_images  # noqa: E402


def _load_state_rows(project, book_id: str):
    db = project.data_dir / "state.sqlite3"
    if not db.exists():
        return None
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT page_no, image_name, sha256, width, height, folder, status, rotation "
            "FROM pages WHERE book_id=? ORDER BY page_no",
            (book_id,),
        ).fetchall()
    finally:
        conn.close()
    return rows


def verify_book_native(project, book) -> list[PackageIssue]:
    issues: list[PackageIssue] = []
    rows = _load_state_rows(project, book.book_id)
    if rows is None:
        return [PackageIssue("STATE_MISSING", f"{project.data_dir / 'state.sqlite3'} not found")]
    native = project.data_dir / "pages" / book.book_id / "native"
    expected = set(range(1, book.expected_pages + 1))
    state_pages = {r[0] for r in rows}
    for page in sorted(expected - state_pages):
        issues.append(PackageIssue("STATE_MISSING_PAGE", f"no state row for page {page}", path=str(native)))
    for page in sorted(state_pages - expected):
        issues.append(PackageIssue("STATE_EXTRA_PAGE", f"state row for out-of-range page {page}", path=str(native)))
    if len(rows) != len(state_pages):
        issues.append(PackageIssue("STATE_DUPLICATE_PAGE", "duplicate (book_id, page_no) rows"))
    # contiguity: page numbers must be exactly 1..expected
    if state_pages and (min(state_pages) != 1 or max(state_pages) != book.expected_pages or len(state_pages) != book.expected_pages):
        issues.append(PackageIssue(
            "STATE_NOT_CONTIGUOUS",
            f"page numbers span {sorted(state_pages)[:3]}…{sorted(state_pages)[-3:]} ({len(state_pages)} rows, expected 1..{book.expected_pages})",
            path=str(native),
        ))
    # file-level checks via the shared sweep (decode + sha256 + naming +
    # per-folder accounting against 1..expected_pages)
    sha_by_image = {r[1]: r[2] for r in rows}
    dims_by_image = {r[1]: (r[3], r[4]) for r in rows}
    issues.extend(
        check_book_images(
            native,
            book.book_name,
            book.expected_pages,
            sha_by_image=sha_by_image,
            dims_by_image=dims_by_image,
            flat=True,
        )
    )
    return issues


def per_book_report(project, book) -> dict:
    rows = _load_state_rows(project, book.book_id) or []
    by_folder: dict[str, int] = {}
    by_status: dict[str, int] = {}
    rotated: list[int] = []
    for _page_no, _name, _sha, _w, _h, folder, status, rotation in rows:
        by_folder[folder or ""] = by_folder.get(folder or "", 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        if int(rotation or 0):
            rotated.append(int(_page_no))
    return {
        "book_id": book.book_id,
        "expected_pages": book.expected_pages,
        "state_rows": len(rows),
        "by_folder": dict(sorted(by_folder.items())),
        "by_status": dict(sorted(by_status.items())),
        "rotated_pages": rotated,
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=str(ROOT / "configs" / "project.yaml"))
    parser.add_argument("--book", action="append", help="restrict to book_id (repeatable)")
    parser.add_argument("--book-dir", type=Path, help="packaged book folder to sweep instead of native layer")
    parser.add_argument("--book-name", help="book name (with spaces/parens) for --book-dir name checks; defaults to folder name")
    parser.add_argument("--expected-pages", type=int, help="expected page count for --book-dir sweeps")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    project = load_config(args.project)
    books = list(project.books)
    if args.book:
        wanted = set(args.book)
        books = [b for b in books if b.book_id in wanted]
        missing = wanted - {b.book_id for b in books}
        if missing:
            print(f"ERROR: unknown book_id(s): {sorted(missing)}", file=sys.stderr)
            return 2

    if args.book_dir:
        book_name = args.book_name or args.book_dir.name
        # try to find the matching book by directory name for expected_pages
        match = next((b for b in books if b.book_name == book_name), None)
        expected = args.expected_pages or (match.expected_pages if match else None)
        if expected is None:
            print("ERROR: --expected-pages required when --book-dir does not match a known book", file=sys.stderr)
            return 2
        rows_by_image: dict[str, str] = {}
        dims_by_image: dict[str, tuple[int, int]] = {}
        if match is not None:
            state_rows = _load_state_rows(project, match.book_id)
            if state_rows:
                rows_by_image = {r[1]: r[2] for r in state_rows}
                dims_by_image = {r[1]: (r[3], r[4]) for r in state_rows}
        issues = check_book_images(
            args.book_dir,
            book_name,
            expected,
            sha_by_image=rows_by_image or None,
            dims_by_image=dims_by_image or None,
        )
        report = {
            "book_dir": str(args.book_dir),
            "book_name": book_name,
            "expected_pages": expected,
            "issues": [f"[{i.code}] {i.message}" for i in issues],
        }
        _emit(report, issues, args.json)
        return 1 if issues else 0

    all_issues: list[PackageIssue] = []
    reports: list[dict] = []
    for book in books:
        report = per_book_report(project, book)
        reports.append(report)
        all_issues.extend(verify_book_native(project, book))
    if args.json:
        print(json.dumps({"books": reports, "issues": [f"[{i.code}] {i.message}" for i in all_issues]}, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print(f"== {report['book_id']}: {report['state_rows']}/{report['expected_pages']} pages")
            print(f"   folders: {report['by_folder']}")
            print(f"   status:  {report['by_status']}")
            if report["rotated_pages"]:
                print(f"   rotated: {report['rotated_pages']}")
        if all_issues:
            print(f"FAIL: {len(all_issues)} issue(s)")
            for issue in all_issues:
                print(f"  [{issue.code}] {issue.message}" + (f" ({issue.path})" if issue.path else ""))
        else:
            print("PASS: native layer verified against state")
    return 1 if all_issues else 0


def _emit(report: dict, issues: list[PackageIssue], as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    for issue in issues:
        print(f"  [{issue.code}] {issue.message}" + (f" ({issue.path})" if issue.path else ""))
    print("PASS" if not issues else f"FAIL: {len(issues)} issue(s)")


if __name__ == "__main__":
    raise SystemExit(main())
