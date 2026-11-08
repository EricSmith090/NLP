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
}

TERMINAL_NOM = set("\u3002\uFF01\uFF1F\uFF1B\uFF1A")
TERMINAL_QN = set(".!?\u2026")

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

    def to_dict(self) -> dict:
        return {
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
    # Cc/Cf/Cs/Co/Cn are control, format, surrogate, private-use, unassigned.
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


def _join_hyphenated_lines(lines: Sequence[str]) -> list[str]:
    """Join OCR line breaks, keeping meaningful name hyphens.

    A line-final hyphen is treated as a line-break artifact when the next
    line starts with a lowercase letter and the preceding token is not a
    one-letter name/initial (e.g. A-ve must remain A-ve).
    """
    out: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if out and out[-1].endswith("-"):
            prev = out.pop().rstrip()
            before = re.search(r"(\S+)-$", prev)
            prior_token = before.group(1) if before else ""
            keep_hyphen = bool(re.fullmatch(r"[A-Z]", prior_token)) or (
                any(c.isupper() for c in prior_token) and line[:1].islower()
            )
            if keep_hyphen:
                out.append(prev + line)
            elif line[:1].islower():
                out.append(prev[:-1] + line)
            else:
                out.append(prev + " " + line)
        else:
            out.append(line)
    return out


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
    total = len(lines)
    for index, raw in enumerate(lines):
        line = nfc(remove_control(str(raw))).strip()
        if not line:
            continue
        if drop_page_numbers and _line_is_margin_noise(
            line, index=index, total=total, running_lines=running_lines
        ):
            dropped.append(line)
            continue
        line, refs_removed = _strip_inline_refs(line)
        if refs_removed:
            flags.append("INLINE_REF_REMOVED")
        line = normalize_nom_punctuation(line)
        line = SPACE_RE.sub("", line)
        if not line:
            continue
        normalized.append(line)
    normalized, dupes = _dedupe_consecutive(normalized)
    if dupes:
        dropped.extend(dupes)
        flags.append("DUPLICATE_LINES_REMOVED")
    text = "".join(normalized)
    text, replacements, sanitize_flags = sanitize_nom_text(text)
    flags.extend(sanitize_flags)
    if MASK in text and len(MASK) != MASK_LEN:  # defensive invariant
        flags.append("MASK_LENGTH_INVALID")
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
    return CleanedPage(
        book_id=book_id,
        page_no=page_no,
        image_name=image_name,
        script="nom",
        text="".join(normalized),
        lines=normalized,
        flags=flags,
        dropped_lines=dropped,
        replacements=replacements,
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
    total = len(lines)
    for index, raw in enumerate(lines):
        line = nfc(remove_control(str(raw))).strip()
        if not line:
            continue
        if drop_page_numbers and _line_is_margin_noise(
            line, index=index, total=total, running_lines=running_lines
        ):
            dropped.append(line)
            continue
        line, refs_removed = _strip_inline_refs(line)
        if refs_removed:
            flags.append("INLINE_REF_REMOVED")
        line = normalize_qn_punctuation(line)
        line = SPACE_RE.sub(" ", line).strip()
        prepared.append(line)
    joined = _join_hyphenated_lines(prepared)
    final: list[str] = []
    for line in joined:
        line = MULTISPACE_RE.sub(" ", line).strip()
        if line:
            final.append(line)
    final, dupes = _dedupe_consecutive(final)
    if dupes:
        dropped.extend(dupes)
        flags.append("DUPLICATE_LINES_REMOVED")
    return final, dropped, sorted(set(flags))


def clean_quoc_ngu_page(
    book_id: str,
    page_no: int,
    image_name: str,
    lines: Sequence[str],
    *,
    running_lines: set[str] | None = None,
) -> CleanedPage:
    cleaned, dropped, flags = clean_quoc_ngu_lines(lines, running_lines=running_lines)
    return CleanedPage(
        book_id=book_id,
        page_no=page_no,
        image_name=image_name,
        script="qn",
        text=" ".join(cleaned),
        lines=cleaned,
        flags=flags,
        dropped_lines=dropped,
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
    if script == "nom":
        if " " in text:
            issues.append("Nôm text contains spaces")
        # The literal token must be exactly six code points and must not be
        # embedded in a longer bracketed token.
        for match in re.finditer(r"\[[^\]]*MASK[^\]]*\]", text, flags=re.IGNORECASE):
            if match.group(0) != MASK:
                issues.append(f"invalid mask token {match.group(0)!r}")
    if text.count(MASK) != len(re.findall(r"\[MASK\]", text)):
        issues.append("mask token count is inconsistent")
    return issues
