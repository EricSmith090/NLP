from __future__ import annotations

import json
from pathlib import Path

from hannom.dictionary.book_lexicon import BookLexicon
from hannom.models import AlignmentRow, DiffElement
from hannom.orchestrator import recompute_text_diff


def _lexicon(tmp_path: Path) -> BookLexicon:
    path = tmp_path / "lexicon.json"
    path.write_text(
        json.dumps(
            {
                "meta": {},
                "readings": {"一": {"nhat": 3, "nhất": 5, "chi": 1}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return BookLexicon(path)


def _row(sentence_id: str, ch: str, vi: str, diff: list[DiffElement] | None) -> AlignmentRow:
    return AlignmentRow(
        img_id="Test.001.jpg",
        sentence_id=sentence_id,
        ch_txt=ch,
        vi_txt=vi,
        text_diff=diff,
    )


def test_null_row_is_preserved_even_with_lexicon(tmp_path: Path):
    """Regression: CSV round-trip drops the NON_ONE_TO_ONE flag, so the
    recompute path cannot use it; a null row must stay null."""
    row = _row("Test.001.1", "一難也", "nhất nhất.", None)
    out = recompute_text_diff([row], lexicon=_lexicon(tmp_path), dictionary=None, force_recompute=False)
    assert out[0].text_diff is None


def test_force_recompute_rescores_null_row(tmp_path: Path):
    row = _row("Test.001.1", "一", "nhất.", None)
    out = recompute_text_diff([row], lexicon=_lexicon(tmp_path), dictionary=None, force_recompute=True)
    assert out[0].text_diff is not None


def test_scored_row_is_recomputed(tmp_path: Path):
    element = DiffElement(
        nom_pos=((0, 1),),
        nom_sub_text="一",
        vi_pos=((0, 4),),
        vi_sub_text="nhất",
        type="error",
    )
    row = _row("Test.001.1", "一", "nhất.", [element])
    out = recompute_text_diff([row], lexicon=_lexicon(tmp_path), dictionary=None, force_recompute=False)
    assert isinstance(out[0].text_diff, list)
