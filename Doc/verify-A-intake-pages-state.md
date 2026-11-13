# Verification report — Area A: Stage 0 Intake, Stage 1 page extraction, SQLite state layer

> **REVISION 2026-11-12 (post map-repair change-set):** written against pre-`feat/map-repair-align` state. The 2026-11-12 change-set (uncommitted; HEAD still c3439e7) is summarized below; claims invalidated by it are REVISED or flagged inline; all section verdicts for Stage-0/1 findings re-confirmed unless marked otherwise. Numbers were re-measured read-only from current data/state.sqlite3 and artifacts.
>
> **The 2026-11-12 change-set at a glance** (uncommitted; branch `feat/map-repair-align`; HEAD `c3439e7` — the same commit as `repair/pipeline-audit-2026-11-09`'s tip, already on `origin`; ZERO new commits):
> - Modified: `configs/alignment.yaml` (+20); `configs/books/T1_CamPhong_Tap1.yaml` (+22: `inventory_vi: [13–20]`, `inventory_misc: [5, 7–11, 277–282, 143, 144]`); `configs/books/T1_SuaLoiQuyen.yaml` (+4: `inventory_misc: [2, 3, 5, 7, 8, 9, 62, 63, 117, 118]`); `docs/decisions.md` (+6 2026-11-12 entries); `src/hannom/align.py` (+72: content-based image-map re-pairing + paren-anchored pairing; `write_alignment_csv` 596→668, `auto_text_diff` call 497→528, `CSV_COLUMNS` ~555→~627, `utf-8-sig` ~608→~680); `src/hannom/config.py` (+5 after line 44: `inventory_vi`/`inventory_misc` keys at ~44–50; `load_config` reads them at ~163–168; `BookConfig.book_name` 48–50 → 53–55); `src/hannom/layout.py` (+11: `BIN_OVERRIDE` block inserted ~339–349; `sorted(set(...))` 342→353; `status="classified"` 343→354); `src/hannom/orchestrator.py` (net-0: `stage_labels` folder tuple at ~169 gained `"misc"`); `src/hannom/textdiff.py` (+1..15; diacritic-variant weak matching).
> - Untracked (new): `src/hannom/charstream.py`, `src/hannom/map_repair.py`, `tools/repair_image_map.py`, `tests/test_charstream.py`, `tests/test_map_repair.py`.
> - Tests now **282 passed** (re-run 2026-11-12, exit 0; was 277 at audit).
> - Data re-bin (applied via **direct DB surgery** — no `BIN_OVERRIDE_*` flags exist in the DB; backups `data/state.sqlite3.bak-2026-11-12-phaseA` 11/12 13:45 and `…bak-2026-11-12-rebin-fix` 11/12 19:36 both pre-date the final re-bin and preserve the pre-final state): Tap1 PDF 13–20 → `vi/`; Tap1 `5, 7–11, 277–282, 143, 144` and Tap3 `2, 3, 5, 7, 8, 9, 62, 63, 117, 118` → `misc/`. Tap1 now 130 ch / 130 vi / 16 misc / 6 blank / 0 toc / 0 intro (was 130 / 124 / 2 / 6 / 16 / 4); Tap3 now 50 / 50 / 12 / 6 / 0 / 0 (was 50 / 52 / 2 / 6 / 4 / 4); Tap2 unchanged (264 / 267 / 1 misc / 6 / 10 / 2). Statuses unchanged (Tap1 274 ocr_done / 8 classified; Tap3 110 / 8; Tap2 6 / 544).
> - Artifact ledger stale: Tap1 `layout/image_map` row dated 11-08 (meta `pairs=124` vs file's 127 pairs); Tap3 `layout/*` rows dated 11/12T06:24Z pre-re-bin (`vi:52/misc:2` vs file now vi:50/misc:12); both sha256-NULL; Tap1 `align/csv` + `evaluation/metrics` re-written 2026-11-12T12:43Z; `pages.jsonl` staleness now extends to folder/status (950/950 inconsistent with current DB).

**Date of audit:** 2026-11-12
**Revised:** 2026-11-12 (post map-repair change-set — see banner; §10 Revision log lists every edit)
**Auditor:** Area A verifier (subagent; revised by the same agent on 2026-11-12)
**Audience:** the next agent working on this repo who has NOT seen the audit conversation and must act on this document without asking questions.
**Repo:** `C:\Users\MSI VN\Desktop\NLP` (git HEAD at audit time: `c3439e7` "charalign: --strip-text option drops margin running heads from Nôm pages" — **HEAD is still `c3439e7` at revision time**; the 2026-11-12 change-set is uncommitted on `feat/map-repair-align`. ~~the six audited source files were unmodified in the working tree~~ — **FALSE as of 2026-11-12**: `config.py` and `orchestrator.py` ARE modified; only `intake.py` / `pages.py` / `state.py` / `models.py` remain unmodified. (revised 2026-11-12)).
**Data:** `data/` (read-only), 3 assigned books, 950 PDF pages, already extracted and partially OCR'd.

---

## 1. Scope & files audited

**In scope (line counts below are 1-based line numbers used throughout):**

| File | Role |
|---|---|
| `src/hannom/intake.py` | Stage 0: `inspect_pdf`, `lock_scope`, `_link_or_copy`, `sha256_file`, `write_json`/`read_json` |
| `src/hannom/pages.py` | Stage 1: `page_number_str`, `image_name`, `extract_page`, `extract_book`, `_save_rgb_jpeg`, `_render_page`, `read/_write_pages_jsonl`, duplicate detection |
| `src/hannom/state.py` | SQLite state: schema, `State`, `upsert_page`, `update_page`, `pages()`, `page()`, artifacts ledger, `default_state` |
| `src/hannom/models.py` | `PageRecord` (lines 16–38) |
| `src/hannom/config.py` | `BookConfig.book_name` (lines 53–55 as of 2026-11-12; was 48–50), `ProjectConfig`, `load_config` (only for path/name semantics at audit; nothing else flagged — **file modified 2026-11-12**: `inventory_vi`/`inventory_misc` keys added at ~44–50 and read by `load_config` at ~163–168) (revised 2026-11-12) |
| `src/hannom/orchestrator.py` | Skimmed only: `open_state` (71–72), `stage_intake` (94–95), `stage_extract` (98–99), run order (599–600) — **file modified 2026-11-12**: `stage_labels` folder tuple (~169) gained `"misc"` (net-0 line change; all cited line numbers unchanged) (revised 2026-11-12) |

**Read for downstream-contract context (not modified at audit time; `layout.py` has since been modified — see banner):** `src/hannom/package.py` (`_copy_jpegs` 54–65, `_copy_label_files` 68–93, staged `_updated.pdf` copy 227–232, `validate_book_package` 371+), `tools/build_updated_pdf.py` (builds `<BookName>_updated.pdf`, self-verification 112–120), `tools/validate_submission.py` (`IMAGE_RE` ~line 37, nothing checks `_updated.pdf`), `src/hannom/layout.py` (353–364 as of 2026-11-12; was 342–353), `src/hannom/orchestrator.py:216/266`, `src/hannom/cli.py` (`intake`/`extract` commands, lines 59–77), `README.md`, `USER_GUIDE.md`, `Doc/PROJECT_PLAN.md`, `Quy_định_đồ_án v2.1` (extracted text). (revised 2026-11-12)

**NOT read (per ground rules):** `.env`, `hannom_API.md`, `API_Kim_Han_Nom_guide.extracted.txt`. **Kim Hán Nôm API was never called.** No models were downloaded/installed.

---

## 2. Method & ground rules

Ground rules (all honoured): read-only on the repo and `data/`; no API calls; no `.env` / `hannom_API.md` access; no installs; no writes except scratch under `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-A` (this report was the only permitted write outside scratch, and was explicitly requested). Internet not needed; PyMuPDF/PIL behaviour verified empirically against the assigned PDFs in scratch.

Scratch probe files (all in `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-A\`, safe to re-run; they are read-only against `data/`):

- `probe1.py` — tables, page/status/folder/extraction_method/rotation counts per book, DUPLICATE_IMAGE count, artifact ledger, integrity_check, sample rows.
- `probe2.py` — proper `PRAGMA integrity_check`/`quick_check` output, rotated-page detail, Tap2 non-uniform sizes, artifacts pages-stage rows.
- `probe3.py` — `pages.jsonl`↔SQLite consistency (name/sha256/dims/method/rotation), disk↔state reconciliation, sha256 re-verification of 30 pages, duplicate-hash groups across all 950 pages.
- `probe4.py` — `extraction_method`/`DUPLICATE_IMAGE`/status breakdown of the three backups + current DB.
- `probe5.py` — compact per-DB summary: method families (embedded/rendered/existing), rotated count, dup flags, statuses.
- `probe6.py` / `probe9.py` — raw vs assigned PDF identity: Windows file-index comparison (ctypes) and `os.stat` `st_dev/st_ino`; NFC/NFD normalisation check of manifest paths.
- `probe7.py` — 950-file naming-rule regex sweep, `.jpg`-only check, contiguity from 1, jsonl↔SQLite mismatch count for `review_flags`/`features_json` (found 950/950 stale rows).
- `probe8.py` — synthetic tests: hidden-text-layer PDF vs pure-image PDF (intake abort behaviour), empty-candidates upscale demonstration, `update_page(review_flags="str")` double-encode demonstration, upsert-clobber demonstration, `page_number_str` boundaries, cross-rotation duplicate miss, verbatim-copy check.
- `probe10.py`–`probe13.py` — verbatim byte-compare of unrotated pages against embedded streams (4/4 match), all-27 rotated pages pixel/histogram comparison vs embedded streams, size/diff statistics (mean |Δ| 0.3–0.7/255).
- `probe11.py` — fast `page.get_image_info()` xref coverage across all 950 pages (0 carry xref in fast mode → slow-path fallback always taken).
- `probe14.py` — `PRAGMA table_info(pages)` on backups (schema identical).
- `probe15.py` — sha256 of raw copies vs assigned PDFs (equal), negative-scale placement matrices sweep (0 found), `_updated.pdf` freshness: for both rotated books, every embedded page byte-matches the current native file; manifests' `source_pdf_sha256` match assigned PDFs.
- `probe16.py` — colour space / bpc / multi-image-page census (all DeviceRGB, bpc=8, single image per page).
- `probe17.py` — count of rows whose flags/features were mutated downstream (950/950).

Windows console note: Vietnamese file names render as mojibake in `powershell` output (the files themselves are proper UTF-8 NFC). Use `Get-ChildItem`/`python` with `$env:PYTHONIOENCODING='utf-8'` for clean output. All path-relevant facts were verified through Python, not console rendering.

---

## 3. Verified facts about the current data state

Source of truth: `data/state.sqlite3` (queried with `sqlite3.connect("file:...?mode=ro", uri=True)`), `data/pages/**`, `data/raw/**`, `data/output/**`, `artifacts/updated_pdf/*.json`. **(re-queried read-only 2026-11-12, after the uncommitted 2026-11-12 change-set; all numbers in §3 are current as of that re-measurement — see banner.)**

### 3.1 Books, pages, files

| Book (`book_id`) | Pages | JPG on disk | Numbering | Status (classified / ocr_done) | Folder split (ch/vi/toc/intro/blank/misc) |
|---|---|---|---|---|---|
| `T1_CamPhong_Tap1` | 282 | 282 | 1–282 contiguous | 8 / 274 | 130 / 130 / 0 / 0 / 6 / 16 (revised 2026-11-12) |
| `T1_CamPhong_Tap2` | 550 | 550 | 1–550 contiguous | 544 / 6 | 264 / 267 / 10 / 2 / 6 / 1 |
| `T1_SuaLoiQuyen` | 118 | 118 | 1–118 contiguous | 8 / 110 | 50 / 50 / 0 / 0 / 6 / 12 (revised 2026-11-12) |
| **Total** | **950** | **950** | | 560 / 390 | |

*(revised 2026-11-12): folder splits for Tap1/Tap3 reflect the 2026-11-12 declarative re-bin (`inventory_vi`/`inventory_misc` in `configs/books/*.yaml`, applied via direct DB surgery — **no `BIN_OVERRIDE_*` flags in the DB**). Tap1 `toc` 16→0 / `intro` 4→0 / `vi` 124→130 / `misc` 2→16; Tap3 `toc` 4→0 / `intro` 4→0 / `vi` 52→50 / `misc` 2→12; Tap2 unchanged. Column order is ch / vi / toc / intro / blank / misc. The 560 classified / 390 ocr_done totals are unchanged ✓ (statuses were not re-derived by the re-bin; only folders were rewritten, via DB surgery).*

- File naming: **950/950** match `^<book_stem>.\d{3,}(_\d+)?\.jpg$`; zero gaps, zero duplicates from 1.
- **950 unique sha256 hashes; 0 duplicate hash groups** (current DB and all five backups — three old plus the two 2026-11-12 backups `.bak-2026-11-12-phaseA` / `.bak-2026-11-12-rebin-fix`) — README's "950 unique JPEGs … no duplicate hashes" is accurate. (revised 2026-11-12)
- **No `.jpg` exceptions**: no other extensions under `data/pages/**`; every file decodes (PIL `Image.open` used throughout probing).
- All pages single-image scans, DeviceRGB, 8 bpc; **zero pages with a placement matrix having `a<0` or `d<0`** (flips/mirrors); zero hidden text layers (`text_chars_total = 0` for all three PDFs).
- Tap2 page sizes: 525 × 800×1135, **25 × 564×800** (all rotated pages). Tap1: all 800×1135 (2 pages @ 180°). Tap3: all 800×1135 (0 rotated).

### 3.2 Rotation (27 total)

- Tap1 (180°): `p263`, `p274` — 800×1135 (dims unchanged by 180°).
- Tap2 (90°, 8): `p295, p310, p392, p405, p452, p499, p515, p525` — all 564×800.
- Tap2 (270°, 17): `p287, p296, p305, p335, p339, p345, p349, p364, p386, p414, p416, p419, p426, p447, p459, p461, p505` — all 564×800.
- Tap3: none → no `_updated.pdf` required.

Rotated files are **re-encoded** (JPEG → decode → transpose → JPEG q95, subsampling=0), not byte-verbatim: measured sizes identical to transposed embedded streams; pixel histograms differ (JPEG generation loss); mean |Δ| 0.3–0.7 per 255; file sizes ~35% smaller than embedded streams. Geometrically exact (no resampling, native resolution kept) — but not bit-wise lossless (see Finding n3).

### 3.3 `extraction_method` — provenance discrepancy (important)

| DB snapshot | embedded | rendered | existing |
|---|---|---|---|
| backup `state.sqlite3.bak-2026-11-08` (950 rows; all `classified`; 0 api_calls) | 950 | 0 | 0 |
| backup `state.sqlite3.bak-20261111-230036` | 0 | 0 | 950 |
| backup `state.sqlite3.bak-20261112-134510` | 0 | 0 | 950 |
| backup `state.sqlite3.bak-2026-11-12-phaseA` (11/12 13:45; pre-re-bin) (revised 2026-11-12) | 0 | 0 | 950 |
| backup `state.sqlite3.bak-2026-11-12-rebin-fix` (11/12 19:36; pre-re-bin; captured a transient state with invalid folder values `other`×24 / `translation`×8, later corrected) (revised 2026-11-12) | 0 | 0 | 950 |
| **current `state.sqlite3`** | **0** | **0** | **950** |

*(revised 2026-11-12): the two new backups both pre-date the final re-bin — at both, Tap1 `misc = {1,145}` and Tap3 `misc = {1,64}` (Tap1's `vi` grew 124→130 and Tap3's `vi` shrank 52→50 only after the final re-bin). `api_calls = 550` in both; statuses 274/8, 110/8, Tap2 6/544 — identical to current.)*

README (lines 50–59) claims "923 pages copied byte-for-byte from the embedded JPEG stream; 27 rotated pages transposed losslessly" — corroborated by the 2026-11-08 backup but **not recorded in the current DB** (every page was re-marked `existing` by later re-runs; see M1). README's other fidelity claims are consistent with the data (`reportable_size`, verbatim bytes verified by sampling, 0 rendered pages).

- Verbatim spot-checks against embedded streams (all match): Tap1 p1/p100, Tap2 p1, Tap3 p1; all 4 sampled rotated inputs verified dimension/histogram-consistent with the transposed embedded streams (all 27 pages probed).
- **Unverifiable today from the DB alone**: which pages were verbatim vs render path — must consult `state.sqlite3.bak-2026-11-08`.

### 3.4 SQLite state

- `PRAGMA integrity_check` → `ok`; `quick_check` → `ok`. (Re-verified read-only 2026-11-12: `ok`; `api_calls` = **550**, with 0 calls on 2026-11-12.) (revised 2026-11-12)
- Tables: `pages` (950), `api_calls`, `reviews`, `runs`, `artifacts`, `sqlite_sequence`.
- Statuses: Tap1 274 `ocr_done` / 8 `classified`; Tap2 6 / 544; Tap3 110 / 8. (**Unchanged** after the 2026-11-12 re-bin — only folders were rewritten.) (revised 2026-11-12)
- `pages.review_flags` (current distinct flags): `PAGE_MARK_REMOVED` 104, `LABEL_EMPTY_OCR` 808 (Tap1 269 — was 267, +2 from the re-binned misc pages; Tap2 537 unchanged; Tap3 2 — was 0), `NOM_UNENCODABLE_REPLACED` 167, `BAND_RETRY_AFTER_FULLPAGE_FAILURE` 36, `FOOTER_TITLE_REMOVED` 17, `TOC_LIKELY_FRONT` 12, `OCR_ENGINE_DISAGREE` 5, `DUPLICATE_LINES_REMOVED` 6, `NOM_BLOCK_START/END` 3/3, `COVER_PAGE` 3 — **`DUPLICATE_IMAGE`: 0** (see n11; unchanged 2026-11-12). **No `BIN_OVERRIDE_*` flags exist in the DB** — the 2026-11-12 re-bin was applied via direct DB surgery, not via a classify re-run (a re-run would wipe `ocr_done`; see M1). (revised 2026-11-12)
- `features_json` populated for 950/950 rows; `review_flags` non-empty for **902/950** rows (Tap1 275/282 — was 274; Tap2 541/550; Tap3 86/118 — was 85). (revised 2026-11-12)
- `artifacts`: `intake/manifest` (with sha256) for 3 books; `pages/native_jsonl` (**no sha256**); `layout/classification`, `layout/image_map`, `align/csv`, `evaluation/metrics` all present. `native_jsonl` meta for all three books: `{"page_count": N, "duplicate_hash_groups": 0, "native_size": [800, 1135]}` — **`native_size` wrong for Tap2's 25 rotated pages** (see n6). (revised 2026-11-12) — **ledger staleness (re-measured 2026-11-12):** Tap1 `layout/image_map` row is stale — meta `pairs=124` vs the file's actual **127 pairs** (file mtime 11/12 19:37; ledger row dated 11-08T12:25Z, meta `vi_pages=124` vs current vi=130); the matching Tap1 `layout/classification` row is likewise pre-re-bin (`misc:2/vi:124`, dated 11-08T12:25Z). Tap3 `layout/classification` and `layout/image_map` ledger rows are pre-re-bin (11/12T06:24Z; `vi:52/misc:2` vs current `vi:50/misc:12`). Tap1 `align/csv` and `evaluation/metrics` rows **were** re-written 2026-11-12T12:43Z (evening local) after the re-pairing change. Tap2 artifacts untouched (11/08). All three `native_jsonl` rows remain sha256-NULL; Tap3's row was re-stamped 11/12T06:24Z, Tap1/Tap2 rows remain 11-08.
- `pages.jsonl` (one per book, e.g. `data/pages/T1_CamPhong_Tap1/pages.jsonl`): consistent with SQLite on `image_name/sha256/width/height/extraction_method/rotation` for 950/950; **stale on `review_flags`/`features` for all 950 rows** (jsonl written at extract time; downstream stages mutate only SQLite) — see n1. **(revised 2026-11-12): staleness now extends to `folder`/`status` too — after the 2026-11-12 re-bin, `pages.jsonl` disagrees with SQLite on folder assignment for 950/950 rows (re-measured read-only).** `read_pages_jsonl` has **zero callers** in `src/` or `tools/`.
- Backups: `data/state.sqlite3.bak-2026-11-08` (oldest; has `embedded` provenance; all-`classified`, 0 api_calls) — 11/08 10:00; `...bak-20261111-230036` — 11/11 23:00; `...bak-20261112-134510` — 11/12 13:44:39; **`...bak-2026-11-12-phaseA`** — 11/12 **13:45:10**; **`...bak-2026-11-12-rebin-fix`** — 11/12 **19:36:40**. Schema identical in all five (verified via `PRAGMA table_info(pages)`): `extraction_method`/`rotation` columns present. The two new backups **pre-date the final re-bin** (at both, Tap1 `misc = {1,145}`, Tap3 `misc = {1,64}`); `-rebin-fix` additionally captured a transient state with invalid folder values (`other` ×24 / `translation` ×8) that was later corrected — the current DB contains only valid folders. **Five backups total** (revised 2026-11-12).

### 3.5 Raw archives and merged PDFs

- `data/raw/<book>/original.pdf` == assigned PDF (`CV20-24127189/<name>.pdf`) — **sha256 identical for all 3 books** (recomputed): Tap1 `05c1002d5246…`, Tap2 `068ceda60d5e…`, Tap3 `63b2bdf6632d…`.
- Raw copies are true copies (not hardlinks): same device, different inode, nlink=1.
- Manifests now record `"raw_link": "existing"` for all three (first-run semantics overwritten on re-runs; originals unknown).
- `${BookName}_updated.pdf` exists for the two rotated books at `data/output/<book_id>/<BookName>/<BookName>_updated.pdf` (mtime 2026-11-08 11:28 local), built by `python tools/build_updated_pdf.py --all` on 2026-11-08T04:28 UTC. **(unchanged by the 2026-11-12 change-set — re-verified read-only 2026-11-12: both files fresh; images 950/950 untouched.)**
  - **Freshness verified for every rotated page**: sha256(embedded image) == sha256(current native file) for all 2 (Tap1) + 25 (Tap2) rotated pages. Page count == expected_pages. Manifests in `artifacts/updated_pdf/<book_id>_updated_pdf_manifest.json` record `source_pdf_sha256` matching the current assigned PDFs (`05c1…` / `068c…`). Built from the re-extracted rotated files, not stale. (re-confirmed 2026-11-12; manifests and `_updated.pdf` untouched by the change-set)
  - Staged copies are copied into the submission book folder by `package.py:227-232` **only if present** — with no verification (M4).
- `T1_SuaLoiQuyen`: no `_updated.pdf` (correct — no rotated pages).
- Assigned PDFs themselves live in `CV20-24127189/` at repo root: `T1_Cấm Phòng Cho Bổn Đạo (Tập 1).pdf`, `T1_Cấm Phòng Cho Bổn Đạo (Tập 2).pdf`, `T1_Sửa Lưỡi Quyển.pdf` (paths in manifests are absolute, NFC).

### 3.6 Tests

`python -m pytest -q` — **282 passed** (re-run 2026-11-12 after the uncommitted 2026-11-12 change-set; was **277 passed** at audit — the five new tests are `test_charstream.py` / `test_map_repair.py`; no GPU/network needed; exit 0). Includes `tests/test_extraction.py` (verbatim-copy and 180° rotation tests) and `tests/test_naming.py`. (revised 2026-11-12)

---

## 4. Findings, ranked by severity

### Blocker

None. Current on-disk artifacts are complete, consistent, and correctly named; the merged PDFs match the submitted images.

---

### Major

#### M1. Re-running Stage 1 silently wipes all downstream per-page state and destroys extraction provenance

`extract_book` builds fresh `PageRecord`s with Stage-1 defaults (`status="extracted"`, `script="unknown"`, `section="unknown"`, `folder=""`, `review_flags=[]`, `features={}`, `ocr_engine=None`, `ocr_confidence=None`) and calls `state.upsert_page(record)` **even when the output file already exists**:

```python
# pages.py:207-213
            if dest.exists() and not force:
                with Image.open(dest) as im:
                    width, height = im.size
                method = "existing"
                rotation = int(doc[page_no - 1].rotation or 0)
```

```python
# pages.py:227
            state.upsert_page(record)
```

```python
# state.py:140-157  (ON CONFLICT branch)
                ON CONFLICT(book_id, page_no) DO UPDATE SET
                    ...
                    status=excluded.status,
                    ocr_engine=excluded.ocr_engine,
                    ocr_confidence=excluded.ocr_confidence,
                    review_flags=excluded.review_flags,
                    features_json=excluded.features_json,
                    extraction_method=excluded.extraction_method,
```

**Demonstrated** (scratch, `probe8.py` #4): upsert a record → `update_page(status='ocr_done', flags=['LABEL_EMPTY_OCR'], features={...})` → re-upsert a fresh default record → row reads back `status='extracted', script='unknown', folder='', flags=[], features={}, method='existing'`.

**Impact:**
1. Any re-run of `hannom extract` after classify/OCR/review (the documented fix-up path; see README line 157) resets every page to `extracted` in the pages table. OCR artifacts on disk survive, but state gating resume logic/metrics/packaging is destroyed; a full classify+OCR pass is needed again. `folder=""` matches **no** folder branch in `package.py:192` — images would silently vanish from the submitted `ch/`/`vi/` folders.
2. `extraction_method` is overwritten to `existing`, erasing the verbatim-vs-rendered provenance README relies on (current DB: `existing` ×950; only `state.sqlite3.bak-2026-11-08` retains `embedded:xref=…` ×950).

**(revised 2026-11-12) Corroboration in the wild:** the 2026-11-12 Tap1/Tap3 re-bin (front matter → `vi/`, back matter/glossary/covers → `misc/`) was applied via **direct DB surgery** — no `BIN_OVERRIDE_*` flags exist in the DB (verified), and the collaborator preserved `.bak-2026-11-12-phaseA` / `.bak-2026-11-12-rebin-fix` (the latter captured a transient invalid-folder state `other`×24 / `translation`×8 at 11/12 19:36:40, since corrected — the current DB contains only valid folders). This is consistent with avoiding the M1 hazard above — a classify re-run would have wiped `ocr_done`. `ocr_done` survived only by manual intervention, not by any code safeguard. This is the M1 hazard operating exactly as documented, on the project's own fix-up path, on the same day this report was revised — it upgrades M1 from "theoretical" to "observed in the act during the 2026-11-12 change-set" and makes the §5 Step 1 fix the single most valuable change to land before any further `extract`/`classify` run.

**Fix** (see §5 step 1): on the `dest.exists() and not force` path, write **only** Stage-1 columns (`image_name, pdf_page, sha256, width, height, path, extraction_method, rotation, updated_at`); never touch the downstream columns; and do not downgrade `extraction_method` when the digest is unchanged.

---

#### M2. `lock_scope`/`_link_or_copy` never verify the archived raw copy against the assigned PDF; copy semantics lost on re-runs

```python
# intake.py:86-95
def _link_or_copy(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return "existing"          # <-- no hash check of dst vs src
    try:
        os.link(src, dst)          # same-volume hardlink
        return "hardlink"
    except OSError:                # cross-volume / fs-unsupported -> copy
        shutil.copy2(src, dst)
        return "copy"
```

`lock_scope` computes `inspection.sha256` (of the **assigned** PDF) and records it both in `raw_dir/manifest.json` → `inspection.sha256` and in `artifacts.intake.manifest` via `set_artifact(... sha256=inspection.sha256 ...)` (`intake.py:139-146`). The **raw copy's** digest is never computed or compared — on re-runs the original `raw_link` (`hardlink`|`copy`) is unconditionally overwritten with `"existing"`, so the archive semantics vanish from the ledger (all three current manifests say `"existing"`).

**Impact:** if the assigned PDF is ever re-scanned/replaced in place with different bytes at the same page count, a re-run leaves a **stale `data/raw/original.pdf` whose sha differs from the sha256 recorded in the manifest and artifact ledger** — silently. For confidential books, the archived raw copy is supposed to be the ground truth of what was processed; this defeats the whole purpose of recording sha256. (Verified now: raw == assigned for all three books; the gap is latent.)

**Fix** (§5 step 4): when `dst.exists()`, compare `sha256_file(dst)` to `inspection.sha256`; mismatch → raise `IntakeError` or back up and re-copy; stop overwriting the first-run `raw_link`.

---

#### M3. `extract_book --force` deletes `data/pages/<book>/native/` before validating the PDF

```python
# pages.py:190-204
    if not book.pdf.exists():
        raise PageExtractionError(f"Assigned PDF not found: {book.pdf}")

    out_dir = project.data_dir / "pages" / book.book_id / "native"
    if force and out_dir.exists():
        shutil.rmtree(out_dir)          # <-- destructive, happens FIRST
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(book.pdf)
    records: list[PageRecord] = []
    try:
        if doc.page_count != book.expected_pages:
            raise PageExtractionError(   # <-- validation only AFTER deletion
                f"{book.book_id}: expected {book.expected_pages}, got {doc.page_count}"
            )
```

**Impact:** if the assigned PDF changed/corrupt/unreadable at hand-in rehearsal time, `--force` (as shown in README line 157: `hannom extract --book T1_CamPhong_Tap2 --force`) **deletes all native JPEGs** and then aborts — DB rows point at missing files; zero images in the workspace. Recoverable by re-extraction from the PDF, but it's a self-inflicted partial data loss with no backup of `native/`.

**Fix** (§5 step 2): open and validate (`page_count`, `image_only`-style sanity, and hashing of the first page) **before** `rmtree`; or extract to a sibling temp dir and swap only on success.

---

#### M4. Nothing enforces the guideline's mandatory `<Book>_updated.pdf` — presence, freshness, or correspondence to the submitted images

The technical chain exists but ends in an unverified human step:

- `tools/build_updated_pdf.py` is run **manually**; it is not wired into `hannom` CLI/orchestrator.
- `package.py:227-232` copies the staged `<Book>_updated.pdf` into the book folder **only if it exists**, without opening it, comparing bytes, or checking freshness.
- `package.py` `validate_book_package` (`package.py:371+`) never mentions `_updated.pdf`.
- `tools/validate_submission.py` never mentions it either (`IMAGE_RE` checks names/order only).
- README (lines 54–59) documents the merge and says notification to the handout person is "a mandatory human step before hand-in" — unverifiable from the repo.

**Impact:** (i) a stale merged PDF (built from pre-rotation-fix images) would be shipped silently; (ii) a missing `_updated.pdf` for a rotated book would pass all automated checks; (iii) the handout-person notification — the only step the guideline explicitly requires — has no checklist anchor.

Current facts (good): both `_updated.pdf` files **are fresh** — every embedded rotated image byte-matches the current native JPEGs (verified for all 27 pages), page counts equal `expected_pages`, exactly one image per page (tool-verified at build time), manifests' `source_pdf_sha256` match the assigned PDFs. This is an **enforcement gap**, not a current defect.

**Fix** (§5 step 3): hard gate at package time — see §5 step 3 for the exact checks.

---

#### M5. Pre-hand-in validation never checks JPEG decodability and never reconciles per-book image accounting

`validate_book_package` checks ch/vi folder **names** and label structure; `tools/validate_submission.py` checks names/image_map/duplicates in ch/vi only. Neither checks:

- that every `.jpg` **decodes** (`PIL Image.open().verify()` / `.load()`),
- that every file's sha256/dimensions match `state` (stale or corrupt files pass),
- that no non-`.jpg` file (`.png`/`.jpeg`/`.webp`/`.JPG`) exists anywhere in the book folder (globs are `*.jpg`; a stray `.png` would ship unnoticed),
- per-book accounting: `ch+vi+intro+ref+toc+blank+misc+missing == expected_pages` — the guideline's "every PDF page accounted once" gate (see `Doc/PROJECT_PLAN.md:569`, listed as a BLOCKING check in the project plan but not implemented as code).

**Impact:** a byte-corrupted-but-present `.jpg` or a shrunken folder would reach the submission ZIP unnoticed; recovery would happen at review time (deadline 2026-11-30).

**Fix** (§5 step 5): add `tools/verify_images.py` / extend `validate_submission.py` as specified there.

---

#### M6. Corrupt or stale SQLite can only be recovered by hand — no integrity check, no migrations, no auto-backup

```python
# state.py:104-110
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)      # <-- CREATE TABLE IF NOT EXISTS only
        self._conn.commit()
```

- **Corrupt DB** ("file is not a database"): raw `sqlite3.DatabaseError`, no message pointing at the five manual backups (`data/state.sqlite3.bak-2026-11-08`, `…bak-20261111-230036`, `…bak-20261112-134510`, **`…bak-2026-11-12-phaseA`**, **`…bak-2026-11-12-rebin-fix`**). (revised 2026-11-12)
- **Valid but older-schema DB**: passes init (tables "exist"); first `pages()` SELECT crashes with `OperationalError: no such column` (e.g. a pre-`extraction_method` file). There is **no** `PRAGMA user_version`, **no** `ALTER TABLE`, **no** `integrity_check`/`quick_check` anywhere in `src/`. `CREATE TABLE IF NOT EXISTS` never adds missing columns.
- **No auto-backup before destructive ops** (extract `--force`, bulk upserts).

**Impact:** one damaged file blocks the entire hand-in; recovery = manual restore of a backup whose own freshness/limitations §3.4 documents (i.e., restoring it would additionally lose OCR progress metadata).

**Fix** (§5 step 6): open-time `PRAGMA quick_check` with a clear error message listing `.bak-*` candidates; `PRAGMA user_version` + explicit migration steps; timestamped auto-backup of `state.sqlite3` before `extract --force` / `rmtree`-like operations and before packaging.

---

### Minor

#### n1. `pages.jsonl` is a write-only, Stage-1-time snapshot; misleads auditors
`pages.py:163-169` / `172-181`; `read_pages_jsonl` has zero callers. All 950 rows carry `review_flags=[]`, `features={}` while SQLite has downstream values (950/950 stale). It is recorded as `artifacts[stage=pages, key=native_jsonl]` — a reviewer auditing from that artifact gets outdated data. **(revised 2026-11-12): staleness now extends to `folder`/`status` — after the 2026-11-12 re-bin the jsonl disagrees with SQLite on folder assignment for 950/950 rows (re-measured read-only).** **Fix:** regenerate `pages.jsonl` at package/report time from current state, or re-label the artifact "snapshot at extraction" and include `updated_at`.

#### n2. `update_page` — no type validation, no row-count check
`state.py:182-215`. A bare string `review_flags="DUPLICATE_IMAGE"` is `json.dumps`-ed and round-trips as `str` (demonstrated) — downstream `.append` (`pages.py:242`) and `page.review_flags + flags` + `sorted(set(...))` (`layout.py:353` (revised 2026-11-12; was 342), `orchestrator.py:216,266`) then raise `AttributeError`/`TypeError`. `review_flags=123` round-trips as `int`. `features=5` round-trips as `5`, breaking `page.features.get(...)` (`orchestrator.py:226-231` region, `layout.py` features usage). A mistyped/absent `(book_id, page_no)` updates 0 rows **silently** — orchestrator's flag-writes would vanish. **Fix:** `isinstance(value, list)`/`isinstance(value, dict)` enforcement for `review_flags`/`features`; check `cursor.rowcount` and raise on 0.

#### n3. "Lossless transpose" of rotated pages is a second lossy JPEG generation
`pages.py:90-112`; verbatim copy only when `rotation % 360 == 0 and im.format == "JPEG" and im.mode in {"RGB", "L"}` (`pages.py:97-99`); otherwise `im.convert("RGB")` → transpose → `im.save(dest, format="JPEG", quality=95, subsampling=0, optimize=False)` (`pages.py:111`). Measured on all 27 rotated files: native resolution preserved, but pixel data differs from the decoded-and-transposed original (JPEG re-quantisation; mean |Δ| 0.3–0.7/255; output ~35% smaller). The guideline contract ("resolution preserved") is met; **README's "transposed losslessly" (README.md:52) and `pages.py`'s docstring (lines 100-102, "transpose is exact") overstate fidelity.** **Fix:** re-word the docstring/README ("geometric transpose, re-encoded q95 4:4:4 — no resampling; not a DCT-domain lossless transform"); optionally use `jpegtran`-style DCT transposition if bit-exact rotation is ever required; convert L-mode re-encodes back to `"L"` instead of forcing RGB.

#### n4. The "no upscale" contract is violated by the empty-candidates render fallback
Docstring (`pages.py:12-13`: "rendering is capped at the native scan width so nothing is upscaled") and `_render_page`'s comment (`pages.py:116-119`) contradict `extract_page`'s no-candidates branch:

```python
# pages.py:155-159
    if candidates:
        target_width = max(int(c.get("width", 0)) for c in candidates) or page.rect.width
    else:
        target_width = max(page.rect.width * 2.0, 1600.0)  # ~144 dpi fallback
```

**Demonstrated** (`probe8.py` #2): page 600×800 pt containing one 300×400 px image → output 1600×2134 px (~5.3× upscale). Never triggered for the assigned books (all pages extracted via `embedded:xref=…`; 0 `rendered` pages anywhere) but the docstring is false for this path. **Fix:** cap at `max(info.width for info in all_placed_images)` when any image exists (fallback chain: candidate width → largest placed-image pixel width → `rect.width*2`/1600), or explicitly document the 1600 px floor as an exception that knowingly upscales small placed images.

#### n5. Duplicate-image flagging misses content-identical pages rotated differently
`extract_book` hashes the **final file** (`pages.py:234-243`): an identical embedded scan on a `/Rotate=0` page (verbatim copy) vs a `/Rotate=90` page (re-encoded) yields different bytes → never flagged (demonstrated, `probe8.py` #6). Also `records[page_no - 1]` (`pages.py:240`) relies on positional indexing instead of a dict; and byte-identical **blank** pages would be flagged `DUPLICATE_IMAGE` with no human distinction (currently moot: 0 flags, 0 groups). Duplicate detection is also scoped to the current book only (fine for distinct scans). **Fix:** hash `Image.open(dest).convert("RGB").tobytes()` (or a cheap perceptual hash) for content identity; build `by_page = {r.page_no: r for r in records}`; consider skipping `folder == "blank"` or requiring ≥2 distinct folders before flagging.

#### n6. `native_size` artifact meta is wrong for Tap2
`pages.py:255`: `"native_size": [records[0].width, records[0].height]` → recorded `[800, 1135]` for **all three books**, but Tap2 has 25 pages at 564×800 (state confirms). **Fix:** record `sorted({(r.width, r.height) for r in records})` and/or `{"min": [...], "max": [...]}`; downstream sanity tooling that consumes the ledger gets wrong data today.

#### n7. Fast `get_image_info()` never carries `xref` — the "~1 s/page fallback" is paid on every page
`pages.py:55-63`. Verified: **0/950 pages** of the three assigned PDFs carry an xref in fast mode (`get_image_info()` returns `number, bbox, transform, width, height, colorspace, cs-name, xres, yres, bpc, size, has-mask` — no `xref`); the xref-aware variant is mandatory. Output is correct (all pages did take the slow path), but the docstring/comment presents the slow path as a rare fallback. **Fix:** document that for these books the two-step approach always pays; or call `xrefs=True` directly and delete the fallback complexity; or gate on a cheap probe of page 1.

#### n8. `_matrix_is_rotated` misses flip placements (negative a/d) — upside-down submissions possible
`pages.py:79-87` inspects only transform components `b`/`c`. A 180° rotation encoded as `a<0, d<0` (with `b=c=0`) is treated as unrotated → the embedded JPEG would be served verbatim → the submitted image displays **upside-down** relative to the PDF's intended orientation. **0 such placements exist in the assigned PDFs** (all 950 pages probed) — latent only. Plus the mirrored-horizontal (`a<0`) case. **Fix:** treat `a < 0 or d < 0` (or sign-flipped scale) as rotated → route to `_save_rgb_jpeg` with the corresponding rotation/flip (or to the render path if ambiguous).

#### n9. No lost/missing-page detection anywhere
Guideline v2.1 requires noting scan-missing pages; `Doc/PROJECT_PLAN.md:313,569` lists "duplicate/missing detection" under Extraction as a blocking gate ("Inventory: Every PDF page accounted once") — but nothing in `src/` detects gaps (no printed-page-number parsing, no notebook cross-check). Gap vs guideline (info; assigned PDFs appear complete).

#### n10. Ledger/provenance nits
(a) `native_jsonl` artifact stored without `sha256` (`pages.py:247-257`) — one-line fix (`sha256_file(manifest_path)`). (b) Manifest overwrites `raw_link` with `"existing"` (see M2). (c) `State.__init__` silently `mkdir`s `data/` (`state.py:105-106`) — masks wrong-cwd invocations that create a stray `./data/`. (d) `_link_or_copy` would treat an existing **directory** named `original.pdf` as `"existing"`. (e) `finish_run` silently no-ops on unknown `run_id`. (f) `default_state` (`state.py:377-378`) duplicates orchestrator's `open_state`.

#### n11. Briefing fact "DUPLICATE_IMAGE flags exist in state" is stale
Current DB (re-checked 2026-11-12): **0** `DUPLICATE_IMAGE` flags; 0 duplicate hash groups in state AND all five backups (2026-11-08, 20261111-230036, 20261112-134510, 2026-11-12-phaseA, 2026-11-12-rebin-fix); README's "950 unique JPEGs" claim is accurate. No action required; noted so the next agent doesn't chase a non-existent flag population. (revised 2026-11-12)

#### n12. Positional indexing in the duplicate loop
`records[page_no - 1]` (`pages.py:240`) — correct today (records appended in page order) but fragile; same refactor as n5.

---

### Verified-good (contract-relevant) — keep as-is

- **Naming rule** `<Tên sách>.NNN[_i].jpg`: 950/950 valid; numbering from 1; zero gaps/dupes; >999-page zero-padding rule correct (`page_number_str(1000)='1000'`, verified for 999/1000/1234/9999/10000 — exactly the guideline's "số trang lớn hơn 999 thì không thêm chữ số 0" rule). `<Tên sách>` = PDF stem including Unicode/spaces/parentheses (`config.py:53-55` as of 2026-11-12, revised; was 48–50) — matches the assigned names.
- **One PDF page = one image**; spreads never split (no splitting code exists); multi-image suffix unused (0 multi-image pages in these books).
- **Native resolution preserved**: unrotated pages copied byte-for-byte from the embedded JPEG stream (sampled, 4/4 byte-identical); rotated pages transposed at exact native size (all 27 verified).
- **Rotation semantics correct**: PDF `/Rotate` is clockwise; PIL transposes counter-clockwise; mappings `90→ROTATE_270, 180→ROTATE_180, 270→ROTATE_90` (`pages.py:103-109`) are right; 180° path verified by `tests/test_extraction.py` and live data.
- **State `page_rotation` ↔ JPEG content match** (the merged PDF stretches each image into the displayed rect; both `_updated.pdf`s verified fresh).
- **950 unique hashes; zero duplicate groups** in state and all five backups (revised 2026-11-12).
- **Raw archives byte-identical** to assigned PDFs (sha256, 3/3).
- **`integrity_check` = ok** (re-verified 2026-11-12); all 950 DB rows ↔ disk ↔ jsonl consistent on Stage-1 fields (Stage-1 only — `folder`/`status` now differ for 950/950 after the 2026-11-12 re-bin; see §3.4) (revised 2026-11-12); all assigned page counts honoured (`book.expected_pages` enforced at both extract sites).
- **Confidentiality-compatible**: raw copies stay in `data/raw/`; source-zip validator blocks `data/`, `.env`, PDFs, `state.sqlite3`, token patterns.
- **Tests pass** — 282 as of 2026-11-12 (was 277 at audit; +5 from the change-set) (revised 2026-11-12).
- **Audited pipeline files**: `intake.py` / `pages.py` / `state.py` / `models.py` unmodified at HEAD (still true — M1–M6 and n1–n12 remain VALID); `config.py` and `orchestrator.py` ARE modified by the 2026-11-12 change-set — the audit's "six audited files unmodified" claim is **false as of 2026-11-12** (revised 2026-11-12).

---

## 5. Concrete fixes / improvements — ordered by expected impact on guideline & submission compliance

**Step 1 (M1) — Stop the re-extraction state wipe.** In `pages.py`, in the `dest.exists() and not force` branch (lines 207-211):
```python
            if dest.exists() and not force:
                with Image.open(dest) as im:
                    width, height = im.size
                method = "existing"
                rotation = ...
                # VERIFY: digest unchanged since last record?
                old = state.page(book.book_id, page_no)
                if old is not None and old.sha256 == sha256_file(dest):
                    method = old.extraction_method or "existing"  # keep provenance
                    state.stage1_update(book.book_id, page_no,
                                        sha256=old.sha256, width=width, height=height,
                                        path=dest, extraction_method=method,
                                        rotation=rotation, image_name=dest.name,
                                        pdf_page=page_no)
                    records.append(replace(old, width=width, height=height, path=dest, rotation=rotation))
                    continue
```
…and add a narrow `State.stage1_update(...)` (or an `upsert_page(..., preserve_downstream=True)` flag) whose `ON CONFLICT` clause touches **only**: `image_name, pdf_page, sha256, width, height, path, extraction_method, rotation, updated_at`. Never `status/script/section/folder/ocr_*/review_flags/features_json`. This single change protects OCR investments regardless of how often extract is re-run.

**Step 2 (M3) — Validate before destroy.** Reorder `extract_book` (`pages.py:190-204`): existence check → `pymupdf.open` → `page_count != book.expected_pages` (+ optionally first-page decode) → **then** `rmtree`/`mkdir`. Also back up `state.sqlite3` (timestamped copy) before any `rmtree`; ideally extract into a sibling temp dir and `os.replace` into place on success (atomic per book).

**Step 3 (M4) — Make `_updated.pdf` a packaging gate, not a courtesy.** In `package.py` / `tools/validate_submission.py`:
1. Load `state`; if **any** page of the book has `rotation != 0`, require `<book_dir>/<BookName>_updated.pdf` else emit `MISSING_UPDATED_PDF` (severity error).
2. Open it: `page_count == book.expected_pages`; each page has exactly one image; `sha256` of each embedded image == `pages.sha256` of that page (embed order == page order). Emit `STALE_UPDATED_PDF` on mismatch.
3. Require `<book_dir>/<BookName>.pdf` (already done) and assert the `_updated.pdf` document is valid via pymupdf open.
4. Print a final block: books with rotated pages, the rotated page lists, and the sentence "If images changed after `<date>`, rebuild with `python tools/build_updated_pdf.py --all` and notify the handout person before submitting." Also have the tool compare `artifacts/updated_pdf/<book_id>_updated_pdf_manifest.json`'s `output_pdf_sha256` against both staged and copied files.

**Step 4 (M2) — Raw-archive integrity in `lock_scope`.**
```python
def _link_or_copy(src: Path, dst: Path, *, expected_sha: str | None = None) -> str:
    if dst.exists():
        if expected_sha is not None and sha256_file(dst) != expected_sha:
            raise IntakeError(f"raw copy diverged from assigned PDF: {dst}")
        return "existing"
    ...
```
Pass `inspection.sha256` in; on mismatch either raise (forcing a human decision) or back up `dst` → `dst.with_suffix('.pdf.bak-<UTC>')`, re-copy/re-link, and re-write the ledger. Record first-run `raw_link` immutably in the manifest (never overwrite `hardlink|copy` with `existing`): keep a `raw_link_first_seen` field or stop writing `raw_link` on re-runs.

**Step 5 (M5) — `tools/verify_images.py` (or extend `validate_submission.py`)** — run before packaging and in CI:
- For every page in `state`: file exists; suffix `.jpg` (case-insensitive); `Image.open(); im.verify()` **and** `im.load()`; sha256 == state; `(width, height)` == state; name matches `^<book_stem>.\d{3,}(_\d+)?\.jpg$`; numbering contiguous 1..N; no `.jpg` under non-expected folders.
- Per book: `sum(len(folder) for folder in (ch, vi, intro, ref, toc, blank, misc, missing/ch, missing/vi))` accounts for `expected_pages` exactly once (with documented ch/missing-ch double placement counted once each); zero non-`.jpg` files anywhere in the book folder; listing unexpected or un- accounted images must fail.
- Exit non-zero with per-book report (counts per folder, per status, rotated pages).
- Cheap adjunct: `python tools/validate_submission.py <zip>` already exists — extend it with the same per-book sweep (it already walks the folders for duplicates).

**Step 6 (M6) — State hardening.**
```python
class State:
    def __init__(self, path):
        ...
        self._conn.execute("PRAGMA quick_check").fetchone()   # or: conn.execute("PRAGMA integrity_check")
        v = self._conn.execute("PRAGMA user_version").fetchone()[0]
        self._migrate(v)                                      # explicit ALTER TABLE steps
```
- `SCHEMA_VERSION = 1`; wrap in try/except `sqlite3.DatabaseError` → raise `StateError(f"state DB corrupt at {path}; restore from newest of: {sorted(path.parent.glob('state.sqlite3.bak-*'))}")`.
- Add `PRAGMA user_version` handling; when adding future columns, do `ALTER TABLE pages ADD COLUMN ...` inside the migration, never rely on `IF NOT EXISTS`.
- Before `extract_book(force=True)` or packaging: `shutil.copy2(state_path, state_path.with_suffix(f'.sqlite3.bak-{utc}'))` (mirror the repo's existing ad-hoc backup habit, but automated).

**Step 7 (n1) — Regenerate `pages.jsonl` at package/report time** from current state (single `_write_pages_jsonl(pages)` call at the end of packaging), or record `"kind": "extraction-snapshot"` in the artifact meta + `updated_at`; document in the report PDF that SQLite is authoritative.

**Step 8 (n2) — Type checks in `update_page`:**
```python
        if key == "review_flags":
            if not isinstance(value, list) or not all(isinstance(f, str) for f in value):
                raise TypeError(f"review_flags must be list[str], got {value!r}")
            value = json.dumps(value, ensure_ascii=False); col = "review_flags"
        elif key == "features":
            if not isinstance(value, dict):
                raise TypeError(f"features must be dict, got {type(value).__name__}")
```
and after `c.execute(...)`: `if c.rowcount != 1: raise KeyError(f"no pages row for {book_id}:{page_no}")` (or add `strict=True` keyword defaulting True).

**Step 9 (n4) — Close the upscale hole:** in `extract_page` fallback compute `largest = max((info.get("width", 0) for info in _placed_image_info(page)), default=0)`; `target_width = max(page.rect.width * 2.0, 1600.0) if largest <= 0 else min(max(page.rect.width * 2.0, 1600.0), float(largest))`; delete the false docstring sentence or scope it to the candidates path.

**Step 10 (n5/n12) — Content-hash duplicates + dict indexing:** hash decoded pixels; `by_page = {r.page_no: r for r in records}`; drop/annotate `DUPLICATE_IMAGE` on `folder == "blank"` pages or gate on ≥2 non-blank pages per hash group.

**Step 11 (n6, n7, n10, n8) — Small wins:** fix `native_size` meta to a size *set*; always call `get_image_info(xrefs=True)` and delete the two-step branch (n7); add `a < 0 or d < 0` to `_matrix_is_rotated` (n8, improves safety at zero cost since no such pages exist); hash `native_jsonl` into the artifact ledger (n10a); preserve first-run `raw_link` (n10b); don't `mkdir` `data/` silently in `State.__init__` (n10c); `_link_or_copy`: `if dst.is_dir() or not dst.is_file(): raise` (n10d); `finish_run`: raise on unknown `run_id` (n10e); dedupe `default_state`/`open_state` (n10f).

**Step 12 (n3) — Re-word, don't re-code:** change README "transposed losslessly" → "transposed at native resolution (JPEG re-encode q95, no resampling)"; change `pages.py` docstring lines 100–102 accordingly; note grayscale→RGB force-conversion.

**Step 13 (n9) — Decide on missing-page detection** (or explicitly scope it out in the report): either parse printed page numbers on TOC/back matter, or add a manual "missing pages" section to the report signed off by a team member (guideline: "Mọi trường hợp trang bị mất … nên được ghi nhận").

**Steps 1–6 are pre-hand-in blockers-in-waiting; 7–13 are polish.** Do 1–6 before any further data transformation (re-extraction, re-packaging) is run.

---

## 6. Downstream contracts map — what this area owns and how it can break

| Contract | Producer / file:line | Consumers | Can this area violate it? |
|---|---|---|---|
| `pages` PK `(book_id, page_no)`, `ORDER BY page_no` | `state.py` 217–227 | classify (`layout.py:context`), OCR router (`ocr/router.py`), align, package | Yes — destructive re-extract wipes `folder/status/script/section` (M1) |
| `image_name` = `<pdf stem>.<NNN[_i]>.jpg`, unique per book | `pages.py:39-52` (verified 950/950) | package (`_copy_jpegs` copies by name), labels (`Label.txt` paths), image_map, validators (`IMAGE_RE`) | Not today (verified); guarantee rests on convention, not constraint |
| `path` absolute, exists at package time | `state.py` 167, `pages.py:223` | `package.py:60-62` (`page.path if page.path.exists() else src_dir/image_name`; `FileNotFoundError` otherwise) | Yes — `--force` (M3); manual deletion; rename |
| `sha256` of the **final** image file | `pages.py:214` | OCR cache keys / quota provenance (`api_calls.image_sha256`), duplicate detection, `tools/build_updated_pdf.py` manifest, this audit | Yes — re-encode under re-extract invalidates OCR cache for rotated pages (silent re-OCR); deterministic today, encoder-dependent tomorrow |
| `rotation` = orientation **already applied** to the JPEG | `pages.py:138-160` | `tools/build_updated_pdf.py` (`rotation != 0 ⇒ rebuild merge`), downstream feature extraction (layouts assume portrait dims) | Yes — flip-in-matrix scans served upside-down (n8); stale `rotation` if file replaced externally (no audit) |
| `extraction_method` | `pages.py:152,160`, `state.py` | README audit trail; this report | Yes — overwritten to `existing` (M1) |
| `review_flags`: JSON array of strings | `state.py:174, 201-203`, `models.py:31` | `layout.py:353,362` (revised 2026-11-12; was 342,351), plus the new `BIN_OVERRIDE` writer at `layout.py:345–349` (flags `BIN_OVERRIDE_VI` at 345 / `BIN_OVERRIDE_MISC` at 348 — declared in `books/*.yaml` as `inventory_vi`/`inventory_misc`; **no `BIN_OVERRIDE_*` flags present in the DB today** — the 2026-11-12 re-bin was DB surgery); `orchestrator.py:216,266`, `ocr/router.py:367-374` (all `sorted(set(...))` merges) | Yes — type-corrupting writes round-trip as str/int (n2); wipe on re-extract (M1) |
| `features_json`: JSON object | `state.py:175,204-206`, `models.py:32` | `layout.py` (classification features), report | Yes — same classes of failure as above (M1/n2) |
| `folder ∈ {ch,vi,intro,ref,toc,blank,misc,missing_ch,missing_vi}` | `models.py:12` Literal; written by classify (and by the new `BIN_OVERRIDE` re-bin path, `layout.py:342–348`, on re-run — writes `vi`/`misc`) (revised 2026-11-12) | `package.py:192-217` folder mapping; submission layout | Yes — M1 writes `folder=""` ⇒ page silently excluded from all folders |
| `status` pipeline: `extracted → classified → ocr_done` | `layout.py:354` (revised 2026-11-12; was 343), OCR stage | resume logic, metrics gating, report | Yes — M1 resets to `extracted` |
| `pages.jsonl` artifact (`stage=pages, key=native_jsonl`) | `pages.py:245-257` | auditor/report expectation; **zero code callers** | Yes — staleness (n1); now extends to `folder`/`status` post-re-bin (950/950 inconsistent, 2026-11-12, revised); nothing breaks, misleading docs only |
| `artifacts` ledger semantics | `state.py:326-358` | audits, this report; `native_jsonl` consumed by docs | Yes — no sha256 for jsonl; `native_size` wrong (n6); `raw_link` overwritten (M2) |
| `data/raw/<book>/original.pdf` immutability & identity | `intake.py:98-147` | provenance for confidential-books audit; nothing technical | Yes — stale copy undetected (M2) |
| One PDF page ⇒ exactly one image; no spread splitting | design of `pages.py` (no splitting code) | guideline compliance; package accounting (M5) | Not violated today; nothing enforces it automatically |

**Net assessment:** the *bytes* are correct and reproducible; the *state machine* around them is the fragile part. Re-extraction after OCR/review, packaging after any mis-ordering, and recovery from a corrupt DB are the three ways this area can still sink the hand-in.

---

## 7. Reproduction commands

Run from `C:\Users\MSI VN\Desktop\NLP`. **All are read-only.** Do **not** run `hannom extract [--force]`, `build_updated_pdf.py`, or anything that writes under `data/`.

```powershell
# 7.1 Full test suite (no GPU/OCR/network needed)
$env:PYTHONIOENCODING='utf-8'; python -m pytest -q        # 282 passed (2026-11-12; re-measured after the uncommitted 2026-11-12 change-set; was 277 at audit)

# 7.2 Read-only SQLite queries (Windows console shows UTF-8 mojibake; files are fine)
#     (both outputs re-verified read-only 2026-11-12: DUPLICATE_IMAGE → (0,); integrity_check → ok)
python -c "import sqlite3; c=sqlite3.connect(f'file:C:/Users/MSI VN/Desktop/NLP/data/state.sqlite3?mode=ro', uri=True); c.row_factory=sqlite3.Row; print([dict(r) for r in c.execute('SELECT book_id, kernel := NULL FROM pages')])"   # (shape only; see probes below)

# Minimal equivalents:
python -c "import sqlite3; c=sqlite3.connect('file:C:/Users/MSI VN/Desktop/NLP/data/state.sqlite3?mode=ro', uri=True); print(c.execute('SELECT book_id, COUNT(*), SUM(CASE WHEN rotation!=0 THEN 1 ELSE 0 END) FROM pages GROUP BY 1').fetchall())"
python -c "import sqlite3; c=sqlite3.connect('file:C:/Users/MSI VN/Desktop/NLP/data/state.sqlite3?mode=ro', uri=True); print(c.execute('SELECT COUNT(*) FROM pages WHERE review_flags LIKE \"%DUPLICATE_IMAGE%\"').fetchone())"   # (0,)
python -c "import sqlite3; c=sqlite3.connect('file:C:/Users/MSI VN/Desktop/NLP/data/state.sqlite3?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchall())"

# 7.3 Unrotated verbatim-copy spot check (compares against embedded stream in memory; writes nothing)
python -c "import sys,json; sys.path.insert(0,'src'); import pymupdf; from pathlib import Path; m=json.loads(Path(r'C:/Users/MSI VN/Desktop/NLP/data/raw/T1_CamPhong_Tap1/manifest.json').read_text(encoding='utf-8')); d=pymupdf.open(m['assigned_pdf']); x=int(d[0].get_image_info(xrefs=True)[0]['xref']); print(d.extract_image(x)['image'] == Path(r'C:/Users/MSI VN/Desktop/NLP/data/pages/T1_CamPhong_Tap1/native/T1_Cấm Phòng Cho Bổn Đạo (Tập 1).001.jpg').read_bytes())"

# 7.4 Rotated-page freshness of <Book>_updated.pdf (all 27 pages; ~30 s; writes nothing)
#     Embedded-image bytes vs current native sha256; see verify-A/probe15.py (re-runnable).

# 7.5 950-file naming/contiguity sweep (see verify-A/probe7.py)

# 7.6 Scratch probes (read-only)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-A\probe1.py" ... probe17.py   # needs $env:PYTHONIOENCODING='utf-8'
```

File existence / counts without any DB:

```powershell
$bytes=(Get-ChildItem "C:\Users\MSI VN\Desktop\NLP\data\pages\T1_CamPhong_Tap2\native" -File | Measure-Object Length -Sum)
Get-ChildItem "C:\Users\MSI VN\Desktop\NLP\data\pages\*\native\*.jpg" | Measure-Object   # 950
```

Git provenance:
```powershell
git -C "C:\Users\MSI VN\Desktop\NLP" log --oneline -1   # c3439e7 (still HEAD; the 2026-11-12 change-set is uncommitted)
git -C "C:\Users\MSI VN\Desktop\NLP" status --porcelain -- src/hannom/intake.py src/hannom/pages.py src/hannom/state.py src/hannom/models.py   # (empty = the four Stage-0/1 pipeline files unmodified — still true)
git -C "C:\Users\MSI VN\Desktop\NLP" status --porcelain -- src/hannom/config.py src/hannom/orchestrator.py   # NOW lists BOTH as modified (2026-11-12 change-set) — the audit's "empty = unmodified" expectation for these two is FALSE (revised 2026-11-12)
```

**Do not:** call the Kim Hán Nôm API; read `.env`/`hannom_API.md`; run `hannom extract` (would overwrite downstream state today — see M1/M3); restore `data/state.sqlite3` from backups without a fresh verified backup; submit without Step 3's gate + the human notification step.

---

## 8. Handoff checklist for the next agent

Do these in order before the 2026-11-30 submission:

1. **Freeze the bytes.** Do not re-extract or re-encode anything. If any change to images is unavoidable, FIRST `cp data/state.sqlite3 "data/state.sqlite3.bak-$(date +%Y%m%d)"` and `cp -r data/pages "data/pages.bak-$(date +%Y%m%d)"`, and rebuild `_updated.pdf` afterwards (`tools/build_updated_pdf.py --all`), then re-verify embedded-bytes == native sha256 (probe15 logic).
2. **Implement Steps 1–6 of §5** (M1–M6 fixes) on a branch — currently unfixed defects; M1/M3 are active hazards for any re-run; M4/M5/M6 are the difference between "demo passes locally" and "hand-in passes review". **(revised 2026-11-12) M1 is no longer theoretical: the 2026-11-12 re-bin was applied via direct DB surgery rather than a classify re-run — consistent with the M1 hazard (a re-run would have wiped `ocr_done`). Treat M1 as the top-priority fix; do not let anyone "just re-classify".**
3. **Re-verify the invariants** (§3): 282 tests pass (re-measured 2026-11-12; was 277 at audit); 950 rows↔disk; 950 unique hashes; 27 rotated pages; naming sweep; `integrity_check=ok`; folder splits Tap1 130/130/0/0/6/16, Tap3 50/50/0/0/6/12, Tap2 unchanged (ch/vi/toc/intro/blank/misc) (revised 2026-11-12).
4. **Run `tools/verify_images.py`** (Step 5) — or the extended `validate_submission.py` — against a freshly built submission: JPEG decodability, name regex, per-book accounting, no `.png`, sha256 vs state.
5. **Gate `_updated.pdf`** (Step 3): require for both rotated books (Tap1 p263/p274 @180°; Tap2 list §3.2); verify freshness and one image/page.
6. **Confirm the human step**: handout-person notification sent (or explicitly assigned), covering: image re-orientation on 27 pages, the two `_updated.pdf` files, and `<Tên sách>_image_map.json`. The guideline requires notification in writing; README (lines 54–59) notes this is mandatory and currently outstanding. Add the notification to the report PDF's notes.
7. **Record missing pages** (n9): either implement or explicitly document "no scan-missing pages observed; evidence: printed page order continuous at section transitions (all 950 spot-checked)" in the report; get a human to sign it off.
8. **Fix ledger meta bugs** (n6): correct `native_size` artifact reading (or stop consumers from relying on it); add sha256 for `native_jsonl` at next packaging.
9. **Do NOT rely on** `pages.jsonl` after any further stage runs; it is stale today for 950/950 rows (n1) unless Step 7 is done.
10. **Report honestly** any re-run of `extract`: state statuses reset unless Step 1 lands; if anyone re-ran extract without fixing M1, expect `status='extracted'`, `folder=''` everywhere — treat OCR artifacts as orphaned and re-run classify (`hannom classify`) + OCR before packaging. **(revised 2026-11-12)** Note for the record: the 2026-11-12 re-bin was NOT produced by a classify re-run — no `BIN_OVERRIDE_*` flags exist in the DB; it was direct DB surgery (see M1 corroboration note and §3.4). A future `hannom classify` re-run WILL apply the declarative `inventory_vi`/`inventory_misc` from `configs/books/*.yaml` and write `BIN_OVERRIDE_VI`/`BIN_OVERRIDE_MISC` flags (layout.py:345–349) — that is by design, but it would also wipe `ocr_done` unless Step 1 lands first.
11. **Backups**: keep `data/state.sqlite3.bak-2026-11-08` untouched — it is the only record of `embedded:xref=…` provenance and the 2026-11-08 `classified`-era state. Do not prune. **(revised 2026-11-12)** There are now **five** backups — also preserve `data/state.sqlite3.bak-2026-11-12-phaseA` (11/12 13:45) and `data/state.sqlite3.bak-2026-11-12-rebin-fix` (11/12 19:36): the only snapshots of the pre-final-re-bin state (at both, Tap1 `misc = {1,145}`, Tap3 `misc = {1,64}`); `-rebin-fix` additionally captured the transient invalid-folder state (`other` ×24 / `translation` ×8) since corrected. They must survive alongside `bak-2026-11-08` in any backup/restore drill — five files, all listed in §3.4.
12. **Spelling/encoding**: keep Vietnamese names byte-exact (NFC) in any new tooling; console display mojibake is cosmetic. Use `$env:PYTHONIOENCODING='utf-8'`.
13. If anything in this report is later found wrong, **amend this file** rather than leaving a stale verdict — the next agent reads this, not my chat.

---

## 9. Caveats & limitations of this audit

- **Byte-identity verified by sampling, not exhaustively.** Unrotated verbatim claim: 4/4 sampled pages are byte-identical to embedded streams; full 923-page verification would require parsing every PDF page's image dict (~15+ min via `xrefs=True`, deliberately avoided as out of scope/unnecessary given deterministic copy logic). Rotated pages: all 27 verified by size match + pixel histogram comparison + spot diffs (mean |Δ| 0.3–0.7/255) — histograms are re-encode-sensitive, not a bitwise comparison (which is impossible: q95 re-encode is lossy).
- **Metadata, not OCR semantics.** This audit covered Stage 0/1 and the state layer only; OCR content, labels, alignment quality, dictionaries, evaluation metrics, and the report PDF were **not** reviewed.
- **`extraction_method` history is reconstructed from backup DBs**, not from a log — `data/state.sqlite3.bak-2026-11-08` shows `embedded` ×950; later backups show `existing` ×950; exact re-run chronology is inferred from file mtimes and snapshot contents, not from an audit trail (there is none).
- **No functional testing of failure paths** beyond what's described (e.g. actual corrupt-DB behaviour of the pipeline binary); failure-mode claims for M6/n2/M3 rest on code reading + scratch-lane demonstrations, not on end-to-end runs.
- **Windows-specific**: inode identity checks used `os.stat`/`ctypes` on NTFS; volume mount semantics differ elsewhere. Crosses-mount hardlink fallback (`EXDEV → copy2`) treated as correct by inspection; not exercised cross-volume here.
- **Console mojibake**: Vietnamese names render corrupted in some embedded output captures; verified via Python `ord()` inspection instead — file names/paths themselves are fine UTF-8.
- **`pytest` count (282)** as re-measured read-only 2026-11-12 **after the uncommitted 2026-11-12 change-set**; the audit itself ran at 277. Counts may drift with future commits. (revised 2026-11-12)
- **The state changed after the audit.** The 2026-11-12 change-set re-binned Tap1 (front matter PDF 13–20 → `vi/`; `5, 7–11, 277–282, 143, 144` → `misc/`) and Tap3 (`2, 3, 5, 7, 8, 9, 62, 63, 117, 118` → `misc/`) via **direct DB surgery** — no `BIN_OVERRIDE_*` flags in the DB; `.bak-2026-11-12-phaseA` (11/12 13:45) and `.bak-2026-11-12-rebin-fix` (11/12 19:36) preserve the pre-final state (at both, Tap1 `misc = {1,145}`, Tap3 `misc = {1,64}`; `-rebin-fix` additionally captured a transient `other` ×24 / `translation` ×8 invalid-folder state, since corrected). The audit's code-level findings (**M1–M6, n1–n12**) target `intake.py` / `pages.py` / `state.py` / `models.py`, all unmodified — they remain **VALID**. All figure-level numbers in this report (folders §3.1, flags §3.4, backups §3.3/§3.4, ledger staleness §3.4, pytest §3.6/§7/§8) were re-measured read-only on 2026-11-12 and are current as of that re-measurement; they will drift again with the next re-bin/classify run. (revised 2026-11-12)
- **Deployment invariant not testable here:** whether a fresh machine/`data/` wipe + full pipeline re-run reproduces today's outputs was **not** tested (would require the API/quota and hours of OCR).
- **No verification** that `_updated.pdf` displays correctly in a PDF viewer (structure verified: 1 image/page, native bytes, page count, freshness — visual check remains a human step).
- **`native_size`/`DUPLICATE_IMAGE`/`jsonl` staleness** were measured (jsonl staleness extended to `folder`/`status` after the 2026-11-12 re-bin — revised 2026-11-12); other artifact metas were not exhaustively cross-checked against disk.
- **The 45% area threshold** for `_image_candidates` (`pages.py:74`) interacts with scan margins; not exercised by these books (all pages ≥45% coverage, single-image).
- **`image_only` gate**: verified to accept these books and abort on a synthetic hidden-text PDF; whether aborting is the *right* policy for future assigned books with invisible OCR layers was not adjudicated — flagged as design rigidity, not a defect.
- **License/privacy**: none of the confidential scans' content was OCR'd, copied, or transmitted; the API was never called.

---

## 10. Revision log

**2026-11-12 (post map-repair change-set)** — what changed in this file and why. All edits were made read-only against the repo with a text editor; no `data/` writes, no API calls, no pipeline stages, no installs; `$env:PYTHONIOENCODING='utf-8'` throughout; verification queries ran `mode=ro` against `data/state.sqlite3` and the artifact ledger and file mtimes.

1. **Added the top banner** (directly under the title) summarizing the uncommitted 2026-11-12 change-set (branch `feat/map-repair-align`, HEAD still `c3439e7`, ZERO new commits) and stating that figure-level numbers were re-measured read-only on 2026-11-12.
2. **Header block**: the audit-time claim "the six audited source files were unmodified" is now **FALSE** and was rewritten — `config.py` (+`inventory_vi`/`inventory_misc` ~44–50, `load_config` ~163–168, `book_name` 48–50→53–55) and `orchestrator.py` (net-0; `stage_labels` folder tuple ~169 gained `"misc"`) are modified; only `intake.py` / `pages.py` / `state.py` / `models.py` remain unmodified. `HEAD` remains `c3439e7`; the change-set is uncommitted.
3. **Line citations re-anchored** for post-change-set files: `layout.py` 342→353 (`sorted(set(...))`) and 343→354 (`status="classified"`), with the new `BIN_OVERRIDE` writer at `layout.py:345–349` (flags `BIN_OVERRIDE_VI` at 345, `BIN_OVERRIDE_MISC` at 348) and the block at ~339–349; `config.py` `book_name` 48–50→53–55; `orchestrator.py` citations (216/266) unchanged (net-0). `align.py`/`textdiff.py` are not cited in this report, so no re-anchoring was needed here.
4. **§3.1**: Tap1 folder split 130/124/16/4/6/2 → **130/130/0/0/6/16** (ch/vi/toc/intro/blank/misc); Tap3 50/52/4/4/6/2 → **50/50/0/0/6/12**; Tap2 unchanged; totals **560 / 390** unchanged ✓ (statuses were not re-derived). Note added: re-bin applied via DB surgery — no `BIN_OVERRIDE_*` flags in the DB.
5. **§3.3/§3.4/§4 M6/§8**: backup census **three → FIVE** — adds `…bak-2026-11-12-phaseA` (11/12 13:45:10) and `…bak-2026-11-12-rebin-fix` (11/12 19:36:40), both pre-date the final re-bin (at both, Tap1 `misc={1,145}`, Tap3 `misc={1,64}`); `-rebin-fix` additionally captured a transient invalid-folder state (`other` ×24 / `translation` ×8), since corrected. `bak-20261112-134510` (13:44:39) and `-phaseA` (13:45:10) were taken ~1 minute apart.
6. **§3.4**: `integrity_check` re-verified `ok`; `api_calls` = 550 (0 on 11/12); statuses unchanged; distinct flags updated — `LABEL_EMPTY_OCR` 804→**808** (Tap1 267→269, Tap3 0→2, Tap2 537); non-empty `review_flags` 900→**902** (Tap1 274→275, Tap3 85→86, Tap2 541); `DUPLICATE_IMAGE` stays 0; **no `BIN_OVERRIDE_*` flags in the DB** (re-bin = DB surgery, §3.4 + M1). Artifact ledger staleness documented: Tap1 `layout/image_map` row dated 11-08 (meta `pairs=124` vs file's 127 pairs; file mtime 11/12 19:37); Tap1 `layout/classification` row pre-re-bin; Tap3 `layout/*` rows 11/12T06:24Z pre-re-bin (`vi:52/misc:2` vs current `vi:50/misc:12`); Tap1 `align/csv` + `evaluation/metrics` re-written 2026-11-12T12:43Z; Tap2 artifacts untouched (11/08); all three `native_jsonl` rows sha256-NULL; Tap1/Tap2 `native_jsonl` rows still 11-08, Tap3 re-stamped 11/12T06:24Z.
7. **§3.1/§3.3/§4/§7/§8/§9**: counts of backups and pytest updated (**277 → 282**, +5 from `test_charstream.py` / `test_map_repair.py`; §3.6, §7.1, §8 item 3, §9); git-status repro expectation fixed (`git status --porcelain` for `config.py`/`orchestrator.py` now shows both as modified); §7.2 outputs re-verified read-only (DUPLICATE_IMAGE `(0,)`; integrity `ok`); §8 gained an M1-corroboration warning (item 2), updated invariant list (item 3), re-bin/`BIN_OVERRIDE` note (item 10), and the five-backup preservation list (item 11).
8. **§4 M1**: added a revised corroboration paragraph — the 2026-11-12 re-bin was applied via direct DB surgery precisely to avoid wiping `ocr_done`; this validates M1's hazard class on the project's own fix-up path. **M1–M6 and n1–n12 remain VALID** (`intake.py` / `pages.py` / `state.py` / `models.py` unmodified); the two modified files (`config.py`, `orchestrator.py`) carry no audited defects.
9. **§6**: `review_flags` row cites `layout.py:353,362` + the new `BIN_OVERRIDE` writer at `layout.py:345–349`; `folder` row documents the `BIN_OVERRIDE` re-bin path (writes `vi`/`misc` on re-run); `status` row cites `layout.py:354`; `pages.jsonl` row notes staleness extended to `folder`/`status` (950/950, revised).
10. **§3.4/§4 n1/§6**: `pages.jsonl` staleness extended — now inconsistent with SQLite on `folder`/`status` for 950/950 rows (re-measured), in addition to flags/features.
11. **§2 kept as-is** (historical; still accurate); **§3.5** `_updated.pdf` freshness claims marked re-confirmed unchanged (both files mtime 11/08; images 950/950 untouched by the change-set; all 27 rotated pages still byte-match).
12. All substantive revisions carry the tag **"(revised 2026-11-12)"**; unmarked content remains as audited 2026-11-12 (pre-change-set) and is still accurate. M1–M6/n1–n12 numbering preserved.

**Why:** the 2026-11-12 change-set (map repair + declarative re-bin) changed folder assignments and shifted line numbers in `layout.py`/`config.py`; every figure in §3 was re-measured read-only on 2026-11-12. Nothing in `data/` was modified; the pipeline was not run; the Kim Hán Nôm API was not called.

---

*End of report — Area A (revision 2026-11-12 applied; see §10 Revision log). Scratch probes: `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-A\probe1..17.py`. Contact path: this file + `Doc/PROJECT_PLAN.md` + `README.md` for repo intent.*
