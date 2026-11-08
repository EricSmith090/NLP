# Hán Nôm–Quốc ngữ Parallel Corpus — Project Plan

**Status:** Planning / pre-implementation  
**Created:** 2026-11-08  
**Deadline:** 2026-11-30  
**Workspace:** `C:\Users\MSI VN\Desktop\NLP Project`  
**Entry point:** This document. No pipeline code exists yet.

**TL;DR:** Three T1 books (950 pages) are due 2026-11-30. Build a local-first OCR/alignment pipeline; use Kim Hán Nôm API only as a measured second opinion. Deliver one ZIP with three book folders, one report, PPOCRLabel labels, CSV/XLSX alignment, and `image_map.json`. Enforce ≥95% per book. No pipeline code exists yet; start with §13.

---

## 0. How to use this document

Read this before touching the data or writing code.

- The **main guideline is the source of truth**: `Quy_định_đồ_án_v2.1.pdf`.
- If the user's or instructors' instructions contradict the guideline, **say so explicitly**; do not silently implement the contradiction.
- The three book PDFs are **confidential**. Do not upload them to third-party hosted APIs, cloud OCR, cloud GPU, or Hugging Face. The only approved external service is the Kim Hán Nôm API.
- The model may not read PDFs directly. Extract text with PyMuPDF/PyMuPDF4LLM. The three guideline PDFs have a text layer; the three book PDFs are **image-only**, so they require OCR.
- Filenames contain Vietnamese Unicode, sometimes in decomposed (NFD) form. Use Python `glob`/`pathlib` rather than typing filenames manually.

---

## 1. Project goal

Build a sentence-aligned parallel corpus between **Hán Nôm** and **Quốc ngữ** for three assigned T1 books, then submit the standardized package defined by the guideline:

- page images;
- PPOCRLabel OCR annotations;
- CSV/XLSX alignment with `text_diff` and colouring;
- `image_map.json` for T1 page mapping;
- report PDF;
- source ZIP;
- optional extras.

The pipeline must be automatic end-to-end. Human work is limited to mandatory sign-offs and **flagged errors only**, not a full manual transcription/alignment pass.

---

## 2. Authoritative source documents

| File | Role | Key facts |
|---|---|---|
| `Quy_định_đồ_án_v2.1.pdf` | Main project specification | 29 pages; v2.1 dated 06/11/2026. Scope, workflow, image rules, PPOCRLabel, bounding boxes, text cleaning, alignment, `text_diff`, evaluation, submission structure, report/source requirements, appendices for T1/T2/T2b/plain-text/etc. |
| `Mô tả dữ liệu từ điển Hán Nôm và Quốc ngữ.pdf` | Dictionary dataset description | 6 pages; v1 dated 03/11/2026. 12 sources, ~969,000 entries; `entries/<source>.jsonl` with shared `Entry` schema. It describes an existing dataset; it is not an explicit scraping assignment. Known gaps: `hvdic`/`dv` incomplete, cross-source duplicates not removed, `freq` empty |
| `Hướng dẫn sử dụng API Kim Hán Nôm.pdf` | OCR API manual | 10 pages; API version 2026-10-10. Four endpoints, auth headers, response envelope, enums, rate limits, `image-rec` fallback. |
| `CV20-24127189/*.pdf` | Assigned book data | Three T1 books, 950 pages total, image-only 800×1135 px, no text layer. |

### Source-of-truth hierarchy

1. `Quy_định_đồ_án_v2.1.pdf`.
2. API manual for API-specific details.
3. Dictionary description for dictionary data (optional support).
4. User/instructor decisions recorded in this plan.
5. This plan.

If a lower item conflicts with a higher item, flag it and follow the higher item unless the instructors explicitly override it in writing.

---

## 3. Actual assigned data

Current path: `CV20-24127189/`.

| Book ID for config | Exact assigned filename | Pages |
|---|---|---:|
| `T1_CamPhong_Tap1` | `T1_Cấm Phòng Cho Bổn Đạo (Tập 1).pdf` | 282 |
| `T1_CamPhong_Tap2` | `T1_Cấm Phòng Cho Bổn Đạo (Tập 2).pdf` | 550 |
| `T1_SuaLoiQuyen` | `T1_Sửa Lưỡi Quyển.pdf` | 118 |
| **Total** | | **950** |

- Use the **exact assigned filename** for the submission book folder. Do not use the cover title if it differs.
- Book 1/2 covers read “CẤM PHÒNG CHO BỔN ĐẠO”; the filename says `Bổn Đạo`.
- Book 3 filename says `Sửa Lưỡi Quyển`; the cover reads “SỬA LỖI QUYỂN”. The filename wins.
- Git shows a rename from `CV20-Phạm Trần Đăng Khoa-24127189/` to `CV20-24127189/`; treat `CV20-24127189/` as current. Do not rely on git history for source data.

### Page-layout estimate (heuristic, not OCR-verified)

| Book | Pages | Likely Nôm | Likely Quốc ngữ | Blank/mixed |
|---|---:|---:|---:|---:|
| T1_CamPhong_Tap1 | 282 | ~128 | ~144 | ~10 |
| T1_CamPhong_Tap2 | 550 | ~242 | ~282 | ~26 |
| T1_SuaLoiQuyen | 118 | ~51 | ~60 | ~7 |
| **Total** | **950** | **~421** | **~486** | **~43** |

These counts come from a projection-profile heuristic on the page images. **Verify them in the pilot.** Approximate Nôm sections: Book 1 ~147–276, Book 2 ~278–536, Book 3 ~67–116.

### T1 layout — critical

The books are **T1**:

- Quốc ngữ is at the front, read **1 → N**, left-to-right/top-to-bottom.
- Nôm is at the end, read **N → 1** (decreasing page numbers), right-to-left/top-to-bottom.
- Quốc ngữ page 1 may correspond to Nôm page 200; QN page 2 to Nôm 199; etc.
- One QN page may correspond to multiple Nôm pages.
- A page may mix scripts (e.g., Book 3 p116 has Nôm text and a QN table of contents). Treat mixed pages per page, not per book: duplicate the image into `ch/` and `vi/`, keep only the relevant boxes in each.
- Generate `image_map.json` with `ch` arrays in reading order (decreasing page numbers for T1).

Example:

```json
{
  "pairs": [
    { "ch": ["Book.200.jpg"], "vi": ["Book.001.jpg"] },
    { "ch": ["Book.199.jpg"], "vi": ["Book.002.jpg"] },
    { "ch": ["Book.198.jpg", "Book.197.jpg"], "vi": ["Book.003.jpg"] }
  ]
}
```

### Scan quality

- 800×1135 px, image-only, one image per page.
- Yellowed paper, skew, library stamps, black borders, some blank pages.
- No higher-resolution copies exist. Preserve native resolution in the submission.
- The guideline says to contact the handout person if **>20% of Nôm pages** are torn/blurred/poor quality. Measure this in the pilot; if exceeded, stop and ask the user to contact the handout person.

---

## 4. Fixed decisions

| Item | Decision | Rationale / note |
|---|---|---|
| Scope | All three books, 950 pages | Confirmed by user |
| Deadline | 2026-11-30 | ~23 calendar days from plan creation |
| Quality gate | **≥95% per book**, not aggregate | Guideline says “của sách”; confirmed by user |
| Packaging | **One ZIP containing three book folders**, one report | Guideline tree shows one book folder; three siblings is an extension. Note it in README/report; provide a split script if instructors later require one ZIP per book |
| OCR | Local models for the majority; Kim Hán Nôm API as measured second opinion | Quota/confidentiality/no-budget risk reduction |
| External services | Kim Hán Nôm API only; no other third-party hosted API/cloud | Confidentiality; user approval |
| Budget | No paid tools; local/open-source only | User has no budget |
| Dictionary | Do not depend on official 12-source JSONL; build an adapter and sidestep | Instructors silent; dataset description is not a scraping task |
| Preprocessing | Follow guideline literally; no hidden dual-image versions | See §7.3 |
| Review tooling | PPOCRLabel for boxes; Streamlit for alignment/`text_diff` | PPOCRLabel is required format; Streamlit is already installed and faster for alignment review |
| Report | Follow guideline content list, with per-book metrics | User confirmed |
| Zip name | `<MSSV1_MSSV2_MSSV3_MSSV4>.zip` | Only `24127189` is known from the folder name; ask for the other MSSVs |

### Decision flags

- **Local-majority Nôm OCR** deviates from the guideline's “ưu tiên Kim Hán Nôm”. It is a priority, not a hard prohibition. Document the reason; the router can be flipped to API-first.
- **Dictionary sidestep** means dictionary misses cannot be automatically marked red with full confidence. Route them to review; do not auto-red.
- **One ZIP with three books** is an extension of the guideline's one-book tree. Document it.
- **No other third-party API/cloud** overrides the guideline's general permission to use paid/free tools.
- **Do not use multiple API accounts** to bypass quota unless instructors explicitly authorize it in writing.

---

## 5. Non-negotiable guideline requirements

This is the acceptance checklist. Do not lose sight of it while building.

### 5.1 Images

- Format: `.jpg` only.
- Naming: `<BookName>.<page number 3+ digits>[_<image index>].jpg`.
- Page numbering starts at 1 from `<BookName>_updated.pdf` if it exists, otherwise the original PDF.
- Two-page spread = **one image and one page number**. Do not split for convenience.
- Use `[_<image index>]` only when a page contains more than one Nôm/QN image; order left-to-right, top-to-bottom / reading order.
- Preserve native resolution; no duplicate images in the merged PDF.
- Correct orientation for every image; if any image is changed, create `<Book>_updated.pdf` and report it.
- Missing pages due to scanning:
  - missing Nôm page, existing QN translation → keep Nôm image in both `ch/` and `missing/ch/`;
  - missing QN page, existing Nôm page → remove QN image from `vi/`, keep only in `missing/vi/`, do not OCR unless requested;
  - missing in the original source itself → do nothing.

### 5.2 PPOCRLabel

- `Label.txt`: one line per image; `<folder>/<image>.jpg` + TAB + JSON array of boxes.
- Each box: `transcription`, `points` with **exactly 4 points**.
- Coordinates must match the exact submitted image; rescale if the image was resized/rotated.
- `fileState.txt`: one line per image; `path` + TAB + `1` (completed) or `0`.
- At submission: **every** `fileState.txt` line is `1`; **every** image has a `Label.txt` line.
- Optional `Label_char.txt` / `fileState_char.txt` for per-character boxes.
- Extra fields allowed if documented; `difficult` from the API does not need documentation.

### 5.3 Bounding boxes

- Tight boxes; no adjacent lines/characters.
- Skip illustrations; **tables are still OCR’d**.
- Remove page numbers, running headers, book titles, footers, library stamps, ownership marks, external notes. Keep chapter/section titles if translated.
- Nôm: vertical columns, **right-to-left, top-to-bottom**; horizontal Nôm by line, left-to-right.
- QN: line/paragraph boxes if supported, otherwise one box per page; left-to-right, top-to-bottom.
- Spaced columns → separate boxes; two-component Nôm characters → two boxes; double-line small notes → two boxes, right column first.
- Illegible text: box the whole column; use phonetic translation to infer if available; otherwise `[MASK]` per missing character after counting from the image.
- Torn page: box only up to the tear. Faded but readable: box normally.
- Distinguish blank pages from show-through.

### 5.4 Text cleaning

- Remove non-content: page numbers, headers/footers, footnotes, inline reference markers, translator notes, OCR garbage, duplicate OCR lines.
- Normalize punctuation without changing meaning.
- Preserve proper names, era names, numbers, units.
- Nôm: no spaces between characters; use appropriate `、。！？；：`; do not invent punctuation; valid Unicode/fonts; unencodable character → `〓` (U+3013) and list in report.
- QN: preserve original spelling, archaic words, old tone placement; only fix OCR errors; normal Vietnamese spacing/punctuation; one sentence per alignment row; join hyphenated line breaks when the hyphen is only a line-break artifact; keep hyphens in names (e.g., `A-ve`); no newline inside CSV/XLSX cells.
- NFC-normalize all text before computing positions.

### 5.5 Alignment

- Join sentences broken across pages before sentence splitting.
- `sentence_id` format: `<img_id without .jpg>.<sentence number>` (e.g., `Book.024.1`).
- Reading order follows the book: T1 Nôm is reverse page order; two-page spread rules apply.
- Accepted types: **1–1, 1–n, n–1, n–m**. Prefer the smallest meaningful unit; do not mechanically split punctuation if it destroys the translation relation.
- CSV columns: `img_id`, `sentence_id`, `ch_txt`, `vi_txt`, `text_diff`.
- XLSX has the same columns plus colour:
  - **black** = same meaning;
  - **red** = different meaning, or Nôm character not found in any dictionary after all checks;
  - **yellow** = only the guideline’s special cases: names/years with different char counts but same meaning; predicted Nôm from QN due to blur; predicted Nôm due to missing scanned Nôm page; predicted QN from Nôm due to missing scanned QN page.
- Non-phonetic translations: `text_diff = null`, no colour.
- CSV must open in Excel/Google Sheets; UTF-8 with BOM recommended.
- CSV `text_diff` is authoritative over XLSX colours.

### 5.6 `text_diff`

- Valid UTF-8 JSON array. `[]` = compared and identical; `null` = not compared/non-1–1.
- Each element: `nom_pos`, `nom_sub_text`, `vi_pos`, `vi_sub_text`, `type` (`warn`/`error`).
- Positions are 0-based **half-open** `[start, end)`, counted by **Unicode code point**, on the exact NFC string in the cell.
- `[MASK]` occupies exactly 6 characters, is never inside a position, is black, and is excluded from the evaluation denominator.
- A side with no corresponding text: `pos: []`, `text: ""`; both sides cannot be empty.
- No overlapping positions of different types; colours in XLSX must match `text_diff`.
- Use a CSV library, not manual string concatenation.

### 5.7 Evaluation

```text
similarity (%) = (1 - mismatched_red_characters / scored_nom_characters) × 100
```

- Denominator: only Nôm characters in rows with `text_diff != null`; excludes QN, punctuation, `[MASK]`, and yellow characters.
- Numerator: for each `error` element, take `max(number of Nôm characters, number of QN syllables)`, then sum.
- Gate: **≥95% per book**.
- Report yellow-character ratio over total Nôm characters and null-row ratio over all rows.
- Yellow must not be used to inflate the score.

### 5.8 Report and source

Report `<MSSV...>_report.pdf` — one PDF covering all three books, with a summary and per-book sections:

- member full names, student IDs, student emails;
- what the group did: model setup, crawling, etc.;
- yellow ratio and reason;
- null-row ratio;
- citations;
- appendix screenshots: Nôm page in PPOCRLabel, QN page in PPOCRLabel, XLSX opened, CSV opened without column shift.
- Screenshots are mandatory. Automate with `tools/capture_ppocrlabel_screenshots.py`; if GUI automation is unreliable, capture once manually. This is a reporting task, not data correction.

`source.zip`:

- `README.md`: detailed project description and run overview;
- pinned dependencies;
- `USER_GUIDE.md`: end-to-end run on a new machine with submitted data;
- paid tools/models/prompts/token setup fully documented (even though this project uses no paid tools);
- environment: Python version, OS (Ubuntu preferred), RAM, GPU, etc.;
- Colab: pinned deps, runtime, secrets.

### 5.9 Submission tree

```text
<MSSV1_MSSV2_MSSV3_MSSV4>.zip/
├── <BookName>/
│   ├── ch/
│   │   ├── <BookName>.001.jpg ...
│   │   ├── Label.txt
│   │   ├── fileState.txt
│   │   ├── Label_char.txt          # optional
│   │   └── fileState_char.txt      # optional
│   ├── vi/
│   │   ├── <BookName>.001.jpg ...
│   │   ├── Label.txt
│   │   └── fileState.txt
│   ├── intro/                      # optional
│   ├── ref/                        # optional
│   ├── toc/                        # optional
│   ├── blank/
│   ├── misc/
│   ├── missing/
│   │   ├── ch/
│   │   └── vi/
│   ├── <BookName>.pdf
│   ├── <BookName>_updated.pdf      # if any submitted image changed
│   ├── <BookName>_image_map.json   # important for T1
│   ├── <BookName>.csv
│   └── <BookName>.xlsx
├── <MSSV1_MSSV2_MSSV3_MSSV4>_report.pdf
├── source.zip
└── extras.zip
```

For this assignment, one ZIP contains three sibling book folders, one report, one `source.zip`, and optional `extras.zip`.

---

## 6. Architecture

```text
PDF
 → 0. Intake / scope lock
 → 1. Page extraction
 → 2. Layout/script classification + T1 mapping
 → 3. OCR routing + ensemble
 → 4. PPOCRLabel generation + validation
 → 5. Text cleaning / dictionary normalization
 → 6. Sentence segmentation + alignment
 → 7. text_diff + colouring
 → 8. Evaluation / QA gates
 → 9. Packaging + report
        ↑
   review queue only for flagged exceptions
```

| Stage | Automatic work | Output | Human trigger |
|---|---|---|---|
| 0. Intake | Hash PDFs, page count, printed page numbers, scope config; no mass OCR before lock | `book.yaml`, manifest, checksums | **Mandatory:** confirm title, volume, page range, sources, formats |
| 1. Extraction | Native-res JPG, naming, spread preservation, checksums, duplicate/missing detection | `pages/`, `pages.jsonl` | Orientation/order ambiguous, split page |
| 2. Classification / T1 map | Script/layout per page/region; ch/vi/intro/ref/toc/blank/misc; T1 boundary; mixed pages; `image_map.json` | Folder assignments, map | Uncertain boundary, mixed page, missing page |
| 3. OCR | Local majority; API sample/low-confidence; cache; quota ledger; `image-rec` fallback | Raw OCR JSON, confidence | Low confidence, engine disagreement, invalid bbox |
| 4. Labels | PPOCRLabel conversion; 4-point boxes; script filtering; duplicate mixed images; validator | `Label.txt`, `fileState.txt` | Validator failure; box edits in PPOCRLabel |
| 5. Cleaning | Header/footer/stamp removal; NFC; punctuation; dictionary; spellcheck; `[MASK]`/`〓` | Clean text + flags | Illegible char, dictionary conflict, archaic spelling |
| 6. Alignment | Cross-page join; segmentation; phonetic + embedding alignment; DP; 1–1/1–n/n–1/n–m | Draft CSV | Low confidence, unusual merge |
| 7. `text_diff` | Reading-based character alignment; dictionary senses; red/yellow/black; exact positions; XLSX colours | Final CSV/XLSX | Semantic ambiguity, proper names, unknown chars |
| 8. Evaluation | Formula, coverage, validators, 95% per-book gate | Metrics, failure list | Gate failure only |
| 9. Packaging | ZIP tree, report, screenshots, source, validator | Final ZIP | Member info + final sign-off |

---

## 7. Key technical choices and rationale

### 7.1 OCR: local majority + API second opinion

**Why:** the Kim Hán Nôm quota is 600 calls/week; each image needs at least 2, realistically 3 calls. All 421 estimated Nôm pages would need 842–1,263 calls (~1.4–2.7 weeks plus retries), leaving little buffer. Local models are free, keep confidential data on-machine, and can process the QN bulk quickly.

**Model plan for 8 GB VRAM / 16 GB RAM:**

- Quốc ngữ: `Vintern-1B-v2` primary; `PaddleOCR-VL` / PP-OCRv5 fallback.
- Nôm: `PaddleOCR-VL` or PP-OCRv5 local primary; Kim Hán Nôm API for low-confidence pages and validation.
- Run models **sequentially**, batch size 1–4; unload between stages. Do not attempt a 7B ensemble.
- If PaddleOCR-VL installation fails on Windows, fall back to PP-OCRv5 or a Transformers-based OCR model.

**API safety measurement:**

- Sample 20–30 Nôm pages stratified by book and quality (40–90 calls, ~7–15% of weekly quota).
- Measure calls/page, latency, errors, agreement with local OCR, readability.
- Allocate quota to lowest-confidence Nôm pages first.
- If the token arrives late, proceed local-only and integrate API later.

**API operational rules:**

- Base URL: `https://kimhannom.fit.hcmus.edu.vn`.
- Endpoints: `image-upload`, `structure-classification`, `image-ocr`, `image-rec`.
- Headers: `Authorization: Bearer <token>` and the exact documented `User-Agent`.
- Python `requests` User-Agent must not start with `python-requests`.
- Token in `.env`; never in logs, Git, or `source.zip`.
- Single-threaded, delayed, exponential backoff, cache by image SHA-256, quota ledger.
- Verify the actual `image-ocr` response schema on day one: the API manual says `result_ocr_text`/`result_bbox`; the project guideline mentions `details.details`. Do not code against an assumption.
- Rate limits: 25/minute, 50/hour, 200/day, 600/week.
- Enums: `ocr_id` 1 normal vertical, 2 administrative, 3 outdoor, 4 normal horizontal; `lang_type` 0 unknown, 1 Hán, 2 Nôm; `reading_direction` 1 vertical, 2 horizontal; `epitaph` 0 normal, 1 epitaph.

### 7.2 Dictionary sidestep

**Why:** the official `entries/*.jsonl` dataset is not confirmed available; the description PDF is not a scraping assignment; scraping 12 sources in 23 days is not realistic and may violate terms.

Build an adapter interface:

```text
DictionaryIndex
├── JsonlDictionary        # official entries/*.jsonl if provided
├── UnihanAdapter          # kVietnamese, kDefinition
├── CcCedictAdapter        # Hán–English meanings
├── MakeMeAHanziAdapter    # decomposition/radicals
├── CjkviAdapter           # IDS/variants
└── BookLexicon            # learned from this book's Nôm–QN alignment
```

- The **book lexicon** is important: phonetic translations provide character-to-syllable evidence. Learn it per book.
- For `text_diff`: reading match + dictionary sense + book lexicon → black; clear semantic mismatch → red; unknown/missing evidence → **review**.
- Do **not** auto-red a character merely because it is absent from an incomplete dictionary. Log which sources were checked.
- If the official JSONL arrives later, plug it in without rework.

### 7.3 Preprocessing

Follow the guideline literally:

- **Default:** extract original images and OCR those same images; no `_updated.pdf`.
- **If enhancement is necessary:** use enhanced images for **both** OCR and submission, generate `<Book>_updated.pdf`, and report the change.
- Do not keep original images for submission and a secret enhanced copy for OCR. That creates coordinate/provenance mismatch and is arguably against the guideline.
- Labels and boxes always correspond to the exact submitted image.

### 7.4 Alignment

- Join cross-page sentences before splitting.
- Use phonetic reading similarity + `Bertalign`/`Vecalign`/`SentAlign`; dynamic programming for 1–1, 1–n, n–1, n–m.
- Prefer the smallest meaningful unit; do not mechanically split punctuation if meaning is lost.
- Confidence score per row; low confidence goes to review.
- T1 Nôm reading order is reverse page order.

### 7.5 `text_diff`

- Generate positions algorithmically from the exact strings; never let an LLM invent positions.
- Use character-reading alignment and dictionary senses for black/red/yellow.
- Unknown or ambiguous semantic decisions go to review.
- CSV is authoritative; XLSX colours must match.

### 7.6 Review tooling

- **PPOCRLabel** for box edits (required format, existing tool).
- **Streamlit** for text/alignment/`text_diff` review: page image, boxes, side-by-side alignment, colour spans, keyboard shortcuts, export patches.
- Every human edit is logged (reviewer, timestamp, before/after, reason).
- Re-running the pipeline must not overwrite reviewed pages.

---

## 8. Project structure

### 8.1 Code repository

```text
han-nom-parallel/
├── README.md
├── USER_GUIDE.md
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── .env.example
├── .gitignore
├── configs/
│   ├── project.yaml
│   ├── books/
│   │   ├── T1_CamPhong_Tap1.yaml
│   │   ├── T1_CamPhong_Tap2.yaml
│   │   └── T1_SuaLoiQuyen.yaml
│   ├── ocr.yaml
│   ├── dictionary.yaml
│   ├── alignment.yaml
│   └── review.yaml
├── src/hannom/
│   ├── cli.py
│   ├── orchestrator.py
│   ├── state.py
│   ├── intake.py
│   ├── pages.py
│   ├── layout.py
│   ├── t1_map.py
│   ├── ocr/
│   │   ├── router.py
│   │   ├── kimhannom.py
│   │   ├── local_vintern.py
│   │   ├── local_paddle.py
│   │   ├── agreement.py
│   │   └── quota.py
│   ├── labels.py
│   ├── clean.py
│   ├── dictionary/
│   │   ├── index.py
│   │   ├── jsonl.py
│   │   ├── open_sources.py
│   │   └── book_lexicon.py
│   ├── align.py
│   ├── textdiff.py
│   ├── evaluate.py
│   ├── package.py
│   ├── report.py
│   └── review/
│       ├── app.py
│       └── patches.py
├── tools/
│   ├── benchmark_ocr.py
│   ├── validate_submission.py
│   └── capture_ppocrlabel_screenshots.py
├── tests/
│   ├── test_naming.py
│   ├── test_bbox.py
│   ├── test_t1_map.py
│   ├── test_quota.py
│   ├── test_textdiff_positions.py
│   ├── test_evaluation.py
│   └── test_packaging.py
├── dictionaries/              # optional official JSONL
├── models/                    # local weights, not committed
├── data/                      # working artifacts, not committed
│   ├── pilot/
│   ├── pages/
│   ├── ocr/
│   ├── labels/
│   ├── clean/
│   ├── align/
│   ├── review/
│   └── output/
├── artifacts/
│   ├── pilot/
│   └── runs/
└── docs/
    ├── decisions.md
    ├── pipeline.md
    └── review_guide.md
```

### 8.2 State and provenance

Use SQLite or JSONL manifests, not ad-hoc filenames:

```text
pages:
  page_id, book_id, pdf_page, image_name, sha256, width, height,
  script, section, folder, status, ocr_engine, ocr_confidence, review_flags

api_calls:
  call_id, endpoint, image_sha256, token_id, requested_at,
  status, response_path, quota_day, quota_week

reviews:
  review_id, page_id, field, before, after, reviewer, reason, timestamp

runs:
  run_id, git_commit, config_hash, model_versions, started_at, finished_at
```

This provides resumability, no repeated API calls, provenance for human changes, and quota accounting.

### 8.3 Working data

```text
data/
├── raw/<book_id>/original.pdf
├── pages/<book_id>/native/*.jpg
├── pages/<book_id>/ocr_derived/*.jpg     # only if enhancement is used
├── ocr/<book_id>/<page_id>.json
├── labels/<book_id>/ch/Label.txt
├── labels/<book_id>/vi/Label.txt
├── clean/<book_id>/<page_id>.json
├── align/<book_id>/<Book>.csv
├── review/<book_id>/queue.jsonl
└── output/<book_id>/<Book>/...
```

Confidential PDFs and `data/` stay out of Git. `source.zip` excludes data, models, tokens, and secrets.

### 8.4 Config example

```yaml
book_id: T1_CamPhong_Tap1
pdf: "CV20-24127189/T1_Cấm Phòng Cho Bổn Đạo (Tập 1).pdf"
layout: T1
scope: all
expected_pages: 282
ocr:
  nom: [paddleocr_vl, kimhannom]
  quoc_ngu: [vintern_1b_v2, paddleocr_vl]
  ensemble: true
  api_mode: sample_then_low_confidence
review_profile: strict
```

---

## 9. Quality gates

| Gate | Checks | Failure action |
|---|---|---|
| Inventory | Every PDF page accounted once; unique image names; no duplicates; correct naming regex | Block; review manifest |
| Labels | Every image has `Label.txt` row; every `fileState.txt` = 1; exactly 4 points; boxes inside image | Block; fix boxes |
| Text | NFC; no control chars; Nôm font coverage; no newline in cells; `[MASK]` length/positions | Block; review text |
| Alignment | `sentence_id` format; no duplicates/missing; reading order; text matches labels except cross-page joins | Block; review rows |
| `text_diff` | Valid JSON; positions exact; substrings match; no overlap; `null` vs `[]`; XLSX colours match | Block; review rows |
| Evaluation | ≥95% per book; yellow ratio reported; null-row ratio reported | Block packaging; review diagnostics |
| Package | ZIP tree, filenames, CSV/XLSX open, report present, source pinned, no tokens/data/models | Block submission |

The final `validate_submission.py` must mirror these checks and fail the build on any error.

---

## 10. Human review policy

Only flagged items leave automation. No full manual pass.

| Reason code | Typical cause | Human action |
|---|---|---|
| `SCAN_ORIENTATION` | Wrong rotation/skew/split page | Rotate/stitch/confirm |
| `SCAN_MISSING` | Printed page number missing | Confirm `missing/ch`/`missing/vi` |
| `T1_BOUNDARY` | Uncertain QN/Nôm section boundary | Confirm split point |
| `MIXED_PAGE` | Both scripts on one page | Confirm duplicated image/box filtering |
| `OCR_LOW_CONF` | Low confidence/engine disagreement | Correct flagged span |
| `BBOX_INVALID` | Wrong point count/out-of-image | Fix in PPOCRLabel |
| `DICT_MISS` | Nôm char absent from all sources | Confirm char / red / `[MASK]` |
| `ALIGN_LOW_CONF` | Weak alignment score | Confirm/split/merge rows |
| `DIFF_SEMANTIC` | Red/yellow unclear | Confirm colour/type |
| `PROPER_NAME` | Name/year character-count mismatch | Confirm yellow vs red |

Mandatory human gates that are **not** error correction:

- scope/source confirmation before mass OCR;
- contacting the handout person if >20% Nôm pages are poor;
- member names/IDs/emails for the report;
- required report screenshots;
- final sign-off.

Calibration: use a 10–20 page stratified pilot sample (including a 5-page gold set) to tune thresholds. This is the only planned manual measurement; it is not a full manual pass.

Review load estimate: 10–20% of Nôm pages (~42–84 pages), more if local Nôm OCR is weak. Pilot will measure.

---

## 11. Schedule and hard gates

| Date | Work / gate |
|---|---|
| **Nov 8–10** | Install PyTorch/OCR stack; benchmark `Vintern-1B-v2` and `PaddleOCR-VL`; 20–30 page pilot; API sample if token; 5-page gold sample; decide if enhancement is needed. **Pilot go/no-go Nov 10.** |
| **Nov 11–14** | Scaffold repo; extraction, classification, T1 mapping, label generation, validators; Book 3 end-to-end pilot. |
| **Nov 15–20** | OCR production: local majority; API low-confidence; cleaning; start Book 2 (largest Nôm section). **OCR complete Nov 20.** |
| **Nov 21–25** | Alignment and `text_diff`; per-book 95% gate; review queue. |
| **Nov 26–27** | Human corrections; re-run affected stages; verify yellow/null ratios. |
| **Nov 28–29** | One ZIP with three book folders; report, screenshots, `source.zip`; validator. |
| **Nov 30** | Final sign-off and submission; buffer. |

**Critical dependency:** API token/quota decision by **Nov 12–15**. If late, proceed local-only; integrate API later. Do not let it block extraction, classification, QN OCR, alignment, or packaging.

---

## 12. Open items

1. **MSSV list:** only `24127189` is known. Need all four student IDs for the ZIP/report filenames.
2. **API token:** when available, put in `.env`; do not paste into chat/repo. Confirm quota is per account/token/IP and whether multiple accounts are allowed.
3. **Dictionary JSONL:** optional; pipeline works without it. If provided later, plug into `DictionaryIndex`.
4. **Model weight downloads:** confirm outbound download of open weights is allowed. If not, obtain approved offline copies.
5. **One ZIP vs three:** user confirmed one ZIP with three folders; guideline tree shows one book. Note in README/report; keep a split script.
6. **Report template:** use the guideline content list; no separate template confirmed.
7. **T1 mapping:** follow the guideline; no instructor input needed unless they specify a different convention.
8. **Preprocessing:** follow the guideline literally; no hidden dual-image versions.

---

## 13. Immediate next steps for the next agent

1. **Read the source PDFs** with PyMuPDF. The guideline PDFs have text; the book PDFs are image-only.
2. **Create the repo scaffold** from §8.1 and a Python virtual environment. Use pinned dependencies.
3. **Extract pages** at native resolution; verify page counts, naming, duplicates, orientation.
4. **Recompute the layout heuristic** and verify the Nôm/QN/blank/mixed estimates; build T1 section boundaries and `image_map.json`.
5. **Run the Book 3 end-to-end pilot** (smallest, 118 pages; includes a mixed page).
6. **Benchmark local OCR** on 20–30 pages; measure VRAM, time/page, quality.
7. **Test the Kim Hán Nôm API** if a token exists; verify the response schema before writing the parser.
8. **Build validators first**, then OCR, cleaning, alignment, `text_diff`, evaluation, packaging.
9. **Start Book 2 OCR early** because it has the largest Nôm section (~242 pages).
10. **Never commit** confidential PDFs, `data/`, `models/`, tokens, or derived artifacts.

### Useful environment facts

- Windows, PowerShell; Python at `D:\anaconda3\python.exe`.
- `pymupdf`, `numpy`, `scipy`, `Pillow`, `streamlit` installed; `torch`, `transformers`, `paddleocr`, `opencv`, `tesseract` not installed.
- GPU: RTX 4060 Laptop, 8 GB VRAM; RAM 16 GB; CPU i7-14700HX 20C/28T; ~210 GB free on C: and D:.
- Set `PYTHONIOENCODING=utf-8` in PowerShell before running scripts that print Vietnamese filenames.
- The PDF extraction script used earlier:

```python
import pymupdf
doc = pymupdf.open(path)
text = "\n".join(page.get_text() for page in doc)
```

For the book PDFs, `get_text()` returns empty; render pages to images and OCR.

---

## 14. Do-not list

- Do not upload confidential scans to third-party hosted APIs, cloud OCR, cloud GPU, or Hugging Face.
- Do not use multiple Kim Hán Nôm accounts to bypass quota without written permission.
- Do not skip difficult pages; route them to review.
- Do not split a two-page spread for convenience.
- Do not modernize archaic Vietnamese spellings.
- Do not use yellow to inflate the 95% score.
- Do not auto-red a character just because an incomplete dictionary lacks it.
- Do not assume the API response schema; verify live.
- Do not overwrite human corrections on re-run.
- Do not commit tokens, data, models, or confidential PDFs.
- Do not silently implement a user/instructor instruction that contradicts the guideline; flag it first.
