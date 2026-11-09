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

Learning policy — a reading is learned only when the reviewer explicitly
confirmed the *position* of the character:

1. The row must carry an explicit, non-stale verifying review decision
   (``alignment_reviewed`` / ``accepted_match`` / ``accepted_difference``)
   recorded by a human; see ``hannom.review_decisions``.
2. Positional evidence, one of:
   a. an explicit ``character_token_mappings`` entry recorded on the
      decision (the strongest evidence — usable even for multi-character
      rows), or
   b. a single Nôm character paired with a single QN token that the
      reviewer explicitly accepted (1↔1 with no positional ambiguity).
3. Dictionary membership in the sentence is **never** positional
   evidence; neither are repeated or multiple candidate readings.

Rows flagged ``NON_ONE_TO_ONE``, ``UNMATCHED_*``, ``ALIGN_LOW_CONF``,
``COSEGMENTED_UNANCHORED``, ``TEXT_DIFF_INVALID``, evidence- or
metadata- or decision-integrity failures are never used for the
no-mapping single-token path. Automated learning can never consume its
own unverified outputs.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..clean import is_nom_char
from ..review_decisions import VERIFYING_STATUSES

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
        "REVIEW_METADATA_UNRESOLVED",
        "ALIGN_EVIDENCE_INSUFFICIENT",
        "REVIEW_DECISION_STALE",
        "REVIEW_DECISION_MISMATCH",
        "REVIEW_DECISION_INVALID",
    }
)


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def qn_syllables(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).casefold()
    return [m.group(0) for m in QN_TOKEN_RE.finditer(text)]


def _normalize_reading(reading: str) -> str:
    return unicodedata.normalize("NFC", reading.strip()).casefold()


def _qn_token_spans(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in QN_TOKEN_RE.finditer(unicodedata.normalize("NFC", text).casefold())]


def _nom_char_positions(text: str) -> list[int]:
    return [i for i, ch in enumerate(text) if is_nom_char(ch)]


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


def _mapping_items(row: Any) -> list[dict[str, Any]]:
    mappings = _row_field(row, "character_token_mappings", []) or []
    return [item for item in mappings if isinstance(item, dict)]


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
        """Learn reading evidence from explicitly reviewed, positional rows.

        A row qualifies only when it carries an explicit, non-stale
        verifying review decision (see ``hannom.review_decisions``) AND one
        of the following holds:

        a. its decision recorded explicit ``character_token_mappings``
           (each mapping is validated against the row content; invalid
           ones are skipped, valid ones are learned), or
        b. the row has exactly one Nôm character and exactly one QN
           token (a 1↔1 correspondence with no positional ambiguity) and
           carries no blocking flags.

        Sentence-level dictionary membership never establishes positional
        correspondence; nothing is inferred from sets of readings.
        """
        learned = 0
        skipped_unreviewed = 0
        skipped_blocked = 0
        skipped_ambiguous = 0
        skipped_empty = 0
        skipped_no_positional_evidence = 0
        skipped_invalid_mapping = 0
        for row in rows:
            ch_text, vi_text, sentence_id, image_name, flags = _row_tuple(row)
            flag_set = set(flags)
            review_status = _row_field(row, "review_status", None)
            reviewer = str(_row_field(row, "review_reviewer", "") or "")
            if review_status not in VERIFYING_STATUSES:
                skipped_unreviewed += 1
                continue
            mappings = _mapping_items(row)

            # -- Path A: explicit reviewer character↔token mappings ------
            if mappings:
                nom_positions = _nom_char_positions(ch_text)
                tokens = _qn_token_spans(vi_text)
                learned_here = 0
                for mapping in mappings:
                    if not self._learn_mapping(
                        mapping,
                        ch_text=ch_text,
                        nom_positions=nom_positions,
                        vi_text=vi_text,
                        tokens=tokens,
                        sentence_id=sentence_id,
                        image_name=image_name,
                        reviewer=reviewer,
                        decision_status=review_status,
                    ):
                        skipped_invalid_mapping += 1
                        continue
                    learned_here += 1
                learned += learned_here
                continue

            # -- Path B: single Nôm character, single accepted token ------
            if flag_set & BLOCKING_FLAGS:
                skipped_blocked += 1
                continue
            chars = [(i, ch) for i, ch in enumerate(ch_text) if is_nom_char(ch)]
            tokens = _qn_token_spans(vi_text)
            if not chars or not tokens:
                skipped_empty += 1
                continue
            if len(chars) != 1 or len(tokens) != 1:
                skipped_no_positional_evidence += 1
                continue
            _, char = chars[0]
            token_text = tokens[0][2]
            self.add(
                char,
                token_text,
                provenance={
                    "source": "human_review_decision",
                    "evidence": "single_token_accepted",
                    "sentence_id": sentence_id,
                    "image_name": image_name,
                    "reviewer": reviewer,
                    "decision_status": review_status,
                    "nom_position": 0,
                    "qn_token_position": 0,
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
            "skipped_no_positional_evidence": skipped_no_positional_evidence,
            "skipped_invalid_mapping": skipped_invalid_mapping,
            "quarantine": self.quarantine_summary(),
        }

    def _learn_mapping(
        self,
        mapping: dict[str, Any],
        *,
        ch_text: str,
        nom_positions: list[int],
        vi_text: str,
        tokens: list[tuple[int, int, str]],
        sentence_id: str,
        image_name: str,
        reviewer: str,
        decision_status: str,
    ) -> bool:
        char = str(mapping.get("nom_char", ""))
        try:
            nom_position = int(mapping.get("nom_position", -1))
            qn_position = int(mapping.get("qn_token_position", -1))
        except (TypeError, ValueError):
            return False
        qn_token = str(mapping.get("qn_token", ""))
        if len(char) != 1 or not is_nom_char(char):
            return False
        if nom_position < 0 or nom_position >= len(nom_positions):
            return False
        if ch_text[nom_positions[nom_position]] != char:
            return False
        if qn_position < 0 or qn_position >= len(tokens):
            return False
        token_text = tokens[qn_position][2]
        if not qn_token or _normalize_reading(token_text) != _normalize_reading(qn_token):
            return False
        return self.add(
            char,
            token_text,
            provenance={
                "source": "human_review_decision",
                "evidence": "explicit_mapping",
                "sentence_id": sentence_id,
                "image_name": image_name,
                "reviewer": reviewer,
                "decision_status": decision_status,
                "nom_position": nom_position,
                "qn_token_position": qn_position,
            },
        )
