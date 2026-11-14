"""Tests for hannom.map_repair (content-based image_map repair)."""

from __future__ import annotations

from types import SimpleNamespace

from hannom.map_repair import qn_token_sets, solve


class StubDictionary:
    """Matcher-compatible stub: of(), known(), __len__."""

    def __init__(self, readings: dict[str, list[str]]):
        self._readings = {c: tuple(v) for c, v in readings.items()}

    def of(self, ch: str):
        return set(self._readings.get(ch, ()))

    def known(self, ch: str) -> bool:
        return bool(self._readings.get(ch))

    def __len__(self) -> int:
        return len(self._readings)

    @property
    def source_names(self):
        return list(self._readings)


CHAR_SET = set("的我你是")
READINGS = {ch: (["de"] if ch == "的" else (["wo"] if ch == "我" else ["ni"])) for ch in CHAR_SET}
DICTIONARY = StubDictionary(READINGS)


def test_dp_repairs_wrong_page_pairing():
    # Reading-order sequences where the heuristic mismatched pages;
    # the DP must restore reading order and pair by content.
    ch_pages = ["B.001.jpg", "B.002.jpg"]
    ch_chars = [
        list("的的的的的的的的的的"),
        list("我我的的我我的的的的"),
    ]
    vi_pages = ["B.021.jpg", "B.022.jpg"]
    vi_sets = [
        qn_token_sets("的 的 的 的 的 的 的 的 的 的 。"),
        qn_token_sets("我 我 我的 我 我 的 。"),
    ]
    result = solve(
        ch_pages, ch_chars, vi_pages, vi_sets,
        readings=DICTIONARY,
        skip_penalty=1.5,
    )
    assert len(result.pairs) == 2
    assert result.pairs[0]["ch"] == ["B.001.jpg"]
    assert result.pairs[0]["vi"] == ["B.021.jpg"]
    assert result.pairs[1]["ch"] == ["B.002.jpg"]
    assert result.pairs[1]["vi"] == ["B.022.jpg"]


def test_anchor_must_be_honored_even_if_dp_prefers_otherwise():
    ch_pages = ["B.001.jpg", "B.002.jpg"]
    ch_chars = [list("的的的的的的的的的的"), list("我我的的我我的的的的")]
    vi_pages = ["B.021.jpg", "B.022.jpg"]
    vi_sets = [
        qn_token_sets("的 的 的 的 的 的 的 的 的 的 。"),
        qn_token_sets("我 我 我的 我 我 的 。"),
    ]
    result = solve(
        ch_pages, ch_chars, vi_pages, vi_sets,
        readings=DICTIONARY,
        skip_penalty=0.5,
        anchors=[("B.001.jpg", "B.021.jpg")],
    )
    assert result.pairs[0] == {"ch": ["B.001.jpg"], "vi": ["B.021.jpg"]}
    assert result.anchor_issues == []


def test_anchor_outside_inventory_is_reported_not_silent():
    ch_pages = ["B.001.jpg"]
    ch_chars = [list("的的的的的的的的的的的的的的的的的的的的")]
    vi_pages = ["B.021.jpg"]
    vi_sets = [qn_token_sets("的 的 。")]
    result = solve(
        ch_pages, ch_chars, vi_pages, vi_sets,
        readings=DICTIONARY,
        anchors=[("B.999.jpg", "B.021.jpg")],
    )
    assert any("999" in issue for issue in result.anchor_issues)
