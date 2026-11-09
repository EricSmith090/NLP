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
confirmed the *position* of the character, and the complete decision
history for the row is sound:

1. The row must carry an explicit, non-stale verifying review decision
   (``alignment_reviewed`` / ``accepted_match`` / ``accepted_difference``)
   whose ``decision_integrity`` is ``valid`` (see
   ``hannom.review_decisions``). Rows whose latest decision is stale,
   invalid, or in conflict never modify the active lexicon.
2. Positional evidence, one of:
   a. an explicit ``character_token_mappings`` entry recorded on the
      decision. The **entire set is validated atomically** — set-level
      uniqueness and monotonicity plus row-bound character/token checks.
      If any mapping fails, no entry from that set is learned; or
   b. a single Nôm character paired with a single QN token that the
      reviewer explicitly accepted (1↔1 with no positional ambiguity).
3. Dictionary membership in the sentence is **never** positional
   evidence; neither are repeated or multiple candidate readings.
4. A log-wide integrity failure (unparseable decision log) disables
   learning for the book entirely; row-specific failures exclude only
   the affected row.
5. Re-running learning is idempotent for identical decisions: a
   character/syllable pair already backed by identical reviewer provenance
   is not double-counted.

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
from ..review_decisions import (
    VERIFYING_STATUSES,
    CharacterTokenMapping,
    content_sha256,
    validate_mappings_against_text,
)

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


def _row_diff_json(row: Any) -> str:
    getter = getattr(row, "text_diff_json", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return "[]"
    value = _row_field(row, "text_diff_json", None)
    if isinstance(value, str):
        return value
    return "[]"


def _mapping_items(row: Any) -> list[dict[str, Any]]:
    mappings = _row_field(row, "character_token_mappings", []) or []
    return [item for item in mappings if isinstance(item, dict)]


class BookLexicon:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, dict[str, int]] = {}
        self.provenance: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.revoked: dict[str, dict[str, list[dict[str, Any]]]] = {}
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
        raw_revoked = raw.get("revoked", {}) or {}
        self.revoked = {}
        for char, sylls in raw_revoked.items():
            if not isinstance(sylls, dict):
                continue
            for reading, records in sylls.items():
                if isinstance(records, list):
                    self.revoked.setdefault(str(char), {})[str(reading)] = [
                        r for r in records if isinstance(r, dict)
                    ]
        self.meta = raw.get("meta", {}) or {}

    def _quarantine_pairs(self, bucket: dict[str, dict[str, int]]) -> int:
        return sum(sum(counts.values()) for counts in bucket.values())

    def _record_count(self, bucket: dict[str, dict[str, list[dict]]]) -> int:
        return sum(len(records) for readings in bucket.values() for records in readings.values())

    def quarantine_summary(self) -> dict[str, int]:
        return {
            "trusted_pairs": self._quarantine_pairs(self.data),
            "trusted_chars": len(self.data),
            "legacy_without_provenance_pairs": self._quarantine_pairs(self.quarantine_legacy),
            "legacy_without_provenance_chars": len(self.quarantine_legacy),
            "unverified_pairs": self._quarantine_pairs(self.quarantine_unverified),
            "unverified_chars": len(self.quarantine_unverified),
            "revoked_records": self._record_count(self.revoked),
        }

    def backup(self) -> Path | None:
        """Snapshot the store before a destructive reconcile/migration.

        Reuses an existing backup only when it is byte-identical to the
        current file; otherwise writes a new timestamped copy. Never
        overwrites a previous backup.
        """
        if not self.path.exists():
            return None
        import shutil

        current_bytes = self.path.read_bytes()
        today = _now().replace("-", "").replace(":", "")[:14]  # YYYYMMDDTHHMMSS
        for existing in sorted(self.path.parent.glob(self.path.name + ".bak-reconcile-*")):
            try:
                if existing.read_bytes() == current_bytes:
                    return existing
            except OSError:
                continue
        stamp = _now().replace("-", "").replace(":", "")[:14]
        dest = self.path.with_name(self.path.name + f".bak-reconcile-{stamp}")
        counter = 2
        while dest.exists():
            dest = self.path.with_name(self.path.name + f".bak-reconcile-{stamp}-{counter}")
            counter += 1
        shutil.copy2(self.path, dest)
        return dest

    AUTO_EVIDENCE = frozenset({"explicit_mapping", "single_token_accepted"})
    MANUAL_EVIDENCE = frozenset({"human_restore"})

    @staticmethod
    def _granule_from_inputs(
        sentence_id: str, nom_position: Any, qn_token_position: Any, char: str, reading: str
    ) -> tuple[str, int, int, str, str] | None:
        try:
            nom_pos = int(nom_position)
            token_pos = int(qn_token_position)
        except (TypeError, ValueError):
            # Non-integer positional identity (e.g. bool): never authorized.
            return None
        if isinstance(nom_position, bool) or isinstance(qn_token_position, bool):
            return None
        if nom_pos < 0 or token_pos < 0:
            return None
        return (
            sentence_id,
            nom_pos,
            token_pos,
            unicodedata.normalize("NFC", str(char)),
            str(reading).strip().casefold(),
        )

    @staticmethod
    def _authorized_granules(rows: Iterable[Any]) -> set[tuple[str, int, int, str, str]]:
        authorized: set[tuple[str, int, int, str, str]] = set()
        for row in rows:
            if _row_field(row, "decision_integrity", None) != "valid":
                continue
            if _row_field(row, "review_status", None) not in VERIFYING_STATUSES:
                continue
            sid = str(_row_field(row, "sentence_id", "") or "")
            if not sid:
                continue
            mappings = _mapping_items(row)
            if mappings:
                for mapping in mappings:
                    granule = BookLexicon._granule_from_inputs(
                        sid,
                        mapping.get("nom_position"),
                        mapping.get("qn_token_position"),
                        str(mapping.get("nom_char", "")),
                        str(mapping.get("qn_token", "")),
                    )
                    if granule:
                        authorized.add(granule)
                continue
            chars = [c for c in str(_row_field(row, "ch_txt", "") or "") if is_nom_char(c)]
            tokens = _qn_token_spans(str(_row_field(row, "vi_txt", "") or ""))
            if len(chars) == 1 and len(tokens) == 1:
                granule = BookLexicon._granule_from_inputs(sid, 0, 0, chars[0], tokens[0][2])
                if granule:
                    authorized.add(granule)
        return authorized

    def reconcile(
        self,
        rows: Iterable[Any],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Withdraw automated review evidence no longer authorized.

        ``rows`` must be the current, post-``apply_decisions`` state of the
        rows (see ``hannom.review_decisions``): only rows with an
        effective, valid, verifying decision may authorize automated
        evidence. Manually restored entries (``human_restore``) and their
        provenance are never touched; unknown or unauthorized automated
        evidence is moved to the ``revoked`` section (kept for audit),
        and the active readings are rebuilt deterministically.

        ``dry_run=True`` reports without mutating anything.
        """
        authorized = self._authorized_granules(rows)
        summary: dict[str, Any] = {
            "dry_run": bool(dry_run),
            "authorized_granules": len(authorized),
            "manual_kept": 0,
            "automated_kept": 0,
            "automated_revoked": 0,
            "unknown_evidence_revoked": 0,
            "pairs_removed": 0,
            "pairs_kept": 0,
            "changed": False,
        }
        new_provenance: dict[str, dict[str, list[dict[str, Any]]]] = {}
        new_data: dict[str, dict[str, int]] = {}
        now = _now()
        for char, readings_map in (self.provenance or {}).items():
            for reading, records in (readings_map or {}).items():
                manual = [r for r in records if r.get("evidence") in self.MANUAL_EVIDENCE]
                automated = [r for r in records if r.get("evidence") in self.AUTO_EVIDENCE]
                unknown = [
                    r
                    for r in records
                    if r.get("evidence") not in self.AUTO_EVIDENCE
                    and r.get("evidence") not in self.MANUAL_EVIDENCE
                ]
                kept: list[dict[str, Any]] = list(manual)
                revoked_here: list[dict[str, Any]] = []
                for record in automated:
                    granule = self._granule_from_inputs(
                        str(record.get("sentence_id", "")),
                        record.get("nom_position"),
                        record.get("qn_token_position"),
                        char,
                        reading,
                    )
                    if granule and granule in authorized:
                        kept.append(record)
                    else:
                        revoked_here.append(
                            {**record, "revoked_at": now, "revocation_reason": "no_longer_authorized_by_review"}
                        )
                for record in unknown:
                    revoked_here.append(
                        {**record, "revoked_at": now, "revocation_reason": "unknown_evidence"}
                    )
                summary["manual_kept"] += len(manual)
                summary["automated_kept"] += len(kept) - len(manual)
                summary["automated_revoked"] += len(
                    [r for r in revoked_here if r.get("evidence") in self.AUTO_EVIDENCE]
                )
                summary["unknown_evidence_revoked"] += len(unknown)
                if revoked_here:
                    summary["changed"] = True
                    if not dry_run:
                        bucket = self.revoked.setdefault(char, {}).setdefault(reading, [])
                        bucket.extend(revoked_here)
                if kept:
                    new_provenance.setdefault(char, {})[reading] = kept
                    bucket = new_data.setdefault(char, {})
                    bucket[reading] = len(kept)
        # Unreferenced data entries (no surviving provenance) are not
        # trusted evidence: move them to legacy quarantine, never delete.
        for char in list(self.data.keys()):
            for reading, count in list(self.data[char].items()):
                if char in new_data and reading in new_data[char]:
                    summary["pairs_kept"] += 1
                else:
                    summary["pairs_removed"] += 1
                    summary["changed"] = True
                    if not dry_run:
                        q = self.quarantine_legacy.setdefault(char, {})
                        q[reading] = q.get(reading, 0) + int(count)
        if not dry_run:
            self.data = new_data
            self.provenance = new_provenance
        return summary

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
            "revoked": {
                char: {reading: list(records) for reading, records in sorted(sylls.items())}
                for char, sylls in sorted(self.revoked.items())
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
        skipped_conflicted = 0
        skipped_duplicate = 0
        for row in rows:
            ch_text, vi_text, sentence_id, image_name, flags = _row_tuple(row)
            flag_set = set(flags)
            review_status = _row_field(row, "review_status", None)
            integrity = _row_field(row, "decision_integrity", None)
            reviewer = str(_row_field(row, "review_reviewer", "") or "")
            row_hash = content_sha256(ch_text, vi_text, _row_diff_json(row))
            decision_id = str(_row_field(row, "decision_id", "") or "")
            if review_status not in VERIFYING_STATUSES:
                skipped_unreviewed += 1
                continue
            if integrity != "valid":
                # No learning from conflicted, stale, invalid or
                # unresolved decision histories (Issue B).
                skipped_conflicted += 1
                continue
            mappings = _mapping_items(row)

            # -- Path A: explicit reviewer character↔token mappings ------
            if mappings:
                # Atomic, set-wide validation: one bad mapping rejects the
                # whole set; nothing is applied partially.
                try:
                    items = [CharacterTokenMapping.from_dict(m) for m in mappings]
                except (TypeError, ValueError):
                    skipped_invalid_mapping += len(mappings)
                    continue
                errors = validate_mappings_against_text(items, ch_text, vi_text)
                if errors:
                    skipped_invalid_mapping += len(errors)
                    continue
                learned_here = 0
                for item, mapping in zip(items, mappings):
                    token_text = _qn_token_spans(vi_text)[item.qn_token_position][2]
                    record = {
                        "source": "human_review_decision",
                        "evidence": "explicit_mapping",
                        "sentence_id": sentence_id,
                        "image_name": image_name,
                        "reviewer": reviewer,
                        "decision_status": review_status,
                        "decision_id": decision_id,
                        "row_hash": row_hash,
                        "nom_position": item.nom_position,
                        "qn_token_position": item.qn_token_position,
                    }
                    if self._has_provenance(
                        item.nom_char,
                        token_text,
                        sentence_id=sentence_id,
                        nom_position=item.nom_position,
                        qn_token_position=item.qn_token_position,
                        evidence="explicit_mapping",
                    ):
                        skipped_duplicate += 1
                        continue
                    self.add(item.nom_char, token_text, provenance=record)
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
            if self._has_provenance(
                char,
                token_text,
                sentence_id=sentence_id,
                nom_position=0,
                qn_token_position=0,
                evidence="single_token_accepted",
            ):
                skipped_duplicate += 1
                continue
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
                    "decision_id": decision_id,
                    "row_hash": row_hash,
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
            "skipped_conflicted": skipped_conflicted,
            "skipped_duplicate_evidence": skipped_duplicate,
            "quarantine": self.quarantine_summary(),
        }

    def _has_provenance(
        self,
        char: str,
        syllable: str,
        *,
        sentence_id: str,
        nom_position: int,
        qn_token_position: int,
        evidence: str,
    ) -> bool:
        """True if identical reviewer evidence is already recorded."""
        normalized = syllable.strip().casefold()
        for record in self.provenance.get(char, {}).get(normalized, []):
            if (
                record.get("evidence") == evidence
                and record.get("sentence_id") == sentence_id
                and record.get("nom_position") == nom_position
                and record.get("qn_token_position") == qn_token_position
            ):
                return True
        return False
