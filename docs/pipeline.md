# Pipeline contracts

Stages: `intake → extract → classify → map → ocr → labels → clean → align → textdiff → evaluate → package`.

- **Extraction:** one native JPEG per PDF page, `≥3` digits, byte-for-byte when possible, lossless transpose for rotated pages. No upscaling.
- **Classification:** heuristic script/section partition from ink density; verified boundaries in book YAMLs.
- **Mapping:** T1 partition of reading-ordered sequences (ch decreasing, vi increasing) by text mass; empty-side pairs for missing pages.
- **OCR:** Nôm = Kim Hán Nôm API first; on quota exhaustion/unavailability the local engines take over and write `local_fallback/<page>.json` (API files are never overwritten). QN = Vintern-1B-v2 full-page. Cache by page; quota ledger enforces 25/50/200/600.
- **Labels:** `Label.txt`/`fileState.txt` per folder, 4 points per box, running-line detection shared with clean.
- **Clean:** NFC, remove page numbers/headers/footnotes, Nom whitespace removal, `〓` for unencodable, hyphen join preserving `A-ve`, no newlines in CSV cells.
- **Align:** cross-page join then sentence segmentation; DP for 1-1/1-n/n-1/n-m with length prior + exact reading bonus.
- **text_diff:** code-point half-open spans on NFC, `[MASK]`=6 chars excluded, span endpoints are letters, no overlapping spans, CSV authoritative.
- **Evaluate:** per-book `similarity = (1 - red/scored)×100`, gate ≥95%.
- **Package:** `ch/vi/intro/ref/toc/blank/misc/missing`, PDF + image_map + CSV/XLSX, report PDF, `source.zip`.
