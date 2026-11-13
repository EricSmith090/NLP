# Area B Verification Report — Stage 2 (Layout/Classification) & Stage 2b (T1 Nôm↔Quốc ngữ image map)

> **REVISION 2026-11-12 (post map-repair change-set):** written against pre-`feat/map-repair-align` state. The collaborator's uncommitted 2026-11-12 change-set (content-DP image_map repair + parens anchors; Tap1 scope re-bin; `hannom.charstream` segmenter; CSVs rebuilt; labels regenerated; tests 277→282, all pass) invalidates the claims marked REVISED below. Numbers re-measured read-only 2026-11-12.
>
> **REPLICATION AUDIT 2026-11-13:** four independent read-only audits (code check; data re-measurement; 32-image ground truth; tests/git/docs hygiene) re-measured nearly everything below. Everything quantitative re-measured as stated — CONFIRMED (maps byte-identical incl. the 6 Tap1 double-absorb groups; metrics exact; CSVs 823/380/8 rows; review-metadata flag histograms exact; DB bins exact; `_pre-repair-2026-11-12` = exactly 1,421 nested levels; backup 1,015,808 B; 18/18 sampled image markers (8 Tap1 + 5 Tap2 + 5 Tap3) match `const−vi`; zero contradicting images; zero `(N)` markers on endnotes/dividers/folio-only blanks; Nôm PDF = printed − 2). Corrections applied in place 2026-11-13 (marked "(revised 2026-11-13)"): tests 282→291; git snapshot 15M+19?? (audits ran pre-commit; the change-sets then landed in `ed43470`/`4fd0af6` and pushed — tree now clean except this document); B3 rewritten (package round-trip drops `meta`; package-time validation = duplicates/empty-pair only; cites shifted +12/+58); B2/§7 `.268.4` — one legitimate occurrence remains (monster gone); M2 — markers survive in clean `dropped_lines` (101/104), `fold()` not `norm_reading`, fix regex validated; §4 BIN_OVERRIDE attribution fixed (status wipe is unconditional at `layout.py:354`; p1 cover re-bin edge); N1 narrowed (`max_group/max_nm_group` live in sentence DP, dead only on map DP); `markers_scan.py`→`markers_all.txt`; `unverified_ratio` derives from `unverified_rows/total_rows` (no metrics key); decisions.md errata confirmed verbatim. See §12 Replication audit log.

**Audience:** the next agent working on the Nôm↔Quốc ngữ parallel corpus. Zero prior context assumed.
**Date:** 2026-11-12 (original 2026-11-12 morning; revised in place 2026-11-12 — see §11 Revision log; replication-audit corrections in place 2026-11-13 — see §12 Replication audit log; the two 2026-11-13 commits `ed43470`/`4fd0af6` landed after this audit ran)
**Verdict:** (revised 2026-11-12) Stage 2 (block detection) is sound and unchanged. **Stage 2b (the T1 image map, the backbone) was systematically wrong in all three books when this report was first written; the two live books (Tap1, Tap3) have now been re-paired in place by the 2026-11-12 content-DP + parens-anchor repair — Tap1 121/127 pairs parens-consistent (all 1:1 pairs consistent; front matter re-included; the monster align row is gone), Tap3 50/50 — but every pair in every book is still `candidate`; zero are `verified`; the packaged submission would still ship unadjudicated page equivalences.** Tap2 was not repaired. The deterministic fix (the `( N )` Nôm printed page marker) is printed on every substantive QN page (incl. title/TOC front matter as of 2026-11-13 re-measurement — never on endnotes/dividers/folio-only blanks) and now corroborates all repaired 1:1 pairs, but it is still not wired as the `verified` criterion (R2, not executed). Verification channels that should have caught the original breakage are starved or broken (M1/M2/M4 — all still valid). **Verdict unchanged by the 2026-11-13 replication audit; every open item and every correction pointer is restated in §12.**

---

## 1. Scope & files

| Area | Files |
|---|---|
| Stage 2 classifier | `src/hannom/layout.py` (2026-11-12: `BIN_OVERRIDE_*` block added, post-insertion lines ~339–348 — never exercised in the delivered state; re-probed 2026-11-13: still zero flags) |
| Stage 2b image map | `src/hannom/t1_map.py`, `src/hannom/anchors.py` |
| Image-map repair (new 2026-11-12) | `src/hannom/map_repair.py`, `tools/repair_image_map.py` |
| Segmenter (new 2026-11-12) | `src/hannom/charstream.py` |
| Cleaning helpers used by the map | `src/hannom/clean.py` (`is_nom_char`, `nfc`, `CJK_RANGES`) |
| Config | `src/hannom/config.py` (`BookConfig`), `configs/books/T1_CamPhong_Tap1.yaml`, `T1_CamPhong_Tap2.yaml`, `T1_SuaLoiQuyen.yaml` (Tap1/Tap3 yamls re-binned by the change-set), `configs/project.yaml` (`quality:`), `configs/alignment.yaml` |
| Data inspected (read-only) | `data/layout/*/classification.json`, `data/layout/*/image_map.json`, `data/layout/*/map_repair/` (backups + summaries + triage), `data/clean/*/*.json`, `data/ocr/*/*.json`, `data/labels/*`, `data/align/*`, `data/evaluation/*/metrics.json` (+ `metrics.20261112T*Z.json` archives), `data/dictionary/book_lexicons/*.json`, `data/dictionary/char_readings.json` (26,700 merged chars), `data/state.sqlite3` (+ `data/state.sqlite3.bak-2026-11-12-rebin-fix`), page images under `data/pages/*/native/` |
| Downstream consumers | `src/hannom/align.py`, `src/hannom/cosegment.py`, `src/hannom/charalign.py`, `src/hannom/package.py`, `src/hannom/cli.py`, `src/hannom/orchestrator.py`, `src/hannom/dictionary/book_lexicon.py`, `src/hannom/dictionary/index.py` |

Test suite: `python -m pytest -q` → **291 passed, 2 warnings** (re-collected 2026-11-13; growth since the 282 below = the 2026-11-13 verify-A hardening, `tests/test_verify_a_hardening.py` (9 tests)). (revised 2026-11-12 → recounted 2026-11-13)

---

## 2. Method & ground rules

- Read-only on the repo and `data/`. No Kim/KimHánNôm API calls were made. `.env` and `hannom_API.md` were never read; no secrets printed.
- Scratch directory used for probes: `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B` (all probe scripts listed in §8, pre-repair); `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B` (2026-11-12 re-measurement probes: `probe_db*.py`, `probe_consistency.py`, `probe_prerepair.py`, `probe_manual*.py`, `probe_proposed.py`, `probe_csv*.py`, `probe_meta*.py`, `probe_ocr.py`, `probe_pairs.py`, `probe_dups.py`). (revised 2026-11-12 → §8 reference fixed 2026-11-13)
- Full suite run: `python -m pytest -q` (291 passed, fast, no GPU; 282 at the 2026-11-12 revision; 277 at first writing). Re-verified green 2026-11-13 (exit 0; warnings are pre-existing numpy/pandas deprecations). (revised 2026-11-12 → 2026-11-13)
- Evidence classes used: (a) direct reads of page **images** (printed page numbers, `( N )` markers, book typography), (b) the existing vintern full-page OCR text (`data/ocr/*.json`) — markers appear there for many pages, (c) the merged hvdic/unihan/etc. reading cache `data/dictionary/char_readings.json` used as a dictionary for reading-anchor probes, (d) the pre-built `charalign` pipeline run three ways (old pairs / no pairs / marker-correct pairs) as a controlled experiment (`three_way.py`), (e) row-level inspection of the real alignment CSVs and evaluation metrics, (f) 2026-11-12 read-only re-measurement of maps/metrics/CSVs/DB bins/pre-repair backups (this revision).
- The three T1 books (`T1_CamPhong_Tap1` = Tap1, `T1_CamPhong_Tap2` = Tap2, `T1_SuaLoiQuyen` = Tap3) are all "dịch âm"/transliteration-style parallel books: QN printed front-to-back, Nôm printed back-to-front.
- Git state at revision (verified read-only 2026-11-12): branch `feat/map-repair-align` == current; HEAD `c3439e7` (== `repair/pipeline-audit-2026-11-09` tip, on origin); **ZERO new commits**; the collaborator's 2026-11-12 change-set is uncommitted — 9 modified (`configs/alignment.yaml`, `configs/books/T1_CamPhong_Tap1.yaml`, `configs/books/T1_SuaLoiQuyen.yaml`, `docs/decisions.md`, `src/hannom/align.py`, `config.py`, `layout.py`, `orchestrator.py`, `textdiff.py`) + 5 new source/tool/test files (`src/hannom/charstream.py`, `src/hannom/map_repair.py`, `tools/repair_image_map.py`, `tests/test_charstream.py`, `tests/test_map_repair.py`). **Update 2026-11-13 (post-commit):** both change-sets are now committed — `ed43470` (2026-11-13 08:07 +0700, "map repair + declarative re-bin; Area A-I audit docs") and `4fd0af6` ("verify-A (Area A) hardening: state integrity, gates, preflight") — `feat/map-repair-align` is pushed to origin and up to date, and the tree is clean **except this document** (`git status --porcelain` → ` M Doc/verify-B-layout-t1-imagemap.md`). CI (`.github/workflows/ci.yml`) triggers on push to `dev`/`main`/`repair/**` + PRs (py3.11/3.13, `python -m pytest -q`) — **not** on pushes to this branch. (revised 2026-11-12 → 2026-11-13)

---

## 3. The marker evidence (decisive)

**Printed in the header of every substantive QN page** (top-right, e.g. `- 58 - ( 65 )` — including title/TOC pages, e.g. Tap1 vi013 `( 274 )` vi020 `( 267 )`; endnotes/dividers/folio-only blanks never carry one): the Nôm **printed** page number in parentheses. This is ground truth, unmatchable by any internal heuristic. Nôm printed = **PDF page − 2** in all three books (verified p147/PDF147 → printed 145; p277/PDF277 → printed 275; p116/PDF116 → printed 114). (Coverage re-measured 2026-11-13 — markers on every substantive page incl. front matter; see §10/§12.4 item 5.)

**Deterministic relations** (marker = Nôm printed page; Nôm PDF = marker + 2):

| book | marker = | Nôm PDF = | vi range | verified slope |
|---|---|---|---|---|
| Tap1 | `287 − vi_PDF` | `289 − vi_PDF` | vi013…vi142 | slope −1 everywhere checked: vi013→274, vi020→267, vi021→266, vi022→265, vi025→262, vi030→257, vi060→227, vi140→147, vi142→145 |
| Tap2 | `547 − vi_PDF` | `549 − vi_PDF` | vi009…vi272 | vi009→538, vi010→537, vi257→290, vi258→289, vi272→275 |
| Tap3 | `125 − vi_PDF` | `127 − vi_PDF` | vi011…vi060 | vi021→104, vi022→103, vi031→94, vi060→65 |

Markers confirm content order too (halving the ambiguity): Tap1 vi013 `CẢM PHÒNG CHO BỔN ĐẠO / In tại Vinh Phú Đường` (printed −11−, marker (274)) ↔ Nôm PDF 276, the Nôm **title page** `禁房朱夲道` (printed 274) ✓; vi020 (TOC page, −18−, marker (267)) ↔ PDF 269 (`序`-section TOC, printed 267) ✓; vi021 (`CẤM PHÒNG…/TỰA`, −19−, marker (266)) ↔ PDF 268, the Nôm page headed `序` (printed 266) ✓. **The markers even cover the front matter that the heuristic map never saw — and the rebuilt 2026-11-12 Tap1 map now includes them (pairs vi013↔ch276…vi020↔ch269).** (revised 2026-11-12)

### Spot-verified marker reads (image + OCR cross-check)

| page | image | OCR | formula → Nôm page |
|---|---|---|---|
| Tap1 vi013 | `( 274 )` | `13: [274]` | ch276 (printed 274) ✓ |
| Tap1 vi020 | `( 267 )` | (dropped by OCR; image-verified) | ch269 ✓ |
| Tap1 vi021 | `( 266 )` | `21: [266]` | ch268 ✓ |
| Tap1 vi025 | `( 262 )` | `25: [262]` | ch264 ✓ |
| Tap1 vi030 | `( 257 )` | `30: [257]` | ch259 ✓ |
| Tap1 vi060 | `( 227 )` | OCR p58/59/60 misses; p56→[231], p57→[230], p58→[229], p62→[225] — same slope | ch229 ✓ |
| Tap1 vi140 | `( 147 )` | `140: [147]` | ch149 ✓ |
| Tap2 vi009 | `( 538 )` | (not run; image-verified) | ch540 ✓ |
| Tap2 vi010 | `( 537 )` | (not run; image-verified) | ch539 ✓ |
| Tap2 vi257 | `( 290 )` | (not run; image-verified) | ch292 ✓ |
| Tap2 vi258 | `( 289 )` | (not run; image-verified) | ch291 ✓ |
| Tap2 vi272 | `( 275 )` | `0275.json: '- 273 - BẢN CHỮ NÔM'` boundary check | ch277 ✓ |
| Tap3 vi021 | `( 104 )` | `0021.json: '-19\n( 104 )'` | ch106 (printed 104) ✓ |
| Tap3 vi022 | `( 103 )` | `0022.json: '-20\n(103)'` | ch105 (printed 103) ✓ |
| Tap3 vi031 | `( 94 )` | `0031.json: '-29 - ( 94 ) điều này…'` | ch096 (printed 94) ✓ |
| Tap3 vi060 | `( 65 )` | `0060.json: '- 58 - (65) lưỡi mà khen…'` | ch067 (printed 65) ✓ |
| Tap3 vi062 | **none** (endnotes `Chú thích`) | `0062.json` | unmapped ✓ |
| Tap3 vi063 | **none** (endnotes `Cái lẽ`) | `0063.json` | unmapped ✓ |

**OCR-extracted markers (regex `\(\s*(\d{2,4})\s*\)`, plausibility range anchored to Nôm printed ranges):** Tap1 — 69 pages hit, every value slope −1, zero repeats (e.g. p13→274…p142→145; footnote noise like p65=[222,11], p116=[171,15], p144=[10..17] all consistent with "footnotes, no marker"); Tap3 — 33–36/110 hit (the translation pages, 12…60; endnotes/blank/absent as expected), every value slope −1, zero repeats; Tap2 — 0 (only sample pages OCR'd), markers confirmed visually instead. **No true 1-2 split exists anywhere in the three books.** The 2026-11-12 repair worked from exactly this evidence channel: Tap1 `markers_used=70` (67 OCR parens + 3 MANUAL_PARENS: vi020, vi079, vi135) and Tap3 `markers_used=33`. (revised 2026-11-12)

### Corrected image maps (marker-derived)

| book | pairs | mapping | unmapped |
|---|---|---|---|
| Tap1 | **130** | `vi_k ↔ ch(289−k)`, i.e. vi013↔276, vi020↔269, vi021↔268 … vi142↔147 — **includes the front matter Nôm pages ch269–276 ↔ intro/toc QN pages vi013–vi020** | vi143 (CHÚ THÍCH endnotes, printed −141−, footnotes 1–9, no marker), vi144 (CHÚ THÍCH cont., −142−, footnotes 10–17, no marker) |
| Tap2 | **264** | `vi_k ↔ ch(549−k)`, i.e. vi009↔540 … vi272↔277 | vi273 (`CHÚ THÍCH`, no marker), vi274–275 (`- 273 - BẢN CHỮ NÔM` half-title dividers, no marker) |
| Tap3 | **50** | `vi_k ↔ ch(127−k)`, i.e. vi011↔116, vi021↔106, vi022↔105 … vi060↔067 | vi061 (blank), vi062–063 (CHÚ THÍCH endnotes, no marker) |

### Current (as of 2026-11-12) maps — marker-consistency score

`correctness.py`-style check (pair set multiset vs marker formula; a pair is correct iff 1:1 and every page matches the marker) — re-measured read-only 2026-11-12:

| book | pairs | mapping_source | consistent | wrong / inconsistent | first wrong pair |
|---|---|---|---|---|---|
| Tap1 | **127** (121×1:1 + 3×(2ch,1vi) + 3×(1ch,2vi)) | `content_dp` (rebuilt 2026-11-12T19:37, `proposed_at` 19:37:42; pre-repair backup: 124-pair heuristic text-mass partition, kept at `map_repair/image_map.pre-repair.json`) | **121/127** — *all 121 1:1 pairs parens-consistent*, including front matter vi013↔ch276 … vi020↔ch269 ✓ | **6 grouped double-absorbs**: vi031↔{257,258}, vi032+33↔{256}, vi040+41↔{249}, vi042↔{247,248}, vi132+33↔{157}, vi134↔{155,156} | n/a — every 1:1 pair consistent; the 6 non-1:1 groups violate the formula |
| Tap2 | 264 (3×(1,2)) | `heuristic text-mass partition; verify after OCR` (**UNCHANGED**, mtime 2026-11-08; no `status`/`source` fields) | **248** | **16** | `ch292 ↔ vi257+258` (markers: vi257→ch292, vi258→ch291) |
| Tap3 | **50** (all 1:1) | `content_dp` (rebuilt 2026-11-12T18:47, `proposed_at` 18:47:21; pre-repair backup: 50-pair `heuristic_mass+anchor_evidence`, 4 pairs re-assigned; `summary.json` records `old_pairs=48`, an unseen intermediate under it; the 2026-11-08 ink-mass heuristic had 48 pairs) | **50/50** | **0** | — |

Pre-repair, as first measured 2026-11-12 morning (retained for the record): Tap1 **0/124** pairs consistent (6×(2,1) absorptions, 100% wrong; first wrong `ch276+275 ↔ vi021`); Tap3 **10/50** (2×(1,2); first wrong `ch106 ↔ vi021+022`). Tap2 scored 248/264 in both eras (artifact untouched). (revised 2026-11-12)

Direction of error: was always "later QN page absorbed too early" — never reordered. Shift grew from 8 (Tap1 head) to ~2–4 (tail); Tap2's shift is exactly +1 from after ch292; Tap3's was exactly +1 from after ch106 (now eliminated). **Tap1's remaining error is localized to six grouped double-absorbs at the drift pressure points (vi031–042 and vi132–134) — not monotone — and is exactly what the parens anchors failed to pin.** (revised 2026-11-12)

Concrete repair outcomes (revised 2026-11-12): Tap1's map is now in the marker-correct *shape* for 121 of 127 pairs (front matter included, glossary 143/144 excluded) but persists 6 clustered double-absorbs; **all pairs in all books remain `status="candidate"` — nothing was promoted to `verified`.** Tap2 is byte-identical to the broken artifact. Markers are used by the tool (markers_used Tap1=70, Tap3=33) but only as pairing anchors, not as a verification oracle.

### Reading-anchor cross-checks (merged hvdic/unihan cache, `find_reading_anchors`)

Anchors agree with the markers wherever both were computed (pre-repair measurement, retained — the maps have since changed shape but not status):

- Tap3 `ch096 ↔ vi031`: **34 anchors** (map pairs it with `vi032`: 3; `vi033`: 4). Nôm text `調尼時碎保英朱特咍事𧘇拯𢧚…` decodes to `Điều này thì tôi bảo anh cho được hay, sự ấy chẳng nên, vì lời nhà kia nói thì nhà nó chẳng nghe thấy…` — literally vi031's text; the (94) marker pins it.
- Tap3 `ch116 ↔ vi011`: **44 anchors** (map agrees here).
- Tap3 `ch105 ↔ vi022`: 44 anchors (map pairs it with vi023: 7).
- Tap3 `ch067 ↔ vi060`: **7 anchors** (map pairs `vi063`, the glossary: 0; `vi062`: 2).
- Tap3 `ch068 ↔ vi059`: **43 anchors** (map pairs `vi060+vi062`: 3; vi060 alone: 3; vi062: 3; vi063: 2). Marker: vi059 = 66 ⇒ ch068 ✓.
- Tap1 `ch232 ↔ vi057`: **57 anchors** (full neighbor vector: vi054:6, vi055:6, vi056:13, **vi057:57**, vi058:9, vi059:8, vi060:5 — the map assigns vi060, the win is unambiguous). Marker check: vi057 → 287−57 = 230 → ch232 (printed 232) ✓.
- Tap1 `ch233 ↔ vi056`: **44 anchors** (vi057: 14, others ≤9; map assigns vi057). Marker: vi056→231→ch233 ✓.
- Tap1 `ch234 ↔ vi055`: **31 anchors** (vi056: 4, vi057: 6, vi054:3, vi058:2; map assigns vi058). Marker: vi055→232→ch234 ✓.

**Own-pair-wins rate** (assigned vi beats vi±1/±2 on anchors): Tap1 **26/124**, Tap3 **11/50** — measured pre-repair; this metric was not recomputed after the 2026-11-12 re-pairing (the rebuilt Tap3 map's 50/50 parens-consistency does not imply reading-anchor coverage; the lexicon situation is unchanged — see M1). The pre-repair maps were not merely weak — they were wrong. (revised 2026-11-12)

### Anchor coverage on the *correct* map (Tap3, `rescore3.py`)

Every pair gets reading evidence (50/50), but coverage is low: min 0.061 / **median 0.201** / max 0.636; only **1/50** pair (ch067↔vi060, 0.636) reaches the pipeline's `verified_min_coverage = 0.5` bar. **The 0.5 coverage bar is unreachable for this corpus even with hvdic+unihan wired in** — most correct pairs sit at 0.1–0.3. And the (pre-repair) maps never even reach that test: the lexicon passed to `score_pairs_with_anchors` has **zero trusted entries in all three books**, and `build_image_map` never passes a dictionary (see §5, M1/M2), so `known == 0` for every pair → all `candidate`. **This remains true of the rebuilt maps** — `map_repair.py`'s `pair_score` uses the same hvdic cache for re-pairing but does not promote anything to `verified`; the lexicon situation (M1) is untouched. (revised 2026-11-12)

---

## 4. Verified classifier facts (Stage 2)

**Nôm block detection works.** All three runs found the blocks from image evidence (`nom_run_source: image_evidence`, no config-hint fallback), matching the team's visually verified boundaries exactly:

| book | Nôm run (PDF) | source |
|---|---|---|
| Tap1 | [147, 276] | image_evidence |
| Tap2 | [277, 540] | image_evidence |
| Tap3 | [67, 116] | image_evidence |

- **Column/ink heuristic holds up across the expected failure modes.** All 25 Tap2 rotated scans (`rotation` ∈ {90, 270}, native 564×800) score `nom_likely=True` (column_std 0.098–0.145, 23–31 peaks) and sit inside the Nôm block — correct. **No 2-page spreads exist** in these books; the "rotated scans will defeat the column heuristic" hypothesis is disproven (verified visually: p277 clean printed page; p287 single Nôm page printed −285−).
- **Every page inside each Nôm block is `nom_likely=True`** (checked page-by-page: zero exceptions). Outside the block, only page 1 of each book trips the heuristic (cstd 0.087/0.094, peaks 16–22) — it is correctly overridden by forced `cover` (`layout.py:306`).
- **QN pages are never allowed as gaps** in `_longest_nom_run` (layout.py:221–264; non-blank non-nom pages `break`; blank gaps ≤3 allowed). The `min_length=15`, `density≥0.75` guards are satisfied (runs are 124–264 pages at >0.99 density).
- **Blank pages are correctly excluded from mapping** (e.g. Tap3 vi061 ink=0.0014, blank → skipped in the map; the DP/missing-page sweep works; no duplicates anywhere; each image used ≤once per side — verified for all three pre-repair maps and re-verified for the two rebuilt maps). Tap3 p61 blank ✓; Tap1 143,144 excluded as `excluded_pages` in the rebuilt map; Tap1 277–282 (pre-existing misc) unmapped; 145 (pre-existing misc) unmapped — unchanged. (revised 2026-11-12)
- **Back-matter TOC override clobbers blanks** — `classify_book` applies the override *after* the `blank_likely` branch, unconditionally (`layout.py:333–334`): Tap1 p281, p282 (blank_likely) and Tap2 p550 are relabeled `back_matter_toc`/`toc` instead of `blank`. Any post-block `nom_likely` page is also silently swallowed (Tap2 **p549**, column_std 0.079, peaks 23, is TOC) with no review flag. (Unchanged by the 2026-11-12 change-set.)
- **`toc_likely` fires on essentially all QN prose**: Tap2 pages 9–274 (266/267 vi pages), Tap1 pages 7–144 (+277–280), Tap3 pages 7–63 — plain body-text pages match `ink≥0.015, row_peaks≥18, column_std<0.070, col_peaks≥12, not nom_likely`. It is useless as a discriminator; it happened not to mislabel anything only because translation pages never enter the `toc` branch. If any front-matter prose page existed, it would be silently relabeled `toc`.
- **Single-line divider/endnote pages are not detected** and were classified `vi` — the root cause of the forced absorptions (M3): Tap1 vi143/144; Tap2 vi273 (`CHÚ THÍCH`, ink 0.0658), vi274 (0.0513), vi275 (`- 273 - BẢN CHỮ NÔM`, ink 0.0115); Tap3 vi062/063 (`Chú thích`). None are `blank_likely`/`nom_likely`/`toc_likely`; none contain `( N )` markers. In the rebuilt maps, these pages are excluded via `excluded_pages` (Tap1: 143/144; Tap3: 62/063) rather than via classifier fix. (revised 2026-11-12)
- **Classification is recomputed, not cached.** `classify_book` deterministically recomputes Otsu/projections every run and unconditionally overwrites state + `classification.json`; `force` parameter is accepted but ignored. Deterministic (no RNG/time), but not incremental. **2026-11-12 change-set addition:** a `BIN_OVERRIDE_*` block at the end of the per-page section logic (post-insertion lines ~339–348; added after line 336 — it shifts no cited line in this document, all cites ≤334): pages in `book.inventory_vi` → `section=translation, folder=vi` + `BIN_OVERRIDE_VI`; pages in `book.inventory_misc` → `section=other, folder=misc` + `BIN_OVERRIDE_MISC`; never overrides blank/ch/nom pages (the guard is on `folder`, not `section` — the cover p1, `folder=misc`, **can** be re-binned if listed in `inventory_misc`; Tap1's includes 001, so a re-run would flip p1 from cover to other). **ZERO `BIN_OVERRIDE_*` entries exist in `pages.review_flags`** (probed read-only 2026-11-12; re-probed 2026-11-13 — still zero) — the path has never been exercised in the delivered state. The re-bin was instead applied by direct DB surgery (backup `data/state.sqlite3.bak-2026-11-12-rebin-fix`, 2026-11-12 19:36:40, 1,015,808 bytes). **Attribution correction (2026-11-13):** the status wipe is **not** caused by the override block — `page.status = "classified"` is assigned unconditionally to **every** page at `layout.py:354` on each run, so any re-run of `classify_book` erases human-repaired statuses (including the re-bin), override block or not. (revised 2026-11-12 → correction 2026-11-13)
- **`classification.json` is stale for both live books and does not reflect the delivered DB.** Tap1's `classification.json` (mtime 2026-11-08; prints `blank6/ch130/intro4/misc2/toc16/vi124`) predates the re-bin and is wrong on the delivered state (re-binned DB: `vi=013–142` (130), `misc={001,005,007,008,009,010,011,143,144,145,277,278,279,280,281,282}` (16), `ch=130`, `blank=6`). Tap3's `classification.json` (mtime 2026-11-12T13:24Z; prints `intro4/toc4/misc2/vi52`) is likewise stale (delivered DB: `vi=011–060` (50), `misc={001,002,003,005,007,008,009,062,063,064,117,118}` (12), `ch=50`, `blank=6`). Boundaries (Nôm runs [147,276]/[277,540]/[67,116]) are fine in both files; the folder tallies are what's wrong. Nothing downstream detects this staleness. (revised 2026-11-12)
- **Nôm-block boundaries are NOT corrupted by the classifier** — the split ch/vi assignment is the one trustworthy stage. The errors are all downstream of boundary selection (back-matter swallow, translation-folder inclusion of endnotes, map construction).

---

## 5. Findings (severity-ranked, with file:line)

### BLOCKER

**B1 — Image maps were systematically wrong (all three books); the two live books have been re-paired but remain `candidate` — severity REVISED (still a BLOCKER for packaging).** `t1_map.py:214–281` (`align_page_groups` DP) + `314–433` (`build_image_map`) — both unchanged; the 2026-11-12 repair ran as a separate pass (`map_repair.solve` + `tools/repair_image_map.py`) that *replaced the maps wholesale* with content-DP re-pairing anchored on OCR parens markers. Marker-verified: pre-repair Tap1 **0/124 | Tap2 248/264 | Tap3 10/50** (see §3; Tap3's pre-repair measurement was on the intermediate heuristic+anchor 50-pair map, not the 2026-11-08 ink-mass original, 48 pairs). Post-repair (re-measured 2026-11-12): Tap1 **121/127 parens-consistent** (all 121 1:1 pairs consistent — the 6 remaining failures are grouped double-absorbs), Tap3 **50/50**, Tap2 **248/264 (unchanged)**. Every pair is still `candidate` (`mapping_source="content_dp"`; Tap2 still legacy heuristic, no `status` fields). Evidence: markers (images + OCR), printed page numbers, reading anchors — the repaired maps now agree with the first two; nothing was promoted to `verified`, so no verification consumer exists for them yet. (revised 2026-11-12)

**B2 — QN front-matter pages with markers were excluded, collapsing the align stream into a monster segment. (FIXED in place for Tap1 by the 2026-11-12 repair; retained for the record.)** `build_image_map` pairs only `folder="vi"` pages, but markers print also on intro/toc QN pages (vi013–019 have markers 274…268; vi020=267 ✓). The QN stream for the align stage therefore **started at vi021** while the Nôm stream started at ch276; the preface region (ch259–276) matched only against vi021/022 (TỰA vs 序, ~9 Nôm pages vs 2 QN pages, ~4.5:1 compression) → `data/align/T1_CamPhong_Tap1/...csv` row `T1_Cấm Phòng Cho Bổn Đạo (Tập 1).268.4` carried **1941 Nôm chars vs 7220 QN chars** of self-repeating text, and pages 259–267 were completely absent from the CSV. **Post-repair (2026-11-12, CSV rebuilt, 823 rows): the monster `.268.4` row is gone (one legitimate `.268.4` sentence_id remains for ch_page 268 — 37 vs 156 chars, text_diff with 2 spans; the pre-repair backup `_pre-repair-2026-11-12/…CSV` retains the 1941/7220 monster); Nôm PDF pages 259, 260, 261, 262, 264, 265, 266, 267 emit rows again (6/10/4/9/3/4/4/5) — 8 of the 9 previously missing Nôm pages re-appeared.** ch263 still yields zero rows (flagged; see §10 #18). The rebuilt map pairs vi013↔ch276 … vi020↔ch269 (8 front-matter pairs), so this can no longer recur while the current artifact is in place — but nothing prevents a future re-`stage_map` run from silently regressing it (R4 unexecuted). (revised 2026-11-12)

**B3 — The packaged submission ships the maps with no semantic validation.** `package.py` does **not** copy `image_map.json` verbatim: it round-trips `load_image_map` → `to_dict()` into `<Book>_image_map.json` (HEAD cites 234–240; the file then gained +58 lines in the 2026-11-13 verify-A hardening — state backup, pages.jsonl regen, `_updated.pdf` gate — so current cites are ~246–252 / ~449–461), which (a) **drops the entire `meta` block** (`mapping_source`, `markers_used`, `vi_page_count`, verified/candidate counts — everything the report leans on for provenance), and (b) silently re-defaults statuses (missing→`candidate`, unknown→`unresolved`, no warning). Package-time validation calls `validate_image_map` **without** `ch_names`/`vi_names`, so the unknown-name branch is not even exercised — only duplicates/empty pairs can fail; unknown names are NOT checked; **no coverage, ordering, real name-check, consistency, or marker checks**. (Unchanged in substance by the 2026-11-12 change-set and the 2026-11-13 hardening — the map-blocks were moved, not hardened.) Any instructor-side check of `ch/ ↔ vi/` equivalence against the printed markers fails immediately on Tap2 (16 wrong pairs) and Tap1 (the 6 grouped double-absorbs); Tap3 now passes such a check (50/50) but still ships as unadjudicated `candidate` pairs — provenance is consistent-by-marker yet unverified by construction. (revised 2026-11-12 → correction 2026-11-13)

### MAJOR

**M1 — Anchor verification is inoperative by construction: 0 verified pairs forever.** Three causes compound at `t1_map.py:344–349` and `dictionary/book_lexicon.py:488–494`: (1) all three book lexicons have **zero trusted readings** (Tap1: `learned_pairs=77`, 47 chars quarantine; Tap2: 244/104; Tap3: 22388/586 — 100% legacy-quarantine), so `known==0` → all `candidate`, `confidence=None`; (2) `build_image_map` never passes `dictionary=` — the only dictionary available offline (`data/dictionary/char_readings.json`, 26,700 chars) is never given to the scorer (the `dictionary=` kwarg exists, `score_pairs_with_anchors` accepts it, but the only production call site omits it); (3) even with the dictionary, the 0.5 coverage bar is unreachable: on the *correct* map, coverage min/median/max = 0.061/**0.201**/0.636, **1/50** pair passes. On the pre-repair maps, confidences were 0.0–0.275 everywhere. `status` distribution today (revised 2026-11-12): Tap1 **127 candidate** (explicit `content_dp` labels), Tap2 **264 candidate** (no status stored — stale format), Tap3 **50 candidate**; **0 verified, 0 unresolved, 0 manual — everywhere.** The repair's `markers_used` (Tap1 70, Tap3 33) demonstrate partial marker capture but did not change the scoring path — `map_repair.py` never emits `status=verified` either. (t1_map.py itself unchanged.)

**M2 — Reading-evidence paths are inconsistent, and the marker channel is dead in code.**
- `anchors.py:37–38` (`normalize_reading`) does exact NFC+casefold only; `charalign.py:53–66` (`fold()`; lines 60–66 are its body) folds `d/gi→d`, `đ→d`, `y→i`. (`norm_reading`, defined at `dictionary/readings.py:45–46`, is NFC+casefold only — identical to `normalize_reading`.) The map-side matcher is strictly weaker than its sibling. (cite fixed 2026-11-13)
- `charalign.QN_HEADER_RE` (`charalign.py:42`) = `^\s*-\s*\d+\s*-\s*(?:\(\s*(\d+)\s*\))?` requires a **trailing dash**; vintern OCR emits `-19\n( 104 )` → no match → `qn_page_markers` = `{}` in `data/diagnostics/book3_charalign/stats.json` (verified; `qn_page_markers` is written at `charalign.py:747` and read by nothing — grep-confirmed 2026-11-13; `charstream.`/`map_repair.` bypass the broken regex entirely, the repair tool uses its own `MARKER_RE` on raw OCR). Fix: `^\s*-\s*\d{1,4}\s*[-–—]?\s*\(\s*(\d{2,4})\s*\)` — **validated empirically 2026-11-13** (matches `-19\n( 104 )`, `-20\n(103)`, `-29 - ( 94 ) x`, `- 58 - (65) x`, `-10 - ( 113 ) x`, `-30 - (93) x`; rejects non-dash-leading and `- 2010 - (5)`). The marker is printed in every substantive QN page (incl. title/TOC pages — e.g. Tap1 vi013/vi020 carry markers; **endnotes/dividers/folio-only blanks never do**) but **never reaches any verification consumer**. (Unchanged by the 2026-11-12 change-set — `charstream.py` replaces cosegmentation for `segmentation == "charalign"` books (`align.py:575–604`), it does not feed cosegmentation, and it emits no markers.)
- `qn vintern` drops the header for most pages (Tap1 markers visible in 69/144 pages' OCR — all of vi013–19 present; Tap2 0 (only sample pages); Tap3 33–36/110; Tap1 vi020 and Tap1 vi060 and Tap3 vi011 and Tap2 vi009 all image-verified markers but OCR-dropped — 4 of 18 sampled body pages) and `clean.py` strips even those from `text` (`PAGE_MARK_REMOVED` flags — e.g. Tap1 vi021 OCR line is `- 19 - (266)` but clean `text` starts `CẤM PHÒNG…`). **Correction (re-measured 2026-11-13):** the marker does **not** vanish from `data/clean/*/*.json` — it survives unstructured in `dropped_lines` (101/104 files carrying `PAGE_MARK_REMOVED`: Tap1 vi021 → `dropped_lines ["- 19 - (266)"]`, Tap3 vi021 → `["-19\n( 104 )"]`, vi031 → `["-29 - ( 94 )"]`, vi060 → `["- 58 - (65)"]`); no `marker` *field* exists (`CleanedPage.to_dict()` emits only book_id/page_no/image_name/script/text/lines/flags/dropped_lines/replacements), and nothing downstream consumes `dropped_lines` as a marker. So: the one deterministic verification signal is **recoverable but consumed by nobody**. (Claim revised 2026-11-13.)

**M3 — Classifier has no class for the pages that break the map.** Endnote/divider/half-title pages (`CHÚ THÍCH`, `BẢN CHỮ NÔM`, `BẢN QUỐC NGỮ`) are single-line-ish pages without markers; they got `folder=vi`, so the map must absorb them, forcing the `(1,2)` absorptions that shifted Tap2 (vi258 onward off by one vi page; 16 pairs wrong; vi273/274/275 force-mapped) and Tap3 (vi062/063; 40 pairs wrong). Same class of error at Tap1's head: the DP absorbed 8 extra Nôm pages into the first pairs (`276,275 ↔ vi021` …), shifting everything. The mass DP (`_mass` = ink fraction, `_group_cost` ratio+penalty, t1_map.py:57–101) **cannot align this corpus**: cumulative ink-mass drift makes later 1:1 pairings increasingly expensive, and the 0.35 penalty for one (1,2) pair is dwarfed by the accumulated ratio cost — the split point (Tap2: between vi257 and vi258; Tap3: between vi106/ch106 and vi107) is wherever drift crosses the threshold, not where the book actually splits. (Verified: no true (1,2) exists — marker slope is −1 everywhere.) **Post-repair, the rebuilt Tap1 map still exhibits six grouped double-absorbs at exactly these pressure points (vi031↔{257,258}, vi032+33↔{256}, vi040+41↔{249}, vi042↔{247,248}, vi132+33↔{157}, vi134↔{155,156}) — the mass/ratio cost model was not replaced, only re-run with content anchors.** (revised 2026-11-12)

**M4 — `validate_image_map` cannot reject a wrong map, and partial manual maps pass silently.** `t1_map.py:284–311` checks only: within-pair duplicates, cross-pair duplicates, empty pair, unknown images (when name-sets passed). Missing: **coverage** (every ch/vi/missing_* page must be in exactly one pair), **monotonicity** (ch decreasing, vi increasing, pair-index consistency), **marker cross-check** (PDF = marker+2), **order-consistency of the file**. `image_map.manual.json` **can fully override** (parse_manual_pairs → `status=manual`, skips scoring; bad names/duplicates fail loudly) but a manual file omitting even one page validates clean — pages simply vanish from the corpus with no error. Sorting bug: empty-vi (`missing_ch`) pairs get `pair_order` default `1e9` (t1_map.py:380–390), appended at the end of the file instead of their reading position (latent — no `missing_*` folders currently). (Unchanged by the 2026-11-12 change-set; the rebuilt maps validate only because `build_image_map` was not re-run — they were swapped in by the repair tool.)

**M5 — Map-confidence is decorative; gates all fail.** `evaluation/*/metrics.json` — re-measured 2026-11-12, before/after the repair (before/after archives: `metrics.20261112T120924Z.json` (Tap1) / `metrics.20261112T120355Z.json` (Tap3); Tap1 live = mtime 2026-11-12, Tap3 live = mtime 2026-11-12, Tap2 = 2026-11-08):
- Tap1: **before** 727 rows; `scored_rows=8`; `total_nom_chars=27976`; `null_rows=124` (17.1%); `coverage_ratio=0.011`; `unverified_ratio=0.817`; `similarity=87.36` (8 rows); issues `INSUFFICIENT_COVERAGE`/`UNVERIFIED_RATIO_HIGH`/`EXCESSIVE_NULL_ROWS`/`SIMILARITY_BELOW_GATE` (all four) — `passed: false`. **After (revised 2026-11-12):** `total_rows=823`; non-null 822; `scored_rows=381`; `denominator=7065`; `similarity=89.9646` (<95, still failing); `coverage_ratio=0.4629` (<0.9); `unverified_ratio=0.5358` (441 rows); `null_rows=0` (**EXCESSIVE_NULL_ROWS GONE**; `null_ratio=0.0`, `yellow_ratio=0.0`); `red_mismatch_chars=709`; warning `UNVERIFIED_DIFFERENT_ROWS:136`; `verified_match_rows=136` / `verified_difference_rows=245`; 1 unmatched row (skip_qn — see B2). Issues: `INSUFFICIENT_COVERAGE:0.4629<0.9`, `UNVERIFIED_RATIO_HIGH:0.5358>0.05`, `SIMILARITY_BELOW_GATE:89.9646<95.0` — `passed: false`. (`total_nom_chars=27976` unchanged.)
- Tap3: **before** 341 rows; `scored_rows=26`; `null_rows=98` (28.7%); `coverage_ratio=0.0762`; `unverified_ratio=0.6364`; `similarity=85.87`; same four issues — `passed: false`. **After (revised 2026-11-12):** `total_rows=380`; `scored_rows=228`; `denominator=3274`; `similarity=93.7385` (<95, still failing); `coverage_ratio=0.6000`; `unverified_ratio=0.4000` (152 rows); `null_rows=0`; `red_mismatch_chars=205`; warning `UNVERIFIED_DIFFERENT_ROWS:125`; `verified_match_rows=125` / `verified_difference_rows=103`; 0 unmatched rows. Issues: `INSUFFICIENT_COVERAGE:0.6000<0.9`, `UNVERIFIED_RATIO_HIGH:0.4000>0.05`, `SIMILARITY_BELOW_GATE:93.7385<95.0` — `passed: false`.
- Tap2: unchanged — 8 rows (sample-only OCR); `similarity=null`; `EMPTY_DENOMINATOR`; `null_ratio=1.0`; `passed: false`.
- **All three books FAIL the project quality gate (minimum_coverage=0.9, max_unverified_ratio=0.05, minimum_similarity=95.0, `configs/project.yaml:37–47`).** The repair *raised* similarity (87.36→89.96; 85.87→93.74) and *eliminated* null rows and `EXCESSIVE_NULL_ROWS`, but coverage/unverified remain far over gate in both live books — and the live books now **additionally fail** `SIMILARITY_BELOW_GATE`. **The 2026-11-12 `docs/decisions.md` entry ("gate status unchanged: … 0.7% gap to 95% on Tap1 and 1.3% on Tap3 …") is correct about coverage/unverified, omits `SIMILARITY_BELOW_GATE` for both live books, and its "0.7% gap to 95% on Tap1" is unreconcilable with the measured 89.9646 (gap 5.04; Tap3's gap 1.26 ≈ its "1.3%", which is consistent).** The failures are the gate doing its job; nothing to self-affirm from these metrics. (revised 2026-11-12)
- **Key-format caveats (re-measured 2026-11-13):** `metrics.json` carries **no `unverified_ratio` key** — the 0.5358 / 0.4000 figures above are derived (`unverified_rows/total_rows` = 441/823 = 0.5358; 152/380 = 0.4000) and match the `UNVERIFIED_RATIO_HIGH` issue strings verbatim. All `UNVERIFIED_RATIO_HIGH` counts (441/152) and flag values elsewhere in this report are from the issue strings, not from a stored key. Tap2 additionally emits warning `NULL_ROW_RATIO_HIGH:1.0000` (not quoted above; trivial). Tap1/Tap3 also store `structural_confidence_mean`, `semantic_evidence_rows`, and `evidence_insufficient_rows` (= 233 / 74). The `docs/decisions.md` gate entry is confirmed verbatim against line 23 of the file: it omits `SIMILARITY_BELOW_GATE` for both live books and states "0.7% gap to 95% on Tap1" — irreconcilable with measured 89.9646 (gap 5.04); "1.3% on Tap3" is consistent (1.26). (revised 2026-11-13)

**M6 (revised 2026-11-12) — Tap1/Tap3 maps are rebuilt but format-honest and unverified; Tap2 is still stale; `classification.json` is stale for both live books.** At first writing: Tap1/Tap2 maps were stale 2026-11-08 artifacts (`mapping_source: "heuristic text-mass partition; verify after OCR"`, no `status`/`verified_pairs` meta — `load_image_map` silently defaults missing status → `candidate`, t1_map.py:443–445, no warning) and Tap3's rebuilt map was "equally wrong, now with honest labels". Now: **Tap1** map rebuilt 2026-11-12T19:37 (mtime 19:37, `proposed_at` 19:37:42), 127 pairs (121×1:1 + 6 grouped double-absorbs), `mapping_source=content_dp`, all `status=candidate`, `markers_used=70` (67 OCR parens + 3 MANUAL_PARENS: vi020, vi079, vi135), `marker_issues=[]`, `excluded_pages=[143,144]`, `meta vi_page_count` **STALE (124 vs actual 130 distinct vi)**. **Tap3** map rebuilt 2026-11-12T18:47 (mtime 18:47, `proposed_at` 18:47:21), 50 pairs all 1:1, all `status=candidate`, `markers_used=33`, `marker_issues` recorded: `vi038 (13)+2=15 not in ch inventory`, `vi049 (8)+2=10 not in ch inventory` (a third one at vi036, (10)+2=12, exists per the current tool but is **not recorded in the artifact**), 4 changed assignments vs heuristic (mean_recall 0.9476→0.9461), `excluded_pages=[62,63]`, `meta vi_page_count` **STALE (52 vs 50)**. Pre-repair backups kept at `map_repair/image_map.pre-repair.json` — Tap1: 124 pairs, heuristic text-mass partition, no status; **Tap3: 50 pairs `heuristic_mass+anchor_evidence` candidate — this is NOT the ink-mass original; `map_repair/summary.json`'s `old_pairs=48` refers to an unseen intermediate map; Tap3's "before" in this report's ground truth is the 2026-11-08 ink-mass heuristic (48 pairs).** Tap1's `map_repair/image_map.proposed.json` (19:51 propose-only run) differs from the applied map only in `proposed_at` — benign. **Tap2 unchanged: mtime 2026-11-08, 264 pairs, no `status`/`source` fields, 16/264 shifted from ch292, 248/264 marker-consistent, map format stale.** `stage_map` still runs only on demand; no staleness check anywhere; the `layout.py` `BIN_OVERRIDE_*` path (added 2026-11-12, never exercised in the delivered state) would additionally wipe `status→classified` on re-run. `classification.json` likewise persists stale for both live books (see §4). (revised 2026-11-12)

### MINOR

- **N1.** Config drift: `configs/alignment.yaml` `max_group: 4`, `max_nm_group: 2` are never read **by the T1 page-map DP** — `align_page_groups(..., max_group=3)` default (t1_map.py:218) is what actually runs on the map path. (**Codebase-wide grep refutes the unqualified claim:** the same keys ARE read live by the sentence DP — `align.py:91–92` (`_as_config` → `raw.get("max_group", 4)` / `raw.get("max_nm_group", 2)`) and enforced at `align.py:419–425` — so they are live config keys, dead only on the image-map path.) `expected_syllables_per_nom_char: 1.0` reduces `ratio_guard` to exactly 0.0 (t1_map.py:100); `many_to_many_penalty` is dead code because n-m groups are `continue`d out of the map DP (t1_map.py:250–251). Small n-m is allowed by the guideline; excluding it is fine *given markers prove zero n-m exists*, but should be via `max_nm_group`, not hardcoded. (revised 2026-11-12 → correction 2026-11-13)
- **N2.** `classify_book(force=...)` accepted, ignored (layout.py:272; `stage_classify` passes it, orchestrator.py:102). Recompute is deterministic but unconditional; `state.update_page` per page rewrites every run. (Unchanged.)
- **N3.** Pair dicts exceed the guideline's `{ch, vi, note?}` (`confidence`, `source`, `status` extras); `mapping_source` is free-form (no constant) — now `content_dp` in Tap1/Tap3 (still free-form), absent in Tap2; Tap3 meta carries `verified_pairs=0/candidate_pairs=50/unresolved_pairs=0/manual_pairs=0`, Tap1 meta lacks verified-counts entirely (and has stale `vi_page_count`); nothing validates meta. (revised 2026-11-12)
- **N4.** `load_image_map` unknown status → `unresolved` (good) but missing status → `candidate` silently (stale maps). **Applies to Tap2 only now — Tap1/Tap3 rebuilt maps carry explicit `status=candidate` (and note/source) per pair.** (revised 2026-11-12)
- **N5.** `cli.py:187–188` globs `*image_map.json`, takes `maps[0]` — ambiguous if book-name map and `image_map.json` coexist; no warning.
- **N6.** Tap2 align output is an 8-row smoke artifact (6 sample pages OCR'd: 0009/0142/0275/0277/0409/0540) — nothing evaluable; Tap1's 823 rows (was 727) exist; pipeline coverage between Tap1 and Tap2 is now ~103× (was 300×). (revised 2026-11-12)
- **N7.** `anchor_coverage` (anchors.py:184–193) is dead code; `MAX_ANCHOR_GAP_TOKENS=120` used only by cosegment.
- **N8.** Cover==page 1 forced (p1 `nom_likely=True` in all three books: cstd 0.087/0.094/0.109) — forced `cover` (layout.py:306–308) must stay that way; worth a test.

### INFO / verified-good

- **I1.** `_longest_nom_run` finds the blocks from image evidence for all three books (source=image_evidence), matching the team's visually-verified boundaries; QN-never-a-gap enforced (layout.py:247–251); blank gaps ≤3 allowed and never miscount boundary (Tap1 p146 blank between blocks, Tap3 p61/p65/p66 blanks inside ranges — handled).
- **I2.** Nôm block pages *inside* each run are 100% `nom_likely=True` (zero exceptions checked page-by-page); outside pages never `nom_likely` except p1 (all books, overridden to cover) and Tap2 p549 (swallowed by the back-matter override, §4; M3-class).
- **I3.** Anchor machinery is correct: bidirectional uniqueness (`find_reading_anchors`, anchors.py:138–181) + bisector-based strict-LIS with parent reconstruction — reviewed and sound; both-direction uniqueness requirement prevents repeated-reading/multiple-candidates anchors (documented, tested in `tests/test_image_map_evidence.py` and `tests/test_cosegment_anchors.py` — all pass).
- **I4.** Images map to images consistently (NFC names, decreasing ch / increasing vi order in file, DP partition back-pointers reversal correct, Tap3 vi061 blank handled, missing_* sweep logic exists). The rebuilt maps preserve this (all pairs NFC 1:1/grouped, exclusions recorded in `excluded_pages`). (revised 2026-11-12)
- **I5.** Tests green: **291 passed** (2026-11-13; includes 2 new charstream + 3 new map_repair already counted; +9 from the 2026-11-13 verify-A hardening, `tests/test_verify_a_hardening.py`; this document said 282 at 2026-11-12 and 277 at first writing). Still **no test pins any real-book map** — the systematic shift was invisible to CI, and the new `test_map_repair.py` only verifies mechanics on synthetic stubs; CI (`.github/workflows/ci.yml`) additionally does **not** trigger on pushes to `feat/map-repair-align` (only `dev`/`main`/`repair/**` + PRs, py3.11/3.13). (revised 2026-11-12 → 2026-11-13)
- **I6.** Map direction-of-error was monotone pre-repair (absorption only, never permutation); post-repair, Tap1's residual error is localized to six grouped double-absorbs (vi031–042, vi132–134 — still absorption-style, not permutations), Tap3 is clean re: 1:1+markers, Tap2 is unchanged (monotone +1 drift from ch292). Markers/anchors fully recover the truth (see §6 fix plan; partially executed). (revised 2026-11-12)

### Cross-path consistency (charalign ≡ align)

| | `align` (orchestrator → align.py) | `charalign` (CLI → charalign.py) |
|---|---|---|
| Pairs source | same rebuilt `image_map.json` (Tap1/Tap3 `content_dp` candidate; Tap2 legacy) (`orchestrator._load_pairs`) | same file; `read_image_map` (charalign.py:611–615) **ignores `status` entirely** |
| How pairs are used | stream membership (QN pages absent from pairs are **not in the streams at all**) + reading order + page attribution | band anchors at pair starts (charalign.py:644–647) |
| Measured effect of pairs (pre→post repair, revised 2026-11-12) | **Pre-repair B2 corruption**: lost vi013–020; monster row `.268.4`; 9 Nôm pages missing. **Post-repair: corruption resolved for Tap1** — front matter re-enters streams; `.268.4` gone; ch259–267 present except ch263 (zero rows); 823 rows; single UNMATCHED_QN row (`.100.jpg`, text_diff `null`, warning `QN_SENTENCE_NO_NOM:529`); stream order non-monotone at that skip row (between two `.189.jpg` rows). Tap2 path unchanged (8-row smoke). Tap3 path rebuilt (380 rows; monotone ✓). | **None measured** (unchanged): three-way run on Book 3 (old/no/correct pairs) → identical stats (7261/360/25/330 pairs; similarity 87.23%; 435 rows; anchors 50/0/50 with band=400 ≫ shift) — the repaired pairs are far closer to "correct" than the pre-repair ones, so still insensitive |
| Status consulted? | COSEGMENTED_ANCHORED/UNANCHORED counts anchors but never gates on `verified` | never |
| Marker usage | none anywhere (still — 2026-11-12 change-set does not add one) | parsed (`QN_HEADER_RE`) but regex broken → `qn_page_markers={}`; never used for alignment |

Both paths now consume the *rebuilt* pairs; `align`'s stream-membership failure (B2) is fixed for Tap1 by the 2026-11-12 rebuild; Tap3 likewise repaired and monotone; `charalign` remains insensitive (band absorbs the residual uncertainty) but still ships the same artifact unchecked — and both paths still treat every pair as unadjudicated `candidate`. (revised 2026-11-12)

---

## 6. The marker-driven fix plan (R1–R6)

### R1 (BLOCKER, ~1–2 days) — Rebuild every T1 image map from the printed `( N )` markers

**Status (revised 2026-11-12): PARTIALLY EXECUTED by the collaborator as a content-DP re-pairing pass (`map_repair.py`), not as specified here — pair sources are `content_dp` pairs anchored on OCR parens markers (plus 3 MANUAL_PARENS), maps carry `status=candidate` (not `verified`), `mapping_source` is `content_dp` (not `printed_marker`), `confidence` is absent (not 1.0), and nothing was promoted. R1's actual expected outputs were *approximated* (Tap1 front matter included; Tap3 50×1:1; exclusions recorded) but the *outputs-as-specified* (verified, confidence 1.0, marker-checkable) were not delivered. Tap2 untouched.**

Step 1 — marker extraction:
- Cheap pass: the existing vintern OCR already contains markers for many pages. Extract with regex `\(\s*(\d{2,4})\s*\)` in the plausible Nôm-printed range (Tap1: 145–274; Tap2: 275–538; Tap3: 65–114; Nôm range PDF±2). Coverage today: Tap1 69/144 pages, Tap3 ~36/110, Tap2 0 (only sample pages). (The repair used this channel: Tap1 `markers_used=70` = 67 OCR parens + 3 MANUAL_PARENS (vi020, vi079, vi135); Tap3 `markers_used=33`.) (revised 2026-11-12)
- Completion pass: for missing pages, OCR **only a ~120×50px top-right crop** of each QN page with a digits-only prompt (vintern or paddle; no Kim API), or do one manual read (~30 min per book). The marker is printed large and clear; extraction is deterministic.
- The marker regex must tolerate the optional trailing dash and newlines: `^\s*-\s*\d{1,4}\s*[-–—]?\s*\(\s*(\d{2,4})\s*\)`.

Step 2 — write the maps (choose one):
- (a) emit `image_map.manual.json` (status `manual`, confidence 1.0) — one explicit human adjudication point, or
- (b) extend `build_image_map` to a new source `marker` (status `verified`, confidence 1.0, deterministic; recommended for transparency).

Expected outputs — exact pairs (as specified at first writing; what the repair actually delivered is annotated):
- **Tap1: 130 pairs 1:1** — `vi013↔ch276 … vi142↔ch147` (`vi_k ↔ ch 289-k`); vi143 (CHÚ THÍCH, no marker, footnotes 1–9) and vi144 (CHÚ THÍCH cont., footnotes 10–17) explicitly unmapped. **Delivered (revised 2026-11-12): 127 pairs — 121×1:1 + 6 grouped double-absorbs (vi031↔{257,258}, vi032+33↔{256}, vi040+41↔{249}, vi042↔{247,248}, vi132+33↔{157}, vi134↔{155,156}); front matter IS paired (vi013↔ch276…vi020↔ch269 ✓); 143/144 excluded ✓; 145 (pre-existing misc) and 277–282 unmapped ✓; all 1:1 pairs parens-consistent ✓; status all `candidate` ✗; not verified ✗.**
- **Tap2: 264 pairs 1:1** — `vi009↔ch540 … vi272↔ch277` (`vi_k ↔ ch 549-k`); vi273/274/275 unmapped. **Delivered: nothing — map byte-identical to 2026-11-08.**
- **Tap3: 50 pairs 1:1** — `vi011↔ch116 … vi060↔ch067` (`vi_k ↔ ch 127-k`); vi061 (blank), vi062/063 (endnotes) unmapped. **Delivered: 50 pairs all 1:1 ✓, 50/50 parens-consistent ✓, vi062/063 excluded ✓, p61 blank ✓, but `status=candidate` ✗ and 4 changed assignments vs the heuristic (mean_recall 0.9476→0.9461) — net quality wash, not a fix.**
- `mapping_source: printed_marker`, `status: verified`, `confidence: 1.0`, `ch` decreasing / `vi` increasing order. **Delivered `content_dp` / `candidate` / no confidence.**

Step 3 — verify: re-run `stage_map` → clean → `stage_align` → charalign → evaluate. Expected: Tap1 monster row 268.4 disappears (front matter re-enters streams), 9 Nôm pages reappear as rows; null_rows collapse; gates pass whatever the human-review pipeline subsequently provides. **Partially executed 2026-11-12 (revised 2026-11-12): CSVs were rebuilt and labels regenerated — monster row `.268.4` is gone, 8 of 9 previously missing Nôm pages re-emit rows (ch263 still zero rows; plus two more zero-row mapped pages ch206, ch275 — see §10 #18), null_rows=0, scored_rows 8→381. Gates do NOT pass (coverage/unverified/similarity still fail — see §5 M5); Tap3 monotone ✓, Tap2 untouched.**

### R2 (MAJOR) — Define "verified" for T1 as marker-consistency + anchors

**Status (revised 2026-11-12): NOT EXECUTED.** The rebuilt maps satisfy marker-consistency for 121/127 (Tap1) and 50/50 (Tap3) pairs — which *would* make them verified under R2's criterion — but no code promotes them, `markers_used` is only recorded as meta, and nothing downstream consumes marker consistency as a gate.

- Make marker agreement the deterministic verified criterion (`verified` iff PDF = marker+2).
- Wire the dictionary into scoring: pass the prebuilt cache `data/dictionary/char_readings.json` (or a `DictionaryIndex`) as `dictionary=` in `build_image_map` (one-line change) so `score_pairs_with_anchors` actually evaluates readings; reuse `fold()` folding from charalign inside `anchors.gather_readings` so coverage rises (current exact-match folding undercounts; median 0.201 → expect ~0.25–0.35).
- Recalibrate `verified_min_coverage` from 0.5 → **0.08** (measured: correct pairs min 0.061/median 0.201; wrong map ≤0.08 except correct-prefix pairs) or drop the coverage bar and require **≥2 unique anchors + marker agreement**. Realistic yield: **all 444 pairs verified** (every correct pair shows ≥7 unique anchors; Tap3 minimum 7).
- Keep `candidate` only for pages without markers; `unresolved` only for marker/map disagreement pending human adjudication.

### R3 (MAJOR) — Classifier boundary fixes so this cannot happen again

**Status (revised 2026-11-12): NOT EXECUTED as specified — the re-bin was applied by DB surgery, not by a classifier fix.** The classifier gained only the dead `BIN_OVERRIDE_*` path (see §4; would wipe `status→classified` on re-run; never exercised — 0 flags in `pages.review_flags`).

1. New page class for `CHÚ THÍCH`/endnote/half-title/divider pages (`BẢN CHỮ NÔM`, `BẢN QUỐC NGỮ`, single-line pages with <8 text lines and no marker): classify as `misc`/`toc`, **exclude from map**. (Delivered instead via map `excluded_pages`: Tap1 143/144, Tap3 62/063.)
2. `blank_likely` must win over the back-matter TOC override (or the override must skip blanks); post-block `nom_likely` pages → new flag `NOM_AFTER_BACKMATTER` → forced review (covers Tap2 p549). (Not executed.)
3. Rebuild Tap1/Tap2 maps (they are also in stale format). (Tap1/Tap3 rebuilt — see R1 status; Tap2 NOT rebuilt.)
4. Fix `toc_likely`: require dotted leaders (row runs of intermittent dots ≥20% of line length) or short lines — any reasonable TOC discriminator; today it matches ~all prose. (Not executed.)
5. Re-audit vi folder composition after fix: Tap2 vi should be 264, Tap1 vi (translation) 122 + documented front matter; Tap3 vi 50 (+ blank excluded). **Partially delivered at the DB level only: Tap1 vi013–142 = 130 (front matter included), misc = {001,005,007,008,009,010,011,143,144,145,277–282} = 16; Tap3 vi011–060 = 50, misc = {001,002,003,005,007,008,009,062,063,064,117,118} = 12 — applied by direct DB surgery with backup `data/state.sqlite3.bak-2026-11-12-rebin-fix` (2026-11-12 19:36:40); `classification.json` NOT regenerated (stale — §4).**

### R4 (MAJOR) — Harden validation & packaging

**Status (revised 2026-11-12; re-checked 2026-11-13): NOT EXECUTED.** `t1_map.py` is unchanged; `package.py` is **no longer byte-unchanged** (2026-11-13 verify-A hardening, +58 lines: state backup, pages.jsonl regeneration, `_updated.pdf` hash gate) — its image-map blocks moved (~+12 / ~+58 → ~246–252 / ~449–461) but no coverage/marker/ordering validation was added; bytes elsewhere are consistent with B3's rewrite.

`validate_image_map` additions: (i) **coverage** — every page of each relevant folder (ch, vi, intro, toc, missing_*) appears in exactly one pair or is explicitly marked unmapped with a note; (ii) **monotonicity** — pairs sorted by vi ascending with ch strictly descending, no crossing; (iii) **marker check** — when a markers payload is supplied, every pair must satisfy Nôm PDF = marker+2 (fail-closed); (iv) **manual-map coverage** — a manual map must cover exactly the pages of the auto-map (or declare omissions); (v) honor `max_group`/`max_nm_group` from `configs/alignment.yaml`; (vi) fix `missing_ch` sort sentinel (`pair_order` 1e9 → use ch `nom_order` instead). Run the same validator in `package.py` as an **error**. Add a fixture test pinning Tap3's marker-derived map so CI can never regress silently (markers are static in the book images).

### R5 (MAJOR/MINOR) — Unify the two alignment paths

**Status (revised 2026-11-12): NOT EXECUTED.** `charalign.py`, `clean.py`, `anchors.py` unchanged; the 2026-11-12 change-set touches `align.py` (+72 net lines after ~line 387; `COSEGMENTED_*` alignment path and `textdiff.py` `_reading_match`/`auto_text_diff` hardening, +1..15) and `orchestrator.py` (net-0, one-line stage_labels tweak) — none of it wires markers to any consumer. `charstream.py` (new) is the charalign-projected segmentation provider used by `align_book` when `segmentation == "charalign"` (`align.py:575–604`) — it replaces cosegmentation for those books, does not "feed cosegmentation", and emits no markers. (cite fixed 2026-11-13)

- `charalign.QN_HEADER_RE`: tolerant pattern (§5 M2); use parsed markers as band anchors (or at minimum drop pair-anchors disagreeing with markers).
- `read_image_map` should honor `status` (skip or hard-flag `unresolved` pairs).
- `build_image_map` must rebuild when `image_map.json` is stale (source absent/old format), not silently keep it.
- Emit a `marker` field into `data/clean/*.json` at cleaning time, **before** `PAGE_MARK_REMOVED` drops the line (the pipeline sees every marker today and throws it away — capture it in `clean_page_lines` where `PAGE_MARK_REMOVED` is currently recorded).
- Unify `QN_TOKEN_RE` (anchors vs charalign) and folding functions.

### R6 (MINOR, hygiene) — Policy and format

**Status (revised 2026-11-12): NOT EXECUTED.**

- Decide the front-matter position explicitly: either include intro/toc QN images in the map against their marker-proven Nôm counterparts (requires relaxing `validate_image_map` to accept intro/toc/misc images) or document their exclusion in `meta.note`. **Current silent drop is the worst option** (it is exactly what broke Tap1's stream). **(Revised 2026-11-12): the rebuilt Tap1 map *includes* the front matter — the decision is effectively made and should now be recorded in `decisions.md`.)**
- Trim/confirm extra `Pair` fields (`confidence`, `source`, `status`) vs the guideline's minimal `{ch, vi, note?}` at packaging; set `mapping_source="printed_marker"` and complete verified-counts in `meta`.
- Delete dead code (`gaps`, `ratio_guard` when both sides are 1.0-expected, `anchor_coverage`), or wire it.
- Honor `force` or drop the parameter; caching of `analyze_image` would help but determinism already holds.
- Update README/USER_GUIDE: image_map source of truth = printed markers; marker extraction step documented; Tap1 front-matter decision recorded.

**Expected verified-pair yield after R1+R2:** 444/444 marker-verified (Tap1 130 incl. front matter, Tap2 264, Tap3 50), anchor-corroborated everywhere (≥2 anchors per pair; median coverage ~0.20 with hvdic wired in). **(Revised 2026-11-12): NOT achieved — the 2026-11-12 repair produced 0 verified pairs; realistic current yield under R2 applied to the rebuilt maps would be 121 (Tap1 1:1) + 264 (Tap2, after rebuild) + 50 (Tap3) = 435; the 6 Tap1 double-absorb groups need marker adjudication individually.** Residual exceptions: none — every 1:1 pair above has marker support; endnotes/dividers/blanks are the only unpaired pages, by design.

### Status of R1–R6 as of 2026-11-12 (summary, revised 2026-11-12)

| item | status | delivered by |
|---|---|---|
| R1 (marker-rebuilt maps) | **PARTIAL** — Tap1/Tap3 re-paired & marker-consistent (121/127, 50/50); mono-`candidate`; Tap2 absent | change-set (`map_repair.py`, `repair_image_map.py`) |
| R2 (verified := marker+anchors) | **NOT DONE** — no promotion path; gates still red | — |
| R3 (classifier boundary fix) | **NOT DONE as specified** — re-bin via DB surgery; `BIN_OVERRIDE_*` dead path added; classification.json stale | change-set (configs, layout.py minor) |
| R4 (validation hardening) | **NOT DONE** | — |
| R5 (align/charalign unification) | **NOT DONE** — align.py/textdiff.py hardened unrelatedly; charalign untouched | — |
| R6 (policy/format) | **NOT DONE** — Tap1 front-matter decision *effectively* made (included), needs recording | change-set (map content) |

---

## 7. Downstream impact quantification

**Human/review-visible damage** (revised 2026-11-12; before → after for Tap1/Tap3, Tap2 unchanged):

| Stage | Tap1 | Tap2 | Tap3 |
|---|---|---|---|
| align CSV (`data/align/*/…`) | **823 rows** (was 727); monster row **gone** (one legitimate `.268.4` remains — ch_page 268, 37 vs 156 chars; the 1941/7220 monster is archived pre-repair); ch259–267 emit rows except **ch263 (zero rows)**; plus zero-row mapped pages **ch206** (vi083 clean text = 0 chars) and **ch275** (vi014, 115-char imprint); `null_rows=0` (was 124); `scored_rows=381` (was 8); `coverage_ratio=0.4629`; `unverified_ratio=0.5358`; `similarity=89.9646`; `denominator=7065`; `red_mismatch_chars=709`; single UNMATCHED_QN row (skip_qn, `img_id=.100.jpg`, `text_diff` `null`, warning `QN_SENTENCE_NO_NOM:529`); stream order non-monotone at that skip row (between two `.189.jpg` rows); `review_metadata.jsonl` 823 lines, `COSEGMENTED_STREAM_ALIGNED` on every row (flags: `DIFF_READING_MISMATCH` 650, `DIFF_NO_READING_MISMATCH` 172, `DIFF_AMBIGUOUS_READINGS` 362, `ALIGN_EVIDENCE_INSUFFICIENT` 233) | **8 rows** (smoke, unchanged); `EMPTY_DENOMINATOR`; all 8 `text_diff=null` | **380 rows** (was 341); intact; **monotone ✓**; **0 UNMATCHED_QN**; `null_rows=0`; `scored_rows=228`; `coverage_ratio=0.6000`; `unverified_ratio=0.4000` (152); `similarity=93.7385`; `denominator=3274`; `red_mismatch_chars=205`; `review_metadata.jsonl` 380 lines, `COSEGMENTED_STREAM_ALIGNED` on every row (flags: `DIFF_READING_MISMATCH` 224, `DIFF_NO_READING_MISMATCH` 156, `DIFF_AMBIGUOUS_READINGS` 120, `ALIGN_EVIDENCE_INSUFFICIENT` 74) |
| evaluation `metrics.json` | `passed=false`; `INSUFFICIENT_COVERAGE:0.4629<0.9`; `UNVERIFIED_RATIO_HIGH:0.5358>0.05`; `SIMILARITY_BELOW_GATE:89.9646<95.0`; **`EXCESSIVE_NULL_ROWS` GONE**; warning `UNVERIFIED_DIFFERENT_ROWS:136`; `verified_match=136` / `verified_difference=245`; `unmatched_rows=1` | `passed=false` (unchanged) | `passed=false`; same three issues (− EXCESSIVE_NULL_ROWS); warning `UNVERIFIED_DIFFERENT_ROWS:125`; `verified_match=125` / `verified_difference=103`; `unmatched_rows=0` |
| `charalign` diagnostic (Book 3) | — | — | `nom_chars=8637`, `qn_syllables=8293`, pairs exact 7261/fold 360/lex 25/diff 330, `dictionary_coverage=0.996`, `qn_page_markers={}`, similarity 87.23, `anchors=50`, `rows=435`, `null_rows=46` — **identical regardless of pair quality** (controlled 3-way experiment; charalign.py untouched by change-set) |
| package step | would ship **repaired but `candidate`** map — any instructor-side marker check fails on the 6 grouped double-absorbs (Tap1); and packaging drops `meta`/re-defaults statuses by construction (see B3) | ships the broken stale map (16 wrong pairs, incl. 3 grouped absorbs) | would ship repaired `candidate` map — passes marker spot-checks (50/50) but unadjudicated; all-books provenance still unverified |

**Mechanism summary:**
- The `align` path was the sensitive one: stream **membership** comes from pairs — pages absent from pairs never reached the aligner (Tap1 lost vi013–vi020; this produced the monster row). **Post-repair (Tap1), membership is restored** — front matter and body pages re-enter; the residual is *zero-row drops*, not mis-pairing (see §10 #18). Stream **order** is file order (always monotone — and the Tap1 CSV is now monotone except at the skip_qn row).
- `charalign` is insensitive at `band=400` (shift ≪ band) but consumes the same pairs as band anchors and silently ships them; narrow band would corrupt its alignment too — and it would corrupt it silently regardless of the repair, since it ignores `status`.
- The evaluation gate still correctly reports failure; nothing can pass the gate on the current corpus state regardless of human review effort — removing broken pages from consideration is impossible because they're structurally in the map, and promotion to `verified` is not wired. (`SIMILARITY_BELOW_GATE` now applies to both live books; see M5.)
- **One wrong 1-2 split is enough to invalidate a whole book-tail** (Tap2: 16/264 pairs shifted by exactly one vi page from pair ch292 onward; Tap3 pre-repair: 40/50 from ch106; Tap1 pre-repair: 100% from pair 1). Post-repair, Tap1's violations are six localized double-absorbs; Tap3 has none; Tap2 is unchanged.
- `data/layout/*/classification.json` boundaries (Nôm runs) are fine; everything downstream of block selection is now (revised) *unverified rather than poisoned* — except Tap2, which is unchanged-and-shipping-broken.
- **New 2026-11-12 hygiene items to fix before packaging:** Tap3's `data/align/T1_SuaLoiQuyen/_pre-repair-2026-11-12/` is a runaway self-nested directory (~1,421 nested `_pre-repair-2026-11-12` levels as written; exactly 1,421 by hard-capped re-measurement 2026-11-13; breaks `Get-ChildItem -Recurse`) holding the pre-repair CSV/review-metadata; Tap1 has a single-level `_pre-repair-2026-11-12/` holding the 727-row pre-repair CSV. Both are artifacts of the repair tool and should be cleaned up. (revised 2026-11-12 → detail 2026-11-13)

---

## 8. Reproduction commands

```powershell
cd "C:\Users\MSI VN\Desktop\NLP"
python -m pytest -q                                  # all 291 tests pass (was 282 at 2026-11-12; 277 at first writing)
```

Empirical probes (all in `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B`):

```powershell
# map correctness vs marker formula
python "$env:TEMP\opencode\verify-B\correctness.py"  # (path: C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B\correctness.py)

# OCR marker hits / coverage scan — recorded output artifact (not a script):
#   "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B\markers_all.txt"   # no `markers_scan.py` exists (cite fixed 2026-11-13); `docs/0021.json`-style markers also verifiable inline

# anchor-evidence agreement between markers and readings
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B\shift_test.py"     # own-pair vs neighbors ±1,±2
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B\detail.py"         # one pair deep-dive (ch096↔vi031: 34 anchors)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B\tap1_shift.py"     # Tap1 neighbor comparison
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B\correct_score.py"  # hvdic-cache scoring of the CORRECT Tap3 map
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B\rescore3.py"       # re-run with zero-padded names: 1 verified (ch067↔vi060), 49 unresolved

# three-way controlled experiment (old pairs / no pairs / marker-correct pairs)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B\three_way.py"

# map validity (structural only) + status census
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B\validate.py"       # issues: [] everywhere; statuses: all candidate
```

2026-11-12 re-measurement probes (all in `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B`, all read-only except that they print):

```powershell
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_consistency.py"  # Tap1 121/127 1:1 all consistent; Tap3 50/50; six Tap1 double-absorb groups listed
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_prerepair.py"   # backups: Tap1 124 pairs heuristic text-mass; Tap3 50 pairs heuristic_mass+anchor_evidence
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_db.py"          # state.sqlite3 tables; no review_flags table (flags in pages.review_flags)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_db2.py"         # DB bins: Tap1 vi130/misc16/ch130; Tap3 vi50/misc12/ch50
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_db3.py"         # ZERO BIN_OVERRIDE_* flags; top flags (LABEL_EMPTY_OCR 269/2, PAGE_MARK_REMOVED 70/34 …)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_proposed.py"    # Tap1 proposed.json vs applied map: differs only in proposed_at (benign)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_manual.py"      # front-matter pairs vi013–020 ↔ ch276–269 present; markers_used=70
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_manual2.py"     # note distribution: all pairs "content dp re-pairing"; no MANUAL_* in pair notes
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_csv.py"         # CSVs: monster row .268.4 gone; pages 259–267 mostly present; .100.jpg skip row found
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_csv3.py"        # .100.jpg at data row 529 (0-based), text_diff "null"; order break 100→189; null_bytes 0
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_csv4.py"        # zero-row mapped ch pages: 206, 263, 275; monster gone; 823 rows
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_csv5.py"        # Tap3 380 rows monotone ✓, 0 unmatched; Tap2 8 rows all text_diff null
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_meta.py"        # review_metadata.jsonl 823/380 lines; COSEGMENTED_STREAM_ALIGNED on every row
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_meta2.py"        # flags: Tap1 MISMATCH 650 / NO_MISMATCH 172; Tap3 224 / 156
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_ocr.py"         # ch0206 (254 ch), ch0263 TOC (138 ch), ch0275 colophon (29 ch) — all have OCR text yet emit no CSV rows
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_pairs.py"       # ch275↔vi014 (115 clean ch), ch263↔vi026 (889 clean ch), ch206↔vi083 (0 clean ch)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B\probe_dups.py"        # duplicate-page audit (present 2026-11-13; not enumerated in the original probe list)
```

Marker extraction (proposal, not yet run in-repo):

```python
import json, re
MARK = re.compile(r"\(\s*(\d{2,4})\s*\)")
for p in range(lo, hi+1):
    d = json.load(open(f"data/ocr/{BOOK}/{p:04d}.json", encoding="utf-8"))
    txt = " ".join(l["text"] for l in d.get("lines", []))
    print(p, [int(m.group(1)) for m in MARK.finditer(txt) if nom_lo <= int(m.group(1)) <= nom_hi])
```

Nôm printed range per book (marker validity): Tap1 145–274, Tap2 275–538, Tap3 65–114.

**Caution (revised 2026-11-12):** do **not** re-run `stage_map`, the repair tool, or `stage_align`/`stage_clean` against the delivered state without a fresh backup — the re-bin backup exists (`data/state.sqlite3.bak-2026-11-12-rebin-fix`) but is the *only* recovery point, and `classification.json` cannot regenerate the DB bins.

---

## 9. Handoff checklist (next agent)

- [ ] Read this document fully; then re-read `src/hannom/t1_map.py` (all), `src/hannom/anchors.py`, `map_repair.py` + `tools/repair_image_map.py` (the 2026-11-12 repair), `layout.py` (`classify_book`, `_longest_nom_run`, `analyze_image` incl. the new `BIN_OVERRIDE_*` block ~339–348), and `charalign.py` around lines 42, 167–201, 611–665, 747. Note: `align.py` shifted (+8 @71, +3 @91, +20 @433→444, +41 @538→569 — net +72 after ~line 387) and `textdiff.py` shifted +1..15 in the 2026-11-12 change-set, so any **stale line cites above those offsets are wrong**; this document carries no such cites; `orchestrator.py` net-0 (cited `:102` still valid). (revised 2026-11-12)
- [ ] Do **not** run the Kim API for any verification; do **not** read `.env`/`hannom_API.md`.
- [ ] Reproduce §3's marker math from scratch on 5+ pages per book before trusting any rebuilt map (images are ground truth). (Done by the 2026-11-13 replication audit: 32 pages read, 18 body/TOC/preface markers (8 Tap1 + 5 Tap2 + 5 Tap3), all match `const−vi_PDF`; boundaries verified (Tap1 147→145, Tap2 277→275 & 540→538, Tap3 067→65 & 116→114); zero contradicting images — see §12.)
- [ ] **Maps were rebuilt 2026-11-12 via content-DP (NOT per R1 spec) — adjudicate, don't re-pair blindly:** (i) resolve the six Tap1 grouped double-absorbs against printed markers (vi031↔{257,258}, vi032+33↔{256}, vi040+41↔{249}, vi042↔{247,248}, vi132+33↔{157}, vi134↔{155,156}); (ii) rebuild Tap2 per R1 (untouched — 248/264, stale format); (iii) promote marker-consistent pairs to `verified` per R2 (markers_used Tap1=70/Tap3=33 already extracted & recorded); (iv) refresh stale `meta vi_page_count` (Tap1 124→130, Tap3 52→50); (v) record the missing third Tap3 `marker_issues` entry (vi036, (10)+2=12) — present in the current tool, absent from the artifact; (vi) re-record Tap1 `metrics.json` (live file) into `metrics.20261112T*` archives before any further overwrite. (revised 2026-11-12)
- [ ] ~~Include Tap1 front matter (vi013–vi020 ↔ ch276–269)~~ — **done by the 2026-11-12 repair** (front matter paired 1:1, parens-consistent); what remains is promoting those pairs to `verified` and recording the front-matter decision in `decisions.md`. (revised 2026-11-12)
- [ ] Re-run the full chain after any R2 promotion and diff every gate number vs this report's §7; the acid test is met on the 1941/7220 monster row (gone — one legitimate `.268.4` sentence_id remains for ch268) and 8/9 Nôm pages back — ch263/206/275 zero-row drops need their own spot-check before calling this closed. (revised 2026-11-12 → annotated 2026-11-13)
- [ ] Run R4 validation additions; `package.py` must fail loudly on marker inconsistency.
- [ ] Pin a fixture test with the marker-derived Tap3 map; require marker consistency in CI for future books (add markers dump for each new book).
- [ ] Re-check `data/output/` (source.zip) gets rebuilt only after R1/R2 land and gates pass; the currently packaged image_map artifacts are unverified (though Tap1/Tap3 pairs are marker-consistent — Tap2's are not). (revised 2026-11-12)
- [ ] Update README (book boundaries, marker step) and USER_GUIDE; remove or soften any claim that Tap2/Tap3 maps are "ready".
- [ ] Re-assess `fileState.txt`, Label.txt and `Quy_định_đồ_án v2.1` mandatory files per book after rebuild (this area-B pass did not audit packaging completeness, only the map).
- [ ] If pursuing anchor-based `verified` labels (R2), collaborate with whoever owns `data/dictionary/book_lexicons/`: the legacy quarantine (Tap3: 22,388 pairs) needs one adjudication pass before anchor evidence can certify anything without markers.
- [ ] Confirm exact endnote/divider page lists per book before exclusion (Tap1: vi143/144; Tap2: vi273/274/275; Tap3: vi062/063 — all footnote-only, no markers) — do not exclude translation pages.
- [ ] Verify p275 (Tap2 divider) and vi144 (Tap1) have no `( N )` marker before excluding (already image-confirmed; re-do quickly after any re-extraction).
- [ ] Re-run `python -m pytest -q` (291 green as of 2026-11-13); add tests for R1–R4; all must stay green.
- [ ] **Clean up the repair artifacts:** `data/align/T1_SuaLoiQuyen/_pre-repair-2026-11-12/` (runaway self-nested, exactly **1,421** levels as re-measured 2026-11-13 with a hard-capped walk — all dirs named `_pre-repair-2026-11-12`, max depth 1,420 below root; top level holds 3 files incl. the pre-repair 341-row CSV) and the single-level `data/align/T1_CamPhong_Tap1/_pre-repair-2026-11-12/` (727-row pre-repair CSV + review-metadata). Decide whether to keep them as archival backups elsewhere or delete. (revised 2026-11-12 → detail 2026-11-13)
- [ ] **Reconcile `classification.json` with the delivered DB** for both books (or record the mismatch explicitly in `decisions.md`): counts are stale (Tap1 prints vi124/toc16/intro4 vs DB vi130/misc16/toc0/intro0; Tap3 prints vi52/intro4/toc4 vs DB vi50/misc12/toc0/intro0). Also decide whether to rerun classification now that `BIN_OVERRIDE_*` exists — noting it would wipe `status→classified`. (revised 2026-11-12)
- [ ] **Errata `docs/decisions.md`:** the "2026-11-12 gate status unchanged" entry omits `SIMILARITY_BELOW_GATE` for both live books and its "0.7% gap to 95% on Tap1" is unreconcilable (measured 89.9646 → gap 5.04; Tap3's 1.26 ≈ its stated 1.3%). (revised 2026-11-12; entry confirmed verbatim against line 23 of the file, 2026-11-13.)

Scratch dir with all probes: `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-B` (correctness.py, three_way.py, shift_test.py, score_dict.py, correct_score.py/rescore3.py, tap1_shift.py, validate.py, markers_all.txt, detail.py, tap1_detail.py, three_way.log, img_map.txt, …) and `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-B` (2026-11-12 read-only re-measurements; see §8). **Repo state at revision (revised 2026-11-12): NOT clean — the collaborator's 2026-11-12 change-set is uncommitted (9 modified files + new `src/hannom/charstream.py`, `src/hannom/map_repair.py`, `tools/repair_image_map.py`, `tests/test_charstream.py`, `tests/test_map_repair.py`, plus this Doc/ verify set); HEAD is `c3439e7` (== `repair/pipeline-audit-2026-11-09` tip, on origin); ZERO new commits. Post-commit (2026-11-13, +0700 08:07): both change-sets landed in `ed43470` (map repair + declarative re-bin + this Doc/ audit set) and `4fd0af6` (verify-A hardening); branch pushed to origin; tree clean except this document. Nothing under `data/` or `src/` was touched by THIS revision pass; only this document was edited.**

---

## 10. Caveats

1. **Marker slope/range are empirical, not proven globally.** The −1 slope held on ~105 verified QN pages across the three books (images + OCR), with zero violations, and is now also consistent with Tap1's 121/127 and Tap3's 50/50 `1:1` paren-consistent rebuilt pairs. Treat any discovered repeat or jump (true 1-2 split) as authoritative — re-audit the affected region only, not the whole book. (revised 2026-11-12)
2. **Marker ↔ Nôm printed page correspondence is assumed, not proven from the source PDF.** It is consistent across typography, direction of writing, page ranges, content order, and reading anchors — overwhelmingly likely "the" counterpart (also matches both V2.1 guideline semantics for dịch âm books). If the books' own erratic pagination ever breaks it mid-run (e.g., a misprinted leaf), trust the marker; it is what the publisher printed.
3. **`p118: [16]`** (Tap1) is an OCR fragment — the formula predicts marker 169 for that page (an OCR hit of `[16]`, i.e. truncated or bled-in footnote `(16)`); image verification for that one page was not performed. The formula is corroborated on every other Tap1 page checked (69 OCR hits + images); treat p118 as unverified-but-formula-consistent.
4. **Tap2 has no OCR markers at all** (only 6 sample pages were ever OCR'd); all Tap2 marker evidence above comes from visually reading images: vi009, vi010, vi257, vi258, vi272 (markers 538/537/290/289/275) plus formula consistency. A completion OCR pass over the top-right crop is mandatory for the R1 migration; do not assume unseen pages deviate — the slope held perfectly at both boundaries and mid-book.
5. **Reading anchors are corroborating, not certifying.** Coverage is intrinsically limited (archaic HV vs modern QN orthography + OCR noise); they catch *gross* misalignment decisively (34 vs 3), not subtle one-page drifts at low density. Use markers for identity, anchors for sanity. (Unchanged — the repair did not wire anchors into any verification consumer.)
6. **Book boundaries per README/team (Tap1 [147,276], Tap2 [277,540], Tap3 [67,116]) are confirmed**, and the PDF = printed+2 offset was verified on boundary pages of all three (Tap1 PDF 146 blank/PDF 147 first Nôm page printed 145; Tap2 PDF 540 printed −538− / Tap2 PDF 277 printed −275−; Tap3 PDF 116 printed −114−). Front matter is: Tap1 PDF 1–20 before translation starts at 21; Tap2 1–8 before 9; Tap3 1–10 before 11.
7. **The monster row (§B2) was an empirical observation**, not a prediction — it existed (string search, 9/9 missing pages) and the 2026-11-12 rebuild removed it. Any re-repair may re-create analogous artifacts; if a row then exceeds sane size, suspect cosegmentation anchor fallback, not the map. (revised 2026-11-12)
8. **Evaluation similarity numbers are not evidence of quality anywhere in this report** — they are reported only to crash-test the gate semantics. Post-repair they are computed over 381 (Tap1) and 228 (Tap3) scored rows with `null_rows=0` — the gate is still red (see §5 M5). (revised 2026-11-12)
9. **All quoted image paths are relative to the repo root**; file names contain Unicode NFC Vietnamese; the CSV uses `utf-8-sig`. Byte-level identity of image_map copies in `data/output/` vs `data/layout/` was not audited (only content semantics).
10. **This report changes nothing in the repo's content.** At first writing the worktree was clean except pre-existing changes elsewhere (untouched). **As of the 2026-11-12 revision, the tree carries the collaborator's uncommitted change-set** (9 modified files + the new map_repair/charstream sources/tests — see §2 git note). **Post-commit 2026-11-13:** those change-sets landed as `ed43470` (map repair + docs) and `4fd0af6` (verify-A hardening) and were pushed; the tree now carries only this document's modification. This revision pass edited only this document; nothing under `data/`, `src/`, `configs/`, or `tests/` was touched by the reviser, and no pipeline stage was run. (revised 2026-11-12 → annotated 2026-11-13)
11. Endnote/divider page sets are confirmed for Tap1/Tap2/Tap3 by image + OCR (footnote-only content, no markers); do not generalize to other books without re-reading their endnotes.
12. If the team decides to keep the front-matter exclusion (R6 option b), B2's monster row must *still* be fixed — it comes from missing QN-counterpart membership in the streams, not from taste; the exclusion decision only affects whether front matter pairs are *in* the map. **(Revised 2026-11-12): moot — the delivered Tap1 map *keeps* front matter.**
13. **`image_map.json` meta `vi_page_count` is stale in both rebuilt maps** (Tap1: 124 vs actual 130 distinct vi; Tap3: 52 vs 50) and counts in `ch_page_count` match (Tap1 130/130, Tap3 50/50 — for Tap1, `ch_page_count` coincidentally equals the re-binned ch count). Tap2's meta `vi_page_count=267` is **consistent** with its 267 distinct vi (stale format but not stale numbers). Trust distinct vi coverage computed from `pairs`, never `meta.vi_page_count`. (revised 2026-11-12 → Tap2 note confirmed 2026-11-13)
14. **`classification.json` counts are stale for both live books** (Tap1: blank6/ch130/intro4/misc2/toc16/vi124 printed vs delivered DB vi130/misc16/ch130/toc0/intro0; Tap3: intro4/toc4/misc2/vi52 printed vs delivered DB vi50/misc12/toc0/intro0). The re-bin was applied by DB surgery (backup `data/state.sqlite3.bak-2026-11-12-rebin-fix`, 2026-11-12 19:36:40, 1,015,808 bytes); `BIN_OVERRIDE_*` in `layout.py` (~339–348) would additionally wipe `status→classified` on re-run for **all** pages (unconditional `layout.py:354`, not specific to the override block) and has never been exercised (`pages.review_flags` contains zero `BIN_OVERRIDE_*`; probed read-only 2026-11-12, re-probed 2026-11-13 — still zero). (revised 2026-11-12 → correction 2026-11-13)
15. **`markers_used` semantics.** Tap1 `markers_used=70` = 67 OCR parens + 3 MANUAL_PARENS (vi020, vi079, vi135); Tap1 `marker_issues=[]`, `anchor_issues=[]`. Tap3 `markers_used=33`, `marker_issues` recorded for vi038 ("(13)+2=15 not in ch inventory") and vi049 ("(8)+2=10 not in ch inventory"); a third (vi036, (10)+2=12) exists per the current tool but is **not** recorded in the artifact. Manual parens markers are not reflected per-pair in notes (all pairs carry the generic `note="content dp re-pairing"`). All statuses remain `candidate`; success by marker should not be conflated with gate passage. (revised 2026-11-12)
16. **Three different "before" numbers coexist for Tap3.** The 2026-11-08 ink-mass heuristic produced 48 pairs (per `map_repair/summary.json` `old_pairs=48`, and the report's original §3 "before"); an intermediate 50-pair `heuristic_mass+anchor_evidence` map (the file kept at `map_repair/image_map.pre-repair.json`, 11/12 ~18:37) scored 10/50 marker-consistent — that is the state the original §3 table measured; the 18:47 `content_dp` rebuild scores 50/50 (Tap3) and 121/127 (Tap1). Tap2's before == after (unchanged artifact). Do not mix these when quoting deltas. (revised 2026-11-12)
17. **Tap1's align CSV is no longer monotone.** One non-1-1 UNMATCHED_QN row (skip_qn, `img_id=…100.jpg`, `text_diff` `null`, warning `QN_SENTENCE_NO_NOM:529`) sits between two `.189.jpg` groups; every other row is ch-monotone decreasing. Tap3 remains fully monotone; Tap2's 8 rows are all `text_diff=null`. (revised 2026-11-12)
18. **Three mapped Tap1 ch pages yield zero CSV rows: ch206, ch263, ch275.** ch206↔vi083 (`data/clean/…/0083.json` = 0 chars), ch275↔vi014 (115-char imprint page), ch263↔vi026 (vi026 has 889 clean chars — but ch263 is the Nôm TOC page, 138 OCR chars; suspected zero-sentence drop on the ch side, mechanism unverified). This is **not** evidence of mis-pairing; all three are consistent with zero-sentence pages being dropped. Flagged for the next pass — verify before quoting CSV completeness; note ch263 is one of the nine pages originally missing pre-repair. (revised 2026-11-12)
19. **Tap1/Tap3 maps are mono-trending `candidate`** — the repair moved pairs into marker agreement but never promoted status, and no consumer treats `markers_used` as verification. Tap2 is stale-format (no `status`/`source` at all; load defaults all to `candidate`). Any downstream "verified" claim about these books is unsupported until R2 lands. (revised 2026-11-12)
20. **`docs/decisions.md` (2026-11-12 entry) is partially wrong.** "Both Tap1 and Tap3 still FAIL coverage ≥ 0.9 and unverified_ratio ≤ 0.05" — correct. It omits that both now also FAIL `SIMILARITY_BELOW_GATE` (89.9646 and 93.7385 vs 95.0). "The 0.7% gap to 95% on Tap1" is unreconcilable (measured gap 5.04); "and 1.3% on Tap3" is consistent (measured 1.26).
21. **Tap3's `data/align/T1_SuaLoiQuyen/_pre-repair-2026-11-12/` is a runaway self-nested directory** (~1,421 nested levels of the same folder name — recursive enumeration errors out; re-measured 2026-11-13 with a hard-capped walk: exactly **1,421** dirs, all named `_pre-repair-2026-11-12`, max depth 1,420 below root, top level 3 files incl. the pre-repair 341-row CSV); Tap1 has a benign single-level sibling holding the pre-repair 727-row CSV. Both should be cleaned up (see §9). (revised 2026-11-12 → detail 2026-11-13)
22. **`map_repair/summary.json` deltas are small by design.** Tap1: `old_pairs=127` → `new_pairs=127`, `changed_assignments=0`, `mean_recall 0.8866→0.8866` (the repair *confirmed* the intermediate 127-pair map rather than re-solving from scratch). Tap3: `48→50`, `changed_assignments=4`, `mean_recall 0.9476→0.9461` (a wash on recall). The headline 121/127 and 50/50 scores come from the parens anchors, not from recall improvements. (revised 2026-11-12)
23. **A marker-consistent pair is not a `verified` pair.** Even where the rebuilt maps satisfy PDF = marker+2, no `status=verified` exists anywhere, the M1 anchor-scoring path is untouched, the 0.5 coverage bar is still unreachable (median 0.201), and Tap2 is entirely unrepaired. Treat every pair in every book as unadjudicated until R2 lands. (revised 2026-11-12)
24. **`image_map.proposed.json` (Tap1, 19:51 propose-only) differs from the applied map only in `proposed_at`** (19:51:50 vs 19:37:42) — benign; pairs are byte-identical (127/127). (revised 2026-11-12)

---

## 11. Revision log (2026-11-12)

**Baseline of this revision:** pre-`feat/map-repair-align`-change-set text → post-change-set text. No new commits; HEAD `c3439e7`; branch `feat/map-repair-align`. All re-measured 2026-11-12 read-only (git, maps, backups, summaries, metrics, CSVs, DB bins, `pages.review_flags`, file mtimes). (Superseded 2026-11-13: both change-sets since committed — `ed43470` + `4fd0af6` — pushed to origin; tree clean except this document; see §2 git note / §12.)

Sections revised:
- Banner (new), Date line (annotated), Verdict (rewritten — repair ≠ verification), §1 files table (new `map_repair`/`charstream` rows; tests 277→282; stage-2 classifier row annotates `BIN_OVERRIDE_*` addition ~339–348), §2 (scratch dirs; git state; 282 tests), §3 (front-matter-included note; corrected-maps table annotated; **"Current maps — marker-consistency" rewritten before/after**; direction-of-error rewritten; anchor-coverage note retained; markers_used Tap1=70/Tap3=33 recorded), §4 (`layout.py:306` cite retained — insertion at 336 does not shift cites ≤334; blank-page and single-line bullets annotated with `excluded_pages`; staleness bullet rewritten to cover `classification.json` stale-for-both and the never-exercised `BIN_OVERRIDE_*` path ~339–348; new re-bin DB-surgery fact), §5 (B1/B2 rewritten before/after — monster row `.268.4` gone; ch259–267 back except ch263; B3 annotated; M1 status distribution updated (127/264/50 candidate; 0 verified); M3 annotated with six surviving double-absorb groups; M4/N4 annotated (Tap2-only staleness); **M5 rewritten with before/after metrics for both books** (Tap1 727→823 rows; similarity 87.36→89.9646; coverage 0.011→0.4629; unverified 0.817→0.5358; null 124→0; EXCESSIVE_NULL_ROWS gone; warning now UNVERIFIED_DIFFERENT_ROWS:136; Tap3 341→380; 85.87→93.7385; 0.0762→0.60; 0.6364→0.40; null 98→0; warning:125; Tap2 unchanged); M6 fully rewritten (rebuilt maps, stale meta `vi_page_count`, Tap3 pre-repair backup nuance incl. `old_pairs=48`, Tap1 proposed.json benign, Tap2 untouched, `BIN_OVERRIDE_*` dead path), N3/N4/N6 updated, I4/I5/I6 updated, **cross-path consistency table rewritten** (align: B2 resolved for Tap1, skip_qn row broke monotonicity; charalign: unchanged insensitivity; marker usage: still none), §6 (R1–R6 status annotations + new "Status of R1–R6 as of 2026-11-12" summary table; expected verified-yield rewritten as unachieved), §7 (align/metrics rows rewritten before→after; package row annotated; mechanism bullets revised; **new hygiene bullet: Tap3 `_pre-repair-2026-11-12` runaway nested dir (~1,421 levels) + Tap1 single-level sibling**), §8 (pytest 282; new `verify-revise-B` probe list; caution on re-running pipeline stages), §9 (checklist updated: R1 adjudication items, front-matter item struck as done, full-chain item updated, output/package items annotated, new cleanup/classification/decisions.md-errata items), §10 (caveats 7–8 re-scoped; **12 new caveats 13–24** covering meta staleness, classification.json staleness, markers_used semantics, Tap3 "before" numbering, Tap1 monotonicity break, zero-row ch pages 206/263/275, candidate-mono-trending, decisions.md errata, `_pre-repair` dir, summary deltas, marker-consistent ≠ verified, Tap1 proposed.json benign), Revision log (this section).

Line-cite deltas applied:
- `t1_map.py`, `anchors.py`, `charalign.py`, `clean.py`, `cli.py`, `cosegment.py`, dictionary sources: **unchanged** — all existing cites remain valid. **`package.py` changed after the revision** (2026-11-13 verify-A hardening, +58 lines; image-map blocks shifted → ~246–252 / ~449–461; B3 and R4 re-cited).
- `orchestrator.py` net-0 (stage_labels one-liner) — cited `:102` still valid.
- `layout.py` insertion at 336 (BIN_OVERRIDE, 11 new lines; post-insertion lines ~339–348) — shifts only cites ≥336; the document cites only ≤334 (306, 221–264, 247–251, 272, 333–334) plus `:354` (added 2026-11-13, §12.2 item 6), so **no shifts applied** to the pre-insertion cites; new content documents the added block.
- `align.py` hunks (+8@71, +3@91, +20@433/444, +41@538/569; net +72 after ~387), `textdiff.py` (+1..15) — **no line cites to those files exist in this document**, so nothing to fix; noted here because sibling verify files do carry such cites.
- Doc-internal references to "277" replaced with 282; pre-repair numbers retained only inside explicit before/after phrasing (never as present-tense claims).

Inconsistencies & oddities found while revising (all also flagged inline):
1. `classification.json` (both books) vs delivered DB bins — counts stale; re-bin by DB surgery with backup; `BIN_OVERRIDE_*` dead-end path added 11/12 would additionally wipe `status→classified` if ever exercised.
2. Rebuilt-map `meta.vi_page_count` stale (Tap1 124→actual 130; Tap3 52→50); verified-counts meta absent for Tap1, zero for Tap3.
3. `docs/decisions.md` gate entry omits `SIMILARITY_BELOW_GATE` (both live books) and its "0.7% gap to 95% on Tap1" is unreconcilable (actual 5.04).
4. Tap3 `marker_issues` understate the current tool (missing vi036, (10)+2=12); Tap1 `marker_issues=[]` with MANUAL_PARENS undisclosed in pair notes.
5. Tap1 CSV: 3 mapped ch pages (206/263/275) emit zero rows (ch206↔vi083 = empty clean text; ch275↔vi014 = 115-char imprint; ch263 = Nôm TOC, 138 OCR chars, vi-side 889 clean chars — mechanism unverified); pages 259–267 otherwise back (8/9).
6. Tap1 CSV non-monotone at the single UNMATCHED_QN row (`.100.jpg`, text_diff `null`, warning `QN_SENTENCE_NO_NOM:529`) — sits between two `.189.jpg` groups.
7. Tap3 `_pre-repair-2026-11-12/` runaway nested directory (~1,421 levels); Tap1 holds a benign 1-level `_pre-repair-2026-11-12/` sibling with the 727-row pre-repair CSV.
8. Tap3 `summary.json` (`old_pairs=48`, ~4 changed assignments, recall 0.9476→0.9461) describes an unseen intermediate — the kept pre-repair backup is 50 pairs `heuristic_mass+anchor_evidence`, while the report's original ground-truth "before" was the 2026-11-08 ink-mass heuristic (48 pairs).
9. Tap1 `map_repair/summary.json` reports `changed_assignments=0`, `mean_recall` flat 0.8866 — i.e. the repair *confirmed* (rather than re-solved) an already-127-pair map; headline correctness gains come from the parens anchors, not the DP.
10. Tap1 `image_map.proposed.json` vs applied `image_map.json` differ only in `proposed_at` (19:51:50 vs 19:37:42) — benign.
11. Tap2 remains the broken 2026-11-08 artifact (16/264 inconsistent; no status fields; EMPTY_DENOMINATOR gate) — the repair did not touch it; any "T1 maps repaired" claim is false for Tap2.
12. Side effect of rewriting §7: the pre-repair claims "727 rows / 9 Nôm pages missing / `.268.4` monster / EXCESSIVE_NULL_ROWS" are now only true of the archives (`metrics.20261112T120924Z.json` / `120355Z.json`) — they are retained above strictly as before/after context.

Nothing under `data/`, `src/`, `configs/`, or `tests/` was modified by this revision; no pipeline stage was run; no API calls; no secrets read.

---

## 12. Replication audit log (2026-11-13)

**Baseline:** the audits were run against the pre-commit worktree (HEAD `c3439e7`, 34 porcelain entries: 15 modified + 19 untracked, this Doc/ set untracked). Later the same morning (2026-11-13, +0700 08:07) both change-sets were committed — `ed43470` ("2026-11-12 map repair + declarative re-bin; Area A-I audit docs") and `4fd0af6` ("2026-11-13 verify-A (Area A) hardening: state integrity, gates, preflight") — and `feat/map-repair-align` was pushed to origin; the tree is now clean except this document, and the committed contents are identical to those audited. Nothing under `data/`, `src/`, `configs/`, or `tests/` was modified by this audit; no pipeline stage was run; no Kim Hán Nôm API calls; `.env` and `hannom_API.md` were never read.

**Method.** Four independent read-only audits, combined with the three 2026-11-12 verification passes:

1. **Static code check** (scratch `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-code-B`) — every file:line claim re-checked against the current tree.
2. **Data re-measurement** (scratch `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-data-B`) — maps, backups, summaries, archives, live metrics, CSVs, review-metadata, charalign stats, `classification.json` vs `state.sqlite3` (read-only `mode=ro`), nested-dir walk (hard-capped at 2000 dirs), `char_readings.json`, Tap2 OCR census.
3. **Image ground truth** — 32 native JPGs read directly (Tap1 12, Tap2 10, Tap3 10) plus regex cross-check of `data/ocr/<book>/*.json`.
4. **Tests / git / docs / hygiene** — `python -m pytest -q` (291 passed, exit 0), branch/HEAD/porcelain census, `docs/decisions.md` gate entry quoted verbatim (line 23), CI workflow read, README/.gitignore staleness checked, scratch dirs listed.

### 12.1 Claims re-measured — CONFIRMED (exact)

| Claim | Measured |
|---|---|
| Tap1 rebuilt map = 127 pairs (121 1:1 + 6 grouped double-absorbs), all `candidate`, `markers_used=70`, `excluded_pages=[143,144]`, front matter paired (vi013↔ch276 … vi020↔ch269) | **exact**; the six absorb groups match byte-for-byte: vi031↔{257,258}, vi032+33↔{256}, vi040+41↔{249}, vi042↔{247,248}, vi132+33↔{157}, vi134↔{155,156} |
| Tap3 rebuilt map = 50 pairs all 1:1, 50/50 parens-consistent, `markers_used=33`, `marker_issues` = vi038/vi049 (vi036 exists in OCR `0036.json` as `( 10 )`, ch 12 ∉ ch inventory — third issue present in tool, absent from artifact) | **exact** |
| Tap2 = 264 pairs, mtime 2026-11-08, byte-identical to `.bak-2026-11-12-phaseA` (SHA256 prefix `D417198F…`), no status/source fields, first wrong pair `ch292↔vi257+258`, 248/264, monotone +1 tail shift from ch292 (13 off-by-one 1:1s + 3 grouped) | **exact** |
| Marker formulas (Tap1 ch=289−vi; Tap2 ch=549−vi; Tap3 ch=127−vi) | **exact** on every 1:1 pair of the rebuilt maps (121/121, 50/50) and on all **18** image-read markers across the three books (8 Tap1 + 5 Tap2 + 5 Tap3); slope −1 everywhere checked; **no true 1–2 split anywhere** |
| Live metrics Tap1 (rows 823, scored 381, similarity **89.9646**, coverage 0.4629, 441/823 = 0.5358, null_rows=0, `UNVERIFIED_DIFFERENT_ROWS:136`, issues: INSUFFICIENT_COVERAGE / UNVERIFIED_RATIO_HIGH / SIMILARITY_BELOW_GATE, `passed=false`) | **exact** (fields read directly; note `unverified_ratio` is derived, not stored — §5 M5 caveat) |
| Live metrics Tap3 (rows 380, scored 228, similarity **93.7385**, coverage 0.6000, 0.4000, null_rows=0, warning `:125`, `passed=false`) | **exact** |
| Tap2 metrics (8 rows, `similarity=null`, `EMPTY_DENOMINATOR`, `null_ratio=1.0`) | **exact** (plus unlisted warning `NULL_ROW_RATIO_HIGH:1.0000`) |
| Pre-repair archives (`metrics.20261112T120924Z.json` Tap1 → 727 rows, 8 scored, 87.36, 0.0110; `…120355Z.json` Tap3 → 341 rows, 26 scored, 85.87, 0.0762) | **exist and match** |
| Pre-repair backups (Tap1 124 pairs `heuristic text-mass partition`; Tap3 50 pairs `heuristic_mass+anchor_evidence` — the intermediate, **not** the 2026-11-08 ink-mass 48-pair original) | **exact** |
| Tap1 `map_repair/summary.json` (old 127 → new 127, `changed_assignments=0`, recall 0.8866→0.8866, mtime 19:51 propose-only run) vs `image_map.proposed.json` (differs from applied map only in `proposed_at`) | **confirmed**; the summary does **not** reconcile with the 124-pair pre-repair backup (propose-only run over the already-repaired map) — artifact lineage quirk, not a report misstatement |
| Tap3 `summary.json` (old_pairs=48 → new=50, `changed=4`, recall 0.9476→0.9461) | **exact**; the referenced 48-pair ink-mass original does not exist anywhere in `data/` |
| CSV row counts (Tap1 823, monotone except `.100.jpg` skip row at 0-based idx 529, text_diff `null`, warning `QN_SENTENCE_NO_NOM:529` in `summary.json`, mapped ch pages with **zero rows = [206, 263, 275] exactly**); Tap3 380, monotone ✓; Tap2 8, all `text_diff=null` | **exact** |
| `review_metadata.jsonl` line counts (823 / 380) and all **eight** flag histograms (Tap1 650/172/362/233 + others; Tap3 224/156/120/74) | **exact, zero tolerance** |
| `book3_charalign/stats.json` (`qn_page_markers={}`, 8637/8293, exact 7261 / fold 360 / lex 25 / diff 330, `dictionary_coverage=0.9961`, similarity 87.23, anchors 50, rows 435, null 46) | **exact** |
| `classification.json` staleness (Tap1 prints blank6/ch130/intro4/misc2/toc16/vi124 vs DB vi130/misc16/ch130/blank6/toc0/intro0; Tap3 prints intro4/toc4/misc2/vi52 vs DB vi50/misc12/ch50/blank6) | **exact**; DB bins and both misc sets confirmed exactly (Tap1 16 pages incl. 001,005,007–011,143–145,277–282; Tap3 12 pages) |
| `pages.review_flags` = **zero** `BIN_OVERRIDE_*` (all three books) | **exact** (re-probed 2026-11-13) |
| `data/state.sqlite3.bak-2026-11-12-rebin-fix` | **exists**: 1,015,808 B, 2026-11-12 19:36:40 |
| `_pre-repair-2026-11-12` runaway dir (Tap3) | **exact**: 1,421 directories, all same name, max depth 1,420, 3 top-level files; Tap1 sibling single-level w/ 727-row CSV |
| `data/dictionary/char_readings.json` | **exactly 26,700** char entries (781,132 B) |
| Tap2 OCR census (`0009/0142/0275/0277/0409/0540`) + `data/evaluation/T1_CamPhong_Tap2/metrics.json` exists | **exact** |
| Markers image-read | every QN *substantive* page read carries `- N - (marker)` with marker = const−vi: Tap1 vi013(274) vi020(267) vi021(266) vi025(262) vi030(257) vi060(227) vi140(147) vi142(145); Tap2 vi009(538) vi010(537) vi257(290) vi258(289) vi272(275); Tap3 vi011(114) vi021(104) vi022(103) vi031(94) vi060(65); endnotes (Tap1 143/144; Tap2 273/274; Tap3 062/063), dividers (Tap2 275 `BẢN CHỮ NÔM`), folio-only blanks (Tap1 PDF 146 `- 144 -`, Tap3 061 `- 59 -`) print **no** marker; **Tap1 PDF 146 and Tap3 061 are NOT fully blank — they print folios**. All match the marker formula (§3) |
| Nôm PDF = printed − 2 at boundary leaves (Tap1 PDF 147 (ch147) `145 -`; Tap2 277 `- 275 -` & 540 `- 538 -`; Tap3 067 `- 65 -` & 116 `- 114 -`) | **exact** |
| Map pairs vs markers: Tap1 front matter re-enters streams; monster row archived; 8 of 9 previously-missing Nôm pages re-emit rows; ch206/ch263/ch275 zero rows | **exact** (ch206↔vi083 0 clean chars; ch263 = Nôm TOC 138 OCR chars vs vi-side 889; ch275 colophon 29 OCR chars / vi014 115 clean chars) |
| `docs/decisions.md` 2026-11-12 gate entry | **confirmed verbatim** (line 23): coverage/unverified named; `SIMILARITY_BELOW_GATE` omitted for both books; "0.7% gap to 95% on Tap1" present but irreconcilable (gap 5.04); Tap3 1.3% ≈ 1.26 ✓ |
| CI / `.gitignore` / `pyproject.toml` | CI triggers dev/main/`repair/**` + PRs only (not this branch), py3.11/3.13, `python -m pytest -q`; `hannom_API.md`/`.env` ignored, never tracked; `pyproject.toml` pytest `pythonpath=["src"], testpaths=["tests"], addopts="-q"` — as stated |
| Scratch dirs `verify-B` (34 entries) and `verify-revise-B` (18 probes) exist | **exact** (probe lists above; `markers_scan.py` does not exist — `markers_all.txt` does; `probe_dups.py` added to listing) |

### 12.2 Claims corrected in place (2026-11-13)

1. **Tests 282 → 291** (§1, §2, I5, §8, §9) — 2026-11-13 verify-A hardening added `tests/test_verify_a_hardening.py` (+9); README still says "57 tests (line 103)" — stale everywhere.
2. **Git snapshot stale** (§2) — 34 porcelain entries (15M+19??) at audit time; both change-sets since committed (`ed43470`, `4fd0af6`) and pushed to origin; CI does not trigger on pushes to `feat/map-repair-align`.
3. **B3 rewritten** (§5) — package does *not* copy `image_map.json` verbatim: `load_image_map → to_dict()` round-trip drops **all `meta`** and silently re-defaults statuses; package-time validation calls `validate_image_map` **without** name-sets (unknown-name branch not even exercised; only duplicates/empty pairs can fail); cites moved (+12/+58 → ~246–252 / ~449–461); `package.py` no longer byte-unchanged (R4 status updated).
4. **B2/§7 `.268.4`** — "0 occurrences" refuted: one legitimate `.268.4` (ch268, 37 vs 156 chars, 2 text_diff spans) remains; the 1941/7220 monster row is gone and archived pre-repair.
5. **M2 (clean-JSON marker channel)** — "The `( N )` marker appears nowhere in `data/clean/*/*.json`" refuted: markers survive in `dropped_lines` (101/104 `PAGE_MARK_REMOVED` files; Tap1 vi021 `["- 19 - (266)"]`, Tap3 vi021/vi031/vi060 as quoted). No `marker` *field* exists (schema unchanged); nothing downstream consumes `dropped_lines` either. Also: `charalign.py:53–66` is `fold()`, not `norm_reading`; `qn_page_markers` written at `charalign.py:747`, read by nothing; fix regex validated empirically; `charstream.py` is the charalign-projected segmentation provider (`align.py:575–604`), not a cosegmentation feeder.
6. **§4 BIN_OVERRIDE attribution** — status wipe is unconditional at `layout.py:354` (all pages), not an override-block side effect; `BIN_OVERRIDE_*` guard is on `folder` — the cover p1 (folder=misc) *can* be re-binned (Tap1 inventory_misc includes 001).
7. **N1 narrowed** — `max_group`/`max_nm_group` are read live by the sentence DP (`align.py:91–92`, enforced `align.py:419–425`); dead only on the T1 page-map DP.
8. **`unverified_ratio` is not a stored metrics key** — 0.5358/0.4000 derive from `unverified_rows/total_rows` (441/823, 152/380) and match `UNVERIFIED_RATIO_HIGH` issue strings verbatim; Tap2 warning `NULL_ROW_RATIO_HIGH:1.0000`; Tap1/Tap3 also store `structural_confidence_mean` / `semantic_evidence_rows` / `evidence_insufficient_rows` (233 / 74).
9. **Misc cites** — `markers_scan.py` → `markers_all.txt`; `probe_dups.py` added; `BIN_OVERRIDE` post-insertion range `~339–348` → `~339–348`; R2's "reuse `norm_reading` folding" → "`fold()`".
10. **Backup facts** — `state.sqlite3.bak-2026-11-12-rebin-fix`: 1,015,808 B, 2026-11-12 19:36:40 (was "~19:36").

### 12.3 Not verified / caveats (2026-11-13)

- The 2026-11-12 pass count (282) cannot be re-measured retroactively; consistent with 291 = 282 + 9 verify-A tests. The original 277 is unmeasurable.
- The Tap3 `vi036` third `marker_issues` entry is corroborated by data (`0036.json` contains `( 10 )`/`( 11 )`; ch 12 ∉ ch inventory) but the repair tool was not re-run (off-limits).
- Tap1 `map_repair/summary.json` (old_pairs=127 propose-only) and the 124-pair pre-repair backup are mutually irreconcilable; the repair lineage cannot be established from data alone.
- Nothing under `data/` or the repo was written by any audit; SQLite read-only (`mode=ro`); no pipeline stage executed; no Kim Hán Nôm API calls; the image-page reads used only the read tool.

### 12.4 Still open (unchanged by this audit)

1. **0 `verified` pairs anywhere**; Tap2 is unrepaired (248/264, monotone +1 drift); Tap1 6 grouped double-absorbs; Tap3's 50 pairs and Tap1's 121 1:1 pairs pass marker arithmetic but carry `candidate` — no consumer treats `markers_used` as verification.
2. Tap1/Tap3 annotation backlog (~593 unverified rows), Tap1/Tap3 gates FAIL (coverage/unverified/SIMILARITY_BELOW_GATE), Tap2 gate empty; the missing-page detection & packaging completeness areas are out of scope here (see verify-C…I).
3. R1–R6 execution status is unchanged (R1 PARTIAL; R2–R6 NOT DONE); markers are still not wired into any gate; `package.py` still ships unadjudicated maps.
4. README staleness (57 tests, 2026-11-08 status block), `classification.json` staleness, decisions.md errata — all still open items to reconcile (verify-I's punch list).
5. Re-scan the §10 caveat list / §3 for marker-harvest automation: markers print on **every substantive QN page incl. title/TOC pages** (Tap1 vi013 `( 274 )` / vi020 `( 267 )` — §3 line 43 now annotated) — the earlier "printed in every QN body page" phrasing understated coverage; OCR-only harvest undercounts (4/18 sampled body pages lose the header; Tap2 has no OCR markers at all).

---

## 13. Implementation log (2026-11-13)

Executed the §6 fix plan (R1–R6), the §9 handoff checklist (where executable), and the `.268.4`-era hygiene items. Everything stays uncommitted on `feat/map-repair-align` (working tree only — see `git status`); no Kim Hán Nôm API calls were made; no confidential data left the machine; `data/` was rebuilt with timestamped backups first.

### 13.1 Code

- `t1_map.py`: new `build_marker_map` — deterministic bijection Nôm PDF = `vi_to_nom_offset` − vi PDF over the `ch`/`vi` inventories; every pair `status=verified`, `confidence=1.0`, `source=printed_marker`; leftover Nôm pages insert an explicit empty-vi `unresolved` pair at reading position (never dropped); `image_map.manual.json` still wins. `build_image_map` prefers the marker map when `vi_to_nom_offset` is configured, DP+anchors remains fallback; the hvdic offline cache (`char_readings.json`, 26,700 entries) is wired into anchor scoring (`_HvdicCacheAdapter`); `verified_min_coverage` recalibrated 0.5 → **0.08** per R2 (correct pairs measured min 0.061 / median 0.201); `validate_image_map` now enforces **coverage** (every ch/vi inventory page in a pair), **monotonicity** (vi ascending / ch descending, empty-side pairs excluded), and the **marker formula** fail-closed (grouped pairs and wrong 1:1 pairs rejected); `align_page_groups` honors `max_group` (4) / `max_nm_group` (2) from `configs/alignment.yaml` and allows n×m groups ≤ `max_nm_group`; `mapping_source=printed_marker`, `markers_used`, `marker_issues` recorded in `meta`.
- `layout.py`: back-matter TOC override never swallows blanks or `ch` pages; post-block Nôm-likely pages flagged **`NOM_AFTER_BACKMATTER`** (Tap2 p549) instead of silent; `BIN_OVERRIDE_*` applies deterministically to every non-`ch`, non-cover page (blanks included — matches delivered re-bin); `page.status = "classified"` only assigned when no non-default status exists (preserves `ocr_done`); `TOC_LIKELY_FRONT` is informational only (never re-labels).
- `clean.py`: `CleanedPage` gains `marker: int | None`; the Nôm printed page is captured at PAGE_MARK_REMOVED time (`_MARKER_LINE_RE` anchored to the `- N - (N)` shape so footnote parens never match); `data/clean/*/*.json` now carries it (Tap1 67 / Tap3 33 — exactly the OCR-provable marker count).
- `charalign.py`: `QN_HEADER_RE` tolerant (`^\s*-\s*\d{1,4}\s*[-–—]?\s*\(\s*(\d{2,4})\s*\)`) — now matches `-19\n( 104 )`, `- 58 - (65) x`, `- 2010 - (5) x` rejected; `read_image_map(..., honor_status=True)` skips `unresolved` pairs with `warnings.warn` (never silently used as band anchors).
- `package.py`: `<Book>_image_map.json` is copied **verbatim** (pairs + full `meta` — no more dropped `meta` or silent status re-defaults); `validate_book_package` runs `validate_image_map` against the actual `ch/`/`vi/`/`missing/` folders with `vi_to_nom_offset` as **errors** (coverage, order, dup/unknown names, marker formula).
- `configs/*.yaml`: `vi_to_nom_offset` added per book (289/549/127); Tap2 YAML re-bins vi273–275 to `misc/`; Tap1/Tap3 YAMLs declare pre-existing misc pages (145 / 64).
- Tests: `tests/test_marker_map.py` (13 functions) pins marker-map construction, bijection/validation/coverage/marker-formula rules, clean-QN marker extraction, tolerant regex, `read_image_map` status honor, config-honoring DP group limits — synthetic fixtures only (no book data in repo). **307 tests pass.** `.github/workflows/ci.yml` now also triggers on `feat/**`.

### 13.2 Data rebuilds (all with timestamped backups)

- Tap2 vi273–275 re-binned `misc/` (§backed up `data/state.sqlite3.bak-2026-11-13-verifyB-impl` before any data op; the p275 `ocr_done` status was briefly lost by the first surgery attempt and was restored — see decisions.md entry).
- `classification.json` regenerated (re-run after the layout fixes): Tap1 {ch130, vi130, misc16, blank6} **byte-identical bins**; Tap3 {ch50, vi50, misc12, blank6} **byte-identical**; Tap2 {ch264, vi264, misc4 (incl. 273–275), toc9 (541–549), intro2, blank7} with p549 flagged `NOM_AFTER_BACKMATTER`; Nôm runs identical ([147,276]/[277,540]/[67,116]).
- Maps rebuilt marker-wise: **Tap1 130/130 verified**, **Tap2 264/264 verified** (was 248/264 candidate heuristic; supersedes the 2026-11-12 content-DP maps for Tap1 and the byte-frozen 2026-11-08 artifact for Tap2), **Tap3 50/50 verified**; `vi_page_count` correct everywhere; pre-impl backups kept at `map_repair/image_map.pre-verifyB-impl.json` (Tap1/Tap2/Tap3).
- Clean re-run; align re-run: **Tap1 823 rows, Tap3 380 rows, Tap2 15 rows** (was 8; real Nôm↔QN pairing now lives in `review_metadata.jsonl`/CSV). text_diff re-computed; metrics archived (`metrics.20261113T*Z.json`) then re-evaluated (unchanged FAIL: Tap1 89.96 / Tap3 93.74; Tap2 85.71 / coverage 0.133 / null 0.33).
- Tap3 runaway nested `_pre-repair-2026-11-12/` **removed** (1,421 levels; three top-level artifacts preserved at `.../_pre-repair-2026-11-12-preserved/`; Tap1's single-level sibling kept).
- Decision log appended in `docs/decisions.md` (marker-formula maps; Tap2 re-bin; classification hardening; verify-A restore note; errata for the "0.7% gap" entry; Tap2 no longer EMPTY_DENOMINATOR).

### 13.3 Still open (not code)

- Tap2 Nôm OCR — weekly Kim Hán Nôm quota re-check at the weekly rollover (2026-11-16); until then re-run is blocked by quota.
- ~593 unverified rows await **human review** (`hannom review --book …`); both live books FAIL gates; Tap2 gate FAIL by OCR completeness.
- `configs/report.yaml` members, the four screenshots, the missing-page human sign-off note, the `_updated.pdf` hand-off (+notify), zip-name announcement, and the report `null`/`yellow` disclosures remain open human steps.
- verify-B §6 R5 residual: unifying `QN_TOKEN_RE` between `anchors.py`/`charalign.py` and unifying the folding functions — not executed (separate consistency decision).
- verify-B §6 R6 residual: dead code (`anchor_coverage`, `gaps`, `ratio_guard`) and the ignored `force` parameter in `classify_book` — not executed (documented, flagged).
- R2's full "≥2 unique anchors + marker agreement" cross-check on the DP path is wired but the DP path is unused by the assigned books (marker formula wins).


