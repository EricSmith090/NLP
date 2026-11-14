# USER_GUIDE — Hán Nôm–Quốc ngữ Parallel Corpus Pipeline

End-to-end run on a fresh machine, per `Quy_định_đồ_án_v2.1` and `Mô tả dữ liệu từ điển Hán Nôm và Quốc ngữ v1`.

## 1. Environment

- **Python** 3.11+ (verified 3.13.9, Windows 11; Ubuntu is preferred per guideline source requirements).
- **RAM** 16 GB, **GPU** NVIDIA RTX 4060 8 GB VRAM for Vintern-1B-v2 (QN primary). CPU-only hosts still run extraction/classification/labels/clean/align, but Vintern reports unavailable without CUDA.
- Set UTF-8 console before running commands that print Vietnamese filenames:

```powershell
$env:PYTHONIOENCODING='utf-8'
```

## 2. Install

Core pipeline (pinned in `pyproject.toml`):

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

OCR extras (pinned in `pyproject.toml` `[project.optional-dependencies] ocr`):

```powershell
python -m pip install -e ".[ocr]"
# torch/torchvision with CUDA are not on PyPI for Windows; install from the cu126 index:
python -m pip install torch==2.14.1+cu126 torchvision==0.29.1+cu126 --index-url https://download.pytorch.org/whl/cu126
```

Notes:
- `transformers` **must** stay at 4.46.3 (5.x is incompatible with Vintern custom code).
- `paddlex` prefers PyYAML 6.0.2; this project pins 6.0.3 (patch-level, tests pass).
- A no-op `flash_attn` shim exists site-wide because the stock Vintern config sets `use_flash_attn=false`.
- `requests==2.32.5` is a core dependency (required by the Kim Hán Nôm client) — it is pinned in `pyproject.toml`, not assumed transitive.

## 3. Secrets and external services

- Copy `.env.example` to `.env` and set `KIMHANNOM_TOKEN=<token>`. The token is read from `KIMHANNOM_TOKEN` env var (`.env` is supported) and is **never** committed or packaged.
- **Only approved external service:** Kim Hán Nôm API (`https://kimhannom.fit.hcmus.edu.vn`), documented limits 25/min, 50/h, 200/day, 600/week. The client is single-threaded, caches by image SHA-256, backs off exponentially, and records a quota ledger. Multiple accounts must not be used to bypass quota.
- No confidential PDF/page image may be sent to any other cloud OCR/GPU/Hugging Face. Local Vintern weights (`5CD-AI/Vintern-1B-v2`) download from Hugging Face on first load and stay local thereafter. Paid tools: none. Prompts: Vintern prompt is fixed in `src/hannom/ocr/local_vintern.py` (“Trích xuất toàn bộ văn bản tiếng Việt…”).

## 4. Data layout

| Path | Contents |
|---|---|
| `CV20-24127189/*.pdf` | 3 assigned T1 books, 950 image-only pages (confidential, gitignored) |
| `dictionaries-04-11-2026/entries/*.jsonl` | Official Entry/v1 dictionary drop (12 sources; see `configs/dictionary.yaml`) |
| `data/` | Working artifacts (gitignored) |
| `artifacts/` | Reports/screenshots (gitignored) |
| `configs/books/*.yaml` | Per-book scope, page hints, OCR routing |

`configs/dictionary.yaml` points at `dictionaries-04-11-2026/entries`. If the folder is absent the pipeline still runs; `JsonlDictionary.available()` is false and dictionary misses only route to review (never auto-red).

## 5. Run the pipeline

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m hannom.cli intake
python -m hannom.cli extract
python -m hannom.cli classify
python -m hannom.cli map
python -m hannom.cli ocr          # Nôm: Kim API first, local fallback on quota (local_fallback/ files); QN: Vintern
python -m hannom.cli labels
python -m hannom.cli clean
python -m hannom.cli align
python -m hannom.cli textdiff
python -m hannom.cli evaluate
python -m hannom.cli review --book T1_SuaLoiQuyen
python -m hannom.cli package-all
python tools/validate_submission.py data/output
```

Per-book variants:

```powershell
python -m hannom.cli ocr --book T1_SuaLoiQuyen --limit 3
python -m hannom.cli extract --book T1_CamPhong_Tap2 --force
python -m hannom.cli pilot --book T1_SuaLoiQuyen
python -m hannom.cli status
python -m hannom.cli source-zip
python -m hannom.cli split
python tools/build_updated_pdf.py --all
```

`hannom ocr` prints per-page progress (`[book] OCR i/N`) and caches results in `data/ocr/<book>/<page>.json`; reruns resume unless `--force`. `pilot` stops with `status=blocked_ocr` if no engine is available rather than fabricating later stages.

**OCR honesty notes (Verify-C fixes, 2026-11-13):**

- The quota ledger records the server's **business code** per call (`api_calls.business_code`, e.g. `000000` / `000108`) — failed attempts still count toward the windows, deliberately (conservative). Every call, including HTTP-200 business failures, is now distinguishable offline.
- `_success_code` is strict: only the string `"000000"` passes. `0`, `False`, `"0"`, `null` are failures.
- Cache-hit results **re-promote** warnings into `pages.review_flags` automatically (`ENGINE_UNAVAILABLE` carries a reason: `no_token` / `import_error` / `quota`; also `IMAGE_REC_FALLBACK`, `API_CLASSIFIED_NOT_SINO_NOM`, `OCR_ROUTING_UNKNOWN_MODE`, `OCR_LINE_WITHOUT_BBOX`).
- **After any re-bin** (`BIN_OVERRIDE_*`, `inventory_*` changes), label bins are stale — re-run `python -m hannom.cli labels [--book <id>]`. Nothing else tracks this dependency.
- `image-rec` is used only as the documented cropped-line recovery; a full-page re-run path stays reachable but is flagged; image-ocr payloads no longer persist `result_image_base64` going forward (existing `data/ocr/api_cache/` payloads keep it — ~92 MB of base64 page images; delete it only if you understand what it is).
- `--no-classify` skips `structure-classification` losslessly for this fixed-layout corpus (183/183 evidence) and saves 264 calls on Tap2 (`python -m hannom.cli ocr --only nom --no-classify --wait-quota`, effective from the W47 rollover 2026-11-16).
- `difficult` is dead weight (always `false`); `ensemble` config was removed. Vintern is pinned to a fixed model revision (`c3f01cf…c8bc`) with a per-call wall-clock watchdog (`max_time_seconds=300`).


## 6. Review

- `python -m hannom.cli review --book <id>` launches the local Streamlit app (port 8501). Only flagged rows leave automation: `DICT_MISS`, `DIFF_SEMANTIC`, `OCR_ENGINE_DISAGREE`, `ALIGN_LOW_CONF`, etc. (see `docs/review_guide.md`).
- Human patches are stored as JSONL and reapplied on rerun; rerunning never overwrites reviewed pages.
- Two mandatory human steps are not error correction:
  1. Fill `configs/report.yaml` with all four members' names/IDs/emails.
  2. Merge `<Book>_updated.pdf` for books with rotated pages into the submission and notify the handout person; capture the four mandatory report screenshots.

## 7. Dictionary adapter notes (Entry/v1)

- `src/hannom/dictionary/jsonl.py` indexes both `kind: char` (single code point, Han/Nôm) and `kind: word` (multi-char), plus `forms` spellings (QN heads → Nôm spellings, e.g. dnqatv).
- Only reading systems `qn/hv/nom` count as Quốc ngữ evidence. `pinyin/jyutping/on/kun/hangul` are kept as gloss, never matched against QN syllables (Entry/v1 “Không suy đoán”). Missing system is treated as `qn`.
- Validation counts (`duplicate_ids`, `invalid_freq`, `invalid_enum`, `skipped_unencoded`) are tracked per adapter; `unencoded:true` IDS/`@img` entries are skipped, not turned into invented senses.
- Structural-only sources (`cjkvi_ids`, `cjkvi_variants`) do not count as phonetic evidence: `LookupResult.found` requires a reading or definition.
- Diacritic matching is exact-first by default (`strip_diacritics_for_reading_match: false`). Stripped matching would merge distinct readings and is opt-in only.

## 8. Packaging and validation

- `package-all` builds one ZIP with three sibling book folders + report PDF + `source.zip` (guideline extension; `hannom split` makes one ZIP per book if required).
- `validate_book_package` checks: images exist and are `.jpg`, `Label.txt`/`fileState.txt` present for `ch`/`vi`, all `fileState` = 1, 4 points per box, CSV parses, `text_diff` positions valid (0-based half-open Unicode code points on NFC, `[MASK]`=6 chars excluded, span endpoints are letters, no overlapping spans), XLSX colours match CSV, per-book similarity ≥95%.
- `EMPTY_LABELS` is a blocking issue by default: any image row with zero boxes in `ch/`/`vi/` `Label.txt` refuses packaging. Ship an explicitly-incomplete book only with `--allow-empty-labels` (off by default). Re-run OCR + `hannom labels` first; empty boxes are never evidence of completion.
- Label box extra fields: `difficult` is the OCR tool's own field (auto-generated, kept unannotated). `confidence` is passed through from the Kim Hán Nôm API line payload; it is a transport value, **not** an annotation-quality signal, and must not be used to filter boxes. Transcription values come from each OCR engine (Nôm: Kim Hán Nôm API; QN: Vintern-1B-v2).
- The guideline allows one full-page box per page when the tool cannot annotate lines (our QN pages are exactly that: a whole-page rectangle). Such rows carry `confidence` from the API for Nôm runs only; QN full-page boxes carry no `confidence`.
- `<Book>_image_map.json` is **optional** per guideline v2.1; a missing map is a warning, an invalid map is a blocker. As of 2026-11-13 the assigned books build their maps deterministically from the printed cross-reference markers (see §8 note below), so a missing map should not happen for these books; re-run `hannom.cli map --book <id>` to rebuild.
- `missing/ch` images are duplicated into `ch/`; `missing/vi` images are kept only in `missing/vi` with no label files, and both appear as empty-side pairs in the image map.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `No OCR engine available / blocked_ocr` | Check `python -c "import torch; print(torch.cuda.is_available())"` (Vintern needs CUDA), `KIMHANNOM_TOKEN` in `.env`, `python -m pytest -q`. |
| `Refusing to call Kim Hán Nôm without --allow-api` (benchmark) | `tools/benchmark_ocr.py` now defaults to local engines; pass `--engine kimhannom --allow-api` explicitly for API. |
| `image-ocr` invalid boxes | `KimHanNomClient` now falls back to `image-rec` once and records `IMAGE_REC_FALLBACK`. |
| `QuotaExceeded` / slow OCR | 25/min, 50/h, 200/day, 600/week. In `api_mode: api_first` the pipeline switches to local models automatically once the quota is reached (results go to `data/ocr/<book>/local_fallback/`). Wait or resume later; cache prevents repeat calls. Every attempt (incl. business failures) records `business_code` — count all rows, not just `http_200`. |
| `Label.txt` stale / missing after re-bin | `python -m hannom.cli labels --book <id>` — label bins are one-shot and not rebuilt by classification/re-bin steps. Check `fileState.txt` lines are all `1` afterwards. |
| `ocr_confidence is NULL` in DB for OCR'd pages | The 2026-11-13 re-sync populated the 51 affected pages (50 SLQ + Tap1 p147); new cache hits promote flags/confidences automatically — re-run `hannom labels`/review queries after any migration. |
| Similarity FAIL | See `data/evaluation/<book>/metrics.json`. Many FAILs are `DIFF_UNVERIFIED` rows awaiting review — open the review app. |
| `SOURCE_MISSING USER_GUIDE.md` | `USER_GUIDE.md` is included in `source.zip` by `build_source_zip`; ensure the file exists in the repo root before packaging. |

## 10. Colab (if used)

Pin the same versions as `pyproject.toml`, use a GPU runtime (T4/A100), set `KIMHANNOM_TOKEN` as a Colab secret, and do not upload confidential PDFs. The pipeline’s state (`data/state.sqlite3`) and quota ledger are local to the session; download `source.zip` rather than the full `data/` directory.

## 11. Review metadata sidecar and verified evaluation (repair 2026-11-09)

- The alignment CSV keeps the five stable columns `img_id, sentence_id, ch_txt, vi_txt, text_diff`. Flags and confidence are persisted next to it in `<Name>.review_metadata.jsonl`, rewritten atomically by `hannom align`/`hannom textdiff` together with the CSV.
- If the sidecar is missing or inconsistent, rows are flagged `REVIEW_METADATA_MISSING` / `REVIEW_METADATA_MISMATCH` and are never treated as clean: the review app shows a warning banner and the flag-only queue includes them.
- Evaluation now separates accuracy from coverage (`hannom.evaluate.evaluate_rows`):
  - `verified_match` = compared with positive comparison evidence (identity, `MASK_ONLY_DIFFERENCE`, or `DIFF_NO_READING_MISMATCH` anchors);
  - `verified_difference` = rows with `text_diff` elements that pass validation;
  - `unverified` = rows without adequate evidence (`DIFF_UNVERIFIED_*`, `DIFF_AMBIGUOUS_READINGS`, `COSEGMENTED_UNANCHORED`, `ALIGN_EVIDENCE_INSUFFICIENT`, metadata failures; `UNMATCHED_*` rows are counted separately);
  - `unmatched` = `UNMATCHED_NOM` / `UNMATCHED_QN` rows (no trustworthy counterpart; never force-aligned); `unmatched` is only resolved by an explicit review decision;
  - `coverage_ratio` = (`verified_match_rows` + `verified_difference_rows`) / `total_rows`; `similarity` is computed over verified rows only. `metrics.json` also carries `spec_formula_similarity`, `spec_formula_red_chars`, `spec_formula_denominator`, `spec_formula_scored_rows` — the guideline "Đánh giá dữ liệu" formula over ALL rows with `text_diff ≠ null` (including unverified rows); the report PDF shows it as "Similarity (spec formula, all non-null rows)". Present both numbers; never quote `similarity` as the spec metric.
  - Since 2026-11-14 the variant fold is yaml-gated (`text_diff.variant_fold` in `configs/alignment.yaml`): rows anchoring ≥1 character through the fold carry the non-blocking flag `DIFF_VARIANT_FOLD_APPLIED` (counted per row in `summary.json`'s flag histogram, rewritten only by the align stage; a bare `hannom textdiff` re-run does not rewrite it). The flag also rides in the review-metadata sidecar flags; `DiffResult` exposes `matched_fold_readings` for unit tests.
- Two more confidence dimensions are now reported per book: `structural_confidence_mean` (grouping plausibility — never correspondence evidence) and `semantic_evidence_rows` / `evidence_insufficient_rows` (rows with/without reading anchors). `AlignmentRow.confidence` is structural; `AlignmentRow.semantic_confidence` is the unique-anchor coverage.
- Human review produces **durable decisions** in `data/review/<book_id>.review_decisions.jsonl` (append-only): `accepted_match`, `accepted_difference`, `alignment_reviewed`, `unresolved`, `unmatched`, `rejected`, `content_edited`. Each decision is hash-bound to the row content it reviewed; editing the row afterwards makes the decision stale. A no-change acceptance from the review app persists a decision exactly like a content-accepting one. `content_edited` never approves the alignment.
- The decision log is replayed in **file order** at every load: the state after the latest event determines the row's review status. A stale or invalid *latest* event blocks the row; superseded historical records stay in the log (append-only audit) and never create active blockers. Two valid decisions on the same content revision with mutually exclusive claims (`accepted_match` vs `accepted_difference`, or contradictory positional mappings) are a genuine `REVIEW_DECISION_CONFLICT` and block the row. Ordinary status transitions (e.g. `unresolved` → `accepted_match`) are legitimate and never conflict.
- **Fail-closed learning**: any decision-log integrity failure that affects the whole book disables dictionary learning for that run. Row-specific failures exclude only the affected row; valid, explicitly reviewed rows elsewhere still learn. Re-running learning is idempotent — identical reviewer provenance is not learned twice.
- Decision replay distinguishes **active** failures (latest event; blocking) from **historical audit diagnostics** (superseded records; preserved, never blocking). Log-wide failures block the whole book.
- **Revocation is enforced before alignment**: `stage_align` reconciles the lexicon against the *previous* CSV + current decision state before alignment consumes it. Automated evidence no longer authorized (superseded, stale, invalid, conflicted, revoked) is moved to the `revoked` section and never influences alignment again. Manual `human_restore` evidence and legacy quarantine are untouched. A timestamped backup is taken before the first *changed* save — note that "changed" now also covers evidence-weight (count) erosion, not only pair-set changes (verify-G M1): the reconcile summary exposes `counts_rewritten`, and a weight-only drift forces the backup+save path.
- The metadata sidecar persists **both** confidence dimensions (`confidence` structural grouping, `semantic_confidence` unique-anchor coverage), with the same `[0, 1]` finiteness validation; missing `semantic_confidence` in legacy sidecars loads as absent (never invented, never coerced to `0.0`).
- Metadata and decision-log integrity failures are gate-blocking, not warnings: `METADATA_*`, `REVIEW_DECISION_*`, and `DECISION_*` issues prevent `PASS` even if every row looks clean. Sidecar writes are atomic (temp file + fsync + `os.replace`); `schema` must be `1` and `confidence`/`semantic_confidence` must be finite real numbers in `[0, 1]`.
- Gate policy is configurable in `configs/project.yaml` `quality`: `minimum_coverage: 0.9`, `max_unverified_ratio: 0.05`, plus `null_ratio_warn: 0.05` now blocking under `EXCESSIVE_NULL_ROWS`. Below-gate rows prevent `package` from building and make the report show FAIL with explicit issues.
- Active lexicon learning requires an explicit, non-stale verifying review decision (accepted_match / accepted_difference / alignment_reviewed) recorded in data/review/<book_id>.review_decisions.jsonl with positional evidence: either an explicit character-to-token mapping recorded on the decision, or a single Nôm character paired with a single accepted QN token. Dictionary membership in the sentence never establishes positional correspondence. A content edit is not an approval of the alignment; only an explicit decision is. Legacy entries without provenance are quarantined, never silently trusted; restore them explicitly with BookLexicon.restore_quarantine() after human verification. Repeated or competing readings never become anchors or learning evidence.
- **Marker-verified maps (2026-11-13, the three assigned books):** every substantive QN page prints the Nôm printed page number in parentheses at the top (e.g. `- 58 - ( 65 )`; Nôm printed = Nôm PDF − 2; Tap1/Tap2/Tap3 carry `vi_to_nom_offset: 289|549|127` in `configs/books/*.yaml`). `hannom.cli map` builds the bijection Nôm PDF = offset − vi PDF directly from the print; pairs are `status=verified`, `source=printed_marker`, `mapping_source=printed_marker`, and `confidence=1.0`. `validate_image_map` enforces coverage, vi-ascending/ch-descending order, exact 4-point structure, and (when the book has `vi_to_nom_offset`) the marker formula, and `validate_book_package` runs the same validator against the packaged folders — an invalid map is a hard blocker. The heuristic mass-DP remains the fallback for books without markers; `image_map.manual.json` (when present) still overrides everything with `status=manual`.

## 12. Verify-G dictionary-subsystem fixes (2026-11-14)

- **Readings cache is now v2** (`CACHE_VERSION = 2` in `hannom.dictionary.readings`). The previously shipped v1 cache (built from the 2026-11-04 drop, catusf included) is preserved at `data/dictionary/char_readings.pre-rebuild-2026-11-14.bak.json`. Loading the v2 cache for the current drop yields the identical char table (26,700) and the enlarged word table (603) — the rebuilt cache re-derives byte-identically from the 11 non-catusf sources (skipping catusf is lossless; catusf contributes nothing).
- **catusf is skipped at ingest by default** (`skip_sources: ["catusf.jsonl"]` in `configs/dictionary.yaml`). The official drop ships the full catusf dump (3,541,369 records, zero `readings` keys, ≥ 2.04M English-Vietnamese): a seconds-per-stage parse that contributes nothing (a full no-skip rebuild yields byte-identical char/word tables to the skipped build, ~10 s slower). Remove the skip only after the provider re-declares the 5-dict subset (22,030 / 9,897 / 78,573 / 3,189 / 139,043 = 252,732). To optionally harvest the declared Hán-Việt dicts' hv readings: `python tools/harvest_catusf_hv.py --entries dictionaries-04-11-2026/entries/catusf.jsonl --out data/dictionary/catusf_hv_harvested.jsonl` — 2026-11-14 yield: **34,998 records / 40,338 readings** (TranVanChanh 22,028/22,030 — one record rejected as a non-positional false positive, TudienThienChuu 9,897/9,897, HanziStoriesViet 3,073/3,189, plus `skipped_unaligned` guard). Ids are unique (raw `#n` suffixes are propagated — heads shared across records like 不/不#2 stay distinct) and multi-codepoint heads are emitted only when syllable count == head length. It is **not wired into the default cache build**; copy/rename the output into the entries dir as `catusf_hv.jsonl` only after human review, then rebuild.
- **hannom_rcv chuẩn bảng now spreads at build time**: its `kind=word script=qn` records with `readings: null` (1,962 records) spread the qn head itself onto the multi-cp nom form positionally (syllables == form chars). Measured marginal token gain is small (2 new word entries — 2,777 of 2,779 unique chuẩn assignments were already present via dv/hvdic char tables); this fix is for correctness, not gate movement.
- **Kim Hán Nôm PUA handling is opt-in and defaults to OFF.** `KHN_PUA_ENABLED=1` (or `hannom.pua_map` API) enables treating Plane-15/16 + BMP PUA code points as Nôm characters (`is_nom_char`, counting, learning, DICT_MISS), and applies the human-curated mapping in `configs/khn_pua_map.yaml` at clean time (`NOM_PUA_MAPPED` instead of 〓). The seed maps **U+F021D → 𡃕 only** (dv evidence; book-side occurrence is in Tap1 page 0185). Unmapped PUA code points (the other 764 of 765 sanitizer-recorded occurrences; Tap1 674 / Tap2 14 / SLQ 77) remain unencodable → 〓, as before. Any clean re-run requires careful review of which PUA glyphs each book actually prints; enabling this does NOT retroactively recover the 〓 already in `data/clean` — PUA evidence is only available from `data/ocr` (raw) or a fresh clean run.
- **`reconcile` is count-faithful**: trusted counts are rebuilt from the provenance records (`count` field; automated records = 1), not `len(kept)`; a weight-only difference sets `changed=True` and `counts_rewritten` in the summary. A reconcile that erodes `时 then→1080` → `then→1` is no longer possible; with `changed=True` the orchestrator backs up the lexicon before the save.
- **`_authorized_granules` single-token branch now honors `BLOCKING_FLAGS`** — matching `learn_from_rows` path B (rows with blocking flags never authorize automated evidence; explicit-mapping Path A stays flag-agnostic, as does learn path A).
- **Slash-glued readings decompose everywhere**: `LookupResult.readings` extracts QN syllables with the same regex as the cache (`bạ/bộ` → `bạ`, `bộ`); the cache token semantics are unchanged.
- **One evidence source reaches the pipeline matchers**: `gather_readings(char, ..., readings=<Readings>)` merges char∪word cache tokens with lexicon/JSONL evidence (dedup; recorded as `readings-cache` in the source string) and is wired through `align_book` → `build_segments` → `stream_cosegment`/`charstream`, `align_segments`, `semantic_evidence`, `_group_cost`, `_reading_matches`, `auto_text_diff`, `recompute_text_diff` and the charalign diagnostic CLI. `load_readings_cache` degrades to `None` with a **warning** (not silently) if the cache can't be loaded — the pipeline then runs with no cache evidence, same as its pre-2026-11-14 behaviour. The DP reading bonus remains exact-only by default; a new opt-in `alignment.dp_fold_bonus: true` credits **fold-only** anchors at half weight (exact = full weight, fold-only = half; tier weights 2.0/1.0 on the textdiff NW-matcher scale). Turn it on only after re-baselining gates.
- **Learning-counter honesty**: `learn_from_rows` path A **and** path B count `learned_pairs` only for pairs the lexicon actually stored — unsupported code points land in the `skipped_unlearnable` counter in the summary dict (path A could previously inflate the counter silently). The summary also carries `quarantine` and `counts_rewritten` (see M1 below).
- Image-map pairs carry `confidence` (1.0 for marker-verified pairs; fraction of reading-carrying Nôm chars with a reliable anchor otherwise), `source` (`printed_marker` / `heuristic_mass` / `manual`) and `status` (`candidate` / `verified` / `unresolved` / `manual`). Manual corrections live in `data/layout/<book_id>/image_map.manual.json` and, when present, fully replace the formula mapping.
