# Fix plan — v2.4 conformance & quality (written 2026-11-19)

> **Audience:** the next agent (or human) picking up this repo with **no access to the conversation that produced this plan**. Everything you need is in this file. Evidence files referenced under "scratchpad" may have been deleted; the key facts are restated inline.
>
> **Status of this plan:** v3.2. It went through two internal verification rounds (red-team review against the code, prototypes on real data, a GPU experiment) and one external review (an independent agent re-ran the official checker and re-measured the numbers). §10 lists the v3.1 corrections and the v3.2 additions (Vintern-1B-v3.5 benchmark, RC10 upside-down Nôm pages). Steps marked ✅ *verified* were prototyped; steps marked ⚠️ carry a residual risk. Numbers depend on the state of `data/` at measurement time (2026-11-19); re-measure before relying on them.

---

## 0. TL;DR

- No book currently passes the **official instructor checker** (`ocr-nom-align` v0.2.0). Official scores: **SLQ 88.55 %**, **Tap1 73.55 %**, Tap2 far lower. The repo's own headline metric (94.71 / 92.75) is a "verified-rows-only" number that the instructors will **not** see.
- The dominant causes are in the **data path**, not in the aligner:
  1. `vi/Label.txt` keeps only the first cleaned line of each QN page → Label ≠ CSV (official `SYNC` check fails everywhere).
  2. `_sort_lines` reorders Nôm boxes wrongly (the API order was already correct).
  3. Vintern-1B-v2 (QN OCR) silently loses text on ~80 page pairs (coverage ratio < 0.7: SLQ 4, Tap1 21, Tap2 57; formula in §3). It also hallucinates sentences that end up in `vi_txt`. **Fix: switch QN OCR to Vintern-1B-v3.5** (already downloaded). Benchmarked on 25 pages it lifts failing pages from 0.25 to 0.87 phonetic recall and normal pages from 0.855 to 0.897 (T2.1).
  4. At least 5 Tap2 Nôm pages were scanned **upside-down**. The API reads the characters, but its right→left box order is then the reverse of the reading order (RC10).
- Keep the repo's aligner (verified better than the official one on this data). Use the official tool as the **release gate**.
- The human-review backlog is too large for one person by 2026-11-30 → **notify instructors today**, freeze text by 23/11, split review across team members.

### 0.1 Implementation status (branch `fix/v24-conformance`, 2026-11-19; nothing committed yet)

| Task | Status | Where / how to verify |
|---|---|---|
| T0.2 snapshot | ✅ | `data/archive/pre-fix-20261119/` (ocr, align, labels, clean, evaluation, layout, output, state.sqlite3; file counts verified) |
| T0.3 quota | ✅ (transport-error ledger logging not done) | `configs/project.yaml` api.limits 500/3000/10000/70000, min_delay 0.5; `quota.py` defaults |
| T1.1–T1.3 one canonical page text | ✅ | `orchestrator.order_and_clean_page` (labels + clean share it; Nôm keeps API order; QN = one full-page box); `clean._clean_nom_indexed` keeps line sources; tests `test_canonical_page.py` |
| T1.4 SYNC self-check + official gate | ✅ | `src/hannom/sync_check.py` (align writes `data/align/<book>/sync_check.json`; package blocks on `SYNC`); `python tools/official_check.py [--book …] [--min 95]` (offline runner `tools/official_nom_cli_offline.py`) |
| G1–G3 | ✅ all 3 books (2026-11-19 23:2x): official `check-diff --final` = ok (0 errors; only `REVIEWED` warnings), repo SYNC = 0 | `tools/official_check.py`; report in `data/diagnostics/official_check/report.json` |
| T2.1 Vintern-1B-v3.5 | ✅ | `local_vintern.Vintern35Engine` (+ loop stopper, loop trim, 2-halves retry, meta-line strip); engine `vintern_1b_v3_5` in `configs/ocr.yaml` and the book yamls; `test_vintern35.py` |
| T2.3 re-OCR all QN pages | ✅ | `python tools/reocr_qn.py --redo-warning QN_REPETITION` (resumable). Weighted phonetic recall v2 → v3.5: SLQ 0.838 → 0.910, Tap1 0.711 → 0.869, Tap2 0.719 → 0.870. Rescue (`tools/qn_rescue.py`) fixed Tap1 vi69, Tap2 vi16/vi260; manual QN queue left: Tap1 vi15, vi26; Tap2 vi114 |
| T2.2 detector / queues | ✅ tool | `python tools/qn_quality.py` → `data/diagnostics/qn_quality/<book>.json|csv` (phonetic recall, queues, RC10 candidates) |
| T2.4 RC10 | ✅ | `nom_reversed_pages` in the book yaml (read by labels/clean); fill it from `qn_quality.py` output after T2.3 (known: Tap2 388, 398, 406, 438, 444; likely 479) |
| T3.1 noise | ✅ | `clean.nom_box_noise` (folio band, corner ornaments, configured running titles), `trim_repeat_runs`, inline `(n)` marks, Cf/selector removal; drops logged to `data/clean/<book>/dropped.jsonl`; `test_nom_noise.py`. Dry run: SLQ 9 titles; Tap1 123 folios + 50 ornaments + 3 runs; Tap2 263 + 37 + 9; regression cases kept |
| T3.2 text_diff v2.4 | ✅ | `textdiff.spec_text_diff` (identical to the official `diff.text_diff` on the test cases), policy `alignment.text_diff_policy` (`spec` default, `legacy` kept); warn keys in `DiffElement`; empty cell ≠ `[]`; edge chars; official counting in `red_penalty`/`scoreable_nom_chars` (repo spec score == official score); gate + report headline use the v2.4 formula; `test_textdiff_spec.py` |
| T3.3 no one-sided rows | ✅ | `align.absorb_one_sided_segments` (charalign) / `absorb_one_sided_groups` (DP); flags `MERGED_ONE_SIDED`, `MERGED_OVER_LIMIT` |
| Validator | ✅ | colours (both legal sets, theme rejected), one-sided rows, NFC, selectors, empty text_diff, missing `type` (invalid, never silently red), pending suggest, unreviewed warn (warning), SYNC, source.zip secrets (`.env*`, `*.sqlite3*`, `hannom_API.md`, bearer tokens), intro/ref/toc need Label.txt + fileState.txt when shipped, `missing/` rules (ch also in ch/, vi not in vi/, no labels, listed in the image map) |
| T4.1 review app | ✅ (headless `streamlit.testing.AppTest` run on SLQ and Tap2: renders, no exceptions; not yet clicked through by a person) | `src/hannom/review/edit.py` (`apply_row_edit` edits Label.txt + CSV together and refuses to break SYNC; `recompute_row_diff`; `accept_warn`; `review_queue` by red density; atomic saves with `.bak-review`), `patches.py` (content-hash patches, stale ones rejected and reported by align as `review_patches_rejected`), `app.py`; `labels` refuses to regenerate Label.txt when reviewer edits exist (`--overwrite-reviewed`); `tests/test_review_edit.py` |
| USER_GUIDE | ✅ | §13 (v2.4 conformance) + outdated lines fixed |
| Report v2.4 sections | ✅ code; ⏳ inputs | `report.compute_book_report_stats` (translation-type ranges, meaning-pair ratio, yellow reviewed/unreviewed, suggestions per source, null ratio + justification, 〓 list), new PDF section, `validate_report_data` issues; **user must fill** `configs/report.yaml`: members (name, MSSV, email), `translation_types`, `null_row_justification`; capture the 4 screenshots; `tests/test_report_v24.py` |
| 〓 list with glyph codes | ✅ code; ⏳ descriptions | clean records `placeholder_origins`; `src/hannom/placeholders.py` maps them to CSV positions via SYNC order; report lists code per 〓 and flags `REPORT_PLACEHOLDER_DESCRIPTION_MISSING:<book>:<code>`; `python tools/placeholder_catalog.py` → `data/diagnostics/placeholders/` (30 codes, 2052 occurrences; top: F047C ×1185 facing "là", F07EF "đường/dường", F03D9 "xem", F070B "một"). **Team writes one description per code** in `configs/report.yaml` `placeholder_descriptions`; codes that are encoded Unicode chars go to `khn_pua_map.yaml` |
| QN rescue (partner-aware) | ✅ tool | `python tools/qn_rescue.py --book <id> [--pages …] [--dry-run]` (halves re-read kept only if phonetic recall vs the Nôm partner rises ≥ 0.10) — run after T2.3 for the `manual_qn` queue |
| extras.zip, pins, packaging | ✅ | `package.build_extras_zip` (patches, decisions, review metadata, SYNC/clean/align summaries, dropped.jsonl, lexicons, QN quality, metrics, official report, 〓 catalogue) wired into `package-all`; the submission folder no longer gets the review-metadata sidecar; `paddlex==3.7.2` pinned; `requirements-lock.txt` (109 packages, `tools/make_lockfile.py`) shipped in source.zip; `book_name` NFC |
| Docs drift | ✅ | README status/QN engine/score formula, `Doc/PROJECT_PLAN.md` marked historical, `configs/report.yaml` method_notes rewritten for the v2.4 pipeline |
| Backlog checks | ✅ verified | persisted book lexicons hold 0 readings (learning only from human-verified rows), so self-learned readings never make a char black; charstream's in-memory learning only affects sentence cuts. Yellow ratio now uses the official definition |
| Orientation of the 6 upside-down Tap2 Nôm images (user chose option 1, 2026-11-20) | ✅ | `rotation_overrides` in the book yaml (extra rotation on top of the PDF /Rotate; re-extraction keeps folder/OCR state); the six images re-extracted upright, Nôm re-OCR'd via the API (12 calls, all `000000`), `nom_reversed_pages: []`, `_updated.pdf` rebuilt (31 rotated pages). Recall of the six pairs 0.74–0.89 → 0.83–0.90; Tap2 official 87.38 → **87.63**, `check-diff --final` ok. Backups: `data/archive/pre-rotate-20261120/` |
| T4.2 full re-run | ✅ | Official score before → now: SLQ 88.55 → **90.81**; Tap1 73.55 → **87.23**; Tap2 46.89 (736/1315 null rows) → **87.38** (0 null). Tap2 switched to `segmentation: charalign` (cosegment DP > 85 min, unfinished). Remaining red (Tap2): reading mismatch 2929, 〓 2299, Nôm without QN 1939, extra QN 407. Go/no-go for Tap2 scope = team decision with these numbers |

---

## 1. Context

### 1.1 Project
- Course project: build a Hán Nôm ↔ Quốc ngữ (QN) sentence-parallel corpus from scanned books. **Deadline 2026-11-30.**
- Package `src/hannom` (~15.5k LOC, 401 tests passing on 2026-11-19). Pipeline:
  `intake → extract → classify → map → ocr → labels → clean → align → textdiff → evaluate → package`
  (run each with `python -m hannom.cli <stage> --book <id>`; see `README.md`, `USER_GUIDE.md`).
- Three books, all **layout T1** (QN pages first, read in increasing page order; Nôm pages at the back, read in **decreasing** page order, right→left columns):

| Config id | File (in `CV20-24127189/`) | Pages | Nôm block | QN block |
|---|---|---|---|---|
| `T1_SuaLoiQuyen` (SLQ) | `T1_Sửa Lưỡi Quyển.pdf` | 118 | 67–116 | 11–63 |
| `T1_CamPhong_Tap1` | `T1_Cấm Phòng Cho Bổn Đạo (Tập 1).pdf` | 282 | 147–276 | 21–144 |
| `T1_CamPhong_Tap2` | `T1_Cấm Phòng Cho Bổn Đạo (Tập 2).pdf` | 550 | 277–540 | 9–275 |

- Nôm↔QN page pairing (`data/layout/<book>/image_map.json`) is derived from printed cross-reference markers (Nôm PDF page = offset − QN PDF page; offsets 127 / 289 / 549). All 444 pairs verified. **Do not touch.**

### 1.2 Authoritative documents (newest wins)
| Document | Location | Notes |
|---|---|---|
| **Quy định đồ án v2.4** (16/11) | `instructor's reference/Quy_định_đồ_án_v2.4.pdf` | **Current spec.** The repo/README/report still cite v2.1 (`docs/Quy_định_đồ_án_v2.1.pdf`). |
| Tool guide (16/11) | `instructor's reference/Hướng dẫn sử dụng công cụ-16-11-2026.pdf` | Describes the official checker/aligner. |
| Official tool source | `instructor's reference/tools-16-11-2026.zip` → contains `ocr-nom-align-main.zip` | Python package `ocr_nom_align` (src/ layout). |
| Samples | `instructor's reference/samples.zip` (`book/ch/Label.txt`, `book/vi/Label.txt`, `book/expected/Sample.csv/.xlsx`, `Sample_image_map.json`) | Expected formats. |
| Kim Hán Nôm API guide | `docs/Hướng dẫn sử dụng API Kim Hán Nôm.pdf` | 4 endpoints; success iff `code == "000000"`. |
| Dictionary description | `docs/Mô tả dữ liệu từ điển Hán Nôm và Quốc ngữ.pdf` | Data in `dictionaries-04-11-2026/entries/*.jsonl`. In `dictionaries-16-11-2026.zip` (~1 GB), `entries/` holds only `catusf.jsonl` (CRC-identical to 04-11) + `.lexview-manifest.json`. The zip also contains two new CSVs (`SinoNom_Similar_Dic_v2.csv` for `--similar`, `QuocNgu_SinoNom_TongHop3.csv`) and the same PDFs/XLSX/lexview installers as the 04-11 set. It lacks the other 11 sources ⇒ keep the 04-11 set. |

### 1.3 v2.4 rules that matter most here (changed vs v2.1)
- **Mandatory**: Label.txt transcriptions (concatenated in reading order) must match the CSV text; cleaning happens in Label.txt; the aligner must not alter text; manual fixes must update Label.txt + CSV + text_diff together. Comparison tolerance: whitespace is ignored on both sides, and on the QN side the hyphen `-` is also ignored (official `ocr_nom_align` `validate.py:276-283`).
- **Every CSV row must have non-empty `ch_txt` and `vi_txt`** (no one-sided rows).
- Rows < 5 Nôm chars or < 5 syllables must be reviewed manually.
- `error` elements have **exactly** 5 keys (`nom_pos`, `nom_sub_text`, `vi_pos`, `vi_sub_text`, `type`). Only `warn` elements may also carry `reviewed` (0/1), `suggest` (exactly one Unicode char replacing one Nôm char, so its `nom_pos` spans 1 char) and `suggest_by`. No pending `suggest` may remain at submission.
- Fixed XLSX colours (000000 / FF0000 / FFFF00 or D32F2F / D99A00); no theme colours.
- **Red is mandatory for**: semantic mismatch, Nôm char not found in any dictionary, `〓` (U+3013, one per unencodable char), repeated/extra Nôm chars.
- Variation selectors U+FE00–FE0F, U+E0100–E01EF must be removed.
- `[MASK]` semantics changed (represents the missing chars; inserted on both sides; QN side attached to the previous word).
- Similarity = (1 − Σ red / scored Nôm chars) × 100. Scored Nôm chars = Nôm chars in rows with `text_diff ≠ null`, **excluding QN text, punctuation, `[MASK]` and yellow (warn) chars**. Red per error element = max(#Nôm chars, #QN syllables); extra QN syllables count. **Red Nôm chars must be corrected** (except `〓`); QN must be exactly correct.
- Report must add: translation-type declaration (phonetic/meaning) per image or sentence-id range, yellow chars reviewed/unreviewed, suggestions accepted/rejected per source, count & ratio of meaning-translation pairs, list of `〓` occurrences, yellow ratio, null-row ratio, 4 appendix screenshots.
- `toc/` now holds QN-only tables of contents; a Nôm TOC with translation goes to `ch/` and must be aligned. `intro/ref/toc`, if submitted, need Label.txt + fileState.txt.
- Quota stated in the docs: 25/min, 50/h, 200/day, 600/week. **The account's real limits (from the user's account page) are 500/min, 3000/h, 10000/day, 70000/week.**

---

## 2. Working rules for whoever executes this plan

1. **Show the user each code change before making it** (user's explicit instruction). Small diffs, one concern per change.
2. The user owns the repo and **runs pipeline stages themselves concurrently** — `data/` can change under you. Record mtimes when measuring; re-check before reporting numbers.
3. When spawning subagents in Claude Code, use **`model: "sonnet"`** (user's choice for cost). In other harnesses, use the cheaper mid-tier model available there, and cross-check subagent numbers before reporting them.
4. Never print or copy secrets: `.env` (`KIMHANNOM_TOKEN`), `hannom_API.md` (plaintext website credentials, gitignored). Never send book text or images to any service except the Kim Hán Nôm API. The official tool by default does **online** dictionary lookups (hvdic.thivien.net) — always run it offline through the sandbox runner in §6.
5. Do not run `tests/test_verify_c_fixes.py` until fixed: lines ~274–283 write a junk file into the real cache `data/ocr/api_cache/zz/zzzz…json` (that junk file exists; delete it once the test is fixed).
6. Windows host (Git Bash + PowerShell). `python -I` ignores `PYTHONIOENCODING` → start scripts with `sys.stdout.reconfigure(encoding="utf-8")`. Open `data/state.sqlite3` read-only for analysis: `sqlite3.connect("file:data/state.sqlite3?mode=ro", uri=True)`.
7. Work on branch `fix/v24-conformance`. At the time of writing, the branch was `UI` with no tracked changes; this file itself is untracked. Commit only when the user asks.
8. **Text freeze:** after D4 (23/11) no automatic change may alter `ch_txt`/`vi_txt` (decisions/patches are keyed to content hashes; any change makes review work stale).

---

## 3. Current state (measured 2026-11-19)

| | SLQ | Tap1 | Tap2 |
|---|---|---|---|
| CSV rows | 379 | 816 | 1315 (user re-ran align 19/11 10:33) |
| null `text_diff` rows in CSV ¹ | 0 | 3 | 736 (56 %) |
| one-sided rows ² | 0 | 3 | 18 |
| error elements / Nôm chars inside `nom_pos` of error elements ³ | 360 / 977 | 1352 / 6572 | 1526 / 9825 |
| official `score` (ocr-nom-align v0.2.0) | **88.55** | **73.55** | not run on the current CSV (old 994-row CSV: −9.36) |
| repo `spec_formula_similarity` | 88.48 | 73.25 | 46.53 |
| repo `similarity` (verified-only) | 94.71 | 92.75 | 88.24 |
| vi pages whose Label has < 90 % of cleaned text | 26/50 | 108/129 | ≈220/264 |
| image_map pairs with QN coverage ratio < 0.7 ⁴ | 4 (vi 016, 032, 040, 056) | 21 | 57 |
| image_map pairs with ratio > 1.2 | 0 | 2 (vi 025: 7.67, vi 026: 1.71) | 0 |
| image_map Nôm pages with **no** CSV row | 0 | 3 (206, 263, 275) | not measured |
| human review decisions recorded | 0 | 0 | 0 |

¹ `metrics.json` `null_rows` excludes one-sided rows: Tap1 metrics 0 vs CSV 3; Tap2 718 vs 736.
² Tap1: the 3 rows have empty `ch_txt` and an `img_id` that is a **QN** image (026, 027, 100). Tap2: the 18 rows have empty `vi_txt` on Nôm images.
³ The official tool counts red as Σ max(#Nôm, #QN syllables) per element: 989 (SLQ) and 7578 (Tap1).
⁴ Coverage formula used for these numbers: for each image_map pair with both sides present and ≥ 20 Nôm chars, ratio = (number of letter runs `[^\W\d_]+` in the cleaned QN text of the `vi` pages) / (number of chars in the cleaned Nôm text of the `ch` pages that satisfy `hannom.clean.is_nom_char` or equal `〓`). Other reasonable formulas give SLQ 4, Tap1 19–24, Tap2 46–69, so always state the formula. SLQ ≈ 1.0 is the healthy reference.

Other facts:
- OCR: Nôm = Kim Hán Nôm API (50 / 132 / 264 pages, no local fallback used); QN = local Vintern-1B-v2 (60 / 144 / 279 pages). OCR results are cached — re-running `labels → clean → align` needs **no API calls**.
- API ledger (`api_calls` table): 1009 calls 08–19/11; week W47 = 459. Local limits (`configs/project.yaml` 25/50/10000/600) now throttle far below the real account limits.
- `submission/` (09/11) is obsolete: 1 book only, 149 all-null rows, `source.zip` missing 7 modules, report named per v2.1.
- `configs/report.yaml` has empty member names/emails; screenshots not captured.

---

## 4. Verified root causes (with code locations)

| ID | Cause | Location | Effect |
|---|---|---|---|
| RC1 | `stage_labels` cleans each OCR line separately and keeps only `cleaned.lines[0]`. The QN page is one full-page box, so only its first cleaned segment survives. | `src/hannom/orchestrator.py:196-206` | vi/Label.txt truncated (e.g. Tap1 p.025: 48 of 7352 chars kept; Tap1 vi side is missing 44,101 chars on 108/129 pages). Official SYNC fails. |
| RC2 | `_sort_lines` reorders Nôm boxes by x-centre, so a column split into two boxes is put bottom-before-top. The API order was already correct (prototype: clustering never beat API order). | `orchestrator.py:129-141`, used at `:196` | ch/Label.txt order ≠ CSV order. SLQ p.067 `阿綿` moved to the front (official SYNC error at row 378). |
| RC3 | Labels and clean are produced by two different code paths: labels sort+clean per box, while `stage_clean` (`orchestrator.py:264-300`) cleans per page in API order. Footnote, dedup and hyphen-join rules apply only on the clean path. | `orchestrator.py:144-300` | Label ≠ clean ≠ CSV even after RC1/RC2 are fixed. |
| RC4 | The Vintern retry only fires when full-page output is `< 40` chars, so partial failures (80–200 chars) are never retried. The retry splits the page into 3 **non-overlapping** bands and merges them with `dict.fromkeys`, which loses lines at band edges and lets the model narrate. | `src/hannom/ocr/local_vintern.py:274` (trigger), `:210-257` (`_band_retry`), `:252` (merge) | QN coverage < 0.7 on 19 + 46 pages. Hallucinated text in `vi_txt`, e.g. Tap1 rows `…170.3` and `…170.4` ("Cô ấy đang ngồi trên giường bệnh viện…"), row `…182.5` (contains "Phần văn bản được nhận dạng là:" with `text_diff=[]`). Tap1 p.025: repetition loop of ~50 cycles (1,665 words; the top 8-gram occurs 52×; only 94 distinct 8-grams). Downstream, its Nôm partner p.263 gets no CSV row. Tap1 p.083: empty after clean, so Nôm p.206 gets no CSV row. |
| RC5 | Text matching folds away **all** combining marks (Mn) and maps đ→d, gi→d, y→i. `allow_flat_match=True` is hard-coded only in the `recompute_text_diff` path, not in `align.py`. The official tool strips only the 5 tone marks (U+0300, U+0301, U+0303, U+0309, U+0323); no such 5-tone constant exists in `src/`. | `charalign.py:54` (fold), `textdiff.py:305,408-415` (flat match), `orchestrator.py:447` (hard-code) | Pairs like `mẫu`/`mau` are scored black → score inflated relative to the official tool. |
| RC6 | Unmatched sentences are emitted as one-sided rows. `UNMATCHED_QN` rows (empty `ch_txt`) take the **QN** image as `img_id`; `UNMATCHED_NOM` rows (empty `vi_txt`) take the Nôm image. | `align.py:636-648, 688-690` | v2.4 violation; official `EMPTY` check fails. |
| RC7 | `〓` is not a Nôm char for `is_nom_char`, so it is outside every denominator and never red. A Nôm char with no known reading is never red on its own (it is routed to review). Unknown chars **inside** an anchored red run do fall inside the red span and inflate `vi_pos`. Red runs are swallowed across `[MASK]`. Extra QN syllables never become error. | `clean.py:131-139` (`is_nom_char`), `textdiff.py:98-99, 372-389, 492-543` (`textdiff.py:310-313` is the docstring describing this policy) | Spec non-conformance; official score differs. |
| RC8 | The gate and the report headline use similarity over "verified" rows only. | `evaluate.py:265-353`, `report.py:272-304` | Misleading 94.71 / 92.75. |
| RC9 | Chinese-numeral page numbers (一百十七…) are not removed: the folio regex covers only Arabic/Roman numerals. No rule handles frame ornaments (熙/照/烈/嘉…). The running-header detector detected 0 running lines on all 3 books (measured value; it is not a constant in the code): its candidates are capped at a short length, and full-page QN text is not split on newlines, so it cannot fire. | `clean.py:83-85, 388-418` | Noise in Label/CSV. Small effect on score (≈3 error elements), but violates the bounding-box rules. |
| RC10 | Some Tap2 Nôm page images are rotated 180° (e.g. ch p.444: folio "- 442 -" and all columns upside-down). The API still recognises the characters and returns in-column text in the correct order, but its box coordinates are in the original image frame and its box order is right→left in that frame, so the **column order is reversed**. The API response carries no orientation field. | data (scans); `kimhannom` box order is used as-is | Confirmed on Tap2 ch 388, 398, 406, 438, 444: phonetic recall vs the QN partner is 0.26–0.28 in API order and 0.77–0.88 with the box order reversed (normal pages: 0.89–0.91 in API order). 18 more Tap2 pages could not be tested because their current QN text is bad. Not seen in SLQ (48 pages tested) or Tap1 (118). |

---

## 5. Plan

Day numbering: D0 = Wed 19/11 … D11 = Sun 30/11. The critical path is D0 → D1 → D2 → D3 → D4 → review → D10.

### D0 (19/11) — preparation
- **T0.1 Notify instructors** (the user does this; you draft the message on request). Cover:
  - current status;
  - per-book expectation: SLQ and Tap1 target ≥ 95 %; Tap2 likely below by 30/11;
  - ask for an adjusted standard for Tap2 (v2.4 allows adjustment to book condition);
  - confirm that 3 books in one ZIP is acceptable.
- **T0.2 Snapshot** `data/ocr` (T2.3 overwrites the QN OCR JSON; the Nôm API results there cost quota to recreate), `data/align`, `data/labels`, `data/clean`, `data/evaluation`, `data/layout`, `data/review` (if present), `data/book_lexicons` (if present) and `data/state.sqlite3` → `data/archive/pre-fix-20261119/`. Create branch `fix/v24-conformance`.
- **T0.3 Quota limits.**
  - `configs/project.yaml` `api.limits`: set to 500 / 3000 / 10000 / 70000; `min_delay_seconds`: 0.5.
  - Update the defaults in `src/hannom/ocr/quota.py:51-54` and `tests/test_quota.py`.
  - Also log transport errors (timeout/connection) to the ledger (`kimhannom.py:301-305`).
  - Acceptance: `pytest tests/test_quota.py`.

### D1 (20/11) — one canonical page text (fixes RC1–RC3)
- **T1.1 Remove Nôm reordering.**
  - Change `_sort_lines` so the Nôm script returns the lines **in API order** (keep top→bottom sorting for QN).
  - Do **not** implement column clustering: it was prototyped (scratchpad `plan/v2/U12/u12c.py`) and never beat the API order.
  - Acceptance: SLQ p.067 `阿綿` stays last; add a unit test with a column split into two boxes.
- **T1.2 Shared function `order_and_clean_page(book, page, script, ocr_lines, running) -> list[tuple[OCRLine, str]]`.**
  - Takes the ordered lines, cleans the **whole page in one call**, and returns per-input-line cleaned text with indices preserved.
  - `clean_page_lines` (`clean.py`) must be extended to return the per-line mapping (input index → cleaned text, `""` if the line was dropped). Do not reverse-map after joining; the round-1 review flagged that as ambiguous.
  - For QN pages (one full-page box), the transcription is the full cleaned page text with newlines → single spaces.
  - Remove `cleaned.lines[0]` (`orchestrator.py:205`).
- **T1.3 Use the shared function in both stages.**
  - `stage_labels` writes the boxes.
  - `stage_clean` writes `data/clean/<book>/NNNN.json` whose `text` is the join of the same per-line results.
  - Leave align and `t1_map._load_cleaned_texts` (`t1_map.py:263`, which reads `data/clean` directly) unchanged.
- **T1.4 SYNC self-check**, using the official normalisation (`ocr_nom_align` `validate.py:276-283`):
  - Nôm: remove all whitespace.
  - QN: remove whitespace and `-`.
  - NFC both sides; pages taken in image_map reading order.
  - Run it in `stage_align` after emitting rows, and in `package`. Fail-closed, with a report of the first mismatching image/offset per side.
- **T1.5 Gate G1.**
  - Re-run `labels → clean → align → textdiff → evaluate` for SLQ and Tap1 (no API calls).
  - Run the official checker (§6).
  - Expected: SYNC = 0 on SLQ and Tap1 for both sides. If Nôm SYNC still fails, diff the first mismatch; the likely cause is a clean rule that applies on one path only.
- Tests expected to need updates: the `test_clean*`, `test_embedded_ocr`, `test_ocr_routing`, `test_verify_a/e/g_*` groups. New tests: Label↔clean round-trip, the SYNC check, and no truncation of a multi-sentence QN box.

### D1–D3 (parallel, GPU) — QN OCR rescue (fixes RC4, RC10)
- **Metric used below: phonetic recall.** Defined as LCS(Nôm chars of the image_map partner page, QN syllables) / Nôm chars. A Nôm char matches a syllable iff the syllable is one of its readings in `data/dictionary/char_readings.json` (char ∪ word tables), compared tone-sensitively but independent of tone-mark placement. The LCS uses a bit-parallel algorithm and takes about 1.4 s for all 442 pairs on CPU. The measure needs no QN ground truth. Its ceiling is ≈0.92–0.97, limited by Nôm OCR and dictionary gaps. It cannot see QN errors that are still a valid reading of the char, nor punctuation or hyphen errors, so it **does not replace proofreading**. Reference implementation: scratchpad `v35\qnm.py` (§11).
- **T2.1 Switch QN OCR to Vintern-1B-v3.5.** ✅ *benchmarked 2026-11-19 on 25 pages (16 failing, 9 normal; 3 books).*
  - Model: `5CD-AI/Vintern-1B-v3_5`, revision `b98f263eab246eb5269ade64edbdca8a887dc44d`. It is already in the HF cache, and its remote code was checked (no network or subprocess calls). It is built on InternViT-300M + Qwen2.5-0.5B and runs on transformers 4.46.3.
  - Loading **must** pass `use_flash_attn=False`; otherwise transformers tries to enable flash-attention-2, which is not installed (Windows), and crashes. Use `torch_dtype=torch.bfloat16`. The checkpoint is stored in fp32 (3.75 GB on disk) and takes 1.76 GB of VRAM in bf16.
  - Generation config (the model card's): `num_beams=3, repetition_penalty=2.5, do_sample=False, max_new_tokens=2048`. Keep the current prompt (`_PROMPT`) and the max-time watchdog.
  - Tiling: all QN page images are 800×1135, so the aspect-ratio rule always picks a 2×3 grid (6 tiles + thumbnail) for any `max_num` ≥ 6. Use `max_num=6`, as the model card does.
  - Code changes in `local_vintern.py`:
    - make `model_id`/revision configurable;
    - add the `use_flash_attn=False` kwarg;
    - make the generation config (`:183-190`) configurable;
    - wire `self.max_num` into `_load_image` (`:151` currently hard-codes 12: a real bug, but harmless on these pages);
    - register a new engine name (e.g. `vintern_1b_v3_5`) in `configs/ocr.yaml` and the 3 book yamls, so the OCR cache does not serve v2 results (see T2.3).
  - Results (phonetic recall, weighted by Nôm chars):

    | Engine / config | Failing pages (16) | Same, excl. 4 Nôm-side pages (12) | Normal pages (9) | s/page |
    |---|---|---|---|---|
    | v2 production (cached, incl. band retry) | 0.218 | 0.249 | 0.855 | — |
    | v2 full page (re-run) | 0.068 | — | 0.851 | 8 |
    | v2 2 halves 15 % overlap | 0.439 | — | 0.668 | 16 |
    | **v3.5, model-card config** | **0.707** | **0.868** | **0.897** | 19 (14 on normal pages) |
    | v3.5 full page, greedy, rep 1.2 | 0.654 | — | 0.744 | 13 |
    | v3.5 2 halves | 0.677 | — | 0.867 | 15 |

    The 4 "Nôm-side" pages (Tap2 vi 070, 105, 111, 151) stay at 0.24–0.30 for every engine and config. Three of them are RC10 pages (reversed Nôm order), and 070 is unresolved (§9). So V3.5 essentially solves QN OCR. The pages it does not solve are Nôm-side problems.
  - Failure modes still seen with V3.5:
    - greedy/rep 1.2 returned only the folio on Tap2 vi 032 ("-30- (515)");
    - the model-card config looped on Tap2 vi 070 (coverage 7.8);
    - character errors remain, e.g. SLQ vi 040 "muôn dữ" for "muông dữ" and "kẻ kèo" for "kẻo".
    
    Keep the retry and the meta-phrase stripping, and keep human QN proofreading.
  - Retry policy, when phonetic recall < 0.6 **or** coverage < 0.7 or > 1.3 **or** 8-gram repetition ≥ 4 **or** a meta phrase is present:
    1. Run V3.5 on 2 halves overlapping 15 % (stitch below).
    2. Keep the candidate with the higher phonetic recall. This needs the Nôm partner page; it is available because Nôm OCR runs first.
    3. If recall is still < 0.6, run the RC10 order test (T2.4) before sending the page to manual QN.
    
    On the benchmark the retry fired on 4/16 failing pages, exactly the 4 Nôm-side pages.
  - Replace the old trigger `len(text) < 40` (`:274`) and the 3 disjoint bands merged by `dict.fromkeys` (`:210-257`, `:252`) with this policy. Strip meta phrases ("Phần văn bản được nhận dạng là", "dòng cuối cùng là", markdown fences or `**`).
  - Stitch function (from the experiment):
    ```python
    def stitch(parts):
        out = parts[0].split()
        for p in parts[1:]:
            w = p.split(); best = 0
            for k in range(min(len(out), len(w), 60), 2, -1):
                if [x.lower() for x in out[-k:]] == [x.lower() for x in w[:k]]:
                    best = k; break
            out += w[best:]
        return " ".join(out)
    # 2 halves with 15% overlap: bh = h/(1+(n-1)*(1-0.15)); stride = bh*0.85; crop (0, i*stride, w, min(h, i*stride+bh))
    ```
- **T2.2 Detector and queues.** Run per QN page after re-OCR (T2.3), using phonetic recall plus the coverage ratio (QN syllables / Nôm chars of the partner pages).
  - Recall < 0.6 → RC10 order test (T2.4), then manual QN queue.
  - Recall 0.6–0.8, coverage outside 0.85–1.2, or 8-gram repetition → human QN queue (priority).
  - The current v2 output has 2 / 16 / 26 pairs with recall < 0.5 (SLQ / Tap1 / Tap2); re-measure after T2.3.
  - Do **not** use a broad "modern vocabulary" regex: it gave 10/50 false positives on SLQ (e.g. "tôi không" is a valid prayer phrase).
- **T2.3 Re-OCR all QN pages** (50 + 130 + 264) with V3.5, not only the failing ones, because V3.5 also improves normal pages (0.855 → 0.897).
  - Cost ≈ 15–20 s/page ⇒ ≈ 2–2.5 h of GPU for all three books. Run it overnight D0→D1 or alongside D1.
  - Write new OCR JSON under the new engine name. The current cache key is page_no + sha only (`router.py:152-203,284`), so without a new engine/version field the v2 result is served again.
  - Then re-run `labels → clean → align`. No Kim Hán Nôm API calls are needed.
- **T2.4 Fix RC10 (upside-down Nôm pages).** Needs good QN text, so run it after T2.3.
  - For each pair, compute phonetic recall of the QN text vs the Nôm boxes in API order and in reversed box order. If reversed > API + 0.2, mark the Nôm page as reversed.
  - Record the result in the book yaml (e.g. `nom_reversed_pages: [388, 398, 406, 438, 444]` for Tap2, plus any newly found) so the ordering is reproducible and reviewable. Do not detect it silently at run time only.
  - In the shared ordering function (T1.2), reverse the API box order for listed pages. Box coordinates stay as they are; they are correct for the image as stored.
  - Do **not** rotate the image files. That changes image hashes and the submitted images, and needs new API calls.
  - Acceptance: recall of the listed pages ≥ 0.75, and official SYNC still 0.
- **Gate G2.** No QN page with phonetic recall < 0.6 remains unexplained (it is either fixed, an RC10 page, or in the manual queue with a reason). Every page is in the human QN proofreading queue, ordered by recall ascending, because v2.4 requires exact QN.

### D2 (21/11) — Label hygiene + text_diff conformance
- **T3.1 Noise filters** in the shared clean function. ✅ *verified: 0 false positives on the regression cases.* Each filter writes `data/clean/<book>/dropped.jsonl` and supports a dry-run.
  - **Folio:** drop a box only if all of these hold:
    - its chars ⊂ `〇一二三四五六七八九十百千`;
    - its top `y0/H` lies within ±0.05 of the median folio band of that book;
    - at least one neighbour page (±4) has a folio consistent with the **decreasing** page sequence.
  - Regression cases that must survive: Tap2 pp.312–346 body-text 三/四/五 at y≈150–226; Tap1 p.234 and p.263 (`三` at y≈888).
  - **Ornament:** drop only when ≤ 2 chars AND API confidence < 0.7 AND inside a corner zone (normalised); otherwise flag only. A character list alone (熙照烈嘉) misses half the ornaments, and a confidence-only rule deletes ~165 real boxes per book.
  - **Repeat-run:** remove only runs of ≥ 4 identical low-confidence chars (e.g. `无无无无无无无`), not the whole box.
  - **Running title by geometry** (margin position after ordering), e.g. `所𥚇卷` on SLQ pages.
  - Expected removals: SLQ 0, Tap1 ~71 boxes, Tap2 ~59 boxes. Negligible score effect (expected).
  - Also fix:
    - the footnote rule deleting real lines that start with `*`/`**` (`FOOTNOTE_RE`, `clean.py:89`; applied at `:383`);
    - remove inline `(n)` footnote markers. `INLINE_REF_RE` (`clean.py:90`) handles only `[n]`; `FOOTNOTE_RE` (`:89`) handles `(n)` only at line start, and deletes the whole line;
    - Cf characters (ZWJ/ZWSP/BOM) must be removed, not turned into `〓` (`clean.py:151-189`);
    - remove variation selectors.
- **T3.2 text_diff / evaluation conformance** (files `textdiff.py`, `evaluate.py`, `models.py`, `align.py`):
  - Official fold for text_diff: strip only U+0300/0301/0303/0309/0323. Keep the lenient fold **only** inside charalign anchoring (`tests/test_charalign.py:37-41` expects quỷ=quỉ, đ=d there).
  - `〓` → its own error element and counted in the denominator.
  - Dictionary-unknown Nôm char → error, after all local dictionaries (plus `data/dictionary/catusf_hv_harvested.jsonl` if adopted).
  - Extra QN syllables → error element (official counting).
  - Fix red runs swallowed across `[MASK]`, and `vi_pos` inflation by unknown chars (`textdiff.py:492-533`).
  - The internal validator must accept spec-valid elements: error on `〓`; warn on a number like "1571" (`textdiff.py:161-183`).
  - An empty `text_diff` cell is an error and is never read as `[]` (`align.py:833-834`). `[]` stays valid for fully matching rows (`tests/test_align_unmatched.py:35`).
  - Preserve `reviewed` / `suggest` / `suggest_by` on **warn** elements in `DiffElement` (`models.py:75-90`), plus the reader at `align.py:828-842`. Error elements must keep exactly 5 keys. Also stop defaulting a missing `type` to `"error"` (`evaluate.py:62`).
  - Denominator: exclude punctuation, `[MASK]` and yellow chars (§1.3).
  - Nôm-side parity check: the multiset of Nôm chars in Label equals that in the CSV; fail-closed. Tap2 align once dropped 37 `〓`.
  - Report the official-formula similarity as the headline in `evaluate.py` and `report.py`. Keep the verified-only figure as secondary.
- **T3.3 No one-sided rows.** Merge an unmatched sentence into the adjacent row on the same Nôm page, at most 3 sentences per side (the official limit, `ocr_nom_align` `align.py:250-258`); otherwise send it to the manual queue. `img_id` must be the Nôm image that contains the sentence start. Update `tests/test_align_unmatched.py:47-109` and `tests/test_textdiff_null_preservation.py:41`.
- **Gate G3.** Official `check-diff --final` = 0 errors on SLQ and Tap1.

### D3 (22/11) — review tooling + re-measure
- **T4.1 Review app** (`src/hannom/review/app.py`, `patches.py`):
  - Key patches by content hash plus the Nôm image, not by positional `sentence_id`. Reject a patch whose `before` does not match. This fixes silent overwrite after re-segmentation (`patches.py:101-127`).
  - An edit updates Label.txt **and** CSV, then auto-recomputes `text_diff`. No more raw JSON editing (`app.py:198`).
  - Sort the queue by red density; show progress; add "accept & next".
  - Fix: always reads `ch/Label.txt` (`app.py:173`); ignores `HANNOM_BOOK` (`cli.py:404` vs `app.py:93`).
- **T4.2 Full re-run** of the 3 books, the official checker, and new counts → **go/no-go for Tap2 scope.** Suggested rule: if Tap2 still has > ~800 error elements, review only structure + QN pages of non-null rows + the densest red, and declare the rest unreviewed in the report.

### D4 (23/11) — TEXT FREEZE
No automatic change to `ch_txt`/`vi_txt` after this point.

### D4–D9 (23–28/11) — human review + deliverables (parallel)
- **Review, split across members.** The upper-bound estimate before the fixes was ≈ 68 person-hours (40 s per error element, 2.5 min per QN page, 1.5 min per short or one-sided row); re-estimate after T4.2.
  - SLQ fully reviewed: ≈ 360 elements, 50 QN pages. Reaching 95 % needs ≈ 560 red chars fixed.
  - Tap1 fully reviewed.
  - Tap2 per the scope decision.
  - Rows < 5 chars/syllables are reviewed manually (v2.4).
- **Validator** (`tools/validate_submission.py`, `package.py:415-615`). Audit E built a fake broken submission and it **passed**. Add checks for:
  - one-sided rows;
  - variation selectors;
  - pending `suggest`;
  - NFD cells;
  - SYNC;
  - `missing/` ⇔ one-sided image_map pairs;
  - intro/toc/ref must have Label.txt;
  - exact colour codes (`package.py:398-406`). Today the check **false-rejects** the spec-legal pair D32F2F/D99A00 (it accepts only FFFF0000/FFFFFF00) and silently ignores theme colours. Accept both legal sets and reject theme colours;
  - secret patterns in `source.zip`: `hannom_API.md`, `.env*`, `*.sqlite3*` including `state.sqlite3.bak-*`, and token-like strings inside `.json`/`.md`.
  
  Treat warnings separately from failures.
- **Report** (`report.py`): the v2.4 sections listed in §1.3, the official score as the headline, and the `〓` list. Fill `configs/report.yaml` with members (name, student id, email); capture the 4 screenshots (`tools/capture_screenshots.py`); name the report `<MSSV…>_report.pdf` after the zip name.
- **Reproducibility.**
  - Ship decisions, patches and lexicon in `extras.zip`.
  - `USER_GUIDE.md`: environment (Windows 11, Python 3.13.9, RTX 4060 8 GB), Vintern prompt, token setup; Linux commands as well as PowerShell.
  - Pin torch, torchvision, opencv and paddlex or document them; consider a lockfile.
- **Package:** stop copying `review_metadata.jsonl` into the book folder (`package.py:261`); include `_updated.pdf` for Tap1 and Tap2 (rotated pages), and tell the hand-out person.

### D10 (29/11) — final run
Run the full pipeline for 3 books → official `check-diff --final` + `score --min 95` per book → `package-all` → `tools/validate_submission.py` → report → final zip.

### D11 (30/11) — buffer and submission.

---

## 6. How to run the official checker safely (offline sandbox)

1. Extract `instructor's reference/tools-16-11-2026.zip`, then the inner `ocr-nom-align-main.zip`, into a scratch folder **outside the repo**, e.g. `<scratch>/ocr-nom-align-main/`.
2. Save this runner as `<scratch>/nom_cli.py`; it blocks all network access before the package is imported:
   ```python
   import os, socket, sys, urllib.request
   sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
   HERE = os.path.dirname(os.path.abspath(__file__))
   TOOL_SRC = os.path.join(HERE, "ocr-nom-align-main", "src")
   def _deny(*a, **k): raise RuntimeError("network blocked")
   socket.socket.connect = _deny; socket.socket.connect_ex = _deny
   socket.create_connection = _deny; socket.getaddrinfo = _deny
   urllib.request.urlopen = _deny
   os.environ["NOM_ALIGN_OFFLINE"] = "1"
   os.environ["NOM_ALIGN_ENV_FILE"] = os.path.join(HERE, "__none__")
   os.environ["NOM_ALIGN_CACHE"] = os.path.join(HERE, "_cache_unused.json")
   for k in ("NOM_ALIGN_TABLE", "NOM_ALIGN_SIMILAR", "NOM_ALIGN_CONTACT", "NOM_ALIGN_OUT_DIR"):
       os.environ.pop(k, None)
   sys.path.insert(0, TOOL_SRC)
   from ocr_nom_align import cli
   from ocr_nom_align import online as _online
   _online.http_get = _deny
   if __name__ == "__main__":
       cli.main(args=sys.argv[1:], prog_name="ocr-nom-align")
   ```
3. Stage a **copy** of each book: `<stage>/<Book>/ch/Label.txt`, `vi/Label.txt` (exactly as `package` would write them), `<Book>.csv`, `<Book>_image_map.json`.
4. Run with `python -I <scratch>/nom_cli.py check-diff --final …` and `… score --min 95 …`. Read the exact arguments from the tool's `README.md` / `cli.py`; `check`, `check-diff` and `score` are offline-safe. For `run`, always pass `--offline`, never `--similar` or `--ch-fallback`, and list `--table` files explicitly (skip `catusf.jsonl`, 2.4 GB).
5. Check codes: KEYS, OOB, OVERLAP, EDGE, MASK, SUB, SELECTOR, FORM, REVIEWED, SUGGEST, SUGGEST_PENDING, EMPTY, SYNC, XLSX. SYNC reports only the **first** mismatch per side, so iterate.
6. Sanity check: on `samples.zip` the tool scores 100 / ok.

A `tools/official_check.py` wrapper (T1.4/G1) should automate steps 3–5 per book and return non-zero on failure.

---

## 7. Rejected approaches (do not redo)

| Idea | Why rejected (evidence) |
|---|---|
| New Nôm column-clustering sort | Never better than the API order (SYNC mismatch vs CSV: API 5889 / clustering 5914 on Tap1); over-merged columns unless tightly capped. |
| Replace the repo aligner with official `run --mode phonetic` | On real data it fails: "no alignment path inside the band", because Nôm Labels have no punctuation (1 Nôm sentence vs 385 QN). With the repo's segmentation injected it is worse: 535 vs 360 error elements, 6 null rows. Runtime 7 s / 83 MB (not the issue). |
| Vintern `max_num` 6 / 12 / 24 | No effect, and the experiment was valid: the U4 script patched the tiler, so the hard-code at `local_vintern.py:151` did not matter. Every QN page is 800×1135, and the aspect-ratio rule picks a 2×3 grid for any `max_num` ≥ 6, so the output is identical. |
| Upscale ×2 + `max_num=24` (25 tiles) | Tested 2026-11-19 on 25 pages. Worse on both models (phonetic recall failing/normal: v2 0.30/0.45, v3.5 0.48/0.57), slower (26 s/page on v3.5) and the VRAM peak hits 7.5 GB. Both models were trained with ≤ 12 tiles. |
| Vintern-1B-v2 with 2 halves as the default | Helps failing pages (0.07 → 0.44) but hurts normal pages (0.85 → 0.67). Superseded by V3.5 (T2.1). |
| 3 overlapping bands | Worse than 2 halves: truncation, repetition, narration ("dòng cuối cùng là…"). |
| Noise filters as a score lever | Remove ~3 of 2,878 error elements. Still required for Label hygiene. |
| Broad modern-vocabulary hallucination detector | 10/50 false positives on SLQ. Use coverage ratio + repetition + known meta phrases. |
| Migrating review decisions/patches | Not needed: zero decisions exist. Enforce the text freeze instead. |

---

## 8. Full findings backlog (deduplicated; fix opportunistically when touching the file)

**Critical/High** (most are covered by §5): RC1–RC10. Further items:
- The validator false-passes broken submissions (§5 D4–D9).
- `difficulty` IndexError after image-rec fallback, which silently routes the page to local OCR (`kimhannom.py:550-557,605`).
- Image map cannot represent pages lost in scanning: the final sort pushes empty-vi pairs to the end and the marker validator rejects one-sided pairs (`t1_map.py:465-480,571-576`). No missing-page detection exists (`models.py:12`, `layout.py:301-355`). **No missing pages exist in current data → deferred**, but document it in the report.
- Review patches silently overwrite another sentence after re-segmentation (§5 T4.1).
- Decisions can go falsely stale because `_emit_rows` recomputes the diff with a different policy than the one hashed (`orchestrator.py:543-557`).
- `charalign` path skips the QN token-parity check (`align.py:759-800`; `orchestrator.py:524` only checks when `qn_tokens_stream` is set). `charstream` learns a lexicon from unreviewed output (`charstream.py:217-222`).

**Medium:**
- Pages that fell to `local_fallback` stay there forever; the cache key lacks engine/upscale (Tap2 mixes upscale 1 and 2) (`router.py:152-203`).
- `lang_type` is forced to 2 although the embedded OCR came from classification with 0 (`kimhannom.py:500`). image-rec runs on the full page instead of crops (`kimhannom.py:558-578`).
- The band DP uses a fixed `|i-j| ≤ 64` not scaled by n/m (`align.py:501`).
- Two different syllable regexes; PUA/`〓` are counted differently in charstream vs textdiff.
- The text_diff parser defaults a missing `type` to "error" (`evaluate.py:46`).
- Positions are checked after NFC normalisation, so NFD cells pass (`textdiff.py:225`).
- The yellow ratio uses mismatched numerator and denominator.
- Classify only adds flags, never removes stale ones (`layout.py:360`).
- Dead config keys: `max_poor_nom_page_ratio`, `unknown_policy`, `require_dictionary_for_black`, `proper_name_max_*`, `require_for_final_gate`, `mark_cross_page_joins`; `configs/review.yaml` is unused.
- PUA codepoints from the API are all replaced by `〓` in clean. `configs/khn_pua_map.yaml` (33 lines) lists 22 PUA codes seen in the books and maps only one (F021D→𡃕); the map is opt-in via `KHN_PUA_ENABLED` and off. An earlier audit measured readings for 11 of the 22 codes in the derived cache `data/dictionary/char_readings.json` and in `dv`/`dnqatv`/`btcn` entries. That figure is **unverified, and the data is not in git**; re-measure before relying on it. If the readings hold, extending the PUA map reduces `〓` (which v2.4 makes red).

**Low:**
- Book-specific hard-code `"sua luoi"` in a generic module (`clean.py:271`).
- `book_name` is not NFC-normalised (`config.py:57-59`).
- Quota day/week labels use UTC, not UTC+7 (`state.py:392-395`).
- XLSX sheet is named `alignment` (the official sample uses `align`; accepted as the first sheet).
- Label.txt has an extra `confidence` field (must be explained in the report).
- Docs drift: README test counts and status; `Doc/PROJECT_PLAN.md` says "No pipeline code exists"; `configs/report.yaml` `method_notes` is outdated; README says "never auto-yellow", but `charalign.py:490` emits warn.
- CI only triggers on `dev`/`main`/`repair/**`/`feat/**`.
- No tests for package, report, validator, labels/clean/align end-to-end.

---

## 9. Open questions for the user
1. Has the instructor message (T0.1) been sent? What did they answer about Tap2 and the single ZIP?
2. Who on the team reviews which book (D4–D9)?
3. Adopt `catusf_hv_harvested.jsonl` as an extra dictionary for the "unknown → red" rule? This reduces false reds.
4. Tap2 vi p.070 ↔ ch p.479: phonetic recall is 0.24–0.27 for every engine, and only 0.12–0.27 against ch 476–482. Bag-of-readings overlap is 0.44, and it is not an RC10 page. Someone must look at both images: a wrong pair, a damaged scan, or a non-transliterated page?

## 10. v3.1 corrections (after the external review, 2026-11-19)

An independent agent re-verified this plan. It re-ran the official checker and reproduced SLQ 88.55 / Tap1 73.55, the SYNC failures on all 4 sides, the CSV counts, the ledger (1009 calls / 459 in W47), the 444 verified pairs, and RC1–RC9 in code. Its corrections were re-checked before being applied:

| Item | v3 said | v3.1 (re-measured) |
|---|---|---|
| QN coverage < 0.7 | 0 / 19 / 46 pages, formula unstated | 4 / 21 / 57 pairs with the formula in §3 note 4. The external agent's formula gave 4 / 24 / 69. **SLQ is not 0.** |
| p.025 loop | 20× | ~50 cycles (top 8-gram ×52) |
| Hallucination rows | `.170.4`, `.182.5` | also `.170.3` |
| Vintern `max_num` | tested, no effect | v3.1 said "untested" — **that was wrong** (v3.2): the U4 script patched the tiler, so the test was valid; the cause of "no effect" is the fixed 2×3 grid (§7) |
| Spec details | — | denominator also excludes yellow/[MASK]/punctuation; `reviewed`/`suggest`/`suggest_by` are warn-only; SYNC ignores `-` on the QN side |
| RC5 / RC6 / RC7 / RC9 wording and line references | partly imprecise | corrected (see §4) |
| `khn_pua_map.yaml:199-200` | cited | the file has 33 lines; the claim is reworded as unverified (§8) |
| Tap2 metrics | 47.22 | 88.24 verified-only / 46.53 spec formula after the user's 10:33 re-run; official score not re-run |
| Tap1 Nôm pages without rows | — | 206, 263, 275 (new; 206 and 263 explained by RC4) |
| Validator colours | "reject theme colours" | also false-rejects legal D32F2F/D99A00 |

External claims that were **not** confirmed:
- "Tap2 clean is stale (11/17)". The sampled Tap2 `data/clean` and `data/labels` files are dated 19/11 08:14 and align is 10:33, so the chain looks consistent; re-check mtimes before measuring.
- "The model `sonnet` does not exist". That holds only for the external harness; §2 rule 3 was reworded.

### v3.2 additions (2026-11-19, after the Vintern-1B-v3.5 benchmark)
- QN OCR engine changed to Vintern-1B-v3.5 with the model-card generation config (T2.1, results table). Re-OCR all QN pages (T2.3). The detector uses phonetic recall (T2.2).
- New root cause RC10: upside-down Tap2 Nôm scans reverse the column order; new task T2.4.
- `max_num` correction (row above), and two more rejected approaches (§7).
- Open question 4 (Tap2 vi 070).

## 11. Evidence (may no longer exist)
Session scratchpad `C:\Users\MSI VN\AppData\Local\Temp\claude\1d2653b4ea906cb3\d38c8d14-1189-4b7f-8ce3-a10098120b49\scratchpad\`:
- `audit2\A_upstream.md` … `F_data_audit.md`: six audits.
- `plan\fix_plan_v1.md`, `v2.md`, `v3.md`.
- `plan\v1\review_P012.md`, `review_P34.md`, `review_P567.md`: round-1 red-team.
- `plan\v2\U12\` (filters/ordering prototypes), `U3\` (official aligner benchmark), `U4\` (Vintern experiment: `run.py`, `results.md`).
- `pdf\*.txt`: text extracted from all specification PDFs.
- `v35\`: Vintern v2 vs v3.5 benchmark. `qnm.py` (phonetic-recall metric), `baseline.py`/`baseline.jsonl` (current v2 output, all 442 pairs), `pages.json` (25 test pages), `run.py` (GPU runner: `python run.py v2|v35`), `res_v2.jsonl`/`res_v35.jsonl` (all outputs with text), `summary.py` (tables), `ch444_preview.jpg` (upside-down Nôm page).
