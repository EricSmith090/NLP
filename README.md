# Hán Nôm – Quốc ngữ Parallel Corpus Pipeline

Local-first pipeline for the three assigned T1 books: page extraction,
script/layout classification, T1 page mapping, OCR routing, PPOCRLabel
generation, cleaning, sentence alignment, `text_diff` colouring, evaluation,
and submission packaging.

**Deadline:** 2026-11-30  
**Scope:** 3 books, 950 PDF pages, ≥95% similarity per book (not aggregate)  
**Current status (2026-11-13):** deterministic stages (0–2) complete and re-verified.
OCR: Tap1 (all 282 targets) and Tap3 (110) complete — Tap1 89.96%, Tap3 93.74%
similarity (gates FAIL: coverage <0.9, unverified >0.05 and similarity <95 for
both; closing requires human review, not code). Tap2 is only 6/550 pages OCR'd
(Nôm section unblocked only by the Kim Hán Nôm API weekly quota rollover
2026-11-16); its gate has 15 rows (85.71%), never empty anymore. Quốc ngữ OCR
uses Vintern-1B-v2 locally; Nôm uses the Kim Hán Nôm API (api_first, quota
ledger; local PaddleOCR fallback). **The T1 Nôm↔QN image maps are now built
deterministically from the printed cross-reference markers** (every substantive
QN page prints the Nôm *printed* page number in parentheses; Nôm PDF = marker
+ 2, e.g. vi013↔ch276 … vi142↔ch147 for Tap1): Tap1 130/130, Tap2 264/264,
Tap3 50/50 pairs **verified** (`mapping_source=printed_marker`); marker-verified
at packaging. The 2026-11-12 content-DP repair and its residual errors are
superseded. Nothing is claimed final; errors/similarities are all human-review
corrections away from final.

## Assigned books

| Config ID | Exact assigned filename | Pages |
|---|---|---:|
| `T1_CamPhong_Tap1` | `T1_Cấm Phòng Cho Bổn Đạo (Tập 1).pdf` | 282 |
| `T1_CamPhong_Tap2` | `T1_Cấm Phòng Cho Bổn Đạo (Tập 2).pdf` | 550 |
| `T1_SuaLoiQuyen` | `T1_Sửa Lưỡi Quyển.pdf` | 118 |
| **Total** | | **950** |

The exact assigned filename wins over cover titles. The books are
image-only and confidential.

## Verified page inventory and boundaries

All 950 pages were visually spot-checked at section transitions; the
classifier was rerun after the last extraction.

| Book | Nôm block | QN block | TOC / back matter | Blank | `image_map` |
|---|---|---:|---|---:|---|
| Book 1 | 147–276 | 21–144 | 277–282 + front TOC | 6 | 124 pairs (118 1–1, 6 2–1) |
| Book 2 | 277–540 | 9–275 | 541–550 | 6 | 264 pairs (261 1–1, 3 1–2) |
| Book 3 | 67–116 | 11–63 (p61 blank) | 117–118 | 6 | 50 pairs (48 1–1, 2 1–2) |

Book 2 has 525 pages at 800×1135 and 25 native rotated scans at 564×800.
Book 3 page 61 is blank and is excluded from `vi/`. Two earlier
`nom_end_hint` values were off by one; the corrected, visually verified
values are in the book configs and `docs/decisions.md`.

Extraction fidelity after the final re-extraction:

- 950 unique JPEGs, one per page, no duplicate hashes;
- 923 pages copied byte-for-byte from the embedded JPEG stream;
- 27 rotated pages transposed at native resolution (90-degree transpose, JPEG re-encode q95 4:4:4; no resampling; not a DCT-domain lossless transform);
- no page was upscaled or rendered at a larger size;
- `<BookName>_updated.pdf` was generated for the two books with rotated
  pages (`data/output/<book_id>/<BookName>/`, built with
  `python tools/build_updated_pdf.py --all`): one native image per page,
  page count identical to the assigned PDF, embedded bytes identical to the
  extracted JPEGs. Book 3 needed none. Merging them into the submission and
  notifying the handout person is a mandatory human step before hand-in.

## Non-negotiable rules enforced by the code

- `.jpg` only; native resolution; page numbering starts at 1; one PDF
  page = one image; two-page spreads are never split.
- Alignment never silently drops a sentence: a collapsed co-cut is emitted
  as an `UNMATCHED_QN`/`UNMATCHED_NOM` row, and `stage_align` asserts
  stream-vs-emitted QN token parity fail-closed.
- Every submitted image has a `Label.txt` row and a `fileState.txt` line;
  every `fileState.txt` value is `1`; boxes have exactly four points.
- T1 reading order: QN increasing page numbers, Nôm decreasing page
  numbers, right-to-left/top-to-bottom for Nôm.
- `text_diff` is `null` for non-1–1 rows and `[]` for compared-and-identical
  rows. Positions are 0-based half-open Unicode code-point ranges on NFC
  text. `[MASK]` is exactly six characters and is excluded from the
  evaluation denominator.
- CSV is authoritative over XLSX colours; the XLSX is generated from the
  same `text_diff` and validated against it.
- Unknown or missing evidence is routed to review. A character is never
  auto-red merely because an incomplete dictionary lacks it. Yellow is
  never generated automatically.
- The quality gate is evaluated separately for each book.
- Confidential scans are never sent to third-party cloud OCR/GPU/Hugging
  Face. The only approved external service is Kim Hán Nôm API.

## Repository layout

```text
.
├── README.md
├── USER_GUIDE.md
├── pyproject.toml
├── .env.example
├── configs/
│   ├── project.yaml
│   ├── report.yaml              # members + mandatory screenshots
│   ├── ocr.yaml
│   ├── alignment.yaml
│   ├── dictionary.yaml
│   ├── review.yaml
│   └── books/*.yaml
├── src/hannom/                  # pipeline, OCR adapters, validators
├── tools/
│   ├── benchmark_ocr.py
│   ├── capture_screenshots.py
│   └── validate_submission.py
├── tests/                       # 352 tests, no OCR runtime required
├── docs/
│   ├── decisions.md
│   ├── pipeline.md
│   └── review_guide.md
├── CV20-24127189/               # confidential PDFs, never committed
├── data/                        # working artifacts, never committed
└── artifacts/                   # reports/screenshots, never committed
```

## Install

Core pipeline (Python 3.11+; tested on 3.13.9):

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

The default install deliberately excludes OCR frameworks. They are pinned
only after a local benchmark; see `pyproject.toml` and `USER_GUIDE.md`.
On Windows, set UTF-8 output before running commands that print Vietnamese
filenames:

```powershell
$env:PYTHONIOENCODING='utf-8'
```

## Run the pipeline

```powershell
$env:PYTHONIOENCODING='utf-8'

python -m hannom.cli intake
python -m hannom.cli extract
python -m hannom.cli classify
python -m hannom.cli map
python -m hannom.cli ocr                 # Nôm: Kim Hán Nôm API first (quota-gated), local fallback on quota; QN: Vintern
python -m hannom.cli labels
python -m hannom.cli clean
python -m hannom.cli align
python -m hannom.cli textdiff
python -m hannom.cli evaluate
python -m hannom.cli review --book T1_SuaLoiQuyen
python -m hannom.cli package-all
python tools/validate_submission.py data/output
```

Useful variants:

```powershell
python -m hannom.cli pilot --book T1_SuaLoiQuyen
python -m hannom.cli status
python -m hannom.cli ocr --book T1_SuaLoiQuyen --limit 3
python -m hannom.cli extract --book T1_CamPhong_Tap2 --force
python -m hannom.cli source-zip
python -m hannom.cli split
python tools/build_updated_pdf.py --all   # rebuild <Book>_updated.pdf if images changed
```

`pilot` stops with `status=blocked_ocr` when no OCR engine is available
instead of pretending later stages can run. `data/state.sqlite3` records
stages, hashes, and metrics so a rerun resumes rather than redoing work.

## OCR policy

- Nôm OCR: the Kim Hán Nôm API is used first (`api_mode: api_first`, the
  guideline's ưu tiên). Once the quota (25/min, 50/h, 200/day, 600/week) is
  exhausted or the API cannot serve a page, the pipeline switches to the
  local PP-OCRv5/PaddleOCR-VL models; those results are written to
  `data/ocr/<book>/local_fallback/<page>.json` so they never clash with the
  API-handled files in `data/ocr/<book>/`. `load_result` prefers the
  API-handled file and falls back to the local fallback file. Local-only
  runs remain available via `api_mode: local_only`.
- QN OCR: Vintern-1B-v2 (Vietnamese-native VLM) is primary. benchmark on
  pages 11/41 gave near-perfect transcription of the archaic spelling,
  ~35 s/page, peak 2.3 GB VRAM (RTX 4060, 8 GB). Forces 1 full-page box
  per image (guideline p.12 allows one box per page). The Kim Hán Nôm API
  is Hán/Nôm-only and must not receive QN pages.
- PaddleOCR's latin/ch models are not used for QN anymore; they drop
  Vietnamese tone marks systematically (128 distinct affected tokens in
  Book 3, e.g. `dēn` for `đến`, `muōn` for `muốn`).
- The API token is read from `KIMHANNOM_TOKEN` (`.env` is supported and is
  never packaged).
- The API client is single-threaded, caches by image SHA-256, applies
  exponential backoff, and records a quota ledger for the documented
  25/minute, 50/hour, 200/day, 600/week limits.
- Multiple accounts are not used to bypass quota. When the quota is reached,
  the pipeline falls back to local models for the remaining Nôm pages
  instead of stalling or exceeding the limits.
- No token, model weight, confidential PDF, `data/`, or `artifacts/`
  directory enters `source.zip`.

## Submission package

One ZIP contains three sibling book folders, one report PDF, `source.zip`,
and optional `extras.zip`:

```text
<MSSV1_MSSV2_MSSV3_MSSV4>.zip/
├── T1_Cấm Phòng Cho Bổn Đạo (Tập 1)/
│   ├── ch/  vi/  intro/  ref/  toc/  blank/  misc/  missing/
│   ├── T1_Cấm Phòng Cho Bổn Đạo (Tập 1).pdf
│   ├── T1_Cấm Phòng Cho Bổn Đạo (Tập 1)_image_map.json
│   ├── T1_Cấm Phòng Cho Bổn Đạo (Tập 1).csv
│   └── T1_Cấm Phòng Cho Bổn Đạo (Tập 1).xlsx
├── T1_Cấm Phòng Cho Bổn Đạo (Tập 2)/ ...
├── T1_Sửa Lưỡi Quyển/ ...
├── <MSSV...>_report.pdf
├── source.zip
└── extras.zip              # optional
```

The guideline's tree shows one book folder; three sibling folders are a
documented extension requested for this assignment. `hannom split` creates
one ZIP per book if an instructor later requires the one-book form.

Before packaging, fill `configs/report.yaml` with all four members'
names/IDs/emails, run the real pipeline, and capture the four mandatory
screenshots. The report validator intentionally fails while any of these
are missing.

## Quality gate

```text
accuracy (similarity %, verified rows only) =
  (1 - mismatched_red_characters / scored_nom_characters) × 100

coverage = (verified_match_rows + verified_difference_rows) / total_rows
```

- Denominator: Nôm characters in rows with comparison evidence and a
  valid `text_diff`; excludes QN text, punctuation, `[MASK]`, yellow
  characters. Accuracy is never computed over unverified rows.
- Numerator: for each `error` element, `max(Nôm characters, QN syllables)`.
- Coverage/unverified/null gates (configurable in `configs/project.yaml`
  `quality`): `minimum_coverage: 0.9`, `max_unverified_ratio: 0.05`, and
  `null_ratio_warn: 0.05` now blocks under `EXCESSIVE_NULL_ROWS`.
- Gate: accuracy ≥95% plus coverage ≥0.9, unverified ≤0.05 and null ≤0.05
  for each of the three books. Insufficient evidence yields a failing,
  inconclusive evaluation, never a pass.
- The report records yellow-character ratio, null-row ratio, coverage, and
  per-class row counts (verified/unverified/unmatched).

No final similarity is claimed yet. It will be measured after OCR and
review; drafts are never used as evidence.

## Documentation

- `USER_GUIDE.md` — end-to-end run, OCR setup, review, screenshots,
  packaging, troubleshooting.
- `docs/pipeline.md` — stage contracts, state model, invariants, data flow.
- `docs/decisions.md` — decisions and explicit guideline contradictions.
- `docs/review_guide.md` — review queue, error codes, human sign-offs.

## Environment used for verification

- Windows 11, Python 3.13.9 (`D:\anaconda3\python.exe`), 15.7 GB RAM.
- NVIDIA RTX 4060 Laptop GPU, 8 GB VRAM (used by Vintern-1B-v2 for QN OCR).
- Local OCR (Nôm draft + geometry): paddlepaddle 3.3.1, paddleocr 3.7.0
  (+ opencv-contrib-python 4.10.0.84). paddlex defaults to oneDNN run mode,
  which crashes on this host (`pir::ArrayAttribute<pir::DoubleAttribute>` on
  the PIR path); the local adapter forces `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=false`
  and uses PP-OCRv5 mobile det/rec. PyYAML stays at the pinned 6.0.3
  (paddlex 3.7.2 requests 6.0.2).
- Vintern-1B-v2 (QN primary): torch 2.14.1+cu126, torchvision 0.29.1+cu126
  (install via `--index-url https://download.pytorch.org/whl/cu126`),
  transformers 4.46.3 (5.x incompatible), einops 0.8.2, timm 1.0.31,
  accelerate 1.15.0. A no-op `flash_attn` shim exists in site-packages; the
  stock model config sets `use_flash_attn=False`.
- PyMuPDF 1.28.2, NumPy 2.2.6, SciPy 1.16.3, Pillow 12.3.0,
  pandas 2.3.3, openpyxl 3.1.5, PyYAML 6.0.3, pydantic 2.12.4,
  Typer 0.20.0, Rich 14.2.0, Streamlit 1.51.0, pytest 8.4.2.

## Do not

- Do not upload the book PDFs or page images to any unapproved service.
- Do not commit `CV20-24127189/`, `data/`, `models/`, `artifacts/`, or
  `.env`.
- Do not skip difficult pages; route them to review.
- Do not modernize archaic Vietnamese spellings.
- Do not use yellow to inflate the score.
- Do not auto-red a character just because a dictionary is incomplete.
