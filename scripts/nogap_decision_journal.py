#!/usr/bin/env python3
"""M8-E1: Decision Journal Entry - immutable historical-position contract.

DECISION SEMANTIC IDENTITY != DECISION HISTORICAL POSITION. M8-D's
DecisionRecordContract.decision_fingerprint (scripts/nogap_decision.py,
frozen, unmodified) already proves "this individual decision has a
deterministic semantic identity." This module begins the separate, later
concern of proving "this decision occupies this position in this historical
sequence" - but M8-E1 itself implements ONLY the single-entry contract. It
does not implement multi-entry behavior: no append, no verification, no
checkpoint, no persistence. Those are M8-E2/E3/E4/E5, not implemented here.

M8-E2 adds pure, in-memory, multi-entry behavior on top of E1's frozen
single-entry contract: verify_decision_journal() (structural chain
verification of a caller-presented Sequence[DecisionJournalEntry]) and
append_decision_entry() (pure construction of the next DecisionJournalEntry
from a verified history and a trusted DecisionRecordContract). Still no
checkpoint, no persistence, no replay - those are M8-E3/E4/E5.

Dependency direction is one-way: this module imports frozen primitives from
nogap_decision.py (DecisionValidationError, DecisionRecordContract,
M8_DECISION_SCHEMA_VERSION, fingerprint_payload, and the existing
_require/_require_nonempty_str/_require_valid_digest/
_require_supported_schema_version validation helpers - reused, not
duplicated, exactly mirroring the established precedent of
nogap_lifecycle.py importing private _require/_now helpers directly from
nogap_methodology.py). schema_version is validated via the SAME
_require_supported_schema_version(...) path every sibling M8-A/B/C/D
contract already uses (checked against nogap_decision.py's own
_SUPPORTED_SCHEMA_VERSIONS set) - no independent version list, no
M8_JOURNAL_SCHEMA_VERSION, no custom parsing. nogap_decision.py imports
nothing from here and never will - M8-D must know nothing about the journal
layer.

LEGACY ISOLATION: this module has zero relationship to
.code-loop/runtime/decisions/ (the M6/M7 decision-0001.json single-slot
store, accept/repair/abstain vocabulary) - a confirmed SEPARATE SUBSYSTEM,
never read, written, migrated, or wrapped here.

FROZEN PLACEHOLDER ISOLATION: DecisionRecordContract.decision_hash,
.previous_decision_hash, and .supersedes remain exactly as M8-A left them -
unused placeholders, never read or referenced by this module. decision_hash
!= entry_fingerprint. previous_decision_hash != previous_entry_fingerprint.
supersedes != journal predecessor. No code here creates any relationship
between them.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Sequence

from nogap_decision import (
    DecisionRecordContract,
    DecisionValidationError,
    M8_DECISION_SCHEMA_VERSION,
    _require,
    _require_nonempty_str,
    _require_supported_schema_version,
    _require_valid_digest,
    fingerprint_payload,
)


@dataclasses.dataclass(frozen=True)
class DecisionJournalEntry:
    """Immutable historical-position commitment for one decision.

    journal_id is an OPAQUE LOGICAL DECISION STREAM IDENTIFIER - caller-
    supplied, never derived from project/decision_type/subject/scope/
    repository/policy/request/filesystem path, and never parsed as a
    delimiter/composite encoding. Its granularity is deliberately left to a
    higher layer; M8-E1 only enforces that it is a non-empty string and
    participates in this entry's semantic identity (a semantic domain
    separator, not a bare correlation label - moving the same sequence to a
    different journal_id must produce a different entry_fingerprint).

    sequence is the historical-position coordinate. Genesis is represented
    ONLY as sequence == 0 with previous_entry_fingerprint == None - no
    sentinel string, no zero-hash, no "GENESIS" literal, matching this
    codebase's consistent use of None for typed absence everywhere else
    (DecisionSnapshot.methodology_ref, DecisionPredicateResult.scope_ref,
    etc.). This class validates only its OWN genesis/predecessor
    relationship; whether a multi-entry journal contains exactly one genesis
    is E2 verification behavior, not implemented here.

    record_ref/recorded_at are CORRELATION/DIAGNOSTIC ONLY - exactly like
    every prior layer's locator/timestamp fields (SnapshotReference.locator,
    DecisionSnapshot.captured_at, PredicateEvidenceBinding.evaluated_at) -
    and are excluded from semantic_payload()/entry_fingerprint accordingly.
    """

    journal_id: str
    sequence: int
    decision_fingerprint: str
    previous_entry_fingerprint: str | None
    record_ref: str | None = None
    recorded_at: str | None = None
    schema_version: str = M8_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty_str(self.journal_id, "journal_id")

        # bool is a subclass of int in Python - sequence=True/False must
        # never silently behave as sequence=1/0. Mirrors the exact discipline
        # already applied to DecisionPredicateResult.required/.blocking and
        # AdmissibilityResult.admissible in nogap_decision.py.
        _require(isinstance(self.sequence, int) and not isinstance(self.sequence, bool), "sequence must be an int, not bool")
        _require(self.sequence >= 0, "sequence must be >= 0")

        _require_valid_digest(self.decision_fingerprint, "decision_fingerprint")

        # Genesis invariant, exact and bidirectional: sequence==0 requires no
        # predecessor; sequence>0 requires a real predecessor digest. Neither
        # direction may be relaxed.
        if self.sequence == 0:
            _require(self.previous_entry_fingerprint is None, "sequence 0 (genesis) must have previous_entry_fingerprint=None")
        else:
            _require(self.previous_entry_fingerprint is not None, "sequence > 0 requires a non-None previous_entry_fingerprint")
            _require_valid_digest(self.previous_entry_fingerprint, "previous_entry_fingerprint")

        if self.record_ref is not None:
            _require_nonempty_str(self.record_ref, "record_ref")
        if self.recorded_at is not None:
            _require_nonempty_str(self.recorded_at, "recorded_at")

        _require_supported_schema_version(self.schema_version)

    def semantic_payload(self) -> dict[str, Any]:
        """The explicit, audited subset of fields that define this entry's
        historical-position identity. Excludes record_ref/recorded_at
        (correlation/diagnostic only, per the class docstring)."""
        return {
            "journal_id": self.journal_id,
            "sequence": self.sequence,
            "decision_fingerprint": self.decision_fingerprint,
            "previous_entry_fingerprint": self.previous_entry_fingerprint,
            "schema_version": self.schema_version,
        }

    @property
    def entry_fingerprint(self) -> str:
        """Computed, never caller-supplied - same rationale as every prior
        fingerprint property in this engine (DecisionSnapshot.snapshot_fingerprint,
        DecisionPredicateResult.result_fingerprint,
        PredicateEvidenceBinding.binding_fingerprint,
        DecisionEvaluationContract.evaluation_fingerprint,
        DecisionRecordContract.decision_fingerprint): a stored/settable
        fingerprint field would let a caller claim an identity its own
        content doesn't match. Reuses fingerprint_payload() only - no second
        hashing implementation exists in this module."""
        return fingerprint_payload(self.semantic_payload())


# ================================================================================
# M8-E2: Pure Append + Structural Journal Verification
# ================================================================================

# Stable, non-overlapping machine-readable reason codes for STRUCTURAL journal
# chain failures only - never reused for DecisionTruthValue/DecisionVerdict,
# and never DECISION_REASON_CODES (that vocabulary describes predicate/policy
# outcomes; a broken chain is not a predicate outcome). Deliberately NOT
# split further into DUPLICATE_SEQUENCE/SEQUENCE_GAP/MISSING_GENESIS/
# MULTIPLE_GENESIS: every one of those conditions is a case where the
# presented sequence values fail to be the required {0, ..., n-1} set, so a
# single SEQUENCE_INVALID code covers all of them without loss of precision -
# the caller already holds the entries needed to see exactly which case it was.
JOURNAL_REASON_CODES = frozenset({
    "JOURNAL_ID_MISMATCH",
    "SEQUENCE_INVALID",
    "PRESENTATION_ORDER_INVALID",
    "PREDECESSOR_MISMATCH",
})


@dataclasses.dataclass(frozen=True)
class JournalVerificationResult:
    """The smallest immutable shape sufficient for verify_decision_journal()'s
    verdict - a direct structural mirror of nogap_decision.py's
    AdmissibilityResult: no details/metadata/
    failed_sequence/failed_entry_fingerprint. The caller already holds the
    entries needed to reconstruct exactly what mismatched; a diagnostic
    field here would just be a second, weaker copy of information the caller
    already has, with no additional trust value."""

    valid: bool
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _require(isinstance(self.valid, bool), "valid must be an explicit bool")
        if self.valid:
            _require(self.reason_code is None, "a valid result must not carry a reason_code")
        else:
            _require(self.reason_code is not None, "an invalid result must carry a reason_code")
            _require(self.reason_code in JOURNAL_REASON_CODES, f"unknown reason code: {self.reason_code!r}")


def verify_decision_journal(
    entries: Sequence[DecisionJournalEntry],
    *,
    journal_id: str | None = None,
) -> JournalVerificationResult:
    """Pure structural verification of a caller-presented journal chain. No
    I/O, no clock, no UUID, no internal sorting, no mutation, no repair.

    Every DecisionJournalEntry already enforces its OWN genesis/predecessor
    SHAPE invariant at construction time (M8-E1); this function only checks
    the RELATIONSHIPS BETWEEN entries: journal_id uniformity, whether the
    presented sequence values form the exact {0, ..., n-1} set (this single
    check also structurally subsumes missing/multiple genesis, gaps, and
    duplicate sequence - see JOURNAL_REASON_CODES), whether that set is
    presented in ascending positional order (list position is a
    presentation-contract constraint only, never historical authority -
    a structurally correct set presented out of order fails
    PRESENTATION_ORDER_INVALID rather than being silently reordered), and
    adjacent-pair previous_entry_fingerprint linkage.

    journal_id pin: when supplied, every entry must match it exactly - this
    proves the presented chain is the CALLER-INTENDED journal, not merely
    some internally self-consistent one (closing a wholesale cross-journal
    substitution gap that plain mutual consistency alone cannot catch). When
    omitted, only mutual consistency against entries[0].journal_id is
    proven - do not read that as proof of caller-intended identity.

    Empty entries is structurally valid regardless of the pin (there is no
    malformed chain in zero entries) - but STRUCTURALLY VALID EMPTY JOURNAL
    != PROOF THAT NO HISTORY EVER EXISTED, exactly as a non-empty valid
    result never proves COMPLETE history (see limitations below).

    CRITICAL, PERMANENT LIMITATIONS (do not weaken these claims):
    - STRUCTURALLY VALID PREFIX != PROOF OF COMPLETE HISTORY. A genuinely
      valid E0->E1 returned by this function proves nothing about whether a
      real E0->E1->E2->E3 exists elsewhere. Detecting truncation/rollback
      against previously observed state requires an external anchor and is
      M8-E3 checkpoint territory, not this function.
    - A FULLY SELF-CONSISTENT REWRITE OF A LOCAL CHAIN CANNOT BE DETECTED.
      If every entry in a chain is rewritten and every descendant's
      previous_entry_fingerprint is recomputed to match, the result verifies
      valid=True. This function has no external anchor to compare against
      and must never claim otherwise.
    - A HIDDEN FORK (a branch that exists but is never included in `entries`)
      cannot be detected. Only a VISIBLE fork - two presented entries sharing
      one historical position - is caught, via SEQUENCE_INVALID (duplicate
      sequence).
    - This function proves structural chain coherence only. It does NOT
      prove the underlying DecisionRecord referenced by decision_fingerprint
      exists, is semantically valid, or was ever persisted - journal
      integrity and decision semantic validity are deliberately not blurred
      together."""
    if journal_id is not None:
        _require_nonempty_str(journal_id, "journal_id")

    if len(entries) == 0:
        return JournalVerificationResult(valid=True)

    for entry in entries:
        _require(isinstance(entry, DecisionJournalEntry), "entries must contain only DecisionJournalEntry objects")

    expected_journal_id = journal_id if journal_id is not None else entries[0].journal_id
    for entry in entries:
        if entry.journal_id != expected_journal_id:
            return JournalVerificationResult(valid=False, reason_code="JOURNAL_ID_MISMATCH")

    entry_count = len(entries)
    sequences = tuple(entry.sequence for entry in entries)
    if set(sequences) != set(range(entry_count)):
        return JournalVerificationResult(valid=False, reason_code="SEQUENCE_INVALID")
    if sequences != tuple(range(entry_count)):
        return JournalVerificationResult(valid=False, reason_code="PRESENTATION_ORDER_INVALID")

    for i in range(1, entry_count):
        if entries[i].previous_entry_fingerprint != entries[i - 1].entry_fingerprint:
            return JournalVerificationResult(valid=False, reason_code="PREDECESSOR_MISMATCH")

    return JournalVerificationResult(valid=True)


def append_decision_entry(
    history: Sequence[DecisionJournalEntry],
    decision_record: DecisionRecordContract,
    *,
    journal_id: str,
    record_ref: str | None = None,
    recorded_at: str | None = None,
) -> DecisionJournalEntry:
    """Pure construction of the next DecisionJournalEntry. No mutation of
    `history`, no persistence, no UUID, no clock, no filesystem, no Git.

    Trust model (Option A - the only one approved for M8-E2): the FULL
    supplied `history` is structurally verified before anything is derived
    from it - never just a caller-supplied last_entry/head, and no new
    "VerifiedJournalHead" trust-token abstraction is introduced. A single
    object's own construction cannot guarantee a caller-assembled LIST of
    objects forms one coherent chain; only verify_decision_journal() can, so
    it is what append relies on. If `history` does not verify, this raises
    DecisionValidationError and constructs nothing - never appends onto
    corruption.

    sequence and previous_entry_fingerprint are always DERIVED from the
    verified history, never caller-supplied: empty history yields sequence 0
    / previous_entry_fingerprint None; otherwise sequence is
    history[-1].sequence + 1 and previous_entry_fingerprint is
    history[-1].entry_fingerprint (safe to index [-1] only because history
    has already been proven to be in correct ascending order by this point).

    decision_fingerprint is obtained from decision_record.decision_fingerprint
    - never a caller-supplied raw string - so this boundary inherits M8-D's
    existing fail-closed behavior for free: an unbound/legacy
    DecisionRecordContract raises DecisionValidationError the moment its
    decision_fingerprint property is read, exactly as it already does for
    every other M8-D caller. That access happens only AFTER history has
    passed structural verification, so a legacy-record failure and a
    corrupt-history failure are never conflated."""
    _require(isinstance(decision_record, DecisionRecordContract), "decision_record must be a DecisionRecordContract")
    _require_nonempty_str(journal_id, "journal_id")

    verification = verify_decision_journal(history, journal_id=journal_id)
    _require(verification.valid, f"cannot append onto an invalid history: {verification.reason_code}")

    decision_fingerprint = decision_record.decision_fingerprint  # raises if unbound - M8-D's own fail-closed check

    if len(history) == 0:
        sequence = 0
        previous_entry_fingerprint = None
    else:
        previous = history[-1]
        sequence = previous.sequence + 1
        previous_entry_fingerprint = previous.entry_fingerprint

    return DecisionJournalEntry(
        journal_id=journal_id,
        sequence=sequence,
        decision_fingerprint=decision_fingerprint,
        previous_entry_fingerprint=previous_entry_fingerprint,
        record_ref=record_ref,
        recorded_at=recorded_at,
    )
