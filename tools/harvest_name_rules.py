"""Turn the reviewer's yellow clicks on proper-name syllables into yellow rules.

Two passes (agreed 2026-11-21):

1. In the review app the reviewer compares a red name syllable with the page
   image and, when the printed char is the OCR char, presses "→ Vàng". The
   app stores it as a reviewed warn element in the CSV.
2. This tool collects those clicks and proposes one rule per (Nôm char,
   syllable) pair for ``alignment.text_diff_warn_rules``;
   ``tools/apply_warn_rules.py`` then turns the same pair yellow in every
   other row of the book.

A proper name is a Quốc ngữ token that starts with a capital letter and has
two or more syllables joined by "-" (Giê-su, An-ti-ô-cô). Only clicks on a
1 Nôm char <-> 1 syllable element inside such a name are harvested. Other red
syllables of the same name are listed, never turned yellow: each yellow char
must have been checked on the image at least once.

Read-only: prints the proposed rules as YAML for configs/alignment.yaml.

    python tools/harvest_name_rules.py --book T1_CamPhong_Tap2
    python tools/harvest_name_rules.py --book T1_CamPhong_Tap2 --data <copy of data/>
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hannom.config import load_config  # noqa: E402
from hannom.textdiff import tone_key, warn_rules_from_config  # noqa: E402

_EDGE_PUNCT = re.compile(r"^[^\w]+|[^\w]+$")


def token_at(text: str, pos: int) -> tuple[int, int, str]:
    """Whitespace-delimited token around ``pos``: (start, end, token without outer punctuation)."""
    s = pos
    while s > 0 and not text[s - 1].isspace():
        s -= 1
    e = pos
    while e < len(text) and not text[e].isspace():
        e += 1
    return s, e, _EDGE_PUNCT.sub("", text[s:e])


def is_name(token: str) -> bool:
    parts = token.split("-")
    return len(parts) >= 2 and all(p.isalpha() for p in parts) and token[:1].isupper()


def short_id(sentence_id: str) -> str:
    head, _, sent = sentence_id.rpartition(".")
    return f"{head.rpartition('.')[2]}.{sent}"


def single_pair(el: dict) -> tuple[str, str] | None:
    """(Nôm char, syllable) when the element is exactly 1 char <-> 1 syllable."""
    nom, vi = el.get("nom_sub_text") or "", (el.get("vi_sub_text") or "").strip()
    if len(nom) == 1 and vi and vi.isalpha():
        return nom, vi
    return None


def name_of(row: dict, el: dict) -> tuple[int, int, str] | None:
    if not el.get("vi_pos"):
        return None
    span = token_at(row["vi_txt"], el["vi_pos"][0][0])
    return span if is_name(span[2]) else None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", required=True)
    ap.add_argument("--data", help="another data directory (e.g. a copy for a trial run)")
    args = ap.parse_args()

    project = load_config(ROOT / args.config)
    if args.data:
        project = dataclasses.replace(project, data_dir=Path(args.data).resolve())
    book = next(b for b in project.books if b.book_id == args.book)
    csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    csv.field_size_limit(10**8)
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["_els"] = json.loads(r.get("text_diff") or "null") or []

    existing = set(warn_rules_from_config(project.alignment_config))
    clicked: dict[tuple[str, str], dict] = {}
    not_harvested: list[str] = []
    siblings: list[str] = []
    for r in rows:
        for el in r["_els"]:
            if el.get("type") != "warn" or el.get("reviewed") != 1 or el.get("suggest"):
                continue
            pair, name = single_pair(el), name_of(r, el)
            if pair and (pair[0], tone_key(pair[1])) in existing:
                continue  # yellow because of a rule already in the config
            if not pair or not name:
                not_harvested.append(f"{short_id(r['sentence_id'])}: {el.get('nom_sub_text') or '∅'} ↔ "
                                     f"{el.get('vi_sub_text') or '∅'} (not 1:1 inside a hyphenated name)")
                continue
            key = (pair[0], tone_key(pair[1]))
            entry = clicked.setdefault(key, {"qn": pair[1].lower(), "names": set(), "ids": []})
            entry["names"].add(name[2])
            entry["ids"].append(short_id(r["sentence_id"]))
            # other red syllables of the same name occurrence: listed, not changed
            for other in r["_els"]:
                if other.get("type") == "error" and other.get("vi_pos"):
                    o = other["vi_pos"][0][0]
                    if name[0] <= o < name[1]:
                        siblings.append(f"{short_id(r['sentence_id'])} {name[2]}: "
                                        f"{other.get('nom_sub_text') or '∅'} ↔ {other.get('vi_sub_text') or '∅'}")

    # what the rules would change elsewhere (apply_warn_rules works on 1:1 red elements)
    reach: dict[tuple[str, str], dict] = defaultdict(lambda: {"in_name": [], "elsewhere": []})
    for r in rows:
        for el in r["_els"]:
            pair = single_pair(el) if el.get("type") == "error" else None
            if pair and (pair[0], tone_key(pair[1])) in clicked:
                bucket = "in_name" if name_of(r, el) else "elsewhere"
                reach[(pair[0], tone_key(pair[1]))][bucket].append(short_id(r["sentence_id"]))

    print(f"{book.book_id}: clicked name pairs not yet in the config: {len(clicked)}")
    for key, e in sorted(clicked.items(), key=lambda kv: -len(reach[kv[0]]["in_name"])):
        rc = reach[key]
        print(f"  {key[0]} ↔ {e['qn']}: clicked in {', '.join(e['ids'][:4])} ({', '.join(sorted(e['names']))}); "
              f"would turn yellow: {len(rc['in_name'])} in names"
              + (f", {len(rc['elsewhere'])} OUTSIDE names ({' '.join(rc['elsewhere'][:5])}) - check" if rc["elsewhere"] else ""))
    if siblings:
        print(f"\nOther red syllables in the clicked names (left red, check them on the image): {len(siblings)}")
        for s in siblings[:30]:
            print(f"  {s}")
    if not_harvested:
        print(f"\nYellow clicks not turned into rules: {len(not_harvested)}")
        for s in not_harvested[:30]:
            print(f"  {s}")
    if clicked:
        print("\n# YAML for configs/alignment.yaml -> text_diff_warn_rules:")
        for key, e in clicked.items():
            names = ", ".join(sorted(e["names"]))
            print(f'    - {{nom: "{key[0]}", qn: "{e["qn"]}", note: "{names}; người review đánh vàng ở '
                  f'{", ".join(e["ids"][:3])}"}}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
