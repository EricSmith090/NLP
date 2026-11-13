# Verify E — Co-segmentation & sentence alignment (Stage 6)

> **REVISION 2026-11-12 (post map-repair change-set):** written against pre-`feat/map-repair-align` state; the collaborator's uncommitted 2026-11-12 change-set (image_map content-DP repair; Tap1 scope re-bin incl. front matter 013–020 → vi; `hannom.charstream` dịch-âm segmenter (Tap1/Tap3; Tap2 keeps cosegment); CSVs rebuilt (Tap1 727→823 rows / Tap3 341→380); labels regenerated; tests 277→282, all pass) is incorporated. Claims revised inline. Numbers re-measured read-only 2026-11-12.

**Repo**: `C:\Users\MSI VN\Desktop\NLP`
**Audience**: next agent, zero prior context.
**Status**: verification complete (2026-11-12). Revised 2026-11-12 (post map-repair change-set); the revision is read-only against the working tree. No source files modified by either pass. (revised 2026-11-12)
**Date of verification**: 2026-11-12 (initial audit); 2026-11-12 (this revision, re-measured read-only).
**Deliverable scope**: `src/hannom/cosegment.py`, `src/hannom/align.py`, `src/hannom/anchors.py`, `src/hannom/clean.py` (segment-relevant parts), `src/hannom/textdiff.py` (`auto_text_diff`), `configs/alignment.yaml`, `src/hannom/models.py` (`AlignmentRow`), **`src/hannom/charstream.py` (new in the change-set; the LIVE dịch-âm segmenter — added to scope this revision)** (revised 2026-11-12), with cross-reads of `src/hannom/orchestrator.py` (`stage_align`, `recompute_text_diff`), `src/hannom/evaluate.py`, `src/hannom/review_metadata.py`, `src/hannom/t1_map.py`, `src/hannom/charalign.py` (unchanged; its CLI driver remains an explicit offline diagnostic; its primitives are imported by live modules — see §13.15), `src/hannom/review_decisions.py`, and `data/{align,evaluation,clean,layout,labels,dictionary,pages,output}` (read-only). `src/hannom/map_repair.py` and `tools/repair_image_map.py` (also new in the change-set) are **not** audited here.

Git state at revision time (revised 2026-11-12): branch `feat/map-repair-align` (current), HEAD `c3439e7` (repair-branch tip; contained in `origin/repair/pipeline-audit-2026-11-09`). **ZERO new commits** — the 2026-11-12 change-set is entirely uncommitted (working tree): **9 modified tracked files** (`configs/alignment.yaml`, `configs/books/T1_CamPhong_Tap1.yaml`, `configs/books/T1_SuaLoiQuyen.yaml`, `docs/decisions.md`, `src/hannom/align.py`, `src/hannom/config.py`, `src/hannom/layout.py`, `src/hannom/orchestrator.py` (labels-misc bin only, `orchestrator.py:169`), `src/hannom/textdiff.py`) **+ 5 new source files** (`src/hannom/charstream.py`, `src/hannom/map_repair.py`, `tests/test_charstream.py`, `tests/test_map_repair.py`, `tools/repair_image_map.py`) plus untracked `Doc/*.md` (this file included) and `submission/`. `tests now 282 — replace "288"/"277" everywhere` (revised 2026-11-12).

---

## 1. Scope & files

| Area | Files | Role |
|------|-------|------|
| Stream co-segmentation (**Tap2-only live path**) | `src/hannom/cosegment.py` | `stream_cosegment`: concat page streams in reading order (Nôm descending for T1, QN ascending), split QN stream at sentence punctuation (+uppercase/digit/quote lookahead), cut Nôm stream at the same boundaries (anchor-windowed interpolation or proportional fallback), attach page attribution + flags. **Post 2026-11-12: live only for Tap2 (8 rows); dormant for Tap1/Tap3** (revised 2026-11-12) |
| Stream segmentation via charalign projection (**dịch-âm books, LIVE**) | `src/hannom/charstream.py` | `stream_segments_by_charalign`: aligns both reading streams **globally** (banded Needleman–Wunsch, the same machinery as `hannom.charalign`; `band=400`, page-start anchors) and **projects QN sentence cut points onto the Nôm stream** through the alignment. One segment per QN sentence; index i ↔ index i; segments carry `COSEGMENTED_STREAM_ALIGNED`; a QN sentence with no aligned Nôm ops yields an empty Nôm segment → `UNMATCHED_QN` flag; consulted by `align_book` per `configs/alignment.yaml` → `alignment.per_book` (revised 2026-11-12) |
| Pair co-segmentation (dead) | `src/hannom/cosegment.py` (`cosegment_pair`) | Legacy pair-wise splitter; **no callers outside tests** — see M7 |
| Sentence segmentation / fallback | `src/hannom/align.py` (`split_nom_page` (:126), `split_qn_page` (:150), `_split_long_text` (:108), `build_segments` (:226), `_may_join_across_pages` (:167)) | Per-page splitting and cross-page hyphen-join when stream mode declines (revised 2026-11-12) |
| Anchor evidence | `src/hannom/anchors.py` | Reliable unique-local monotone Nôm↔QN reading anchors (both directions unique), LIS over pairs |
| Alignment DP | `src/hannom/align.py` (`align_segments` (:387-455), `_emit_rows` (:458-559, NEW — emission tail extracted 2026-11-12), `_group_cost` (:354-384), `_reading_matches` (:303), `semantic_evidence` (:337)) | Grouped edit-distance DP, max_group=4, max_nm_group=2, n-m ≤2, explicit UNMATCHED transitions, structural confidence. **For the charstream path the DP is bypassed entirely** — `align_book` returns forced 1-1 groups (`kind` = `group` / `skip_qn` / `skip_nom`) (revised 2026-11-12) |
| Scoring | `src/hannom/textdiff.py` (`auto_text_diff`) | N×M Needleman–Wunsch over reading-carrying Nôm chars vs QN token set; red candidates (never auto-yellow); `allow_flat_match` used only in `recompute_text_diff`; `allow_variant_fold` **defaults ON** (`textdiff.py:324`) at both callsites; align-time call is now **inside `_emit_rows` (`align.py:528`)** with `strict_reading_mismatch=False` (revised 2026-11-12) |
| Outputs | `configs/alignment.yaml`, `src/hannom/models.py` | 5-column CSV (`img_id, sentence_id, ch_txt, vi_txt, text_diff`) + `<Name>.review_metadata.jsonl` sidecar (flags/confidence/semantic_confidence/content_sha256); `CSV_COLUMNS` at `align.py:627`; BOM-writing path `write_alignment_csv` at `align.py:668` (`utf-8-sig` at `align.py:680`); `read_alignment_csv` at `align.py:697` (revised 2026-11-12) |
| Cross-checks | `src/hannom/orchestrator.py`, `evaluate.py`, `review_metadata.py` | Load/restore/patch/decisions chain, metric computation. `orchestrator.py` essentially unchanged (571 lines; only change = `misc` bin in `stage_labels`, `orchestrator.py:169`) — recompute_text_diff at `orchestrator.py:310-358`, UNVERIFIED_FLAGS at `evaluate.py:69-85` — all cites valid (revised 2026-11-12) |

The three books (align rows / CSV text_diff null, re-measured 2026-11-12):

| book_id | layout | clean pages (nom/qn) | align rows | CSV text_diff null | segmenter (2026-11-12) |
|---|---|---|---|---|---|
| T1_CamPhong_Tap1 | T1 (dịch âm-ish, Catholic imprint book, Vietnamese) | 130 / 144* | **823** | **1 (the `UNMATCHED_QN` skip_qn row; 0.1%)** | charalign-stream |
| T1_SuaLoiQuyen | T1 (Catholic moral text) | 50 / 60* | **380** | **0 (0%)** | charalign-stream (+ `strip_texts: ["所𥚇卷"]`, margin running head) |
| T1_CamPhong_Tap2 | T1 | 3 / 3 (incomplete) | 8 | 8 (100%) | cosegment (explicit `per_book`; unchanged artifacts, 2026-11-08) |

\* clean-page counts are pre-repair; the 2026-11-12 change-set re-binned Tap1 front matter PDF 013–020 → `vi/` (Nôm PDF 276–269 ↔ 013–020), moved Tap1 pages 277–282 (publisher back matter + two prompt-spill pages) and both books' glossary/reprint-cover pages to `misc/` (Tap1 glossary **143–144**, Tap3 glossary **62–63**, Tap1 reprint covers/forewords **5, 7–11**, Tap3 covers/forewords **2, 3, 5, 7, 8, 9**), and excluded Tap1 143–144 from the image map. A post-re-bin re-count of clean pages was **not** re-measured in this revision. (revised 2026-11-12)

Segmenter selection lives in `configs/alignment.yaml` → `alignment.per_book` (revised 2026-11-12):

```yaml
segmentation: cosegment                    # global default (preserved)
per_book:
  T1_SuaLoiQuyen:
    segmentation: charalign
    strip_texts: ["所𥚇卷"]               # margin running head (line filter on cleaned page text;
                                           # same option name as the pre-existing clean_nom_pages(strip_texts=…) in charalign.py)
  T1_CamPhong_Tap1:
    segmentation: charalign
  T1_CamPhong_Tap2:
    segmentation: cosegment                # explicit
```

`hannom.charstream` aligns both reading streams **globally** (banded NW, same alignment `hannom.charalign` uses) and PROJECTS QN sentence cut points onto the Nôm stream. Segments carry `COSEGMENTED_STREAM_ALIGNED`; one segment per QN sentence; empty-Nôm sentences → `UNMATCHED_QN` (text_diff = null). Tap1 has **exactly ONE** (`skip_qn`, warning `QN_SENTENCE_NO_NOM:529` in `summary.json`, img_id row `.100.jpg`); Tap3 has **ZERO** `UNMATCHED_QN`. The forced 1-1 rows **bypass the DP entirely** (`align_book` returns 1-1 groups with `kind` `skip_qn`/`skip_nom`); on any charalign exception → warning `CHARALIGN_SEGMENTS_FAILED:<type>…` **plus a loud fallback to cosegment**; `NO_SEGMENTS_FOR_ALIGNMENT` → loud failure. The sibling re-alignment (Tap1 2026-11-12 19:43, Tap3 2026-11-12 19:03 artifacts) is what decisions.md records as the similarity gains (see §3, §13.15, Revision log; audit trail: `docs/decisions.md` 2026-11-12 entries, esp. the *"charalign segmenter shipped"* entry and the map-repair entry, lines 18–23). (revised 2026-11-12)

---

## 2. Method & ground rules

- **READ-ONLY** on repo and `data/`. No API calls (no calls to kimhannom.fit.hcmus.edu.vn, no LLM APIs). `.env` and `hannom_API.md` were **not** opened.
- Initial scratch directory: `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E`. This revision used `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-E` (probe scripts listed under §11; outputs stay in scratch, nothing written to repo). (revised 2026-11-12)
- `python -m pytest -q` — **282 collected** (`--collect-only` re-run 2026-11-12: 282 items; new `tests/test_charstream.py` (2) and `tests/test_map_repair.py` (3)). All pass per the change-set record. (revised 2026-11-12; was **288**)
- Empirical measurements were done by: reading `data/align/<book>/summary.json`, parsing CSVs via Python (`utf-8-sig`), loading `.review_metadata.jsonl`, recomputing the alignment evidence chain in-memory (never writing) with the prebuilt reading map `data/dictionary/char_readings.json` (26,700 chars, sources = the 12 hvdic-family JSONL files) behind a minimal `DictionaryIndex`-compatible stub. The pipeline's own `build_dictionary_index` was **not** loaded in scratch (3.1 GB of JSONL); the prebuilt map is exactly the union of those 12 sources and reproduces pair/sentence evidence to within ±1 row of the stored `semantic_confidence` values (verified on both books, **pre-repair**; not re-measured against the 2026-11-12 artifacts — the evidence model changed with the segmenter). (revised 2026-11-12)
- Metrics cross-checks: `data/evaluation/<book>/metrics.json` recomputed from CSV+sidecar with the semantics of `evaluate.evaluate_rows` — **no longer reproduces exactly for the re-aligned books** (it reproduces only against the pre-repair CSVs). Post-repair, the stored artifacts were re-cross-checked read-only 2026-11-12: row arithmetic (Tap1 1 unmatched + 0 null + 441 unverified + 381 verified = 823; Tap3 0 + 0 + 152 + 228 = 380), coverage (0.4629 / 0.6000), unverified ratio (0.5358 / 0.4000), similarity inputs (red 709 / denominator 7065 → 89.96%; 205 / 3274 → 93.74%), `structural_confidence_mean` (0.9115 / 0.9622 — matches sidecar recompute), `evidence_insufficient_rows` (233 / 74 — matches sidecar ALIGN_EVIDENCE_INSUFFICIENT histogram), `semantic_evidence_rows` (823 / 380), warnings `UNVERIFIED_DIFFERENT_ROWS:136` / `:125` (== verified_match_rows). All internally consistent with metrics.json. Pre-repair metrics archived at `data/evaluation/<book>/metrics.20261112T120924Z.json` (Tap1) / `metrics.20261112T120355Z.json` (Tap3). See §8. (revised 2026-11-12)
- Internet search used once for grounding (Vecalign/Bertalign literature); nothing from it was executed.
- Guideline v2.1 governing gates (from `Quy_định_đồ_án_v2.1.extracted.txt`): alignment rows are translation pairs; 1-1/1-n/n-1/n-m only (n-m only on restructured translation); reading order per T1; `sentence_id = <image_id without .jpg>.<n>`; `[MASK]` never aligned; Nôm split at `。！？；：`, QN at `.?!;:`; hyphenated page-break joins first; an Nôm sentence may be merged/paraphrased by translation; the minimum meaningful unit is preferred; `text_diff` **must be null for non-1-1 rows**; 5 strict CSV columns, UTF-8 BOM allowed.

---

## 3. CRITICAL — C1: `stream_cosegment` silently drops QN sentences (SUPERSEDED-LIVE-PATH for Tap1/Tap3; dormant, unfixed) (revised 2026-11-12)

**Status 2026-11-12: this is an audit of the cosegment path, which is now live ONLY for T1_CamPhong_Tap2 (8 rows, artifacts 2026-11-08, untouched by the change-set). The two dịch-âm books re-aligned through `hannom.charstream`, which does not use this code path at all — so C1 is SUPERSEDED-LIVE-PATH for Tap1/Tap3 (the books no longer flow through `stream_cosegment`), but the defect itself is **unfixed** in `cosegment.py` and remains live for Tap2. The drop census below is a **pre-repair** measurement against the pre-repair CSVs; the finding stands for the Tap2 path and for any future fall-back to cosegment. (revised 2026-11-12)**

### 3.1 Mechanism (code)

`stream_cosegment` (`cosegment.py:232-374`) builds per-sights streams and joins every sentence's co-cut into segments; the emission loop is:

```python
# cosegment.py ~line 326-336
for idx, (a, b, _tcount) in enumerate(sentences):
    n_start_cum, n_end_cum = nom_cuts[idx]
    # nom text slice from nom_idx positions.
    n0 = nom_idx[n_start_cum] if n_start_cum < total_nom else len(nom_text)
    n1 = nom_idx[n_end_cum - 1] + 1 if n_end_cum > n_start_cum else n0
    nom_chunk = nom_text[n0:n1].strip()
    qn_chunk = qn_text[a:b].strip()
    if not nom_chunk or not qn_chunk:
        continue          # <-- silently drops the QN sentence (line ~333)
```

Two collapse modes create zero-width Nôm chunks:

1. **Monotone clamp collapse** (`cosegment.py:217-226`): per sentence, `start_cut = max(prev_end, min(total_nom, start_cut))`. Consecutive sentence boundaries that round to the same proportional index (tiny 1–3 token sentences are the first victims: share ≈ 0 ideographs, `round()` ties) produce `(i, i)` chunks → dropped.
2. **Anchor interpolation overshoot**: `_anchor_cuts` (`cosegment.py:167-229`) interpolates a cut from the two nearest bracketing anchors; a cut may land *ahead* of a small following sentence's ideograph allotment, and clamping then collapses the in-between tiny sentence to zero width → dropped (not hostile to anchor quality — it is the mechanism by which aggressive anchors eat little sentences).

The `qn_chunk` side is never empty for a non-empty QN sentence, so **the deletion is always of a whole QN sentence**. No row is emitted, no flag set, no counter recorded; `summary.json` (`orchestrator.py:433-448`) has no field for dropped sentences. The DP (`align_segments`) is never reached for these sentences, so **no `UNMATCHED_QN` rows can appear from this path**. On the **pre-repair** CSVs, `UNMATCHED_QN` count was **0 in all three books** (Tap1: `UNMATCHED_NOM=1, UNMATCHED_QN=0`; Tap3: neither) — statistically implausible given two imprint/front-matter-heavy QN streams. Post-repair, Tap1 has exactly one `UNMATCHED_QN` row — but it is produced by **charstream's empty-Nôm projection** (QN sentence with no aligned Nôm ops, `charstream.py:254-290`), **not** by this code path; Tap3 has zero; Tap2 (legacy artifacts) has none and is stale. (revised 2026-11-12)

### 3.2 Empirical measurements (read-only, **pre-repair**) (revised 2026-11-12)

Stream token budgets vs the **pre-repair** shipped CSVs:

| book | QN stream tokens (regex `[^\W\d_]+`, cleaned, white-space joined) | CSV vi_txt tokens | missing |
|---|---|---|---|
| T1_CamPhong_Tap1 | 26,222 | 24,598 | **1,624 (6.2%)** |
| T1_SuaLoiQuyen | 8,816 | 8,054 | **762 (8.6%)** |
| T1_CamPhong_Tap2 | 433 | 433 | 0 (only 2 of ~264 pairs covered) |

Whole-sentence accounting for Tap3: `qn_sentence_spans` over the concatenated stream yields **484 sentences**. A greedy consecutive-sentence matcher on CSV `vi_txt` covers **383/484 (101 sentences absent, incl. runs of 1-token fragments)** — after accounting for 8 rows that fail exact string matching (whitespace/page-separator artefacts of the matcher, not a real coverage gain) treated as covered, the token deficit (762) is the hard lower bound.

Cut/segment stability vs `anchor_window` (default 20, `cosegment.py:239`), reproduced on Tap3 and Tap1 with the prebuilt reading map, whole-book streams, read-only:

| book | window=20 → segments | window=20 → missing tokens | window=40 | window=60 → segments | window=60 → missing tokens |
|---|---|---|---|---|---|
| T1_SuaLoiQuyen | 449 | 253 (2.9%) | 396 | **341** | 1,861 (21%) |
| T1_CamPhong_Tap1 | 861 | 313 (1.2%) | — | 708 | 3,230 (12.3%) |

The **pre-repair** shipped Tap3 has exactly **341 rows** — consistent with window=20-style cut collapse plus heavy DP group merging (60 `ALIGNED_ONE_TO_MANY` + 48 `ALIGNED_MANY_TO_ONE` + 98 `NON_ONE_TO_ONE` merges; rows ≤ segments), not with window=60 (341 segments ≪ 341 rows once merged, impossible). The instability is a direct artefact of how the windowed anchor cuts interact with rounding: **more anchor freedom ⇒ more collapse ⇒ more deleted sentences**.

Drops are not limited to 1-token sentences; measured drop classes at window=20 (Tap3, prebuilt map): 1-token×3, 4-token×5, 5-token×1, 6-token×5, 7-token×2, 8-token×6, sentence headers (`Đoạn 10:`), and mid-length prose sentences (`Nói giễm là tội trọng hơn ăn trộm cướp.` — 8 tokens).

Post-repair reality check (re-measured 2026-11-12): the 2026-11-12 re-alignment produced **Tap1 727→823 rows** and **Tap3 341→380 rows**, with `UNMATCHED_QN` 1/0 — the delta came from the charstream segmenter projecting QN cuts onto the globally-aligned streams (which cannot silently delete a sentence: an unmatched QN sentence is emitted as an empty-Nôm segment), **not** from the emission-loop fix in §3.4, which was **not** implemented. C1 as literally written therefore describes the Tap2-relevant defect only. (revised 2026-11-12)

**Archive hazard (revised 2026-11-12):** `data/align/T1_SuaLoiQuyen/_pre-repair-2026-11-12/` contains a **runaway nested archive** — ~1,421 nested `_pre-repair-2026-11-12` directories (recursive listing hits path-length errors; the directory tree totals 359,543 bytes and is almost all path metadata, not content). Flag for cleanup. Tap1's `_pre-repair-2026-11-12/` archive is clean (3 files, 1,095,083 bytes). Both archives are pre-repair lineage, not live outputs.

### 3.3 Why the existing gates didn't catch it

- `STAGE_ALIGN` writes `summary.json` with `warnings` from `build_segments` (cosegment path) or from the charstream segmenter (`QN_SENTENCE_NO_NOM:<sidx>`, `CHARALIGN_SEGMENTS_FAILED:<type>…`, `NO_SEGMENTS_FOR_ALIGNMENT`) — the cosegment drop counter still does not exist.
- `evaluate_rows` consumes CSV rows only; it cannot see sentences that never arrived.
- `UNMATCHED_QN` requires the DP (or charstream) to see the sentence; on the cosegment path it never did.
- The only external hint is Tap3's `total_nom_chars = 8,560` (exact match with the stream's ideograph count — Nôm side is always fully covered; the QN side is the lost side). Same holds post-repair (Tap3 `total_nom_chars` = 8,560 in `metrics.json`). (revised 2026-11-12)

### 3.4 Required fix

1. In the emission loop, when a sentence span is non-empty but the co-cut collapses, emit a row instead of `continue`:
   - `UNMATCHED_QN` (+`NON_ONE_TO_ONE`, `TEXT_DIFF_NULL_NON_ONE_TO_ONE`) when the Nôm side is empty;
   - keep the normal path otherwise;
   - optionally re-cut with an `est` floor of `max(1, round(share))` for non-empty sentences and let the DP adjudicate.
2. Add to `summary.json`: `segments_dropped`, `qn_tokens_dropped`, `nom_ideographs_emitted`, `qn_tokens_stream`, `qn_tokens_emitted`, appended flags per dropped sentence.
3. Assert at end of `stage_align` (fail-closed): `emitted_qn_tokens + dropped_qn_tokens == stream_qn_tokens`. A mismatch is a blocking error.
4. Packaging validator: check `UNMATCHED_QN + rows == emitted segments`, report drops loudly; add a `sentence_coverage` metric.
5. Delete or flag zero-width segments: `if cuts collapse, do not skip`.

**Status 2026-11-12 (revised):** items 1–5 remain **unimplemented** in `cosegment.py` (the module is unchanged). The whole-sentence-`UNMATCHED_QN` outcome these items demand is, for the dịch-âm books, now delivered by construction via charstream + `align_book`'s forced `skip_qn` rows — but **only for books configured `segmentation: charalign`**. For Tap2 (cosegment), and for any book that falls back to cosegment, the silent-drop defect stands. Note the actual measured gain (Tap3 +39 rows / Tap1 +96 rows) came from charstream, not from this fix. The fix is still the right one for the cosegment path — do not close it as "done".

---

## 4. H1 — `UNVERIFIED_FLAGS` over-flagging (co-segmentation + evidence)

**2026-11-12 reframing (revised):** the live rows no longer carry `COSEGMENTED_ANCHOR/UNANCHORED` at all — the whole *anchored vs unanchored* axis this section and §9 were built around has been **retired by the segmenter change**. `ALIGN_EVIDENCE_INSUFFICIENT` remains the operative machine-vs-verified discriminator, and it now fires on 233/823 (Tap1) and 74/380 (Tap3) rows instead of 692/283. The gate still FAILS, but the mechanism is different and the measurements below are re-measured, not inferred.

### 4.1 The flags (definition, `evaluate.py:69-85`, unchanged)

```python
UNVERIFIED_FLAGS = frozenset({
    "DIFF_UNVERIFIED_NO_BOOK_READINGS",
    "DIFF_UNVERIFIED_DIFFERENT_TEXT",
    "DIFF_AMBIGUOUS_READINGS",
    "COSEGMENTED_UNANCHORED",     # <-- line 74 — still listed; **no longer emitted by any live row** (revised 2026-11-12)
    "REVIEW_METADATA_MISSING",
    "REVIEW_METADATA_MISMATCH",
    "REVIEW_METADATA_UNRESOLVED",
    "TEXT_DIFF_INVALID",
    "ALIGN_EVIDENCE_INSUFFICIENT", # <-- line 79
    "REVIEW_DECISION_STALE",
    "REVIEW_DECISION_MISMATCH",
    "REVIEW_DECISION_INVALID",
    "REVIEW_DECISION_CONFLICT",
})
```

### 4.2 Measured incidence (sidecar read-only, **re-measured 2026-11-12**) (revised 2026-11-12)

| flag | Tap1 | Tap3 |
|---|---|---|
| `COSEGMENTED_STREAM_ALIGNED` | **823/823 (100%)** | **380/380 (100%)** |
| `COSEGMENTED` (parent) | 823 | 380 |
| `ALIGN_EVIDENCE_INSUFFICIENT` | **233/823 (28.3%)** | **74/380 (19.5%)** |
| `COSEGMENTED_UNANCHORED` | **0 — flag retired, not emitted anywhere** | **0 — retired** |
| `COSEGMENTED_ANCHORED` | **0 — flag retired, not emitted anywhere** | **0 — retired** |
| `ALIGNED` (1-1) | **822** (+1 `UNMATCHED_QN` row) | **380** |
| `NON_ONE_TO_ONE` | **1** (the skip_qn row) | **0** |
| `ALIGN_LOW_CONF` | **39** | **4** |
| `SPANS_PAGES` | **126** | **42** |
| `DIFF_READING_MISMATCH` (error elements) | **650** | **224** |
| `DIFF_NO_READING_MISMATCH` (empty `[]`) | **172** | **156** |
| `DIFF_AMBIGUOUS_READINGS` | **362** | **120** |
| `TEXT_DIFF_NULL_NON_ONE_TO_ONE` | 1 | 0 |
| `UNMATCHED_QN` | 1 | 0 |
| rows carrying BOTH ANCHORED+UNANCHORED (union across scripts/groups) | **no longer measurable — flags retired on live rows** (pre-repair: 65) | **retired** (pre-repair: 56) |
| rows ANCHORED∩SPANS / UNANCHORED∩SPANS | **retired** (pre-repair: — / 152) | **retired** (pre-repair: — / 57) |

Arithmetic cross-check (re-measured 2026-11-12): Tap1 `err 650 + empty 172 + null 1 = 823` ✓; Tap3 `224 + 156 + 0 = 380` ✓; sidecar flag histograms match `summary.json` `flags` exactly on both books; `DIFF_READINGS_FROM_DICTIONARY` 821/379. Pre-repair archived values: Tap1 727 rows (ALIGN_EVIDENCE_INSUFFICIENT 692, UNANCHORED 596, ANCHORED 196, ALIGNED 602, NON_ONE_TO_ONE 125, ALIGN_LOW_CONF 27, SPANS_PAGES 185); Tap3 341 (283 / 251 / 146 / 243 / 98 / 27 / 74). (revised 2026-11-12)

### 4.3 Root cause: sentence-level reading evidence is weak, no longer dead (revised 2026-11-12)

`semantic_confidence` (fraction of reading-carrying Nôm chars with a unique-local anchor) distribution, re-measured 2026-11-12:

| book | median | ==0 | (0,0.25) | [0.25,0.5) | [0.5,0.75) | [0.75,1) | ==1 |
|---|---|---|---|---|---|---|---|
| Tap1 | **0.6176** | 4 | 68 | 161 | 351 | 176 | 63 |
| Tap3 | **0.7083** | 1 | 10 | 63 | 132 | 111 | 63 |

Rows <0.5 (the `ALIGN_EVIDENCE_INSUFFICIENT` bar — kind≠group forced rows, e.g. the Tap1 skip_qn row at 0.0, plus group rows below the bar): **233 Tap1 / 74 Tap3** (== `evidence_insufficient_rows` in `metrics.json` ✓). Rows ≥0.5: **590 Tap1 / 306 Tap3**. Pre-repair the same table read: median 0.069 / 0.086, <0.5 counts 692 (Tap1, 95.1%) / 283 (Tap3, 83.0%) — the 2026-11-12 re-alignment lifted sentence-level evidence dramatically (charstream's global-stream alignment produces far more anchored cut points), which is why `verified` rows jumped from 8→381 (Tap1) and 26→228 (Tap3) **with no policy change**. Strict unique-local anchoring on *both* sides (`anchors.py`) still systematically zeros out common Nôm function words (`也`, `而`, `之`, `不`…) — that mechanism is unchanged; it just no longer dominates.

The learned lexicon is still entirely quarantined (no provenance) — unchanged artifacts, re-confirmed in `summary.json` 2026-11-12:

| book | verified lexicon readings | quarantine (legacy pairs) | quarantine (unverified) |
|---|---|---|---|
| T1_CamPhong_Tap1 | `data.readings` = `{}` | 77 (47 chars), meta.learned_pairs=77 | 0 |
| T1_CamPhong_Tap2 | `{}` | 244 | 0 |
| T1_SuaLoiQuyen | `{}` | **22,388 (586 chars)** | 0 |

So dictionary (hvdic family via `DictionaryIndex`) is still the only evidence, and unique-local anchoring still caps it. Pair-level anchor verification (`t1_map.score_pairs_with_anchors`, bar = 0.5 coverage **and ≥2 anchors**, `t1_map.py:110-111`) verified **0/50** Tap3 pairs with exact matching (max pair coverage 0.28) and **0/50** even with accent-fold flat matching (max 0.14) — **pre-repair measurement**; the map it scored is gone (see §8). Level-1/level-2 bars relax to ≥1 anchor at 0.5 ⇒ still **0 pairs**. The pre-repair map for Tap3 was 50/50 `candidate`; Tap1 pairs were never anchor-scored (`status=None` — heuristic mass mapping). **Post-repair image_map: Tap1 127/127 `candidate`, all `content_dp`, `markers_used=70`, `mapping_source=content_dp` (proposed 2026-11-12T19:37:42); Tap3 50/50 `candidate`, `content_dp`, `markers_used=33` (proposed 2026-11-12T18:47:21).** The pair-level relaxation is still a dead end; the map no longer floats on heuristic luck. (revised 2026-11-12)

### 4.4 Policy simulation (re-measured 2026-11-12 on the re-aligned CSVs+sidecars; exact `evaluate._classify_row` semantics; baseline reproduces stored metrics.json **exactly**) (revised 2026-11-12)

Baseline reproduced = stored metrics: Tap1 verified **381** (136 match / 245 diff), unverified **441** (0.5358), null 0 (+1 `UNMATCHED_QN` classified `unmatched`), coverage 0.4629. Tap3 verified **228** (125 / 103), unverified **152** (0.4000), null 0, coverage 0.6000. (Pre-repair archived baseline: 8/594 and 26/217.)

| policy | Tap1 verified | Tap1 unv. ratio | Tap3 verified | Tap3 unv. ratio |
|---|---|---|---|---|
| baseline | **381 (136/245)** | 0.5358 | **228 (125/103)** | 0.4000 |
| drop `COSEGMENTED_UNANCHORED` | 381 (136/245) — **no-op; flag absent** | 0.5358 | 228 (125/103) — no-op | 0.4000 |
| drop `ALIGN_EVIDENCE_INSUFFICIENT` | 460 (138/322) | 0.4399 | 260 (131/129) | 0.3158 |
| drop **both** | **460 (138/322)** | 0.4399 | **260 (131/129)** | 0.3158 |
| drop 3 (also `DIFF_AMBIGUOUS_READINGS`) | 822 (172/650) | 0.0000 | 380 (156/224) | 0.0000 |

Row semantic-confidence ≥ thresholds (all rows — every row carries `semantic_confidence`): ≥0.25 → **751 tap1 / 369 tap3**; ≥0.33 → **721 / 360**; ≥0.5 → **590 / 306**. (Pre-repair, scored rows: 58/55, 40/49, 24/35.)

**Reading the table honestly (revised 2026-11-12):** dropping `ALIGN_EVIDENCE_INSUFFICIENT` still does **not** approach gate compliance (coverage ≈ 0.56 / 0.68 ≪ 0.9; unverified ratio ≈ 0.44 / 0.32 ≫ 0.05). The corpus still cannot self-verify; the gate remains *doing its job as a blocker*, and the correct response is human review + lexicon restoration + better evidence fusion — **not** silently loosening the bar. But note the pre-repair framing is obsolete: `COSEGMENTED_UNANCHORED` no longer punishes anyone (0 carriers), so the "double-count" pathology it described is gone with the flag — the reason it was a bad UNVERIFIED_FLAG is now moot; remove it anyway for hygiene or leave it harmlessly, but do not expect a metric shift from doing so. The honest gate conclusion is unchanged in direction, weaker in magnitude: coverage 0.46/0.60 and unverified ratio 0.54/0.40 still block.

### 4.5 Required fix

Keep for `verified`: `semantic_confidence ≥ 0.5` **or explicit human decision** (`ALIGN_EVIDENCE_INSUFFICIENT` stays fatal). Remove `COSEGMENTED_UNANCHORED` from `UNVERIFIED_FLAGS` — **now a no-op hygiene edit, not a metric lever** (the flag is retired on live rows; Tap2's stale artifacts are the only place it still exists, and they are being re-run anyway). (revised 2026-11-12) Keep `ALIGN_EVIDENCE_INSUFFICIENT` as the machine-vs-verified discriminator. Do not restore `DIFF_AMBIGUOUS_READINGS` to verified without a review rule (it marks genuine ambiguity).

---

## 5. H2 — DP band: wrong alignments systematically preferred

### 5.1 Mechanics (code)

`align_segments` (`align.py:387-455`) DP over segments; transitions: explicit UNMATCHED_NOM/UNMATCHED_QN at `unmatched_nom_penalty = unmatched_qn_penalty = 1.2` (`align.py:72-73`), plus groups ≤4×4 with `max_nm_group=2` (n-m only when both sides ≤2). Emission of rows (and the align-time `auto_text_diff` call) now lives in `_emit_rows` (`align.py:458-559`); the diff is computed at **`align.py:528`** for 1-1 rows. Group cost (`_group_cost`, `align.py:354-384`):

```python
observed  = vi_tokens / nom_chars                      # phonetic expectation ~1.0
expected  = max(0.25, expected_syllables_per_nom_char)  # default 1.0
ratio_cost = abs(log(max(0.05, observed) / expected))
group_cost = 0.35*(b-1) [1×n] / 0.35*(a-1) [n×1] / 0.90*(a+b-2) [n-m]
reading_bonus = 1.2 * (matched / known)   # unique-local matches
return max(0.0, ratio_cost + group_cost - reading_bonus)
```

A forced 1-1 group beats `skip_nom + skip_qn` (2.4) whenever `ratio_cost < 2.4`, i.e. obs ∈ (0.09, 11.05); the "two unmatched lose to a decent 1-1 but beat a badly-forced correspondence" comment (`align.py:69-73`) is accurate only at the extremes. Inside the band, **wrong alignments are preferred**, and are only filtered by `ALIGN_EVIDENCE_INSUFFICIENT` and `ALIGN_LOW_CONF` (**39 Tap1 / 4 Tap3** rows at `confidence = 1/(1+structural_cost) < 0.55 ⇔ cost > 0.82`; pre-repair: 27/27). (revised 2026-11-12)

**Bypass note (revised 2026-11-12):** for the two charstream books this entire DP analysis is latent — `align_book` forces 1-1 groups index-by-index and never calls the DP. The band, the penalties and the mis-preference analysis still govern (a) T1_CamPhong_Tap2 (cosegment), (b) any `CHARALIGN_SEGMENTS_FAILED` fallback, (c) any future cosegment default. Do not delete the DP; do not extend it either — the live dịch-âm path is deliberately non-DP.

Group penalties: n-m costs `0.90 × (a+b−2)` → 1.8 for 2-2, still < 2.4; 1-n/n-1 cost 0.35 per extra segment; a 4-1 costs 1.05.

### 5.2 `NON_ONE_TO_ONE` is absent from `UNVERIFIED_FLAGS` — the force-recompute loophole

`_classify_row` (`evaluate.py:105-161`): `elements is None` → `null` (never unverified-blocked); nonzero elements + no unverified flags → `verified_difference`. `NON_ONE_TO_ONE` is not in `UNVERIFIED_FLAGS` (exhaustive set), and `TEXT_DIFF_NULL_NON_ONE_TO_ONE` isn't either. Consequence: rows that were deliberately scored `null` at align time (n-1/n-m groups) become **automatic verified differences** when re-scored with `--force-recompute` (`cli.py` flag, `orchestrator.py:327-338`, lines `if row.text_diff is None and not force_recompute: ... out.append(row); continue`). The "keep null unless forced" design (CSV roundtrip loses flags ⇒ keep null) is only half-safe — force-recompute both re-admits them to scoring and loses the `NON_ONE_TO_ONE` protection at verification time.

**2026-11-12 context (revised):** the loophole is now narrow in practice — live null-diff rows exist only in Tap2 (8/8, pre-repair path) and the single Tap1 `UNMATCHED_QN` row (which classifies as `unmatched`, not `verified_difference`, because `UNMATCHED_QN` is checked first at `evaluate.py:151-152`). But it remains a structural hole and is unchanged in code; `orchestrator.py` is essentially untouched (only the `misc` bin at `orchestrator.py:169`). Align-time diff call now lives at `align.py:528` (inside `_emit_rows`); align-time passes **no** `allow_variant_fold`/`allow_flat_match` → **variant fold ON (1.0-cost anchor; `textdiff.py:324` default), flat match OFF (align-time)**. The recompute path (`orchestrator.py:349`) passes `allow_flat_match=True` and likewise **no** `allow_variant_fold` → variant fold ON there too. The variant fold (quỷ/quỉ/quĩ→qui, d/gi, đ/d — added in the change-set, see decisions.md 2026-11-12) therefore fires at **both** callsites with weight 1.0, while the flat tone-stripped match is OFF at align-time / ON at recompute-time — an asymmetry worth documenting before anyone relies on either. (revised 2026-11-12)

### 5.3 Required fix

1. Add `NON_ONE_TO_ONE` (and `TEXT_DIFF_NULL_NON_ONE_TO_ONE`) to a classification-level safeguard, not necessarily `UNVERIFIED_FLAGS`: classify force-recomputed non-1-1 rows as `unverified`; or refuse to re-score `NON_ONE_TO_ONE` rows at all (`force_recompute` should map them to *unverified*, not 1-1 candidates).
2. Fix the comment/statement in `align.py` to state the true band (`unmatched` wins only when `ratio_cost > 2.4`).
3. Keep `n-m ≤ 2×2`, `max_group=4`, `0.90` many-to-many — sensible for T1; no evidence to change.
4. If `ALIGNED_MANY_TO_MANY` rows are structurally untrustworthy under restructured translation, consider routing all `NON_ONE_TO_ONE` automatically to unverified classification regardless — safer default, unchanged current gate behavior (currently they're `null` anyway).

---

## 6. H3 — Tap2 is stale, incomplete, and would fail closed on re-load

- `summary.json` / CSV / `.review_metadata` **absent** for T1_CamPhong_Tap2 (mtime 2026-11-08 20:02) — **before** the `3d8e4f2` repair commit (2026-11-09 18:52), before the second/third repair passes (`e0107ec`, `f0d5b05` rewrites for evidence/integrity), and before the 2026-11-12 map-repair change-set. Its 8 rows are pre-repair artifacts: 525 `MISSING_CLEAN_PAGE:T1_Cấm Phòng Cho Bổn Đạo (Tập 2).NNN.jpg` warnings (clean = 7 files: 3 Nôm + 3 QN; 592 Nôm ideographs; 18 stream sentences in cleaned set) — the translation is essentially absent from the run.
- No `COSEGMENTED` flag anywhere; `CROSS_PAGE_JOIN` on all 8 rows; `NON_ONE_TO_ONE` 8/8; `SPANS_PAGES` 5/8; `ALIGN_LOW_CONF` 3/8 — the pre-repair per-page fallback path produced these.
- On `load_rows_for_evaluation` all 8 rows would be flagged `REVIEW_METADATA_MISSING` (blocking), and Tap2 `metrics.json` (2026-11-08, pre-D-gate) shows only `EMPTY_DENOMINATOR` with no verified fields.
- **2026-11-12 update (revised):** the sibling books were re-aligned on 2026-11-12 (Tap1 19:43, Tap3 19:03 artifacts; real dictionary; `per_book` charalign) **while Tap2 was left untouched** — its CSV (line 5 stale), sidecar absence, and 11/08 `metrics.json` are all unchanged and now visibly out of line with the rest of the corpus. This is a **deadline risk**, not just hygiene. Post-rerun, expected state must be: explicit `segmentation: cosegment` (as now configured), `COSEGMENTED_*` flags, sidecar present, all rows null or reviewed — never silently clean.
- **Action needed**: rerun align for Tap2 after full OCR/clean coverage (it is genuinely out of scope of the audit in terms of content, but its shipped artifacts are unusable — and now the only un-repaired book in the corpus).

---

## 7. M1 — Regex class is wrong (`[A-ZÀ-Ỹ…]` matches U+00C0–U+1EF8)

### 7.1 Definition and code

```python
# cosegment.py:33  SENTENCE_UPPER_RE = re.compile(r"[A-ZÀ-Ỹ0-9\"“(\[]")   # UNCHANGED 2026-11-12
# align.py:31      QN_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\u2026])\s+(?=[A-ZÀ-Ỹ\"“(\[]|\d)")              # UNCHANGED
```

The literal range `À-Ỹ` spans **U+00C0–U+1EF8 = 7,737 codepoints**. Empirical block counts (via `unicodedata.name`): Latin-1 and Latin Extended pages mostly intended, plus **Greek 131**, **Cyrillic 307**, **Hebrew 88**, **Arabic 416**, **Armenian 89**, and **814 unassigned** codepoints. Intended Vietnamese uppercase set (À Á Â Ã È É È È Ê Í Ò Ó Ô Õ Ù Ú Ư + Latin Extended-A/B/C… and U+1EA0–U+1EF8 uppers) is a sparse subset; the class also swallows every *lowercase* Latin-1/Additional letter (à, á, ạ, ệ, ủ, ư, ỹ is excluded as the upper endpoint exactly at Ỹ U+1EF8, but ỵ U+1EF5 matches, etc.).

Font note: CJK (starts U+2E80/0x3400) and Hangul (U+AC00) are **not** in the range — so Nôm side is unaffected; and CJK punctuation 、。 doesn't match.

### 7.2 Real-data impact (measured)

| book | stops tested | extra boundaries from lowercase-in-range | intended-class boundaries |
|---|---|---|---|
| T1_SuaLoiQuyen | 621 | **2** | 481 |
| T1_CamPhong_Tap1 | 970 | **0** | 894 |

So per the audit instruction: **spec deviation, minor in practice** — but two systematic consequences remain:

1. **Stream path lacks the abbreviation guard**: `qn_sentence_spans` (`cosegment.py:36-55`) splits after any stop followed by uppercase-like/digit/quote/paren/bracket — `"Tp. Hồ Chí Minh"` splits after `Tp.` (`H` matches), `"Mr. Smith"` splits too (and `Dr|St|No|v|p|fig.` likewise). The guard (`_QN_ABBREV_RE`, `align.py:32`) exists only inside `split_qn_page` (the fallback path), not in the stream path. **2026-11-12 escalation (revised): this is no longer a cosegment-only concern — `qn_sentence_spans` is the sentence splitter `hannom.charstream` uses for the LIVE dịch-âm segmentation of both re-aligned books (`charstream.py:30,145`). The abbreviation defect is therefore inherited by the live path verbatim (`"Tp. …"` / `"Mr. …"` mid-sentence splits shift row boundaries for 823/380 rows). Treat as a live-data-correctness defect, not a dormant one.**
2. **Stream vs fallback splitters disagree on `;`/`:`**: `qn_sentence_spans` uses `SENTENCE_STOP_RE = [.!?;:]` (`;` and `:` are stops, line 32), while `QN_SENTENCE_SPLIT_RE` (page-split) only allows `.!?…`. The fallback path therefore under-segments relative to the stream path; different rows, different groups, different flags for the same book. (Still true; fallback path unchanged.)

The impact counts above were measured **pre-repair** but the splitter function is unchanged, so they hold for both the cosegment path and the charstream path (same `qn_sentence_spans`). (revised 2026-11-12)

### 7.3 Required fix

- Build the uppercase class from actual cased uppercase Vietnamese letters (\u1EA0-\u1EF8 uppers + Latin-1/A/B uppers, or use regex `\p{Lu}`-equivalent logic; Python `re` has no `\p{Lu}`, so use an explicit class or `str.isupper()` on the following lookahead token).
- Mirror `_QN_ABBREV_RE` (or its generalized form) into `qn_sentence_spans` — **now doubly important: it protects the live charstream cut points**, e.g. negative lookbehind `(?<!Mr)(?<!Mrs)(?<!Dr)(?<!St)(?<!No)(?<!Tp)\.\s+` or simpler: skip a stop when the token ending at the stop is a known abbreviation.
- Align both splitters on the same terminal set (`.?!;:` per the guideline `'.?!;:'`, adding `…` where clean converts it); delete or use `TERMINAL_QN` (`clean.py:48`, currently unused).

---

## 8. Verified-good list (cross-checked, re-measured 2026-11-12) (revised 2026-11-12)

Claims independently re-measured (read-only, against the re-aligned artifacts) — or explicitly labeled pre-repair:

- **Sidecar integrity**: `content_sha256` re-verified against CSV content for **1203/1203 rows** (Tap1 823/823, Tap3 380/380) using `hannom.review_decisions.content_sha256` (probe5, 2026-11-12). No `REVIEW_METADATA_*` issues would fire on reload; CSV roundtrip loses flags but sidecar restores them exactly (`restore_review_metadata`). Sidecars: **823 / 380 lines, 408,571 / 169,644 bytes**. (Was 1068/1068.)
- **Null-preservation chain**: `_emit_rows` emits `null` + `TEXT_DIFF_NULL_NON_ONE_TO_ONE` + `NON_ONE_TO_ONE` for every non-1-1 row (`align.py:543-545`); align-time `auto_text_diff` is called only for 1-1 rows (`align.py:527-535`); CSV stores literal `null`; `load_rows_with_metadata` restores the flag; `recompute_text_diff` keeps null for `NON_ONE_TO_ONE`/empty-side rows unless `--force-recompute` (`orchestrator.py:327-338`); **verified 2026-11-12: Tap1 has exactly 1 row with `text_diff == null` (the `UNMATCHED_QN` skip_qn row, `img_id …100.jpg`), Tap3 0; `TEXT_DIFF` structural invalidity = 0 on both books** (CSV error-element census: 650 rows with error elements + 172 empty `[]` + 1 null = 823 ✓; Tap3 224 + 156 + 0 = 380 ✓). (Was: all 125/98 non-1-1 rows null.)
- **Metrics reproduce**: **no longer "exactly" — superseded (revised 2026-11-12).** Pre-repair the recomputed values matched stored `metrics.json` 1:1 (Tap1 similarity 87.3626% over denominator 182; coverage 0.0110; unverified 0.8171, null_ratio 0.1706, EXCESSIVE_NULL_ROWS present; Tap3 85.8696% / 0.0762 / 0.6364 / 0.2874). Re-aligned `metrics.json` (2026-11-12 19:43 / 19:03) now reads: **Tap1 similarity 89.9646 (denominator 7065, red 709), coverage 0.4629 (381/823), unverified ratio 0.5358 (441 rows), null_ratio 0.0, 0 yellow, passed=false** (issues: `INSUFFICIENT_COVERAGE:0.4629<0.9`, `UNVERIFIED_RATIO_HIGH:0.5358>0.05`, `SIMILARITY_BELOW_GATE:89.9646<95.0` — **`EXCESSIVE_NULL_ROWS` is GONE**); warnings `UNVERIFIED_DIFFERENT_ROWS:136`. **Tap3 similarity 93.7385 (denominator 3274, red 205), coverage 0.6000 (228/380), unverified 0.4000 (152), null_ratio 0.0, passed=false** (same three issues with same prefixes; `SIMILARITY_BELOW_GATE:93.7385`); warnings `UNVERIFIED_DIFFERENT_ROWS:125`. Pre-repair metrics archived: `metrics.20261112T120924Z.json` (Tap1), `metrics.20261112T120355Z.json` (Tap3). All row-arithmetic and sidecar-flag cross-checks performed this revision are consistent with the stored artifacts (see §2, §4.2).
- **Verified rows by class**: Tap1 **136 match** (== `UNVERIFIED_DIFFERENT_ROWS:136` warning, all ch≠vi auto-clean) **+ 245 difference** = 381 scored; Tap3 **125 match + 103 difference** = 228 scored. Positive semantic evidence on all verified rows (bar ≥0.5). By construction these are machine-classified, not human-verified. (Was: Tap1 2/6, Tap3 7/19, 9 total match rows — pre-repair.)
- **`csv` file format**: UTF-8 BOM (`utf-8-sig`, `align.py:680`), `\n` terminator, exactly 5 columns (`CSV_COLUMNS`, `align.py:627`), LF; `read_alignment_csv` rejects other schemas; required by spec (BOM allowed). Re-checked 2026-11-12 on both re-aligned CSVs ✓ (BOM present; header `['img_id', 'sentence_id', 'ch_txt', 'vi_txt', 'text_diff']`). Tap2 unchanged (BOM ✓, 5 cols ✓).
- **sentence_id contract**: per-img_id counter (`align.py:480-483`); `img_id` = `<Name>.<page>.jpg` (ends `.jpg` on all rows); `<img_id without .jpg>.<n>` format confirmed on all **1,203** rows; zero duplicates; **max suffix 15 (Tap1) / 16 (Tap3)** (pre-repair: 26). Tap1 CSV sequence is **NOT monotone at the skip_qn row** (row index 529, `sentence_id …100.1`; break between two `.189.jpg` rows): the empty-Nôm row's `TextSegment.image_name` is set from the QN-side page (`charstream.py` sets `ch_image = vi_image` when no Nôm ops are selected, then passes it as the Nôm segment's `image_name`; `align_book` emits `img_id` from `nom_group[0].image_name`, `align.py:480`) — known anomaly, one row, flagged `UNMATCHED_QN` + `ALIGN_EVIDENCE_INSUFFICIENT` (+`NON_ONE_TO_ONE`, `TEXT_DIFF_NULL_NON_ONE_TO_ONE`). **Tap3 sequence is monotone ✓**. (revised 2026-11-12)
- **Ordering**: `t1_map` sorts ch descending / vi ascending; pairs list respects both; Tap3 page sequence strictly non-increasing across rows ✓; Tap1 non-increasing except the single `.100.jpg` skip_qn spike above; no other interleaving anomalies.
- **`img_id` = head page** (first page in reading order) for stream `SPANS_PAGES` rows and for cross-page fallback joins — correct per guideline (img of page holding sentence head); cross-page join keeps the first page's `image_name` (corrected cites: the join helper is `_may_join_across_pages` at `align.py:167`; the head-page rule realized at `align.py:480-483`). **Exception: the Tap1 skip_qn row's `.100.jpg` (QN-side fallback, see above).** Tap2 keeps its old behavior. (revised 2026-11-12)
- **Monotonic cuts**: `_anchor_cuts` clamps to `[0, total_nom]` and enforces non-decreasing boundaries (`cosegment.py:217-226`); `order_no` reindexed sequentially after emission (`cosegment.py:369-374`) — cosegment path only; charstream cut points are monotone by construction of the global alignment. Tap2 unaffected.
- **`SPANS_PAGES`**: set iff >1 page on the respective side (`cosegment.py:297-321` QN-side `chunk_pages`, `309-321` Nôm-side `nom_chunk_pages`; charstream sets it from union-of-op-pages spans, `charstream.py:274-275`); **data confirms 126 (Tap1) / 42 (Tap3)** (pre-repair: 185/74). The old "ANCHORED∩SPANS / UNANCHORED∩SPANS (152/57)" sub-claims are **retired** with the flags (no longer emitted; not measurable on live rows).
- **Co-segmentation window mechanics** (Tap2-only live today; dormant Tap1/Tap3): bracketing rule (`left: token_index < tok_mid`, `right: ≥ tok_mid`), monotone pairs, `gap ≤ max_gap_tokens`, interpolation via QN char offsets, cuts clamped into `[0,total_nom]`, `COSEGMENTED_ANCHORED` only when both boundaries anchored, else `COSEGMENTED_UNANCHORED` (`cosegment.py:167-229, 337-344`); stream edges never counted as unanchored (boundary indices 1..len-1 only) — code still correct, dormant for the dịch-âm books.
- **`_split_long_text` cut marks**: works on U+3001 (、) and U+FF1B (；); mid-limit fallback hard cut confirmed (see M2). `align.py:108` (was :97).
- **`cosegment_pair` / `anchors` agree**: segments ≥80 % ideology-only chars; `is_nom_char` never matches Latin or `[MASK]` — no MR-aligned content (texts contain zero `[MASK]`; total MASK tokens in rows = 0). Tap2 unchanged.
- **Tap1 pages coverage / book math (rewritten; pre-repair version obsolete)**: the 2026-11-12 map-repair re-paired the books by content-DP + QN-header parenthetical cross-references: **Tap1 127/127 pairs `candidate`, all `content_dp` (`mapping_source=content_dp`, `markers_used=70`, proposed 2026-11-12T19:37:42; glossary 143–144 excluded); Tap3 50/50 `candidate`, `content_dp` (`markers_used=33`, proposed 2026-11-12T18:47:21)**. Tap1 front matter PDF 013–020 (covers/foreword/TOC — the print edition's translation of the Nôm title/TOC) is re-binned `vi/` and enters the map as extra pairs (Nôm PDF 276–269 ↔ PDF 013–020). Pages 277–282 (Tap1 publisher back matter + two Vintern prompt-spill pages) and the CHÚ THÍCH glossary → `misc/`; Tap1 glossary 143–144 & Tap3 glossary 62–63 and the reprint covers/forewords → `misc/` (decisions.md 2026-11-12 *aparat/bin split* entry). **Pre-repair this read: "130 ch → 124 pairs; 144 QN → 124 pairs; Tap3 50 pairs; Tap1 pairs status=None heuristic mass mapping" — all superseded.** Tap2 beyond scope. (revised 2026-11-12)
- **`evaluate._classify_row`**: non-1-1 rows with `UNMATCHED_*` flags classify as `unmatched` (checked before the elements-null branch, `evaluate.py:151-152`) — Tap1's single null-diff row is therefore **`unmatched`, not `null`** (metrics `unmatched_rows=1`, `null_rows=0`, exactly as stored). Otherwise `elements is None` → `null` (correctly excluded from verified and unverified arithmetic).
- **Guideline compliance where measurable**: 5-column schema ✓ both books; BOM ✓; per-image ids ✓; head-page img_id ✓ except the one documented skip_qn fallback row; T1 reading order ✓ except the same row; `null` for non-1-1 ✓; no invented semantics (auto_text_diff invents no reds without learned/dictionary evidence; zero-human-input corpus as expected pre-review).
- **Tap3 gate path unchanged** (`metrics.json` regenerated 2026-11-12): still `passed=false`, same three gate issues (INSUFFICIENT_COVERAGE / UNVERIFIED_RATIO_HIGH / SIMILARITY_BELOW_GATE); `EXCESSIVE_NULL_ROWS` no longer fires (null_ratio 0.0).
- **`cosegment.py` dormant but intact for Tap1/Tap3; live for Tap2** — do not "clean up" the cosegment path; Tap2 needs it.
- **`charalign.py`'s diagnostic CLI remains explicit/offline; its primitives are now load-bearing** (see §13.15) — unchanged as a file. **`hannom.charstream` is LIVE** (not diagnostic): it is the segmenter for both dịch-âm books. (revised 2026-11-12)
- **image_map candidate-only** ✓ (Tap1 now `content_dp`, `markers_used` 70; Tap3 `content_dp`, `markers_used` 33; all `status=candidate` — the map is evidence-ranked, still not human-confirmed).

---

## 9. Policy simulation table (reference; **re-measured 2026-11-12**, supersedes the pre-repair table) (revised 2026-11-12)

Parameters: rows parsed from the re-aligned CSVs (`text_diff` null ↔ elements present), flags from sidecar, **no review decisions present** (`data/output/` carries no decision logs — verified read-only), belt-and-braces repeat of §4.4. Semantics = `evaluate._classify_row` exactly; baseline row reproduces stored `metrics.json` exactly.

| book | policy | verified (match/diff) | unverified | null | coverage | unverified ratio |
|---|---|---|---|---|---|---|
| Tap1 | baseline | **381 (136/245)** | 441 | 0* | **0.4629** | **0.5358** |
| Tap1 | drop `COSEGMENTED_UNANCHORED` | 381 (136/245) — no-op (flag absent) | 441 | 0 | 0.4629 | 0.5358 |
| Tap1 | drop `ALIGN_EVIDENCE_INSUFFICIENT` | 460 (138/322) | 362 | 0 | 0.5589 | 0.4399 |
| Tap1 | drop both | **460 (138/322)** | 362 | 0 | **0.5589** | **0.440** |
| Tap1 | drop 3 (`+DIFF_AMBIGUOUS_READINGS`) | 822 (172/650) | 0 | 0 | 0.9988 | 0.000 |
| Tap3 | baseline | **228 (125/103)** | 152 | 0 | **0.6000** | **0.4000** |
| Tap3 | drop `COSEGMENTED_UNANCHORED` | 228 (125/103) — no-op (flag absent) | 152 | 0 | 0.6000 | 0.4000 |
| Tap3 | drop `ALIGN_EVIDENCE_INSUFFICIENT` | 260 (131/129) | 120 | 0 | 0.6842 | 0.3158 |
| Tap3 | drop both | **260 (131/129)** | 120 | 0 | **0.6842** | **0.316** |
| Tap3 | drop 3 (`+DIFF_AMBIGUOUS_READINGS`) | 380 (156/224) | 0 | 0 | 1.0000 | 0.000 |

\* Tap1's single `text_diff == null` row classifies as `unmatched` (`UNMATCHED_QN` checked first, `evaluate.py:151-152`) — not `null`; metrics: `unmatched_rows=1`, `null_rows=0`. Tap3: none. (Pre-repair table archived: baselines 8/594/125 and 26/217/98; the "drop both" 460/203 rows; the 602/243 drop-3 rows — all superseded.)

**Dual-inflation / UNANCHORED-overlap rows of the pre-repair table are retired** (the flags no longer exist on live rows; 65/56 overlap and 152/57 span-overlap are no longer measurable). Re-measured anchor facts instead: Tap1 median semantic_confidence 0.6176 (≥0.5: 590 rows), Tap3 0.7083 (≥0.5: 306 rows).

Pair-level relaxations (`t1_map`): Tap3 pairs verified @ (≥2 anchors ∧ coverage ≥0.5) = **0/50**; @ (≥1 anchor ∧ coverage ≥0.5) = **0/50**; @ coverage ≥0.25 = 1/50; flat-unique best 0.14/pair — **pre-repair measurement against the pre-repair map**; the map it scored is superseded by the content-DP repair (§8). Tap1 pairs never anchor-scored (`status` was `None`; now all `candidate`/`content_dp` — still unscored by t1_map). Pair-level relaxation remains a dead end — sentence-level or human evidence is required.

---

## 10. Recommendations (ranked)

1. **[C1] Never drop co-segmented sentences.** Emit an `UNMATCHED_QN` row (flags `UNMATCHED_QN`, `NON_ONE_TO_ONE`, `TEXT_DIFF_NULL_NON_ONE_TO_ONE`) for every non-empty QN sentence whose Nôm co-cut collapses (`cosegment.py` emission loop). Add `qn_tokens_stream/emitted/dropped`, `segments_dropped` and a per-dropped-sentence flag to `summary.json`; assert stream-vs-emitted token parity at end of `stage_align` (fail-closed). **Expected-effect correction (revised 2026-11-12): do not expect this fix to produce the 341→380 / 727→823 row gain anyone measured this week — that gain already happened, delivered by `hannom.charstream` (global-stream alignment + QN-cut projection), not by this fix, which was never implemented. What this fix restores is the invariant "no silently deleted sentence" for the **cosegment** path — i.e., for Tap2 and for any future fall-back.** The live dịch-âm books already satisfy the substance of this item (empty-Nôm sentences are emitted as `UNMATCHED_QN` rows, e.g. Tap1's `…100.1` row, plus `QN_SENTENCE_NO_NOM:<sidx>` in `summary.json`), but only because of charstream — the emission loop still drops silently. Minimum meaningful unit restored everywhere, not just by accident of configuration.
2. **[C1] Floor the proportional estimate for tiny sentences.** `est = round(tok_off*total_nom/total_tok)` ties for 1–3 token fragments; use `floor/ceil` monotonic rounding with a minimum 1-ideograph span for any non-empty sentence that no anchor brackets (don't rely on clamping alone). (Unchanged; still unimplemented; cosegment-path-only.)
3. **[H1] Remove `COSEGMENTED_UNANCHORED` from `UNVERIFIED_FLAGS`** (`evaluate.py:74`). **2026-11-12: this is now a no-op for live data** (flag retired on live rows — zero carriers), retained as a hygiene/consistency edit whenever `UNVERIFIED_FLAGS` is next touched. Segmentation uncertainty is already expressed in `confidence`; double-counting no longer exists in practice. Keep `ALIGN_EVIDENCE_INSUFFICIENT` as the machine-vs-verified discriminator. (revised 2026-11-12)
4. **[H1] Restore lexicon evidence before the next align run.** Promote quarantined legacy pairs/chars through `BookLexicon.restore_quarantine()` after human review of the 22,388 Tap3 / 77 Tap1 / 244 Tap2 entries; even partial restoration (say the top ~20% by count) restores sentence-level anchoring on the repetitive function words that unique-local anchoring currently zeroes out. Until then, and until review begins, do not change the coverage gate. **2026-11-12 update: the re-alignment already lifted machine-verified rows to 381 (Tap1) / 228 (Tap3) without lexicon restoration — evidence sufficiency, not flag policy, was the binding constraint. The gate still fails (coverage 0.46/0.60; unverified ratio 0.54/0.40); lexicon restoration is now about *certifying* more of those rows, not about finding them.** (revised 2026-11-12)
5. **[H1/scale] Raise verified coverage the honest way**: (a) unblock lexicon review (see 4); (b) the change-set already folded a **weak variant fold** (quỷ/quỉ/quĩ→qui, d/gi, đ/d; decisions.md 2026-11-12) into the NW matcher at 1.0-cell weight at **both** callsites — align-time (via default) and recompute-time — with flat tone-stripped match still align-time OFF / recompute-time ON; measure its contribution in the report instead of adding a third matcher; rows ≥0.5 under the measured (unique-local) evidence: **590 (Tap1) / 306 (Tap3)**; (c) keep `ALIGN_EVIDENCE_INSUFFICIENT`; (d) do not claim v2.1 compliance from machine-only rows. None of this flips the gate (drop-ALIGN_EVIDENCE_INSUFFICIENT coverage would be only 0.56/0.68 — still ≪ 0.9); it raises trustworthy coverage linearly. (revised 2026-11-12)
6. **[H2] Fix the `NON_ONE_TO_ONE` force-recompute loophole.** In `recompute_text_diff` (`orchestrator.py:327-338`), skip `force_recompute` for rows flagged `NON_ONE_TO_ONE` (leave the null), or classify such re-scored rows `unverified` regardless of elements. Update the comment block; add a unit test. (Unchanged; still unimplemented; narrower relevance after 2026-11-12 — only Tap2's 8 rows and Tap1's one `UNMATCHED_QN` row carry the null.)
7. **[H2] Document the true DP band** — `align.py` comment near `unmatched_nom_penalty` (`align.py:69-73`): `unmatched` wins only when `ratio_cost > 2.4` (obs <0.09 or >11). Keep `2×1.2`, `max_nm_group=2`, `max_group=4`, penalties 0.35/0.35/0.90 (all consistent with T1). (Unchanged; the comment itself is still accurate at its extremes; now also document the charstream DP-bypass in the same block.) (revised 2026-11-12)
8. **[H3] Re-run T1_CamPhong_Tap2** after OCR/clean coverage is complete; quarantine its stale outputs; ensure the re-run produces sidecar and the D-gate (not the 11/8 file) measures it. **2026-11-12: siblings re-aligned 11/12 — Tap2 is now the only stale book in the corpus (deadline risk; its `per_book` is explicitly cosegment).** (revised 2026-11-12)
9. **[M1] Fix the sentence-uppercase classes** — `SENTENCE_UPPER_RE` (`cosegment.py:33`) and `QN_SENTENCE_SPLIT_RE` (`align.py:31`): replace `[A-ZÀ-Ỹ…]` with an explicit Vietnamese uppercase class (e.g. `[A-ZĂÂĐÊÔƠƯÀÁẢÃẠẰẮẲẴẶẦẤẨẪẬÈÉẺẼẸỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲÝỶỸỴ]` plus the sub/unparenthesized Latin-1 uppers used) or decode via `unicodedata.category(ch)=='Lu'` on the lookahead token; add the `_QN_ABBREV_RE` abbreviation guard (or equivalent) to `qn_sentence_spans` — **the same guard now protects the live charstream cuts**; make `;:` handling identical in stream and fallback paths; delete or repurpose unused `TERMINAL_QN`. **2026-11-12 escalation: this is a live-path defect for both re-aligned books, not a dormant one — impact counts measured pre-repair (2/621 stops in Tap3, 0/970 in Tap1; both books' live cuts derive from the same `qn_sentence_spans`).** (revised 2026-11-12)
10. **[M2/M8] Fallback segmentation hygiene** — add `U+FF0C` to `_split_long_text` marks (`,`, space, `;`, `、` (U+3001), `；` (U+FF1B), `，` (U+FF0C), and ideally `〃` (U+303F)) (`align.py:116`); clamp Nôm mid-word hard cuts to clause boundaries when available; emit `LONG_SEGMENT` flag for stream rows > 160 ideographs (Tap1 has ≥1 at 1,854 ideographs / 7,220 QN chars — re-check on the re-aligned CSVs) or a configurable split at clause punctuation for stream mode — the current `max_nom_chars=80` cap never applies to stream output (cosegment **nor** charstream). (revised 2026-11-12)
11. **[M7] De-duplicate the co-segmentation surface** — delete `cosegment_pair` (no production callers; its docstring still claims it "is used as a fallback" although `build_segments` never calls it) **or** wire it as the real fallback with a `FALLBACK_SEGMENTATION` flag — **note the change-set's `CHARALIGN_SEGMENTS_FAILED` loud fallback in `align_book` (`align.py:584-593`) now occupies this role for the charstream books (falls back to cosegment, loudly), which partially supersedes this item for them**; delete dead `MAX_ANCHOR_GAP_TOKENS` or apply it (it is inert vs `anchor_window=20`); make `anchor_window` sentence-relative (`window = max(30, k × sentence_tokens)`); ensure anchor cuts may never collapse a neighboring segment to zero width — reject/flag/count instead of clamping into dropping (see 1). (revised 2026-11-12)
12. **[M5/L6] Hygiene & honest reporting** — remove double-pass flag union or namespace it (`DIFF_ALIGN_*` vs `DIFF_RECOMPUTE_*`) so rows cannot carry both `DIFF_READING_MISMATCH` and `DIFF_NO_READING_MISMATCH` anonymously; persist per-segment anchor flags sidecar or change row semantics to `min()`; add `UNVERIFIED_DIFFERENT_ROWS`-style warnings to the report with an explicit note that for dịch âm books `ch_txt ≠ vi_txt` by construction — **2026-11-12: this warning now fires at 136 (Tap1) / 125 (Tap3), exactly the verified_match counts (all ch≠vi auto-clean rows); the note must cite these numbers**; print `dropped_qn_sentences` in every affected report/page; when Tap2 metrics are regenerated, replace the 11/8 artifact; note in the thesis/report that zero rows in this corpus are human-verified yet automatic `verified_*` rows are gate inputs — the 0.9/0.05/0.05 policy stays a fail (it does — similarity 89.96/93.74 < 95, coverage 0.46/0.60 < 0.9, unverified 0.54/0.40 > 0.05) and must be documented as such. **Whole-sentence `UNMATCHED_QN` is now possible and present** (Tap1 `…100.1` row; warning `QN_SENTENCE_NO_NOM:529` in `summary.json`) — report it explicitly; `UNMATCHED_NOM` is currently 0 on both books. (revised 2026-11-12)

**Config hints**

- `configs/alignment.yaml`: **2026-11-12 — both suggestions are superseded (revised).** (i) `anchor_window` is moot for the dịch-âm books — `hannom.charstream` segments via banded global NW (`band=400`), not the windowed cut heuristic; `anchor_window=20` remains cosegment-only. Do not set it from row count. (ii) `allow_flat_match: true` for the recompute pass only is **already the case** (`orchestrator.py:349`), and the align-time/recompute **variant fold is default-on at both callsites** (`textdiff.py:324`; decisions.md 2026-11-12, weak 1.0-cost cells) — the "superseded by default-on variant fold" state is now real, keep it; do not flip `strip_diacritics_for_reading_match` (still false). Consider a `suspension_gate`-style unverified_ratio budget review — **no change to `maximum_coverage: 0.9` or `max_unverified_ratio: 0.05` without explicit sign-off** (out of this report's authority). The `per_book` block is now the load-bearing config surface — audit edits to it as pipeline changes, not as comments.
- Keep `expected_syllables_per_nom_char: 1.0` — measured vi/nom syllable ratio is 0.93 (mean, pre-repair) with 92% of Tap1 rows and 91% of Tap3 rows inside [0.6, 1.6]; 1.0 remains the right prior for dịch âm T1.
- If/when the instructor wants the books re-yielded: treat Tap1/Tap3 as **diễn nghĩa-influenced dịch âm** (Vietnamese side is a fluent translation with reordering — noticeable in samples above, e.g. ` năm giám mục … → "Vì bấy lâu nay địa phận này không có sách cấm phòng …"`), which is exactly the case the guideline allows n-m groups for — do not force 1-1.

**Literature pointers** (for design hygiene, not required by the fix): Vecalign (Thompson & Koehn, EMNLP-IJCNLP 2019) — pseudo-alignment with dynamic-programming approximation of sentence embeddings; note its known failure on cross-order/low-scoring pairs; Bertalign (Liu & Zhu, DSH 2023) — retrieve-top-k then DP over 1-1 paths, recovering 1-n/n-m under restructured translation — structurally similar to this repo's DP + group penalties; Liu, Lv, Yang, Qu "Ancient-Modern Chinese translation" (ACM TALLIP) and Dinh, Nguyen, Nguyen (IJACSA 12(2), 2021) "Transliterating Nôm Scripts into Vietnamese" are the in-guideline exemplars.

---

## 11. Reproduction commands

Scratch directories used during verification: `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E` (initial); `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-E` (this revision — probe.py: CSV/BOM/cols/row counts, null/error-element census, sentence_id max suffix, monotone check; probe2.py: per-book null/empty/err census + skip_qn row + Tap1 non-monotone window; probe3.py: sidecar flag histograms, sem/conf aggregates; probe4.py: the Tap1 UNMATCHED_QN sidecar record; probe5.py: sidecar sha256 1203/1203; probe6.py: re-measured policy simulation + semantic-confidence thresholds).

```powershell
# tests (must pass)             - cache artifacts excluded, nothing written to repo
cd "C:\Users\MSI VN\Desktop\NLP"; python -m pytest -q
# 2026-11-12 collection re-run: 282 items collected (test_charstream.py: 2, test_map_repair.py: 3); all pass per change-set record.

# --- stage-6 empirical probes (read-only on data/; outputs stay in scratch) ---
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_csv.py"          # row counts, nulls, sidecar, flags (pre-repair artifacts)
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_sem.py"         # semantic_confidence distributions
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_policy.py"      # flag set overlap + policy sums (all rows)
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_policy2.py"     # policy simulation with _classify_row semantics
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_tok.py"         # CSV vi-token totals vs stream totals
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_drop.py"        # qn_sentence_spans counts vs CSV row counts
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_coverage.py"    # whole-sentence coverage of shipped rows
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_anchor_window.py" # window sensitivity of cuts → drops
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_drop2.py"      # which sentences drop, by token size
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_ratio.py"      # vi/nom syllable ratio distribution
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_conf.py"       # structurally low-conf rows cross-tabs
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_pages.py"      # img_id order & cleaning-page coverage
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_sha.py"        # sidecar sha integrity (1068/1068 OK, pre-repair)
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_nullcheck.py"  # null ⇔ NON_ONE_TO_ONE consistency
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_verified.py"   # reconstruct verified rows, match metrics
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_den.py"        # denominators 182/368 reproduce (pre-repair)
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_pair.py"        # pair-level anchor bar = 0/50 tap3
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_pair_flat.py"   # flat-unique pair bars = 0/50
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_diffs.py"      # auto_text_diff sample output
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_upper_re.py"    # SENTENCE_UPPER_RE block counts
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_bugimpact.py"   # stops split-by-bug counts on real text
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_span.py"        # SPANS_PAGES × UNANCHORED overlap (flags now retired)
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_flags.py"        # ANCHORED+UNANCHORED union counts (retired)
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_clean.py"       # cleaned page json layout
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_lowconf.py"     # low-conf x group-type cross-tab
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_imagemap.py"     # image_map statuses
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-E\probe_tap2.py"        # Tap2 stream_cosegment smoke test
# --- 2026-11-12 re-measurements (post map-repair) ---
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-E\probe.py"
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-E\probe2.py"
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-E\probe3.py"
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-E\probe4.py"
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-E\probe5.py"
python -X utf8 "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-E\probe6.py"
```

Key repo references (line anchors, current tree, post-repair) (revised 2026-11-12):

```
src/hannom/cosegment.py   32-33 (SENTENCE_STOP/UPPER), 36-55 (qn_sentence_spans),
                           167-229 (cuts), 217-226 (monotone clamp), 232-374 (stream_cosegment),
                           297-321 (page attribution), 326-336 (THE DROP), 333-334,
                           337-344 (anchored flags), 369-374 (reindex)   [UNCHANGED]
src/hannom/charstream.py  1-19 (docstring: live segmenter), 99-218 (stream_segments_by_charalign:
                           global banded NW via align_streams, band=400, page-start anchors,
                           two-pass lexicon learn), 145 (qn_sentence_spans), 254-290 (QN-cut
                           projection; empty-Nôm → UNMATCHED_QN + nom empty segment;
                           QN_SENTENCE_NO_NOM:<sidx> warning at :277), 254-260 (empty-Nôm
                           row takes ch_image = vi_image)     [NEW 2026-11-12]
src/hannom/align.py       31-34 (regexes; 69-73 unmatched comment), 58-105 (AlignConfig;
                           per_book + strip_texts fields at 79-81; _as_config at 84-105),
                           108-123 (_split_long_text), 126-166 (split_nom_page/split_qn_page/join),
                           167-180 (_may_join_across_pages / _stream_segments), 226-302
                           (build_segments), 303-336 (_reading_matches / semantic_evidence),
                           354-384 (_group_cost), 387-455 (align_segments, DP bypass intact),
                           458-559 (_emit_rows NEW; auto_text_diff at :528; null diff +
                           TEXT_DIFF_NULL_NON_ONE_TO_ONE at :543-545; UNMATCHED_* flags at
                           :509-512; per-img counter at :480-483),
                           562-625 (align_book; charalign branch ~575-611: forced 1-1 groups,
                           CHARALIGN_SEGMENTS_FAILED loud fallback, NO_SEGMENTS_FOR_ALIGNMENT),
                           627-628 (CSV_COLUMNS), 668-694 (write_alignment_csv; utf-8-sig at :680),
                           697-713 (read_alignment_csv)
configs/alignment.yaml    segmentation default + per_book (Tap1/Tap3 → charalign;
                           Tap3 + strip_texts 所𥚇卷; Tap2 → cosegment), text_diff variant_fold: true
src/hannom/evaluate.py    69-85 (UNVERIFIED_FLAGS — UNCHANGED; COSEGMENTED_UNANCHORED still listed),
                           105-161 (_classify_row), 151-152 (UNMATCHED_* → unmatched),
                           209-320 (metrics assembly; UNVERIFIED_DIFFERENT_ROWS counts verified_match
                           ch≠vi rows with elements == [])
src/hannom/orchestrator   571 lines; 169 (labels misc bin — only 2026-11-12 change),
                           310-358 (recompute_text_diff), 327-338 (force-recompute null keep),
                           349 (allow_flat_match=True), 389-449 (stage_align)
src/hannom/anchors.py     34 (MAX_ANCHOR_GAP_TOKENS=120, dead), 138-181 (find_reading_anchors)  [UNCHANGED]
src/hannom/charalign.py   27 (variant_fold imported BY textdiff — live), 104-… (clean_nom_pages),
                           matcher/NW primitives shared WITH live pipeline; CLI driver = explicit
                           offline diagnostic only (cli.py:172)     [UNCHANGED file]
src/hannom/textdiff.py    323-324 (allow_flat_match=False / allow_variant_fold=True defaults), 416-424
src/hannom/t1_map.py      110-111 (verified_min_coverage=0.5, verified_min_anchors=2)
docs/decisions.md         2026-11-12 entries (map-repair line 18; parens discovery line 19;
                           aparat/bin split line 20; charalign segmenter shipped line 21; labels line 22;
                           gate status unchanged line 23) — the change-set's own audit trail
Quy_định_đồ_án_v2.1.extracted.txt  (not committed? it IS untracked-but-present; read-only copy-paste above)
```

---

## 12. Handoff checklist (for the next agent)

- [ ] Reproduce C1 on a *throwaway pair* first (never write into `data/`): build a tiny `PageUnit` pair in scratch, call `stream_cosegment`, assert no zero-width chunk and no silent drop. (Cosegment path only — the dịch-âm books no longer exercise it.)
- [ ] Confirm at `stage_align` level: `emitted_qn_tokens + dropped_qn_tokens == stream_qn_tokens` and `len(nom_segments) == len(qn_segments)`; assert `UNMATCHED_*` rows counted in `summary.json`.
- [ ] Decide and document (explicit sign-off) whether `UNVERIFIED_FLAGS` loses `COSEGMENTED_UNANCHORED` — this is now a hygiene edit, not a metric change (0 carriers on live rows); keep a test proving the no-op and that no row becomes `verified` without reading evidence or a human decision.
- [ ] Run `restore_quarantine()` only after human review of quarantine entries; iterate; re-run `stage_align`; track `learned_pairs` > 0 in `summary.json`.
- [ ] **Re-run T1_CamPhong_Tap2 align** after OCR/cleaned pages complete; confirm sidecar written; confirm `summary.json.flags` includes `COSEGMENTED*`; demote old `metrics.json`. (Now the only stale book; siblings re-aligned 2026-11-12.)
- [ ] Track the re-aligned Tap1/Tap3 CSVs forward: row counts 823/380; watch `QN_SENTENCE_NO_NOM` (Tap1 sidx 529); verify `COSEGMENTED_STREAM_ALIGNED` persists 100%; attach `sentence_coverage` to the report.
- [ ] **Clean up `data/align/T1_SuaLoiQuyen/_pre-repair-2026-11-12/`** — ~1,421 nested `_pre-repair-2026-11-12` directories (path-length errors on recursion); Tap1's archive is clean (3 files). Decide with the owner before deleting anything; nothing in this task deletes it.
- [ ] Resolve the one Tap1 `UNMATCHED_QN` row (`…100.1`, `img_id .100.jpg`, vi_txt "Con suy tàn …"): human review or a Nôm source for the sentence — it is the only whole-sentence gap in the re-aligned corpus.
- [ ] Make `anchor_window` sentence-relative; delete dead `MAX_ANCHOR_GAP_TOKENS` or honor it; test monotone/non-zero emission on a pathological mini-book (tiny 1–2 token sentences). (Cosegment path.)
- [ ] If any of the above changes `data/align/*`, re-run unit tests and the packaging validator; do **not** commit `data/` artifacts unless that's the team's explicit workflow (current repo state shows data is committed on purpose — verify before writing).
- [ ] Update `output/`-side reports to state explicitly that Tap1/Tap3 verified coverage (**0.463 / 0.600**) fails the 0.9/0.05/0.05 policy and why (this file §4-6, §10); cite decisions.md 2026-11-12 (gate status unchanged) as the standing position.
- [ ] Double-check the 5-column schema is still intact after emitting `UNMATCHED_QN` rows (CSV unchanged; no new columns) — 823/380/8 all pass.
- [ ] Confirm no `[MASK]` creep: any co-segment that lets `[MASK]` into an anchor or a diff span is a regression — add a validator check.
- [ ] Note the Tap1 CSV monotone anomaly (skip_qn row) in the report; confirm downstream consumers tolerate a non-monotone `img_id` sequence for that one row.

---

## 13. Caveats & notes

1. **Dictionaries not fully loaded.** All in-scratch anchor/evidence measurements (except the already-stored `semantic_confidence` values) used the prebuilt 12-source union map `data/dictionary/char_readings.json` (26,700 chars) behind a ~4-line stub of `DictionaryIndex` (readings for `char` kind only). The real `DictionaryIndex` loads `dictionaries-04-11-2026/entries/*.jsonl` (~3.1 GB, 12 adapters) plus Unihan/CC-CEDICT; reading sets are ≈ identical for the sources probed (spot-checked hvdic for 道/德/主/民/鬼/生/天/𡥵 — same or superset coverage). **The 2026-11-12 re-alignment ran through the real pipeline and real dictionary** (that is why evidence flipped); re-verify any absolute drop/coverage numbers you re-derive in scratch before quoting them against the shipped artifacts.
2. **The exact shipped configuration cannot be reconstructed bit-exactly.** Tap1/Tap3 artifacts were regenerated on 2026-11-12 (19:43/19:03) with the charstream segmenter, `per_book` config, real dictionary and the change-set's `textdiff` variant fold; the global-stream alignment × dictionary-specific matches cannot be cloned in scratch without the 3.1 GB load. All §3–§4 replication numbers marked *pre-repair* are exactly that — system-level evidence against the pre-repair CSVs. The token-gap tables are dictionary-independent (counting CSV vs cleaned streams).
3. **Policy simulations are exact only under public semantics.** `evaluate._classify_row` was re-implemented from source (reviewed line-by-line); this revision re-ran the simulation on the re-aligned CSVs+sidecars (no review decisions present) and the baseline reproduces stored `metrics.json` **exactly** on both books — so the drop-ALIGN_EVIDENCE_INSUFFICIENT deltas (460/260; unverified ratios 0.44/0.32) are sound estimates of the *flag-class* effect; they are not predictions of accuracy, nor endorsement of auto-verifying those rows. The pre-repair deltas (460/203 etc.) are archived in §9's provenance note.
4. **"Vietnamese uppercase" bug (M1) impact is negligible today** (2/621 stops in Tap3, 0/970 in Tap1) — treat it as a spec-compliance defect to fix opportunistically, not an emergency. **2026-11-12 (revised): the same splitter now feeds the live charstream cuts of both dịch-âm books, so "negligible" only bounds the stops it changes at the margin; the structural risks remain (i) no abbreviation guard — `Tp.`/`Mr.`/`St.`/`No.` will hard-split sentences at live row boundaries — and (ii) stream vs fallback splitters disagreeing on `;`/`:`.**
5. **`UNMATCHED_NOM` / `UNMATCHED_QN` post-repair**: Tap1 `UNMATCHED_QN=1` (the charstream empty-Nôm row; warning `QN_SENTENCE_NO_NOM:529`; img_id `.100.jpg`; sidecar flags include `ALIGN_EVIDENCE_INSUFFICIENT`), `UNMATCHED_NOM=0`. Tap3 **both 0**. Tap2 0/0 (stale artifacts). The pre-repair claim "`UNMATCHED_QN = 0` anywhere is not explained by DP fiat alone" referred to the cosegment path; the live path makes unmatched QN sentences structurally impossible to hide — they surface as `UNMATCHED_QN` rows + `QN_SENTENCE_NO_NOM` warnings. The cosegment path still hides them (C1, unfixed).
6. **`Tap3 ships without a sidecar?`** — false: Tap3 has sidecar (`T1_Sửa Lưỡi Quyển.review_metadata.jsonl`, sha **380/380 OK** re-verified 2026-11-12; Tap1 823/823 — total 1203/1203). **Tap2 lacks sidecar** and its 8 rows will flip to `REVIEW_METADATA_MISSING` on reload — blocking fail-closed as designed (state that in the Tap2 rerun task).
7. **Guideline says texts differ in orthography so `ch != vi` always;** the `UNVERIFIED_DIFFERENT_ROWS` warnings (Tap1: **136**, Tap3: **125** — equal to the verified_match counts) are therefore uninformative — all rows differ. Treat that warning as a future-proofing hook, not evidence of a scoring leak.
8. **Row counts** (re-measured 2026-11-12): **823 / 380 / 8** rows; `SPANS_PAGES` **126 / 42 / 5**; SPANS_PAGES∩UNANCHORED overlap no longer measurable (flag retired). Line up with cleaning coverage and the post-repair image_map (Tap1 127 / Tap3 50 pairs, all `candidate`/`content_dp`; Tap1 143–144 excluded; Tap1 front matter 013–020 re-binned `vi/`; glossary/reprint pages of both books → `misc/`). The one non-monotone CSV span (Tap1 skip_qn row) is documented in §8.
9. **Numbers from `metrics.json` are trusted only where reproduced; the re-aligned metrics were cross-checked for internal consistency this revision** (row arithmetic, sidecar-flag histograms, structural_confidence_mean, evidence_insufficient_rows, similarity inputs) — all consistent. Pre-repair metrics reproduce only the pre-repair CSVs (archived: `metrics.20261112T120924Z.json` Tap1, `metrics.20261112T120355Z.json` Tap3). Tap2 metrics are stale (§6); ignore them for the thesis/report.
10. **The 2026-11-12 change-set is uncommitted** (read-only audit + revision on `src/`, `configs/`, `data/` except for pytest's `.pytest_cache`, which pre-existed): **9 modified tracked files + 5 new source files** (`src/hannom/charstream.py`, `src/hannom/map_repair.py`, `tests/test_charstream.py`, `tests/test_map_repair.py`, `tools/repair_image_map.py`) **+ untracked `Doc/*.md` (this file included) and `submission/`**. The only file this report adds is `Doc/verify-E-cosegment-align.md` (this one).
11. **Git status at revision time**: branch `feat/map-repair-align` (current), HEAD `c3439e7` (repair-branch tip; contained in `origin/repair/pipeline-audit-2026-11-09`); **ZERO new commits** — everything above is working-tree state. The pre-repair revision's "5 untracked files / no tracked modifications" claim is obsolete (now 9 modified + 5 new sources, uncommitted).
12. **`python -m pytest -q`** passes in full at the time of the audit (**282 collected**; `tests/test_charstream.py` (2) and `tests/test_map_repair.py` (3) are new) with repo state as-is. (Was: 288.)
13. Tap1/Tap3 are, on sample inspection, **diễn nghĩa with dịch âm alignment** (see row `Year覧…→ "Vì bấy lâu nay địa phận này …"` and Tap3's nearly 1-1 syllable rows). Confidence in 1-1 discipline for these books is a judgment the instructor must make; nothing in this audit endorses silently forcing 1-1 group alignment either — the re-aligned rows ARE all forced 1-1 by `align_book` for the charstream books (index i ↔ index i), with non-1-1 expressed only via the one `skip_qn` row; the DP flags, the n-m caps, and `text_diff=null` on non-1-1 remain functioning for the cosegment path in that respect. The forced-1-1 design is exactly what the guideline's n-m allowance is for restructured translation — flag for the instructor, do not silently "fix" either way.
14. File `Quy_định_đồ_án_v2.1.extracted.txt` was extracted from the course PDF and used only for the guideline cross-check. It was **not** committed in this task. The v2.1 text cited in §1 is the governing spec for the CSV layer only.
15. **`charalign.py` vs `hannom.charstream` — the diagnostic-only framing, corrected (revised 2026-11-12).** Pre-repair this note said: *"`charalign.py` (diagnostic twin, used for reference only) aligns at character level and projects sentences through a banded NW … architecturally analogous to `cosegment.py`'s sentence cuts; its `sentence_spans` treats `.?!;:` + space as terminators, confirming the *intent* of the stream splitter; the divergence with `QN_SENTENCE_SPLIT_RE` is an artifact of `split_qn_page`, to be reconciled under M1/M7."* Two things are true now, and they are not the same thing: (a) **`charalign.py` is no longer purely diagnostic even in import terms** — its primitives feed the live path: `textdiff.py:27` imports `fold` from it as `variant_fold` (the default-on weak fold at **both** align-time and recompute-time), `charstream.py` imports `Matcher`/`Op`/`QnToken`/`NomChar`/`align_streams`/`fold` (and lazily `learn_lexicon`, `charstream.py:27,211`), and `map_repair.py:25` imports `fold`. What remains genuinely diagnostic-only is its **CLI driver** (`cli.py:172` — an explicit offline command; `clean_nom_pages`, the diagnostic outputs): the Stage-6 pipeline never invokes it, and no evaluation artifact derives from it. (b) **`hannom.charstream` is NOT diagnostic** — it is the **live segmenter** for both dịch-âm books (`per_book: charalign`), activated 2026-11-12; it reuses charalign's banded NW (`align_streams`, `band=400`) and page-start anchors, learns a two-pass lexicon in-run (`learn_lexicon(..., min_unknown=2)`), projects the QN sentence cuts (`qn_sentence_spans`) onto the Nôm stream through the alignment, stamps `COSEGMENTED_STREAM_ALIGNED` on every segment, emits one segment per QN sentence, and yields `UNMATCHED_QN` for empty-Nôm sentences (1 in Tap1, 0 in Tap3). The pre-repair caveats about "charalign does not feed evaluation" applied to the *module's outputs*; the live *mechanism* changed. `QN_SENTENCE_NO_NOM` is the audible signal for a QN sentence with no Nôm content under charstream — Tap1 carries exactly one (sidx 529). Evaluation consumes the CSV, so the charalign CLI's own diagnostic numbers never needed to appear in `data/evaluation/` — they were never the live path. **Both books re-aligned 2026-11-12 through this path; Tap2 keeps cosegment explicitly; the gate still FAILS (coverage 0.46/0.60, unverified ratio 0.54/0.40, similarity 89.96/93.74 < 95.0), and the failure now reflects machine evidence on re-cut rows, not stale artifacts.** Audit trail for this change: `docs/decisions.md` 2026-11-12 entries — map-repair (line 18), parens discovery (19), aparat/bin split (20), **charalign segmenter shipped (line 21)** — Tap3 similarity 85.87 → 93.74 (+7.87), Tap1 87.36 → 89.96 (+2.60), null ratios 0.287 → 0.000 / 0.171 → 0.000; note that under the shipped code the DP does not run at all for these books (bypassed in `align_book`), so read the entry's "the DP still runs on strata that did not segment cleanly" clause as pre-ship expectation rather than runtime behavior, and read the gate-status entry (line 23) for the standing policy position: both books still FAIL coverage and unverified-ratio gates; Tap2 essentially un-OCR'd; "the 0.7% gap to 95% on Tap1 and 1.3% on Tap3 will only close with review decisions, not with more code."

---

## Revision log (2026-11-12)

- Added the post-map-repair banner; revised status/date lines; added `hannom.charstream` (live segmenter) to scope; recorded git state (branch `feat/map-repair-align`, HEAD `c3439e7`, zero new commits, 9 modified + 5 new sources, uncommitted change-set).
- §1: three-books table → 823 rows/1 null (Tap1), 380 rows/0 nulls (Tap3); Tap2 unchanged 8/8/100% null; segmenter column; scope table split into cosegment (Tap2-only live) vs charstream (dịch-âm live); `align_book` charalign branch documented; cites re-anchored (align_segments 387-455, `_emit_rows` 458-559 NEW, auto_text_diff at :528, `_group_cost` 354-384, `_reading_matches` 303, `semantic_evidence` 337, AlignConfig 58-105, `_split_long_text` 108, `split_nom_page` 126, `split_qn_page` 150, `build_segments` 226; `CSV_COLUMNS` 627, `write_alignment_csv` 668, utf-8-sig 680, `read_alignment_csv` 697 — verified in current file).
- §2: pytest 288 → **282** (re-collected); pre-repair restart notes on scratch (`verify-revise-E`), metrics reproduction claim rewritten (EXCESSIVE_NULL_ROWS gone; new cross-checks documented; pre-repair archives cited).
- §3 C1: re-labeled SUPERSEDED-LIVE-PATH for Tap1/Tap3 (dormant, unfixed in `cosegment.py`, live for Tap2); dropped-sentence census marked pre-repair; **UNMATCHED_QN=0 claim corrected** (Tap1 1 — charstream, not cosegment; Tap3 0); Tap3 runaway archive `_pre-repair-2026-11-12/` (~1,421 nested dirs) flagged for cleanup (Tap1 clean).
- §4 H1: §4.2 incidence table re-measured (ALIGN_EVIDENCE_INSUFFICIENT 692/283 → **233/74**; UNANCHORED/ANCHORED **retired**; ALIGNED 602/243 → **822/380**; NON_ONE_TO_ONE 125/98 → **1/0**; ALIGN_LOW_CONF 27/27 → **39/4**; SPANS_PAGES 185/74 → **126/42**; +DIFF_* census 650/172/362 · 224/156/120; COSEGMENTED_STREAM_ALIGNED 823/380 new). §4.3 evidence distribution re-measured (medians 0.6176/0.7083; <0.5: 233/74; ≥0.5: 590/306; full histogram added). §4.4/§9 policy simulation re-measured on re-aligned artifacts (baseline reproduces stored metrics exactly; UNANCHORED drop = no-op; drop-both 460/260; drop-3 822/380). §4.5: UNANCHORED removal now a hygiene no-op.
- §5 H2: DP bypassed for charstream books noted; cites re-anchored; ALIGN_LOW_CONF 27 → 39/4; variant-fold default-on at both callsites documented (flat match OFF align-time / ON recompute-time).
- §6 H3: siblings re-aligned 2026-11-12; Tap2 remains untouched (mtime 2026-11-08 20:02; metrics.json 2026-11-08 EMPTY_DENOMINATOR) — kept all claims; escalated to deadline risk; `per_book: cosegment` unchanged.
- §7 M1: consequence 1 escalated — `qn_sentence_spans` is now the **live** splitter for both dịch-âm books (via charstream); impact table marked pre-repair (function unchanged).
- §8 verified-good list: all items re-measured or labeled pre-repair; sidecar sha **1203/1203 ✓**; CSV format ✓ (5 cols, BOM); sentence_id max suffix **15/16**; **Tap1 CSV not monotone at the skip_qn row (`…100.1`, between two `.189.jpg` rows)**; tap3 monotone ✓; image_map candidate-only (Tap1 content_dp/70 markers, Tap3 content_dp/33; Tap1 127 pairs, front matter 013–020 re-binned, glossary/publisher pages → misc/); Tap3 gate still FAIL (three issues, EXCESSIVE_NULL_ROWS absent); cosegment dormant-but-intact; charalign.py CLI driver offline-diagnostic but its primitives load-bearing; `charstream.py` LIVE — corrected.
- §9: policy table replaced with re-measured one (baseline reproduces stored metrics; UNANCHORED no-op rows; dual-inflation/UNANCHORED-overlap rows retired).
- §10 recommendations: [C1] expected-gain correction (341→380 by charstream, not the emission-loop fix — not implemented); [H1-3] UNANCHORED removal now hygiene no-op; [H1-4/5] lexicon + variant fold updates (381/228 machine-verified rows without restoration; drop-evidence coverage 0.56/0.68 ≪ 0.9); [H1-5(b)] superseded by default-on variant fold; [H3] deadline-risk note; [M1] live-path escalation; [M5/L6] whole-sentence UNMATCHED_QN now present (Tap1 `…100.1`; `QN_SENTENCE_NO_NOM:529`); [config hints] superseded by default-on variant fold; per_book now the load-bearing surface.
- §12 handoff: coverage figures updated (0.011/0.076 → **0.463/0.600**); siblings re-aligned; `_pre-repair-2026-11-12` cleanup item added; Tap1 skip_qn row review item added; Tap2 escalation kept.
- §13 caveats: items 2 (shipped-config), 4 (M1), 5 (UNMATCHED_*), 7 (warning 136/125), 8 (row counts/image_map), 9 (metrics trust), 10-12 (git state; tests 282), 13 (forced 1-1 by align_book noted), 15 (**charalign.py — CLI driver still offline-diagnostic, but its primitives are now load-bearing (`variant_fold` in textdiff, charstream's Matcher/NW, `fold` in map_repair); hannom.charstream is the LIVE segmenter — misplaced legacy caveat rewritten; decisions.md audit trail cited, lines 18–23**) all revised.
- Citations decisions.md 2026-11-12 (map-repair; parens; aparat/bin split; charalign segmenter shipped; gate status unchanged) incorporated as the change-set's audit trail.
- Not revised / out of scope: `map_repair.py` unaudited; Tap2 unmodified (as instructed); no source, config, or data files edited; no pipeline re-run; no API calls; `.env`/`hannom_API.md` untouched.
