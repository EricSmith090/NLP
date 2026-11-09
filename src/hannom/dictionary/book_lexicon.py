"""Per-book learned character-to-syllable evidence.

Evidence classes handled here:

- **Trusted** entries carry explicit provenance (who/what evidence,
  which sentence) and are the only entries used as alignment anchors.
- **Unverified** entries were added without provenance.
- **Legacy** entries come from files written before provenance tracking
  existed.

Unverified and legacy entries are preserved under ``"quarantine"`` in the
JSON file, but ``readings()`` never returns them: they are not trusted
alignment, colouring or learning evidence until a human explicitly
restores them.

Learning policy (both properties are required):

1. The row must carry the ``HUMAN_REVIEWED`` flag (i.e. a reviewer
   signed off on it) — see ``hannom.review.patches``.
2. The character↔syllable correspondence must be unambiguous: exactly
   one Nôm character in the row and either exactly one QN syllable, or a
   dictionary reading present in the row's syllables.

Rows flagged ``NON_ONE_TO_ONE``, ``UNMATCHED_*``, ``ALIGN_LOW_CONF``,
``COSEGMENTED_UNANCHORED``, ``TEXT_DIFF_INVALID`` or review-metadata
failures are never used for active learning. Automated learning can
never consume its own unverified outputs.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..clean import is_nom_char

QN_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

BLOCKING_FLAGS = frozenset(
    {
        "NON_ONE_TO_ONE",
        "UNMATCHED_NOM",
        "UNMATCHED_QN",
        "ALIGNED_MANY_TO_ONE",
        "ALIGNED_ONE_TO_MANY",
        "ALIGNED_MANY_TO_MANY",
        "ALIGN_LOW_CONF",
        "TEXT_DIFF_INVALID",
        "COSEGMENTED_UNANCHORED",
        "REVIEW_METADATA_MISSING",
        "REVIEW_METADATA_MISMATCH",
    }
)


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def qn_syllables(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).casefold()
    return [m.group(0) for m in QN_TOKEN_RE.finditer(text)]


def _reading_forms(reading: str) -> set[str]:
    value = reading.strip().casefold()
    forms = {value, strip_diacritics(value)}
    forms.update(x for x in re.split(r"[\s,;/]+", value) if x)
    forms.update(strip_diacritics(x) for x in list(forms))
    return {x for x in forms if x}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_field(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, key):
        return getattr(row, key)
    if isinstance(row, dict):
        return row.get(key, default)
    return default


def _row_tuple(row: Any) -> tuple[str, str, str, str, list[str]]:
    return (
        str(_row_field(row, "ch_txt", "") or ""),
        str(_row_field(row, "vi_txt", "") or ""),
        str(_row_field(row, "sentence_id", "") or ""),
        str(_row_field(row, "img_id", "") or ""),
        [str(f) for f in (_row_field(row, "flags", []) or [])],
    )


class BookLexicon:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, dict[str, int]] = {}
        self.provenance: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.quarantine_legacy: dict[str, dict[str, int]] = {}
        self.quarantine_unverified: dict[str, dict[str, int]] = {}
        self.meta: dict[str, Any] = {}
        if self.path.exists():
            self.load()

    def available(self) -> bool:
        return bool(self.data) or self.path.exists()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        readings = {
            str(char): {str(k): int(v) for k, v in readings.items()}
            for char, readings in (raw.get("readings", {}) or {}).items()
        }
        quarantine = raw.get("quarantine")
        provenance = raw.get("provenance", {}) or {}

        def _bucket(value: Any) -> dict[str, dict[str, int]]:
            out: dict[str, dict[str, int]] = {}
            if not isinstance(value, dict):
                return out
            for char, readings_map in value.items():
                if isinstance(readings_map, dict):
                    out[str(char)] = {
                        str(k): int(v) for k, v in readings_map.items() if isinstance(v, (int, float, str))
                    }
            return out

        if quarantine is not None:
            self.quarantine_legacy = _bucket(quarantine.get("legacy_without_provenance"))
            self.quarantine_unverified = _bucket(quarantine.get("unverified"))
        trusted: dict[str, dict[str, int]] = {}
        if quarantine is None:
            # Legacy files (no quarantine section) move entirely into
            # quarantine: nothing is trusted without provenance.
            for char, readings_map in readings.items():
                q = self.quarantine_legacy.setdefault(char, {})
                for syllable, count in readings_map.items():
                    q[syllable] = q.get(syllable, 0) + int(count)
        else:
            for char, readings_map in readings.items():
                for syllable, count in readings_map.items():
                    if provenance.get(char, {}).get(syllable):
                        bucket = trusted.setdefault(char, {})
                        bucket[syllable] = int(count)
                    else:
                        # An entry in the trusted section without provenance
                        # is not trusted evidence.
                        q = self.quarantine_legacy.setdefault(char, {})
                        q[syllable] = q.get(syllable, 0) + int(count)
        self.data = trusted
        self.provenance = {
            str(char): {str(k): list(v) for k, v in sylls.items()}
            for char, sylls in provenance.items()
            if isinstance(sylls, dict)
        }
        self.meta = raw.get("meta", {}) or {}

    def _quarantine_pairs(self, bucket: dict[str, dict[str, int]]) -> int:
        return sum(sum(counts.values()) for counts in bucket.values())

    def quarantine_summary(self) -> dict[str, int]:
        return {
            "trusted_pairs": self._quarantine_pairs(self.data),
            "trusted_chars": len(self.data),
            "legacy_without_provenance_pairs": self._quarantine_pairs(self.quarantine_legacy),
            "legacy_without_provenance_chars": len(self.quarantine_legacy),
            "unverified_pairs": self._quarantine_pairs(self.quarantine_unverified),
            "unverified_chars": len(self.quarantine_unverified),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "meta": self.meta,
            "readings": {
                char: dict(sorted(readings.items(), key=lambda kv: (-kv[1], kv[0])))
                for char, readings in sorted(self.data.items())
            },
            "provenance": {
                char: {reading: list(records) for reading, records in sorted(sylls.items())}
                for char, sylls in sorted(self.provenance.items())
            },
            "quarantine": {
                "legacy_without_provenance": {
                    char: dict(sorted(readings.items(), key=lambda kv: (-kv[1], kv[0])))
                    for char, readings in sorted(self.quarantine_legacy.items())
                },
                "unverified": {
                    char: dict(sorted(readings.items(), key=lambda kv: (-kv[1], kv[0])))
                    for char, readings in sorted(self.quarantine_unverified.items())
                },
            },
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def restore_quarantine(self, char: str | None = None, syllable: str | None = None) -> int:
        """Promote quarantined entries back to trusted after human review.

        Returns the number of promoted pairs. Requires an explicit call;
        automated stages never call this.
        """
        promoted = 0
        for bucket in (self.quarantine_legacy, self.quarantine_unverified):
            for c, readings in list(bucket.items()):
                if char is not None and c != char:
                    continue
                for reading, count in list(readings.items()):
                    if syllable is not None and reading != syllable:
                        continue
                    trusted = self.data.setdefault(c, {})
                    trusted[reading] = trusted.get(reading, 0) + int(count)
                    records = self.provenance.setdefault(c, {}).setdefault(reading, [])
                    records.append(
                        {
                            "source": "manual_restore",
                            "evidence": "human_restore",
                            "restored_at": _now(),
                            "count": int(count),
                        }
                    )
                    promoted += 1
                    del readings[reading]
                if not readings:
                    del bucket[c]
        return promoted

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def readings(self, char: str) -> list[str]:
        return [
            reading
            for reading, _count in sorted(
                self.data.get(char, {}).items(), key=lambda kv: (-kv[1], kv[0])
            )
        ]

    def provenance_for(self, char: str, syllable: str) -> list[dict[str, Any]]:
        return list(self.provenance.get(char, {}).get(syllable, []))

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------
    def add(
        self,
        char: str,
        syllable: str,
        count: int = 1,
        *,
        provenance: dict[str, Any] | None = None,
    ) -> bool:
        if len(char) != 1 or not is_nom_char(char):
            return False
        syllable = syllable.strip().casefold()
        if not syllable:
            return False
        if not provenance:
            bucket = self.quarantine_unverified.setdefault(char, {})
            bucket[syllable] = bucket.get(syllable, 0) + max(1, int(count))
            return False
        bucket = self.data.setdefault(char, {})
        bucket[syllable] = bucket.get(syllable, 0) + max(1, int(count))
        record = dict(provenance)
        record.setdefault("learned_at", _now())
        records = self.provenance.setdefault(char, {}).setdefault(syllable, [])
        records.append(record)
        return True

    def learn_from_rows(
        self,
        rows: Iterable[Any],
        dictionary: Any | None = None,
    ) -> dict[str, Any]:
        """Learn conservative reading evidence from human-reviewed rows.

        Only rows flagged ``HUMAN_REVIEWED`` qualify, and only rows with an
        unambiguous correspondence: exactly one Nôm character, and either
        exactly one QN syllable or a dictionary reading present in the
        row's syllables. Everything else is reported as skipped, never
        silently learned.
        """
        learned = 0
        skipped_unreviewed = 0
        skipped_blocked = 0
        skipped_ambiguous = 0
        skipped_empty = 0
        for row in rows:
            ch_text, vi_text, sentence_id, image_name, flags = _row_tuple(row)
            flag_set = set(flags)
            if "HUMAN_REVIEWED" not in flag_set:
                skipped_unreviewed += 1
                continue
            if flag_set & BLOCKING_FLAGS:
                skipped_blocked += 1
                continue
            chars = [ch for ch in ch_text if is_nom_char(ch)]
            syllables = qn_syllables(vi_text)
            if not chars or not syllables:
                skipped_empty += 1
                continue
            if len(chars) != 1:
                skipped_ambiguous += 1
                continue
            char = chars[0]
            syllable_set = set(syllables)
            if len(syllables) == 1:
                self.add(
                    char,
                    syllables[0],
                    provenance={
                        "source": "human_reviewed_row",
                        "evidence": "single_token",
                        "sentence_id": sentence_id,
                        "image_name": image_name,
                    },
                )
                learned += 1
                continue
            if dictionary is None:
                skipped_ambiguous += 1
                continue
            lookup = dictionary.lookup(char)
            matched = []
            for reading in getattr(lookup, "readings", []) or []:
                for form in _reading_forms(str(reading)):
                    if form in syllable_set and form not in matched:
                        matched.append(form)
            if len(matched) != 1:
                # Zero or multiple candidate readings: not unambiguous.
                skipped_ambiguous += 1
                continue
            self.add(
                char,
                matched[0],
                provenance={
                    "source": "human_reviewed_row",
                    "evidence": "dictionary_reading",
                    "sentence_id": sentence_id,
                    "image_name": image_name,
                    "reading": matched[0],
                },
            )
            learned += 1
        self.meta["learned_pairs"] = int(self.meta.get("learned_pairs", 0)) + learned
        return {
            "learned_pairs": learned,
            "characters": len(self.data),
            "skipped_unreviewed": skipped_unreviewed,
            "skipped_blocked": skipped_blocked,
            "skipped_ambiguous": skipped_ambiguous,
            "skipped_empty": skipped_empty,
            "quarantine": self.quarantine_summary(),
        }
