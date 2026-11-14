# Verify-C — Area C: OCR subsystem (Stage 4) — Final verification report

> **REVISION 2026-11-13 (verification & replication pass — HEAD `d515491`):** the 2026-11-12 revision below was re-verified line-by-line against the current tree, and every empirical claim re-measured read-only on 2026-11-13 (DB `mode=ro`; **no network calls**; `.env`/`hannom_API.md` not read; scratch in `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-replicate-C\`). **All 15 defects D1–D15 reproduce** (current anchors in §7/§13/Appendix; `kimhannom.py`, `router.py`, `quota.py`, `local_*` line numbers are unchanged; `config.py`, `state.py`, `orchestrator.py` (571→643), `package.py` (secret scan moved ~+80), `clean.py`, `labels.py`, `models.py` anchors drifted — see §13 errata). One simulation is overstated (D6 — see corrected wording); two precision fixes (D8 warning name is `ENGINE_UNAVAILABLE`, not `OCR_UNAVAILABLE`; D15's docstring does not document the "(website)" qualifier anywhere); one refinement (D13 `sample_pages` is also read for `routing.api_sample_pages` metadata). The v2.1 sanction for the classify 0-fields (D4) was re-verified verbatim from the guideline PDF (p.4), and the `000108` inference is corroborated end-to-end (second cache entry `abbe…` `saved_at` = 2nd call +16 ms; first call left no cache). Numeric drift from the 2026-11-13 commits (`ed43470`, `4fd0af6` — verify-A hardening; `d515491` — marker-formula maps): pytest 282→**307**; non-empty `review_flags` 902→**907**; OCR targets 903→**899** (Tap2 543→539; Tap2 YAML **is now modified**: `inventory_misc: [273,274,275]`, `vi_to_nom_offset: 549`); Tap2's 6 ocr_done = 0277/0409/0540 (ch) **+ 0009 & 0142 (vi) + 0275 (misc)** (not "3 vi"); Tap3 OCR JSON count 110 main + 4 `local_fallback` (≠116); mean line confidence **0.919 overall** (0.860 = Tap2 only); state `OCR_ENGINE_DISAGREE` 5 vs 6 in JSONs (**p147 missing** — fresh evidence for D7); classify payloads embed a full OCR response incl. `result_image_base64` (~92.7 MB in `api_cache`). Also the 2026-11-13 verify-A re-bin invalidated downstream labels: **Tap3 `misc/Label.txt` still covers only 001/064 (10 ocr_done misc pages unlabeled), Tap2 has no `misc` bin at all — re-run `stage_labels` after any re-bin** (§5, §13.4). Six new findings D16–D21 (§7, §13). Binding blocker remains **delivery, not code**: Tap2 is 1.1% OCR'd (6/539 targets) and W46's remainder cannot finish it (§4). (This banner replaces the stale 2026-11-12 HEAD citation; that revision is preserved below as history.)
>
> **REVISION 2026-11-12 (post map-repair change-set):** written against pre-`feat/map-repair-align` state; the collaborator's uncommitted 2026-11-12 change-set (image_map repair; Tap1/Tap3 scope re-bin to misc/vi; `hannom.charstream` dịch-âm segmenter; align CSVs rebuilt (Tap1 727→823 / Tap3 341→380); labels regenerated (Tap1 OK; Tap3 inconsistent); tests 277→282, all pass) is incorporated. Claims revised inline. Numbers re-measured read-only 2026-11-12. (Superseded by the 2026-11-13 pass above where they disagree.)

**Audience:** the next agent picking up this repo. Zero prior context assumed.
**Author:** area-C verification agent (subagent), 2026-11-12; revision pass 2026-11-12 (post map-repair change-set); **verification & replication pass 2026-11-13** (HEAD `d515491`, clean tree at re-measure).
**Repo HEAD tested:** `d515491` (2026-11-13 — "Marker-formula image maps…"; tree clean at 2026-11-13 re-measure; includes `ed43470` re-bin+hardening, `4fd0af6` verify-A hardening (`state.py` +118 lines), this audit's baseline `c3439e7` + 2026-11-12 uncommitted change-set). API subsystem (`kimhannom.py`, `router.py`, `quota.py`, `local_paddle.py`, `local_vintern.py`) unchanged since the 2026-11-11 OCR runs; exact line anchors for those files still hold (see §13).
**Verdict:** implementation quality of the OCR stack is good (UA exact, token hygiene clean, caching deterministic, 307 tests green, OCR↔DB sha consistent) and the manual's constraints are mostly honoured. **The dominant blocker is delivery, not code: Tap2 is 1.1% OCR'd and this week's Kim Hán Nôm quota (219 calls) cannot finish it.** Several latent defects need fixing before the ≥95% gate is reachable; all 15 re-verified 2026-11-13 (see §13). (line numbers in defect citations were checked against the 2026-11-13 HEAD — see §1, §7, §10, §11, §13 and the Revision log)

---

## 1. Scope & files

**In scope (verified line by line):**

- `src/hannom/ocr/` — `base.py`, `kimhannom.py` (PyKim Hán Nôm API client), `local_paddle.py`, `local_vintern.py`, `quota.py`, `router.py`, `agreement.py`, `mock.py`, `__init__.py`
- `src/hannom/config.py` — `ApiSettings` (67-90), `OCRSettings` (22-28), `load_config` (141-228) — (re-verified 2026-11-13; 2026-11-12 revision had 63-86/23-29/121-215; `inventory_vi`/`inventory_misc` fields unchanged at 47-48; `ensemble=bool(ocr_raw.get("ensemble", True))` now at line **181** (was 168-170))
- `src/hannom/state.py` — `log_api_call`/`count_api_calls`/`api_calls_since`/`last_api_call`/`update_page`/`upsert_page`/`_row_to_page` (**352-382 / 384-390 / 402-406 / 392-400 / 276-315 / 224-274**, re-verified 2026-11-13; 2026-11-12 revision had 252-300/182-250 — verify-A hardening `4fd0af6` added ~+118 lines)
- `src/hannom/cli.py` — `ocr` command, `OCR_FOLDERS_BY_SCRIPT`, `filter_pages_by_script` (100-154); `src/hannom/orchestrator.py` — `stage_ocr`, `stage_labels`, `stage_clean` (110-275+; orchestrator.py **now 643 lines** (2026-11-12 revision: 571 — verify-A hardening `4fd0af6` added lines); the 2026-11-12 change-set added `"misc"` to the `stage_labels` folder tuple, still at ~line 169: `("ch","vi","intro","ref","toc","misc")` (re-verified 2026-11-13); `stage_labels` is **one-shot — not re-run after the 2026-11-13 verify-A re-bin**, which is why Tap3/Tap2 label bins are stale (§5, §13.4)); `src/hannom/labels.py` — `points_to_quad` (41-69), `line_to_box` (83-93, was 83-90); `src/hannom/clean.py` — `MASK`, `count_nom_chars` (17, 105-107, was 101-102); `src/hannom/models.py` — `OCRLine` (42-59) / `OCRResult` (63-72); `src/hannom/evaluate.py` (`MASK` handling ~274-308); `src/hannom/textdiff.py` — `scoreable_nom_chars` (603-612, unchanged 2026-11-13); `src/hannom/package.py` — zip secret scan now in `validate_source_zip` (**597-631**; `SOURCE_CONTAINS_SECRET_OR_STATE` 611-612; `KIMHANNOM_TOKEN` content scan 625-630) — the 2026-11-12 cite "package.py:541" (scan in `validate_book_package`) is stale (re-verified 2026-11-13)
- `configs/ocr.yaml`, `configs/project.yaml` (`api:` 24-35, `quality:` 45-55), `configs/books/T1_CamPhong_Tap1.yaml`, `T1_CamPhong_Tap2.yaml`, `T1_SuaLoiQuyen.yaml` — (the two Tap1/Tap3 YAMLs were modified 2026-11-12 with declarative `inventory_vi`/`inventory_misc` bin overrides; their `ocr:` sections are unchanged — the OCR-relevant verdicts above stand as revised 2026-11-12)
- `pyproject.toml` — pins (`requests==2.32.5`, `paddleocr==3.7.0`, `transformers==4.46.3`, torch via cu126 index per comment)

- The 2026-11-12 change-set itself is **out of this report's scope** except where it changes OCR-adjacent facts: `image_map` repair (`map_repair.py`), Tap1/Tap3 scope re-bin to `misc`/`vi` (`configs/books/T1_CamPhong_Tap1.yaml`, `T1_SuaLoiQuyen.yaml`, `layout.py`), `hannom.charstream` dịch-âm segmenter, align CSVs rebuilt (Tap1 727→823 / Tap3 341→380), labels regenerated (Tap1 consistent; Tap3 inconsistent). The OCR subsystem proper is byte-identical to what was audited before. (revised 2026-11-12)

**Cross-checked against:**

- `API_Kim_Han_Nom_guide.extracted.txt` (deleted from tree by 2026-11-13; the manual PDF at repo root was re-read directly by the 2026-11-13 verification pass — PyMuPDF, read-only)
- `Quy_đinh_đồ_án_v2.1.extracted.txt` (deleted from tree by 2026-11-13; the guideline PDF was re-read directly by the 2026-11-13 verification pass — sanction quotes on p.4 verified verbatim, §13.2)
- **NOT read:** `hannom_API.md`, `.env` (per ground rules; never printed; token never shown anywhere)

**Data inspected (read-only):** `data/ocr/<book>/*.json`, `data/ocr/api_cache/**`, `data/ocr/*/local_fallback/*`, `data/state.sqlite3` (`pages`, `api_calls`, `runs`; `runs` table is empty).

**Tests:** `python -m pytest -q` → **307 passed, 0 failed** (warnings only; re-run read-only 2026-11-13, exit 0, ~4.6 s — `test_verify_a_hardening.py` and `test_marker_map.py` are new since 2026-11-12's 282). (revised 2026-11-13)

---

## 2. Method & ground rules

- **READ-ONLY on the repo and `data/`.** No file outside `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-revise-C\` / `…\verify-replicate-C\` was written. The 2026-11-13 verification pass additionally re-measured with scratch in `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-replicate-C\` (`census.py` / PDF extraction / `extract_pdfs.py` / `ua_check.py` / `quota_probe.py` / `inspect_state.py` / `pytest*.log`; the earlier 2026-11-12 revision pass used `verify-revise-C\`, the original audit used `verify-C\`). (revised 2026-11-13)
- **Absolutely no network calls**; in particular **no requests to `kimhannom.fit.hcmus.edu.vn`** were made. Live-API behaviour is inferred only from repo artefacts (ledger, cache, OCR JSONs).
- **`.env` and `hannom_API.md` were not read**; no token material is reproduced anywhere in this report or in scratch. Token handling is verified structurally (grep for logging/printing; `package.py`'s secret scan).
- **No repo modifications** by either audit pass. (As of 2026-11-12: `git status --porcelain` showed only the 2026-11-12 change-set; nothing committed; `Tap2 book YAML is **not** modified. **Superseded 2026-11-13:** the 2026-11-13 verify-A work and the re-bin landed in `ed43470`/`4fd0af6`/`d515491`; HEAD `d515491` is clean; **Tap2 book YAML is modified** — `inventory_misc: [273,274,275]`, `vi_to_nom_offset: 549`; the three `*.extracted.txt` files are gone from the tree.) (revised 2026-11-13)
- Internet search was permitted but not needed; all compliance claims rest on the manual/guideline (re-verified 2026-11-13 verbatim from the PDFs: envelope string-`"000000"`, file_name-only classify, crop-only image-rec + "hiện chưa được mô tả", "(website)" limits, vertical default; guideline p.4 flow/limits/≥2-calls-per-image sentences) and repo evidence. (revised 2026-11-13)
- **Probe list actually executed** (see §10 for exact reproductions):
  - read-only sqlite queries (`mode=ro`): table list/counts, api_calls by endpoint×status, per-image duplicates, W45/W46 & daily usage, quota_week/quota_day labels, `pages` folder/status/engine/flags histogram, `ocr_confidence` NULL cross-tab against OCR JSONs
  - AST/text inspection + exact UA byte comparison (whitespace-flattened) between config and manual
  - scratch simulations against a *temporary* sqlite state: rolling-window quota edge cases, `_success_code` truth table (`"000000":T, 0:T, 1:F, "0":F, None:F, False:T` — **bool False accepted**), future-dated row blocking (`now+3h` → `retry_after=10860s`), `choose_consensus` confidence-free ranking, `sample_page_numbers`, `promote_review_flags`
  - OCR-JSON census: engine/warning/char-count distributions, band-retry evidence, `difficult` value census, sha↔state consistency (390/390 OK)
- **What was NOT verified:** the live API itself (health, business codes, error schema beyond the manual + cached evidence), Vintern/paddle inference on this machine's GPU, timing claims from comments, `Label.txt`/packaging stages (out of scope), `hannom_API.md` contents. See §12 Caveats.

---

## 3. Kim Hán Nôm client vs the manual — compliance table

Exact manual quotes come from the manual PDF at repo root (`Hướng dẫn sử dụng API Kim Hán Nôm.pdf`, version 2026-10-10, "Phiên bản: 2026-10-10" — extracted.txt deleted by 2026-11-13; re-read via PyMuPDF, read-only, 2026-11-13). "Guideline" quotes come from the guideline PDF (`Quy_định_đồ_án_v2.1.pdf`, v2.1, v2.1 2026-11-06) §4 "Chạy OCR hình ảnh" (p.4) / §5 (p.5).

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
| 3.10 | image-ocr data | Manual p.6 exemplar: data contains `result_file_name`, `result_ocr_text[]`, `result_bbox[]` (empty; the "có thể rỗng" wording is **p.10 ImageOcrData**, not p.6 — the p.6 example shows `"result_bbox": []` with no prose); p.6 exemplar + p.10 ImageOcrData | `kimhannom.py:379-434` handles nested `[points, [transcription, confidence]]` (**all 2284 live boxes**) **and** `details.details` "guideline shape" | ✅ dual-shape parser; all 183 live responses have both shapes present, all `result_ocr_text`↔`result_bbox` lengths equal |
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

- **550 calls total = 183 `image-upload` + 184 `structure-classification` + 183 `image-ocr`** (all recorded as `http_200`). One image (T1_SuaLoiQuyen p67) was classified twice (the 000108 failure + re-run), the other 182 images exactly once. Distinct images per endpoint: 183/183. (re-verified 2026-11-13 — exact match; `quota_day` 11-08=169 / 11-10=198 / 11-11=183, `quota_week` W45=169 / W46=381, **zero calls on 2026-11-12**, none since 2026-11-11T16:00:05Z; max 10 calls/minute; `note` NULL ×550; `response_path` NULL ×550; `token_id` NULL ×550 — no `business_code`/`outcome` column exists, see §7 D5)
- ⚠ **219 calls remain this week; Tap2 needs 264 Nôm pages.** Even with **`--no-classify`** (see §4.4), that is 264 pages × 2 calls (upload+ocr) = **528 calls > 219**. The API cannot finish Tap2 before the week rolls over (2026-11-16, W47). (re-verified 2026-11-13 — still 219 left, still W46-blocked, week overruns to 2026-11-15; 2026-11-12 AND 2026-11-13 saw zero API calls)
- `--wait-quota` (`cli.py:109`, `router.py` honours `project.api.wait_on_quota`) sleeps through quota windows instead of stopping the run; pairs with `--no-classify`.

### 4.2 Ledger semantics (verified by code read + scratch simulation)

- `record()` writes **every** attempt, including 4xx/5xx/429 (`kimhannom.py:239,245,250` — all record **before** the business-code check at `253-255`), and including HTTP-200 **with a non-`000000` code** (business failure). Empirically: **all 550 rows say `http_200`; at least one of them (p67, first classify at 05:41:32) was a business failure**. The ledger column is *HTTP status only*, not outcome.
- A transient 500/429 with `max_retries=3` burns **up to 3 ledger rows** per call.
- Rolling windows: `minute`/`hour`/`day`/`week` sliding windows computed from `api_calls_since(since)` (`quota.py:49-72`); `seconds_until_allowed` waits for the **oldest row in the window** to age out (`quota.py:74-88`) — correct sliding-window semantics (re-verified 2026-11-13: 2 calls with `per_minute=2`, oldest 55 s ago ⇒ wait = **4.99 s** ✓; `WINDOWS` = 60/3600/86400/604800 s).
- **Future-row bug (mechanism CONFIRMED 2026-11-13; original one-row-bricks-the-API claim NOT reproducible with default limits)**: `api_calls_since` is `WHERE requested_at >= ?` with **no upper bound** (state.py:402-406); a `requested_at = now + 3h` row is counted in **all four windows** (`snapshot()` = 1/1/1/1, verified) and `log_api_call` has no future-rejection (state.py:352-382 — `requested_at` is TEXT, no clamp). **However**, with default limits `check()` does **not** raise (1 < 25/50/200/600): the quoted `QuotaExceeded(retry_after=10860s)` reproduces only when a window is saturated by the future row alone (`per_minute=1` ⇒ measured `retry_after=10859.996s`); with default limits `seconds_until_allowed()` ≈ **10803 s** comes from the `min_delay` branch, not a window. The defect is **window-count inflation**, not unconditional bricking — still HIGH→**MEDIUM-HIGH** (blast radius: a single clock-skewed/forward row silently eats one slot in every window). The fix is unchanged: in `api_calls_since`/`seconds_until_allowed`, treat rows with `requested_at > now + tolerance` (e.g. 5 min) as absent (or warn loudly); validate `requested_at <= now` at insert. (revised 2026-11-13)
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

1. **51 API pages carry confidence-bearing lines in JSON but `ocr_confidence IS NULL` in state** — 50 SuaLoiQuyen kimhannom pages (**p0067–p0116 consecutive**, confirmed 2026-11-13) + Tap1 p147 (NOM_BLOCK_START page, 2026-11-08 19:24). Root cause: those pages were OCR'd by an older code revision / crashed before `update_page` committed confidence; `update_page` itself is unconditional, so some path in the 11-08 code passed/failed differently. Modern code (`router.py:366-375`) always sets `ocr_confidence` when ≥1 line has confidence. (re-verified 2026-11-13: cross-tab = **51** = 50 SLQ + Tap1 p0147 ✓; the 132 non-null kimhannom confidences exist (Tap1 129 + Tap2 3); vintern pages all NULL ✓) **Consequence:** any consumer reading state (review app, gates) sees these as unscored → they will be counted as "unverified", not as low-quality-but-scored.
2. **Band-retry pages: 40 total, only 36 have `BAND_RETRY_AFTER_FULLPAGE_FAILURE` in page `review_flags`.** The **4 SuaLoiQuyen pages (0016/0032/0040/0056)** carry only `FOOTER_TITLE_REMOVED` (their JSONs were written 2026-11-09 00:39 by a run that predates the router fix *or* bypass propagation); cache-hit re-runs never re-promote warnings. Tap1's 36 pages (refreshed 2026-11-10/11) are correctly flagged ✓ — re-verified 2026-11-13: exactly 35 `vi` (pages 0032–0139, incl. **0011**) + 1 `misc` **p011** (flags `["BAND_RETRY_AFTER_FULLPAGE_FAILURE","BIN_OVERRIDE_MISC","LABEL_EMPTY_OCR"]`) ✓. The 2026-11-12 `stage_labels` re-run did **not** re-run OCR and did **not** re-promote BAND_RETRY flags; the 2026-11-13 verify-A re-bin did **not** re-promote either. **Corroborating promotion gap found 2026-11-13:** Tap1 **p0147** carries `OCR_ENGINE_DISAGREE` in its OCR JSON (sim 0.11) but is **absent from `pages.review_flags`** (state shows 5, JSONs 6 — Tap1 212/276, Tap2 277/409/540). Same failure mode as the 4 SLQ band-retry pages: flags never re-sync on cache-hit paths. (revised 2026-11-13)
3. **`difficult` is dead-weight** — `False` ×2284 in every API line (cached `details.details` too). The guideline's `difficult` flag currently carries zero triage information. Do not use it for review ordering.
4. **All 390 OCR JSONs are consistent with the pages table on `(book_id, page_no, image_sha256, status='ocr_done')`** — 0 mismatches. `ocr_done`=390 == 390 JSON files ✓.
5. **All kimhannom JSONs predate the current client** — no `upload_scale`/`classified` keys in `raw` (they were added in the 2026-11-11 upscale change). (re-verified 2026-11-13: top-level JSON keys are `engine`/`cached`/`book_id`/`page_no`/`image_name`/`image_sha256`/`lines[]`/`raw{}`/`warnings[]`; routing telemetry sits at `raw.routing.{api_mode, api_called, engines_requested, engines_unavailable, api_sample_pages}` — e.g. `0005.json` = vintern_1b_v2, `0147.json` = kimhannom + `api_mode=sample_then_low_confidence`) After any client change, re-OCR with `--force` or re-sync; the response cache (keyed by image sha) keeps re-evaluation free.
6. **local_fallback cruft**: SLQ `local_fallback/{0016,0032,0040,0056}.json` are stale, **text-identical to the main files** but not byte/JSON identical (main files carry `raw.routing.*`; fallback `raw` = `{band_retry, canonical_path, local_draft, page_size, prompt, re_ran_at, reason, seconds}` with **no `routing` key**, mtimes 2026-11-09 23:00–23:01); plus `DRAFT-2026-11-09.md` and `NOTE.md` (NOTE.md documents the 2026-11-08 paddle hourly-quota trip). **Tap1's `local_fallback/` is EMPTY** (created 2026-11-10, 0 files); Tap2 has none. No nom page was ever served from local fallback. Delete in a cleanup pass. (revised 2026-11-13)
7. `pages.ocr_engine` counts: kimhannom 183 / vintern 207 — consistent with the JSON census ✓. (re-verified 2026-11-13 — exact)
8. `runs` table: empty. No formal run ledger exists; `api_calls` + OCR files are the only provenance trail. (re-verified 2026-11-13 — `runs` still 0; `reviews` 0; `artifacts` 18 — 6 stages × 3 books: `align/evaluation/intake/layout×2/pages` per book.)
9. **NEW (2026-11-13): every cached `structure-classification` payload embeds a full OCR response incl. `result_image_base64`** (~500 KB avg; classify files ≈ **92.7 MB** vs image-ocr ≈ 4.6 MB). The report's "classify `data` = `{ocr_id, lang_type, reading_direction, is_sino_nom}`" is not what the cache actually stores — the payload redacted nothing. Unused downstream (no code reads `result_image_base64`), but any future `source.zip`/upload sweep must know `data/ocr/api_cache/` contains full page images base64-encoded. (re-verified 2026-11-13; see §13.5, D21.)
10. **NEW (2026-11-13): `NOM_UNENCODABLE_REPLACED` (167) is a state/clean flag only.** OCR JSONs contain **neither `〓` (U+3013) nor `[MASK]` nor PUA-replaced text** — the pipeline ships the PUA code points as-is and records `flags:["NOM_UNENCODABLE_REPLACED"]` + `replacements:{…}` in `data/clean/*.json`. Reviewers must not expect `〓` in any output text; sample the flagged *pages*, not the glyphs (see §13.6, R6). (re-verified 2026-11-13.)

**Also (non-skew but related):** 907/950 pages have non-empty `review_flags` as of 2026-11-13 (Tap1 276, Tap2 542, SuaLoiQuyen **89** — was 902 vs the 2026-11-12 baseline; +5 from the 11-13 re-bin); `LABEL_EMPTY_OCR` unchanged at **808** (Tap1 269, Tap2 537, SuaLoiQuyen 2); all 36 Tap1 band-retry pages also carry `LABEL_EMPTY_OCR`. The 2026-11-12 `stage_labels` re-run regenerated labels for all bins incl. `misc` (orchestrator `stage_labels` writes the `misc` bin; folder tuple at ~line 169 includes `"misc"`). **Tap1 labels were fully rebuilt and are consistent** (Tap1 `misc/Label.txt` covers all 16 DB-misc pages). **Tap3 labels remain stale** — `data/labels/T1_SuaLoiQuyen/misc/Label.txt` still covers only `001`/`064` (empty labels) vs 12 DB-misc pages; the 10 ocr_done misc pages (002, 003, 005, 007, 008, 009, 062, 063, 117, 118) are **unlabeled anywhere** (8 of them sit in the obsolete `intro/`/`toc/` bins from the pre-re-bin layout). **NEW 2026-11-13 — Tap2 is stale too**: `data/labels/T1_CamPhong_Tap2/` has no `misc` bin at all (ch 264 / vi 267 / intro 2 / toc 10 — vi 267 ≠ 264 DB pages after the re-bin moved pages) while Tap2's `273/274/275` were re-binned to `misc` (with 275 OCR'd). **Root cause (§13.4): the 2026-11-13 verify-A re-bin (`updated_at` 2026-11-13T01:57–02:00) moved already-OCR'd pages into `misc` *after* the last `stage_labels` run (2026-11-12 19:35/19:36); labels are one-shot and nothing invalidates/regenerates them on re-bin.** That is a labeling-stage defect, not an OCR defect, but it means those misc pages cannot be PPOCRLabel-verified even though they were OCR'd. (revised 2026-11-13)

---

## 6. Verified working areas

- **Caching determinism**: API response cache keyed by `sha256(endpoint|image|params)` (183 upload names cached; 366 payload files = 183 classify + 183 image-ocr, all `code="000000"`); re-runs are quota-free; upload names cached per image sha (`uploads/<sha2>/<sha>.json`); enlarged (`upscale`) copy deterministically named `<origsha>_xN.jpg`, atomic `tmp→replace`, boxes scaled back uniformly LANCZOS factor (`kimhannom.py:123-143, 529-532`).
- **`local_fallback/` never shadows API files**; `load_result` prefers `data/ocr/<book>/<page>.json` over `local_fallback/…json` (`router.py:139-143`); nom pages always attempted via API first under `api_first` (`router.py:306-328`); local results land in `local_fallback/` and never overwrite API-handled files (`save_result(local_fallback=True)`, `router.py:168-184`).
- **`--only` over-run guard** (`cli.py:106-121` + `148-154`): `--only nom|qn` filters folders via `OCR_FOLDERS_BY_SCRIPT = {"nom": {"ch"}, "qn": {"vi","intro","toc","ref"}}`; empty filter **skips the book** ("no nom pages (run classify/map first?)") instead of widening to everything; invalid `--only` values rejected (`typer.BadParameter`). The guard is tested (`tests/test_ocr_options.py`).
- **UA hygiene**: project UA == manual default (byte-exact); Bearer never logged/printed/cached; `package.py`'s zip scan would catch a committed token; `.env` git-ignored. **No token exposure found anywhere.**
- **Engine instance caching** (`router.py:90-98`): one instance per engine per process (vintern ~35-120 s/page — without caching this would be catastrophic); paddle models lazy-loaded on first `recognize_page`.
- **Consensus boxed-preference** (`agreement.py:50-75`): `with_boxes` pool preferred (PPOCRLabel needs 4-point boxes); highest mean-line-confidence wins; no-confidence results (Vintern) ranked by `len(text)/10000.0` — monotonic, conservative, and harmless because QN is never mixed with API results; `BBOX_MISSING` raised when no boxed line exists; disagreement emits `OCR_ENGINE_DISAGREE:<a>:<b>:<sim>`; deterministic.
- **Blank/misc excluded from OCR targets; intro/toc/ref included and OCR'd via vintern** (`router.py:386` targets `{"ch","vi","intro","toc","ref"}` — target set unchanged 2026-11-13; `run_page` raises for `blank|misc`, `:245`; `OCR_FOLDERS_BY_SCRIPT` agrees). **Tap2's 264 vi + 2 intro + 9 toc = 275 QN pages** (DB 2026-11-13; was 279 pre-re-bin — the 11-13 re-bin moved 273/274/275 to `misc`; `inventory_misc: [273,274,275]`) are destined for vintern — correctly planned, not yet run in Tap2. Tap1/Tap3 front matter was re-binned by the 2026-11-12 change-set to `vi` (Tap1 PDF 13–20 = Nôm PDF 276–269 via the parens cross-reference; they were already OCR'd) or `misc` (Tap1 5, 7–11, 143, 144, 277–282; Tap3 2, 3, 5, 7, 8, 9, 62, 63, 117, 118) — Tap1/Tap3 now have **zero** intro/toc pages and **260 / 100** in-target pages respectively, all ocr_done. **32 misc pages are excluded from future OCR targets** (Tap1 16, Tap3 12, **Tap2 4** — new after the 11-13 re-bin), of which **25** are already ocr_done (Tap1 14, Tap3 10, Tap2 p0275). Total targets **899** (260+100+539). (revised 2026-11-13)
- **QN never goes near the API** (`quoc_ngu: [vintern_1b_v2]`; Kim Hán Nôm is Hán/Nôm-only; the routing marks `second_opinion: none`); **no QN page was ever sent to the API** — verified in the ledger (all 183 calls are ch/ pages; per-image p67 etc. are ch).
- **Single full-page box per QN page** (guideline: "đánh 1 box cho toàn trang") — emitted (`local_vintern.py:232-244`), `confidence=None` (never fabricated) ✓.
- **Pipeline consistency**: 390/390 OCR JSONs match `pages(book_id,page_no,sha256,status='ocr_done')` ✓ (re-verified 2026-11-13 via top-level `image_sha256` ↔ `pages.sha256`; engines agree; 0 mismatches); every OCR file parses as JSON ✓; engines match `pages.ocr_engine` ✓.
- **PPOCRLabel format path**: `points_to_quad` normalises polys/flat/dicts → 4 points; `points_to_quad`+`line_to_box` produce 4-point `points` arrays + `difficult` passthrough — compatible with PPOCRLabel/Label.txt (`labels.py:41-90`).
- **Retry/backoff**: 429/5xx retried ≤3 with `min(60, 2**n)` backoff; 4xx non-retryable ("Retrying a 401 or a bad enum only burns quota and hides the bug"); `ApiBusinessError` raised after `.json()` parse + code check, **never retried** (deterministic) — except the one deliberate re-upload in `recognize_page`.
- **Tests green**: `python -m pytest -q` → **307 passed, 0 failed** (re-run read-only 2026-11-13; exit 0, ~4.6 s). (revised 2026-11-13)

---

## 7. Defects ranked (file:line)

### D1 — `_success_code` accepts `0` and `False` as success — `src/hannom/ocr/kimhannom.py:45-48` (re-verified + truth table reproduced 2026-11-13)
```python
def _success_code(value: Any) -> bool:
    # The manual documents the string "000000"; accept the integer zero some
    # deployments return, but do not guess arbitrary success values.
    return value == "000000" or value == 0
```
`"000000"==0` is False; `value == 0` is True for `0` and for **`False`** (verified truth table: `"000000":True, 0:True, 1:False, "0":False, None:False, False:True`). The manual documents **only** string `"000000"` (manual p.2, ResponseEnvelope: `code: string`); the comment claims "some deployments return the integer zero" — **no evidence anywhere in the repo, no test covers it** (`tests/` has zero `_success_code` assertions). A `code:false` response would be cached as a valid OCR result. **Fix:** `return value == "000000"` (or raise `KimHanNomError` with the raw envelope); add a unit test asserting `0`, `False`, `1`, `"0"`, `None`, `"000001"` all fail. **Severity: HIGH** (fail-open correctness bug on the API's only contract; never observed on the wire, but one-line latent corruption path).

### D2 — Full-page `image-rec` fallback replaces API texts/boxes via an undocumented response shape — `kimhannom.py:491-513` (re-verified 2026-11-13; `IMAGE_REC_FALLBACK_NO_IMPROVEMENT` confirmed absent from src/tests/tools)
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

### D4 — Code `000108`: classify payload exceeds the manual; verified only via the p67 incident — `kimhannom.py:301-317` (re-verified 2026-11-13 — evidence now end-to-end; sanction re-verified verbatim from the guideline PDF p.4)
Manual documents **only** `file_name` for `structure-classification` (p.4, example body `{"file_name": "tempd561…"}` — re-verified 2026-11-13); the client adds `ocr_id:0, lang_type:0, reading_direction:0` citing the v2.1 guideline (p.4, verbatim: *"image-upload →structure-classification (đặt ocr_id, lang_type, reading_direction bằng 0 để server tự nhận diện) →image-ocr"* — **re-verified directly from the PDF 2026-11-13**). Evidence this is real and required, now end-to-end (2026-11-13): the 2026-11-08 pair (two `structure-classification` rows 20 s apart for image `84d3a98c…` = T1_SuaLoiQuyen p67, call_ids 2 & 3); the **first** call (05:41:32.956410) left **no cache entry**; the **second** (05:41:52.653391) is followed by a matching cache file (`abbebecfe0722582c…`, `saved_at` = 2026-11-08T05:41:52.669308, **+16 ms**, `raw.code == "000000"`), consistent with `_save_cache` running only after the business-code check passes at `kimhannom.py:262`. `image-ocr` follows at 05:41:58.497. All 550 `note` values NULL; **no `business_code`/`outcome`/success column exists in `api_calls`** — the business failure is recorded as `http_200` with no distinguishing signal. Compliance verdict: **compliant with the guideline, exceedance of the manual** — the manual is stale (2026-10-10) while v2.1 (2026-11-06) is newer and prescriptive; the fields are constant and were accepted on 183/183 subsequent calls. **Keep the fields; document the deviation** (it is commented in code — extend the comment to quote the guideline); do not extend the undocumented-field pattern to anything else. **Severity: MEDIUM** (contract clarity; risk is a future server-behaviour change, not a current bug). (evidence re-verified end-to-end 2026-11-13)

### D5 — Ledger records HTTP status only; business failures and 4xx/5xx count as `http_*` success — `kimhannom.py:236-255`, `quota.py:107-123`
```python
# _request(), HTTP path:
self.ledger.record(endpoint, image_sha256, f"http_{status}")  # line ~250
if not _success_code(raw.get("code")):                          # line ~253
    raise ApiBusinessError(f"{endpoint}: {raw.get('code')}: {message}")
```
The business-code check happens **after** `record()`. All 550 rows say `http_200`, yet ≥1 call (p67) was an error — re-verified 2026-11-13 (550/550 `http_200`; `note` NULL ×550; **no `business_code`/`outcome`/`success` column in `api_calls`** — schema re-checked). Consequences: (i) operators auditing quota see false "all success"; (ii) a silent auth-model/enum regression would burn full pages of quota as "successful" calls while OCRing with nothing (except — see D8 — the local fallback); (iii) no way to distinguish "server at capacity" from "fine"; (iv) the `000108` evidence for D4 rests on inference alone because there is no business-code column to check. **Fix:** record `status=http_{status}` and **also** `business_code`/`outcome` (or overload `note`): e.g. `note=f"code={raw.get('code')}"`. Decide & document whether failed attempts count toward limits (current: yes — conservative; keep, but make it explicit). **Severity: HIGH** (observability/trust of the quota ledger). (evidence re-verified 2026-11-13)

### D6 — Future-dated rows block every quota window — `quota.py:80-88`
```python
since = now - timedelta(seconds=seconds)
rows = self.state.api_calls_since(since)   # requested_at >= since — no upper bound
...
oldest = datetime.fromisoformat(rows[0]["requested_at"])
waits.append(max(0.0, (oldest + timedelta(seconds=seconds) - now).total_seconds()))
```
Mechanism CONFIRMED 2026-11-13 (scratch simulation on a fresh temp DB): a `requested_at = now + 3h` row is counted in **all four windows** (`snapshot()` = 1/1/1/1); `api_calls_since` is `WHERE requested_at >= ?` with **no upper bound** (state.py:402-406) and `log_api_call` applies **no future-rejection** (state.py:352-382). **However the literal `check()`-raises claim does NOT reproduce with default limits** (1 < 25/50/200/600 ⇒ no exception; `seconds_until_allowed()` ≈ 10803 s via the `min_delay` branch, not a window). The quoted `QuotaExceeded(retry_after=10860s)` reproduces only with `per_minute=1` (measured 10859.996 s). So this is **window-count inflation**, not unconditional bricking. **Fix:** in `api_calls_since`/`seconds_until_allowed`, treat rows with `requested_at > now + tolerance` (e.g. 5 min) as absent (or warn loudly); validate `requested_at <= now` at insert. **Severity: HIGH → MEDIUM-HIGH** (blast radius narrower than claimed; still fail-blinds every window with one clock-skewed row). (revised 2026-11-13)

### D7 — Warning non-propagation: silent-degradation paths leave pages unflagged — `router.py:24-41`, `claims for Tap1 36/40 proven` (Tap1 36 pages = 35 vi + 1 misc/p011 as of 2026-11-12; the SuaLoiQuyen 4 remain un-re-promoted) (revised 2026-11-12)
`PROPAGATED_WARNING_CODES = {OCR_ENGINE_DISAGREE, BBOX_MISSING, OCR_EMPTY, BBOX_INVALID, OCR_TEXT_BBOX_COUNT_MISMATCH, BAND_RETRY_AFTER_FULLPAGE_FAILURE}`. **Missing:** `ENGINE_UNAVAILABLE` (incl. broken-token whole-book local fallback), `IMAGE_REC_FALLBACK`, `API_CLASSIFIED_NOT_SINO_NOM`, `OCR_ROUTING_UNKNOWN_MODE`, `OCR_LINE_WITHOUT_BBOX`. Proven empirically: 36 Tap1 band-retry pages have `BAND_RETRY_AFTER_FULLPAGE_FAILURE` in `pages.review_flags` ✓; the **4 SuaLoiQuyen band-retry pages (0016/0032/0040/0056) carry only `FOOTER_TITLE_REMOVED`** because they were OCR'd before the router carried the promotion (mtimes 2026-11-09 00:39; only JSONs, flags not re-synced) — and **cache-hit runs never re-promote**. **Fresh corroboration 2026-11-13: Tap1 p0147 carries `OCR_ENGINE_DISAGREE` (sim 0.11) in its OCR JSON but is absent from `pages.review_flags`** (state shows 5 DISAGREE — Tap1 212/276, Tap2 277/409/540 — vs 6 in JSONs). `load_result` (139-166) serves cache with no flag union; only `run_page`'s fresh-run path (router.py:367) calls `promote_review_flags`. **Fix:** (i) add the missing codes to `PROPAGATED_WARNING_CODES`; (ii) re-promote on `load_result` (or a one-time migration): for every cached `OCRResult`, union `promote_review_flags(result.warnings)` into `pages.review_flags`. **Severity: HIGH** (gate triage blindness) / the promotion mechanism itself is otherwise correct. (evidence re-verified 2026-11-13)

### D8 — Broken/absent API credentials silently OCR the nom corpus with paddle — `router.py:306-335`, `kimihannom.py:78-85, 450-451`
`is_available()` = token set + `requests` importable. If the token expires mid-run: every nom page `is_available()→False` → `unavailable=["kimhannom: unavailable"]` → `results` empty → **all pages fall back to paddle**, each page gets `ENGINE_UNAVAILABLE:kimhannom: unavailable` recorded as a **warning only** (not propagated, D7). (precision fix 2026-11-13: the code emits `ENGINE_UNAVAILABLE`, not `OCR_UNAVAILABLE`; the reason string is bare — it cannot distinguish quota-exhaustion vs missing token vs import failure, see D20.) Paddle for Nôm: similarity **0.02–0.25** vs the API (six stale 2026-11-08 `sample_then_low_confidence` DISAGREE files — Tap1 0147(0.11)/0212(0.13)/0276(0.25), Tap2 0277(0.15)/0409(0.02)/0540(0.11); engine delta across all six = `paddleocr_vl` vs `kimhannom`). The whole book would silently ship garbage. `unknown_mode` assignment handles typo'd `api_mode` but not this. **Fix:** startup auth self-check (cheap: call classify on a tiny/canary image once per run, or verify token reachability first page and abort loudly after N consecutive `ENGINE_UNAVAILABLE`s). At minimum propagate `ENGINE_UNAVAILABLE` into `review_flags`. **Severity: HIGH** (integrity; unobservable without the fix). (evidence re-verified 2026-11-13)

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

### D13 — `difficult` carries zero signal; `ensemble`/`max_pages_per_api_batch` dead config — `local_vintern.py`/`kimhannom.py:484-536`; all book YAMLs `ensemble: true`; `ocr.yaml:41`; `config.py:26,181` (re-verified 2026-11-13; `ensemble=bool(ocr_raw.get("ensemble", True))` is at line **181** after the verify-A hardening; grep confirms repo-wide zero readers)
All 2284 API `details.details.difficult` values are `False`; paddle doesn't emit one either. **Stop using `difficult` for triage.** `ensemble: true` (all 3 book YAMLs) is parsed into `OCRSettings.ensemble` and **never read anywhere** — remove or wire it. `max_pages_per_api_batch: 12` (ocr.yaml:41) unused (string absent from `src/`). `OCRSettings.sample_pages` is used for `sample_then_low_confidence` **decisions**, and also evaluated for `routing.api_sample_pages` metadata in **every** mode (router.py:220, 362, 394) — the "sample mode only" claim in the 2026-11-12 revision was imprecise (re-verified 2026-11-13). **Severity: LOW** (operator confusion).

### D14 — `validate_ledger_timestamp` dead; `QuotaSnapshot.to_dict` dead; `token_id` unused — `quota.py:125-126,31-39`, `kimhannom.py:72` — **Severity: LOW**.

### D15 — Website-vs-API quota scope — `quota.py:1-5` — the manual labels its limits "(website)"; code applies them to the API. The docstring enforces the numbers and documents the local-enforcement choice, but **nowhere mentions the "(website)" qualifier** — that reasoning lives only in `docs/decisions.md`/this report. Conclusion stands **keep, but document** (guideline v2.1 p.4 applies the same numbers under *"Khi gọi trực tiếp qua API … Giới hạn trên website"*, so it is also the guideline's own reading; quote verified verbatim 2026-11-13). **Severity: LOW.** (revised 2026-11-13)

### D16 (NEW 2026-11-13) — `load_result`/`run_page` cache never revalidates `image_sha256` — `router.py:139-166`, `249-250` — **Severity: MEDIUM**
Cached OCR JSONs are keyed only by book/page identity (`data/ocr/<book>/<page>.json`), never compared against the current page's `sha256` (`image_sha256` is stored top-level in the JSON but unused for validation). After any re-extraction/rotation, the pipeline silently labels/scores **last week's** OCR. The ledger does the right thing (content-sha keys); the per-page result cache does not. **Fix:** in `load_result`, reject/warn when `page.sha256 != result.image_sha256` (fallback to re-OCR or loud review flag). (found 2026-11-13)

### D17 (NEW 2026-11-13) — Unguarded `json.loads` on cache/OCR files crashes the stage — `kimhannom.py:161-171` (`_load_cache`), `router.py:145` (`load_result`) — **Severity: LOW-MEDIUM**
A truncated/corrupt `data/ocr/api_cache/*.json` or `data/ocr/<book>/*.json` raises out of `recognize_page`/`load_result` instead of refetching or flagging. Contrast `_load_uploaded_name` (191-194) which swallows `OSError`/`JSONDecodeError`. **Fix:** catch, warn (`API_CACHE_CORRUPT`), treat as cache-miss. (found 2026-11-13)

### D18 (NEW 2026-11-13) — `ocr_id == 3` with `needs_rec` is fully silent — `kimhannom.py:499` — **Severity: LOW**
When `needs_rec` is true but the image-rec fallback is skipped (`ocr_id == 3`), not even an informational warning is recorded; only the underlying `OCR_TEXT_BBOX_COUNT_MISMATCH` fires later. Deliberate per guideline (image-rec only for crops), but invisible in triage data. **Fix:** record `OCR_REC_SKIPPED_SCENE` at minimum. (found 2026-11-13)

### D19 (NEW 2026-11-13) — `difficult` length-mismatch branch silently drops the field — `kimhannom.py:489-490` — **Severity: LOW**
If `len(details.details) != len(texts)`, `difficulty` stays `None` with no warning (consistent with D13 dead-weight, but a silent branch, not a logged one). **Fix:** log `DIFFICULT_LENGTH_MISMATCH` when it triggers (currently never observed — all 2284 lengths match; the branch exists for future drift). (found 2026-11-13)

### D20 (NEW 2026-11-13) — `ENGINE_UNAVAILABLE` reason is bare — `router.py:316, 350-351` — **Severity: LOW**
`f"{name}: unavailable"` records no cause, so `ENGINE_UNAVAILABLE:kimhannom: unavailable` cannot distinguish **quota-exhaustion** vs **missing token** vs **import error** without opening the run log. Worsens D8's triage blindness. **Fix:** carry the reason (`quota`/`no_token`/`import_error`) into the warning. (found 2026-11-13)

### D21 (NEW 2026-11-13) — API response cache embeds full page images (`result_image_base64`) — `kimhannom.py:161-182` (`_load_cache`/`_save_cache` save whole `ApiResponse`); `data/ocr/api_cache/` — **Severity: LOW-MEDIUM (data hygiene, packaging risk)**
Every cached `structure-classification` payload embeds the server's full result incl. `result_image_base64` (~500 KB avg; classify cache ≈ **92.7 MB** vs image-ocr ≈ 4.6 MB; `uploads/` holds another 183 `file_name` JSONs). Nothing reads the base64 downstream; it is redundant with the image-ocr payloads and with the page images themselves. It never leaves the machine, but any future sweep (`source.zip`, repo share, bug-report dump) must know it is there. **Fix:** strip `result_image_base64` (and `result_file_name`) from cached payloads at save time, or exclude `data/` from any archive (already the case); document in `USER_GUIDE.md`. (found 2026-11-13)

---

## 8. Empirical counts (re-measured 2026-11-13 at HEAD `d515491` — DB `mode=ro`, mtime 2026-11-13 09:22:34; JSONs last written 2026-11-08…11)

| Metric | Value |
|---|---|
| Books | 3 (`T1_CamPhong_Tap1` 282 pp, `T1_CamPhong_Tap2` 550 pp, `T1_SuaLoiQuyen` 118 pp) |
| Pages total / classified / ocr_done | **950 / 560 / 390** |
| OCR targets `{ch,vi,intro,toc,ref}` | 260 + **539** + 100 = **899** (blank **19**, **misc 32 excluded** — Tap1 16 + Tap3 12 + **Tap2 4** after the 11-13 re-bin; Tap1/Tap3 intro/toc emptied by the 2026-11-12 re-bin; Tap1 PDF 13–20 are now `vi` and already OCR'd) |
| **OCR done** | **Tap1 260/260 ✓, SuaLoiQuyen 100/100 ✓, Tap2 6/539 (1.1%)** — Tap1/Tap3/Tap2 also hold 14 + 10 + 1 already-OCR'd `misc` pages outside the future target set (**25** misc ocr_done total); misc pages remaining classified-only (**7**): Tap1 p001/p145, SuaLoiQuyen p001/p064, Tap2 p001/p273/p274 |
| OCR JSON files | 390 (all parse; 390/390 sha-consistent with `pages`) |
| Engines in files | vintern_1b_v2 **207**, kimhannom **183** |
| `api_calls` rows | **550** = 183 `image-upload` + **184** `structure-classification` + 183 `image-ocr`; **all recorded `http_200`** |
| Distinct images per endpoint | 183 / 183 (p67 classified twice → 184) |
| Weekly usage | W45=169, **W46=381/600 (219 left; zero calls on 2026-11-12)** |
| Daily usage | 11-10 **198/200**, 11-11 183/200 |
| `data/ocr/api_cache` | 366 payloads (183 classify + 183 image-ocr; all `raw.code="000000"`, all `details.details` present for image-ocr) + 183 `uploads/*.json` file_names; **classify payloads embed a redundant full OCR result incl. `result_image_base64` (≈92.7 MB total — see D21)** |
| Warnings across JSONs | `BAND_RETRY_AFTER_FULLPAGE_FAILURE` **40** (36 Tap1 + 4 SuaLoiQuyen), `OCR_ENGINE_DISAGREE` **6** (all stale `sample_then_low_confidence` mode, sim 0.02–0.25) |
| Warnings present: `ENGINE_UNAVAILABLE` / `IMAGE_REC_FALLBACK` / `BBOX_INVALID` / `OCR_EMPTY` / `BBOX_MISSING` / `API_CLASSIFIED_NOT_SINO_NOM` | **0 / 0 / 0 / 0 / 0 / 0** |
| Lines in API results | **2284**; `difficult=False` ×2284; `result_bbox` nested shape ×2284 |
| Lines with `confidence<0.5` | **150** across **93 pages** (91 Tap1 + 2 Tap2) |
| Mean line confidence (API pages) | ≈0.907 (Tap1) / **0.919 (all 183; 2026-11-13 re-measurement — 0.860 is Tap2-only, not "all")** / 0.971 (SuaLoiQuyen) |
| Pages with `<100` chars OCR text | **14** — Tap1 0005(29,misc — was intro) 0009(5,misc — was toc) 0013(55,vi — was intro) 0083(12,vi) 0271(84,ch) 0275(29,ch) 0276(15,ch, DISAGREE 0.25); Tap2 0275(19, **misc** after the 11-13 re-bin — was vi); SuaLoiQuyen 0002(14,misc) 0003(17,misc) 0005(57,misc) 0009(15,misc) 0060(64,vi) 0067(13,ch) |
| Pages `<10` chars | 1 (Tap1 0009, misc — was toc; `LABEL_EMPTY_OCR` + `TOC_LIKELY_FRONT` flags) |
| Pages `<50` chars Nôm (ch) | **3** (Tap1 0275(29), 0276(15), SuaLoiQuyen 0067(13)) |
| State pages with non-empty `review_flags` | **907/950** (Tap1 276, Tap2 **542**, SuaLoiQuyen **89** — drift +5 vs 2026-11-12 baseline; LABEL_EMPTY_OCR **808** — Tap1 269, Tap2 537, SuaLoiQuyen 2, labeling stage; BAND_RETRY 36 (Tap1 35 vi + 1 misc/p011); DISAGREE **5 in state vs 6 in JSONs** (p0147 unpromoted — see D7); NOM_UNENCODABLE_REPLACED 167; PAGE_MARK_REMOVED 104; BIN_OVERRIDE_MISC 29; FOOTER_TITLE_REMOVED 17 (all Tap3)) |
| `ocr_confidence` NULL in state despite confidences in JSON | **51 API pages** (50 SuaLoiQuyen + Tap1 p147) |
| Tap2 OCR'd pages | 6 = **0009 & 0142 (vi) + 0275 (misc, after 11-13 re-bin) + 0277/0409/0540 (ch)** — report's "3 vi" was wrong; Tap2 `ocr_confidence` for the 3 kimhannom pages = 0.610 / 0.858 / 0.842 |
| `local_fallback/` files | 4 stale duplicates (SuaLoiQuyen) + DRAFT/NOTE `.md` |
| pytest | **307 passed / 0 failed** (re-run 2026-11-13; was 282 on 2026-11-12) |

**Reading the counts:** Tap1 and SuaLoiQuyen are done and consistent; Tap2 is the gap. All silent-failure signatures (0 `OCR_EMPTY`, 0 `BBOX_*`) are clean; the only live risks are the 40 band-retry pages, the 51 state-skew pages, and the Tap3/Tap2 **label bins invalidated by the 2026-11-13 re-bin** (§5), plus **Tap2** itself.

**Repo-state note (revised 2026-11-13):** both books were re-aligned on 2026-11-12 (image_map repair; `charalign` dịch-âm segmenter for Tap1 & Tap3, Tap2 stays `cosegment`; align CSVs rebuilt: Tap1 **823 rows** / Tap3 **380 rows**). On 2026-11-13 the verify-A hardening (`4fd0af6`) and the marker-formula maps (`d515491`, `vi = marker + offset`, Tap1 130/130, Tap2 264/264, Tap3 50/50 verified) landed; the Tap2 book YAML **is now modified** (`inventory_misc: [273,274,275]`, `vi_to_nom_offset: 549`). Metrics re-measured 2026-11-13 09:21–09:22 (`passed:false` for all three books): Tap1 `similarity 89.9646` / `coverage_ratio 0.4629` / `UNVERIFIED_RATIO_HIGH 0.5358` / red 709 / denominator 7065 / rows 823; Tap3 (SuaLoiQuyen) `93.7385` / `0.6` / `0.4` / red 205 / denominator 3274 / rows 380; Tap2 `85.7143` / `0.1333` / `0.3333` null ratio / rows 15 / scored 2 (gates FAIL — Tap2's coverage is the binding constraint). OCR freshness itself is unchanged — no OCR JSON, `api_calls` row, or `ocr_confidence` was touched by the 2026-11-13 work (last api_calls = 2026-11-11T16:00:05Z; **zero calls on 2026-11-12 and 2026-11-13**). Tap3 `misc/Label.txt` remains stale as noted in §5 — now also Tap2 (no `misc` bin). The 2026-11-13 re-bin happened **after** the 2026-11-12 19:35/19:36 `stage_labels` re-run (§13.4). Tap1 labels remain consistent.

---

## 9. Prioritized recommendations R1-R10

Impact on the ≥95% gate is annotated per item.

- **R1 — Run Vintern over Tap2's remaining QN pages now** (`python -m hannom.cli ocr --only qn`, or the full `--only` matrix): **275 pages (264 vi + 2 intro + 9 toc)** × ~35-120 s ≈ **3-9 h GPU**. Zero API quota. (Tap2-only: Tap1/Tap3 front matter is already OCR'd or sits in `misc` and is outside future targets; counts re-verified 2026-11-13, was 279.)
  *Gate impact:* makes Tap2's QN half measurable at all; expect the same 25% band-retry incidence as Tap1 → those pages join the R6 review queue.

- **R2 — Block the API for Tap2 Nôm until W47 (2026-11-16), then run with `--no-classify`:**
  `python -m hannom.cli ocr --only nom --no-classify --wait-quota`
  (Per §4.4, classify is lossless to skip: all 183 prior responses are `ocr_id=1, dir=1`; saves **528** calls. `--only nom` prevents QN pages from consuming API. `--wait-quota` prevents a mid-week abort.)
  *Gate impact:* 264/264 Nôm pages OCR'd with API quality; without it, Tap2 Nôm is impossible this week (219 calls left). **Highest-value change available.**

- **R3 — Re-sync state before scoring (EXTENDED 2026-11-13):** (i) set `pages.ocr_confidence` from the 51 JSONs (50 SLQ **p0067–p0116** + Tap1 **p0147**); (ii) fix D7 **first** (add missing codes to `PROPAGATED_WARNING_CODES`), then re-promote on `load_result`: union `promote_review_flags(result.warnings)` into `pages.review_flags` for ALL 390 cached results — this re-flags Tap1 p0147 (`OCR_ENGINE_DISAGREE`) and the 4 SLQ band-retry pages (`0016/0032/0040/0056`) **and** makes future cache hits self-syncing; (iii) **re-run `stage_labels` so Tap3 `misc` (002 003 005 007 008 009 062 063 117 118) and Tap2 (273/274/275) get labeled** — §5; the 2026-11-12 19:35/19:36 re-run predates the 2026-11-13 verify-A re-bin; (iv) re-check `ocr_confidence IS NOT NULL` for the 183 kimhannom pages and `BAND_RETRY_AFTER_FULLPAGE_FAILURE` for 40 pages. All pure local operations, **zero API calls**. *Gate impact:* 51 pages move from unscored/unverified to scorable; +4-5 pages correctly flagged; Tap3/Tap2 misc pages become PPOCRLabel-verifiable. (revised 2026-11-13)

- **R4 — Ship the two one-line fixes first:** (a) `KimHanNomClient._success_code` → strict `== "000000"` (D1); (b) propagate `ENGINE_UNAVAILABLE`, `IMAGE_REC_FALLBACK`, `API_CLASSIFIED_NOT_SINO_NOM`, `OCR_ROUTING_UNKNOWN_MODE` (D7). Both are 5-minute patches + tests; re-run `python -m pytest -q` before any API spend.
  *Gate impact:* prevents fail-open success and makes every degradation path visible to reviewers.

- **R5 — Fix the ledger honesty gap (D5+D6):** add `business_code`/`outcome` to `api_calls` records (or `note=f"code={…}"`), and clamp/skip future `requested_at` rows in `api_calls_since`. Backfill note for the p67 row. Do not change what counts toward the limit without a deliberate written decision (current = count all; conservative, keep).
  *Gate impact:* honest quota accounting → correct W47/R2 scheduling; no silent error burns.

- **R6 — Retriage the suspicious pages before the gate run:** (i) 150 API lines `<0.5` conf over **93 pages** (Tap1 91 — sort by confidence, review lowest first); (ii) the **40 BAND_RETRY pages** — 36 Tap1 flagged (35 vi + 1 misc/p011) + 4 SuaLoiQuyen unflagged; merged-text QN — verify merge didn't duplicate/missing bands, spot-check against source scans; (iii) **3-4 short Nôm pages**: SuaLoiQuyen 0067(13 chars, NOM_BLOCK_START), Tap1 0275(29)/0276(15, DISAGREE 0.25, NOM_BLOCK_END) — these are near-empty and must pass human review or be treated as empty; (iv) 6 stale DISAGREE pages (mode dead, but the samples prove paddle≈0.02-0.25 similarity — do not let paddle serve nom anywhere); (v) **167 `NOM_UNENCODABLE_REPLACED` pages — note (2026-11-13): the texts contain neither `〓` nor `[MASK]`; the pipeline ships PUA code points as-is and flags the page** — sample ≥20 flagged pages to validate the flag's correctness, not the glyph; (vi) **14** `<100`-char pages (mostly front-matter — Tap1 0005/0009 now `misc`, 0013 now `vi`; SuaLoiQuyen 0002/0003/0005/0009 now `misc`; Tap2 0275 now `misc`); auto-skip OK. Note: SuaLoiQuyen misc pages also cannot be label-verified until `misc/Label.txt` is regenerated (§5/§13.4). (revised 2026-11-13)
  *Gate impact:* converts silent failures into explicit review; protects the 95% claim's honesty.

- **R7 — Do not use `difficult` for triage** (`difficult=False` ×2284). Replace with confidence-sorted review queues.

- **R8 — QN gate tactic:** for the 40 band-retry + any page whose `clean` stage produced `PAGE_MARK_REMOVED`/`DUPLICATE_LINES_REMOVED` (104/6 flags), exclude from automatic similarity scoring and count as `unverified` (they already reduce coverage rather than accuracy — that's the right gate behaviour). Do not let band-merged text inflate the verified-match ratio.

- **R9 — Sequencing to the 2026-11-30 deadline (18 days):** Day 0: R4+R5 (fixes) + R3 (re-sync) → Day 1-2: R1 (Tap2 QN GPU) + R2 queued for Monday W47 → Day 3-9: W47 API batch over 264 pages (`--no-classify`, 3s delay, `--wait-quota`) → Day 10-12: review queues (R6) → Day 13-15: labeling + fileState + alignment + gate metrics → Day 16-18: packaging (`package.py`, zip scan already verified clean of tokens). Any API slip beyond W47 eats the window in which the gate can run. (plan unchanged 2026-11-12 — the 11/12 change-set is review-input re-generation, not a pipeline change for Tap2; gates still FAIL on Tap1/Tap3, so the review-queue days are now also where the 823/380 re-aligned rows get triaged.) (revised 2026-11-12)
  *Gate impact:* without this calendar, the Tap2 books cannot pass coverage (≥0.9 verified rows) at all.

- **R10 — Hygiene (before packaging):** delete `local_fallback/` stale duplicates + DRAFT/NOTE (or document); remove dead config (`ensemble`, `max_pages_per_api_batch`, `validate_ledger_timestamp`, unused `token_id`, `QuotaSnapshot.to_dict`); pin `revision=` for the Vintern model; add a watchdog/timeout on `model.chat`; consider `--no-classify` as the *permanent* default once fixed-layout is validated on a few more books (evidence: 183/183 identical classify verdicts). **Extended 2026-11-13 (new defects):** (a) strip `result_image_base64` from cached classify payloads or explicitly exclude `data/ocr/api_cache/` from every archive/sweep (D21); (b) `load_result` must compare `image_sha256` (or reference) with the current page's sha — refuse or flag on mismatch (D16/N1); (c) wrap `json.loads` in `_load_cache`/`load_result` and degrade to cache-miss (D17/N2); (d) log a skip warning when `ocr_id == 3` with `needs_rec` (D18); (e) carry the unavailability **reason** (`quota`/`no_token`/`import_error`) into `ENGINE_UNAVAILABLE` (D20); (f) log `DIFFICULT_LENGTH_MISMATCH` instead of silent drop (D19).

---

## 10. Reproduction commands

All commands are **read-only** w.r.t. the repo (except scratch). No network access required.

```powershell
cd "C:\Users\MSI VN\Desktop\NLP"
python -m pytest -q                                  # expect: 307 passed (verified 2026-11-13; was 282 on 2026-11-12)

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
# (Note: 2026-11-13 supersedes review_flags → 907 and pytest → 307; see verify-replicate-C.)

# 2026-11-13 verification & replication pass (read-only re-measurement; scratch):
#   python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-replicate-C\census.py"        # census of OCR JSONs (engines/lines/warnings/short pages/band-retry)
#   → 390 JSONs (Tap1 274 + Tap2 6 + SLQ 110); engines vintern 207 / kimhannom 183; 2284 lines;
#     difficult=False ×2284; confidence<0.5 = 150 lines over 93 pages; band-retry 40 JSONs (36+4);
#     14 <100-char pages; <10 chars 1 (Tap1 0009); 3 ch <50 chars; api_cache 366 payloads all raw.code="000000";
#     uploads/ 183 files; classify payloads embed result_image_base64 (~92.7 MB) → D21
#   python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-replicate-C\extract_pdfs.py"   # PDF re-read (PyMuPDF, read-only)
#   → guideline v2.1 p.4 sentences verified verbatim (flow / website limits / ≥2 calls per image);
#     manual p.1 UA (flattened, byte-identical to project.yaml api.user_agent — PyYAML-parsed compare = True, 131 chars);
#     manual p.4 structure-classification documents ONLY file_name; p.6/p.10 image-ocr/ImageOcrData ("có thể rỗng" = p.10);
#     p.7 image-rec = crops only + "hiện chưa được mô tả"; p.8/p.9 envelope + OcrId/LangType/ReadingDirection/Epitaph enums
#   python "C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-replicate-C\quota_probe.py"     # temp sqlite, NO repo writes
#   → future row counted in 4/4 windows (snapshot 1/1/1/1); check() does NOT raise with default limits;
#     retry_after=10860s reproduces only with per_minute=1 saturation (measured 10859.996s); rolling window ≈4.99s (limit=2, −55 s);
#     record() counts http_500s; WINDOWS = 60/3600/86400/604800; default min_delay path ≈3.0s
#   state cross-tabs (mode=ro) →
#     review_flags non-empty 907 (Tap1 276/Tap2 542/SLQ 89); LABEL_EMPTY_OCR 808; BAND_RETRY 36; DISAGREE 5 state vs 6 JSON (p0147);
#     NOM_UNENCODABLE_REPLACED 167; PAGE_MARK_REMOVED 104; BIN_OVERRIDE_MISC 29; FOOTER_TITLE_REMOVED 17; NOM_BLOCK_START/END 3/3;
#     ocr_confidence NULL 51 (50 SLQ p0067–p0116 + Tap1 p0147); Tap3 misc/Label.txt = 001/064 only; Tap2 label bins stale (no misc);
#     metrics.json: Tap1 89.9646/0.4629, Tap3 93.7385/0.6, Tap2 85.7143/0.1333, all passed=false; DB mtime 2026-11-13 09:22:34
#   python -m pytest -q → 307 passed, exit 0 (~4.6 s)

# Run the remaining OCR (NOT executed during verification):
# python -m hannom.cli ocr --only nom --no-classify --wait-quota   # R2
# python -m hannom.cli ocr --only qn                              # R1 (vintern, GPU)
```

---

## 11. Handoff checklist (for the next agent)

- [ ] Confirm `git status --porcelain` shows only the intended changes (`Doc/verify-C-ocr.md`; nothing else modified by you).
- [ ] Re-run `python -m pytest -q` — **307 green** before and after any edit (verified 2026-11-13; was 282 on 2026-11-12). (2026-11-13)
- [ ] Apply R4 (the D1 one-liner + D7 codes: `ENGINE_UNAVAILABLE`, `IMAGE_REC_FALLBACK`, `API_CLASSIFIED_NOT_SINO_NOM`, `OCR_ROUTING_UNKNOWN_MODE`, `OCR_LINE_WITHOUT_BBOX`) + their unit tests; re-run pytest. (extend R4 2026-11-13)
- [ ] Apply R5/R6 code changes **behind** the same run's tests; do not alter `api_calls` semantics silently.
- [ ] **Extend R3 (2026-11-13):** fix D7 first, *then* re-sync — `ocr_confidence` for the 51 pages (50 SLQ **p0067–p0116** + Tap1 **p0147**); re-promote `promote_review_flags` for all 390 cached results at `load_result` (this re-flags p0147 `OCR_ENGINE_DISAGREE` and the 4 SLQ band-retry pages); **re-run `stage_labels` so Tap3 `misc` (002,003,005,007,008,009,062,063,117,118) and Tap2 (273/274/275) get labeled** — §5, §13.4; expect Tap2's label bins to be rebuilt from the current DB (they were generated pre-re-bin and miss `misc`). Verify `ocr_confidence IS NOT NULL` for the 183 kimhannom pages and `BAND_RETRY_AFTER_FULLPAGE_FAILURE` for 40 pages. The 11/12 `stage_labels` re-run and the 11/13 verify-A re-bin did NOT do this.
- [ ] After **any** future re-bin/classification change: treat label bins (`data/labels/<book>/*/Label.txt`) and `stage_clean` outputs as **stale** and re-run before packaging (no dependency tracking exists). (2026-11-13)
- [ ] Run R1 (Tap2 QN, GPU); then **wait for W47** and run R2 (`--only nom --no-classify --wait-quota`).
- [ ] Verify no QN page ever appears in `api_calls` (it must not — v2.1/decision: QN never via API).
- [ ] Confirm the gate report separates accuracy (`similarity`) from coverage (`verified/total`) per `evaluate.py`; Tap2's coverage is the binding constraint.
- [ ] Sampling: 167 `NOM_UNENCODABLE_REPLACED` + 40 band-retry pages + 150 low-conf lines + **6** DISAGREE pages (incl. p0147) must all land in review before any "nhì tóm tắt" (report) claim passes. **Texts contain neither `〓` nor `[MASK]`** — sample the flagged pages, not the glyphs (§13.6).
- [ ] D16/D17 hygiene before any production re-run: `load_result` must compare `image_sha256` with the current page sha; wrap `json.loads` in cache reads. D21: `result_image_base64` must never enter `source.zip` (see §10 — `data/ocr/api_cache/` is ~97 MB of base64 page images).
- [ ] Do **not** read `hannom_API.md`/`.env`; do not call the API except through `--wait-quota` runs with R4 fixed; never call `kimhannom.fit.hcmus.edu.vn` ad hoc.
- [ ] If any kimhannom client code changes: `--force` re-run of the API pages (or re-sync via cache; no quota re-spend) before re-scoring.
- [ ] Delete `local_fallback/` stale duplicates + DRAFT/NOTE (or document them) before packaging.
- [ ] Update `USER_GUIDE.md`: quota now includes business-failure rows (D5 — with the 2026-11-13 severity caveat D6/D15 in mind), `--no-classify` recommended after Tap2 evidence, `difficult` not usable, PUA-ships-as-is note for `NOM_UNENCODABLE_REPLACED`.
- [ ] Verify `submission/` (untracked, pre-existing) is handled by whatever process owns it — not this agent's scope.
- [ ] Leave `Doc/verify-C-ocr.md` as the record; append a "resolved" section rather than editing history.

---

---

## 12. Caveats (what was NOT tested)

- **The live Kim Hán Nôm API was not called** (forbidden in both audit passes). Compliance rests on the manual PDF, the v2.1 guideline PDF (re-read verbatim 2026-11-13), and repo artefacts (ledger/cache/JSONs). Business codes **other than** `"000000"` were never observed by this agent; the `000108` claim is an inference from one p67 ledger pair — strong (2 calls 20 s apart, first un-cached, second cached with code `000000`), not absolute.
- **Integer-0 success return**: mechanical defect confirmed by truth-table reproduction (`0`, `False`, `0.0` all pass); no live evidence of a wire occurrence — the D1 risk remains unobserved but one-line-deadly.
- **Image-rec full-page behavior** was never exercised (0 calls); D2's impact is wholly unobserved.
- **Vintern inference quality on this machine** was not re-run by this report; the 36/144 page-marker failure rate comes from persisted outputs (2026-11-10/11), not from a controlled experiment. The band-retry merged outputs' fidelity (duplication? missing columns? 4-point order?) is unverified beyond length statistics — **must be manually sampled**.
- **PaddleOCR** was not run; its Nôm similarity (0.02-0.25) is from six stale `DISAGREE` files (Tap1 0147/0212/0276, Tap2 0277/0409/0540) produced in a since-removed mode; parity across corpora is not established.
- **`data/state.sqlite3` "all http_200"** is true only of *recorded* rows; business failures are folded in (D5). No evidence either way about what the *server* counts toward its website limits. Quota DB mtime = **2026-11-13 09:22:34**; last api_calls = 2026-11-11T16:00:05Z; **zero calls on 2026-11-12 and 2026-11-13**.
- **Timing claims** (`~35 s/page`) come from file `raw.seconds` statistics of past runs (2-120 s observed), not a fresh benchmark.
- **Packaging/labeling/gate stages** (Label.txt writer, `fileState.txt`, alignment, `evaluate_rows`, zip validator) were read but not executed; their correctness is out of this area's scope — **except where the 2026-11-13 pass measured them: Tap3/Tap2 label bins are stale post-re-bin (§5, §13.4)**. The ≥95% recommendation assumes packaging works as written.
- **`hannom_API.md` was not read** (per ground rules) — so the possibility that its content differs from the PDF manual is unverified. (The `*.extracted.txt` files are also gone from the tree as of 2026-11-13.)
- **The 2026-11-13 commits (`ed43470`, `4fd0af6`, `d515491`)** re-binned pages and hardened state/preflight and `t1_map`: `inventory_misc: [273,274,275]` committed; labels are **invalidated** by any re-bin but were **not regenerated** for Tap3 misc (001/064 only) or Tap2 (no `misc` bin); Tap1 misc was rebuilt 2026-11-12 19:36 and is consistent. Whether `BIN_OVERRIDE_*`/`misc` bins are consumed correctly downstream is verify-A/B/D/E scope — but the stale-label outcome is now empirically confirmed (§5). `image_map` markers (`d515491`) are out of this area's scope. Image-workflow unchanged (ocr freshness from 2026-11-10/11). (revised 2026-11-13)
- **D6 severity caveat (2026-11-13):** the one-row-bricks-the-API simulation does **not** reproduce with default limits — it is window-count inflation; the `10860 s` figure requires `per_minute=1` saturation (measured 10859.996 s). Treat any single "verified" simulation from 2026-11-12 accordingly.
- The **`submission/`** directory (pre-existing untracked) and any **`*.extracted.txt`** were not audited; they are not part of OCR stage 4.
- **made-up dates**: none. All timestamps quoted come from ledger/JSON/file mtimes.
- **Grep completeness**: token-leak sweep covered `src/**`, `configs/**`, `tools/**`; docs and `data/**` were not exhaustively swept; `api_cache` payloads have **not** been swept for leaked secrets (only shape/`code`/size inspected — and found to contain full page images, D21). (revised 2026-11-13)
- **The 2026-11-13 figures in this file** (307 tests, 907 flags, 899 targets, 0.919 mean confidence) are a point-in-time measurement at HEAD `d515491` — the pipeline is dynamic; re-measure with `verify-replicate-C\` scripts before citing them again.

## 13. 2026-11-13 verification & replication pass — errata, new findings & root causes

Everything in this section was **re-measured read-only on 2026-11-13 at HEAD `d515491`** (`git status` clean; scratch in `verify-replicate-C\`; DB `mode=ro`; no network; PDFs re-read with PyMuPDF). It records what the 2026-11-12 revision got right, what drifted, what was wrong, and what is new. **No repo/data file was modified.**

### 13.1 What replicated unchanged (the bulk, all verified)

UA byte-identity; 550 `api_calls` (183 upload / 184 classify / 183 ocr, all `http_200`); p67 duplicate (call_ids 2/3, 20 s apart, first un-cached); W45=169 / W46=381 (198 on 11-10, 183 on 11-11, **0 on 2026-11-12**, 0 on 2026-11-13); max 10 calls/min; WINDOWS=60/3600/86400/604800; rolling-window ≈5 s semantics; `record()` counting failures; 390/390 JSON↔state sha consistency; engines (207 vintern / 183 kimhannom; Tap1 144/130, Tap2 3/3, SLQ 60/50); 2284 lines; `difficult=False ×2284`; `<0.5` conf = 150 lines / 93 pages (pipe: Tap1 91 + Tap2 2); 14 `<100`-char pages (same list, folder annotations updated); 1 `<10`-char page (Tap1 0009); 3 ch `<50` pages; 36 Tap1 band-retry flagged (35 vi pages 0032–0139 incl. 0011 + misc p011) and 4 SLQ unflagged; `BBOX_*`/`OCR_EMPTY`/`ENGINE_UNAVAILABLE`/`IMAGE_REC_FALLBACK`/`FULLPAGE_DEGRADED` = 0 everywhere; DISAGREE = 6 (Tap1 0147 0.11 / 0212 0.13 / 0276 0.25; Tap2 0277 0.15 / 0409 0.02 / 0540 0.11); Tap3 band-retry mtimes ≈00:39–00:41 on 2026-11-09 (`0016/0032/0040/0056`) with `local_fallback` copies 23:00–23:01; Tap1 36 refreshed 2026-11-10 14:07–14:46; `ocr_done`=390 (per-book 274/6/110 — §8); `runs`=0; `artifacts`=18; gates FAIL (89.96/0.463; 93.74/0.6; 85.71/0.133) — metrics.json mtimes 2026-11-13 09:21–09:22.

### 13.2 PDF re-verification (both manual & guideline — quotes verbatim)

- **Manual** (`Hướng dẫn sử dụng API Kim Hán Nôm.pdf`, v2026-10-10): limits table **labelled "Giới hạn số lượt gọi (website)"** = 25/min · 50/h · 200/day · 600/week (p.1); envelope `code` is a **string**, success `"000000"` (pp.2, 8); `structure-classification` documents **only** `file_name`, example `{"file_name": "tempd561…"}` (p.4); p.6's successful response example shows shape `{ocr_id, lang_type, reading_direction, is_sino_nom}` (`is_sino_nom` can be `true`); image-ocr example body p.6; image-rec = **crops only**, response structure "hiện chưa được mô tả" (pp.7, 10); "có thể rỗng" belongs to **p.10** ImageOcrData (not p.6 — §3.10 corrected); `reading_direction` default vertical (pp.6, 9).
- **Guideline** (`Quy_định_đồ_án_v2.1.pdf`, v2.1 2026-11-06): §4 "Chạy OCR hình ảnh" (p.4) — *"Ưu tiên sử dụng công cụ https://kimhannom.fit.hcmus.edu.vn/ … Khi gọi trực tiếp qua API (xem file hướng dẫn sử dụng API): Quy trình: image-upload →structure-classification (đặt ocr_id, lang_type, reading_direction bằng 0 để server tự nhận diện) →image-ocr."*; *"Giới hạn trên website: 25 lượt/phút, 50 lượt/giờ, 200 lượt/ngày, 600 lượt/tuần. Mỗi ảnh cần ít nhất 2 lượt gọi…"*; *"Nếu bounding box từ image-ocr không hợp lệ: chỉnh lại box, cắt từng dòng rồi dùng image-rec."*; §5 (p.5) details/difficult note (ocr_id ≠ 3). ⇒ D4's exceedance is the guideline's own prescription; keep the 0-fields.

### 13.3 What drifted with the 2026-11-13 commits (`ed43470`, `4fd0af6`, `d515491`)

| Item | 2026-11-12 report/revision | 2026-11-13 reality |
|---|---|---|
| pytest collected/passed | 282 (revision log: 282; original: 277) | **307 passed** (read-only; exit 0) |
| non-empty `review_flags` | 902 (275/541/86) | **907** (276/542/89) |
| blank / misc (DB) | 18 / 29 | **19 / 32** (misc: Tap1 16 + SLQ 12 + **Tap2 4**) |
| OCR targets total | 903 | **899** (Tap1 260, Tap2 **539**, SLQ 100; Tap2 YAML now `inventory_misc: [273,274,275]`, `vi_to_nom_offset: 549`) |
| Tap2 book YAML | "not modified" | **modified** (committed `ed43470`) |
| Tap2 6 ocr_done | "3 vi" (+3 ch) | **0009 & 0142 (vi) + 0275 (misc) + 0277/0409/0540 (ch)** |
| Tap2 misc re-bin flag | — | `BIN_OVERRIDE_MISC` ×29 in state (Tap1/SLQ/Tap2); `BIN_OVERRIDE_VI` ×8 |
| state `OCR_ENGINE_DISAGREE` | 5 | **5** (JSONs still 6; p0147 promotion gap — D7) |
| mean line confidence | "0.86 (all)" | **0.919 (all)**; 0.907 Tap1 (✓), 0.860 Tap2, 0.971 SLQ (✓) — "0.86" is Tap2-only |
| SLQ JSON count | "116" | **110 main + 4 `local_fallback` (114 JSONs) + 2 `.md` = 116 non-JSON-misc artefacts under SLQ/** (390 total holds) |
| `orchestrator.py` length / labels tuple | "571 (still)" / ~169 | **643**, tuple unchanged at ~line 169 (`("ch","vi","intro","ref","toc","misc")`) — see Appendix |
| `config.py` | 63-86 / 23-29 / 121-215 / `ensemble`@168-170 | **67-90 / 22-28 / 141-228 / `ensemble`@181** |
| `state.py` | log_api_call ~252–300; `api_calls_since` ~294–300 | **352–382 / 384–390 / 392–400 / 402–406** (verify-A hardening `4fd0af6`) |
| `package.py` secret scan | ~520–546 ("541") | **`validate_source_zip` 597–631** (`SOURCE_CONTAINS_SECRET_OR_STATE` 611–612; `KIMHANNOM_TOKEN` scan 625–630) |
| `models.py` | ~35–60 | OCRLine **42–59**, OCRResult **63–72**, PageRecord **16** |
| `clean.py` `count_nom_chars` | 101–102 | **105–107** |
| `labels.py` `line_to_box` | 83–90 | **83–93** |
| `textdiff.py` `scoreable_nom_chars` | 603–612 | **unchanged ✓** |
| `quota.py` anchors | unchanged | **unchanged ✓** (quota.py 126 lines: WINDOWS 41-46, snapshot 60-72, seconds_until_allowed 74-88, check 90-105, record 107-123, validate_ledger_timestamp 125-126) |
| `kimhannom.py`, `router.py`, `local_paddle.py`, `local_vintern.py` | unchanged anchors | **unchanged ✓** (router api_first branch = 306–328) |
| `pytest count files` | 36 files | **36 files** ✓ |

### 13.4 Root cause: the 2026-11-13 verify-A re-bin invalidated downstream labels (Tap3 misc, Tap2 bin)

The 11-13 verify-A change **re-binned 29 already-OCR'd pages** (`BIN_OVERRIDE_MISC`): Tap1's 16 misc were already consistent (its 11-12 19:36 rebuild followed its re-bin, 11-12) — but they are the exception. The 10 OCR'd SLQ misc pages (`002 003 005 007 008 009 062 063 117 118`, all vintern, OCR'd 11-11, `FOOTER_TITLE_REMOVED`) were re-binned on **2026-11-13T01:57–02:00** (`pages.updated_at`), *after* the last `stage_labels` run (**2026-11-12 19:35**, bins written before re-bin) ⇒ `data/labels/T1_SuaLoiQuyen/misc/Label.txt` still covers only `001`/`064` (empty labels, classified-only pages) ⇒ the 10 pages are **unlabeled anywhere** (8 sit in the obsolete `intro/`/`toc/` bins from pre-re-bin; `intro/`/`toc/` bins' mtimes = 13:24 ≠ 19:35). **Tap2 has no `misc` bin at all** (ch 264 / vi 267 / intro 2 / toc 10 — page moves post-re-bin not reflected; 273/274/275 re-binned; 275 OCR'd). **Single failure mode: label bins are one-shot-generated and nothing tracks "bins changed at" vs "labels built at"** — `stage_labels` does not re-run on re-bin, `load_result` never validates sha, `stage_clean` unions only its own flags. ⇒ **R3 extended (§9): fix D7, then re-run `stage_labels` for Tap3 misc + Tap2 misc, then re-promote cache results.** This is the same family as the 51 `ocr_confidence IS NULL` (11-08 21:00 batch, cache-hit re-runs never re-sync) and the 4 SLQ band-retry flag gap — **the pipeline has no cross-stage consistency gate**, and every 2026-11-1x re-bin demonstrates it.

### 13.5 New findings

**D16–D21** (§7): (D16) `load_result` never revalidates `image_sha256` — stale OCR can be silently re-used post-re-extract (router.py:139-166, 249-250). (D17) unguarded `json.loads` in `_load_cache`/`load_result` — one corrupt file crashes the stage. (D18) `ocr_id == 3` + `needs_rec` — fully silent skip. (D19) `difficult` length-mismatch → silent `None`. (D20) `ENGINE_UNAVAILABLE` reason-free string. (D21) **classify cache embeds `result_image_base64`** (~92.7 MB) — unused downstream; packaging/archive hazard.

**Test-signal drift**: `OCR_ENGINE_DISAGREE` for Tap1 **p0147** exists in the OCR JSON but **not** in `pages.review_flags` (state 5 vs JSON 6) — direct evidence that cache-hit paths do not re-promote (D7).

### 13.6 Unencoded glyphs — what reviewers will actually see

`NOM_UNENCODABLE_REPLACED` (167 pages) and clean-stage `replacements:{…}` are **flag strings only**. OCR/clean texts contain **neither `〓` (U+3013) nor `[MASK]` nor PUA-substituted text**: the raw PUA code points (e.g. `U+F0272`, `U+F0803`) ship as-is; the flag exists so a reviewer can find and inspect them. The intended `〓` (U+3013, defined as `clean.py:19` `REPLACEMENT`) and `[MASK]` (`clean.py:17`, `MASK_LEN=6`) never appear in any OCR or clean text. ⇒ **Sampling instructions (R6) must target flagged pages, not glyphs**; any gate claim about "all 〓 cases listed in the report" (guideline p.13) must be computed from `replacements:{}` maps, not from text inspection.

### 13.7 Verdicts on D1–D15 as revised

All 15 survive in substance. D6's simulation corrected (mechanism real, one-row-cap claim not reproducible with default limits; severity HIGH→MEDIUM-HIGH). D8's warning name fixed (`ENGINE_UNAVAILABLE`, reason-free). D13's `sample_pages` claim refined. D15's docstring qualifier absent (website-vs-API reasoning remains only in docs). D7 gains the p0147 evidence. D4's sanction and the `000108` inference re-verified end-to-end. D12 verified against the tree (CUDA-required `is_available`; `transformers==4.46.3` pinned). No defect was observed live on the wire; D2 is wholly dormant (0 calls). **None of this changes the headline verdict: Tap2 is the blocker; everything else is triage hygiene.**

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
- `src/hannom/orchestrator.py` — **643 lines** (2026-11-13; was 571 on 2026-11-12). `stage_labels` folder tuple unchanged at ~line 169: `("ch","vi","intro","ref","toc","misc")`; stage_labels binds nothing — **one-shot, not re-run after the 2026-11-13 re-bin** ⇒ Tap3 `misc/Label.txt` stale (001/064 only), Tap2 **no `misc` bin** (§5, §13.4). `stage_ocr` unchanged. (revised 2026-11-13)
- `src/hannom/config.py` — `BookConfig.inventory_vi`/`inventory_misc` (fields 47-48, unchanged 2026-11-13); **`ApiSettings` 67-90** (fixed_ocr_id/fixed_reading_direction 84-85; `classify` default 83), **`OCRSettings` 22-28**, **`load_config` 141-228**, `ensemble=bool(ocr_raw.get("ensemble", True))` at line **181** (was 168-170 — verify-A hardening `4fd0af6` added lines). (revised 2026-11-13)
- `src/hannom/state.py` — `upsert_page` 224-274; `update_page` 276-315; `log_api_call` **352-382** (no future-validation; no business_code); `count_api_calls` **384-390** (no status filter); `last_api_call` **392-400**; `api_calls_since` **402-406** (no upper bound → D6). (revised 2026-11-13)
- `src/hannom/package.py` — zip secret scan now in `validate_source_zip` **597-631** (`SOURCE_CONTAINS_SECRET_OR_STATE` **611-612**; `KIMHANNOM_TOKEN` content scan **625-630**); 2026-11-12 cite "541" stale. (revised 2026-11-13)
- `src/hannom/models.py` — `PageRecord` 16; `OCRLine` **42-59**; `OCRResult` **63-72**. `src/hannom/clean.py` — `MASK` 17; `MASK_LEN` 18-ish; `REPLACEMENT` 19 (`〓` U+3013 — never emitted; flag-only, §13.6); `count_nom_chars` **105-107**. `src/hannom/labels.py` — `line_to_box` **83-93**; `difficult` passthrough **89-90** ✓; `points_to_quad` 41-69 ✓. (revised 2026-11-13)
- `src/hannom/layout.py` — 2026-11-12 change-set: declarative `BIN_OVERRIDE_VI`/`BIN_OVERRIDE_MISC` post-classification override (~line 339+, never overrides blank/ch/nom). (revised 2026-11-12)
- `src/hannom/textdiff.py` — scoreable_nom_chars 603-612 (was 588-597); `_reading_match` gained the weak orthographic variant-fold cell (`charalign.fold`; quỷ/quỉ/quĩ→qui, d/gi, đ/d; never strong, never rewrites text). (revised 2026-11-12)
- `src/hannom/align.py` — 2026-11-12 change-set added ≤72 lines post-~387 (charalign projection; `COSEGMENTED_STREAM_ALIGNED` segments). Not re-audited line-by-line by this report. (revised 2026-11-12)
- `src/hannom/charstream.py` / `src/hannom/map_repair.py` (new 2026-11-12) — `hannom.charstream` dịch-âm segmenter (charalign); `map_repair` image_map repair (DP pairing + parens anchors; pre-repair map kept at `map_repair/image_map.pre-repair.json`). Not OCR; not audited here. (revised 2026-11-12)
- Manual quotes: `Hướng dẫn sử dụng API Kim Hán Nôm.pdf` (repo root, v2026-10-10 — the extracted.txt is gone; re-read via PyMuPDF 2026-11-13) pp.1-10 as quoted in §3/§13.2; guideline quotes: `Quy_định_đồ_án_v2.1.pdf` (repo root, v2.1 2026-11-06) pp.4-5 as quoted in §3.6a/§3.11/§3.12/§13.2. (revised 2026-11-13)
- Empirical data: `data/state.sqlite3` (mtime 2026-11-13 09:22:34; `api_calls` 550 rows; `pages` 950; `runs` 0; `reviews` 0; `artifacts` 18), `data/ocr/**` (390 JSONs = Tap1 274 + Tap2 6 + SLQ 110; 366 API-cache payloads all `raw.code="000000"` — **classify payloads embed `result_image_base64` ≈92.7 MB (D21)**; `uploads/*` 183), `data/align/**` (Tap1 823 rows / Tap3 380 rows, unchanged), `data/evaluation/**` (metrics.json mtimes **2026-11-13 09:21–09:22**; similarity 89.96 / 93.74 / 85.71; gates FAIL ×3), `data/labels/**` (Tap1 consistent; **Tap3 `misc/Label.txt` = 001/064 only — 10 ocr_done misc unlabeled; Tap2 has no `misc` bin** — §5/§13.4), `data/pages/` (950 native JPEGs, ~354.3 MB). (revised 2026-11-13; scratch: `verify-replicate-C\`, `verify-revise-C\`, `verify-C\`)

---

## Revision log (2026-11-13 — verification & replication pass)

**Pass:** re-verified the 2026-11-12 revision line-by-line and empirically re-measured every claim read-only at HEAD `d515491` (clean tree; scratch in `C:\Users\MSI VN\AppData\Local\Temp\opencode\verify-replicate-C\`; DB `mode=ro`, mtime 2026-11-13 09:22:34; **no network calls**; `.env`/`hannom_API.md` not read; both PDFs re-read with PyMuPDF). **No repo or `data/` file was modified — this document only.** Headline: **all 15 defects D1–D15 survive** (T1–D15 re-confirmed; D6 reworded — severity HIGH→MEDIUM-HIGH; D8 warning name corrected to `ENGINE_UNAVAILABLE`; D13 `sample_pages` refined; D15 qualifier absent from docstring; D7 gains the p0147 promotion-gap instance; D4 sanction re-verified verbatim from guideline p.4; `000108` inference corroborated end-to-end: first p67 call un-cached, second cached `abbe…` with `raw.code="000000"`, `saved_at` = 2nd call +16 ms). Six new findings D16–D21 (§7, §13.5). Material drift corrected throughout (§13.3): pytest **282→307**; `review_flags`** 902→907** (Tap2 542, SLQ 89 — 11-13 re-bin); targets **903→899** (Tap2 539; blank 18→19; misc 29→32 incl. Tap2 4; Tap2 YAML now modified); Tap2 6 = 2 vi (0009/0142) + 1 misc (0275) + 3 ch (report's "3 vi" wrong); mean line confidence **0.919 all** ("0.86" = Tap2-only); SLQ OCR JSONs 110 (+4 `local_fallback`) not 116; `orchestrator.py` 571→643; `config.py` ApiSettings 63-86→**67-90** (`ensemble` 170→**181**); `state.py` +118-line verify-A hardening (anchors **352-382/384-390/402-406**); `package.py` secret scan moved +~80 (now `validate_source_zip` **597-631**); models 62-72→42-72; clean `count_nom_chars` 101-102→**105-107**; labels `line_to_box` 83-90→**83-93**; DISAGREE state 5 vs JSON 6 (p0147). **New root-cause finding (§13.4): the 2026-11-13 verify-A re-bin invalidated downstream labels — SLQ `misc/Label.txt` still 001/064 (10 unlabeled), Tap2 has no `misc` bin; labels are one-shot with no staleness tracking; R3 extended: fix D7 first, re-run `stage_labels`, then re-promote all 390 cached results.** `NOM_UNENCODABLE_REPLACED` documented (§13.6): flag-only, PUA ships as-is, `〓` never emitted. `api_cache` documented (D21): classify payloads embed `result_image_base64` (~92.7 MB; `validate_source_zip` scans for secrets, not for images — keep `data/` out of archives). Guideline/manual quotes re-verified verbatim (§13.2). Reproduction note: 2026-11-12's "one future row bricks the API" simulation does **not** reproduce with default limits (D6) — 2026-11-13 D6 severity accordingly lowered; all other 11-12 sim results reproduce. Penalty/goal unchanged: **Tap2's 6/539 pages is the binding gate risk**; W47 (2026-11-16) is still the earliest API unblock.

Changes made by this revision (2026-11-13):

1. **§Banner/header/verdict**: 2026-11-13 revision banner; HEAD re-cited (`d515491`); tests 282→307.
2. **§1/§2/§10/§11**: line-anchor updates (config.py, state.py, orchestrator.py, package.py, models, clean, labels); scratch → `verify-replicate-C\`; re-verified PDF paths; `runs` still 0.
3. **§3/§3.10**: p10 "có thể rỗng" cite corrected; D4 evidence end-to-end; all other §3 verdicts unchanged.
4. **§4**: future-row mechanism reworded (D6); 550/W45/W46/198/183/zero-11-12 re-confirmed; `note` NULL ×550; no business/outcome column.
5. **§5**: p0067–p0116/p0147 precise; band-retry split re-confirmed (35 vi 0032–0139 + p011); **p0147 JSON-flag vs state** gap added (D7 corroboration); new items 9 (classify cache base64) & 10 (PUA-ships-as-is); Tap1 misc OK / **Tap3 misc stale / Tap2 no misc bin** — with 11-13 re-bin causation; `runs`=0; `artifacts`=18 (6×3).
6. **§6**: Tap2 QN = 275 (264+2+9) — was 279; targets 899; `pipeline consistency` re-cited (`image_sha256` top-level); tests 307.
7. **§7**: D1–D15 re-verified & some reworded (D6/D7/D8/D13/D15); **six new defects D16–D21** (D16 load_result sha revalidation missing; D17 unguarded `json.loads`); D20 reason-free ENGINE_UNAVAILABLE; D21 classify-cache base64); D2 confirmed still dormant (0 calls); D13 anchor 181; all anchors re-checked, OCR-subsystem files unchanged.
8. **§8**: full re-measure (§13.3 drift table); `metrics.json` mtimes 2026-11-13 09:21–09:22; Tap2 6 re-detailed; 907 flags; 899 targets; mean conf 0.919.
9. **§9**: R1 counts (275); R3 **extended** (D7-first, `stage_labels` re-run, p0147 re-promotion, sha check, SLQ misc + Tap2 273/274/275 labels); R6 PUA wording; R10 extended with D16–D21 hygiene; R2/R4/R5/R7/R8/R9 unchanged.
10. **§10/§11**: 307 expected; verify-replicate-C steps documented (extraction, UA, quota probe, censuses, cross-tabs); checklist reworked (D7→R3 order, re-bin→labels gate, D16/D17/D21 items, 307).
11. **§12 Caveats**: API never live-called; D1 truth-table-confirmed mechanically, wire-unobserved; Tap2/SLQ labels stale; D6 caveat; 11-13 point-in-time caveat; `api_cache` not secret-swept (but base64-found).
12. **§13 (new)**: full errata/root-cause/new-finding consolidation incl. verdict table on D1–D15 and the label-invalidation root cause.
13. **Appendix**: all drifted anchors updated (orchestrator 643 / `stage_labels` ~169 / config.py / state.py / package.py / models / clean / labels); manual/guideline quotes now cited from the PDFs directly; empirical data re-dated; scratch paths added.
14. Not done (out of scope): D1–D21 remain **unfixed in code** (this revision only documents); align CSVs, image_map markers, gates, packaging pipeline untouched; CI not re-run; `hannom_API.md`/`.env` still unread; no API calls made (zero on 11-12 and 11-13); `submission/` untouched.

History: the section immediately below is the 2026-11-12 post-map-repair revision, preserved as written (except where inline tags mark superseded claims). The 2026-11-12 section text is untouched apart from tags added by that pass — the 2026-11-13 pass made **document-level** revisions only (this doc).

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

History: this section (2026-11-12 revision) is preserved as written except where the inline "(revised 2026-11-12)" tags mark superseded claims; the current state of this document is governed by the **2026-11-13 verification & replication pass** section above. The 2026-11-13-to-present view is: HEAD `d515491`; **307 tests green**; all 15 defects reproduced and line anchors re-checked; **6 new defects D16–D21**; Tap2 still the blocker (6/539 OCR'd, W47 = 2026-11-16 is the first API unblock); Tap3/Tap2 label bins stale post-re-bin (§5, §13.4).

---

## 14. Resolved (2026-11-13) — what the fix pass landed

The 2026-11-13 verification pass (see §13) ended with a decision to implement the fixes. This section supersedes the handoff items in §11: the code/data work is done; only the quota-gated work remains.

**Implemented & verified (code):**

| Item | Fix | Verified |
|---|---|---|
| D1 | `_success_code` now strictly accepts `"000000"` (truth table is a test) | `tests/test_verify_c_fixes.py::test_d1_success_code_is_strict` |
| D7 | `PROPAGATED_WARNING_CODES` += `ENGINE_UNAVAILABLE`, `IMAGE_REC_FALLBACK`, `API_CLASSIFIED_NOT_SINO_NOM`, `OCR_ROUTING_UNKNOWN_MODE`, `OCR_LINE_WITHOUT_BBOX`; `load_result` re-promotes cached warnings on cache hits (idempotent) | `test_d7_new_codes_are_propagated`, `test_d7_cache_hit_promotes_flags` |
| D5 | `api_calls.business_code` column; schema v2 (v1→v2 `ALTER TABLE` migration path tested); every call records the server business code (e.g. `000000`/`000108`) | `test_d5_*` (fresh schema, v1 migration, roundtrip) |
| D6 | `requested_at` beyond a 5-min future tolerance rejected at insert (`StateError`); `count_api_calls`/`api_calls_since`/`last_api_call` accept `until=`; quota windows ignore skewed rows | `test_d6_*` |
| D16 | `load_result` ignores cached JSONs whose `image_sha256` ≠ current page (log + skip) | `test_d16_stale_result_is_ignored` |
| D17 | Corrupt cache/result JSON degrades to skip+log | `test_d17_*` |
| D18/D19 | `OCR_REC_SKIPPED_SCENE` (ocr_id==3 + needs_rec) logged; `DIFFICULT_LENGTH_MISMATCH` logged | code review; kimhannom.py |
| D20 | `ENGINE_UNAVAILABLE:<engine>:<no_token|import_error>` — router carries the reason | `test_d20_unavailability_reason_without_token` |
| D21 | `scrub_server_payload` strips `result_image_base64` on every cached save (kimhannom `_save_cache` + `router.save_result`) | `test_d21_scrub_server_payload_strips_base64_anywhere` |
| D12 | Vintern pinned to revision `c3f01cf5…c8bc` (matches local HF cache `refs/main`); per-call wall-clock `StoppingCriteria` watchdog (`max_time_seconds=300`); degrades with a loud warning if transformers rejects it | code review; not run live |
| D14/D10/D13 | Dead code removed (`validate_ledger_timestamp`, `QuotaSnapshot.to_dict`, client `token_id`); `ensemble` + `max_pages_per_api_batch` config removed | grep; `pytest` green |
| R3-extended (data) | Backup `state.sqlite3.bak-20261113-062421-pre-verifyc-resync` taken; re-promote over all 390 cached results → 5 pages changed (p0147 → `OCR_ENGINE_DISAGREE`; SLQ 0016/0032/0040/0056 → `BAND_RETRY_AFTER_FULLPAGE_FAILURE`); `ocr_confidence` set for the 51 NULLed pages (50 SLQ p0067-p0116 + p0147) | DB verification (`quick_check=ok`; `user_version=2`) |
| R3-extended (labels) | `stage_labels` re-run for Tap2/Tap3 after the 11-13 re-bin: SLQ misc now 12 rows (10 OCR'd pages labeled incl. 062/063); Tap2 gained a `misc` bin (275 boxed; 001/273/274 empty pending OCR); all `fileState.txt` = 1 | `hannom labels` output + file check |

**Test count:** 320 passed (was 307; +13 in `tests/test_verify_c_fixes.py`; one existing fixture in `test_ocr_routing.py` corrected to seed the same sha). **No API calls were made; no OCR re-runs; Tap2 remains un-OCR'd by quota policy (W47 = 2026-11-16).**

**Explicitly not done (by design):** R1 (Tap2 QN on GPU), R2 (Tap2 Nôm after W47 rollover, `--no-classify --wait-quota`), packaging/report/members/screenshots, human review of the ~593 unverified rows, and the `submission/` stale-sample question. Gates still FAIL — that now only depends on review and Tap2 quota, not on code.

**Caveat on this document:** the body of this report describes the pre-fix baseline (by design, for audit trail). Statements about defects being "open" are historical — see this section for current status. Line anchors drift again as the tree moves; re-verify with `verify-replicate-C/` scripts before quoting numbers.
