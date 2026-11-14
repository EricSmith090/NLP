"""Kim Hán Nôm private-use (PUA) → standard Nôm code point mapping.

The assigned books are typeset with a Kim Hán Nôm font whose glyphs
occupy private-use code points (Plane 15/16 and the BMP PUA planes).
Unicode, the official dictionary drop and the fonts referenced by the
guideline know nothing about those code points, so the pipeline cannot
match, learn or count them (finding H1 in ``Doc/verify-G-dictionary.md``).

This module keeps the human-curated mapping between PUA code points and
standard Nôm characters. It is deliberately:

- **opt-in.** ``set_enabled`` gates whether PUA code points are treated
  as Nôm characters at all. Default: disabled, so the code behaves
  byte-identically to the pre-fix pipeline until a human operator
  switches it on (``KHN_PUA_ENABLED`` env var or ``hannom.pua_map`` API).
- **evidence-based.** Seed entries in ``configs/khn_pua_map.yaml`` cite
  their source. An unmapped PUA code point is **never** guessed: it maps
  to nothing and is handled by the unchanged 〓 replacement path in the
  clean stage. Adding a mapping requires explicit human verification of
  the glyph against the scan.
- **strictly validated.** ``load_pua_map`` accepts only single PUA
  code points as keys and single ideographic characters as values;
  invalid entries are reported, never applied.

Enable order: ``set_mapping(load_pua_map(path))`` then ``set_enabled(True)``.
``reset()`` restores the disabled, empty-map default (used by tests).
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

# CJK / Compatibility ideograph ranges (mirror of clean.CJK_RANGES plus
# the supplementary planes used for ideographs). Kept local on purpose:
# importing hannom.clean from here would create an import cycle.
_IDEOGRAPH_RANGES: tuple[tuple[int, int], ...] = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF),
    (0x2EBF0, 0x2EE5F),
    (0x30000, 0x3134F),
    (0x31350, 0x323AF),
    (0x2F800, 0x2FA1F),
)

PUA_RANGES: tuple[tuple[int, int], ...] = (
    (0xE000, 0xF8FF),        # BMP private use
    (0xF0000, 0x10FFFD),     # supplementary private use (Kim Hán Nôm font)
)

_MAPPING: dict[int, str] = {}
_ENABLED: bool = False


def is_khn_pua_char(ch: str) -> bool:
    if len(ch) != 1:
        return False
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in PUA_RANGES)


def is_ideograph(ch: str) -> bool:
    if len(ch) != 1:
        return False
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _IDEOGRAPH_RANGES)


def set_mapping(mapping: dict[int, str]) -> None:
    global _MAPPING
    _MAPPING = dict(mapping)


def set_enabled(enabled: bool) -> None:
    global _ENABLED
    _ENABLED = bool(enabled)


def is_enabled() -> bool:
    return _ENABLED


def mapped_pua(ch: str) -> str | None:
    """Return the standard Nôm character for ``ch`` (enabled + mapped), else None."""
    if not _ENABLED or len(ch) != 1:
        return None
    return _MAPPING.get(ord(ch))


def reset() -> None:
    global _MAPPING, _ENABLED
    _MAPPING = {}
    _ENABLED = False


def load_pua_map(path: str | Path) -> tuple[dict[int, str], list[str]]:
    """Load a YAML mapping ``{hex_codepoint: target_char}``.

    Returns (mapping, problems). Invalid entries are skipped and reported,
    never applied. A missing file yields ({}, [problem]) — the caller may
    still run with PUA enabled (unmapped code points stay unmatchable,
    exactly as before); it is the operator's decision whether to enable.
    """
    import yaml

    problems: list[str] = []
    mapping: dict[int, str] = {}
    path = Path(path)
    if not path.exists():
        return {}, [f"pua map not found: {path}"]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # unreadable YAML: report, never apply
        return {}, [f"pua map unreadable: {exc}"]
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        return {}, [f"pua map root must be a mapping, got {type(raw).__name__}"]
    for key, value in raw.items():
        try:
            code = int(str(key), 16)
        except (TypeError, ValueError):
            problems.append(f"key {key!r}: not a hex code point")
            continue
        if not (0xE000 <= code <= 0xF8FF or 0xF0000 <= code <= 0x10FFFD):
            problems.append(f"key U+{code:04X}: not a PUA code point")
            continue
        if not isinstance(value, str) or len(value) != 1:
            problems.append(f"key U+{code:04X}: value must be a single character, got {value!r}")
            continue
        target = unicodedata.normalize("NFC", value)
        if len(target) != 1 or not is_ideograph(target):
            problems.append(f"key U+{code:04X}: value {value!r} is not a single ideographic character")
            continue
        mapping[code] = target
    return mapping, problems


def enable_from_env() -> bool:
    """Enable PUA handling from the environment, if requested.

    ``KHN_PUA_ENABLED=1`` (or ``true``/``yes``) enables the mapping loaded
    from ``KHN_PUA_MAP``. The default map is ``configs/khn_pua_map.yaml``
    resolved against the repository root (two levels above this module —
    correct for editable installs and source checkouts). Returns True iff
    PUA handling is enabled after the call.
    """
    import os
    from pathlib import Path

    if os.environ.get("KHN_PUA_ENABLED", "").strip().lower() not in {"1", "true", "yes"}:
        return False
    default_map = Path(__file__).resolve().parent.parent.parent / "configs" / "khn_pua_map.yaml"
    path = os.environ.get("KHN_PUA_MAP") or str(default_map)
    mapping, problems = load_pua_map(path)
    for problem in problems:
        import warnings

        warnings.warn(f"KHN PUA map: {problem}")
    set_mapping(mapping)
    set_enabled(True)
    return True
