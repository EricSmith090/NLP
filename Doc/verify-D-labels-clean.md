# Area D verification — Labels + Clean (handoff report)

> **REVISION 2026-11-12 (post map-repair change-set):** written against pre-`feat/map-repair-align` state; the collaborator's uncommitted 2026-11-12 change-set (image_map repair; Tap1/Tap3 scope re-bin (vi 013–020 now vi; glossary/cover/back-matter/foreword → misc); `hannom.charstream` dịch-âm segmenter; align CSVs rebuilt; labels REGENERATED (Tap1 fully rebuilt 2026-11-12T19:36 and DB-consistent; Tap3 stale/incomplete); tests 277→282, all pass) is incorporated. Claims revised inline. Numbers re-measured read-only 2026-11-12.

**Audience**: the next agent. No prior context assumed.
**Date**: 2026-11-12 (re-verified/revised 2026-11-12) · **Repo**: `C:\Users\MSI VN\Desktop\NLP` (Windows) · **Branch**: `feat/map-repair-align` @ `c3439e7` (repair-branch tip on origin; **ZERO new commits** — all change-set work is uncommitted) · **Tests**: `python -m pytest -q` → **282 passed** (was 291)
**Status at verification time** (revised 2026-11-12): structurally valid, semantically incomplete — unchanged conclusion, but the label state is now **bifurcated**: **Tap1** labels fully rebuilt 2026-11-12T19:36:49 and **consistent with the DB**; **Tap3 (SuaLoiQuyen)** labels rebuilt 19:35:42 but **stale/incomplete vs the re-binned DB** (re-bin applied to DB ~19:43, after the label rebuild); **Tap2** untouched (2026-11-08). Format gates pass; content does not (Tap2 empty, Nôm 〓 rule unimplemented, Nôm sanitizer output discarded).

---

## 1. Scope & files

Verification of area D only — PPOCRLabel label generation/validation (Stage: `labels`) and OCR-text cleaning (Stage 5).

| File | Lines | What it does |
|---|---|---|
| `src/hannom/labels.py` | 293 | `write_label_txt`, `write_file_state`, `validate_label_txt`, `line_to_box`, `clamp_quad`, `points_to_quad`, `read_label_txt`/`parse_label_line`, `filter_boxes_by_script` |
| `src/hannom/clean.py` | 496 | `clean_nom_lines`/`clean_nom_page`/`clean_quoc_ngu_page`, `_FULLPAGE_LEADING_MARK`, `_strip_leading_page_marker`, `_strip_trailing_title`, `_join_hyphenated_lines`, `detect_running_lines`, `is_safe_codepoint`, `sanitize_nom_text`, `validate_clean_text` |
| `src/hannom/orchestrator.py` | 571 | `stage_labels` (folder tuple ~line 169 — now `("ch","vi","intro","ref","toc","misc")`, gained `"misc"`; net 0 lines, line cites unchanged), `stage_clean`, `_label_script`, `_sort_lines` (only these — rest out of scope) |
| `src/hannom/models.py` | | `OCRLine` (line 42) — dataclass `{text, points, confidence, script, difficult, extra}` |
| `src/hannom/align.py` | | `_split_long_text` (line 108; was line 97), `NOM_TERMINAL_RE` (line 33) — referenced only for the U+FF0C finding below |
| `configs/ocr.yaml` | | engine routing: kimhannom (API, Nôm), vintern_1b_v2 (local, QN, whole-page), paddleocr_vl |
| `configs/project.yaml` | | books: Tap1, Tap2, SuaLoiQuyen |
| `Quy_định_đồ_án_v2.1.extracted.txt` | | guideline § "Quy định chung về file OCR" — Label.txt/fileState.txt format, 4 points, `〓`/U+3013 rule, Nôm column order |
| Data under verification | | `data/labels/<book>/{ch,vi,intro,toc,misc}/{Label.txt,fileState.txt}` (misc since the 2026-11-12 re-bin; revised), `data/clean/<book>/*.json`, `data/state.sqlite3` (read-only), `data/ocr/<book>/*.json`, `data/pages/<book>/native/*.jpg` |

**No Tap3 exists.** The three configured books are `T1_CamPhong_Tap1`, `T1_CamPhong_Tap2`, `T1_SuaLoiQuyen` (pdf stems: `T1_Cấm Phòng Cho Bổn Đạo (Tập 1)`, `…(Tập 2)`, `T1_Sửa Lưỡi Quyển`). (The change-set refers to SuaLoiQuyen as "Tap3" throughout; terminology kept.)

---

## 2. Method & ground rules

- **READ-ONLY** on repo and `data/`. No API calls. `.env` and `hannom_API.md` never read.
- Scratch (probes + dumps): `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-D\` — files named `probe_*.py/.txt`. This report supersedes `REPORT.md` there. Revision re-measurements (2026-11-12) live under `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-D\` (`probe1..5.py`; outputs quoted inline).
- Spot signature checks performed on the cleaned outputs, labels, state DB, OCR cache, and page images (all via `sqlite3 … mode=ro` or text reads; verification edits were **not** applied to any repo file).
- Internet used only to confirm PPOCRLabel conventions (PFCCLab/PPOCRLabel README, PaddleX docs, PaddleOCR issue #12048): Label.txt = `<folder>/<image>\t[{"transcription","points[4]"}…]`, fileState.txt = `<folder>/<image>\t<0|1>`, LF lines — repo format is correct.
- Validation pattern: `validate_label_txt(label_path, image_dir, folder, state_path, require_all_images=False, strict_points=True)` where `image_dir = data/pages/<book>/native` (folder prefix stripped). All **12 existing** folders were checked this way — Tap1 ch/vi/misc, Tap2 ch/vi/intro/toc, SLQ ch/vi/intro/toc/misc (the 2026-11-12 re-bin deleted Tap1's intro/toc folders and made SLQ's `misc` populated; **the audit loop must now be misc-aware**, i.e. `['ch','vi','intro','toc','misc']`, otherwise the stale Tap3 rows and Tap1 misc are silently missed) — plus folder-membership equality vs `state.sqlite3.pages` (**fails for Tap3 and Tap2 — see §3.1**), image existence (929/929 on-disk rows via `native`; validator read real image dims for all 12 folders), and fileState values.
- Regex and ordering claims verified empirically (synthetic strings + all 104 flagged pages cross-checked against `data/ocr/<book>/*.json` raw first lines).
- `git status` at end of re-verification (2026-11-12): **9 modified** files (`configs/alignment.yaml`, `configs/books/T1_CamPhong_Tap1.yaml`, `configs/books/T1_SuaLoiQuyen.yaml`, `docs/decisions.md`, `src/hannom/align.py`, `src/hannom/config.py`, `src/hannom/layout.py`, `src/hannom/orchestrator.py`, `src/hannom/textdiff.py`) + untracked: **5 new source/tool files** (`src/hannom/charstream.py`, `src/hannom/map_repair.py`, `tools/repair_image_map.py`, `tests/test_charstream.py`, `tests/test_map_repair.py`), the 9 `Doc/verify-*.md` handoff docs, and `submission/`. **ZERO new commits**; branch `feat/map-repair-align`, HEAD `c3439e7`. (Replaces the pre-rebin claim of "only pre-existing untracked files … nothing modified" — that is FALSE now.)

---

## 3. Labels — validation results

### 3.1 Format validation (all 12 existing data/labels folders)

`validate_label_txt` issues: **0 for all 12 existing folders** (Tap1 ch/vi/misc, Tap2 ch/vi/intro/toc, SLQ ch/vi/intro/toc/misc) — re-checked 2026-11-12 (revised). Per folder:

- Rows == images in that folder per state — **now FAILS for Tap3, and for Tap2's misc page** (revised 2026-11-12):
  - **Tap1 — FULLY REBUILT 2026-11-12T19:36:49 and DB-consistent** ✓: ch 130/130 (1,793 boxes, byte-identical to pre-rebin), vi 130/130 (rows `013`–`142`, 1 empty `[]` — page `.083`), misc 16/16 (rows `001,005,007,008,009,010,011,143,144,145,277,278,279,280,281,282`; 13 boxes; 3 empty `[]` on `001,009,145`). Tap1's intro/toc folders are **ABSENT on disk and ABSENT in DB** (re-bin moved the front/back matter to misc/vi) — consistent both sides ✓. fileState.txt all `\t1`; misc rows are full-page-bbox pattern (verified ≈1.0 page coverage). Tap1 boxes: ch 1,793 / vi 129 / misc 13.
  - **Tap3 — REBUILT 19:35:42 BUT STALE/DESYNCHRONIZED vs DB** (revised): ch 50/50 ✓ and vi 50/50 ✓ rebuilt & consistent; **misc/Label.txt contains ONLY 2 rows** (`001.jpg`, `064.jpg`, both empty `[]`) **vs DB misc = 12** (`{001,002,003,005,007,008,009,062,063,064,117,118}`): the CHÚ THÍCH glossary pair **`062`/`063` is labeled NOWHERE**, and the 10 other re-binned misc pages (`002,003,005,007,008,009,062,063,117,118`; all vintern-engine, never got label rows) have NO labels. **Stale leftover label files** remain: `intro/Label.txt` (`002,003,005,009`; 4 rows/4 boxes) and `toc/Label.txt` (`007,008,117,118`; 4 rows/4 boxes), mtimes `2026-11-12T13:24` (stale) — **DB intro/toc = 0**, so 4+4 rows disagree with the 0 state. fileState all `\t1` everywhere **including the stale files**.
  - **Root cause** (revised): the Tap3 re-bin was applied to the DB via surgery **~19:43, after** labels were rebuilt at 19:35 (DB backup `state.sqlite3.bak-2026-11-12-rebin-fix`, ~19:36). Tap1's label rebuild at 19:36:49 landed after the fix → consistent. `decisions.md`'s claim "Tap3 labels refreshed including misc" is only loosely true (refreshed ≠ complete).
  - **Tap2 — UNTOUCHED (2026-11-08)**: ch 264/264, vi 267/267, intro 2/2, toc 10/10 ✓; DB has **1 misc page (`.001`) but Tap2 has NO `misc/` label folder** (stage not re-run for Tap2) — 543/544 DB pages labeled.
  - On-disk label rows total: **929** (was 927). Folder-membership equality vs state now fails for **Tap3** (misc 2 on-disk vs 12 DB; 8 stale intro/toc rows vs 0) and **Tap2** (misc `.001` unlabeled); passes for Tap1 (276/276).
- Prefix rule `<folder>/<imageName>`: **0 violations** (929 rows checked; revised).
- Points: exactly 4 per box; all boxes inside image dimensions (validator passed with real image dims).
- Transcription: no `\n`/`\r` anywhere (strict check passed).
- Line endings LF; no BOM (12/12 files); `fileState.txt` key-set == Label.txt key-set; every fileState value == `1` (12/12 files, **929/929 rows** — including the stale Tap3 intro/toc and Tap3 misc; fileState≡1 remains not proof of currency/completeness; revised).
- Reading order: ch (Nôm) boxes with tall geometry sorted by `(−x_center, y0)` — **0 violations in 444 ch pages** (Tap1 0/130 re-verified, Tap2 0/264, SLQ 0/50 re-verified 2026-11-12). QN row-major `(y0, x0)` — correct per guideline.
- Vintern QN boxes are **whole-page rects** (clamped to `799×1134`); guideline allows "nếu công cụ không hỗ trợ thì đánh 1 box cho toàn trang". **100% of QN-style boxes have ≥85% page-area coverage (re-verified 2026-11-12; all min-cov = 1.000)**: Tap1 **142** (129 vi + 13 misc), SLQ **58** (50 vi + 4 stale intro + 4 stale toc; misc rows are `[]`), Tap2 **3** (vi) — was Tap1 175 / SLQ 60. ch boxes are 9–16 line/column boxes per page (line-level annotation, correct).
- **`misc` folders now EXIST and carry labels** (revised 2026-11-12 — this bullet previously claimed misc was "correctly absent … as the guideline requires", which is FALSE now): Tap1 `misc/` has 16 rows / 13 full-page boxes (3 empty `[]`); Tap3 `misc/` has only 2 empty rows vs DB 12 (incomplete — see above); Tap2 has none. The **guideline does not forbid misc/apparatus labels** — they are intro/toc-like apparatus for submitted data and are acceptable as long as fileState≡1 and Label.txt exists. The hard guideline is unchanged: `Label.txt` may exist only for ch/vi or apparatus actually shipped, and **`missing/` may never carry labels** (still true everywhere — no `missing/` folder exists under `data/labels`). `blank/` remains correctly absent from labels everywhere ✓ (no Label.txt/fileState.txt); no `ref/` folder exists anywhere (ref unused). Image filename rule holds for all 950 pages: `<pdf_stem>.<NNN>.jpg`, `bad_prefix=0`, numbering contiguous 1..N per book (282/550/118) — `data/pages` unchanged by the change-set.
- Boxes: **2,487 total** (ch **2,284** [1,793 Tap1 + 38 Tap2 + 453 SLQ — unchanged] / **vi 182** = 129 Tap1 + 3 Tap2 + 50 SLQ / intro **4** (stale Tap3 only) / toc **4** (stale Tap3 only) / **misc 13** (Tap1) + 0 (Tap3)); **non-empty rows 386** (was 388). (Revised 2026-11-12.)

### 3.2 Empty boxes vs guideline

| Book | Folder | Empty `[]` rows / total | Boxes |
|---|---|---|---|
| Tap1 | vi | **1** / 130 (page `.083`, flags only `PAGE_MARK_REMOVED`) | 129 |
| Tap1 | misc | **3** / 16 (pages `.001`, `.009`, `.145`, all `[]`) | 13 |
| Tap1 | ch | 0 / 130 | 1793 |
| Tap2 | ch | **261** / 264 (only 3 pages OCR'd: 38 boxes) | 38 |
| Tap2 | vi | **264** / 267 (only 3 pages OCR'd: 3 boxes) | 3 |
| Tap2 | intro | **2** / 2 | 0 |
| Tap2 | toc | **10** / 10 | 0 |
| SLQ | ch | 0 / 50 | 453 |
| SLQ | vi | 0 / 50 (was 52 boxes — 2 pages re-binned to misc, unlabeled) | 50 |
| SLQ | intro (stale vs DB 0) | 0 / 4 | 4 |
| SLQ | toc (stale vs DB 0) | 0 / 4 | 4 |
| SLQ | misc | **2** / 2 (pages `.001`, `.064`, both `[]`) | 0 |
| **Total** | | **543 / 929 on disk (58.5%)** (was 539 / 927, 58.1%) | 2,487 |

(Tap1's `toc` row — previously 1 / 16 empty, page `.009` — is GONE: the folder no longer exists; page `.009` now lives in `misc` with an empty `[]` row, still flagged `LABEL_EMPTY_OCR`+`TOC_LIKELY_FRONT`.)

**Note on the change-set tally "empties 555" (revised 2026-11-12)**: the on-disk re-measure gives **543**, cross-checked two ways (per-folder recount; and 808 LABEL_EMPTY_OCR flags − 266 flagged-with-boxes = 542 flagged-empty + 1 unflagged empty (`vi .083`) = 543, consistent with non-empty 386 + 543 = 929 rows). 555 does **not** reconcile with the other re-measured numbers (929 − 386 ≠ 555); it appears to add **all 12** Tap3 DB-misc pages onto 543 (double-counting the 2 labeled-empty rows) instead of the 10 unlabeled ones. The membership failure that actually matters: **10 of 12 expected Tap3 misc pages have no labels at all** (plus 8 stale Tap3 intro/toc rows vs DB 0) and **Tap2's misc page `.001` is unlabeled** — those are “missing” rows, not `[]` rows, and a `[]`-row audit will not see them. (Flagged to the user in this revision; see Revision log.)

### 3.3 State `LABEL_EMPTY_OCR` flags vs reality — 808 flagged, 543 real, audit impossible via state

Querying `pages.review_flags` (mode=ro): **808** `LABEL_EMPTY_OCR` flags — Tap1 **269** (ch 127, misc 14, vi 128 — per-folder re-measured 2026-11-12; was 267 = ch 127 + vi 121 + intro 3 + toc 16), Tap2 **537** (ch 261, vi 264, intro 2, toc 10), SLQ **2** (misc `.001`, `.064`; was 0). Total was 804 → now 808.
Tap2's 537 are accurate (never OCR'd; Tap2 OCR never ran — see §3.5). Tap1: **266** flagged pages now contain boxes — invariant, re-verified on disk 2026-11-12 (of 269 flags: 266 back non-empty boxes, **3 flagged pages are genuinely empty** — misc `.001`, `.009`, `.145` — the `.009` empty page used to be counted as the 1 flagged empty under `toc`). **1 unflagged empty page remains** (vi `.083` — its OCR was all page-marker noise, cleaned to nothing, so no `LABEL_EMPTY_OCR` was ever raised; flags there are `PAGE_MARK_REMOVED` only). SLQ's 2 flags are accurate (both `[]` rows). Reconciliation: 808 = 266 flagged-with-boxes (Tap1) + 542 flagged-empty (Tap1 3 + Tap2 537 + SLQ 2); 542 + 1 unflagged = **543** = on-disk empty rows (§3.2). Nothing clears flags — they are stale forever (as before).

### 3.4 Stale submission

`submission/` currently holds a **different, partial book set** (`T1_Sửa Lưỡi Quyển`: 18 ch + 19 vi rows, all fileState≡1; `T1_Thánh Giáo Giám Lược (Tập 1)`: 18+18 rows) — not derived from the 3 configured books and not built from the current pipeline. Out of area D scope, flagged loudly. (Its folders do pass fileState≡1, but names and coverage mismatch `configs/project.yaml`.) Untracked, unchanged by the change-set (2026-11-12).

### 3.5 OCR progress driving the labels picture

`state.sqlite3.pages.status/engine` (re-verified 2026-11-12, mode=ro): Tap1 `ocr_done` 274/282 (8 `classified` = 6 blank + 2 NULL-engine misc) — ch: kimhannom ×130; **vi 130 + misc 14: vintern ×144** (2 misc pages engine NULL: `.001` COVER_PAGE, `.009` TOC_LIKELY_FRONT — never OCR'd; the third empty misc `.145` is vintern). SLQ `ocr_done` 110/118 (8 `classified` = 6 blank + 2 NULL-engine misc) — kimhannom ×50, **vintern ×60** (vi 50 + misc 10: `002,003,005,007,008,009,062,063,117,118` — exactly the 10 re-binned misc pages whose labels were never written; misc `.001`/`.064` are engine NULL, never OCR'd). **Tap2 `ocr_done` 6/550** (3 kimhannom + 3 vintern; 544 `classified`, engine NULL — misc page `.001` among them, unlabeled). All 550 recorded API calls report `http_200`; weekly quota used (`api_calls` = 550) — Tap2 Nôm (264 ch pages) cannot be completed from the remaining weekly budget (**219 left, W46 window** — corrected 2026-11-12; this report previously said “50 left”, which is outdated) and needs Vintern or a quota reset. `data/clean/<book>` has exactly 390 files == 390 OCR'd pages ✓ (clean not re-run by the change-set; unchanged).

### 3.6 Guideline § "Quy định chung về file OCR" conformance summary

`<folder>/<image>` + TAB + JSON (4-point boxes) + `{folder}/{name}\t1` in fileState + row per image + 1 box per page for tools without line boxes — **formally** satisfied everywhere; `〓`/cleaned-transcription obligations — **not satisfied** (see §4); annotation completeness — **not satisfied for Tap2** (see §3.2) **and not satisfied for Tap3 misc** (10 of 12 expected misc pages have no labels; `.062`/`.063` glossary pair labeled NOWHERE; stale intro/toc rows vs DB 0; Tap2 misc `.001` unlabeled) — see §3.1/§3.2; right→left column order for Nôm — satisfied (0 violations, re-verified 2026-11-12).

---

## 4. Clean — the 〓 no-op (highest-impact clean defect) and frozen flags

> Clean-side (§4) findings are **unchanged** — the 2026-11-12 change-set did not modify `clean.py`; all line cites below remain valid and the counts (765 PUA, 128 dropped_lines, 104 PAGE_MARK_REMOVED drops, 17 FOOTER_TITLE_REMOVED, etc.) were not re-scanned except where explicitly noted. (Revised 2026-11-12.)

### 4.1 `clean_nom_lines` discards the sanitizer result (critical)

`clean.py:322` — the function:
```python
text = "".join(normalized)                          # clean.py:358
text, replacements, sanitize_flags = sanitize_nom_text(text)   # clean.py:359 — result only used for the dead MASK check below
if MASK in text and len(MASK) != MASK_LEN: ...      # clean.py:361 — dead branch (len('[MASK]')==6)
return normalized, dropped, replacements, sorted(set(flags))    # clean.py:363 — `normalized` is UNSANITIZED
```
`clean_nom_page` (clean.py:382) then sets `text="".join(normalized)`. Net effect: **nothing is ever replaced**; only counted.

Empirical consequences (verified by scanning all 390 clean files + labels):
- **765 Plane-15 PUA codepoints survive** in `text`/`lines` — 167 pages flag `NOM_UNENCODABLE_REPLACED` (Tap1 125, SLQ 39, Tap2 3). Codepoints U+F000B…U+F12D3 (Kim Hán Nôm font PUA; most frequent U+F047C), **23 distinct**.
- Label.txt ch transcriptions carry the **same 765** (Tap1 **674**, Tap2 **14**, SLQ **77**).
- Sum of declared `replacements` dicts = **765** — the accounting is honest; the substitution was never performed.
- **0 occurrences of U+3013 (〓) anywhere** in clean outputs or Label.txt (`total U+3013 characters in clean outputs + Label.txt: 0`).
- 0 Cf (e.g. ZWJ U+200D) and 0 Cc survive in any output — but only because none were emitted by these engines this run; `is_safe_codepoint` (clean.py:110-117) would replace any Cf silently.
- `validate_clean_text` (clean.py:477) exists but is **dead code** — never called anywhere; it doesn't even check Co/Cn/Cf membership, so it would not have caught this.

(765 remains valid post-rebin: Clean not re-run; `clean.py` untouched; Tap1 ch labels byte-identical — 674 stands; Tap3 ch/vi rebuilt deterministically from unchanged OCR, box counts identical (453/50). Revised 2026-11-12 notes only.)

### 4.2 `_FULLPAGE_LEADING_MARK` backtracking bug (high; latent, 0 live hits)

`clean.py:186-188`:
```python
_FULLPAGE_LEADING_MARK = re.compile(
    r"^\s*-?\s*\d{1,4}\s*[-–—]?\s*\(?\s*\d{2,4}\s*\)?(?:[.\-–—]\s*)?")
```
The **required** `\d{2,4}` lets `\d{1,4}` backtrack and split a bare 4-digit year at line start. Verified synthetic matches:
- `'1802, vua Gia Long lên ngôi'` → match `'1802'` → remainder `', vua Gia Long lên ngôi'`
- `'1802 Gia Long lên ngôi'` → match `'1802 '` → remainder `'Gia Long lên ngôi'`
- `'1913 Lời mở đầu'` → match `'1913 '` → remainder `'Lời mở đầu'`
- `'1975 30 tháng 4 giải phóng'` → match `'1975 30 '` → remainder `'tháng 4 giải phóng'`
- `'15 20 25 là các số'` → match `'15 20 '`

**Real-data audit (should be re-run after any OCR refresh)**: all **104** `PAGE_MARK_REMOVED` drops (Tap1 70, SLQ 34) were cross-checked against raw first lines (`_FULLPAGE_LEADING_MARK.match(raw_first_line)`). Every recorded drop starts with `-` (e.g. `-11 - (274)`, `-14\n(271)`, `-276 -`); remainders: 103/104 start with a letter (content), 1 empty (Tap1 `0083`, marker-only page); **0** cleaned texts start with `,` or a digit; **0 pages were over-tripped in the current corpus**. The bug is real but latent; it will not produce visible `,`/digit-led tails — over-trips would leave `'Lời mở đầu'`-style remainders that no downstream check can detect. Note the regex also spans newlines (`\s`), so multi-line markers `'-14\n(271)'` get stripped as one match (by design; the recorded drop then contains an embedded `\n` — cosmetic).

### 4.3 `_strip_trailing_title` false-positive risk (medium)

`clean.py:210-226` strips any line ending in the flat letters of `sua luoi` / `sua luoi quyen`, trimming the exact suffix span. Verified: `'hãy sửa lưới'` →`'hãy'` (removes 6 chars of legitimate body). The **17** `FOOTER_TITLE_REMOVED` drops (all SLQ) look like true footers in context (e.g. `-15-` body ending `…Sửa Lưới` after page punctuation) and are preserved in `dropped_lines` — nothing is silently lost — but at least `T1_SuaLoiQuyen 0048`/`0051` drop `sửa lưỡi`/`Sửa Lưỡi` inside Vintern-truncated output where body vs footer is indistinguishable (the book's theme is literally "sửa lưỡi"—repairing the tongue). Also runs **after** the margin noise check, so: `SLQ 0003.json` input `'-1\nSỬA LƯỚI QUYỀN'` → footer strip leaves `'-1'` → final `text='-1'`, one bare page-number line survives into the deliverable.

### 4.4 `_join_hyphenated_lines` (medium)

`clean.py:229-256`. The line-break artifact branch does `prev[:-1] + line` (clean.py:251) — **joins without any space**. The guideline explicitly says "Các dòng được nối bằng một khoảng trắng" and its example joins `tin-\ntưởng` → `tin tưởng`. Only the keep-hyphen branch (`A-`+`ve`→`A-ve`, proper names) is space-free legitimately. Keep rule (clean.py:245-247) `re.fullmatch(r"[A-Z]", prior) or (any isupper(prior) and line[:1].islower())` over-keeps: `'Nam-'`+`'Việt'` → `'Nam-Việt'` regardless of context. Third branch (prior all-lower, next line starts uppercase) falls through to `prev + " " + line` → `'tint- Việt'` (hyphen kept AND space). No flag/count records joins — unauditable. Live data: 0 lines end with `-` after joining (all join decisions invisible).

**U+FF0C (，) in split/terminal marks (latent, 0 occurrences)**: `src/hannom/align.py:116` `_split_long_text` prefers `(" ", ";", ",", "\u3001", "\uFF1B")` as break marks — no U+FF0C (`，`), and no `\u3002`/`\uFF01`/`\uFF1F`/`\uFF1A`; `NOM_TERMINAL_RE` (align.py:33) and `TERMINAL_NOM` (clean.py:47) split sentences on `。！？；：` only; `NOM_PUNCT_MAP` (clean.py:38) maps only ASCII `';' ',' ':' '!' '?' '.'` → fullwidth. Empirical counts: **U+FF0C = 0 in raw OCR AND 0 in cleaned Nom text** (and U+3001/U+3002 etc. also 0 — Kim Hán Nôm output carries no punctuation at all), so today this is a **consistency/latent gap, not corruption**: a future engine emitting `，` would (a) pass `is_safe_codepoint` (Po category — kept), (b) not be mapped by `NOM_PUNCT_MAP` (ASCII-only), (c) not split sentences (correct — comma isn't terminal) but also **could not be used by `_split_long_text` as a break mark**, forcing mid-word hard cuts at `max_chars` (80) even when a natural `，` boundary exists, and (d) bypass `normalize_nom_punctuation`'s intent of unified fullwidth punctuation. Recommended (low priority): add `\uFF0C` and the missing fullwidth marks to `_split_long_text`'s mark tuple; map `，`→`、` in `NOM_PUNCT_MAP`; decide whether `NOM_TERMINAL_RE` should ever include `，` (it must **not** — it is not a sentence terminator).

### 4.5 `detect_running_lines` is inert (high wrt residual noise)

`clean.py:295-319`. Edge-only window (first/last 2 lines per page), `min_pages=5`, `max_ratio=0.35`, `max_length=80`. Empirical: re-running it on **raw** lines (all files per book) and on **cleaned** lines returns an **empty set in all 3 books**; `data/clean/<book>/summary.json` reports `running_lines: {ch: 0, vi: 0}` for Tap1, Tap2, SLQ. Root cause: Vintern output is a single giant page line per page → it never repeats across pages; Kim Hán Nôm output is column-sized Nôm — margin candidates never reach the 35% bar (Nôm pages rarely share identical margin strings). Consequently **no running header/footer was removed by this machinery anywhere**: residue confirmed e.g. SLQ `0005.json` final text verbatim `'-3 SỬA LUỘI QUYỂN 2065 Lưu Hành Nội Bộ 09 - 2008'`; SLQ `0117`/`0118` keep `SỬA LƯỚI…` TOC lines; Tap1 `CẤM PHÒNG` occurs in 32 cleaned qn texts (body usage — not auto-removable). Only the 104 leading marks + 17 title-footers + 4 unflagged full-line page-numbers were ever stripped.

### 4.6 Misc clean facts (empirical)

- Total `dropped_lines`: **128** entries (~1,350 bytes); classified: 101 fullpage-leading-mark, 12 title-footer, 6 duplicates (`DUPLICATE_LINES_REMOVED`), 4 full-line page-numbers (**unflagged** — `is_page_number_line` path emits no flag), 5 footer drops counted under title (trailing_title_footer/'Sửa Lưỡi' under `FOOTER_TITLE_REMOVED`). Losses are small and fully recoverable; `dropped_lines` preserved everywhere.
- NFC: 0 non-NFC files. Nom whitespace: 0 occurrences. Control chars: 0 survive (`remove_control` applied at input). QN: 0 double spaces, 0 curly quotes, 0 `–—`, 0 NBSP residuals; punctuation normalized correctly.
- `normalize_mask` — dead code; `MASK` invariant branch (`clean.py:361`) — dead branch.
- `DUPLICATE_LINES_REMOVED`: 6 (all Tap1). `INLINE_REF_REMOVED`: 0. `MASK_LENGTH_INVALID`: 0.
- Also empty `text=''` with only `PAGE_MARK_REMOVED`: 1 page (Tap1 `0083`, marker-only) — no unambiguous `EMPTY_AFTER_CLEAN` signal.

---

## 5. Findings, severity-ranked (with file:line)

| # | Severity | Finding | Location |
|---|---|---|---|
| C1 | Critical | Tap2 ships 537 empty boxes with `fileState≡1`; OCR never ran; any submission packages it as a "complete" empty book. (2026-11-12: `stage_labels` folder tuple ~line 169 now also emits `misc` — Tap2 still has no misc folder; net-0 lines, cites valid.) | `orchestrator.py:169-218`; data `data/labels/T1_CamPhong_Tap2/*` |
| C2 | Critical | Nôm sanitizer output discarded — 765 PUA codepoints survive unreplaced; §4.1 | `clean.py:359-363`, `clean.py:382` |
| C3 | Critical | `validate_clean_text` dead code; nothing blocks packaging on bad text; Tap1 stale `LABEL_EMPTY_OCR` (266 of **269** flags now back boxes) (revised 2026-11-12) | `clean.py:477-496`; `orchestrator.py:213-217` |
| H1 | High | `_FULLPAGE_LEADING_MARK` backtracking over-trips bare 4-digit years (latent; audit shows 0 live hits across 104 drops) | `clean.py:186-207` |
| H2 | High | `LABEL_EMPTY_OCR` accounting unusable; Tap1 flags **269** vs **3** flagged empties (misc `.001/.009/.145`) + 1 unflagged empty (vi `.083`); nothing clears flags (revised 2026-11-12) | `orchestrator.py:213-217`, `orchestrator.py:265-267` |
| H3 | High | `detect_running_lines` inert (0 detected everywhere); running headers/colophons survive (SLQ `0005` etc.) | `clean.py:295-319` |
| M1 | Medium | `_strip_trailing_title` can delete legitimate body endings (`'hãy sửa lưới'`→`'hãy'`; book's theme words) | `clean.py:210-226` |
| M2 | Medium | `_join_hyphenated_lines` artifact join lacks a space (guideline: join with one space); over-broad keep-hyphen rule; third-branch "hyphen+space" nonsense; no join counter/flag | `clean.py:229-256` |
| M3 | Medium | Cleaning order: page-number check runs before footer-strip → bare `'-1'` survives (`SLQ 0003`); mask invariant dead; Cf silently eaten; `normalize_mask` dead; 4 full-line page-number drops unflagged | `clean_quoc_ngu_lines` `clean.py:390-435`; `clean.py:138-142,110-117` |
| M4 | Medium | Labels carry raw PUA in transcriptions; `confidence` extra field without documentation (guideline: extra fields need explanation; `difficult` is exempt as the OCR tool's own field) | `data/labels/*/*/Label.txt` |
| M5 | Low | `clamp_quad` caps points at `width-1`/`height-1` (799×1134) while validator accepts ≤width; points_to_quad collapses >4-point polygons to bbox | `labels.py:72-80,63-68` |
| M6 | Low | `_split_long_text` preferred marks miss U+FF0C and other fullwidth marks (`align.py:116`; was `align.py:105`); `NOM_PUNCT_MAP` ASCII-only (0 live occurrences); ~~stray `T1_SuaLoiQuyen/image_map.json` confusing submission tooling~~ — **RESOLVED 2026-11-12**: the change-set's image_map repair removed it; no `image_map.json` exists anywhere in the repo (re-verified 2026-11-12) | `align.py:116`; `clean.py:38-45` |
| M7 | Low | `stage_labels` swallows all exceptions in the running-lines block (`except Exception: running = {}`) — silent disablement (net-0 lines; cite valid) | `orchestrator.py:163-164` |
| M8 | Low | Stale `submission/` (different books, fileState≡1, partial) — packaging risk outside D | `submission/` |
| M9 | Low–Medium | **NEW (2026-11-12 change-set)** — Tap3 `T1_SuaLoiQuyen` labels are **desynchronized from the DB**: misc labels 2/12 (10 re-binned misc pages unlabeled; `.062`/`.063` glossary pair labeled NOWHERE); stale intro/toc label files (4+4 rows vs DB 0); Tap2's DB misc page `.001` unlabeled. Any label consumer (packaging gate, audits) silently sees a partial book. Detectable only by a **misc-aware** membership audit (ch/vi/intro/toc/misc) | `data/labels/T1_SuaLoiQuyen/*`; `state.sqlite3` (folder column) |

**Assets correct and ready (keep)**: LF/UTF-8/BOM-free files, exactly-4-point boxes, no newlines, `folder/` prefix, fileState key-set equality, 4-point bounds, ch right→left order (444/444, re-verified 2026-11-12), QN whole-page fallback boxes (all ≥85% coverage), NFC enforced, QN punctuation normalized, Nôm whitespace removed, all drops recoverable, **282 tests green** (was 291; revised 2026-11-12), strict validator wired into packaging gate (`package.py:417-424`).

---

## 6. Fix list (ordered)

1. **Apply the sanitizer result in `clean_nom_lines`** — sanitize each line (or `normalized`) before return; re-run `hannom clean` **and** `hannom labels` for the three books; verify: 0 PUA/Co codepoints in `data/clean/**` and in all `Label.txt`, and `U+3013` count > 0 (**765 expected** — still valid post-rebin, see §4.1). Note: Tap3 needs its label rebuild to land **after** any DB resync (see §8/M9) — the 19:35 build was overtaken by the ~19:43 DB re-bin.
2. **Wire `validate_clean_text`** into `stage_clean` per page (cheap) and extend it to reject Nom unsafe membership (`category in {Co,Cf,Cs,Cn}` unless char ∈ {〓, MASK}); fail/flag on violation. Also fix the dead `MASK_LEN` invariant branch.
3. **Clear flags on success in `stage_labels`** — on successful regeneration, `state.update_page(...)` must remove stale `LABEL_EMPTY_OCR` (rebuild flags rather than merge-only); add `EMPTY_AFTER_CLEAN`/`OCR_MISSING` vs `OCR_ALL_NOISE` distinction; fail packaging (`package.py` gate) when any page lacks boxes unless `--allow-empty-labels` is passed. Everything above also needs re-running after Tap2 OCR exists — and **after Tap3's DB/labels resync** (see §8); unflagged empties (currently 1: Tap1 vi `.083`) must become impossible.
4. **Fix `_FULLPAGE_LEADING_MARK`** — anchor with a leading `-` (all 104 real drops conform) or atomic-group `\d{1,4}` so it cannot backtrack into the second group, e.g. `^\s*-\s*\d{1,4}(?:\s*[-–—])?(?:\s*\(\s*\d{2,4}\s*\))?`. Add regression tests: `'1802, vua Gia Long lên ngôi'`, `'1913 Lời mở đầu'`, `'1975 30 tháng 4 giải phóng'` must **not** match. Re-audit the 104 pages after any OCR refresh (expect no change today).
5. **`_strip_trailing_title`** — require following punctuation (`[.:!?…;)]` or end-of-line/start) or a capitalized standalone title suffix; otherwise downgrade to `FOOTER_TITLE_SUSPECT` (flag, do **not** drop). Human-review the 17 current drops (all in `dropped_lines`).
6. **`_join_hyphenated_lines`** — artifact join becomes `prev[:-1] + " " + line`; drop the `any isupper(prior)` half of the keep-hyphen rule; add `HYPHEN_JOINED` flag/counter; unit tests for all three branches.
7. **Clamp to `width`/`height`** (not `width-1`/`height-1`) in `clamp_quad`.
8. **One-pass clean-quoc-ngu** — after `_strip_trailing_title`, re-apply `is_page_number_line` (or loop stripping until stable); add `EMPTY_AFTER_CLEAN` flag when text becomes empty; add a flag for page-number full-line drops in the Nom path.
9. **Running lines** — for Vintern giant pages, split the page line on `\n` and apply the same ≥35% marginal rule per line; or replace `detect_running_lines` with per-book title/colophon detection emitting `RUNNING_LINE_REMOVED` (keeps current data quiet, catches future runs).
10. **Re-check the filename rule** — after any regeneration, verify every Label.txt/fileState row equals `<folder>/<book_name>.<NNN>.jpg` with `bad_prefix == 0` and contiguous numbering; `data/pages` currently conforms (282/550/118; prefix rule 0/950 violations); ~~remove stray `data/labels/T1_SuaLoiQuyen/image_map.json` or document it~~ — **DONE 2026-11-12** (image_map repair; `image_map.json` no longer exists anywhere — verified); consider stripping `confidence` from boxes (or documenting it); keep `difficult` (allowed from the OCR tool).
11. **Tap2** — the blocker. Run Vintern for the 267 vi pages locally; Nôm ch pages (264) need quota (600/week, 550 used, **219 left in the W46 window** — corrected 2026-11-12; was “50 left”) or a new window or paddleocr_vl as fallback; then re-run labels+clean and the audit in §8. Also flag the stale `submission/` to the packaging owner.

---

## 7. Reproduction commands (all read-only)

Run from `C:\Users\MSI VN\Desktop\NLP`. Encoding: prefix `python -X utf8 -c …` (PowerShell console is cp1252); or `$env:PYTHONIOENCODING='utf-8'`.

```python
# (a) validate_label_txt per existing folder (0 issues expected — form only; NOT membership)
python -X utf8 -c "
import sys; sys.path.insert(0,'src')
from hannom.labels import validate_label_txt
from pathlib import Path
for book in ['T1_CamPhong_Tap1','T1_CamPhong_Tap2','T1_SuaLoiQuyen']:
    for folder in ['ch','vi','intro','toc','misc']:
        lbl = Path('data/labels')/book/folder/'Label.txt'
        if not lbl.exists():
            print(book, folder, 'ABSENT (skipped)'); continue
        res = validate_label_txt(lbl, Path('data/pages')/book/'native', folder,
                                 lbl.with_name('fileState.txt'),
                                 require_all_images=False, strict_points=True)
        print(book, folder, 'issues', len(res.issues), 'boxes', res.box_count, 'lines', res.image_count)
"
# (b) fileState≡1 + LF/no-BOM + row/box/empty counts (misc-aware)
python -X utf8 -c "
import json, pathlib
tot_rows = tot_boxes = tot_empty = 0
for book in ['T1_CamPhong_Tap1','T1_CamPhong_Tap2','T1_SuaLoiQuyen']:
    for folder in ['ch','vi','intro','toc','misc']:
        lp = pathlib.Path('data/labels')/book/folder/'Label.txt'
        if not lp.exists():
            continue
        raw = lp.read_bytes()
        n = empty = boxes = 0
        for line in lp.read_text(encoding='utf-8').splitlines():
            if line.strip():
                n += 1
                b = json.loads(line.split('\t',1)[1]); boxes += len(b); empty += (len(b)==0)
        fs = (lp.with_name('fileState.txt')).read_bytes()
        tot_rows += n; tot_boxes += boxes; tot_empty += empty
        print(book, folder, 'rows', n, 'boxes', boxes, 'empty_rows', empty,
              'fileState_rows', fs.count(b'\n'), 'crlf', raw.count(b'\r\n'), 'bom', raw.startswith(b'\xef\xbb\xbf'))
print('TOTAL rows', tot_rows, 'boxes', tot_boxes, 'empty_rows', tot_empty)
"
# (c) Nôm reading-order check (vertical-box x-centers non-increasing)
python -X utf8 -c "
import json, pathlib
for book in ['T1_CamPhong_Tap1','T1_CamPhong_Tap2','T1_SuaLoiQuyen']:
    bad = tot = 0
    for line in (pathlib.Path('data/labels')/book/'ch'/'Label.txt').read_text(encoding='utf-8').splitlines():
        boxes = json.loads(line.split('\t',1)[1]); tot += 1
        xs = []
        for b in boxes:
            pts = b['points']; xs = xs
            w = max(p[0] for p in pts)-min(p[0] for p in pts)
            h = max(p[1] for p in pts)-min(p[1] for p in pts)
            if h > 1.25*w: xs.append((min(p[0] for p in pts)+max(p[0] for p in pts))/2)
        if xs != sorted(xs, reverse=True): bad += 1
    print(book, 'ch order violations', bad, '/', tot)
"
# (d) regex test strings (pre-fix vs post-fix)
python -X utf8 -c "
import sys; sys.path.insert(0,'src')
from hannom.clean import _FULLPAGE_LEADING_MARK
cases = ['-11 - (274) CẤM PHÒNG','- 12 - (273)','-10 ( 113 )','-276 -',
         '1802, vua Gia Long lên ngôi','1802 Gia Long lên ngôi',
         '1913 Lời mở đầu','1975 30 tháng 4 giải phóng','15 20 25 là các số']
for c in cases:
    m = _FULLPAGE_LEADING_MARK.match(c)
    print(repr(c), '->', repr(m.group(0)) if m else None)
"
# (e) how many PUA survive
python -X utf8 -c "
import json, pathlib, unicodedata
bad = {}
for p in pathlib.Path('data/clean').rglob('*.json'):
    if p.name=='summary.json': continue
    t = json.loads(p.read_text(encoding='utf-8')).get('text','')
    for ch in t:
        if unicodedata.category(ch) in {'Co','Cn','Cs'}:
            bad[ch] = bad.get(ch,0)+1
print('PUA chars surviving:', sum(bad.values()), 'distinct:', len(bad))
"
```

**Caveat for running this today (revised 2026-11-12)**: the loops above now include `misc` and tolerate ABSENT folders (Tap1 intro/toc and Tap2 misc no longer exist; before the re-bin, plain `['ch','vi','intro','toc']` loops *silently excluded* misc). Re-running (a)/(b) re-derives the **current** state — **0 issues on all 12 existing folders, 929 rows, 2,487 boxes, 543 empty rows, fileState 929 × `\t1`** — but the membership check must be run separately and is **not** re-derivable from Label.txt alone: it needs `state.sqlite3` (mode=ro) `pages.folder` per book/folder and **must include misc**. On-disk vs DB today: Tap1 full match (276/276; intro/toc absent both sides), Tap2 543/544 (misc `.001` unlabeled), **Tap3 fails** (misc 2 vs DB 12 — `.062`/`.063` unlabeled everywhere; stale intro 4 + stale toc 4 vs DB intro/toc = 0). The old pre-rebin loops (`['ch','vi','intro','toc']`) would report Tap3 as "consistent" and miss all of this.

Scratch probes (already written, re-runnable): `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-D\probe_{labels,labels2,clean1,clean2,clean3,split,regex,marks,marks2,marks3,verify_marks,final,dropped,running}.py` and outputs `clean2.txt`, `clean3.txt`, `marks.txt`, `dropped.txt`. Revision re-measurements: `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-D\probe1.py`–`probe5.py` (validator re-run, mtimes/git status, DB membership/flags/engines, full-page coverage, ch reading order, on-disk recount).

---

## 8. Handoff checklist

- [ ] Tap2 OCR exists (Vintern vi ×267; ch ×264 after quota/window) and `hannom ocr`/`hannom clean`/`hannom labels` re-run for Tap2 only.
- [ ] **Tap3 `T1_SuaLoiQuyen` labels resync (NEWLY OPENED 2026-11-12)** — the headline item of this revision: rebuild labels from the **re-binned** DB. `misc/Label.txt` must hold **12 rows** (`001,002,003,005,007,008,009,062,063,064,117,118`); `.062`/`.063` (CHÚ THÍCH glossary pair) are currently labeled **NOWHERE**; the 10 vintern-engine re-binned misc pages have no label rows; **delete stale** `intro/Label.txt`+`fileState.txt` (`002,003,005,009`, 4 rows/4 boxes) and `toc/Label.txt`+`fileState.txt` (`007,008,117,118`, mtimes 2026-11-12T13:24) — **DB intro/toc = 0**; verify `fileState≡1` with LF afterwards. Cause: labels built 19:35:42, DB re-bin landed ~19:43 (backup `state.sqlite3.bak-2026-11-12-rebin-fix`). `decisions.md`'s "Tap3 labels refreshed including misc" is only loosely true (refreshed ≠ complete). **Tap1 labels (19:36:49) are post-fix and DB-consistent ✓** — do not disturb; diff Tap1 against pre-rebin only if auditing.
- [ ] Nôm PUA audit clean: 0 `Co/Cn/Cs` chars in `data/clean/**` and in all `Label.txt`; `U+3013` count ≥ 765 (or reported difference explained); `NOM_UNENCODABLE_REPLACED` pages now actually show `〓`.
- [ ] `label rows == state folder membership` per book/folder with a **misc-aware** audit (`ch/vi/intro/toc/misc`) — **currently FAILS** for Tap3 (misc 2 vs DB 12; stale intro/toc 4+4 vs 0) and Tap2 (misc `.001` unlabeled); **passes** for Tap1 (276/276; intro/toc absent both sides). Audit `[]` rows misc-aware too (Tap1 misc `.001/.009/.145`, vi `.083`; Tap2 ch 261/vi 264/intro 2/toc 10; SLQ misc `.001`/`.064` → **543 on disk**); empty/misc handling is allowed (misc labels are intro/toc-like apparatus — fine as long as fileState≡1 and Label.txt exists); only `missing/` may never carry labels. Else block packaging.
- [ ] `validate_label_txt` = 0 issues on all existing folders (holds today) **and** membership check passes (fails today, Tap3/Tap2 — see above); `validate_clean_text` wired and passing.
- [ ] Regex fix + tests pass (`'1802…'`, `'1913 …'`, `'1975 30 …'` no longer match).
- [ ] Footer-strip gate reviewed against the 17 drops; `FOOTER_TITLE_SUSPECT` downgrade path exercised; `SLQ 0003` no longer emits `'-1'`.
- [ ] `LABEL_EMPTY_OCR` flags re-generated truthfully (stale cleared); state audit == Label.txt reality; unflagged empty pages impossible (currently 1: Tap1 vi `.083`).
- [ ] `_join_hyphenated_lines` new unit tests pass; joins counted (`HYPHEN_JOINED`).
- [ ] Running-lines implemented or formally removed; headers/colophons no longer leak (SLQ `0005`, Tap1 `CẤM PHÒNG` 32 pages triaged).
- [ ] Filename rule re-checked after regeneration: prefix `folder/<book_name>.<NNN>.jpg`, contiguous numbering, `bad_prefix == 0`; ~~no stray `image_map.json`~~ — **DONE 2026-11-12** (change-set image_map repair; absent repo-wide, verified).
- [ ] **Tap2 misc page `.001`** (in DB, folder=misc; engine NULL) — no label row exists and Tap2 has no `misc/` folder: re-run `hannom labels` for Tap2 as part of the Tap2 blocker fix, or emit a `misc/` `[]` row for `.001` explicitly; do not ship a misc folder silently dropped from submission.
- [ ] `stamp: git status` — currently **9 modified + 5 new source/tool files untracked** (`charstream.py`, `map_repair.py`, `tools/repair_image_map.py`, `test_charstream.py`, `test_map_repair.py`) + 9 `Doc/verify-*.md` docs + `submission/`; **ZERO new commits; branch `feat/map-repair-align` @ `c3439e7`**. Review the change-set as the accepted 2026-11-12 state before any new edits; no `data/` or config edits outside a sanctioned pipeline run.
- [ ] `submission/` staleness raised to packaging owner (different book set, partial).

---

## 9. Caveats

- **Data volumes**: counts as re-measured **2026-11-12 (post map-repair)**; Tap1/Tap2/SLQ are not final books in scope (OCR refresh will shift everything; re-run §7 — misc-aware — after any pipeline run). Tap1 = rebuilt & DB-consistent; Tap3 = stale/desynced (§3.1/M9); Tap2 = untouched 2026-11-08 data.
- **fState≡1 is not proof of annotation** — 537 Tap2 rows are empty transcriptions marked done (plus Tap2 misc `.001` has NO row at all). Never audit completion via `fileState.txt`; audit `[]` rows in Label.txt — and never audit membership with a ch/vi-only loop (miss misc) nor with Label.txt alone (miss stale rows vs DB).
- **State flags are not signals** — merged, never cleared (`orchestrator.py:216-217,265-267`; net-0 lines, cites valid); treat `LABEL_EMPTY_OCR` as historical junk until fix #3 lands and a fresh run regenerates flags. Current totals (2026-11-12): **808** (Tap1 269, Tap2 537, SLQ 2); Tap1 non-empty flagged invariant **266** (re-verified on disk; 808 − 266 = 542 flagged-empty + 1 unflagged = 543 on-disk empty rows).
- **Δ between this verification and future runs**: `validate_label_txt` validating against `data/pages/<book>/native` passed because images keep source names; the actual submission tree (`submission/<book>/<folder>`) has different ledger semantics — this report did not validate the package, only the pipeline artifacts.
- **PUA vs 〓 judgment call**: treating Kim Hán Nôm "font PUA" codepoints (Plane 15) as unencodable-per-guideline is the intended policy (their own fonts render them; the reference Hán Nôm fonts do not); no alternative policy was found in the guideline. If the project decides these are *encodable in a specialized font*, the fix differs — but the guideline's literal wording ("not in any Hán Nôm font → 〓") matches unencodable-by-default.
- **Nôm label boxes clamp `[0…width-1]`**: PPOCRLabel and the validator tolerate it; change is cosmetic.
- **`submission/` is a different book set** ("Sửa Lưỡi Quyển" + "Thánh Giáo Giám Lược (Tập 1)") — everything about it is out-of-date and out of scope; do not build on it without reconciling against `configs/project.yaml`.
- **Tap3/Tap2 label desync (new, 2026-11-12)**: any consumer of `data/labels/T1_SuaLoiQuyen/` sees a partial book (2/12 misc rows; 8 stale rows vs DB 0) and any consumer of Tap2 misses misc `.001`. fileState≡1 is uniformly true, so naive gates pass. Trust a misc-aware DB-membership audit, not fileState, not folder absence.
- **Non-root deliverables touched**: §3 counts are as of 2026-11-12 19:36–19:43; the DB was repaired after the label build — if the labels are ever rebuilt, §3.1/§3.2/§3.3 must be re-derived (§7, misc-aware) and this report updated.
- Tests (**282 passed**) cover labels/clean paths but none fail on the found defects (C1/C2/C3 un-gated by tests) — coverage of the failure modes is incomplete, which is precisely items #2/#3 and #7 in §6.
- **No live corruption today** from the H1 regex: 0 `,`- or digit-led cleaned texts, 104/104 drops start with `-`, every drop preserved in `dropped_lines`. The risk is prospective (future OCR refreshes), not retroactive.

---

## Revision log (2026-11-12, post map-repair change-set)

1. **Banner added** after title; date line now cites branch `feat/map-repair-align` @ `c3439e7`, **ZERO new commits**; tests **291 → 282** everywhere (§1 header, §5 keep-list, §9).
2. **Labels state bifurcated**, all §3 rewritten from read-only re-measurement (2026-11-12): on-disk rows **927 → 929**, boxes **2,489 → 2,487** (ch 2,284 unchanged; vi **178 → 182** = 129 Tap1 + 3 Tap2 + 50 SLQ; intro **8 → 4**; toc **19 → 4**; misc **+13 Tap1 / +0 Tap3**), non-empty rows **388 → 386**, **on-disk empty rows 539 → 543** (58.5%).
   - **Discrepancy flagged**: the change-set tally says “empties 555”. On-disk re-measure (two independent ways: per-folder recount = 929 − 386 = **543**; and flags: 808 − 266 flagged-with-boxes = 542 flagged-empty + 1 unflagged vi `.083` = **543**) gives 543; 555 appears to add **all 12** Tap3 DB-misc pages to 543 (double-counting the 2 labeled-empty rows) instead of the 10 unlabeled ones. The membership failure (10 unlabeled misc pages + 8 stale intro/toc rows vs DB 0) is the finding that matters; left visible in §3.2 instead of silently adopting 555.
3. **`stage_labels` folder tuple** now `("ch","vi","intro","ref","toc","misc")` (~orchestrator.py:169; single line gained `"misc"`; net 0 lines; line cites 163-171/213-217/265-267 remain valid). Labels are rebuilt deterministically from OCR on every run; no rebuild logic added — the behavior change is only the misc-bin emission.
4. **Tap1** (rebuilt 2026-11-12T19:36:49, post-fix): ch 130 rows / 1,793 boxes (**byte-identical** to pre-rebin), vi 130 rows (`.013`–`.142`; 1 empty `.083`), **misc 16 rows / 13 boxes / 3 empty `[]`** (`001,009,145`), rows == DB misc membership ✓, full-page-bbox pattern, fileState≡1; intro/toc folders **absent** on disk and in DB (re-bin moved the matter to vi/misc) — removed from the §3.2 table.
5. **Tap3 (T1_SuaLoiQuyen)** rebuilt 19:35:42 but **stale/incomplete vs DB** (re-bin applied to DB ~19:43, after the label build; DB backup `state.sqlite3.bak-2026-11-12-rebin-fix`): misc 2 rows (`001`,`064`, both `[]`) vs DB misc = 12 (`{001,002,003,005,007,008,009,062,063,064,117,118}`); **pages `062`/`063` (CHÚ THÍCH glossary pair) labeled NOWHERE**; the 10 vintern-engine re-binned misc pages have no labels; **stale `intro` (`002,003,005,009`) and `toc` (`007,008,117,118`) label files** (4+4 rows/boxes, mtimes 2026-11-12T13:24) vs **DB intro/toc = 0**; fileState≡1 everywhere including stale files. `decisions.md` “Tap3 labels refreshed including misc” is only loosely true (refreshed ≠ complete). Root cause and resync runbook recorded in §3.1 and §8.
6. **Tap2** untouched (2026-11-08): label rows 264 ch / 267 vi / 2 intro / 10 toc (537 empties); **DB misc page `.001` unlabeled** — no `misc/` folder (stage not re-run for Tap2); added to §8 checklist.
7. **Membership reconciliation fails now** — §2 method line, §3.1, §7 (caveat), §8 all updated to a **misc-aware** audit (`['ch','vi','intro','toc','misc']`); §7a/b repro commands updated (ABSENT-folder guard added) and annotated: re-running them today re-derives the current state (form-pass on 12 folders) but membership fails for Tap3/Tap2; `[]`-only audit misses the 10 unlabeled Tap3 misc pages and Tap2 misc `.001`.
8. **§3.3 retitled**: 804 → **808** flags (Tap1 **269** = ch 127 + misc 14 + vi 128 (was 267 = ch 127 + vi 121 + intro 3 + toc 16); Tap2 **537** ✓; SLQ **2** (misc `.001`/`.064`, was 0)); flagged-with-boxes invariant **266** (re-verified on disk); Tap1 real empties now **3** (misc `.001/.009/.145`, incl. former toc `.009`); unflagged empty vi `.083` unchanged.
9. **Guideline phrasing corrected**: misc labels are **allowed** (intro/toc-like apparatus for submitted data) as long as fileState≡1 and Label.txt exists; the hard guideline (Label.txt only for ch/vi or apparatus actually shipped; `missing/` may never carry labels) is unchanged. The old “blank and misc folders are correctly absent … as the guideline requires” claim is marked FALSE.
10. **Git/tests**: §2 git-status line and §8 stamp item replaced with the real state (9 modified + 5 new source/tool files untracked + 9 verify-*.md docs + `submission/`; branch `feat/map-repair-align`, HEAD `c3439e7`, ZERO new commits).
11. **§3.5** re-verified via DB (mode=ro): Tap1 vintern ×144 = vi 130 + misc 14 (2 misc engine-NULL = `.001`/`.009`); SLQ vintern ×60 = vi 50 + misc 10 (the 10 unlabeled), misc `.001`/`.064` engine NULL; Tap2 unchanged (6 `ocr_done`, 544 `classified` incl. misc `.001`). Weekly quota “50 left” → **219 left (W46 window)**.
12. **Fix list**: #1 annotated (Tap3 must rebuild labels after DB resync); #2 unchanged (765 expected — ch labels byte-identical / deterministic rebuild, Clean untouched); #3 annotated (Tap3 + unflagged-empties impossibility); **#10 image_map.json item marked DONE 2026-11-12** (no `image_map.json` exists repo-wide, verified); **#11 quota corrected to 219 (W46)**; flag counts 267→269 in C3/H2 rows; review_flags “267” → “269” where it denotes flags (Tap2’s 267 vi pages untouched).
13. **New finding M9** (Low–Medium): Tap3/Tap2 label–DB desync; detectable only via misc-aware membership audit.
14. **Line-cite fixes**: `align.py` `_split_long_text` 97 → **108**, break-mark tuple 105 → **116** (align.py gained lines before those symbols; `NOM_TERMINAL_RE` line 33 unchanged). `clean.py` untouched — all Clean cites valid. `orchestrator.py` net-0 lines (folder tuple ~line 169) — cites 163-171/213-217/265-267 valid with semantic change noted. `layout.py`/`textdiff.py`/`config.py` are **not cited by this report** — no cite changes required (insertions live in other verify files: layout.py +10/11 post-339/349, textdiff.py +1..15, config.py +5 post-44).
15. **§8 checklist**: Tap2 item kept; **new Tap3 resync item** added (12 misc rows; delete stale intro/toc vs DB 0; Tap1 must NOT be disturbed); new Tap2 misc `.001` item; filename-rule item image_map note marked DONE; git-status item replaced; membership item rewritten misc-aware with current FAIL/PASS status; empties rewritten (543; misc-allowed guidance).
16. **Clean §4 kept verbatim** apart from a header note and the `align.py:116` cite fix — `clean.py` untouched, 765 PUA / 128 dropped_lines / 104 PAGE_MARK_REMOVED / 17 FOOTER_TITLE_REMOVED unchanged.
17. **§9 caveats**: counts re-measured 2026-11-12; added Tap3/Tap2 desync caveat; `fileState≡1` caveat extended (uniformly true incl. stale files → membership must be checked misc-aware against DB); 291 → 282.

*Evidence appendix: `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-D\` (probes + outputs) and `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-D\` (this revision's re-measurement probes). Full long-form narrative also at `REPORT.md` there — this document is the handoff version.*

---

## Addendum 2026-11-13 (fixes implemented and re-verified)

All fixes from §6 (fix list) landed on 2026-11-13, with the replication's additions. No Tap2 decision was taken (OCR untouched). Tests: **333 passed**. Backups: `data/archive/verify-D-fix-backup-2026-11-13T185732/` (DB + labels + clean snapshot).

**Landed:**
1. **C2** — `clean_nom_lines` now applies the sanitizer (per-line, merged counts); `text == join(lines)` re-verified; `U+3013` count = **765** in clean outputs and **765** in Label.txt; Co/Cn/Cs = **0** everywhere.
2. **C3** — `validate_clean_text` extended to reject all `Co/Cf/Cs/Cc/Cn` code points (except 〓/`[MASK]` chars), now called from `stage_clean` (violations → `CLEAN_TEXT_INVALID`); dead `MASK_LEN` branch replaced with a live bracketed-token check; current corpus: **0** `CLEAN_TEXT_INVALID`.
3. **H2** — `stage_labels` reconciles flags truthfully on every regeneration (stale `LABEL_EMPTY_OCR` removed from pages that carry boxes; OCR-exists-but-silent pages get `OCR_ALL_NOISE`; nothing unflagged): Tap1 `LABEL_EMPTY_OCR` 269 → **2** (never-OCR'd NULL-engine `.001`/`.009`); `OCR_ALL_NOISE` = Tap1 2 (`.083`, `.145`), SLQ 2 (`.002`, `.003`); every on-disk empty row (545) is now flagged.
4. **H1** — `_FULLPAGE_LEADING_MARK` rewritten: mandatory leading `-`, terminator required (`-N -`, `-N
(P` or `-N (P)`); bare years cannot split (`'1802…'`, `'1913 …'`, `'1975 30 …'`, `'15 20 25 …'`); synthetic suite added; all recorded corpus drops still match (110/110).
5. **M1** — `_strip_trailing_title` now returns a disposition: `removed` (title-only or remainder ending in sentence/dash punctuation) → `FOOTER_TITLE_REMOVED`; ambiguous body-ish remainders → kept + `FOOTER_TITLE_SUSPECT` (SLQ `0048`/`0051`-class are now kept and flagged).
6. **M2** — `_join_hyphenated_lines`: artifact joins are `prev-… + " " + rest` (guideline: one space); keep-hyphen rule reduced to `[A-Z]` prior token; hyphen+space third branch removed; `HYPHEN_JOINED` flag emitted.
7. **M5** — `clamp_quad` caps at `width`/`height` (not `width-1`); QN whole-page coverage ≈ 1.000 on 800×1135 pages possible again (previous min 0.9979).
8. **M3** — QN path loops a final page-number drop pass after footer stripping; `EMPTY_AFTER_CLEAN` emitted when text becomes empty (Tap1 `0083`/`0009`, SLQ `0003`); Nôm margin-noise page-number drops are now flagged `PAGE_NUMBER_REMOVED` (was unflagged).
9. **H3** (partial) — Vintern giant pages are split on embedded newlines at input, so the existing marginal rule actually works on QN pages at all (marker-only apparatus pages now clean to empty correctly instead of silently keeping junk). `detect_running_lines` output is still 0 everywhere (no false removals); the bare `except Exception: running = {}` in `stage_labels` now logs the exception instead of swallowing it. `stage_clean` also skips nothing relevant anymore (`misc` included).
   **Caveat:** misc pages (colophon/TOC/glossary) that were stale now regenerate; 0003-class residue (e.g. the `Lưu Hành Nội Bộ` colophon fragment in SLQ `0005`) survives as content and is flagged — auto-removal still needs human review.
10. **M4** — documented in `USER_GUIDE.md` §8: `difficult` = the OCR tool's own field; `confidence` = passthrough from the Kim Hán Nôm API line payload (not an annotation-quality filter).
    **M6** — `_split_long_text` now prefers fullwidth `，` (U+FF0C) too; `NOM_PUNCT_MAP` maps `，→、`; `NOM_TERMINAL_RE` unchanged (correct — `，` never ends a sentence). Stray `data/labels/T1_SuaLoiQuyen/image_map.json` moved to `data/archive/.../stray_labels_T1_SuaLoiQuyen_image_map.json`.
11. **Stale-file pruning** — `stage_labels` now prunes folders whose bin has no pages in the DB (SLQ stale `intro/`/`toc/` removed; Tap1/Tap2 consistent 15/15 on the misc-aware membership audit). The pruning is deletion-to-zero-page-scope only; no other deletion.
12. **Packaging** — `validate_book_package` + `EMPTY_LABELS` blocker (any `ch/`/`vi/` Label.txt row with zero boxes refuses packaging; `--allow-empty-labels` override on `package`/`package-all`/`validate`). Packaging gate remains blind to intro/toc/misc membership by design (DB vs folder parity is 15/15 today but enforced nowhere in-pipeline).

**Re-verified 2026-11-13:** 0 validator issues on 11 existing folders; 931 rows / 2,487 boxes (545 empty — +2 from SLQ `.002`/`.003` marker-only apparatus pages, now flagged `OCR_ALL_NOISE`); membership audit 15/15; fileState ≡1; prefix 0 violations; Nôm order 0/444; `summary.json` pages == DB ocr_done exactly (274+6+110=390).

**Not done / outstanding:**
- Tap2 OCR untouched (explicit exclusion). Tap2 remains a 537-empty-row book; `package-all` now **refuses** it unless `--allow-empty-labels` is passed (intended).
- `align`/`evaluate`/`report` were **not** re-run after the 〓 regeneration; `data/align`, `data/evaluation` contain pre-fix texts (scores unchanged in aggregate but artifact text differs). Re-run before any packaging/report step.
- `FOOTER_TITLE_SUSPECT` and `OCR_ALL_NOISE` pages still need human review (see `docs/review_guide.md`).
- Flags merged by clean/labels remain merge-only (never retracted) — truthful for current runs but revisit flag GC separately.
- Nothing committed; all changes are in the working tree.
