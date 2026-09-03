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

Dependency direction is one-way: this module imports frozen primitives from
nogap_decision.py (DecisionValidationError, M8_DECISION_SCHEMA_VERSION,
fingerprint_payload, and the existing _require/_require_nonempty_str/
_require_valid_digest/_require_supported_schema_version validation helpers -
reused, not duplicated, exactly mirroring the established precedent of
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
from typing import Any

from nogap_decision import (
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
