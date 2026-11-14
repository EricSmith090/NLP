# Area H — Human-review governance & Stage 8 evaluation gates: verification report

> **REVISION 2026-11-12 (post map-repair change-set):** written against pre-`feat/map-repair-align` state; the collaborator's uncommitted 2026-11-12 change-set (image_map repair; Tap1/Tap3 scope re-bin; `hannom.charstream` dịch-âm segmenter; CSVs rebuilt (Tap1 727→823 / Tap3 341→380); variant fold in textdiff; labels regenerated; tests 277→282, all pass) is incorporated. Claims revised inline. Numbers re-measured read-only 2026-11-12.

> **Audience:** the next agent picking up work in this repo. No prior context assumed. All file paths are absolute from repo root `C:\Users\MSI VN\Desktop\NLP`.
> **Outcome in one line:** the gate code is honest and fail-closed, and **all three stored `metrics.json` files were re-audited (2026-11-12)** — but **the ≥95 % similarity / 0.9 coverage gates still FAIL on `T1_SuaLoiQuyen` and `T1_CamPhong_Tap1`**; similarity rose to **93.74 / 89.96** yet remains below 95, and coverage (**0.60 / 0.46**) and unverified-ratio (**0.40 / 0.54**) still breach their gates. Tap2 is unchanged and still fails with `EMPTY_DENOMINATOR`. The books are dịch-nghĩa books and the guideline (Quy_định_đồ_án_v2.1, p.21) only permits the criterion to be waived, not passed. **Review burden shrank from ~811 to 593 unverified rows — but the waiver question still comes first; do not burn review hours to "move the number" before it is settled.**
> **Ground rules honored:** read-only repo/data; no API calls; no `.env`/`hannom_API.md` reads; scratch only in `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H` (original 2026-11 probes) and `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-H` (2026-11-12 re-measurements); UTF-8 tooling only. `git status --porcelain` on `feat/map-repair-align` (HEAD `c3439e7`, zero new commits) shows the collaborator's **uncommitted** 2026-11-12 change-set (modified: `configs/alignment.yaml`, both book configs, `docs/decisions.md`, `src/hannom/align.py`, `config.py`, `layout.py`, `orchestrator.py`, `textdiff.py`; untracked: `src/hannom/charstream.py`, `src/hannom/map_repair.py`, `tests/test_charstream.py`, `tests/test_map_repair.py`, `tools/repair_image_map.py`, `Doc/verify-*.md`, pre-existing `submission/`). This revision is a documentation change and touches no code, config, or data.

---

## 1. Scope & files

**H₂ contents reviewed:**

| Area | Files |
|---|---|
| Evaluation / gates | `src/hannom/evaluate.py`, `src/hannom/models.py` (AlignmentRow, BookMetrics), `src/hannom/orchestrator.py` (`load_rows_for_evaluation` L452, `stage_evaluate` L480, `recompute_text_diff` L310, `learn_for_book` L292, `reconcile_for_book` L361), `configs/project.yaml` (`quality:`), `configs/review.yaml` |
| Human-review governance | `src/hannom/review_decisions.py`, `src/hannom/review_metadata.py`, `src/hannom/review/patches.py`, `src/hannom/review/app.py`, `src/hannom/dictionary/book_lexicon.py` (learning gate) |
| Data | `data/align/<book>/*.csv`, `data/align/<book>/*.review_metadata.jsonl`, `data/align/<book>/summary.json`, `data/evaluation/<book>/metrics.json` (+ archived `metrics.*.json` incl. pre-repair snapshots `metrics.20261112T120924Z.json` Tap1 / `metrics.20261112T120355Z.json` Tap3), `data/review/*` (**absent**) |
| Guideline | `Quy_định_đồ_án_v2.1.extracted.txt` (targeted p.16–21) |
| Appendices | `data/archive/*` (not a decision source — none found) |

**NEW module since the original write-up (2026-11-12 change-set):** `src/hannom/charstream.py` — the live dịch-âm segmenter; emits only `COSEGMENTED` / `COSEGMENTED_STREAM_ALIGNED` (+ `SPANS_PAGES` across pages) and **no longer emits `COSEGMENTED_ANCHORED` / `COSEGMENTED_UNANCHORED`** (both flag counts are now dead metrics — 0 rows carry them).

**Method:** `python -m pytest -q` (**282 passed**, 2026-11-12) + ~20 probe scripts in `verify-H/` (listed in §3; pre-repair, 2026-11) + 2026-11-12 re-measurement probes in `verify-revise-H/` (`cohorts2.py`, `allrows.py`, `appfilter2.py`, `csvcheck2.py`) + targeted reading of the pipeline (align → recompute → evaluate). Every empirical number below was measured by those probes, not eyeballed.

---

## 2. Method & ground rules

- Read-only everywhere except the single file you are reading now. Probes re-implement only the `stage_evaluate` call sequence (loader → restore sidecar → apply patches → apply decisions → `evaluate_rows`) and are discarded in `verify-H/`.
- The full dictionary index (`dictionaries-04-11-2026/entries/*.jsonl`, 2.7 GB incl. a 2.4 GB `catusf.jsonl`) was prepared with hvdic-only adapters for a re-score sanity check; `JsonlDictionary` lazy-loads. Numbers labeled "stored elements" are the authoritative ones.
- UTF-8 everywhere (`PYTHONIOENCODING=utf-8`). Vietnamese paths/fixtures rendered correctly in output files (cp1252 console mangles them — always pipe probes into an output file).
- **git state (2026-11-12):** branch `feat/map-repair-align`, HEAD `c3439e7`, zero new commits — the 2026-11-12 change-set is **uncommitted** collaborator work. This revision changes only this file; no probe leaked into the repo.
- **Pre-repair evidence preserved:** `data/align/<book>/_pre-repair-2026-11-12/` holds the pre-repair CSVs/sidecars of Tap1 and Tap3 (Tap3's is self-nested ~1,422 levels — see §12); `data/evaluation/<book>/metrics.20261112T120924Z.json` (Tap1) and `metrics.20261112T120355Z.json` (Tap3) hold the pre-repair metrics snapshots quoted in §3. Current `metrics.json` (mtimes 2026-11-12 19:43:40 Tap1 / 19:03:55 Tap3) reflects the rebuilt, re-aligned books.

---

## 3. EXACT reproduction of `data/evaluation/*/metrics.json`

### 2026-11-12 status — `metrics.json` is NOT bit-compatible with the pre-repair state (revised 2026-11-12)

`repro.py` (and the whole probe suite) run against the **current** data derive the **post-repair** numbers quoted below (89.9646 / 93.7385; three issues each; `UNVERIFIED_DIFFERENT_ROWS` 136/125). The pre-repair bit-for-bit reproduction is still possible, but **only** against the preserved pre-repair copies: restore `data/align/T1_CamPhong_Tap1/*.csv`, `*.review_metadata.jsonl` (and Tap3's) from `data/align/<book>/_pre-repair-2026-11-12/` into a scratch directory and point the probe at the copies — do **not** overwrite the live files. With those inputs the probe reproduces the archived snapshots `metrics.20261112T120924Z.json` (Tap1) and `metrics.20261112T120355Z.json` (Tap3) bit-for-bit. Intermediate re-align snapshots from 2026-11-12 (`metrics.20261112T122218Z.json` = 775 rows, `metrics.20261112T124340Z.json` = 782 rows) are retained as historical artifacts; the authoritative post-repair files are `metrics.json`.

### Reproduction method

```python
rows, blocking, audit = load_rows_for_evaluation(project, book)   # read-only
m = evaluate_rows(book.book_id, rows,
                  minimum_similarity=95.0, null_ratio_warn=0.05,
                  yellow_ratio_warn=0.05, minimum_coverage=0.9,
                  max_unverified_ratio=0.05,
                  integrity_issues=blocking, audit_diagnostics=audit)
```

Compared key-by-key against each stored `metrics.json` (probe: `repro.py`; pre-repair runs, retained for reference — printed values reflect the old data). Also ran the same per-flag/per-row analysis (`analysis.py`, `analysis2.py`, `sim.py`, `reddist.py`, `cohorts.py`, `appfilter.py`, `flatmatch.py`, `sidecar_check.py`, `csvcheck.py`, `boundary.py`, `boundary2.py`, `adversarial.py`, `hashbind.py`). 2026-11-12 re-measurements (cohorts, visibility, CSV audit) were run fresh in `verify-revise-H/` and are quoted inline.

### Bit-for-bit reproductions

**Tap1 `T1_CamPhong_Tap1` — post-repair state (revised 2026-11-12). EXACT vs current `metrics.json` (mtime 2026-11-12 19:43:40; align 12:43:30Z):**

```
total_rows=823  null_rows=0  scored_rows=381  verified_match=136  verified_difference=245
unverified_rows=441  unmatched_rows=1  coverage_ratio=0.4629404617253949
total_nom_chars=27976  denominator=7065  red_mismatch_chars=709  yellow_chars=0
similarity=89.96461429582449  yellow_ratio=0.0  null_ratio=0.0
issues=[INSUFFICIENT_COVERAGE:0.4629<0.9, UNVERIFIED_RATIO_HIGH:0.5358>0.05,
        SIMILARITY_BELOW_GATE:89.9646<95.0]
warnings=[UNVERIFIED_DIFFERENT_ROWS:136]
structural_confidence_mean=0.911492797508248  semantic_evidence_rows=823  evidence_insufficient_rows=233  decision_audit_diagnostics=[]
passed=False
```

(`evidence_insufficient_rows=233` = 232 unverified + the single `UNMATCHED_QN` null row `T1_Cấm Phòng Cho Bổn Đạo (Tập 1).100.1`, img `.100.jpg`, `QN_SENTENCE_NO_NOM:529` warning — the book's **only** non-1-1 row; `summary.json` warning. The 441 unverified rows are the union of `ALIGN_EVIDENCE_INSUFFICIENT` (232 unverified rows) and `DIFF_AMBIGUOUS_READINGS` (362): 79 + 209 + 153 both = 441 ✔.)

**Tap1 — pre-repair snapshot (archived 2026-11-12, `metrics.20261112T120924Z.json`) for the bit-for-bit reproduction command:**

```
total_rows=727  null_rows=124  scored_rows=8  verified_match=2  verified_difference=6
unverified_rows=594  unmatched_rows=1  coverage_ratio=0.011004126547455296
total_nom_chars=27976  denominator=182  red_mismatch_chars=23  yellow_chars=0
similarity=87.36263736263736  yellow_ratio=0.0  null_ratio=0.17056396148555708
issues=[INSUFFICIENT_COVERAGE:0.0110<0.9, UNVERIFIED_RATIO_HIGH:0.8171>0.05,
        EXCESSIVE_NULL_ROWS:0.1706>0.05, SIMILARITY_BELOW_GATE:87.3626<95.0]
warnings=[NULL_ROW_RATIO_HIGH:0.1706, UNVERIFIED_DIFFERENT_ROWS:2]
structural_confidence_mean=0.8054287388936219  semantic_evidence_rows=727  evidence_insufficient_rows=692  decision_audit_diagnostics=[]
passed=False
```

**Tap3 `T1_SuaLoiQuyen` — post-repair state (revised 2026-11-12). EXACT vs current `metrics.json` (mtime 2026-11-12 19:03:55; align 12:03:37Z):**

```
total_rows=380  null_rows=0  scored_rows=228  verified_match=125  verified_difference=103
unverified_rows=152  unmatched_rows=0  coverage_ratio=0.6
total_nom_chars=8560  denominator=3274  red_mismatch_chars=205  yellow_chars=0
similarity=93.73854612095296  yellow_ratio=0.0  null_ratio=0.0
issues=[INSUFFICIENT_COVERAGE:0.6000<0.9, UNVERIFIED_RATIO_HIGH:0.4000>0.05,
        SIMILARITY_BELOW_GATE:93.7385<95.0]
warnings=[UNVERIFIED_DIFFERENT_ROWS:125]
structural_confidence_mean=0.9622084765740814  semantic_evidence_rows=380  evidence_insufficient_rows=74  decision_audit_diagnostics=[]
passed=False
```

(152 unverified = union of `ALIGN_EVIDENCE_INSUFFICIENT` (74) and `DIFF_AMBIGUOUS_READINGS` (120): 32 + 78 + 42 both = 152 ✔.)

**Tap3 — pre-repair snapshot (archived 2026-11-12, `metrics.20261112T120355Z.json`) for the bit-for-bit reproduction command:**

```
total_rows=341  null_rows=98  scored_rows=26  verified_match=7  verified_difference=19
unverified_rows=217  unmatched_rows=0  coverage_ratio=0.07624633431085044
total_nom_chars=8560  denominator=368  red_mismatch_chars=52  yellow_chars=0
similarity=85.86956521739131  yellow_ratio=0.0  null_ratio=0.2873900293255132
issues=[INSUFFICIENT_COVERAGE:0.0762<0.9, UNVERIFIED_RATIO_HIGH:0.6364>0.05,
        EXCESSIVE_NULL_ROWS:0.2874>0.05, SIMILARITY_BELOW_GATE:85.8696<95.0]
warnings=[NULL_ROW_RATIO_HIGH:0.2874, UNVERIFIED_DIFFERENT_ROWS:7]
structural_confidence_mean=0.8060002229611297  semantic_evidence_rows=341  evidence_insufficient_rows=283  decision_audit_diagnostics=[]
passed=False
```

**Before/after delta (both books):** issue set shrank from 4 → **3** (`EXCESSIVE_NULL_ROWS` / `NULL_ROW_RATIO_HIGH` are **gone** — `null_ratio=0.0` in both); `UNVERIFIED_DIFFERENT_ROWS` 2→136 / 7→125; similarity +2.60 / +7.87 points; coverage ×42.1 / ×7.9. `passed=False` either way.

**Tap2 `T1_CamPhong_Tap2` — DIVERGES (stale artifact)**

Stored `metrics.json` (written 2026-11-08 20:02; current schema predating the sidecar-aware loader; **unchanged 2026-11-12** — Tap2 is not part of the re-align):
```
{total_rows=8, null_rows=8, scored_rows=0, denominator=0, similarity=null,
 null_ratio=1.0, issues=[EMPTY_DENOMINATOR], warnings=[NULL_ROW_RATIO_HIGH:1.0000], passed=false}
```
Missing: `coverage_ratio`, `verified_*_rows`, `unverified_rows`, `unmatched_rows`, `decision_audit_diagnostics`, `evidence_insufficient_rows`, `semantic_evidence_rows`, `structural_confidence_mean`.
Recomputed on current code: same 8/8 nulls → `EMPTY_DENOMINATOR`, plus **`METADATA_SIDECAR_MISSING:T1_Cấm Phòng Cho Bổn Đạo (Tập 2).review_metadata.jsonl`, 8×`METADATA_MISSING:<sid>`**, `INSUFFICIENT_COVERAGE:0.0000<0.9`, `EXCESSIVE_NULL_ROWS:1.0000>0.05` (blocking, `METADATA_`/`REVIEW_METADATA_` prefixes). `passed=False` either way. **Tap2 has no sidecar and never will unless re-aligned** (alignment summary: 8 rows; 525 `MISSING_CLEAN_PAGE` warnings, pages .010–.541 missing — OCR is the prerequisite, not review). **Tap2 DOES have a `metrics.json`** (this section's artifact, and F5) — any claim that it does not is a misreading; there is, however, **no Tap2 `metrics.*.json` archive** (the identically 369-byte `metrics.20261112T035909Z.json` lives in Tap1's directory and is Tap1's own 6-row pre-governance artifact — not a Tap2 twin, as the pre-2026-11-12 text of this section wrongly implied).

---

## 4. Gate semantics — empirically verified

### 4.1 Row classification precedence (`_classify_row`, evaluate.py L105–161)

| Inputs | Outcome | Confirmed by probe |
|---|---|---|
| `review_status == unmatched`, `decision_integrity=="valid"` | `unmatched` | ✔ |
| same, integrity≠valid | `unverified` | ✔ |
| verifying status (`alignment_reviewed` / `accepted_match` / `accepted_difference`), integrity valid, `elements is None` | `unverified` + `REVIEW_DECISION_MISMATCH:<sid>` (BLOCKING issue) | ✔ probed |
| verifying status, integrity valid, elements invalid (`validate_text_diff` fails) | `unverified` + `REVIEW_DECISION_MISMATCH` | ✔ |
| `accepted_match` with non-empty elements | `unverified` + `REVIEW_DECISION_MISMATCH` | ✔ probed |
| `accepted_difference` with `elements==[]` | same | ✔ |
| `alignment_reviewed`, elements empty / non-empty | `verified_match` / `verified_difference` | ✔ |
| `unresolved` / `rejected` | `unverified` | ✔ |
| `content_edited` | falls through to automatic path (grants nothing) | ✔ |
| Automatic: `UNMATCHED_NOM`/`UNMATCHED_QN` in flags | `unmatched` (beats null) | ✔ |
| Automatic: `elements is None` | `null` | ✔ |
| Automatic: invalid elements | `unverified` | ✔ |
| Automatic: `flags ∩ UNVERIFIED_FLAGS ≠ ∅` | `unverified` | ✔ |
| Automatic: elements non-empty, no unverified flag | `verified_difference` | ✔ |
| Automatic: `elements==[]`, no unverified flag | `verified_match` | ✔ |

### 4.2 Fail-closed integrity blocking

- Loader issues normalized: `"sidecar went sideways"` → `METADATA_sidecar went sideways` (kept blocking); `REVIEW_METADATA_UNRESOLVED:whatever` passes through unchanged (both block via `METADATA_` / `REVIEW_METADATA_` prefixes) — probed.
- Log-wide decision failure (unparseable JSON / `DECISION_NOT_OBJECT` / empty `sentence_id` etc.) → `DECISION_LOG_INVALID:<line>:<err>` in `apply_decisions` (review_decisions.py L612–614) → blocks gate (prefix `DECISION_`) — probed: gate `passed=False` even with all rows otherwise clean. `learn_for_book` correctly **skips learning book-wide** when `any(failure.sentence_id is None)` (orchestrator.py L292–307); `reconcile_for_book` does the same (orchestrator.py L361–386).
- Duplicated `sentence_id` → `DUPLICATE_SENTENCE_ID:<sid>` per row, prefix in `BLOCKING_PREFIXES` → gate blocked. Probed. **Zero duplicates** in the three CSVs (re-verified on the 2026-11-12 rebuilt CSVs: Tap1 823 / Tap3 380 / Tap2 8 rows, 0 duplicates; 0 empty `img_id`; 0 non-NFC fields). `text_diff` cells all parse to list/null (**re-measured 2026-11-12**: Tap1 `array` 822 = 650 with error elements + 172 `[]` / null 1 / unparseable 0; Tap3 `array` 380 = 224 non-empty + 156 `[]` / null 0 / unparseable 0; Tap2: null 8/8). CSVs are NFC-clean, all `text_diff` cells parse to list/null.

### 4.3 Boundary probes (all pass decisively; `passed` blocks on any of)

| Probe | Result |
|---|---|
| similarity exactly 95.0 (red=1, den=20) | `passed=True` |
| similarity 90.0 | `passed=False`, `SIMILARITY_BELOW_GATE` appended |
| coverage exactly 0.900 (9/10 rows) | `passed=True` |
| coverage 0.800 | `passed=False`, `INSUFFICIENT_COVERAGE` |
| unverified 0.05 (1/20) | allowed at `max_unverified_ratio=0.05` boundary |
| unverified 2/21 = 0.095 > 0.05 | `passed=False`, `UNVERIFIED_RATIO_HIGH` |
| null exactly 0.05 | NOT blocked (`EXCESSIVE_NULL_ROWS` uses `>`) |
| `NO_ROWS` book | `passed=False` |
| `EMPTY_DENOMINATOR` (all rows null) | `similarity=None` → `passed=False` |
| yellow exclusion | warn chars leave `denominator` entirely; `yellow_ratio>0.05` → warning only, **never blocks** |

`metrics.passed=False` is reached via `similarity is None` / `<95` / `coverage<0.9` / `unverified>0.05` / `null>0.05` / any `BLOCKING_PREFIXES` issue (evaluate.py L326–337). `SIMILARITY_BELOW_GATE` deliberately is *not* in `BLOCKING_PREFIXES` (evaluate.py L87–98) but affects `passed` directly — safe. `metrics.decision_audit_diagnostics` (default `[]`) is included in the JSON but **never blocks**.

### 4.4 Decision-log replay — semantics all verified correct

- **File order (append position) wins over timestamps**; timestamps are cosmetic, never used for selection (review_decisions.py L590–608, `parse_decisions` assigns `log_line` L530).
- **Latest event wins, including failure supersession**: valid@1 + failure@2 → row invalid, **no fallback** (probe 1) ✔; failure@1 + valid@2 → row **valid**, failure recycled into `audit` as `DECISION_SUPERSEDED` (probe 2) ✔; valid old decision + any newer invalid event → stale/invalid (probe 3) ✔.
- **Same-revision** `accepted_match` vs `accepted_difference` → `REVIEW_DECISION_CONFLICT` (only same-hash decisions are eligible, review_decisions.py L678–685) ✔; cross-revision (content patch → new hash) legitimate, no conflict (probe 5) ✔; superseded same-revision conflict stays conflict only while the latest event is conflicted ✔.
- **Element-consistency contradiction keeps `decision_integrity="valid"`** and is gate-blocked solely via the emitted MISMATCH issue (evaluate.py L250–254, L334–336); the flag itself is **never set on the row** (only `REVIEW_DECISION_STALE`/`INVALID`/`CONFLICT` reach `row.flags`, review_decisions.py L716) — consequence: see F7.
- **An active log-wide failure does NOT downgrade row `decision_integrity`; it blocks the gate as a list-level issue** — semantically correct (there is no row to attribute it to), learning disabled for the book, gate still blocked ✔.
- Timestamps absent / reordered / duplicated: file order still authoritative ✔ (code-read; `event[0]==log_line` stable sort, provenance-less records sort first — documented L606–607).

---

## 5. ZERO human decisions; gates; full-review bounds (revised 2026-11-12)

**Fact: `data/review/` still does not exist — anywhere (re-verified 2026-11-12).** A recursive search for `*.review_decisions.jsonl` and `*.patches.jsonl` across `data/`, `artifacts/`, `submission/` returns nothing. (The Tap3 `_pre-repair-2026-11-12/` quagmire — ~1,422 self-nested directories, 3 files — had to be **pruned** during the walk; an unpruned traversal dies with Win32 `PathTooLongException`. See §12.) **Zero human decisions anywhere; every `verified_*` row below is machine-labeled** (dictionary evidence / semantic-confidence bands; book lexicon learned **0** pairs on the 2026-11-12 run: `skipped_unreviewed=823` Tap1 / `380` Tap3).

- Tap1: verified **381/823 = 46.29 %** coverage (136 match + 245 difference); **100 % machine-automatic**. Tap3: **228/380 = 60.00 %** (125 match + 103 difference), all automatic. (Pre-repair: 8/727 = 1.10 % and 26/341 = 7.62 %.)
- **Coverage ceilings (revised):** the pre-repair "null-cap" argument is **dead for Tap1/Tap3** — Tap3 now has **0 null rows** (380/380 `text_diff` arrays); Tap1 has exactly **1** non-1-1 row (`skip_qn` / `UNMATCHED_QN`, img_id `…100.jpg`, sentence `.100.1`, `text_diff=null`, warning `QN_SENTENCE_NO_NOM:529`) — and decisions can never verify a `text_diff==null` row (verifying status + `elements is None` → unverified + MISMATCH), so Tap1's ceiling is **822/823 = 99.88 %**, Tap3's is **100 %**. **Tap2 remains capped at 0 %.** Both Tap1/Tap3 ceilings clear 0.9 → the coverage gate is now **attainable** given review labor and no content fixes (pre-repair this was impossible: 82.95 % / 71.26 %).
- Even assuming **every row were reviewed and accepted as-is** (no content fixes), re-measured on the rebuilt data (all array rows; scoreable basis; `red_penalty` over error spans):
  - Tap3: denominator 8414, red 1052 → **similarity ≈ 87.5 %** (was ≈ 49.5 %).
  - Tap1: denominator 27820, red 8111 → **similarity ≈ 70.8 %** (was ≈ 28.9 %).
  - (Tap1's single null row is excluded, consistent with `evaluate.py` scoring non-null rows only.)
- Required to hit ≥95 **on this full re-scored basis**: red ≤ 420 (Tap3 — eliminate **60.1 %** of red), ≤ 1391 (Tap1 — eliminate **82.9 %** of red). On the **stored gate basis** (`evaluate.py:302–305` scores *verified* rows only — Tap1 `denominator=7065 red=709`, Tap3 `denominator=3274 red=205`): Tap1 red ≤ **353** (eliminate **50.2 %**), Tap3 red ≤ **163** (eliminate **20.5 %**; 164 would score 94.99 < 95, so 163 is the binding bound). Neither is achievable by verification; requires the §8-1 waiver discussion or a data rework (F1, §9). (Pre-repair full basis: Tap3 ≤ 428 of denominator 8560 / Tap1 ≤ 1394 of denominator 27880 — the much larger required cuts quoted in the pre-repair text of this section.)
- hvdic+flat-match re-score of every 1-1 row (pre-repair probe; **not re-executed 2026-11-12** — Tap1 similarity rose anyway, from 87.36 to 89.96 stored / ≈70.8 full basis, yet remains < 95) changes the conclusion not at all → **it is the content (dịch-nghĩa), not the matcher**.
- Red/nom ratio ≥ 0.8 (among rows with error elements): Tap3 **2/224** rows (was 187/243), Tap1 **32/650** rows (was 535/602). `red/nom < 0.05`: Tap3 38, Tap1 80. Error spans cover nom chars: Tap3 1031/8414 (**12.3 %**), Tap1 6914/27820 (**24.9 %**). QN syllables in error spans: Tap3 415, Tap1 3145. (Pre-repair span stats — 75.7 %/82.9 % coverage — reflected pre-repair misaligned spans and are obsolete.)
- **Identical ch/vi rows: 0** (scripts differ always) — the "bulk black rows" cohort still does not exist. Yellow chars: **0** stored for both books (pre-repair: "nonzero but tiny; 0 currently used" — now measurably none).

---

## 6. Findings F1–F15 (severity-ranked, with file:line)

### F1 — CRITICAL — Similarity gate is still unattainable on this content (revised 2026-11-12)
`evaluate.py:302–305` (similarity formula), `:338–341` (SIMILARITY_BELOW_GATE), `textdiff.py:615–626` (`red_penalty` = max(nom_chars, qn_syllables) per error span — line cites shifted +15 by the 2026-11-12 change-set), `textdiff.py:603–612` (`scoreable_nom_chars` excludes only warn/MASK). The change-set also added **diacritic-variant weak matching** (quỷ/quỉ/quĩ → qui, d/gi, đ/d) as a 1.0-cost NW cell (never strong, never rewrites text — variant fold, `docs/decisions.md` 2026-11-12 entry) — this narrowed the gap (stored similarity 87.36→**89.96** / 85.87→**93.74**) but did not move the gate. Guideline: `Quy_định_đồ_án_v2.1.extracted.txt` p.21 (`độtương đồng = (1 – Σchữ đỏ / Σchữ Nôm tính điểm) × 100`; scores computed only for `text_diff` non-null rows; yellow only for proper names/years, illegible-Nôm predictions, lost-page cases; **"Yêu cầu độtương đồng … có thể thay đổi để phù hợp với tính chất và tình trạng của sách được giao"**). Zero review decisions change the red/nom characteristics of the book → the 95 % target is structurally unreachable without a signed-off criterion change. **Both books still fail `SIMILARITY_BELOW_GATE:89.9646` / `:93.7385` — policy blocker, not an engineering task.** (Code unchanged in this area; verdicts stand.)

### F2 — CRITICAL — Coverage gate: null-cap dead for Tap1/Tap3; waiver still required (revised 2026-11-12)
Null rows never verify (F3-adjacent contradiction rule, evaluate.py L130–133, L153–154). **Ceilings: Tap3 100 % (0 null rows), Tap1 822/823 = 99.88 % (exactly one non-1-1 row — `skip_qn`/`UNMATCHED_QN`, img `.100.jpg`, `QN_SENTENCE_NO_NOM:529`), Tap2 0 %.** The pre-repair "gate impossible while nulls are kept" ruling no longer binds for Tap1/Tap3; `textdiff --force-recompute` is relevant only to Tap1's single row and would still violate the guideline's "n-m ⇒ text_diff = null" rule (Quy_định p.17) — **do not run it for this**. The **waiver conversation (F1) is still required** — both books fail `INSUFFICIENT_COVERAGE` (**0.4629** / **0.6000**) and `UNVERIFIED_RATIO_HIGH` (**0.5358** / **0.4000**) — but the review burden is now **593 unverified rows** (Tap1 441 + Tap3 152; was ~811), and Tap1 needs ≥**741** of 823 verified (was ≥655 of 727), Tap3 ≥**342** of 380 (was ≥307 of 341); unverified must fall to ≤**41** (Tap1) / ≤**19** (Tap3) at the 0.05 boundary (41/823 = 0.0498; 19/380 = 0.0500 exactly — allowed, since the gate triggers only on `>`; the pre-repair bounds were ≤36/≤17; a targeted stricter goal of ≤36/≤17 is also sufficient). Tap2 needs OCR first regardless. If n-m rows *were* recomputed (Tap2 scenario), every converted row is `elements=[]` + `DIFF_UNVERIFIED_NO_BOOK_READINGS` (no readings available; `recompute_text_diff` adds it, orchestrator.py L339–358 + textdiff L380–395), i.e. still unverified until a human attests it — there is no automatic path out.

### F3 — HIGH — Streamlit app can record self-contradictory blocking decisions with no same-revision recovery
`app.py` is unchanged in the 2026-11-12 change-set — this finding and every line cite below stand (re-verified; `review_decisions.py`, `evaluate.py` unchanged). (Revised 2026-11-12: unchanged.)
Path: `app.py` accept buttons L347–361 (`accept_match`/`accept_diff`) → `_record_decision` L283–307 → `make_decision` (review_decisions.py L407–447) — which **validates only structure** (schema, status, sha, timestamp, mapping set) + row-bound mapping evidence, **not element consistency**. So `accepted_match` with red elements → gate-blocking `REVIEW_DECISION_MISMATCH` (evaluate.py L334–336) yet `decision_integrity="valid"`; a follow-up `accepted_difference` on the same revision then fires **same-revision conflict** (review_decisions.py L678–685) → **permanently blocked until a content patch (new hash) or an `alignment_reviewed` decision is used.** Infinitely repeatable via the UI; app displays "Đã ghi quyết định … thành công". Fix: element-consistency precondition inside `make_decision` (or in the app before it), see §9-1.

### F4 — HIGH — `content_sha256` binds the raw diff JSON string, not canonical content
`review_decisions.py:123–131` hashes the literal `diff_json` string; `models.py:131–137` (`text_diff_json`) emits canonical JSON — meaning `[{"vi_sub_text":…,"vi_pos":…,"nom_sub_text":…,"nom_pos":…}]` pretty-printed yields a **different** hash. The **save** path calls `_record_decision("content_edited", ch_txt, vi_txt, diff_json)` (app.py L340) with the **raw form string** ⇒ a pasted-but-semantically identical diff creates a `content_edited` decision that is **born stale** (empirically: `decision_integrity="stale"`, active `REVIEW_DECISION_STALE:<sid>`) — an edit decision that blocks the gate until another decision supersedes it. The accept_* paths are correct because they pass `row.text_diff_json()` verbatim (unsaved edits never leak into the hash — confirmed). Fix: parse + canonical re-serialization before hashing (§9-2). Sig: `content_sha256(ch_txt, vi_txt, text_diff_json)` should normalize `diff_json` (parse → `to_dict()` round-trip) or hash the element list directly. (Code unchanged 2026-11-12 — verdict stands; `review_decisions.py`, `models.py`, `app.py` all untouched by the change-set.)

### F5 — MEDIUM — Tap2 stored metrics are pre-governance artifacts
`data/evaluation/T1_CamPhong_Tap2/metrics.json` (2026-11-08 20:02; **Tap2 has no sibling archive** — the same-size `metrics.20261112T035909Z.json` belongs to Tap1 and is Tap1's own 6-row pre-governance artifact, not a Tap2 twin): missing all newer fields, hides the sidecar blocker (`METADATA_SIDECAR_MISSING`), and misstates the gate state (`similarity=null`, `EMPTY_DENOMINATOR`, `null_ratio=1.0`, 8 rows, 525 `MISSING_CLEAN_PAGE` in `summary.json`). Current code on the same data: `METADATA_SIDECAR_MISSING`, 8×`METADATA_MISSING`, `EMPTY_DENOMINATOR`, `INSUFFICIENT_COVERAGE`, `EXCESSIVE_NULL_ROWS` → blocked. Tap2 cannot ship as-is. Re-align Tap2 (with the missing-pages remediation tracked elsewhere) or explicitly drop it from the gate with a written note. (Unchanged 2026-11-12 — Tap2 was deliberately outside the re-align.)

### F6 — MEDIUM — `UNVERIFIED_FLAGS` contains a dead entry; or: silent auto-verified rows with zero red-span evidence
`evaluate.py:69–85` lists `DIFF_UNVERIFIED_DIFFERENT_TEXT`, but every emitting path puts it **Review-reasons-side**: `textdiff.py:551–552` (`review.append("DIFF_UNVERIFIED_DIFFERENT_TEXT")` — line cites shifted +15/16 by the 2026-11-12 change-set), and `orchestrator.py:352` stores review reasons as `"REVIEW:" + reason` ⇒ rows carry **`REVIEW:DIFF_UNVERIFIED_DIFFERENT_TEXT`**, never the bare flag ⇒ the UNVERIFIED_FLAGS entry never fires. Consequence (re-measured 2026-11-12 on the rebuilt data): rows with **no detectable mismatch and ch≠vi** (always) auto-verify as `verified_match` while carrying only an advisory REVIEW marker — **Tap1 136/136** and **Tap3 125/125** of the respective `verified_match` cohorts (the old text's row IDs — `…199.3`, `…175.5`, Tap3 `116.2…` — are stale; locate current ones by filtering sidecar `DIFF_NO_READING_MISMATCH` ∧ no unverified driver). Additionally, the `DIFF_NO_READING_MISMATCH` population (**172** Tap1 / **156** Tap3) splits exactly: **136 / 125 verified_match** + **36 / 31 empty-elements unverified** (those carry `ALIGN_EVIDENCE_INSUFFICIENT` and/or `DIFF_AMBIGUOUS_READINGS`). Decide deliberately: either normalize `REVIEW:` markers as blockers (hard fail), or delete the dead flag and **document** that REVIEW: flags are advisory only — but be aware the guideline-equivalent statement ("không được gì nếu chỉ có cấu trúc" — actually these rows have dictionary anchors, they are not structure-only) still hinges on this silent policy. (Code unchanged; counts updated 2026-11-12.)

### F7 — MEDIUM — Verifying decision with element contradiction can still feed `learn_from_rows` Path B
`evaluate.py:250–254` returns the `REVIEW_DECISION_MISMATCH` contradiction as a **metrics-issue only**; `row.flags` never gains the flag (evaluate never sets it). `apply_decisions` sets `REVIEW_STATUS_ACCEPTED_MATCH`-type flags for valid states (review_decisions.py L705). The lexicon's `BLOCKING_FLAGS` (book_lexicon.py L66–84) **does list `REVIEW_DECISION_MISMATCH`** (L82) but no producer ever sets it ⇒ a 1↔1 character row attested `accepted_match` against a non-empty red diff is gate-blocked yet passes Path B learning (`learn_from_rows`, book_lexicon.py L618–634, requires `integrity=="valid"` + 1 nom char + 1 QN token + no BLOCKING_FLAGS). Fix: set the row flag in the contradiction branch (or skip learning for rows with MISMATCH issue) — §9-3. (Code unchanged 2026-11-12. Note: the 2026-11-12 run learned **0** pairs anyway — `summary.json`: `learned_pairs=0`, `skipped_unreviewed=823`/`380`, `quarantine.legacy_without_provenance_*` 77/47 Tap1, 22388/586 Tap3.)

### F8 — LOW — `OCR_ENGINE_DISAGREE` can never reach a row's flags
(Code unchanged 2026-11-12 — verdict stands.)
Emitted only at page level (`ocr/agreement.py` L71, `ocr/router.py` list inclusion) and consumed as page warnings; no code path propagates it into alignment rows. A page whose two engines disagreed can produce an auto-verified row as long as dictionary readings coincide — **acceptable today** (row gate keys on reading evidence, not OCR agreement), but the reviewer UI therefore cannot surface "untrustworthy image" provenance. Suggest an *informational* (non-blocking) flag or report aggregate (§9-7).

### F9 — LOW — `validate_mapping_set` does not type-check positions
(Code unchanged 2026-11-12 — verdict stands.)
`review_decisions.py:207–264`: `mapping.nom_position < 0` works for bools (`True < 0` is False); duplicate detection granularity is set-level but positions are never `isinstance(int)`-checked here. Production data flows only through `CharacterTokenMapping.from_dict` (positions rejected if bool / float / `0.8` / `"0"` — verified), so this is defense-in-depth, not a hole. Add the check in `validate_mapping_set` itself (§9-8).

### F10 — LOW/MEDIUM — `hannom textdiff` rescoring rewrites the canonical CSV+sidecar in place, with no backup and no patch record
Command chain: load (CSV already includes patched content) → `recompute_text_diff` → `write_alignment_csv` (cli.py L249–257; cli.py unchanged in the change-set) — `write_alignment_csv` rewrites the CSV **and** the sidecar atomically together (`review_metadata.py:102–133`, `align.py:668–694` — shifted +72 by the change-set; auto_text_diff call site `align.py:528`, was 497), which is self-consistent (hashes recomputed on what's written), but `/data/` is **gitignored** — the previous auto-generated diffs are **irreversibly lost**, and n-m 1-1 re-casting is silently applied. **2026-11-12 is a live example:** the align/evaluate stages rewrote both books' CSVs/sidecars/metrics on 12:03/12:43Z (align) and 19:03/19:43 local (evaluate; automatic timestamped metrics backups). The pre-repair evidence now survives **only** in `data/align/<book>/_pre-repair-2026-11-12/` and the archived metrics snapshots — back up `data/align/<book>/*.{csv,review_metadata.jsonl,summary.json}` before **any** further rescoring; otherwise you destroy the align-time evidence you may later need to justify the yellow/patch decisions.

### F11 — LOW — Review app: filter gap, no bulk actions
`app.py:125–139` (`only_flagged` filter L125–136 — app.py unchanged): prefix list `("ALIGN_LOW_CONF","DIFF_","REVIEW:","OCR_","BBOX_","REVIEW_METADATA_","UNMATCHED_","REVIEW_DECISION_")` + `REVIEW_STATUS_UNRESOLVED/REJECTED`. **Missing**: `ALIGN_EVIDENCE_INSUFFICIENT` (now the **#1 unverified driver** — 233/74 rows), `SPANS_PAGES` (126/42), `NON_ONE_TO_ONE`, `TEXT_DIFF_NULL_NON_ONE_TO_ONE`. (`COSEGMENTED_UNANCHORED` is dead — 0 rows; remove it from the keeper list rather than add it.) Measured re-check 2026-11-12 (`appfilter2.py`): **0 unverified rows are invisible** (Tap1 441 + Tap3 152; visibility currently rides on `DIFF_READINGS_FROM_DICTIONARY` / `DIFF_AMBIGUOUS_READINGS` `DIFF_*` prefixes, not on the missing keepers), but the filter cannot express "only ALIGN_EVIDENCE_INSUFFICIENT" per-flag and offers **no multi-select and no bulk-accept**, forcing **~441 (Tap1) / ~152 (Tap3) — 593 total (was ~718 / ~315)** individual button presses. Add per-flag multi-select + bulk-accept (attestation checkbox + one `make_decision` per row — never a shared decision/hash across rows) and add `ALIGN_EVIDENCE_INSUFFICIENT` to the keeper list so visibility no longer depends on `DIFF_*` luck. (`pending_diff` from "Thêm span màu" is RAM-only and never persisted until the reviewer pastes it into the `text_diff` box and saves — verified; no unbounded growth risk in practice.)

### F12 — INFO — Governance is fail-closed by design and the reporting surface is honest
Yellow ratio is `0.0` for both books, reported; **null ratio `0.0` / `0.0`** for both (post-repair — was `0.2874` / `0.1706`; both books now report **no** `EXCESSIVE_NULL_ROWS` / `NULL_ROW_RATIO_HIGH`); `report.py` prints both (L278–332); `evidence_insufficient_rows` **233 / 74**, `semantic_evidence_rows` **823 / 380** visible in metrics; `structural_confidence_mean` **0.9115 / 0.9622** — all aggregates are disclosed, none can block, none is silently consumed by the gate; `decision_audit_diagnostics=[]` never blocks. Both books fail loudly and `passed=False`, with exactly **3 issues** each (`INSUFFICIENT_COVERAGE`, `UNVERIFIED_RATIO_HIGH`, `SIMILARITY_BELOW_GATE:89.9646` / `:93.7385`) listed explicitly — `SIMILARITY_BELOW_GATE` listed explicitly in both.

### F13 — INFO — `UNVERIFIED_FLAGS` completeness audit (all flags any code path can set on a row) — rebuilt 2026-11-12

Current sidecar histogram (re-measured 2026-11-12; Tap1 / Tap3):

| Flag | Tap1 | Tap3 | In `UNVERIFIED_FLAGS`? |
|---|---|---|---|
| `COSEGMENTED` | 823 | 380 | no |
| `COSEGMENTED_STREAM_ALIGNED` | 823 | 380 | no |
| `ALIGNED` | 822 | 380 | no |
| `DIFF_READINGS_FROM_DICTIONARY` | 821 | 379 | no |
| `DIFF_READING_MISMATCH` | 650 | 224 | no |
| `DIFF_REVIEW_RECOMMENDED` | 650 | 224 | no |
| `REVIEW:DIFF_SEMANTIC` | 650 | 224 | no |
| `DIFF_AMBIGUOUS_READINGS` | 362 | 120 | **YES** — unverified driver (153 / 42 rows also carry `ALIGN_EVIDENCE_INSUFFICIENT`) |
| `ALIGN_EVIDENCE_INSUFFICIENT` | 233 | 74 | **YES** — unverified driver (232 unverified + Tap1's 1 null row / 74 unverified) |
| `DIFF_NO_READING_MISMATCH` | 172 | 156 | no (but see F6: each carries `REVIEW:DIFF_UNVERIFIED_DIFFERENT_TEXT`) |
| `REVIEW:DIFF_UNVERIFIED_DIFFERENT_TEXT` | 172 | 156 | no (REVIEW-marker; bare flag dead — F6) |
| `SPANS_PAGES` | 126 | 42 | no (103 / 29 unverified) |
| `ALIGN_LOW_CONF` | 39 | 4 | no (38 / 4 unverified) |
| `DIFF_UNKNOWN_NOM_CHARS` | 7 | 4 | no (5 / 4 unverified) |
| `REVIEW:DICT_MISS` | 7 | 4 | no |
| `REVIEW:DIFF_UNKNOWN_RUN` | 5 | 1 | no |
| `NON_ONE_TO_ONE` | 1 | 0 | no |
| `TEXT_DIFF_NULL_NON_ONE_TO_ONE` | 1 | 0 | no |
| `UNMATCHED_QN` | 1 | 0 | no — but automatic path ⇒ class `unmatched` (beats null; evaluate.py automatic branch) |
| `QN_SENTENCE_NO_NOM` (warning, not a row flag) | 1 (`:529`) | 0 | n/a |
| `COSEGMENTED_UNANCHORED` / `COSEGMENTED_ANCHORED` | **0** | **0** | **YES — DEAD: no producer** (the old DP-anchor segmenter was replaced by `hannom.charstream` 2026-11-12); remove from the set or document as reserved |

| Status | Flags | Verdict |
|---|---|---|
| In UNVERIFIED_FLAGS, present in data | `ALIGN_EVIDENCE_INSUFFICIENT` (233/74 rows; 232/74 unverified + 1 Tap1 null row), `DIFF_AMBIGUOUS_READINGS` (362/120, all unverified) | Correct: the only genuine row-blocking categories today (Tap1: 79 insuff-only + 209 ambig-only + 153 both = 441 ✔; Tap3: 32 + 78 + 42 = 152 ✔) |
| In UNVERIFIED_FLAGS, reachable | `TEXT_DIFF_INVALID` | Correct |
| In UNVERIFIED_FLAGS, reachable via decisions/sidecar | `REVIEW_DECISION_STALE/MISMATCH/INVALID/CONFLICT`, `REVIEW_METADATA_MISSING/MISMATCH/UNRESOLVED` | Correct |
| In UNVERIFIED_FLAGS, 0 rows today | `DIFF_UNVERIFIED_NO_BOOK_READINGS` (blocks when a 1-1 row has *zero* readings at all — correct, prevents empty-diff rubber stamping) | Correct |
| In UNVERIFIED_FLAGS, dead in the change-set | `COSEGMENTED_UNANCHORED` (0 rows; no producer) | Remove or document |
| Dead / unreachable as bare flag | `DIFF_UNVERIFIED_DIFFERENT_TEXT` (see F6) | Decide |
| Latent, not blocking | `DIFF_UNKNOWN_NOM_CHARS` (7 Tap1 / 4 Tap3 rows — was 6/3; the rest verified) | Consider making it block `verified_match` at minimum, or report it |
| Latent, not blocking | `SPANS_PAGES` / `CROSS_PAGE_JOIN` on verified rows (Tap1 23 verified_difference + Tap3 9 verified_difference carry SPANS_PAGES — legit because readings anchor them) | Disclose in UI; leave gate as-is |
| Page-level only, fine | `OCR_ENGINE_DISAGREE` (F8), `MASK_ONLY_DIFFERENCE` (excluded by guideline — zero rows contain `[MASK]`) | OK |
| Deliberately not blocking | `DIFF_READING_MISMATCH`, `DIFF_NO_READING_MISMATCH`, `DIFF_READINGS_FROM_DICTIONARY`, `DIFF_REVIEW_RECOMMENDED`, `REVIEW:*`, `COSEGMENTED`, `COSEGMENTED_STREAM_ALIGNED`, `ALIGN_LOW_CONF`, `ALIGNED*` | Deliberate (dictionary-anchored rows are evidence, not doubt) |

Zero `REVIEW_METADATA_*`/`REVIEW_DECISION_*`/`CONTENT_EDITED` flags stored in either **rebuilt** sidecar (scan of both `.review_metadata.jsonl` files, 2026-11-12) ✔. Restore found **zero** missing/mismatch metadata issues for Tap1/Tap3 ✔ — running `write_review_metadata` now would change nothing (sidecars are consistent; F10 backup still stands before any rescoring). **The `UNMATCHED_QN` argument is gone:** the pre-repair text claimed no unmatched QN could appear (char-align assumption); the 2026-11-12 charalign path **can** emit it — Tap1 has one (`.100.1`). The corresponding `skip_nom`→`UNMATCHED_NOM` case exists only on the Tap2 cosegment path today (Tap2 not re-aligned).

### F14 — INFO — Decision replay is industrial-grade correct
(Code unchanged 2026-11-12 — this audit stands verbatim; `review_decisions.py` untouched by the change-set.)
latest-event-wins including latest-failure supersession ✔ (probe 1 vs 2); stale never verifies, no fallback to superseded valid ✔ (probe 3); same-revision mutual exclusivity (`accepted_match` ↔ `accepted_difference`) conflict only between same-hash events; mapping-set monotonicity/uniqueness/dup enforced; bool/float/`0.8`/string positions rejected at `from_dict`; failures with known `sentence_id` attribute to that row only, log-wide failures disable book-wide learning but still block the gate; `DECISION_SUPERSEDED` kept as audit-only; content hash covers `ch_txt`, `vi_txt`, `text_diff_json` NFC-normalized ch/vi — patches invalidate prior decisions as intended (F4 aside). One cosmetic nit: an active `REVIEW_DECISION_INVALID` issue's detail string joins **all** of the row's failure lines, including superseded ones (`invalid` state only) — not wrong, just noisy; could list only the latest event's failures.

### F15 — INFO — `verified_match` ≠ string equality
Rows counted `verified_match` (counts Tap1 **136** / Tap3 **125** — all carry `REVIEW:DIFF_UNVERIFIED_DIFFERENT_TEXT`; see F6) have `elements==[]` but ch≠vi always (Nôm vs Quốc ngữ can never be equal) — each is a zero-mismatch reading-anchored match with no reading-based evidence conflict. Their presence confirms the gate can genuinely pass rows by *absence* of contradiction — which is exactly why the guideline demands evidence, which these rows have (anchors), but also why "black" decisions must be human-attested, never auto. (Counts updated 2026-11-12; was Tap1 2 / Tap3 7.)

---

## 7. Quantified review plan for passing the gates (revised 2026-11-12)

> **Order matters: get §8 waiver first. These numbers assume the waiver (or an agreed criterion) is in hand, or that you are deliberately doing best-effort verification + full disclosure. All row counts re-measured read-only 2026-11-12 by joining `data/align/<book>/*.csv` × `*.review_metadata.jsonl` (probe `cohorts2.py`), reproducing `evaluate.py`'s row classification; the ANCHORED/UNANCHORED cohorts of the pre-repair plan are **dead** (the `charstream` segmenter emits no `COSEGMENTED_ANCHORED`/`COSEGMENTED_UNANCHORED`).**

### Tap3 — `T1_SuaLoiQuyen` (380 rows) — effort budget ~2–6 h

State now: **228 auto-verified** (125 match + 103 difference) · **152 unverified** (121 non-empty elements + 31 empty-elements, all 31 carrying `DIFF_NO_READING_MISMATCH` + `REVIEW:DIFF_UNVERIFIED_DIFFERENT_TEXT`) · **0 null rows** · 0 unmatched · gate needs ≥**342** verified (0.9×380 = 342.0 exactly), ≤**19** unverified (19/380 = 0.0500 allowed), null-ratio already passes (0.0).

| Wave | Cohort | Rows | Notes |
|---|---|---|---|
| G | already verified (automatic) | **228** | 125 match / 103 diff — machine only, zero decisions |
| B | empty-element unverified (accept-match-eligible after reading) | **31** | all `DIFF_NO_READING_MISMATCH` + `REVIEW:` marker; fast (30–60 s each) |
| A | near-black unverified (red/nom < 0.10) | **100** (54 of them < 0.05) | **now dominates the cohort** (66 % of unverified); glance, decide fast |
| C | `DIFF_AMBIGUOUS_READINGS` | **120** (78 ambiguous-only; 42 both) | the single biggest driver; readings exist but compete |
| D | `ALIGN_EVIDENCE_INSUFFICIENT` | **74** (32 insuff-only) | evidence failed; largest false-negative risk |
| — | both (`ALIGN_EVIDENCE_INSUFFICIENT` ∧ `DIFF_AMBIGUOUS_READINGS`) | **42** | subset of C∩D |
| F | `DIFF_UNKNOWN_NOM_CHARS` (no reading anywhere) | **4** | external dictionary lookups, ~10–20 min each |
| — | `SPANS_PAGES` cross-page rows | 42 total (29 unverified) | no extra work; read image |
| — | `ALIGN_LOW_CONF` | 4 (all unverified) | read with care |

**Knowledge-work fraction ≈ 380/380 = 100 %** (all content is readable Quốc ngữ + visible Nôm; image lookup per row in the app; **genuinely unknowable: 0** — the >20 % bad-scan escalation rule is the escape for unreadable scans, not a row count).

Target end-state: coverage 1.00, unverified 0–19, null 0 ⇒ **coverage, unverified-ratio and null-ratio gates pass**. Similarity is **not** fixed by any of this (F1) — disclose ≈**87.5 %** on the full re-scored basis (currently **93.74** stored, or whatever the waived formula yields) with yellow ratio 0.0 and null ratio 0.0 in the report.

### Tap1 — `T1_CamPhong_Tap1` (823 rows) — effort budget ~4–12 h

State now: **381 auto-verified** (136 match + 245 difference) · **441 unverified** (405 non-empty + 36 empty elements — all 36 `DIFF_NO_READING_MISMATCH` + `REVIEW:` marker) · **1 null row** (the `skip_qn` row `.100.1` / img `.100.jpg`, `UNMATCHED_QN`, warning `QN_SENTENCE_NO_NOM:529` — policy row, not a review wave) · 0 unmatched-by-decision · gate needs ≥**741** verified (0.9×823 = 740.7 → 741), ≤**41** unverified (41/823 = 0.0498 ≤ 0.05; the pre-repair bound was ≤36), null ratio stays ≤ 0.05 automatically (1/823 = 0.0012 ✓).

| Wave | Cohort | Rows | Notes |
|---|---|---|---|
| G | already verified | **381** | machine (dictionary evidence), zero decisions |
| B | empty-element unverified | **36** | same semantics as Tap3 |
| A | near-black unverified (red/nom < 0.10) | **184** (82 of them < 0.05) | **now dominates the cohort** (42 % of unverified) |
| C | `DIFF_AMBIGUOUS_READINGS` | **362** (209 ambiguous-only) | the single biggest driver |
| D | `ALIGN_EVIDENCE_INSUFFICIENT` | **232** unverified (79 insuff-only; metrics `evidence_insufficient_rows`=233 incl. the null row) | the second driver |
| — | both | **153** | subset of C∩D |
| E | n-m null rows | **1** | keep null + disclose (verify OCR of page `.100`), or recompute the single row — no longer gate-relevant (null_ratio 0.0012) |
| F | `DIFF_UNKNOWN_NOM_CHARS` | **5 unverified** (+1 verified_difference +1 verified_match machine-classified) | external lookups |
| — | `SPANS_PAGES` | 126 (103 unverified) | read image |
| — | `ALIGN_LOW_CONF` | 39 (38 unverified; 1 verified_difference) | read with care |

**Knowledge-work fraction ≈ 822/823 = 99.9 %** (every reviewable row; image lookup per row; 0 known-unreviewable). End-state identical pattern: coverage/unverified/null pass; similarity ≈**70.8 %** absent waiver (full re-scored basis; **89.96** stored) — disclose.

### Estimated wall-clock

Tap3 ≈ **2–6 h** focused (~152 decisions × 20–45 s, plus evaluate rerun). Tap1 ≈ **4–12 h** (~441 decisions + 1 policy row). Add 10–20 % context-switch overhead. **Neither number helps the similarity gate — do the waiver conversation first.** (Pre-repair estimates, for the record: Tap3 ≈ 3–8 h / ~315 decisions; Tap1 ≈ 4–10 h / ~718 decisions + 124 n-m rescoring. The repair removed the n-m cohort entirely — Tap3 has 0 nulls, Tap1 has 1 — and cut the unverified mass by ~27 %.)

---

## 8. Blocking orders of operations (do not reorder)

1. **Waiver FIRST.** With the instructor (guideline p.21: criterion may change per book; or declare the books non-dịch-âm → formula waived, with report changes to match). The **n-m policy** is now nearly moot for Tap1/Tap3 (Tap3 has 0 nulls; Tap1 has exactly 1) — settle only the single `skip_qn` row (page `.100` OCR check, or disclose as-is). **Tap2 still needs OCR before any gate question.**
2. **Backups second.** Copy `data/align/<book>/*.csv`, `*.review_metadata.jsonl`, `summary.json` to a dated folder (gitignored). Record hashes. **The pre-repair evidence is already preserved under `data/align/<book>/_pre-repair-2026-11-12/` — do not delete it before the waiver decision (F10); do not point unpruned tooling at it (§12).**
3. **Rescore only with sign-off**: `hannom textdiff --force-recompute --book <SLQ|T1_CamPhong_Tap1>` (now relevant only to Tap1's single row; post-repair both books already score `null_ratio=0.0`). Expect sidecar regenerated, `git diff` on backups, and any recomputed row to gain `elements=[]` + `DIFF_UNVERIFIED_NO_BOOK_READINGS` (human attestation only).
4. **Review waves per §7** using the Streamlit app (`streamlit run src/hannom/review/app.py`), saving decisions; **re-run `evaluate` → `hannom evaluate --book <id>` after each batch** — `stage_evaluate` backs up `metrics.json` to a timestamped file before rewriting (non-destructive; the 2026-11-12 evaluate run did this: `metrics.20261112T122218Z.json` etc.).
5. **Re-evaluate + disclose** in the report: similarity (≈70.8 / ≈87.5 full basis; or the waived number), yellow ratio (0.0 expected — keep it that way; do not re-type genuine red as yellow to game numerator/denominator — guideline-sanctioned yellow cases only: proper names/years, illegible-Nôm, lost pages), null ratio (**0.0 / 0.0** now), coverage, both books' tables, the 1 Tap1 null row, and `metrics.json` copied verbatim into the appendix.
6. **Tap2 disposition** written down: re-align (needs OCR of the missing pages first — 525 `MISSING_CLEAN_PAGE`) or exclude with reason; delete or quarantine stale `metrics.json` (it's already wrong on disk). **Disposition unchanged — Tap2 remains the dominator of deadline risk.**

---

## 9. Ranked code-fix list (file:line, in priority order)

1. **`review_decisions.py` `make_decision` (L407–447) — element-consistency precondition.** Reject `accepted_match` with non-empty elements, `accepted_difference` with empty elements (fail at decision time, not at gate). Mirror the evaluate-side rule (evaluate.py L134–141) so humans cannot create the F3 trap. Also reject/annotate in `review/app.py` when accept buttons are shown (app.py L347–361).
2. **`review_decisions.py` `content_sha256` (L123–131) — canonical binding.** Parse `diff_json`, round-trip through `json.loads`/`json.dumps(sort_keys=False, ensure_ascii=False)` or serialize elements via `to_dict()` before hashing. Kills F4 (born-stale edit decisions).
3. **`evaluate.py` contradiction branch (L250–254) — also set `REVIEW_DECISION_MISMATCH` on `row.flags`** when the classify pair returns a contradiction (and/or `apply_decisions` sets it for element-consistency rejections) so `book_lexicon.BLOCKING_FLAGS` (L82) finally has a producer; Path B then cannot learn from attested-but-invalid rows (F7).
4. **`review/app.py` — bulk-accept + per-flag multi-select** filter; replace the dead `COSEGMENTED_UNANCHORED` keeper with **`ALIGN_EVIDENCE_INSUFFICIENT`** (the #1 unverified driver; 233/74 rows) and add `SPANS_PAGES`/`NON_ONE_TO_ONE`/`TEXT_DIFF_NULL_NON_ONE_TO_ONE` (L125–136) and button guards (F11, F3): grey out accept-match when `elements≠[]`, disable accept-diff when `elements==[]`.
5. **`review_decisions.py` — audit detail only the triggering failure** in active `REVIEW_DECISION_INVALID` (L720–722); superseded failures already demoted to `DECISION_SUPERSEDED` audit.
6. **`evaluate.py` — make `DIFF_UNKNOWN_NOM_CHARS` block (propose: `verified_match` only, or `verified_difference` if any unknown-char span is error) or add a warning**; also consider whether `SELF`: `REVIEW:DIFF_UNVERIFIED_DIFFERENT_TEXT` should block (see F6 policy choice — pick one and encode it). **Also: remove `COSEGMENTED_UNANCHORED` from `UNVERIFIED_FLAGS` (or document it as reserved) — the change-set left the entry with zero producers.**
7. **`ocr/agreement.py`/`ocr/router.py` — export page-level `OCR_ENGINE_DISAGREE` into row report/overlay or a metrics aggregate** (informational), e.g. `pages_with_engine_disagreement` in BookMetrics (F8).
8. **`review_decisions.py` `validate_mapping_set` (L207–264)** — bool/float reject for positions (F9).
9. **`cli.py`/`align.py` — add CSV backup step to `hannom textdiff`** (or at least a loud warning + `--backup` flag) (F10).
10. **Refresh Tap2 metrics** (or mark stale); regenerate `metrics.json` via `hannom evaluate --book T1_CamPhong_Tap2` after any re-align (F5). **Note:** Tap2 *has* a `metrics.json` (2026-11-08, `EMPTY_DENOMINATOR`) — it is stale/pre-governance, not absent.
11. **Documentation**: write the review-decision runbook (bytes-flow: CSV → patches → decisions → recompute) into the report or `Doc/`, and explicitly state that **0 decisions ⇒ 100 % machine classification ⇒ all 381/823 (Tap1) and 228/380 (Tap3) verified rows are dictionary-evidence-driven**.
12. **Quarantine or delete the Tap3 `data/align/T1_SuaLoiQuyen/_pre-repair-2026-11-12/` quagmire** (~1,422 self-nested `_pre-repair-2026-11-12` levels, 3 files, `PathTooLongException`-inducing for unpruned `os.walk`/`glob`) — owner action, not this report's; verify `Doc/` runbooks never recurse it; keep the one-level `Tap1/_pre-repair-2026-11-12/` (normal backup) intact.

---

## 10. Reproduction commands

```powershell
cd "C:\Users\MSI VN\Desktop\NLP"
python -m pytest -q                                    # 282 passed (2026-11-12; was 277)
$env:PYTHONIOENCODING='utf-8'
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-H\cohorts2.py"   # current-data cohorts: unverified/verified split, near-black buckets (441/152), empty-element rows
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-H\allrows.py"    # full re-scored basis: denom 8414/27820, red 1052/8111, similarity ≈87.5/≈70.8
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-H\appfilter2.py"  # visibility audit on current sidecars → 0 invisible (Tap1 441 + Tap3 152)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-H\csvcheck2.py"  # CSV duplicates/empty img_id/NFC on rebuilt CSVs (all clean; Tap2 8 rows 0 dups)
# --- historical (pre-repair, 2026-11) probes; printed numbers are superseded, kept for reference ---
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\repro.py"             # metrics check — on CURRENT data derives the NEW metrics (89.9646/93.7385, 3 issues each, UNVERIFIED_DIFFERENT_ROWS 136/125); on pre-repair copies reproduces 87.3626/85.8696 bit-for-bit
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\sim.py"               # (historical) denominator/red totals over all 1-1 rows
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\flatmatch.py"         # (historical) hvdic+flat-match re-score of all 1-1 rows (SLQ) — NOT re-executed 2026-11-12
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\reddist.py"           # (historical) red/nom ratio distribution buckets
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\appfilter.py"         # (historical) review-app visibility audit
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\sidecar_check.py"    # (historical) sidecar completeness + REVIEW_METADATA_* flags
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\csvcheck.py"         # (historical) CSV audit (all clean)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\boundary.py"         # 95.0 / 0.900 / 0.05 boundary probes (code unchanged — still valid)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\adversarial.py"      # latest-event-wins, supersession, conflicts, log-wide failure (code unchanged — still valid)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\hashbind.py"         # content_sha256 canonicalization bug (F4), make_decision trap (F3) (code unchanged — still valid)
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-H\cohorts.py"          # (historical) cohort sizes for the review plan (superseded by cohorts2.py)
```

**Bit-for-bit reproduction of the pre-2026-11-12 numbers (§3):** copy `data/align/T1_CamPhong_Tap1/*.csv`, `*.review_metadata.jsonl` (and Tap3's) from **`data/align/<book>/_pre-repair-2026-11-12/`** into a scratch directory, point `repro.py`'s loader at the copies, and compare against the archived snapshots `data/evaluation/T1_CamPhong_Tap1/metrics.20261112T120924Z.json` and `data/evaluation/T1_SuaLoiQuyen/metrics.20261112T120355Z.json` — expected values are the pre-repair blocks quoted in §3 (727 rows / 87.3626 / `EXCESSIVE_NULL_ROWS` / cov 0.0110 / null 0.1706; 341 rows / 85.8696 / cov 0.0762 / null 0.2874). **On the live (rebuilt) data, `repro.py` derives the NEW metrics** — the check "passes bit-for-bit" only against the archives. Do **not** run the reproduction against `data/align/T1_SuaLoiQuyen/**` with an unpruned walker (pathological nesting, §12).

All probes write **nothing** to the repo; only `verify-H/`, `verify-revise-H/` and this report file are touched.

---

## 11. Handoff checklist for the next agent (in order)

- [ ] Confirm the instructor waiver decision (F1/F2) and the n-m policy (now: only Tap1's single `skip_qn` row); record it in `Doc/` (this file is fine).
- [ ] Backup `data/align/<book>/*.csv|.review_metadata.jsonl|summary.json` (F10) before any `textdiff` run; do not delete `_pre-repair-2026-11-12/`.
- [ ] If approved: `hannom textdiff --force-recompute` is now relevant only to Tap1's single row; normally skip it — both books already score `null_ratio=0.0`. `hannom evaluate` rewrites `metrics.json` and backs it up automatically to a timestamped sibling.
- [ ] Run review waves per §7 (Tap3 B/…/G then Tap1) for one book at a time; save decisions; verify `metrics.json` coverage climbs toward ≥0.90 (≥741/823 or ≥342/380), `unverified_ratio ≤ 0.05` (≤41 / ≤19), `null_ratio ≤ 0.05` (already 0.0).
- [ ] Do **not** report the book as "accepted" — only as "best-effort; similarity < 95; waiver granted/requested on <date>". Include `yellow_ratio=0.0`, `null_ratio=0.0`, full tables, and copy `metrics.json` verbatim.
- [ ] Implement §9 fixes 1–6 before mass review (they remove self-inflicted blocking decisions; #6 additionally removes the dead `COSEGMENTED_UNANCHORED` entry).
- [ ] Tap2: disposition written; stale `metrics.json` refreshed or moved to `data/archive/…` — Tap2 *has* one (2026-11-08, `EMPTY_DENOMINATOR`); it is stale, not absent.
- [ ] **Quarantine/delete the Tap3 `_pre-repair-2026-11-12/` quagmire** (~1,422 levels; §12) or ensure no tooling walks it (prune `os.walk`/`glob`).
- [ ] If any review finding contradicts this report, update this file and re-run `pytest`.

---

## 12. Caveats & known-unknowns

1. **Dictionary index never built** (2.7 GB); red-span evidence uses *stored* `text_diff` from the delivered (2026-11-12 rebuilt) CSVs. The hvdic-only flat-match re-score (sim 15.3 %/9.5 %) is a pre-repair probe — **not re-executed 2026-11-12**; the post-repair full re-scored basis (≈87.5 / ≈70.8) is the current evidence, and it still sits below 95. A smarter (variant/soundex-ish — the change-set's diacritic-variant fold already exists but is a 1.0-cost weak match only) matcher might anchor *some* more characters; do not rely on it to reach 95 %.
2. **Full Tap3/Tap1 gate after force-recompute is untested by this verification** (it rewrites data; it was deliberately not executed — and is now nearly irrelevant: 0 and 1 null rows). The post-recompute gate outcome claimed here is: coverage/unverified/null pass (if all rows attested), similarity fails regardless (≈87.5 / ≈70.8 full basis). Anything else is untested territory.
3. **`metrics.json` for Tap1/Tap3 is NOT bit-compatible with the pre-repair state.** The bit-for-bit check reproduces only the archived pre-repair snapshots (`metrics.20261112T120924Z.json` / `metrics.20261112T120355Z.json`) against the `_pre-repair-2026-11-12/` CSV/sidecar copies; `repro.py` on the live data derives the new metrics (89.9646 / 93.7385, 3 issues each, `UNVERIFIED_DIFFERENT_ROWS` 136/125). They are rewritten by `hannom evaluate` (with backup) — re-verify after any rescoring.
4. **Tap2's staleness** (metrics from 2026-11-08, pre-governance fields) means Tap2 conclusions are drawn from direct CSV/sidecar/summary inspection, not from a current-format `metrics.json`. Tap2 **does** have a `metrics.json` (`EMPTY_DENOMINATOR`, `null_ratio=1.0`, `similarity=null`, 8 rows) — stale/pre-governance, not absent — but **no** Tap2 `metrics.*.json` archive exists; the identically-sized `metrics.20261112T035909Z.json` is Tap1's own 6-row pre-governance artifact.
5. **"0 unverified rows invisible to the app filter"** (F11) was re-measured on the post-repair flag set (Tap1 441 + Tap3 152 — visibility survives, but currently via `DIFF_*` prefixes; `ALIGN_EVIDENCE_INSUFFICIENT` — the #1 driver — is **not** an app keeper). It can still drift if the pipeline changes (e.g. F6's policy or a new REVIEW-reasons class without blocking power).
6. **Guideline page references are to `Quy_định_đồ_án_v2.1.extracted.txt`** (p.16–21): non-phonetic rows `⇒ text_diff=null`; non-dịch-âm book `⇒` formula not applicable, criterion changed "để phù hợp với tính chất và tình trạng của sách"; yellow ratio & null-row ratio must be disclosed; ≥95 % is "mức tiêu chuẩn" and may be adjusted. Any gate-pass claim must cite the applicable clause.
7. **Similarity inputs are elements-driven**: any hand-patch of a `text_diff` changes hashes → all prior decisions for that row go stale by design — re-decide after every patch (the app reruns and re-reads on each action, consistent).
8. **This report reflects the repo state at 2026-11-12 after the map-repair change-set**; if align/review stages re-run, the numbers change and §3 repro must be re-done. CSVs/sidecars were rebuilt on 2026-11-12 19:43 (Tap1) / 19:03 (Tap3); `metrics.json` at the same mtimes; Tap3 `_pre-repair-2026-11-12/` is a **~1,422-level self-nested directory** (measured 2026-11-12: 1,422 nested `_pre-repair-2026-11-12` directories, only 3 files — a recursive-backup accident of unknown origin; review tooling must not glob `data/align/**` unpruned — unpruned `os.walk`/`glob` over `data/align/T1_SuaLoiQuyen/**` dies with Win32 `PathTooLongException`). Prune or delete it — owner action; it is not this report's to remove. Tap1 has a normal one-level `_pre-repair-2026-11-12/` backup.
9. **`docs/decisions.md` "2026-11-12 gate status unchanged" entry is unreliable and was not edited here** (it is the collaborator's uncommitted file; this revision touches only this report): it is correct that Tap1/Tap3 still FAIL **coverage ≥ 0.9** and **unverified_ratio ≤ 0.05** (human review required); it **omits `SIMILARITY_BELOW_GATE`** entirely; its "**0.7 % gap to 95 % on Tap1 and 1.3 % on Tap3**" does not reconcile with stored metrics (actual absolute gaps **5.04** / **1.26** similarity points; ≈5.3 %/1.33 % relative); and "will only close with review decisions, not with more code" is wrong for similarity — decisions do not touch `red_mismatch_chars`/`denominator` (`evaluate.py:277–278`); only a signed-off criterion change, a corpus rework, or content fixes close that gap. Owner should correct that entry (or replace it with a pointer to this report).
10. **Flag-family change-set summary** (any documentation/tooling referencing the old flags is stale): `COSEGMENTED_ANCHORED`/`COSEGMENTED_UNANCHORED` are gone (0 rows; no producer — `charstream.py` emits only `COSEGMENTED`/`COSEGMENTED_STREAM_ALIGNED`); `UNMATCHED_QN` can now surface from the charalign path (Tap1: 1, `.100.1`, with warning `QN_SENTENCE_NO_NOM:529`); the analogous `UNMATCHED_NOM` appears only on the Tap2 cosegment path today (Tap2 not re-aligned); `DIFF_READING_MISMATCH` is carried by 650/224 rows (all machine `verified_difference`); `DIFF_NO_READING_MISMATCH` by 172/156 (136/125 machine `verified_match` + 36/31 empty-elements unverified); variant fold in `textdiff.py` shifts line cites +1..15 (F6 `:551–552`, F1 `:603–612`/`:615–626`); `align.py` shifts +72 past line 387 (`write_alignment_csv` L668–694; `auto_text_diff` call L528).
11. **Boundary probes vs new gates (sanity):** coverage ≥ 0.9 binds at ≥741/823 (Tap1) and =342/380 (Tap3, exactly 0.9); `unverified_ratio ≤ 0.05` binds at ≤41/823 = 0.0498 and =19/380 = 0.0500 (gate triggers only on `>`, evaluate.py L314–315) — the pre-repair bounds ≤36/≤17 are simply superseded; similarity binds at red ≤353/7065 (Tap1, 353/7065 ⇒ 95.004) and ≤163/3274 (Tap3, 163/3274 ⇒ 95.021; 164 ⇒ 94.991 < 95 — the change-set note's "≤164" is a round(163.7) artifact). `null_ratio=0.0` both books ⇒ `EXCESSIVE_NULL_ROWS`/`NULL_ROW_RATIO_HIGH` cannot fire.
12. **Independent arithmetic checks performed 2026-11-12** (this revision): flag-union reconciliation — Tap1 232+362−153 = 441 ✔, Tap3 74+120−42 = 152 ✔; `verified+unverified+unmatched+null = total` ✔ both books; stored denominator/red (7065/3274 ≤ full basis 27820/8414 — evaluate scores verified rows only) ✔; `evidence_insufficient_rows` = unverified-with-insufficient + Tap1 null row ✔ (232+1 = 233; Tap3 74). Read-only probes: `cohorts2.py`, `allrows.py`, `appfilter2.py`, `csvcheck2.py` (in `verify-revise-H/`).
13. **Git topology unchanged since the change-set**: `feat/map-repair-align` @ `c3439e7`, zero new commits; the change-set is 9 modified tracked files + untracked code/tests/docs — **no commit should be made from this revision** (it is a Doc-only file, and committing is the owner's call).

---

## Revision log

**2026-11-12 (this revision; post-`feat/map-repair-align` change-set; written by the H-report owner)**

Scope: documentation-only revision of this file. No code, config, data, or cache files were touched; scratch under `verify-revise-H/`. All quoted numbers re-measured read-only 2026-11-12 (joins of rebuilt `data/align/<book>/*.csv` × `*.review_metadata.jsonl`; stored `metrics.json`; sidecar flag histograms; full re-scored-basis probe). Nothing here was run against the live pipeline (`pytest` not re-run by this revision — the 282-pass figure is the change-set's own, recorded as such).

Sections changed and what:
- **Banner/header (top):** added the mandated REVISION banner; ground rules now describe the **uncommitted** collaborator change-set (branch `feat/map-repair-align` @ `c3439e7`, zero new commits; 9 modified tracked files + untracked `charstream.py`/`map_repair.py`/tests/tools/`Doc/verify-*.md`; only this report edited by this revision). Outcome-in-one-line restated with post-repair numbers.
- **§1 Scope:** `charstream.py` added (new live segmenter — `COSEGMENTED`/`COSEGMENTED_STREAM_ALIGNED` only); data row lists the pre-repair archives; method: tests 277→**282**; mirrors list both scratch dirs.
- **§2 Method:** git-state bullet rewritten (change-set is uncommitted); pre-repair evidence locations; archived snapshots documented.
- **§3 Reproduction:** split into current (post-repair) values, tagged `(revised 2026-11-12)`, and archived pre-repair snapshots (`metrics.20261112T120924Z.json` Tap1 / `metrics.20261112T120355Z.json` Tap3) for the bit-for-bit command, which now requires copying `_pre-repair-2026-11-12/` inputs into scratch (live files must not be restored over). `metrics.json` is **not** bit-compatible post-repair (all figures changed). Tap2: mis-twin corrected (`metrics.20261112T035909Z.json` is Tap1's own 6-row pre-governance artifact — same size, different book/row-count); the pre-repair line "`metrics.20261112T035909Z.json` is a byte-size twin of `metrics.json`" was wrong and is removed; Tap2 previously referenced no archive at all — corrected: none exists. F-report claim "Tap2 has no `metrics.json`" checked — not present in this file; the actual mis-claim (above) fixed instead.
- **§4:** code unchanged (`evaluate.py`, `review_decisions.py`, `review_metadata.py`, `review/app.py` — line cites re-verified valid). §4.2 CSV audit re-measured on rebuilt CSVs (823/380/8 rows; 0 dup `sentence_id`; 0 empty `img_id`; 0 non-NFC; per-cell diff-type splits Tap1 822 array [650 non-empty + 172 `[]`] / 1 null; Tap3 380 [224 + 156 `[]`] / 0 null; Tap2 8/8 null) — all clean.
- **§5:** ceilings rewritten (null-cap argument dead for Tap1/Tap3 — Tap3 0 nulls, Tap1 exactly 1 (`skip_qn`/`UNMATCHED_QN`, `.100.1`, img `.100.jpg`, `QN_SENTENCE_NO_NOM:529`) ⇒ ceilings 100 % / 99.88 %; Tap2 still 0 %); verified counts 381/823 = 46.29 % and 228/380 = 60.00 %, 100 % machine; `data/review/` confirmed absent ⇒ **zero human decisions** (search pruned of the Tap3 quagmire); full-review bounds re-measured (≈70.8 / ≈87.5); gate-basis red-elimination bounds Tap1 ≤353 (50.2 %) / Tap3 ≤163 (20.5 %); hvdic/flat-match figures marked pre-repair/not re-run; error-span coverage 6914/27820 = 24.9 % and 1031/8414 = 12.3 %; `red/nom≥0.8` cohorts 32/650 and 2/224; yellow_chars=0 both books.
- **§6 Findings:** F1/F2 rewritten (line cites re-anchored: `textdiff.py` 536–537→**551–552**, 588–597→**603–612**, 600–611→**615–626**, 373–389→**380–395**; `align.py` 596–623→**668–694**; `orchestrator.py` cites unchanged and re-verified: learn_for_book L292, recompute L310 (align-time `auto_text_diff` call L339 unchanged), reconcile L361, loader L452, stage_evaluate L480; `write_alignment_csv` body verified at L668–694). Verdicts **intact** for F1 (policy blocker), F3, F4, F6, F7, F10, F11 (code unchanged; counts updated). F5 corrected (Tap2 DOES have `metrics.json` — 2026-11-08, stale/pre-governance, not absent). F6 counts: verified_match cohorts Tap1 136 / Tap3 125 all carry `REVIEW:DIFF_UNVERIFIED_DIFFERENT_TEXT`; `DIFF_NO_READING_MISMATCH` 172/156 = 136/125 verified_match + 36/31 empty-elements unverified. F10 notes 2026-11-12 live in-place rewrite; pre-repair evidence preserved under `_pre-repair-2026-11-12/`. F11: visibility re-measured **0 invisible** (Tap1 441 + Tap3 152, probe `appfilter2.py`; visibility survives via `DIFF_*` prefixes, not the missing keepers — `ALIGN_EVIDENCE_INSUFFICIENT` still missing from the app filter); press-count now ~593 total. F12: aggregates updated (null_ratio 0.0/0.0; `evidence_insufficient_rows` 233/74; `semantic_evidence_rows` 823/380; `structural_confidence_mean` 0.9115/0.9622; exactly 3 issues each; `UNVERIFIED_DIFFERENT_ROWS` 136/125). F13: table rebuilt from the post-repair sidecar histogram; `COSEGMENTED_UNANCHORED` flagged as a dead UNVERIFIED_FLAGS entry (no producer; `charstream.py` emits only `COSEGMENTED`/`COSEGMENTED_STREAM_ALIGNED`); `UNMATCHED_QN`/`UNMATCHED_NOM` appearability amended. F15: counts 136/125.
- **§7 Review plan:** wholesale rebuilt (old `ANCHORED`/`UNANCHORED` cohorts dead). New totals **441 + 152 = 593** unverified; near-black cohorts now dominate (Tap1 184/441 = 42 %; Tap3 100/152 = 66 %); Tap3 `E`-wave (98 nulls) removed (0 nulls); Tap1 keeps a single policy row (`skip_qn`); gate bounds restated (≥741/823, ≥342/380; ≤41/≤19 unverified; null 0.0); effort re-estimated 2–6 h / 4–12 h; interference: knowledge-work ≈100 % (Tap1 822/823 = 99.9 %).
- **§8 Ordering:** waiver first (unchanged); n-m policy now only Tap1's single row; backups reference the preserved `_pre-repair-2026-11-12/`; step 6 Tap2 disposition unchanged (still the deadline-risk dominator; needs OCR first).
- **§9 Fixes:** #4 keeper modernized (drop `COSEGMENTED_UNANCHORED`; add `ALIGN_EVIDENCE_INSUFFICIENT` + `SPANS_PAGES`/`NON_ONE_TO_ONE`/`TEXT_DIFF_NULL_NON_ONE_TO_ONE`); #6 additionally removes the dead `COSEGMENTED_UNANCHORED` UNVERIFIED_FLAGS entry; #10 notes Tap2's metrics.json is stale not absent; #11 restates "0 decisions ⇒ all 381/228 verified rows machine-driven"; **#12 added** — quarantine/delete Tap3 `_pre-repair-2026-11-12/` quagmire (owner action).
- **§10 Reproduction:** tests 277→**282**; current-state probes listed (`verify-revise-H/`); pre-repair `verify-H/` probes labeled historical (their numbers superseded; line-cite-only probes — `boundary.py`, `adversarial.py`, `hashbind.py` — remain valid, code unchanged); bit-for-bit procedure documented (restore `_pre-repair-2026-11-12/` copies to scratch; compare to archived snapshots; live data derives NEW metrics).
- **§11 Handoff:** waves updated per §7; Tap2 disposition unchanged; new item — quagmire quarantine; git topology note (Doc-only revision; committing is owner's call).
- **§12 Caveats:** rewritten 1–8 and extended to 13 — new: decisions.md "gate status unchanged" entry is unreliable (correct only on coverage/unverified; omits `SIMILARITY_BELOW_GATE`; "0.7 % gap (Tap1)/1.3 % (Tap3)" irreconcilable — actual 5.04/1.26 points; "will only close with review decisions" wrong for similarity, decisions don't touch `red_mismatch_chars`/`denominator`; file not edited — owner's call); Tap3 `_pre-repair-2026-11-12/` ~1,422-level self-nesting (unpruned `os.walk`/`glob` dies with `PathTooLongException`; measured 2026-11-12: 1,422 dirs / 3 files); `UNMATCHED_QN` appearability; flag-family change summary; boundary-probe reconciliation vs the 0.05 gate on new denominators (≤41/≤19); independent arithmetic checks.
- **Discrepancies vs the change-set note — flagged, NOT silently adopted:** (i) "Tap3 red ≤164" is `round(0.05×3274)=164` — the gate is strict (`similarity ≥ 95.0`), so the binding bound is **≤163** (163 ⇒ 95.021 ✓; 164 ⇒ 94.991 ✗); (ii) "unverified must drop ≤36/≤17 (same percentage, new denominators)" is internally inconsistent — at 0.05 on 823/380 denominators the bounds are **≤41/≤19** (19/380 = 0.0500, allowed; 41/823 = 0.0498); the stricter ≤36/≤17 remains a *sufficient* target and is stated as such; (iii) Tap1 `evidence_insufficient_rows=233` includes the null `skip_qn` row (232 unverified + 1); (iv) pre-repair "full basis" denominators differ from stored-gate denominators — old §5 text quoted 27880/8560 (full basis) while the F2/§7 text quoted ≤1394/≤428 — both restated against 27820/8414 (full) and 7065/3274 (gate basis) with definitions now explicit.
- **Not verified / deliberately not re-run:** `pytest` (would write cache dirs into the repo — recorded instead, 282 pass per the change-set); hvdic/flat-match re-score (2.7 GB index build); Tap2 pipeline; any pipeline stage; `decisions.md` (read-only here); file writes other than this report and `verify-revise-H/` scratch.

**Verdicts that survived the change-set intact:** F1 (policy blocker — similarity still fails both books), F2 (waiver conversation first — burden 593, was ~811), F3/F4 (unrecoverable-without-content-patch traps; code untouched), F6/F7 (dead bare flag; learning Path B producer still absent), F8/F9 (page-level/defense-in-depth), F10 (in-place rewrite hazard — realized live on 2026-11-12), F11 (filter gap; press-count shrank, gap persists), F12 (fail-closed honesty — failure now printed with 3 issues, not hidden), F13/F14/F15 (completeness audit rebuilt; replay industrial-grade; `verified_match` semantics). Tap2 disposition: unchanged; still the dominator of deadline risk. The review-hours-before-waiver prohibition stands.
