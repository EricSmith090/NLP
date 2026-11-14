"""Harvest Hán-Việt readings from the three declared catusf Hán-Việt dicts.

The official 2026-11-04 dictionary drop ships the FULL catusf dump
(3,541,369 records, zero `readings` keys — verify-G H3). The spec page 6
declares only 5 dicts, three of which are Hán-Việt and carry the readings
embedded in their definition text:

- ``Tu-dien-ThienChuu-TranVanChanh`` (22,030): ``[nhất] ① Một, ...`` /
  ``[đinh, chênh] ① Can Ðinh ...`` — readings between the first ``[``…``]``.
- ``TudienThienChuu`` (9,897): first line is pipe-separated —
  ``đinh|chênh\\n1. Can Ðinh ...``.
- ``HanziStoriesViet`` (3,189): ``HÁN VIỆT đinh, chênh\\n NGHĨA`` — readings
  after the literal ``HÁN VIỆT`` up to the next newline (or ``NGHĨA``).

This tool parses those three patterns and emits an Entry/v1-compatible
JSONL with ``readings: [{value, system: "hv"}]`` so the records can be
ingested **deliberately** by an operator who prefers harvested hv evidence
over the status quo (hvdic's char-section is the weak coverage link). It
is intentionally NOT wired into the default cache build or the adapter
list: harvested readings must be reviewed before they gate anything.

Usage:
    python tools/harvest_catusf_hv.py \
        --entries dictionaries-04-11-2026/entries/catusf.jsonl \
        --out data/dictionary/catusf_hv_harvested.jsonl

Then (manual, deliberate step): copy the output into the entries directory
as e.g. ``catusf_hv.jsonl`` and rebuild the readings cache
(``hannom charalign --rebuild-readings``). Verify the diff first.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

DECLARED_HV_DICTS = (
    "Tu-dien-ThienChuu-TranVanChanh",
    "TudienThienChuu",
    "HanziStoriesViet",
)

_SYLLABLE_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_SPLIT_RE = re.compile(r"[,;\s|]+")


def _syllable_tokens(text: str) -> list[str]:
    """Split a readings fragment into normalised QN syllable tokens."""
    out: list[str] = []
    for part in _SPLIT_RE.split(unicodedata.normalize("NFC", text).casefold()):
        if _SYLLABLE_RE.fullmatch(part):
            out.append(part)
    return out


def readings_from_tranvanchang(text: str) -> list[str]:
    match = re.match(r"\s*\[([^\]]{1,120})\]", text)
    if not match:
        return []
    return _syllable_tokens(match.group(1))


def readings_from_thienchuu(text: str) -> list[str]:
    first_line = text.split("\n", 1)[0]
    parts = first_line.split("|")
    return _syllable_tokens("|".join(parts))


def readings_from_hanzistory(text: str) -> list[str]:
    match = re.search(r"HÁN\s*VIỆT\s+([^\n]{1,120})", text)
    if not match:
        return []
    fragment = match.group(1).split("NGHĨA", 1)[0]
    return _syllable_tokens(fragment)


PARSERS = {
    "Tu-dien-ThienChuu-TranVanChanh": readings_from_tranvanchang,
    "TudienThienChuu": readings_from_thienchuu,
    "HanziStoriesViet": readings_from_hanzistory,
}


def harvest(entries_path: Path, dicts: tuple[str, ...] = DECLARED_HV_DICTS) -> tuple[list[dict], dict[str, int], dict[str, int]]:
    stats = {slug: 0 for slug in dicts}
    seen_records = 0
    skipped_unaligned = 0
    dedup_removed = 0
    seen: set[tuple[str, tuple[str, ...]]] = set()
    out: list[dict] = []
    with entries_path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            # Cheap prefilter: only lines of the three declared dicts.
            slug = None
            for candidate in dicts:
                if f'"{candidate}"' in line:
                    slug = candidate
                    break
            if slug is None:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            extra = record.get("extra") or {}
            if str(extra.get("dict") or "") != slug:
                continue
            seen_records += 1
            head = unicodedata.normalize("NFC", str(record.get("head") or "")).strip()
            if not head:
                continue
            senses = record.get("senses") or []
            text = ""
            for sense in senses:
                if isinstance(sense, dict) and sense.get("text"):
                    text = str(sense["text"])
                    break
            readings = PARSERS[slug](text)
            if not readings:
                continue
            if len(head) > 1 and len(readings) != len(head):
                # Not a positional hv transcription of a multi-cp head
                # (e.g. a gloss like "[viết tắt]" on a 3-cp head). Requiring
                # syllables == chars mirrors the cache build's _spread_word
                # validation and drops this class of false positive.
                skipped_unaligned += 1
                continue
            raw_id = str(record.get("id") or f"catusf:{slug}:{head}")
            raw_tail = raw_id.rsplit(":", 1)[-1] if ":" in raw_id else raw_id
            out_id = f"catusf-hv:{slug}:{raw_tail}"
            dedup_key = (out_id, tuple(readings))
            if dedup_key in seen:
                dedup_removed += 1
                continue
            seen.add(dedup_key)
            stats[slug] += 1
            out.append(
                {
                    "id": out_id,
                    "source": "catusf_hv",
                    "kind": "char" if len(head) == 1 else "word",
                    "head": head,
                    "script": "han",
                    "readings": [{"value": r, "system": "hv"} for r in readings],
                    "extra": {"origin": "catusf", "dict": slug, "raw_id": raw_id},
                    "ref": dict(record.get("ref") or {}),
                }
            )
    return out, stats, {"skipped_unaligned": skipped_unaligned, "dedup_removed": dedup_removed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entries", required=True, type=Path, help="Path to catusf.jsonl")
    parser.add_argument("--out", required=True, type=Path, help="Output JSONL (Entry/v1-shaped records)")
    parser.add_argument(
        "--dicts",
        default=",".join(DECLARED_HV_DICTS),
        help="Comma-separated subset of the declared Hán-Việt dicts to parse",
    )
    args = parser.parse_args()

    dicts = tuple(item.strip() for item in args.dicts.split(",") if item.strip())
    unknown = [slug for slug in dicts if slug not in PARSERS]
    if unknown:
        print(f"error: no parser for {unknown}; known: {sorted(PARSERS)}", file=sys.stderr)
        return 2

    records, stats, aux = harvest(args.entries, dicts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    readings = sum(len(r["readings"]) for r in records)
    ids = {r["id"] for r in records}
    print(f"records written : {len(records)} (unique ids: {len(ids)})")
    print(f"readings written: {readings}")
    print(f"skipped_unaligned: {aux['skipped_unaligned']}")
    print(f"dedup_removed    : {aux['dedup_removed']}")
    for slug, count in stats.items():
        print(f"  {slug}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
