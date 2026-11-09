"""Image-map confidence provenance and validation (Issue H)."""

from __future__ import annotations

import json

import pytest

from hannom.t1_map import (
    ImageMapError,
    Pair,
    align_page_groups,
    load_image_map,
    mapping_summary,
    parse_manual_pairs,
    score_pairs_with_anchors,
)
from hannom.models import PageRecord
from pathlib import Path


def _page(no: int, folder: str, ink: float) -> PageRecord:
    return PageRecord(
        book_id="b",
        page_no=no,
        image_name=f"Book.{no:03d}.jpg",
        pdf_page=no,
        sha256=f"sha{no}",
        width=800,
        height=1135,
        path=Path(f"Book.{no:03d}.jpg"),
        folder=folder,
        features={"ink_fraction": ink},
    )


class StubLexicon:
    def __init__(self, mapping: dict[str, list[str]]):
        self.mapping = mapping

    def readings(self, char: str) -> list[str]:
        return list(self.mapping.get(char, []))


def test_pairs_survive_json_round_trip(tmp_path):
    pair = Pair(ch=("Book.001.jpg",), vi=("Book.002.jpg",), note="n",
                confidence=0.75, source="heuristic_mass+anchors", status="verified")
    payload = {"pairs": [pair.to_dict()], "meta": {}}
    path = tmp_path / "image_map.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (loaded,) = load_image_map(path)
    assert loaded.confidence == pytest.approx(0.75)
    assert loaded.source == "heuristic_mass+anchors"
    assert loaded.status == "verified"
    assert loaded.note == "n"


def test_unknown_status_becomes_unresolved_not_verified(tmp_path):
    payload = {"pairs": [{"ch": ["a.jpg"], "vi": ["b.jpg"], "status": "super_reliable"}]}
    path = tmp_path / "image_map.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (loaded,) = load_image_map(path)
    assert loaded.status == "unresolved"


def test_score_pairs_repeated_tokens_stay_unresolved():
    ch = [_page(n, "ch", 0.05) for n in range(4, 0, -1)]
    vi = [_page(n, "vi", 0.05) for n in range(1, 5)]
    for i, page in enumerate(ch):
        page.image_name = f"Book.C{i:03d}.jpg"
    for i, page in enumerate(vi):
        page.image_name = f"Book.V{i:03d}.jpg"
    # Distinct names are required: text evidence is keyed per image.
    pairs = align_page_groups(ch, vi, None, max_group=1)
    assert pairs and all(p.status == "candidate" for p in pairs)
    lexicon = StubLexicon({"字": ["thì"]})
    texts = {pair.ch[0]: "字字" for pair in pairs}
    texts.update({pair.vi[0]: "thì thì" for pair in pairs})
    pairs = score_pairs_with_anchors(pairs, texts, lexicon=lexicon,
                                     verified_min_coverage=0.5)
    # Every Nôm char and every QN token is ambiguous: evidence exists but
    # cannot confirm the pairing → never verified.
    assert all(p.status == "unresolved" for p in pairs)
    assert all(p.confidence == pytest.approx(0.0) for p in pairs)


def test_score_pairs_without_lexicon_keeps_candidate():
    pairs = [Pair(ch=("a.jpg",), vi=("b.jpg",), note="x", source="heuristic_mass", status="candidate")]
    out = score_pairs_with_anchors(pairs, {"a.jpg": "字其", "b.jpg": "thì thế"}, lexicon=None)
    assert out[0].status == "candidate"
    assert out[0].confidence is None


def test_score_pairs_with_unique_evidence_is_verified():
    pair = Pair(ch=("a.jpg",), vi=("b.jpg",), note="x", source="heuristic_mass", status="candidate")
    lexicon = StubLexicon({"之": ["thì"], "其": ["thế"]})
    out = score_pairs_with_anchors(
        [pair], {"a.jpg": "之其", "b.jpg": "thì thế"}, lexicon=lexicon
    )
    assert out[0].status == "verified"
    assert out[0].confidence == pytest.approx(1.0)


def test_score_pairs_repeated_tokens_are_unresolved():
    pair = Pair(ch=("a.jpg",), vi=("b.jpg",), note="x", source="heuristic_mass", status="candidate")
    lexicon = StubLexicon({"字": ["thì"], "其": ["thế"]})
    out = score_pairs_with_anchors(
        [pair], {"a.jpg": "字其字其", "b.jpg": "thì thế thì thế"}, lexicon=lexicon
    )
    # Each reading occurs twice on both sides: no unique evidence.
    assert out[0].status == "unresolved"
    assert out[0].confidence == pytest.approx(0.0)


def test_score_pairs_requires_minimum_anchor_count():
    pair = Pair(ch=("a.jpg",), vi=("b.jpg",), note="x", source="heuristic_mass", status="candidate")
    lexicon = StubLexicon({"之": ["thì"]})
    # One unique anchor but below the minimum-anchor bar of 2 → unresolved.
    out = score_pairs_with_anchors(
        [pair], {"a.jpg": "之沛", "b.jpg": "thì bóng khác"}, lexicon=lexicon
    )
    assert out[0].status == "unresolved"


def test_score_pairs_marks_unresolved_when_no_token_matches():
    pair = Pair(ch=("a.jpg",), vi=("b.jpg",), note="x", source="heuristic_mass", status="candidate")
    lexicon = StubLexicon({"字": ["thì"]})
    out = score_pairs_with_anchors(
        [pair], {"a.jpg": "字字字", "b.jpg": "khac biet hoan toan"}, lexicon=lexicon
    )
    assert out[0].status == "unresolved"
    assert out[0].confidence == pytest.approx(0.0)


def test_manual_pairs_replace_and_validate():
    manual = {
        "pairs": [
            {"ch": ["a.jpg"], "vi": ["b.jpg"], "note": "đúng vì đối chiếu ảnh"},
            {"ch": ["c.jpg"], "vi": ["d.jpg"], "note": "ok"},
        ]
    }
    pairs = parse_manual_pairs(manual)
    assert [p.status for p in pairs] == ["manual", "manual"]
    assert [p.source for p in pairs] == ["manual", "manual"]
    assert all(p.confidence == 1.0 for p in pairs)
    with pytest.raises(ImageMapError):
        parse_manual_pairs({"pairs": [{"ch": [], "vi": []}]})


def test_mapping_summary_counts():
    pairs = [
        Pair(ch=("a",), vi=("b",), status="verified"),
        Pair(ch=("c",), vi=("d",), status="candidate"),
        Pair(ch=("e",), vi=("f",), status="unresolved"),
        Pair(ch=("g",), vi=("h",), status="unresolved"),
    ]
    summary = mapping_summary(pairs)
    assert summary == {"pairs": 4, "verified": 1, "candidate": 1,
                       "unresolved": 2, "manual": 0}
