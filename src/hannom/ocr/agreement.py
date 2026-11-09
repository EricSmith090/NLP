"""Engine agreement and conservative consensus selection."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from ..models import OCRResult


def normalize_for_compare(text: str, script: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    text = re.sub(r"\s+", "", text) if script == "nom" else re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def text_similarity(a: str, b: str, script: str) -> float:
    a_n = normalize_for_compare(a, script)
    b_n = normalize_for_compare(b, script)
    if not a_n and not b_n:
        return 1.0
    if not a_n or not b_n:
        return 0.0
    return float(SequenceMatcher(None, a_n, b_n).ratio())


def result_text(result: OCRResult) -> str:
    return "\n".join(line.text for line in result.lines if line.text)


def _mean_confidence(result: OCRResult) -> float:
    """Mean line confidence; the spec calls for 'highest-confidence result'.

    A single high-confidence line (e.g. a folio page number like '- 65 -')
    must not outvote a body of real text lines.
    """
    confidences = [
        float(line.confidence)
        for line in result.lines
        if line.confidence is not None
    ]
    if not confidences:
        # No calibrated confidence (Vintern). Rank by text coverage so a
        # substantive transcription is not silently outvoted by a stub.
        return len(result_text(result)) / 10000.0
    return sum(confidences) / len(confidences)


def choose_consensus(
    results: list[OCRResult],
    script: str,
    threshold: float = 0.85,
) -> tuple[OCRResult, list[str]]:
    """Choose the highest-confidence result, flagging disagreement.

    We keep the primary result's boxes. A text-only second opinion must not
    replace a boxed primary result, because PPOCRLabel requires coordinates.
    """
    if not results:
        raise ValueError("no OCR results to compare")
    with_boxes = [r for r in results if r.lines and all(len(line.points) == 4 for line in r.lines)]
    pool = with_boxes or results
    best = max(pool, key=_mean_confidence)
    warnings: list[str] = []
    texts = [result_text(r) for r in results]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            sim = text_similarity(texts[i], texts[j], script)
            if sim < threshold:
                warnings.append(f"OCR_ENGINE_DISAGREE:{results[i].engine}:{results[j].engine}:{sim:.2f}")
    if not with_boxes:
        warnings.append("BBOX_MISSING")
    best.warnings.extend(sorted(set(warnings)))
    return best, best.warnings
