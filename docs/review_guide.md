# Review guide

Only flagged items need human work. Codes: `DICT_MISS`, `DIFF_SEMANTIC`, `DIFF_UNVERIFIED`, `OCR_ENGINE_DISAGREE`, `ALIGN_LOW_CONF`, `PROPER_NAME_CANDIDATE`, `IMAGE_REC_FALLBACK`, `MISSING_CLEAN_PAGE`.

Operational integrity flags (not review content, but surfaced): `LABEL_EMPTY_OCR` (page has no OCR result — boxes `[]`), `OCR_ALL_NOISE` (OCR ran but every line cleaned away — boxes `[]`), `EMPTY_AFTER_CLEAN` (page text became empty after cleaning), `PAGE_MARK_REMOVED` (full-page print marker stripped), `PAGE_NUMBER_REMOVED` (a bare page-number line was dropped), `FOOTER_TITLE_REMOVED` (unambiguous colophon stripped), `FOOTER_TITLE_SUSPECT` (book-title-looking body ending — kept, needs human review), `HYPHEN_JOINED` (line-break hyphen join applied), `CLEAN_TEXT_INVALID` (cleaned text failed `validate_clean_text`).

- Unknown or ambiguous semantics go to review; the pipeline never auto-reds an unknown character and never auto-yellows.
- Guideline-legal yellow is limited to: proper-name/year count mismatch, predicted Nôm from blur, predicted Nôm/QN from a missing scan page. Apply these via patches.
- Patches are JSONL in `data/review/<book>.patches.jsonl` and are reapplied after `textdiff`; reruns never overwrite them.
