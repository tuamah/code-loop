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
from a verified history and a trusted DecisionRecordContract).

M8-E3 adds an immutable checkpoint contract (DecisionJournalCheckpoint),
a pure creation helper (create_journal_checkpoint), and a pure verification
helper (verify_journal_checkpoint) that answers one narrow question: is a
presented, structurally valid journal CONSISTENT WITH a retained historical
position, not whether that history is globally unique, tamper-proof, or
externally anchored. STRUCTURAL JOURNAL VALIDITY (E2) != CHECKPOINT
CONSISTENCY (E3) != EXTERNAL ANCHORING (out of scope through at least E5).
Still no persistence, no replay, no signing/witnessing/Merkle structures -
those remain M8-E4/E5 or later, unstarted.

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


# ================================================================================
# M8-E3: Checkpoint Contract - Consistency With a Retained Historical Position
# ================================================================================

# Success/failure status vocabulary for verify_journal_checkpoint(). Distinct
# from JOURNAL_REASON_CODES (E2's structural-chain vocabulary) - a checkpoint
# result answers a different question (consistency with a retained position,
# not internal chain coherence) and must never be flattened into or confused
# with it. CHECKPOINT_SUCCESS/FAILURE_STATUSES together are the exhaustive,
# closed outcome space of verify_journal_checkpoint(); nothing outside this
# set may ever be returned as `status`.
CHECKPOINT_SUCCESS_STATUSES = frozenset({
    "AT_CHECKPOINT",
    "AHEAD_OF_CHECKPOINT",
})

CHECKPOINT_FAILURE_STATUSES = frozenset({
    "BEHIND_CHECKPOINT",
    "CHECKPOINT_MISMATCH",
    "JOURNAL_INVALID",
    "JOURNAL_ID_MISMATCH",
})

# Reason codes for the three CHECKPOINT-LEVEL failure statuses only.
# JOURNAL_INVALID deliberately has NO code of its own here: its reason_code
# is instead the underlying JournalVerificationResult.reason_code, drawn from
# JOURNAL_REASON_CODES and passed through verbatim (see
# CheckpointVerificationResult.__post_init__) - flattening it into a generic
# checkpoint reason would destroy exactly the diagnostic precision E2 exists
# to provide. For the other three statuses, reason_code always equals status
# (no finer-grained reason exists below "the journal is behind" / "the
# historical entry doesn't match" / "the checkpoint's own journal_id doesn't
# match" - each IS its own complete explanation).
CHECKPOINT_REASON_CODES = frozenset({
    "BEHIND_CHECKPOINT",
    "CHECKPOINT_MISMATCH",
    "JOURNAL_ID_MISMATCH",
})


@dataclasses.dataclass(frozen=True)
class DecisionJournalCheckpoint:
    """Immutable commitment to one previously observed journal head.

    Deliberately minimal: journal_id/head_sequence/head_entry_fingerprint/
    schema_version only. No checkpoint_id/created_at/source_ref/entry_count/
    path/signature/public_key/metadata - none of those have a strong
    architectural reason at this milestone (entry_count in particular would
    be pure redundant derivation of head_sequence + 1, exactly the kind of
    second, competing representation of the same fact this engine has never
    permitted at any prior layer). If correlation fields are ever added
    later, they must be explicitly non-semantic, mirroring
    DecisionJournalEntry.record_ref/recorded_at's exclusion from identity.

    journal_id/head_sequence/head_entry_fingerprint are the SAME domain
    separator, position, and content-commitment concepts DecisionJournalEntry
    already establishes - this checkpoint does not invent a parallel vocabulary,
    it names one specific, previously-verified entry's position and identity.
    """

    journal_id: str
    head_sequence: int
    head_entry_fingerprint: str
    schema_version: str = M8_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty_str(self.journal_id, "journal_id")

        # Same bool-vs-int discipline as DecisionJournalEntry.sequence.
        _require(isinstance(self.head_sequence, int) and not isinstance(self.head_sequence, bool), "head_sequence must be an int, not bool")
        _require(self.head_sequence >= 0, "head_sequence must be >= 0")

        _require_valid_digest(self.head_entry_fingerprint, "head_entry_fingerprint")

        _require_supported_schema_version(self.schema_version)

    def semantic_payload(self) -> dict[str, Any]:
        """The explicit, audited subset of fields that define this
        checkpoint's identity - all four constructor fields; there are no
        correlation-only fields to exclude in E3."""
        return {
            "journal_id": self.journal_id,
            "head_sequence": self.head_sequence,
            "head_entry_fingerprint": self.head_entry_fingerprint,
            "schema_version": self.schema_version,
        }

    @property
    def checkpoint_fingerprint(self) -> str:
        """Computed, never caller-supplied - reuses fingerprint_payload()
        only, no second hashing implementation. Unlike
        DecisionEvaluationContract.evaluation_fingerprint/
        DecisionRecordContract.decision_fingerprint, this needs no
        fail-closed guard: every constructor field here is required and
        always validated at construction, so there is no legacy-unbound
        state possible.

        This is SEMANTIC IDENTITY ONLY. It is NOT a digital signature, NOT
        an external trust anchor, NOT a guarantee of persistence, and NOT a
        guarantee that this checkpoint itself has not been replaced. A
        future layer may sign, witness, or externally anchor this single
        value without ever needing to redesign the checkpoint body - but no
        such layer exists yet."""
        return fingerprint_payload(self.semantic_payload())


@dataclasses.dataclass(frozen=True)
class CheckpointVerificationResult:
    """The result of verify_journal_checkpoint(). Deliberately NOT a reuse of
    DecisionTruthValue/DecisionVerdict/ACCEPT/REJECT/ABSTAIN/UNKNOWN/
    CONFLICT - checkpoint consistency is a structural historical-position
    question, not decision algebra, and must never be read as one.

    `reason_code`'s required vocabulary depends on `status`: when
    status == "JOURNAL_INVALID", reason_code is the underlying E2
    JournalVerificationResult.reason_code (JOURNAL_REASON_CODES) passed
    through verbatim; for every other checkpoint-level failure status,
    reason_code is drawn from CHECKPOINT_REASON_CODES (and in practice
    always equals status - see CHECKPOINT_REASON_CODES's own docstring)."""

    verified: bool
    status: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _require(isinstance(self.verified, bool), "verified must be an explicit bool")
        if self.verified:
            _require(self.status in CHECKPOINT_SUCCESS_STATUSES, f"unknown success status: {self.status!r}")
            _require(self.reason_code is None, "a verified result must not carry a reason_code")
        else:
            _require(self.status in CHECKPOINT_FAILURE_STATUSES, f"unknown failure status: {self.status!r}")
            _require(self.reason_code is not None, "an unverified result must carry a reason_code")
            if self.status == "JOURNAL_INVALID":
                _require(self.reason_code in JOURNAL_REASON_CODES, f"unknown journal reason code: {self.reason_code!r}")
            else:
                _require(self.reason_code in CHECKPOINT_REASON_CODES, f"unknown checkpoint reason code: {self.reason_code!r}")


def create_journal_checkpoint(
    entries: Sequence[DecisionJournalEntry],
    *,
    journal_id: str,
) -> DecisionJournalCheckpoint:
    """Pure construction of a checkpoint at the current head of a verified
    journal. No I/O, no filesystem, no Git, no clock, no UUID, no
    persistence, no sorting, no mutation of `entries`, no repair.

    Trust model mirrors append_decision_entry(): the FULL supplied `entries`
    is structurally verified first; head_sequence/head_entry_fingerprint are
    always DERIVED from that verified tail, never caller-supplied - no raw
    trust-bearing head injection at this boundary either.

    An empty journal is structurally VALID under E2 (verify_decision_journal
    does not reinterpret that), but a checkpoint represents an actually
    observed journal head - there is no head to checkpoint in zero entries,
    so this raises DecisionValidationError for an empty journal even though
    verification alone would not."""
    _require_nonempty_str(journal_id, "journal_id")

    verification = verify_decision_journal(entries, journal_id=journal_id)
    _require(verification.valid, f"cannot create a checkpoint from an invalid journal: {verification.reason_code}")
    _require(len(entries) > 0, "cannot create a checkpoint from an empty journal - there is no observed head to checkpoint")

    head = entries[-1]
    return DecisionJournalCheckpoint(
        journal_id=journal_id,
        head_sequence=head.sequence,
        head_entry_fingerprint=head.entry_fingerprint,
    )


def verify_journal_checkpoint(
    entries: Sequence[DecisionJournalEntry],
    checkpoint: DecisionJournalCheckpoint,
    *,
    journal_id: str | None = None,
) -> CheckpointVerificationResult:
    """Pure verification that a presented, structurally valid journal is
    CONSISTENT WITH a retained historical position - not whether that
    history is globally unique, tamper-proof, or externally anchored. No
    I/O, no clock, no UUID, no sorting, no reconstruction, no mutation.

    journal_id pin: `expected_journal_id` is the caller-supplied `journal_id`
    when given, else `checkpoint.journal_id` itself. Either way,
    verify_decision_journal() below is ALWAYS called with an explicit,
    non-None journal_id - this checkpoint is never reconciled against an
    unpinned, self-derived journal identity, so a fully valid journal from a
    different domain can never satisfy a checkpoint from journal A merely by
    being internally self-consistent. checkpoint.journal_id must equal
    expected_journal_id or this short-circuits with JOURNAL_ID_MISMATCH
    before entries are examined at all.

    STRUCTURAL JOURNAL VALIDITY != CHECKPOINT CONSISTENCY: an invalid
    presented journal fails as JOURNAL_INVALID, with the underlying E2
    JournalVerificationResult.reason_code preserved verbatim (never
    flattened into a generic checkpoint reason).

    BEHIND_CHECKPOINT means ONLY "the presented journal does not reach the
    retained checkpointed historical position" - never a claim of rollback,
    attack, or malicious intent, and never distinguishable here from benign
    truncation. An empty presented journal is classified BEHIND_CHECKPOINT
    directly (no current_head_sequence = -1 is ever synthesized as an
    authoritative fact - there is no head, so this is a consistency
    classification only, made explicit rather than derived from a fake
    position).

    Exact-entry match is load-bearing: because a valid, non-empty
    verify_decision_journal() result already guarantees entries[i].sequence
    == i for every i, entries[checkpoint.head_sequence] is always a safe,
    direct index once the journal reaches or passes that position - never a
    scan. The comparison against checkpoint.head_entry_fingerprint at
    EXACTLY that position (not merely "current head is past
    checkpoint.head_sequence") is what makes AHEAD_OF_CHECKPOINT a real
    consistency guarantee: LONGER JOURNAL != CONSISTENT EXTENSION. This same
    mechanism is what lets E3 detect a fully self-consistent rewritten
    chain: E2 alone cannot distinguish an original E0->E1->E2->E3 from a
    fully rewritten E0'->E1'->E2'->E3'->E4' (both may verify valid=True),
    but a checkpoint retained from before the rewrite will not match the
    rewritten entry at its exact retained sequence, producing
    CHECKPOINT_MISMATCH.

    PERMANENT, EXPLICIT LIMITATIONS - do not weaken these claims:
    CHECKPOINT CONSISTENCY != EXTERNAL ANCHORING. If both the presented
    journal AND the retained checkpoint are replaced together inside the
    same trust domain, this function - a pure function over whatever it is
    handed, with no independent retention mechanism of its own - cannot
    detect that. A hidden fork is not detectable either: two branches that
    each independently extend the same retained checkpoint (e.g.
    E0->E1->E2A and E0->E1->E2B, checkpointed at E1) will each,
    verified separately, correctly return AHEAD_OF_CHECKPOINT/verified=True
    - this function only ever reasons about the single `entries` list it is
    given, with no cross-branch or cross-call comparison. Fork/gossip/
    witness comparison remains out of scope. This function also does not
    prove the underlying DecisionRecord referenced by any entry's
    decision_fingerprint exists or is semantically valid - identical to
    verify_decision_journal()'s own boundary, unchanged here."""
    _require(isinstance(checkpoint, DecisionJournalCheckpoint), "checkpoint must be a DecisionJournalCheckpoint")

    if journal_id is not None:
        _require_nonempty_str(journal_id, "journal_id")

    expected_journal_id = journal_id if journal_id is not None else checkpoint.journal_id

    if checkpoint.journal_id != expected_journal_id:
        return CheckpointVerificationResult(verified=False, status="JOURNAL_ID_MISMATCH", reason_code="JOURNAL_ID_MISMATCH")

    journal_result = verify_decision_journal(entries, journal_id=expected_journal_id)
    if not journal_result.valid:
        return CheckpointVerificationResult(verified=False, status="JOURNAL_INVALID", reason_code=journal_result.reason_code)

    if len(entries) == 0:
        return CheckpointVerificationResult(verified=False, status="BEHIND_CHECKPOINT", reason_code="BEHIND_CHECKPOINT")

    current_head_sequence = entries[-1].sequence

    if current_head_sequence < checkpoint.head_sequence:
        return CheckpointVerificationResult(verified=False, status="BEHIND_CHECKPOINT", reason_code="BEHIND_CHECKPOINT")

    checkpoint_entry = entries[checkpoint.head_sequence]
    if checkpoint_entry.entry_fingerprint != checkpoint.head_entry_fingerprint:
        return CheckpointVerificationResult(verified=False, status="CHECKPOINT_MISMATCH", reason_code="CHECKPOINT_MISMATCH")

    if current_head_sequence == checkpoint.head_sequence:
        return CheckpointVerificationResult(verified=True, status="AT_CHECKPOINT")

    return CheckpointVerificationResult(verified=True, status="AHEAD_OF_CHECKPOINT")
