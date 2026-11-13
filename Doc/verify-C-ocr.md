# Verify-C — Area C: OCR subsystem (Stage 4) — Final verification report

> **REVISION 2026-11-12 (post map-repair change-set):** written against pre-`feat/map-repair-align` state; the collaborator's uncommitted 2026-11-12 change-set (image_map repair; Tap1/Tap3 scope re-bin to misc/vi; `hannom.charstream` dịch-âm segmenter; align CSVs rebuilt (Tap1 727→823 / Tap3 341→380); labels regenerated (Tap1 OK; Tap3 inconsistent); tests 277→282, all pass) is incorporated. Claims revised inline. Numbers re-measured read-only 2026-11-12.

**Audience:** the next agent picking up this repo. Zero prior context assumed.
**Author:** area-C verification agent (subagent), 2026-11-12; revision pass 2026-11-12 (post map-repair change-set).
**Repo HEAD tested:** `feat/map-repair-align` @ `c3439e7` (2026-11-12, repair-branch tip, on origin), uncommitted 2026-11-12 change-set in working tree (9 modified source/config/docs files + 5 new source files: `src/hannom/charstream.py`, `src/hannom/map_repair.py`, `tests/test_charstream.py`, `tests/test_map_repair.py`, `tools/repair_image_map.py`; the `Doc/verify-*.md` files incl. this one and `submission/` are also untracked). Nothing committed by the change-set. OCR subsystem (`ocr/*`, quota, `kimhannom.py`, `router.py`, `clean.py`) untouched by the change-set. (revised 2026-11-12)
**Verdict:** implementation quality of the OCR stack is good (UA exact, token hygiene clean, caching deterministic, 282 tests green, OCR↔DB sha consistent) and the manual's constraints are mostly honoured. **The dominant blocker is delivery, not code: Tap2 is 1.1% OCR'd and this week's Kim Hán Nôm quota (219 calls) cannot finish it.** Several latent defects need fixing before the ≥95% gate is reachable. (line numbers in defect citations were checked against the 2026-11-12 post-change tree — see §1, §7, §10, §11 and the Revision log; OCR-subsystem behaviour itself is unchanged.)

---

## 1. Scope & files

**In scope (verified line by line):**

- `src/hannom/ocr/` — `base.py`, `kimhannom.py` (PyKim Hán Nôm API client), `local_paddle.py`, `local_vintern.py`, `quota.py`, `router.py`, `agreement.py`, `mock.py`, `__init__.py`
- `src/hannom/config.py` — `ApiSettings` (63-86), `OCRSettings` (23-29), `load_config` (121-215) — (revised 2026-11-12; config.py gained 7 lines in the 2026-11-12 change-set: `inventory_vi`/`inventory_misc` BookConfig fields at 47-48, loader parsing at 163-164)
- `src/hannom/state.py` — `log_api_call`/`count_api_calls`/`api_calls_since`/`last_api_call`/`update_page`/`upsert_page`/`_row_to_page` (252-300, 182-250)
- `src/hannom/cli.py` — `ocr` command, `OCR_FOLDERS_BY_SCRIPT`, `filter_pages_by_script` (100-154); `src/hannom/orchestrator.py` — `stage_ocr`, `stage_labels`, `stage_clean` (110-275; orchestrator.py still 571 lines total — the 2026-11-12 change-set added `"misc"` to the `stage_labels` folder tuple at ~line 169, otherwise unchanged); `src/hannom/labels.py` — `points_to_quad` (41-69), `line_to_box` (83-90); `src/hannom/clean.py` — `MASK`, `count_nom_chars` (17, 101-102); `src/hannom/models.py` — `OCRLine`/`OCRResult` (~35-60); `src/hannom/evaluate.py` (`MASK` handling ~274-308); `src/hannom/textdiff.py` — `scoreable_nom_chars` (603-612, was 588-597 before the change-set); `src/hannom/package.py` — zip secret scan (520-546)
- `configs/ocr.yaml`, `configs/project.yaml` (`api:` 24-35, `quality:` 45-55), `configs/books/T1_CamPhong_Tap1.yaml`, `T1_CamPhong_Tap2.yaml`, `T1_SuaLoiQuyen.yaml` — (the two Tap1/Tap3 YAMLs were modified 2026-11-12 with declarative `inventory_vi`/`inventory_misc` bin overrides; their `ocr:` sections are unchanged — the OCR-relevant verdicts above stand as revised 2026-11-12)
- `pyproject.toml` — pins (`requests==2.32.5`, `paddleocr==3.7.0`, `transformers==4.46.3`, torch via cu126 index per comment)

- The 2026-11-12 change-set itself is **out of this report's scope** except where it changes OCR-adjacent facts: `image_map` repair (`map_repair.py`), Tap1/Tap3 scope re-bin to `misc`/`vi` (`configs/books/T1_CamPhong_Tap1.yaml`, `T1_SuaLoiQuyen.yaml`, `layout.py`), `hannom.charstream` dịch-âm segmenter, align CSVs rebuilt (Tap1 727→823 / Tap3 341→380), labels regenerated (Tap1 consistent; Tap3 inconsistent). The OCR subsystem proper is byte-identical to what was audited before. (revised 2026-11-12)

**Cross-checked against:**

- `API_Kim_Han_Nom_guide.extracted.txt` (repo root; API manual, version 2026-10-10)
- `Quy_đinh_đồ_án_v2.1.extracted.txt` (repo root; v2.1 guideline, p.4 "Chạy OCR hình ảnh")
- **NOT read:** `hannom_API.md`, `.env` (per ground rules; never printed; token never shown anywhere)

**Data inspected (read-only):** `data/ocr/<book>/*.json`, `data/ocr/api_cache/**`, `data/ocr/*/local_fallback/*`, `data/state.sqlite3` (`pages`, `api_calls`, `runs`; `runs` table is empty).

**Tests:** `python -m pytest -q` → **282 passed, 0 failed** (warnings only: typer/click deprecation; re-run read-only during this revision 2026-11-12 — was 277 before the change-set). (revised 2026-11-12)

---

## 2. Method & ground rules

- **READ-ONLY on the repo and `data/`.** No file outside `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-C\` was written by this revision pass. The original 2026-11-12 audit wrote scratch to `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-C\`; the revision pass (this document's inline tags) re-measured the numbers with scratch in `verify-revise-C\` (`census.py`, `census2.py`). Scratch contains all analysis scripts (`inspect_state.py`, `inspect_pages.py`, `ocr_stats.py`, `short_pages.py`, `p67_cache.py`, `dup_calls.py`, `band_*.py`, `conf_*.py`, `quota_probe.py`, `ua_check.py`, `cache_shapes.py`, `cache_codes.py`, `timing.py`, `consistency.py`, `difficult.py`, etc.) and `pytest.log`.
- **Absolutely no network calls**; in particular **no requests to `kimhannom.fit.hcmus.edu.vn`** were made. Live-API behaviour is inferred only from repo artefacts (ledger, cache, OCR JSONs).
- **`.env` and `hannom_API.md` were not read**; no token material is reproduced anywhere in this report or in scratch. Token handling is verified structurally (grep for logging/printing; `package.py`'s secret scan).
- **No repo modifications** by either audit pass. (`git status --porcelain` as of 2026-11-12 shows the 2026-11-12 change-set only: 9 modified — `configs/alignment.yaml`, `configs/books/T1_CamPhong_Tap1.yaml`, `configs/books/T1_SuaLoiQuyen.yaml`, `docs/decisions.md`, `src/hannom/align.py`, `src/hannom/config.py`, `src/hannom/layout.py`, `src/hannom/orchestrator.py`, `src/hannom/textdiff.py` — plus untracked `Doc/verify-*.md` (incl. this file), `src/hannom/charstream.py`, `src/hannom/map_repair.py`, `tests/test_charstream.py`, `tests/test_map_repair.py`, `tools/repair_image_map.py`, `submission/`, and the pre-existing three `*.extracted.txt` files. Nothing committed; CI not re-run (still triggered on `repair/**` pushes). Tap2 book YAML is **not** modified.) (revised 2026-11-12)
- Internet search was permitted but not needed; all compliance claims rest on the manual/guideline extracts and repo evidence.
- **Probe list actually executed** (see §10 for exact reproductions):
  - read-only sqlite queries (`mode=ro`): table list/counts, api_calls by endpoint×status, per-image duplicates, W45/W46 & daily usage, quota_week/quota_day labels, `pages` folder/status/engine/flags histogram, `ocr_confidence` NULL cross-tab against OCR JSONs
  - AST/text inspection + exact UA byte comparison (whitespace-flattened) between config and manual
  - scratch simulations against a *temporary* sqlite state: rolling-window quota edge cases, `_success_code` truth table (`"000000":T, 0:T, 1:F, "0":F, None:F, False:T` — **bool False accepted**), future-dated row blocking (`now+3h` → `retry_after=10860s`), `choose_consensus` confidence-free ranking, `sample_page_numbers`, `promote_review_flags`
  - OCR-JSON census: engine/warning/char-count distributions, band-retry evidence, `difficult` value census, sha↔state consistency (390/390 OK)
- **What was NOT verified:** the live API itself (health, business codes, error schema beyond the manual + cached evidence), Vintern/paddle inference on this machine's GPU, timing claims from comments, `Label.txt`/packaging stages (out of scope), `hannom_API.md` contents. See §12 Caveats.

---

## 3. Kim Hán Nôm client vs the manual — compliance table

Exact manual quotes below come from `API_Kim_Han_Nom_guide.extracted.txt` (version 2026-10-10, "Phiên bản: 2026-10-10"). "Guideline" quotes come from Quy_định_đồ_án_v2.1 (§"4. Chạy OCR hình ảnh", p.4).

| # | Item | Manual/guideline (quote) | Code location | Verdict |
|---|---|---|---|---|
| 3.1 | Base URL & path | "Base URLs — https://kimhannom.fit.hcmus.edu.vn … https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/image-upload" (manual pp.2-3) | `kimhannom.py:223` `f"{self.project.api.base_url}/api/web/clc-sinonom/{endpoint}"` | ✅ exact |
| 3.2 | User-Agent | Manual p.1: "Giá trị User-Agent mặc định: dùng đúng giá trị dưới đây cho mọi request." — `User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0` (lines 19-20, wrapped across two lines) | `configs/project.yaml:26` — byte-identical after whitespace-flatten; NOT starting with `python-requests` ✓ | ✅ exact match (verified programmatically) |
| 3.3 | `Authorization: Bearer <token>` | Manual p.1: "Gửi token theo định dạng Authorization: Bearer <token>." / p.3: "Yêu cầu bearerAuth: header Authorization: Bearer <token>." | `kimhannom.py:71,99` (`os.environ.get(project.api.token_env)` → `headers["Authorization"] = f"Bearer {self.token}"`) | ✅ env-only, never logged/cached/printed (greps clean; token appears in no artifact; `package.py:541` scans zips to prove it) |
| 3.4 | Envelope | Manual pp.2: "Mọi API đều trả về JSON có bốn trường is_success, code, message, data." / "• code = "000000": thực thi thành công; message = null" / ResponseEnvelope: "code: string — Mã kết quả. 000000 là thành công." | `kimhannom.py:45-48` `_success_code` accepts `value == "000000" or value == 0` (and, by Python equality, **`False`**) | ⚠️ **partial — see Defect D1**. All 366 cached responses carry the documented string `"000000"`; the int-0/bool-False path is speculative and untested |
| 3.5 | image-upload | Manual p.3: "Trường `image_file` string (binary) Bắt buộc — Tệp ảnh cần tải lên." | `kimhannom.py:291` `files={"image_file": (path.name, data, "image/jpeg")}` | ✅ exact |
| 3.6 | structure-classification request | Manual p.4: only `file_name` (string) is documented; body `{"file_name": "tempd561….jpg"}` | `kimhannom.py:302-317` sends **`file_name` plus `ocr_id: 0, lang_type: 0, reading_direction: 0`** | ⚠️ **exceeds the manual**, but **sanctioned by the v2.1 guideline** (quote below). Server rejects requests without the 0-fields (code `000108`). Keep; see D7 |
| 3.6a | guideline quote (sanction) | Guideline v2.1, p.4: "image-upload →structure-classification (đặt ocr_id, lang_type, reading_direction bằng 0 để server tự nhận diện) →image-ocr." | (same) | ✅ compliant with guideline |
| 3.6b | cache key | (derived) Code omits volatile `file_name` from the classify cache key — classification is a function of the image, not of the server's temp filename | `kimhannom.py:314-316` | ✅ sound; **staleness risk** if the server's classification model is swapped (D11) — minor |
| 3.7 | classification response | Manual p.5: data = `{ocr_id, lang_type, reading_direction, is_sino_nom}` | `kimhannom.py:449-549` uses `ocr_id`, `reading_direction`, `is_sino_nom` (warning `API_CLASSIFIED_NOT_SINO_NOM` if `is_sino_nom is False`); code ignores `lang_type` (maps by script instead) | ✅ parse OK (all 183 responses `ocr_id=1, dir=1, is_sino_nom=true`) |
| 3.8 | image-ocr payload | Manual pp.5-6: required `ocr_id` (int), `lang_type` (int), `file_name`; optional `epitaph` (default — manual: tag/ epitaph optional, reading_direction "mặc định là dọc"), `reading_direction` ("Chiều đọc; mặc định là dọc"), `tag` ("Yêu cầu dùng mô hình detection chuyên biệt. Mặc định là null") | `kimhannom.py:319-344` sends `{ocr_id, lang_type, reading_direction=1, epitaph=0, file_name, tag=None}`; `reading_direction=1` (vertical, manual default) ✓; `ocr_id/lang_type/reading_direction` taken from classify | ✅ field set exactly matches the manual's example body |
| 3.9 | OcrId / LangType / ReadingDirection / Epitaph enums | Manual p.8-9: OcrId `1 Thông thường, chiều dọc · 2 Hành chính · 3 Ngoại cảnh · 4 Thông thường, chiều ngang`; LangType `0 Chưa biết · 1 Chữ Hán (Chinese) · 2 Chữ Nôm`; ReadingDirection `1 Dọc (mặc định) · 2 Ngang`; Epitaph `0 Văn bản thông thường · 1 Văn bia` | `kimhannom.py:457` (`lang_type = 2 if script == "nom" else 1`); `recognize_page`'s `ocr_id==3` skip for `details.details`-less responses; `epitaph=0`, `tag=None` | ✅ used as documented (no call ever sends LangType 0) |
| 3.10 | image-ocr data | Manual p.6 exemplar: data contains `result_file_name`, `result_ocr_text[]`, `result_bbox[]` ("có thể rỗng", i.e. **yểu thể rỗng**); p.10 ImageOcrData | `kimhannom.py:379-434` handles nested `[points, [transcription, confidence]]` (**all 2284 live boxes**) **and** `details.details` "guideline shape" | ✅ dual-shape parser; all 183 live responses have both shapes present, all `result_ocr_text`↔`result_bbox` lengths equal |
| 3.11 | guideline quote (details/difficult) | Guideline v2.1 §5: "Với kết quả image-ocr (ocr_id khác 3), trường details.details đã có transcription, points (đúng 4 điểm) và difficult… Với ocr_id = 3 không có trường này." | `kimhannom.py:484-490` copies `difficult` when `len(details.details)==len(texts)` else `None`; carried to Label.txt via `line_to_box` (`labels.py:89`) | ✅ implemented; **all 2284 live `difficult` values are `False`** — zero information (see D13) |
| 3.12 | image-rec | Manual p.7: "API nhận dạng (recognition) trên ảnh đã upload, dùng khi image-ocr trả về bounding box không hợp lệ: **đánh dấu lại bounding box, cắt (crop) từng vùng, tải ảnh crop lên bằng API Tải ảnh lên, rồi gọi API này để mô hình nhận dạng chạy trên ảnh crop.** Cấu trúc dữ liệu trong data của response hiện chưa được mô tả." (+ p.10 ImageRecData: "cấu trúc chi tiết hiện chưa được mô tả"); Guideline: "Nếu bounding box từ image-ocr không hợp lệ: chỉnh lại box, cắt từng dòng rồi dùng image-rec." | `kimhannom.py:491-513` calls `recognize()` (image-rec) **on the full page**, replacing texts/boxes when `len(r_texts) >= len(texts)` | ❌ **documented flow violated** — see Defect D2 |
| 3.13 | Rate limiting | Manual p.1: "Giới hạn số lượt gọi (website): Phút 25 / Giờ 50 / Ngày 200 / Tuần 600" + "nên đặt thời gian trễ giữa các request và không gửi nhiều request cùng lúc"; Guideline v2.1: "Giới hạn trên website: 25 lượt/phút, 50 lượt/giờ, 200 lượt/ngày, 600 lượt/tuần. Mỗi ảnh cần ít nhất 2 lượt gọi, nên cần lập kế hoạch…" | `quota.py` + `project.yaml:28-32` (per_minute 25, per_hour 50, per_day 200, per_week 600, min_delay 3.0s) | ✅ enforced locally (rolling windows); scope: the numbers are labelled *website* limits in the manual — see D15 |
| 3.14 | No network at test time; UA never overridden | (process) | `tests/` mock everything; `requests` imported lazily | ✅ |
| 3.15 | UA never drifts | "không được bắt đầu bằng python-requests" (manual p.1) | no `python-requests` default anywhere | ✅ |

**All 183 project `structure-classification` calls succeeded** (live evidence in `data/ocr/api_cache`), with `ocr_id=1, reading_direction=1, is_sino_nom=true ×183, lang_type=2 ×181, 1 ×2`.

**Code 000108 evidence (p67):** `data/state.sqlite3:api_calls` shows **two** `structure-classification` rows for the same image (`image_sha256` prefix `84d3a98c…` = T1_SuaLoiQuyen p67): 2026-11-08 05:41:32 (`http_200`, **no cache entry** for that call) and 05:41:52 (`http_200`, cache entry present, followed by `image-ocr` 05:41:58). Most plausible reading: the first call omitted the 0-fields and the server rejected it with business code `000108` (as the code comment documents: "code 000108, verified 2026-11-08"); the ledger nevertheless recorded it as `http_200`. The 20-second gap is consistent with a manual code fix between runs. This is the only concrete evidence for both (a) the 000108 claim's validity and (b) the ledger's status blindness (D5).

---

## 4. Quota analysis

Source: `data/state.sqlite3.api_calls` (read-only, 550 rows) + `QuotaLedger` semantics (`quota.py:41-126`) + scratch simulation.

### 4.1 Usage vs limits

| window | used | limit | remaining |
|---|---|---|---|
| W45 (2026-11-02→08, `quota_week=2026-W45`) | **169** | ~600/week | — |
| W46 (2026-11-09→15, `quota_week=2026-W46`) | **381** (= 198 on 11-10 + 183 on 11-11; **zero calls on 2026-11-12**) | **600** | **219** |
| 2026-11-08 (Sunday, W45) | 169 | 200/day | fine |
| 2026-11-10 | **198 / 200** | nearly exhausted | 2 |
| 2026-11-11 | **183 / 200** | ok | 17 |
| minute (25/min, `min_delay_seconds=3.0`) | not saturated in practice (3s delay ⇒ ≤20/min) | 25 | ok |

- **550 calls total = 183 `image-upload` + 184 `structure-classification` + 183 `image-ocr`** (all recorded as `http_200`). One image (T1_SuaLoiQuyen p67) was classified twice (the 000108 failure + re-run), the other 182 images exactly once. Distinct images per endpoint: 183/183.
- ⚠ **219 calls remain this week; Tap2 needs 264 Nôm pages.** Even with **`--no-classify`** (see §4.4), that is 264 pages × 2 calls (upload+ocr) = **528 calls > 219**. The API cannot finish Tap2 before the week rolls over (2026-11-16, W47). (revised 2026-11-12 — unchanged: still 219 left, still W46-blocked; 2026-11-12 saw zero API calls)
- `--wait-quota` (`cli.py:109`, `router.py` honours `project.api.wait_on_quota`) sleeps through quota windows instead of stopping the run; pairs with `--no-classify`.

### 4.2 Ledger semantics (verified by code read + scratch simulation)

- `record()` writes **every** attempt, including 4xx/5xx/429 (`kimhannom.py:239,245,250` — all record **before** the business-code check at `253-255`), and including HTTP-200 **with a non-`000000` code** (business failure). Empirically: **all 550 rows say `http_200`; at least one of them (p67, first classify at 05:41:32) was a business failure**. The ledger column is *HTTP status only*, not outcome.
- A transient 500/429 with `max_retries=3` burns **up to 3 ledger rows** per call.
- Rolling windows: `minute`/`hour`/`day`/`week` sliding windows computed from `api_calls_since(since)` (`quota.py:49-72`); `seconds_until_allowed` waits for the **oldest row in the window** to age out (`quota.py:74-88`) — correct sliding-window semantics (verified: 2 calls with limit 2, oldest 55 s ago ⇒ wait ≈ 5.0 s ✓).
- **Future-row bug (verified)**: a `requested_at = now + 3h` row is counted in **all four windows** (`requested_at >= since`, no upper bound) and yields `QuotaExceeded(retry_after=10860s)` — a single clock-skewed/forward-dated row bricks the API until the row ages out.
- `check()` (quota.py:90-105) counts **all** recorded rows (failures included) against the limit — conservative (over-count vs the server) but never under-counts a consumed call; fine as a safety margin as long as the business-error blindness (D5) is fixed, or operators will systematically over-count silent failures.
- Weekly limit scope: the manual labels these numbers "Giới hạn số lượt gọi **(website)**". The code applies them to the API (`quota.py:1-5` documents the choice); the v2.1 guideline applies the same numbers to direct API calls ("Giới hạn trên website: … Khi gọi trực tiếp qua API"), so the scope is the guideline's own implication and the conservative reading. Worth one line in docs, but not a defect.
- `min_delay_seconds=3.0` ⇒ ≤20 requests/minute — inside the 25/min website cap with margin; single-threaded, sequential POSTs ✓ (manual: "không gửi nhiều request cùng lúc").
- `validate_ledger_timestamp()` (`quota.py:125-126`) and `QuotaSnapshot.to_dict()` (`quota.py:31-39`) are dead code.
- `last_api_call`/`seconds_until_allowed` correctly handle the min-delay spacing.

### 4.3 Re-upload cost amplification

`recognize_page`'s `except ApiBusinessError` branch (`kimhannom.py:466-480`) re-uploads once (`force=True`) and re-runs classify→ocr. Classify itself is then served from cache (same image sha), so the re-upload costs **+1 call**; contrast with a hard-fail auth error, which instead silently OCRs the book with the local engine (see D8). The re-upload path is **untested live** (zero `Upload force` occurrences in the ledger: only 1 upload per image).

### 4.4 Classify is losslessly skippable for Tap2

All **183** cached `structure-classification` responses: `ocr_id=1, reading_direction=1` (2 images answered `lang_type=1` Hán vs Nôm — irrelevant, the client maps lang_type itself). For this printed vertical Nôm corpus, `classify=false` + fixed layout (`fixed_ocr_id=1`, `fixed_reading_direction=1`, `ApiSettings` lines 79-80 — was 74-75 pre-change-set) produces the identical payload **and saves 264 calls for Tap2** (`--no-classify` or `api.classify: false`). This is the single biggest quota saving available. (revised 2026-11-12)

### 4.5 Weekly budget arithmetic for the remaining work

| item | calls |
|---|---|
| Tap2 Nôm 264 pages × (upload+ocr) with `--no-classify` | **528** |
| same with classify | 792 |
| Remaining this week (W46) | 219 |
| Needed before rollover | ≥ 309 short → **must wait for W47 (2026-11-16)** or downgrade scope |
| Vintern for Tap2's 279 vi/intro/toc pages | 0 (local GPU, ~35-120 s/page ≈ 2.7-9 h) |
| bytes already cached (image-ocr+classify+upload) | 183/183 hit-rate for completed pages; re-runs are free |

---

## 5. State↔artifact skew (proven)

Cross-tab of `data/ocr/*/*.json` vs `data/state.sqlite3.pages`:

1. **51 API pages carry confidence-bearing lines in JSON but `ocr_confidence IS NULL` in state** — 50 SuaLoiQuyen kimhannom pages (the entire 2026-11-08 21:00 batch) + Tap1 p147 (NOM_BLOCK_START page, 2026-11-08 19:24). Root cause: those pages were OCR'd by an older code revision / crashed before `update_page` committed confidence; `update_page` itself is unconditional, so some path in the 11-08 code passed/failed differently. Modern code (`router.py:366-375`) always sets `ocr_confidence` when ≥1 line has confidence. **Consequence:** any consumer reading state (review app, gates) sees these as unscored → they will be counted as "unverified", not as low-quality-but-scored.
2. **Band-retry pages: 40 total, only 36 have `BAND_RETRY_AFTER_FULLPAGE_FAILURE` in page `review_flags`.** The **4 SuaLoiQuyen pages (0016/0032/0040/0056)** carry only `FOOTER_TITLE_REMOVED` (their JSONs were written 2026-11-09 00:39 by a run that predates the router fix *or* bypass propagation); cache-hit re-runs never re-promote warnings. Tap1's 36 pages (refreshed 2026-11-10/11) are correctly flagged ✓. The 2026-11-12 `stage_labels` re-run did **not** re-run OCR and did **not** re-promote BAND_RETRY flags; Tap1's 36 flagged pages now split **35 vi + 1 misc (p011, which carries both `LABEL_EMPTY_OCR` and `BAND_RETRY_AFTER_FULLPAGE_FAILURE`)** — the 2026-11-12 re-bin moved p011 to `misc`. (revised 2026-11-12)
3. **`difficult` is dead-weight** — `False` ×2284 in every API line (cached `details.details` too). The guideline's `difficult` flag currently carries zero triage information. Do not use it for review ordering.
4. **All 390 OCR JSONs are consistent with the pages table on `(book_id, page_no, image_sha256, status='ocr_done')`** — 0 mismatches. `ocr_done`=390 == 390 JSON files ✓.
5. **All kimhannom JSONs predate the current client** — no `upload_scale`/`classified` keys in `raw` (they were added in the 2026-11-11 upscale change). After any client change, re-OCR with `--force` or re-sync; the response cache (keyed by image sha) keeps re-evaluation free.
6. **local_fallback cruft**: `T1_SuaLoiQuyen/local_fallback/{0016,0032,0040,0056}.json` are stale, text-identical-to-main-file duplicates; they lack the `routing` block (`raw` absent or key missing) and are shadowed by the main files; plus `DRAFT-2026-11-09.md` and `NOTE.md`. No nom page was ever served from local fallback. Delete in a cleanup pass.
7. `pages.ocr_engine` counts: kimhannom 183 / vintern 207 — consistent with the JSON census ✓.
8. `runs` table: empty. No formal run ledger exists; `api_calls` + OCR files are the only provenance trail.

**Also (non-skew but related):** 902/950 pages have non-empty `review_flags` (Tap1 275, Tap2 541, SuaLoiQuyen 86 — was 900/950: Tap1 274, Tap2 541, SuaLoiQuyen 85); `LABEL_EMPTY_OCR` dominates (**808** — Tap1 269, Tap2 537, SuaLoiQuyen 2; was 804 with SuaLoiQuyen at 0). The 2026-11-12 `stage_labels` re-run regenerated labels for all bins incl. `misc` (orchestrator `stage_labels` now writes the `misc` bin; folder tuple at ~line 169 includes `"misc"`). **Tap1 labels were fully rebuilt and are consistent** (Tap1 `misc/Label.txt` covers all 16 DB-misc pages with entries); **Tap3 labels were refreshed incl. misc but are inconsistent** — `data/labels/T1_SuaLoiQuyen/misc/Label.txt` is stale (only 001 and 064 rows vs 12 DB-misc pages; the 10 ocr_done misc pages — 002, 003, 005, 007, 008, 009, 062, 063, 117, 118 — are unlabeled; 062/063 included). That is a labeling-stage flag, not an OCR defect, but it means most Nôm pages will be *coverage gaps*, not *accuracy gaps*, in the gate metrics — and Tap3 misc pages currently cannot be PPOCRLabel-verified even though they were OCR'd. (revised 2026-11-12)

---

## 6. Verified working areas

- **Caching determinism**: API response cache keyed by `sha256(endpoint|image|params)` (183 upload names cached; 366 payload files = 183 classify + 183 image-ocr, all `code="000000"`); re-runs are quota-free; upload names cached per image sha (`uploads/<sha2>/<sha>.json`); enlarged (`upscale`) copy deterministically named `<origsha>_xN.jpg`, atomic `tmp→replace`, boxes scaled back uniformly LANCZOS factor (`kimhannom.py:123-143, 529-532`).
- **`local_fallback/` never shadows API files**; `load_result` prefers `data/ocr/<book>/<page>.json` over `local_fallback/…json` (`router.py:139-143`); nom pages always attempted via API first under `api_first` (`router.py:306-328`); local results land in `local_fallback/` and never overwrite API-handled files (`save_result(local_fallback=True)`, `router.py:168-184`).
- **`--only` over-run guard** (`cli.py:106-121` + `148-154`): `--only nom|qn` filters folders via `OCR_FOLDERS_BY_SCRIPT = {"nom": {"ch"}, "qn": {"vi","intro","toc","ref"}}`; empty filter **skips the book** ("no nom pages (run classify/map first?)") instead of widening to everything; invalid `--only` values rejected (`typer.BadParameter`). The guard is tested (`tests/test_ocr_options.py`).
- **UA hygiene**: project UA == manual default (byte-exact); Bearer never logged/printed/cached; `package.py`'s zip scan would catch a committed token; `.env` git-ignored. **No token exposure found anywhere.**
- **Engine instance caching** (`router.py:90-98`): one instance per engine per process (vintern ~35-120 s/page — without caching this would be catastrophic); paddle models lazy-loaded on first `recognize_page`.
- **Consensus boxed-preference** (`agreement.py:50-75`): `with_boxes` pool preferred (PPOCRLabel needs 4-point boxes); highest mean-line-confidence wins; no-confidence results (Vintern) ranked by `len(text)/10000.0` — monotonic, conservative, and harmless because QN is never mixed with API results; `BBOX_MISSING` raised when no boxed line exists; disagreement emits `OCR_ENGINE_DISAGREE:<a>:<b>:<sim>`; deterministic.
- **Blank/misc excluded from OCR targets; intro/toc/ref included and OCR'd via vintern** (`router.py:386` targets `{"ch","vi","intro","toc","ref"}` — target set unchanged 2026-11-12; `run_page` raises for `blank|misc`, `:245`; `OCR_FOLDERS_BY_SCRIPT` agrees). **Tap2's** 279 vi/intro/toc pages are destined for vintern — correctly planned, not yet run in Tap2. Tap1/Tap3 front matter was re-binned by the 2026-11-12 change-set to `vi` (Tap1 PDF 13–20 = Nôm PDF 276–269 via the parens cross-reference; they were already OCR'd) or `misc` (Tap1 5, 7–11, 143, 144, 277–282; Tap3 2, 3, 5, 7, 8, 9, 62, 63, 117, 118) — Tap1/Tap3 now have **zero** intro/toc pages and **260 / 100** in-target pages respectively, all ocr_done. 29 misc pages are excluded from future OCR targets, of which 24 are already ocr_done (Tap1 14, Tap3 10). (revised 2026-11-12)
- **QN never goes near the API** (`quoc_ngu: [vintern_1b_v2]`; Kim Hán Nôm is Hán/Nôm-only; the routing marks `second_opinion: none`); **no QN page was ever sent to the API** — verified in the ledger (all 183 calls are ch/ pages; per-image p67 etc. are ch).
- **Single full-page box per QN page** (guideline: "đánh 1 box cho toàn trang") — emitted (`local_vintern.py:232-244`), `confidence=None` (never fabricated) ✓.
- **Pipeline consistency**: 390/390 OCR JSONs match `pages(book_id,page_no,sha256,status='ocr_done')` ✓; every OCR file parses as JSON ✓; engines match `pages.ocr_engine` ✓.
- **PPOCRLabel format path**: `points_to_quad` normalises polys/flat/dicts → 4 points; `points_to_quad`+`line_to_box` produce 4-point `points` arrays + `difficult` passthrough — compatible with PPOCRLabel/Label.txt (`labels.py:41-90`).
- **Retry/backoff**: 429/5xx retried ≤3 with `min(60, 2**n)` backoff; 4xx non-retryable ("Retrying a 401 or a bad enum only burns quota and hides the bug"); `ApiBusinessError` raised after `.json()` parse + code check, **never retried** (deterministic) — except the one deliberate re-upload in `recognize_page`.
- **Tests green**: `python -m pytest -q` → 282 passed (re-run read-only during this revision 2026-11-12 — was 277 before the change-set). (revised 2026-11-12)

---

## 7. Defects ranked (file:line)

### D1 — `_success_code` accepts `0` and `False` as success — `src/hannom/ocr/kimhannom.py:45-48`
```python
def _success_code(value: Any) -> bool:
    # The manual documents the string "000000"; accept the integer zero some
    # deployments return, but do not guess arbitrary success values.
    return value == "000000" or value == 0
```
`"000000"==0` is False; `value == 0` is True for `0` and for **`False`** (verified truth table: `"000000":True, 0:True, 1:False, "0":False, None:False, False:True`). The manual documents **only** string `"000000"` (manual p.2, ResponseEnvelope: `code: string`); the comment claims "some deployments return the integer zero" — **no evidence anywhere in the repo, no test covers it** (`tests/` has zero `_success_code` assertions). A `code:false` response would be cached as a valid OCR result. **Fix:** `return value == "000000"` (or raise `KimHanNomError` with the raw envelope); add a unit test asserting `0`, `False`, `1`, `"0"`, `None`, `"000001"` all fail. **Severity: HIGH** (fail-open correctness bug on the API's only contract; never observed on the wire, but one-line latent corruption path).

### D2 — Full-page `image-rec` fallback replaces API texts/boxes via an undocumented response shape — `kimhannom.py:491-513`
```python
needs_rec = (
    len(texts) != len(boxes)
    or (texts and not boxes)
    or (bool(texts) and len([t for t in texts if t]) > len([b for b in boxes if b is not None]) * 2)
)
if needs_rec and ocr_id != 3:
    try:
        rec = self.recognize(file_name, upload_sha, ...)   # FULL PAGE, not crops
        ...
        if r_texts and r_boxes and len(r_texts) >= len(texts):
            texts, boxes, confidences = r_texts, r_boxes, r_confs
            warnings.append("IMAGE_REC_FALLBACK")
```
The manual (p.7) and the v2.1 guideline both specify image-rec **only** for cropped invalid lines: "đánh dấu lại bounding box, cắt (crop) từng vùng, tải ảnh crop lên … rồi gọi API này để mô hình nhận dạng chạy trên ảnh crop" — full-page image-rec is outside documented usage, and image-rec's own response shape is explicitly undocumented ("Cấu trúc dữ liệu trong data của response hiện chưa được mô tả"). Consequences if it ever fires: (i) boxes/texts from an unknown full-page mode silently replace the API's 4-point boxes (violating the PPOCRLabel 4-point contract unless points happen to align); (ii) when the fallback is worse (`len(r_texts) < len(texts)`) it does **nothing silently** — `OCR_LINE_WITHOUT_BBOX`/`OCR_TEXT_BBOX_COUNT_MISMATCH` is recorded but no warning says the recovery attempt failed. **Never triggered live** (API texts/boxes always aligned, 183/183; `api_calls` has **zero `image-rec` rows**; no `IMAGE_REC_FALLBACK` in any JSON). **Fix:** restore documented flow (mark invalid boxes client-side → crop → upload crop → image-rec crop), or delete the fallback; at minimum always record `IMAGE_REC_FALLBACK_NO_IMPROVEMENT`. **Severity: HIGH** (compliance + latent corruption path; currently dormant).

### D3 — Classify cache key omits `file_name` (deliberate) → staleness risk, not corruption — `kimhannom.py:314-317`
```python
cache_params={"ocr_id": 0, "lang_type": 0, "reading_direction": 0},
# Classification is a function of the image, not of the temporary
# server-side file_name. Omitting it makes the cache reusable.
```
Sound reasoning, verified: all 183 classify calls for identical images produce interchangeable results; cache works across renames. **Residual risks:** (a) if the server swaps/retrains its classifier, stale cached `(ocr_id, lang_type, reading_direction)` silently persists — add an API-cache **version/TTL tag** (e.g. `cache_schema: 2026-11`) in the cache file header or a `--purge-api-cache` flag; (b) verify this claim stays true if `classify` is ever re-enabled — currently every classifier answer is `(1,2,1)`. Document as known-weak; not blocking. **Severity: LOW-MEDIUM**.

### D4 — Code `000108`: classify payload exceeds the manual; verified only via the p67 incident — `kimhannom.py:301-317`
Manual documents **only** `file_name` for `structure-classification`; the client adds `ocr_id:0, lang_type:0, reading_direction:0` citing the v2.1 guideline (which *does* prescribe exactly those =0). Evidence this is real and required: the 2026-11-08 ledger entry (two `structure-classification` rows 20 s apart for image `84d3a98c…` = T1_SuaLoiQuyen p67, first one **not** cached → most likely a `000108` business failure recorded as `http_200`). Compliance verdict: **compliant with the guideline, exceedance of the manual** — the manual is stale (2026-10-10) while v2.1 is newer and prescriptive; the fields are constant and were accepted on 183/183 subsequent calls. **Keep the fields; document the deviation** (it is commented in code — extend the comment to quote the guideline); do not extend the undocumented-field pattern to anything else. **Severity: MEDIUM** (contract clarity; risk is a future server-behaviour change, not a current bug).

### D5 — Ledger records HTTP status only; business failures and 4xx/5xx count as `http_*` success — `kimhannom.py:236-255`, `quota.py:107-123`
```python
# _request(), HTTP path:
self.ledger.record(endpoint, image_sha256, f"http_{status}")  # line ~250
if not _success_code(raw.get("code")):                          # line ~253
    raise ApiBusinessError(f"{endpoint}: {raw.get('code')}: {message}")
```
The business-code check happens **after** `record()`. All 550 rows say `http_200`, yet ≥1 call (p67) was an error. Consequences: (i) operators auditing quota see false "all success"; (ii) a silent auth-model/enum regression would burn full pages of quota as "successful" calls while OCRing with nothing (except — see D8 — the local fallback); (iii) no way to distinguish "server at capacity" from "fine". **Fix:** record `status=http_{status}` and **also** `business_code`/`outcome` (or overload `note`): e.g. `note=f"code={raw.get('code')}"`. Decide & document whether failed attempts count toward limits (current: yes — conservative; keep, but make it explicit). **Severity: HIGH** (observability/trust of the quota ledger).

### D6 — Future-dated rows block every quota window — `quota.py:80-88`
```python
since = now - timedelta(seconds=seconds)
rows = self.state.api_calls_since(since)   # requested_at >= since — no upper bound
...
oldest = datetime.fromisoformat(rows[0]["requested_at"])
waits.append(max(0.0, (oldest + timedelta(seconds=seconds) - now).total_seconds()))
```
Verified (scratch): inserting one `requested_at = now + 3h` row makes `check()` raise `QuotaExceeded(retry_after=10860s)`. There is no clamp, no future rejection in `log_api_call`, no `requested_at <= now` filter anywhere. **Fix:** in `api_calls_since`/`seconds_until_allowed`, treat rows with `requested_at > now + tolerance` (e.g. 5 min) as absent (or warn loudly); validate `requested_at <= now` at insert. **Severity: HIGH** (availability trap; low likelihood, unbounded blast radius).

### D7 — Warning non-propagation: silent-degradation paths leave pages unflagged — `router.py:24-41`, `claims for Tap1 36/40 proven` (Tap1 36 pages = 35 vi + 1 misc/p011 as of 2026-11-12; the SuaLoiQuyen 4 remain un-re-promoted) (revised 2026-11-12)
`PROPAGATED_WARNING_CODES = {OCR_ENGINE_DISAGREE, BBOX_MISSING, OCR_EMPTY, BBOX_INVALID, OCR_TEXT_BBOX_COUNT_MISMATCH, BAND_RETRY_AFTER_FULLPAGE_FAILURE}`. **Missing:** `ENGINE_UNAVAILABLE` (incl. broken-token whole-book local fallback), `IMAGE_REC_FALLBACK`, `API_CLASSIFIED_NOT_SINO_NOM`, `OCR_ROUTING_UNKNOWN_MODE`, `OCR_LINE_WITHOUT_BBOX`. Proven empirically: 36 Tap1 band-retry pages have `BAND_RETRY_AFTER_FULLPAGE_FAILURE` in `pages.review_flags` ✓; the **4 SuaLoiQuyen band-retry pages (0016/0032/0040/0056) carry only `FOOTER_TITLE_REMOVED`** because they were OCR'd before the router carried the promotion (mtimes 2026-11-09 00:39; only JSONs, flags not re-synced) — and **cache-hit runs never re-promote**. **Fix:** (i) add the missing codes to `PROPAGATED_WARNING_CODES`; (ii) re-promote on `load_result` (or a one-time migration): for every cached `OCRResult`, union `promote_review_flags(result.warnings)` into `pages.review_flags`. **Severity: HIGH** (gate triage blindness) / the promotion mechanism itself is otherwise correct.

### D8 — Broken/absent API credentials silently OCR the nom corpus with paddle — `router.py:306-335`, `kimihannom.py:78-85, 450-451`
`is_available()` = token set + `requests` importable. If the token expires mid-run: every nom page `is_available()→False` → `unavailable=["kimhannom: unavailable"]` → `results` empty → **all pages fall back to paddle**, each page gets `OCR_UNAVAILABLE` recorded as a **warning only** (not propagated, D7). Paddle for Nôm: similarity **0.02–0.25** vs the API (six stale 2026-11-08 `sample_then_low_confidence` DISAGREE files). The whole book would silently ship garbage. `unknown_mode` assignment handles typo'd `api_mode` but not this. **Fix:** startup auth self-check (cheap: call classify on a tiny/canary image once per run, or verify token reachability first page and abort loudly after N consecutive `ENGINE_UNAVAILABLE`s). At minimum propagate `ENGINE_UNAVAILABLE` into `review_flags`. **Severity: HIGH** (integrity; unobservable without the fix).

### D9 — Vintern emits page-marker-only output on 36/144 Tap1 vintern pages (25%), silently, before band retry — `local_vintern.py:152-166, 217-246` — (36 pages = 35 vi + 1 misc/p011, revised 2026-11-12)
Every such page: `len(text) < 40` (only the printed page marker, e.g. `- 30 - (255)`), `seconds` ≈ **0.7–1.6 s** (vs normal 2–120 s), then `BAND_RETRY_AFTER_FULLPAGE_FAILURE`, top/mid/bot bands re-generated, merged (dedup via `dict.fromkeys`), accepted iff `len(merged) ≥ 2×len(text)` — all 36 recovered (200–850 chars). Lines carry `confidence=None`. Tap1 data: **36/144 vintern JSONs in `data/ocr/T1_CamPhong_Tap1/` tripped the band retry** (36 flagged in state; as of 2026-11-12 split 35 vi + 1 misc/p011 after the re-bin — still 36/144, OCR outputs unchanged); SuaLoiQuyen: 4 more (0016/0032/0040/0056, "4/60" as documented in code — matches; still carrying only `FOOTER_TITLE_REMOVED`). This is a **systematic, page-content-correlated silent failure** (25% incidence, far above the documented 4/60). With the band fallback the text is recovered, but: (a) the failure is unexplained; (b) the merged QN text has **no per-line boxes** — only a single full-page box (PPOCRLabel-compatible, guideline-compliant), so automatic quality metrics can't isolate lines; (c) the `<40 chars` detection works but a page whose marker-only output *barely* clears 40 chars would slip through with garbage. **Fix:** root-cause (page-type? density? stop-token?—try `repetition_penalty=1.0`, longer `max_new_tokens`, or crop/band-first for the affected range); if page-type-specific, exclude those pages from automatic scoring or flag them for manual transcription; add `FULLPAGE_DEGRADED` warning even when merged recovery succeeds (currently only `BAND_RETRY_AFTER_FULLPAGE_FAILURE`, which *is* propagated ✓). **Severity: MEDIUM** (quality risk, mitigated but significant; gate-relevant).

### D10 — Paddle adapter: degenerate all-zero 4-point box used silently — `local_paddle.py:81-89`
```python
if index < len(polys) and polys[index] and len(polys[index]) == 4: ...
if index < len(boxes): ...axis-aligned quad...
return ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0))   # line 89
```
Passes the "4 points" PPOCRLabel check while being an invisible zero-area box; indistinguishable from a valid box downstream. **Fix:** skip the line + warn (`POINTS_UNAVAILABLE`) or clamp min-detection fallback with a flagged zero-size box that packaging rejects. **Severity: MEDIUM** (local engine quality; currently unused for nom hits because API path dominates).

### D11 — Classify cache staleness if the server model changes (see D3) — `kimhannom.py:154-159, 314-317` — **Severity: LOW-MEDIUM** (see D3).

### D12 — Vintern: `trust_remote_code=True` with no `revision=` pin; no watchdog on `model.chat` — `local_vintern.py:76-84, 152-166`
- Loads arbitrary custom code from `5CD-AI/Vintern-1B-v2` at whatever revision; pin `revision="<commit-sha>"`.
- `model.chat` has no timeout — a hung CUDA generation blocks the entire pipeline forever; add an inference watchdog (or accept + document a `max_time`).
- `is_available()` correctly requires `torch.cuda.is_available()` ✓; transformers pinned `==4.46.3` ✓ (per guideline v2.4 note: 5.x breaks Vintern).
- **Severity: MEDIUM** (supply chain) / **LOW** (watchdog; GPU jobs in this project are operator-run).

### D13 — `difficult` carries zero signal; `ensemble`/`max_pages_per_api_batch` dead config — `local_vintern.py`/`kimhannom.py:484-536`; all book YAMLs `ensemble: true`; `ocr.yaml:41`; `config.py:26,168` (revised 2026-11-12; see Revision log — content-locate `ensemble=bool(ocr_raw.get("ensemble", True))` in `load_config`, measured at line 170)
All 2284 API `details.details.difficult` values are `False`; paddle doesn't emit one either. **Stop using `difficult` for triage.** `ensemble: true` (all 3 book YAMLs) is parsed into `OCRSettings.ensemble` and **never read anywhere** — remove or wire it. `max_pages_per_api_batch: 12` (ocr.yaml:41) unused. `OCRSettings.sample_pages` used only by `sample_then_low_confidence`. **Severity: LOW** (operator confusion).

### D14 — `validate_ledger_timestamp` dead; `QuotaSnapshot.to_dict` dead; `token_id` unused — `quota.py:125-126,31-39`, `kimhannom.py:72` — **Severity: LOW**.

### D15 — Website-vs-API quota scope — `quota.py:1-5` — the manual labels its limits "(website)"; code applies them to the API. Conclusion: **keep, but document** (it is also the guideline's own reading). **Severity: LOW.**

---

## 8. Empirical counts (as of 2026-11-12, this repo state — revised 2026-11-12 post map-repair change-set)

| Metric | Value |
|---|---|
| Books | 3 (`T1_CamPhong_Tap1` 282 pp, `T1_CamPhong_Tap2` 550 pp, `T1_SuaLoiQuyen` 118 pp) |
| Pages total / classified / ocr_done | **950 / 560 / 390** |
| OCR targets `{ch,vi,intro,toc,ref}` | 260 + 543 + 100 = **903** (blank 18, **misc 29 excluded** ✓ — 16 Tap1 + 12 SuaLoiQuyen + 1 Tap2; Tap1/Tap3 intro/toc emptied by the 2026-11-12 re-bin; Tap1 PDF 13–20 are now `vi` and already OCR'd) |
| **OCR done** | **Tap1 260/260 ✓, SuaLoiQuyen 100/100 ✓, Tap2 6/543 (1.1%)** — Tap1/Tap3 also hold 14 + 10 already-OCR'd `misc` pages outside the future target set (24 misc ocr_done total; 5 misc pages remain classified-only: Tap1 p001, p145; SuaLoiQuyen p001, p064; Tap2 p001) |
| OCR JSON files | 390 (all parse; 390/390 sha-consistent with `pages`) |
| Engines in files | vintern_1b_v2 **207**, kimhannom **183** |
| `api_calls` rows | **550** = 183 `image-upload` + **184** `structure-classification` + 183 `image-ocr`; **all recorded `http_200`** |
| Distinct images per endpoint | 183 / 183 (p67 classified twice → 184) |
| Weekly usage | W45=169, **W46=381/600 (219 left; zero calls on 2026-11-12)** |
| Daily usage | 11-10 **198/200**, 11-11 183/200 |
| `data/ocr/api_cache` | 366 payloads (183 classify + 183 image-ocr; all `code="000000"`, all `details.details` present for image-ocr) + 183 `uploads/*.json` file_names |
| Warnings across JSONs | `BAND_RETRY_AFTER_FULLPAGE_FAILURE` **40** (36 Tap1 + 4 SuaLoiQuyen), `OCR_ENGINE_DISAGREE` **6** (all stale `sample_then_low_confidence` mode, sim 0.02–0.25) |
| Warnings present: `ENGINE_UNAVAILABLE` / `IMAGE_REC_FALLBACK` / `BBOX_INVALID` / `OCR_EMPTY` / `BBOX_MISSING` / `API_CLASSIFIED_NOT_SINO_NOM` | **0 / 0 / 0 / 0 / 0 / 0** |
| Lines in API results | **2284**; `difficult=False` ×2284; `result_bbox` nested shape ×2284 |
| Lines with `confidence<0.5` | **150** across **93 pages** (91 Tap1 + 2 Tap2) |
| Mean line confidence (API pages) | ≈0.907 (Tap1) / 0.86 (all) / 0.971 (SuaLoiQuyen) |
| Pages with `<100` chars OCR text | **14** — Tap1 0005(29,misc — was intro) 0009(5,misc — was toc) 0013(55,vi — was intro) 0083(12,vi) 0271(84,ch) 0275(29,ch) 0276(15,ch, DISAGREE 0.25); Tap2 0275(19,vi); SuaLoiQuyen 0002(14,misc) 0003(17,misc) 0005(57,misc) 0009(15,misc) 0060(64,vi) 0067(13,ch) |
| Pages `<10` chars | 1 (Tap1 0009, misc — was toc; `LABEL_EMPTY_OCR` + `TOC_LIKELY_FRONT` flags) |
| Pages `<50` chars Nôm (ch) | **3** (Tap1 0275(29), 0276(15), SuaLoiQuyen 0067(13)) |
| State pages with non-empty `review_flags` | **902/950** (Tap1 275, Tap2 541, SuaLoiQuyen 86; LABEL_EMPTY_OCR **808** — Tap1 269, Tap2 537, SuaLoiQuyen 2, labeling stage; BAND_RETRY 36 (Tap1 35 vi + 1 misc/p011); DISAGREE 5; NOM_UNENCODABLE_REPLACED 167; PAGE_MARK_REMOVED 104) |
| `ocr_confidence` NULL in state despite confidences in JSON | **51 API pages** (50 SuaLoiQuyen + Tap1 p147) |
| Tap2 OCR'd pages | 6 (0277/0409/0540 ch via sample mode 2026-11-08; 3 vi) |
| `local_fallback/` files | 4 stale duplicates (SuaLoiQuyen) + DRAFT/NOTE `.md` |
| pytest | **282 passed / 0 failed** |

**Reading the counts:** Tap1 and SuaLoiQuyen are done and consistent; Tap2 is the gap. All silent-failure signatures (0 `OCR_EMPTY`, 0 `BBOX_*`) are clean; the only live risks are the 40 band-retry pages and the 51 state-skew pages, plus **Tap2** itself.

**Repo-state note (revised 2026-11-12):** both books were re-aligned on 2026-11-12 (image_map repair; `charalign` dịch-âm segmenter for Tap1 & Tap3, Tap2 stays `cosegment`). Align CSVs rebuilt: **Tap1 727→823 rows** (similarity **89.96**, was 87.36) / **Tap3 341→380 rows** (similarity **93.74**, was 85.87); null-row ratio 0.000 both books. **Gates still FAIL** (coverage 0.46 Tap1 / 0.60 Tap3, unverified_ratio 0.54 / 0.40; `SIMILARITY_BELOW_GATE` 89.96 < 95 / 93.74 < 95) — gate status unchanged, rows await human review. `data/evaluation/T1_CamPhong_Tap1/metrics.json` mtime 2026-11-12 19:43; `data/evaluation/T1_SuaLoiQuyen/metrics.json` 19:03 (Tap2 metrics untouched, 2026-11-08). OCR freshness itself is unchanged — no OCR JSON, `api_calls` row, or `ocr_confidence` was touched by the re-alignment; the numbers above remain from the 2026-11-10/11 OCR runs. Tap3 misc/Label.txt remains stale as noted in §5.

---

## 9. Prioritized recommendations R1-R10

Impact on the ≥95% gate is annotated per item.

- **R1 — Run Vintern over Tap2's remaining QN pages now** (`python -m hannom.cli ocr --only qn`, or the full `--only` matrix): 279 pages (267 vi + 2 intro + 10 toc) × ~35-120 s ≈ **3-9 h GPU**. Zero API quota. (Tap2-only: Tap1/Tap3 front matter is already OCR'd or sits in `misc` and is outside future targets — revised 2026-11-12.)
  *Gate impact:* makes Tap2's QN half measurable at all; expect the same 25% band-retry incidence as Tap1 → those pages join the R6 review queue.

- **R2 — Block the API for Tap2 Nôm until W47 (2026-11-16), then run with `--no-classify`:**
  `python -m hannom.cli ocr --only nom --no-classify --wait-quota`
  (Per §4.4, classify is lossless to skip: all 183 prior responses are `ocr_id=1, dir=1`; saves **528** calls. `--only nom` prevents QN pages from consuming API. `--wait-quota` prevents a mid-week abort.)
  *Gate impact:* 264/264 Nôm pages OCR'd with API quality; without it, Tap2 Nôm is impossible this week (219 calls left). **Highest-value change available.**

- **R3 — Re-sync state before scoring:** set `pages.ocr_confidence` from the 51 JSONs (and union `promote_review_flags` for all 390 cached results into `review_flags`) — pure local operation, **zero API calls**. Also add the 4 SuaLoiQuyen band-retry pages' `BAND_RETRY_AFTER_FULLPAGE_FAILURE` to their `review_flags`.
  *Gate impact:* 51 pages move from "unscored/unverified" to scorable; +4 pages correctly flagged for human review instead of silently clean.

- **R4 — Ship the two one-line fixes first:** (a) `KimHanNomClient._success_code` → strict `== "000000"` (D1); (b) propagate `ENGINE_UNAVAILABLE`, `IMAGE_REC_FALLBACK`, `API_CLASSIFIED_NOT_SINO_NOM`, `OCR_ROUTING_UNKNOWN_MODE` (D7). Both are 5-minute patches + tests; re-run `python -m pytest -q` before any API spend.
  *Gate impact:* prevents fail-open success and makes every degradation path visible to reviewers.

- **R5 — Fix the ledger honesty gap (D5+D6):** add `business_code`/`outcome` to `api_calls` records (or `note=f"code={…}"`), and clamp/skip future `requested_at` rows in `api_calls_since`. Backfill note for the p67 row. Do not change what counts toward the limit without a deliberate written decision (current = count all; conservative, keep).
  *Gate impact:* honest quota accounting → correct W47/R2 scheduling; no silent error burns.

- **R6 — Retriage the suspicious pages before the gate run:** (i) 150 API lines `<0.5` conf over **93 pages** (Tap1 91 — sort by confidence, review lowest first); (ii) the **40 BAND_RETRY pages** — 36 Tap1 flagged (now 35 vi + 1 misc/p011) + 4 SuaLoiQuyen unflagged; merged-text QN — verify merge didn't duplicate/missing bands, spot-check against source scans; (iii) **3-4 short Nôm pages**: SuaLoiQuyen 0067(13 chars, NOM_BLOCK_START), Tap1 0275(29)/0276(15, DISAGREE 0.25, NOM_BLOCK_END) — these are near-empty and must pass human review or be treated as empty; (iv) 6 stale DISAGREE pages (mode dead, but the samples prove paddle≈0.02-0.25 similarity — do not let paddle serve nom anywhere); (v) **167 `NOM_UNENCODABLE_REPLACED`** pages — sample ≥20 to validate the `〓`/`[MASK]` policy; (vi) **14** `<100`-char pages (mostly front-matter — Tap1 0005/0009 now `misc`, 0013 now `vi`; SuaLoiQuyen 0002/0003/0005/0009 now `misc`); auto-skip OK. Note: SuaLoiQuyen misc pages also cannot be label-verified until `misc/Label.txt` is regenerated (§5). (revised 2026-11-12)
  *Gate impact:* converts silent failures into explicit review; protects the 95% claim's honesty.

- **R7 — Do not use `difficult` for triage** (`difficult=False` ×2284). Replace with confidence-sorted review queues.

- **R8 — QN gate tactic:** for the 40 band-retry + any page whose `clean` stage produced `PAGE_MARK_REMOVED`/`DUPLICATE_LINES_REMOVED` (104/6 flags), exclude from automatic similarity scoring and count as `unverified` (they already reduce coverage rather than accuracy — that's the right gate behaviour). Do not let band-merged text inflate the verified-match ratio.

- **R9 — Sequencing to the 2026-11-30 deadline (18 days):** Day 0: R4+R5 (fixes) + R3 (re-sync) → Day 1-2: R1 (Tap2 QN GPU) + R2 queued for Monday W47 → Day 3-9: W47 API batch over 264 pages (`--no-classify`, 3s delay, `--wait-quota`) → Day 10-12: review queues (R6) → Day 13-15: labeling + fileState + alignment + gate metrics → Day 16-18: packaging (`package.py`, zip scan already verified clean of tokens). Any API slip beyond W47 eats the window in which the gate can run. (plan unchanged 2026-11-12 — the 11/12 change-set is review-input re-generation, not a pipeline change for Tap2; gates still FAIL on Tap1/Tap3, so the review-queue days are now also where the 823/380 re-aligned rows get triaged.) (revised 2026-11-12)
  *Gate impact:* without this calendar, the Tap2 books cannot pass coverage (≥0.9 verified rows) at all.

- **R10 — Hygiene (before packaging):** delete `local_fallback/` stale duplicates + DRAFT/NOTE (or document); remove dead config (`ensemble`, `max_pages_per_api_batch`, `validate_ledger_timestamp`, unused `token_id`); pin `revision=` for the Vintern model; add a watchdog/timeout on `model.chat`; consider `--no-classify` as the *permanent* default once fixed-layout is validated on a few more books (evidence: 183/183 identical classify verdicts).

---

## 10. Reproduction commands

All commands are **read-only** w.r.t. the repo (except scratch). No network access required.

```powershell
cd "C:\Users\MSI VN\Desktop\NLP"
python -m pytest -q                                  # expect: 282 passed

# Ledger (read-only sqlite; adjust path separators):
python - <<'EOF'
import sqlite3
db = sqlite3.connect("file:C:/Users/MSI VN/Desktop/NLP/data/state.sqlite3?mode=ro", uri=True)
print(db.execute("SELECT endpoint, COUNT(*) FROM api_calls GROUP BY endpoint").fetchall())
print(db.execute("SELECT quota_week, COUNT(*) FROM api_calls GROUP BY quota_week").fetchall())
print(db.execute("SELECT quota_day, COUNT(*) FROM api_calls GROUP BY quota_day").fetchall())
print(db.execute("SELECT endpoint, status, COUNT(*) FROM api_calls GROUP BY endpoint, status").fetchall())
EOF

# Duplicated classify for image 84d3a98c… (evidence of the 000108 retry):
#   SELECT image_sha256, COUNT(*) n FROM api_calls
#   WHERE endpoint='structure-classification' GROUP BY image_sha256 HAVING n>1

# OCR JSON census (engines / warnings / chars / band-retry):
#   see scratch ocr_stats.py / short_pages.py / band_inspect2.py in
#   C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-C\

# API cache shape/code census (all 366 payloads must be code "000000"):
#   see scratch cache_codes.py / cache_shapes.py

# Quota edge cases (temp sqlite, no repo writes):
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-C\quota_probe.py"

# Exact UA match:
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-C\ua2.py"

# State↔artifact skew cross-tab (51 pages NULL):
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-C\conf_gap2.py"

# Consistency check (390/390 OK):
python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-C\consistency.py"

# 2026-11-12 revision pass (read-only re-measurement; this document's numbers):
#   python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-C\census.py"
#   python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-C\census2.py"
#   → api_calls 550 (W45=169, W46=381, 0 on 2026-11-12); endpoints 183/183/184; all http_200;
#     pages 950 (classified 560, ocr_done 390); non-empty review_flags 902 (Tap1 275 / Tap2 541 / SuaLoiQuyen 86);
#     LABEL_EMPTY_OCR 808 (Tap1 269 / Tap2 537 / SuaLoiQuyen 2); Tap1 band-retry flagged 36 (35 vi + 1 misc/p011);
#     Tap3 SuaLoiQuyen misc=12 DB pages but Label.txt only 001,064 (10 ocr_done misc unlabeled);
#     metrics.json mtimes 19:43 (Tap1) / 19:03 (SuaLoiQuyen); align CSVs 823/380 rows; pytest → 282 passed.

# Run the remaining OCR (NOT executed during verification):
# python -m hannom.cli ocr --only nom --no-classify --wait-quota   # R2
# python -m hannom.cli ocr --only qn                              # R1 (vintern, GPU)
```

---

## 11. Handoff checklist (for the next agent)

- [ ] Confirm `git status --porcelain` shows only the intended changes (`Doc/verify-C-ocr.md`; nothing else modified by you).
- [ ] Re-run `python -m pytest -q` — 282 green before and after any edit. (revised 2026-11-12)
- [ ] Apply R4 (two one-line fixes) + their unit tests; re-run pytest.
- [ ] Apply R5/R6 code changes **behind** the same run's tests; do not alter `api_calls` semantics silently.
- [ ] Re-sync state (`ocr_confidence` for the 51 pages; re-promote warnings for all cached results) — verify `ocr_confidence IS NOT NULL` for the 183 API pages and `BAND_RETRY_AFTER_FULLPAGE_FAILURE` present for 40 pages (36 Tap1 flagged + these 4 SuaLoiQuyen pages). The 11/12 `stage_labels` re-run did not change this.
- [ ] Regenerate the stale **Tap3 `misc/Label.txt`** before any label-based review of Tap3 misc pages (currently only 001,064 rows vs 12 DB-misc pages; the 10 ocr_done misc pages, incl. 062/063, are unlabeled — §5). Tap1 labels are already rebuilt and consistent. (revised 2026-11-12)
- [ ] Run R1 (Tap2 QN, GPU); then **wait for W47** and run R2 (`--only nom --no-classify --wait-quota`).
- [ ] Verify no QN page ever appears in `api_calls` (it must not — v2.1/decision: QN never via API).
- [ ] Confirm the gate report separates accuracy (`similarity`) from coverage (`verified/total`) per `evaluate.py`; Tap2's coverage is the binding constraint.
- [ ] Sampling: 167 `NOM_UNENCODABLE_REPLACED` + 40 band-retry pages + 150 low-conf lines + 6 DISAGREE pages must all land in review before any "nhì tóm tắt" (report) claim passes.
- [ ] Do **not** read `hannom_API.md`/`.env`; do not call the API except through `--wait-quota` runs with R4 fixed; never call `kimhannom.fit.hcmus.edu.vn` ad hoc.
- [ ] If any kimhannom client code changes: `--force` re-run of the API pages (or re-sync via cache; no quota re-spend) before re-scoring.
- [ ] Delete `local_fallback/` stale duplicates + DRAFT/NOTE (or document them) before packaging.
- [ ] Update `USER_GUIDE.md`: quota now includes business-failure rows (D5), `--no-classify` recommended after Tap2 evidence, `difficult` not usable.
- [ ] Verify `submission/` (untracked, pre-existing) is handled by whatever process owns it — not this agent's scope.
- [ ] Leave `Doc/verify-C-ocr.md` as the record; append a "resolved" section rather than editing history.

---

## 12. Caveats (what was NOT tested)

- **The live Kim Hán Nôm API was not called** (forbidden). Compliance rests on the manual extract, the v2.1 guideline, and repo artefacts (ledger/cache/JSONs). Business codes **other than** `"000000"` were never observed by this agent; the `000108` claim is an inference from one p67 ledger pair — strong, not absolute.
- **Integer-0 success return is unverified** — no live or cached evidence; treat D1 as speculative-but-deadly.
- **Image-rec full-page behavior** was never exercised (0 calls); D2's impact is wholly unobserved.
- **Vintern inference quality on this machine** was not re-run by this agent; the 36/144 page-marker failure rate comes from persisted outputs (2026-11-10/11), not from a controlled experiment. The band-retry merged outputs' fidelity (duplication? missing columns? 4-point order?) is unverified beyond length statistics — **must be manually sampled**.
- **PaddleOCR** was not run; its Nôm similarity (0.02-0.25) is from six stale `DISAGREE` files produced in a since-removed mode; parity across corpora is not established.
- **`data/state.sqlite3` "all http_200"** is true only of *recorded* rows; business failures are folded in (D5). No evidence either way about what the *server* counts toward its website limits.
- **Timing claims** (`~35 s/page`) come from file `raw.seconds` statistics of past runs (2-120 s observed), not a fresh benchmark.
- **Packaging/labeling/gate stages** (Label.txt writer, `fileState.txt`, alignment, `evaluate_rows`, zip validator) were read but not executed; their correctness is out of this area's scope. The ≥95% recommendation assumes packaging works as written.
- **`hannom_API.md` was not read** (per ground rules) — so the possibility that its content differs from `API_Kim_Han_Nom_guide.extracted.txt` (e.g., different UA list, different limits) is unverified.
- **The 2026-11-12 post-map-repair change-set was not audited for correctness** — only its OCR-relevant facts were re-measured (state DB, OCR JSON census unchanged). `image_map` repair, the Tap1/Tap3 re-bin, `charstream`, and the align CSV rebuild are review-input changes; the OCR artefacts they consume are byte-identical to the 2026-11-10/11 state. Whether the re-bin's `BIN_OVERRIDE_VI`/`BIN_OVERRIDE_MISC` flags or the new `misc` labels are consumed correctly downstream is verify-A/B/D/E scope, not this report's. (revised 2026-11-12)
- The **`submission/`** directory (pre-existing untracked) and the three **`*.extracted.txt`** files were not audited; they are not part of OCR stage 4.
- **made-up dates**: none. All timestamps quoted come from ledger/JSON mtimes.
- **Grep completeness**: token-leak sweep covered `src/**`, `configs/**`, `tools/**`; docs and `data/**` were not exhaustively swept (cache files were shape-inspected only: keys/sizes/`code`, never raw image-text payloads beyond structure).

---

## Appendix — source-of-truth files & line anchors

- `src/hannom/ocr/kimhannom.py` — `_success_code` 45-48; `KimHanNomClient.__init__` (token/token_id) 62-73; `is_available` 78-85; `_get_session` 87-104; `_check_quota` 106-121; `_prepare_upload` 123-143; `_page_layout` 145-152; cache 154-171; upload-name cache 184-204; `_request` 206-273; `upload` 275-299; `classify` 301-317; `ocr` 319-350; `recognize` (image-rec) 352-377; `_extract_boxes` 379-447; `recognize_page` 449-549; `needs_rec` 494-498; `except ApiBusinessError` re-upload 466-480; `difficulty` 484-490; box scale-back 529-532.
- `src/hannom/ocr/quota.py` — `WINDOWS` 41-46; `snapshot` 60-72; `seconds_until_allowed` 74-88; `check` 90-105; `record` 107-123; `validate_ledger_timestamp` 125-126; docstring 1-5.
- `src/hannom/ocr/router.py` — `PROPAGATED_WARNING_CODES` 24-31; `promote_review_flags` 34-41; `sample_page_numbers` 44-55; `page_confidence` 58-68; engine cache/build 90-116; `_path`/`_fallback_path` 130-137; `load_result` 139-166; `save_result` 168-184; `_split_engines` 193-201; `run_page` 239-376; `api_first` 306-335; run_book targets 378-400 (targets `{"ch","vi","intro","toc","ref"}` — **unchanged 2026-11-12**); `OCR_FOLDERS_BY_SCRIPT` + allowlists cli.py:148-154.
- `src/hannom/ocr/agreement.py` — `normalize_for_compare` 12-15; `_mean_confidence` 32-47; `choose_consensus` 50-75.
- `src/hannom/ocr/local_vintern.py` — prompt 36-39; `is_available` 52-59; `_load` 61-86; tiling 89-150; `_generate_on_image` 152-166; `_band_retry` 168-215; `recognize_page` 217-259; `<40` threshold 237.
- `src/hannom/ocr/local_paddle.py` — DEFAULT_DET/REC 27-28; mkldnn workaround 53-56; zero-polygon 89.
- `configs/project.yaml` — `token_env` 24, `user_agent` 26, `limits` 27-31 (per_minute 25/per_hour 50/per_day 200/per_week 600), `min_delay_seconds` 32, `timeout_seconds` 33, `max_retries` 34, `cache_dir` 35.
- `configs/ocr.yaml` — engines 7-25; routing nom/quoc_ngu 27-41; `api_mode: api_first` 40; `max_pages_per_api_batch: 12` 41 (dead).
- `src/hannom/orchestrator.py` — still 571 lines; 2026-11-12 change-set: `stage_labels` folder tuple (~line 169) now `("ch","vi","intro","ref","toc","misc")`; stage_labels re-run regenerated labels for all bins (Tap1 consistent; Tap3 misc stale). `stage_ocr` unchanged.
- `src/hannom/config.py` — 2026-11-12 change-set: `BookConfig.inventory_vi`/`inventory_misc` (fields 47-48, +5-line comment), `load_config` parses them (163-164); `ApiSettings` (63-86), `OCRSettings` (23-29), `load_config` (121-215). (revised 2026-11-12)
- `src/hannom/layout.py` — 2026-11-12 change-set: declarative `BIN_OVERRIDE_VI`/`BIN_OVERRIDE_MISC` post-classification override (~line 339+, never overrides blank/ch/nom). (revised 2026-11-12)
- `src/hannom/textdiff.py` — scoreable_nom_chars 603-612 (was 588-597); `_reading_match` gained the weak orthographic variant-fold cell (`charalign.fold`; quỷ/quỉ/quĩ→qui, d/gi, đ/d; never strong, never rewrites text). (revised 2026-11-12)
- `src/hannom/align.py` — 2026-11-12 change-set added ≤72 lines post-~387 (charalign projection; `COSEGMENTED_STREAM_ALIGNED` segments). Not re-audited line-by-line by this report. (revised 2026-11-12)
- `src/hannom/charstream.py` / `src/hannom/map_repair.py` (new 2026-11-12) — `hannom.charstream` dịch-âm segmenter (charalign); `map_repair` image_map repair (DP pairing + parens anchors; pre-repair map kept at `map_repair/image_map.pre-repair.json`). Not OCR; not audited here. (revised 2026-11-12)
- Manual quotes: `API_Kim_Han_Nom_guide.extracted.txt` pp.1-10 as quoted in §3; guideline quotes: Quy_định_đồ_án_v2.1 extracts pp.4-5 as quoted in §3.6a/§3.11/§3.12.
- Empirical data: `data/state.sqlite3` (`api_calls` 550 rows; `pages` 950 rows), `data/ocr/**` (390 JSONs, 366 API-cache payloads, `uploads/*` 183), `data/align/**` (align CSVs rebuilt 2026-11-12: Tap1 823 rows / Tap3 380 rows), `data/evaluation/**` (metrics.json mtimes 2026-11-12 19:43 Tap1 / 19:03 Tap3; similarity 89.96 / 93.74; gates FAIL), `data/labels/**` (Tap1 rebuilt & consistent; Tap3 misc stale). (revised 2026-11-12)

---

## Revision log (2026-11-12 — post map-repair change-set)

Written against pre-`feat/map-repair-align` state; the 2026-11-12 change-set is uncommitted (nothing committed; branch `feat/map-repair-align` @ `c3439e7`). OCR subsystem (`ocr/*`, `quota.py`, `kimhannom.py`, `router.py`, `clean.py`, `api_calls` ledger) is byte-identical to the audited state — **no defect was fixed, no quota was spent, no state row was touched**, so D1–D15, the quota math and the defect severities are unchanged. Changes made by this revision:

1. **Header**: new revision banner; `Repo HEAD tested` now cites the branch/tip and the full uncommitted change-set list (9 modified + 5 new source files); verdict updated 294→282 tests green.
2. **Tests 277→282** everywhere (verified read-only: `python -m pytest -q` → 282 passed, warnings only); §1, §6, §8, §10, §11.
3. **OCR targets** (§6, §8): Tap1 274→**260** (intro/toc emptied; 13–20 now `vi`, already OCR'd), SuaLoiQuyen 110→**100**, Tap2 543 unchanged ⇒ total 927→**903**; misc excluded 5→**29** (Tap1 16, Tap3 12, Tap2 1); 24 misc pages are ocr_done but outside future targets (router target set `{"ch","vi","intro","toc","ref"}` unchanged). "OCR done" rows and `<100`-char folder annotations updated (0005/0009→misc, 0013→vi; SuaLoiQuyen 0002/0003/0005/0009→misc, 0060→vi).
4. **Review flags** (§5, §8): non-empty `review_flags` 900→**902** (Tap1 274→275, Tap3 85→86; Tap2 541); `LABEL_EMPTY_OCR` 804→**808** (Tap1 267→269, Tap3 0→2, Tap2 537) after the 2026-11-12 `stage_labels` re-run (regenerates all bins incl. `misc`; does not re-promote BAND_RETRY, does not re-run OCR). Tap1 band-retry pages now **35 vi + 1 misc (p011)**. Tap1 labels rebuilt & consistent; **Tap3 `misc/Label.txt` stale** (only 001,064 rows vs 12 DB-misc pages; 10 ocr_done misc pages incl. 062/063 unlabeled) — flagged in §5 and §11.
5. **Line cites updated**: `config.py` (ApiSettings 58-81→63-86; `load_config` span 116-210→121-215; §4.4 `ApiSettings` 74-75→79-80), `textdiff.py` `scoreable_nom_chars` 588-597→603-612 (+1..15 line shift), D13 cite 163→168 (uniform-+5 mapping per brief; **measured position of `ensemble=bool(ocr_raw.get("ensemble", True))` is now line 170** — the second `load_config` insertion (+2) is not modelled by the uniform shift; locate by content), `align.py` post-387 ≤+72 note, orchestrator still 571 lines with `stage_labels` misc tuple at ~169 (§1, §5, Appendix).
6. **Repo-state note (§8)**: both books re-aligned 2026-11-12 (image_map repair; charalign dịch-âm for Tap1/Tap3); align CSVs 727→823 (Tap1) / 341→380 (Tap3); similarity 87.36→**89.96** / 85.87→**93.74**; null ratio 0.000 both; **gates still FAIL** (metrics.json mtimes 19:43 / 19:03); OCR freshness unchanged; align/label/gate facts routed to the other verify reports.
7. **Caveats & checklist**: added change-set-not-audited caveat (§12), Tap3 `misc/Label.txt` regeneration item (§11), appendix entries for the new/changed non-OCR files (orchestrator, config, layout, textdiff, align, charstream, map_repair), revised `.env`/token note (none read this pass either).
8. Scratch for this pass: `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-C\` (`census.py`, `census2.py`); original audit scratch remains at `…\verify-C\`.
9. Not done (out of scope): defects D1–D15 remain unfixed and unre-verified; align CSVs, labels, image_map and gates were not re-audited; CI not re-run; `hannom_API.md`/`.env` still unread; no API calls made (zero on 2026-11-12); `submission/` untouched.

History above this section is preserved as written (2026-11-12 morning, pre-change-set) except where the inline "(revised 2026-11-12)" tags mark superseded claims.
