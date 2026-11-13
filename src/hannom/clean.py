"""Stage 5: conservative text cleaning and normalization.

The cleaners here are intentionally narrow. They remove things the guideline
names explicitly (page numbers, running headers/footers, control characters,
duplicate OCR lines) and normalize Unicode/punctuation. They do **not**
modernize archaic Vietnamese, invent punctuation, or guess illegible Nôm
characters. Anything uncertain is returned as a flag for human review.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Sequence

MASK = "[MASK]"
MASK_LEN = 6
REPLACEMENT = "\u3013"  # 〓, the guideline's unencodable-character marker

# CJK blocks that can contain Hán/Nôm ideographs. Include extensions and
# compatibility ideographs; do not include kana, hangul, or Latin.
CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0x20000, 0x2A6DF),  # Extension B
    (0x2A700, 0x2B73F),  # Extension C
    (0x2B740, 0x2B81F),  # Extension D
    (0x2B820, 0x2CEAF),  # Extension E
    (0x2CEB0, 0x2EBEF),  # Extension F
    (0x2EBF0, 0x2EE5F),  # Extension I
    (0x30000, 0x3134F),  # Extension G
    (0x31350, 0x323AF),  # Extension H
    (0x2F800, 0x2FA1F),  # Compatibility Ideographs Supplement
)

NOM_PUNCT_MAP = {
    ",": "\u3001",   # 、
    ".": "\u3002",   # 。
    "!": "\uFF01",   # ！
    "?": "\uFF1F",   # ？
    ";": "\uFF1B",   # ；
    ":": "\uFF1A",   # ：
    "\uFF0C": "\u3001",  # ，→、 (fullwidth comma is the Nôm equivalent of 、)
}

# Abbreviations ending with a full stop that never open a new sentence.
# (tp./tr. are Vietnamese: "Tp. Hồ Chí Minh", "tr. 3" — both mid-sentence.)
QN_ABBREVIATIONS = frozenset(
    {"mr", "mrs", "ms", "dr", "st", "no", "v", "p", "fig", "tp", "tr", "vnd"}
)

TERMINAL_NOM = set("\u3002\uFF01\uFF1F\uFF1B\uFF1A")


def _uppercase_class(ranges: tuple[tuple[int, int], ...]) -> str:
    """Uppercase (general-category ``Lu``) chars found in ``ranges``.

    Used to build sentence-splitting lookahead classes. The hand-written
    range ``À-Ỹ`` (U+00C0–U+1EF8) matched lowercase letters as well as
    Greek, Cyrillic, Hebrew, Arabic, Armenian and unassigned code points;
    restricting to Unicode's ``Lu`` category inside the Latin blocks keeps
    every Latin uppercase letter and drops everything else.
    """
    seen: set[str] = set()
    for lo, hi in ranges:
        for cp in range(lo, hi + 1):
            ch = chr(cp)
            if unicodedata.category(ch) == "Lu":
                seen.add(ch)
    return "".join(sorted(seen))


# Latin blocks carrying Vietnamese (and other Latin) uppercase letters:
# Latin-1 Supplement, Latin Extended-A, Latin Extended-B, Latin Extended Additional.
VIETNAMESE_UPPER_CLASS = _uppercase_class(
    ((0x0041, 0x005A), (0x00A1, 0x00FF), (0x0100, 0x017F), (0x0180, 0x024F), (0x1E00, 0x1EFF))
)

PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:[-–—–]\s*)?(?:\d{1,4}|[ivxlcdmIVXLCDM]{1,8})(?:\s*[-–—–])?\s*$"
)
RUNNING_LABEL_RE = re.compile(
    r"^\s*(?:trang|page|p\.)\s*\d{1,4}\s*$", re.IGNORECASE
)
FOOTNOTE_RE = re.compile(r"^\s*(?:[*†‡]+|\(\d{1,3}\)|\d{1,3}[.)])\s+\S")
INLINE_REF_RE = re.compile(r"(?<=\S)\[\d{1,3}\]")
CONTROL_RE = re.compile(r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]")
SPACE_RE = re.compile(r"[ \t\u00A0\u2000-\u200A\u202F\u205F\u3000]+")
MULTISPACE_RE = re.compile(r"\s+")
CURLY_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201C": '"', "\u201D": '"'})


@dataclass
class CleanedPage:
    book_id: str
    page_no: int
    image_name: str
    script: str
    text: str
    lines: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    dropped_lines: list[str] = field(default_factory=list)
    replacements: dict[str, int] = field(default_factory=dict)
    marker: int | None = None

    def to_dict(self) -> dict:
        d = {
            "book_id": self.book_id,
            "page_no": self.page_no,
            "image_name": self.image_name,
            "script": self.script,
            "text": self.text,
            "lines": self.lines,
            "flags": self.flags,
            "dropped_lines": self.dropped_lines,
            "replacements": self.replacements,
        }
        if self.marker is not None:
            d["marker"] = self.marker
        return d


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def is_nom_char(ch: str) -> bool:
    if len(ch) != 1:
        return False
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in CJK_RANGES)


def count_nom_chars(text: str) -> int:
    return sum(1 for ch in text if is_nom_char(ch))


def is_cjk_punctuation(ch: str) -> bool:
    code = ord(ch)
    return 0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFF65


def is_safe_codepoint(ch: str) -> bool:
    if ch == REPLACEMENT or ch in "[]MASK":
        return True
    category = unicodedata.category(ch)
    # Guideline: chars not in any Hán Nôm font must become 〓. Private-use
    # (Co) and unassigned (Cn) code points render as tofu in the reference
    # fonts, so they are treated as unencodable rather than safe.
    return category not in {"Cc", "Cf", "Cs", "Co", "Cn"}


def sanitize_nom_text(text: str) -> tuple[str, dict[str, int], list[str]]:
    """Replace unencodable/unsafe characters with 〓 and report them."""
    out: list[str] = []
    counts: dict[str, int] = {}
    flags: list[str] = []
    for ch in nfc(text):
        if ch.isspace():
            continue
        if is_safe_codepoint(ch):
            out.append(ch)
        else:
            out.append(REPLACEMENT)
            counts[ch] = counts.get(ch, 0) + 1
    if counts:
        flags.append("NOM_UNENCODABLE_REPLACED")
    return "".join(out), counts, flags


def normalize_mask(text: str) -> str:
    """Normalize harmless mask variants; never create a mask from text."""
    text = text.replace("\uFF3B", "[").replace("\uFF3D", "]")
    text = re.sub(r"\[\s*MASK\s*\]", MASK, text, flags=re.IGNORECASE)
    return text


def remove_control(text: str) -> str:
    return CONTROL_RE.sub("", text)


def normalize_nom_punctuation(text: str, *, convert_ascii: bool = True) -> str:
    if not convert_ascii:
        return text
    return "".join(NOM_PUNCT_MAP.get(ch, ch) for ch in text)


def normalize_qn_punctuation(text: str) -> str:
    text = text.translate(CURLY_QUOTES)
    text = text.replace("\u2026", "...")
    text = text.replace("\u00A0", " ")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return text


def is_page_number_line(line: str) -> bool:
    return bool(PAGE_NUMBER_RE.match(line) or RUNNING_LABEL_RE.match(line))


def looks_like_footnote(line: str) -> bool:
    return bool(FOOTNOTE_RE.match(line))


def _strip_inline_refs(text: str) -> tuple[str, bool]:
    new = INLINE_REF_RE.sub("", text)
    return new, new != text


# Full-page OCR transcription produces a single giant "line" per page, so
# the margin machinery (which inspects each page's marginal lines) never
# sees the running page marker and lets it pass through. The two concrete
# forms observed in both Book 3 runs are stripped here, in a deliberately
# narrow way:
#
#   leading: '-14-', '- 38 -', '-30 - (93) Sửa Lưới', '-10 ( 113 )'
#   trailing: the literal book-title footer, e.g. 'Sửa Lứỡi' / 'Sửa Lưới'
#
# Both removals are counted and flagged, never silent.
# The leading dash is mandatory: every recorded page marker starts with one
# (e.g. `-11 - (274)', `-14-'), and the number must be terminated by a dash,
# a parenthesized print number, or end-of-line — otherwise a bare '-7 some
# text' heading would be over-stripped. Requiring dashes/parens also prevents
# the bounded digits group from backtracking into and splitting a bare
# 4-digit year that has no terminator. Multi-line markers such as
# `-14\n(271)' are kept as one match (`\s` spans newlines) by design.
_FULLPAGE_LEADING_MARK = re.compile(
    r"^\s*-\s*\d{1,4}(?:\s*[-–—]\s*(?:\(\s*\d{2,4}\s*\))?|\s*\(\s*\d{2,4}\s*\)|\s*$)(?:[.\-–—]\s*)?"
)
# Anchored pattern for the printed cross-reference marker inside a dropped
# line (the Nôm printed page the QN page pairs with). Requires the `- N -`
# context so stray footnote parens never match.
_MARKER_LINE_RE = re.compile(
    r"^\s*-?\s*\d{1,4}\s*[-–—]?\s*\(\s*(\d{2,4})\s*\)"
)


def extract_qn_marker(dropped: list[str]) -> int | None:
    """Return the Nôm printed page number from a dropped header line."""
    for raw in dropped:
        match = _MARKER_LINE_RE.match(str(raw))
        if match:
            return int(match.group(1))
    return None
_FULLPAGE_TRAILING_TITLES = (
    "sua luoi",  # flat form of every tonal/casing variant of the book title
    "sua luoi quyen",
)


def _flat_letters(text: str) -> str:
    return "".join(
        ch
        for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    ).casefold()


def _strip_leading_page_marker(line: str) -> tuple[str, bool, str]:
    match = _FULLPAGE_LEADING_MARK.match(line)
    if match is None:
        return line, False, ""
    return line[match.end():].strip(), True, match.group(0).strip()


def _strip_trailing_title(line: str) -> tuple[str, str, str]:
    """Strip a trailing book-title colophon from a line.

    Returns ``(line, disposition, dropped)`` where disposition is one of:

    - ``"removed"``: the line was either the title itself (empty remainder)
      or a remainder ending with sentence/dash punctuation — the shapes
      observed for print colophons. The line is returned stripped.
    - ``"suspect"``: the remainder looks like body text (the book's theme
      words can legitimately occur at the end of body lines). The line is
      returned unchanged; the caller flags it for human review instead of
      silently deleting content.
    - ``"none"``: no trailing title was present.
    """
    if not line:
        return line, "none", ""
    flat_line = _flat_letters(line)
    for flat_title in _FULLPAGE_TRAILING_TITLES:
        if not flat_line.endswith(flat_title):
            continue
        # Remove the exact suffix span of the original line whose flat
        # form matches the title.
        for span in range(1, len(line) + 1):
            suffix = line[len(line) - span :]
            if _flat_letters(suffix) == flat_title:
                rest = line[: len(line) - span].rstrip()
                if not rest:
                    # Title-only line (an apparatus/colophon line): safe to drop.
                    return "", "removed", suffix.strip()
                if rest[-1] in ".:;!?…)]»\"'-–—":
                    return rest, "removed", suffix.strip()
                return line, "suspect", suffix.strip()
    return line, "none", ""


def _join_hyphenated_lines(lines: Sequence[str]) -> tuple[list[str], int]:
    """Join OCR line breaks, keeping meaningful name hyphens.

    Lines are joined with a single space, as the guideline requires. A
    line-final hyphen is treated as a line-break artifact and dropped (with a
    single space retained) in every case except a single-character
    upper-case prior token such as `A-ve`, where the hyphen is meaningful.

    Returns ``(joined_lines, joined_count)``; ``joined_count`` counts the
    hyphen joins applied so callers can flag them.
    """
    out: list[str] = []
    joined = 0
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if out and out[-1].endswith("-"):
            prev = out.pop().rstrip()
            before = re.search(r"(\S+)-$", prev)
            prior_token = before.group(1) if before else ""
            keep_hyphen = bool(re.fullmatch(r"[A-Z]", prior_token))
            if keep_hyphen:
                out.append(prev + line)
            else:
                out.append(prev[:-1] + " " + line)
            joined += 1
        else:
            out.append(line)
    return out, joined


def _dedupe_consecutive(lines: Iterable[str]) -> tuple[list[str], list[str]]:
    out: list[str] = []
    dropped: list[str] = []
    for line in lines:
        if out and line == out[-1]:
            dropped.append(line)
        else:
            out.append(line)
    return out, dropped


def _line_is_margin_noise(
    line: str,
    *,
    index: int,
    total: int,
    running_lines: set[str] | None,
) -> bool:
    if is_page_number_line(line):
        return True
    normalized = normalize_for_running_key(line)
    if running_lines and normalized in running_lines:
        return True
    # Footnote markers near the bottom of a page are usually apparatus, not
    # translated content. Keep the rule narrow to avoid deleting dialogue.
    if total >= 4 and index >= total - 2 and looks_like_footnote(line):
        return True
    return False


def normalize_for_running_key(text: str) -> str:
    text = nfc(text).casefold()
    text = re.sub(r"\d+", "#", text)
    return MULTISPACE_RE.sub(" ", text).strip()


def detect_running_lines(
    lines_by_page: Sequence[Sequence[str]],
    *,
    min_pages: int = 5,
    max_ratio: float = 0.35,
    max_length: int = 80,
) -> set[str]:
    """Find short lines repeated at page margins across many pages.

    Only the first and last two lines of each page are considered, which
    avoids treating repeated liturgical formulas in the body as headers.
    """
    if len(lines_by_page) < min_pages:
        return set()
    counts: dict[str, int] = {}
    for lines in lines_by_page:
        clean = [ln.strip() for ln in lines if ln.strip()]
        if not clean:
            continue
        candidates = {normalize_for_running_key(x) for x in clean[:2] + clean[-2:]}
        for candidate in candidates:
            if candidate and len(candidate) <= max_length and not is_page_number_line(candidate):
                counts[candidate] = counts.get(candidate, 0) + 1
    threshold = max(min_pages, int(len(lines_by_page) * max_ratio))
    return {line for line, count in counts.items() if count >= threshold}


def _split_embedded_newlines(lines: Sequence[str]) -> list[str]:
    """Split lines on embedded newlines.

    Vintern and similar engines emit one giant page line per page with real
    newlines inside; the margin machinery (first/last lines per page) needs
    physical lines to see page markers at all.
    """
    out: list[str] = []
    for raw in lines:
        out.extend(str(raw).split("\n"))
    return out


def clean_nom_lines(
    lines: Sequence[str],
    *,
    running_lines: set[str] | None = None,
    drop_page_numbers: bool = True,
) -> CleanedPage | tuple[list[str], list[str], dict[str, int], list[str]]:
    """Clean Nôm lines and return a page object when book metadata is given.

    For direct use this function accepts no metadata and returns a tuple; the
    public page-level wrapper is clean_nom_page().
    """
    normalized: list[str] = []
    dropped: list[str] = []
    flags: list[str] = []
    pieces = _split_embedded_newlines(lines)
    total = len(pieces)
    for index, raw in enumerate(pieces):
        line = nfc(remove_control(str(raw))).strip()
        if not line:
            continue
        if drop_page_numbers and _line_is_margin_noise(
            line, index=index, total=total, running_lines=running_lines
        ):
            dropped.append(line)
            if is_page_number_line(line):
                flags.append("PAGE_NUMBER_REMOVED")
            continue
        line, refs_removed = _strip_inline_refs(line)
        if refs_removed:
            flags.append("INLINE_REF_REMOVED")
        line, mark_removed, mark_text = _strip_leading_page_marker(line)
        if mark_removed:
            flags.append("PAGE_MARK_REMOVED")
            dropped.append(mark_text)
        line = normalize_nom_punctuation(line)
        line = SPACE_RE.sub("", line)
        if not line:
            continue
        normalized.append(line)
    normalized, dupes = _dedupe_consecutive(normalized)
    if dupes:
        dropped.extend(dupes)
        flags.append("DUPLICATE_LINES_REMOVED")
    # Replace unencodable/unsafe code points with 〓 (the guideline's marker).
    sanitized: list[str] = []
    replacements: dict[str, int] = {}
    sanitized_any = False
    for line in normalized:
        cleaned_line, repl, _ = sanitize_nom_text(line)
        if cleaned_line:
            sanitized.append(cleaned_line)
        for code, count in repl.items():
            replacements[code] = replacements.get(code, 0) + count
        sanitized_any = sanitized_any or bool(repl)
    if sanitized_any:
        flags.append("NOM_UNENCODABLE_REPLACED")
    normalized = sanitized
    text = "".join(normalized)
    for match in re.finditer(r"\[[^\]]*MASK[^\]]*\]", text, flags=re.IGNORECASE):
        if match.group(0) != MASK:
            flags.append("MASK_LENGTH_INVALID")
            break
    return normalized, dropped, replacements, sorted(set(flags))


def clean_nom_page(
    book_id: str,
    page_no: int,
    image_name: str,
    lines: Sequence[str],
    *,
    running_lines: set[str] | None = None,
) -> CleanedPage:
    cleaned = clean_nom_lines(lines, running_lines=running_lines)
    assert isinstance(cleaned, tuple)
    normalized, dropped, replacements, flags = cleaned
    text = "".join(normalized)
    if not text:
        flags = sorted(set(flags) | {"EMPTY_AFTER_CLEAN"})
    return CleanedPage(
        book_id=book_id,
        page_no=page_no,
        image_name=image_name,
        script="nom",
        text=text,
        lines=normalized,
        flags=flags,
        dropped_lines=dropped,
        replacements=replacements,
        marker=extract_qn_marker(dropped),
    )


def clean_quoc_ngu_lines(
    lines: Sequence[str],
    *,
    running_lines: set[str] | None = None,
    drop_page_numbers: bool = True,
) -> tuple[list[str], list[str], list[str]]:
    prepared: list[str] = []
    dropped: list[str] = []
    flags: list[str] = []
    # Pass 1: strip the full-page leading marker first (it may span an
    # embedded newline, e.g. `-14\n(271)'), then expand to physical lines so
    # the margin machinery (page numbers, running lines, footnotes) sees
    # each line individually.
    physical: list[str] = []
    for raw in lines:
        raw_line = nfc(remove_control(str(raw)))
        line, mark_removed, mark_text = _strip_leading_page_marker(raw_line)
        if mark_removed:
            flags.append("PAGE_MARK_REMOVED")
            dropped.append(mark_text)
        physical.extend(line.split("\n"))
    pieces = [p.strip() for p in physical if p.strip()]
    total = len(pieces)
    for index, line in enumerate(pieces):
        if drop_page_numbers and _line_is_margin_noise(
            line, index=index, total=total, running_lines=running_lines
        ):
            dropped.append(line)
            if is_page_number_line(line):
                flags.append("PAGE_NUMBER_REMOVED")
            continue
        line, refs_removed = _strip_inline_refs(line)
        if refs_removed:
            flags.append("INLINE_REF_REMOVED")
        line = normalize_qn_punctuation(line)
        line = SPACE_RE.sub(" ", line).strip()
        prepared.append(line)
    joined, n_joins = _join_hyphenated_lines(prepared)
    if n_joins:
        flags.append("HYPHEN_JOINED")
    final: list[str] = []
    for line in joined:
        line = MULTISPACE_RE.sub(" ", line).strip()
        if not line:
            continue
        line, disposition, footer_text = _strip_trailing_title(line)
        if disposition == "removed":
            flags.append("FOOTER_TITLE_REMOVED")
            dropped.append(footer_text)
        elif disposition == "suspect":
            flags.append("FOOTER_TITLE_SUSPECT")
        if line:
            final.append(line)
    final, dupes = _dedupe_consecutive(final)
    if dupes:
        dropped.extend(dupes)
        flags.append("DUPLICATE_LINES_REMOVED")
    # One more pass for page-number-shaped lines that surfaced only after
    # the footer strip (e.g. '- 1\nSỬA LƯỚI QUYỀN' -> '-1').
    stable: list[str] = []
    for line in final:
        if drop_page_numbers and is_page_number_line(line):
            dropped.append(line)
            flags.append("PAGE_NUMBER_REMOVED")
            continue
        stable.append(line)
    return stable, dropped, sorted(set(flags))


def clean_quoc_ngu_page(
    book_id: str,
    page_no: int,
    image_name: str,
    lines: Sequence[str],
    *,
    running_lines: set[str] | None = None,
) -> CleanedPage:
    cleaned, dropped, flags = clean_quoc_ngu_lines(lines, running_lines=running_lines)
    text = " ".join(cleaned)
    if not text:
        flags = sorted(set(flags) | {"EMPTY_AFTER_CLEAN"})
    return CleanedPage(
        book_id=book_id,
        page_no=page_no,
        image_name=image_name,
        script="qn",
        text=text,
        lines=cleaned,
        flags=flags,
        dropped_lines=dropped,
        marker=extract_qn_marker(dropped),
    )


def clean_page_lines(
    book_id: str,
    page_no: int,
    image_name: str,
    script: str,
    lines: Sequence[str],
    *,
    running_lines: set[str] | None = None,
) -> CleanedPage:
    if script == "nom":
        return clean_nom_page(
            book_id, page_no, image_name, lines, running_lines=running_lines
        )
    return clean_quoc_ngu_page(
        book_id, page_no, image_name, lines, running_lines=running_lines
    )


def validate_clean_text(text: str, script: str) -> list[str]:
    """Return blocking text-integrity issues for one cell."""
    issues: list[str] = []
    if nfc(text) != text:
        issues.append("text is not NFC")
    if CONTROL_RE.search(text):
        issues.append("text contains control characters")
    if "\n" in text or "\r" in text:
        issues.append("text contains a newline")
    # Reject characters that are not safe for the deliverable at all:
    # private-use (Co), unassigned (Cn), format (Cf), surrogates (Cs) and
    # control (Cc) — unless the character is 〓 (U+3013) or part of the
    # literal [MASK] token (see is_safe_codepoint).
    for char in text:
        if not is_safe_codepoint(char):
            issues.append(
                f"unencodable code point U+{ord(char):04X} ({unicodedata.name(char, 'UNKNOWN')})"
            )
    if script == "nom":
        if " " in text:
            issues.append("Nôm text contains spaces")
    # The literal [MASK] token must be exactly six code points and must not be
    # embedded in a longer bracketed token (runs for every script).
    for match in re.finditer(r"\[[^\]]*MASK[^\]]*\]", text, flags=re.IGNORECASE):
        if match.group(0) != MASK:
            issues.append(f"invalid mask token {match.group(0)!r}")
    return issues
