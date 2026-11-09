# Review guide

Only flagged items need human work. Codes: `DICT_MISS`, `DIFF_SEMANTIC`, `DIFF_UNVERIFIED`, `OCR_ENGINE_DISAGREE`, `ALIGN_LOW_CONF`, `PROPER_NAME_CANDIDATE`, `IMAGE_REC_FALLBACK`, `MISSING_CLEAN_PAGE`.

- Unknown or ambiguous semantics go to review; the pipeline never auto-reds an unknown character and never auto-yellows.
- Guideline-legal yellow is limited to: proper-name/year count mismatch, predicted Nôm from blur, predicted Nôm/QN from a missing scan page. Apply these via patches.
- Patches are JSONL in `data/review/<book>.patches.jsonl` and are reapplied after `textdiff`; reruns never overwrite them.
