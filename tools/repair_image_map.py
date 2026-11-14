"""Propose (and optionally apply) a content-based repair of a book's image_map.

Usage:
    python tools/repair_image_map.py --book T1_SuaLoiQuyen [--exclude-pages a.jpg,b.jpg] [--apply]

Propose-only is the default: it writes
    data/layout/<book>/map_repair/image_map.proposed.json
    data/layout/<book>/map_repair/image_map.triage.csv
    data/layout/<book>/map_repair/summary.json
and prints per-pair evidence. --apply replaces data/layout/<book>/image_map.json
with the proposal (a backup image_map.pre-repair.json is kept next to it).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hannom.config import load_config  # noqa: E402
from hannom.map_repair import (  # noqa: E402
    ideographs,
    image_page_number,
    match_recall,
    qn_token_sets,
    read_clean_text,
    solve,
    triage_rows,
    write_triage_csv,
)

# Parenthetical Nôm (printed) page number printed in the QN page header, e.g.
# "- 81 - (204)" or "-14 (271)". Verified: PDF page = printed page + nom_offset
# (2 for both tap1 and tap3 books).
MARKER_RE = re.compile(r"\(\s*(\d{1,4})\s*\)")

# Pages where OCR silently dropped the header but the parens was read off the
# page image directly (visual check of the scan, 2026-11-12). Keep tiny;
# everything else must come from the OCR pass.
MANUAL_PARENS = {
    "T1_CamPhong_Tap1": {
        "T1_Cấm Phòng Cho Bổn Đạo (Tập 1).020.jpg": 267,
        "T1_Cấm Phòng Cho Bổn Đạo (Tập 1).079.jpg": 208,
        "T1_Cấm Phòng Cho Bổn Đạo (Tập 1).135.jpg": 152,
    },
}


def extract_markers(ocr_dir: Path, vi_inventory: set[str], ch_inventory: set[str], offset: int) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Return (anchors ch_name->vi_name map, issues) from raw OCR files."""
    def page_of(name: str) -> int:
        return image_page_number(name)

    ch_pages = {page_of(n): n for n in ch_inventory}
    ocr_by_page: dict[int, Path] = {}
    for f in sorted(ocr_dir.glob("*.json")):
        try:
            ocr_by_page[int(f.stem)] = f
        except ValueError:
            continue

    anchors: dict[str, str] = {}
    issues: list[dict[str, str]] = []
    for vi_name in sorted(vi_inventory):
        vi_page = page_of(vi_name)
        f = ocr_by_page.get(vi_page)
        if f is None:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            issues.append({"vi_page": vi_name, "problem": f"unreadable OCR json: {exc}"})
            continue
        head = " ".join(str(line.get("text", "")).strip() for line in data.get("lines", [])[:3])
        if not head:
            issues.append({"vi_page": vi_name, "problem": "empty OCR lines"})
            continue
        # Header may wrap across lines; only trust small, near-the-start parens.
        match = MARKER_RE.search(head[:200])
        if not match:
            continue
        printed = int(match.group(1))
        ch_page = printed + offset
        target = ch_pages.get(ch_page)
        if target is None:
            issues.append({"vi_page": vi_name, "problem": f"marker ({match.group(1)})+{offset}={ch_page} not in ch inventory"})
            continue
        anchors[target] = vi_name
    return anchors, issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", required=True)
    parser.add_argument("--config", default="configs/project.yaml")
    parser.add_argument("--exclude-pages", default="",
                        help="Comma-separated vi image names to exclude (translator apparatus, no Nôm counterpart)")
    parser.add_argument("--skip-penalty", type=float, default=25.0)
    parser.add_argument("--nom-offset", type=int, default=2,
                        help="Printed Nôm page number -> PDF page offset (default 2)")
    parser.add_argument("--no-anchors", action="store_true",
                        help="Do not pin pairs from the QN header parens markers")
    parser.add_argument("--manual-anchors", default="",
                        help="JSON mapping of vi image name -> printed Nôm page, for OCR-dropped headers")
    parser.add_argument("--apply", action="store_true",
                        help="Replace data/layout/<book>/image_map.json with the proposal")
    args = parser.parse_args()

    project = load_config(ROOT / args.config)
    book = project.book(args.book)
    entries_dir = ROOT / "dictionaries-04-11-2026" / "entries"
    cache_path = ROOT / "data" / "dictionary" / "char_readings.json"
    from hannom.dictionary.readings import load_readings
    readings = load_readings(str(entries_dir), str(cache_path))

    image_map_path = ROOT / "data" / "layout" / book.book_id / "image_map.json"
    map_data = json.loads(image_map_path.read_text(encoding="utf-8"))
    old_pairs = map_data.get("pairs", [])

    # Full page inventory comes from the assigned scope (book config), not
    # from which pages happened to be paired last time. Explicit inventory
    # overrides add pages the print edition handles as front matter (e.g.
    # parens-marked translation pages before the body).
    overrides_vi = set(int(p) for p in getattr(book, "inventory_vi", ()))
    overrides_misc = set(int(p) for p in getattr(book, "inventory_misc", ()))
    if book.nom_start_hint and book.nom_end_hint and book.translation_start:
        ch_inventory = {f"{book.book_name}.{p:03d}.jpg" for p in range(book.nom_start_hint, book.nom_end_hint + 1)}
        vi_pages = list(range(book.translation_start, book.translation_end + 1)) + list(overrides_vi)
        vi_inventory = {f"{book.book_name}.{p:03d}.jpg" for p in vi_pages}
        vi_inventory = {n for n in vi_inventory if image_page_number(n) not in overrides_misc}
    else:
        ch_inventory = {name for pair in old_pairs for name in pair.get("ch", [])}
        vi_inventory = {name for pair in old_pairs for name in pair.get("vi", [])}

    clean_dir = ROOT / "data" / "clean" / book.book_id

    def page_of(name: str) -> int:
        return image_page_number(name)

    excluded = {p.strip() for p in args.exclude_pages.split(",") if p.strip()}
    ocr_dir = ROOT / "data" / "ocr" / book.book_id
    marker_anchors, marker_issues = ({}, []) if args.no_anchors else extract_markers(ocr_dir, vi_inventory, ch_inventory, args.nom_offset)
    if args.manual_anchors:
        manual = json.loads(Path(args.manual_anchors).read_text(encoding="utf-8"))
        # Only accept manual parens that land inside the Nôm inventory.
        for vi_name, printed in manual.items():
            target = f"{book.book_name}.{int(printed) + args.nom_offset:03d}.jpg"
            if target in ch_inventory:
                marker_anchors[target] = vi_name
            else:
                marker_issues.append({"vi_page": vi_name, "problem": f"manual parens {printed}+{args.nom_offset} target {target} not in ch inventory"})
    # Built-in visual-check parens for pages OCR dropped; keep tiny.
    for vi_name, printed in MANUAL_PARENS.get(book.book_id, {}).items():
        target = f"{book.book_name}.{int(printed) + args.nom_offset:03d}.jpg"
        if target in ch_inventory and vi_name not in {v for v in marker_anchors.values()}:
            marker_anchors[target] = vi_name
        elif target not in ch_inventory:
            marker_issues.append({"vi_page": vi_name, "problem": f"built-in parens {printed}+{args.nom_offset} target {target} not in ch inventory"})

    # T1 reading order: ch decreasing page number, vi increasing.
    ch_pages = sorted(ch_inventory, key=page_of, reverse=True)
    vi_pages = sorted(vi_inventory - excluded, key=page_of)

    def ch_text(name: str) -> str:
        return read_clean_text(clean_dir, page_of(name))

    ch_chars_by_name = {name: ideographs(ch_text(name)) for name in ch_pages}
    vi_sets_by_name = {name: qn_token_sets(read_clean_text(clean_dir, page_of(name))) for name in vi_inventory}

    ch_chars = [ch_chars_by_name[name] for name in ch_pages]
    vi_sets = [vi_sets_by_name[name] for name in vi_pages]

    result = solve(
        ch_pages, ch_chars, vi_pages, vi_sets, readings,
        skip_penalty=args.skip_penalty,
        anchors=list(marker_anchors.items()),
    )

    out_dir = ROOT / "data" / "layout" / book.book_id / "map_repair"
    out_dir.mkdir(parents=True, exist_ok=True)

    proposed = {
        "pairs": [
            {"ch": p["ch"], "vi": p["vi"], "note": "content dp re-pairing", "source": "content_dp", "status": "candidate"}
            for p in result.pairs
        ],
        "meta": {
            **{k: v for k, v in map_data.get("meta", {}).items()},
            "mapping_source": "content_dp",
            "proposed_at": datetime.now().isoformat(timespec="seconds"),
            "excluded_pages": sorted(excluded),
            "skip_penalty": args.skip_penalty,
            "skipped_ch": result.skipped_ch,
            "skipped_vi": result.skipped_vi,
            "markers_used": len(marker_anchors),
            "marker_issues": marker_issues,
            "anchor_issues": result.anchor_issues,
        },
    }
    proposed_path = out_dir / "image_map.proposed.json"
    proposed_path.write_text(json.dumps(proposed, ensure_ascii=False, indent=1), encoding="utf-8")

    rows = triage_rows(old_pairs, result.pairs, ch_chars_by_name, vi_sets_by_name, readings)
    triage_path = out_dir / "image_map.triage.csv"
    write_triage_csv(triage_path, rows)

    def assignment(pairs):
        return {name: pair["vi"] for pair in pairs for name in pair["ch"]}

    old_by_ch, new_by_ch = assignment(old_pairs), assignment(result.pairs)
    all_ch = sorted(set(old_by_ch) | set(new_by_ch))
    changed = sum(1 for c in all_ch if old_by_ch.get(c) != new_by_ch.get(c))

    def mean_recall(assn):
        total, count = 0.0, 0
        for c in all_ch:
            names = assn.get(c) or []
            sets = [vi_sets_by_name[n] for n in names if n in vi_sets_by_name]
            chars = ch_chars_by_name.get(c, [])
            exact = frozenset().union(*(s[0] for s in sets)) if sets else frozenset()
            folds = frozenset().union(*(s[1] for s in sets)) if sets else frozenset()
            total += match_recall(chars, (exact, folds), readings)
            count += 1
        return total / count if count else 0.0

    summary = {
        "book": book.book_id,
        "old_pairs": len(old_pairs),
        "new_pairs": len(result.pairs),
        "changed_assignments": changed,
        "skipped_ch": result.skipped_ch,
        "skipped_vi": result.skipped_vi,
        "excluded_pages": sorted(excluded),
        "markers_used": len(marker_anchors),
        "marker_issues": marker_issues,
        "anchor_issues": result.anchor_issues,
        "mean_recall_old": round(mean_recall(old_by_ch), 4),
        "mean_recall_new": round(mean_recall(new_by_ch), 4),
        "triage_rows": len(rows),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"proposed: {proposed_path}")
    print(f"triage:   {triage_path} ({len(rows)} changed rows)")

    if args.apply:
        backup = out_dir / "image_map.pre-repair.json"
        if not backup.exists():
            backup.write_text(image_map_path.read_text(encoding="utf-8"), encoding="utf-8")
        image_map_path.write_text(json.dumps(proposed, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"applied: {image_map_path} (backup at {backup})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
