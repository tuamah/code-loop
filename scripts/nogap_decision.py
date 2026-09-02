#!/usr/bin/env python3
"""M8-A/M8-B: Decision Contracts & Safety Model, Immutable Decision Snapshot.

M8-B ADDENDUM: adds SnapshotReference, DecisionSubject, and DecisionSnapshot -
a pure, immutable identity layer binding a future decision to the EXACT state
it was about (Principle 2, in-toto/SLSA-derived: "a trusted statement is about
an immutable subject"). Like M8-A, this addition is CONTRACT-ONLY:
  - build_decision_snapshot() accepts only explicit, already-resolved
    SnapshotReference/DecisionSubject values. It performs no filesystem, Git,
    M7 methodology-state, verification-directory, decision-ledger, memory,
    research, environment, network, or implicit-clock access of any kind.
  - A DecisionSnapshot carries facts/references only - it structurally cannot
    carry a verdict, a requested_verdict, a confidence/score, or a vote; no
    such field exists anywhere on DecisionSnapshot or SnapshotReference, and
    no method on either class derives one.
  - Capturing a reference into a snapshot does not prove it valid, fresh,
    independent, or authoritative - that evaluation belongs to M8-D/M8-E/M8-F.
    A SnapshotReference is a provenance BINDING, never a truth claim.
  - Fingerprinting reuses this module's own canonical_json() (no second
    competing canonicalizer) and stdlib hashlib.sha256 (no Python hash(),
    mtime, uuid, or filename-based identity anywhere).
  - Candidate fingerprints are NOT recomputed here - scripts/nogap_lifecycle.py's
    compute_candidate_fingerprint() remains the sole owner; DecisionSubject
    only carries whatever value that function already produced, verbatim, as
    an opaque already-computed digest. Likewise gate fingerprints remain
    scripts/nogap.py's gate_hash()'s sole ownership.

This module defines the formal vocabulary and structural safety contracts for
NoGapCode's future Decision Engine (M8). It is CONTRACT FOUNDATION ONLY:

  - It does NOT read the filesystem, runtime evidence, methodology state,
    verification records, failure records, research records, memory, or CLI
    input. It has zero imports from any other nogap_*.py module or from
    Python's filesystem/process libraries - by construction, not by
    discipline alone.
  - It does NOT call an LLM, AgentRuntime, model provider, or any consensus/
    voting/scoring mechanism. There is no such call site to remove later.
  - It does NOT persist decisions, does NOT implement a "current decision"
    selector, and does NOT migrate scripts/nogap.py's existing cmd_decide()/
    acceptability() (M6/M7's existing acceptance surface) or
    nogap_lifecycle.py's decision_refs resolution. Those remain exactly as
    they are; M8-A only defines the vocabulary a LATER milestone (M8-J) will
    use to eventually become the single writer.
  - It provides exactly one pure algebra helper, derive_contract_verdict(),
    which operates only on already-formed DecisionPredicateResult objects
    supplied by the caller. It proves the safety algebra is representable and
    deterministic; it is not the production kernel.

CANONICAL RULE: MODEL OPINION IS NOT ACCEPTANCE AUTHORITY. There is no
DecisionScore, acceptance_probability, or weighted_vote anywhere in this
module, and none may be added without discarding the entire safety model
this milestone establishes - the algebra is conjunctive/constraint-based,
never additive/weighted. A single failed mandatory condition can never be
outweighed by any number of positive ones.

NAMESPACE SEPARATION (enforced by construction, regression-tested in
tests/test_decision_contracts.py against the real vocabularies): DecisionVerdict
{ACCEPT, REJECT, ABSTAIN} is disjoint from every other outcome vocabulary this
codebase already owns elsewhere - nogap_research.py's ASSESSMENT_OUTCOMES
(SUPPORTED/PARTIALLY_SUPPORTED/REFUTED/INCONCLUSIVE), nogap_lifecycle.py's
READINESS_OUTCOMES/DEPLOYMENT_STATUSES/LIFECYCLE_OUTCOMES, and
nogap_verification.py's review verdict vocabulary (pass/fail/inconclusive).
None of those may ever be read as a DecisionVerdict, and DecisionVerdict may
never be written into their fields. Each vocabulary keeps its own owner.

AUTHORITY CLASS MAPPING (documented, not imported - this module has zero
dependencies on other project modules): AUTHORITY_CLASSES below is the M8-own
uppercase vocabulary. It corresponds conceptually to scripts/nogap.py's
ACCEPTANCE_AUTHORITIES = {"acceptance", "human"} and
scripts/nogap_methodology.py's TRANSITION_AUTHORITY_CLASSES =
{"execution", "verification", "acceptance", "human", "tool"}:
  EXECUTION            <-> "execution"
  VERIFICATION         <-> "verification"
  ACCEPTANCE           <-> "acceptance"
  HUMAN                <-> "human"
  SYSTEM_DETERMINISTIC <-> "tool"
  ADVISORY             <-> (new: advisory-only sources, e.g. model review
                             votes, that carry no acceptance weight at all -
                             M7 has no equivalent because M7 never lets
                             advisory sources near acceptance in the first
                             place)
AuthorityClass is descriptive provenance context ONLY - this module
deliberately defines NO "acceptance capable" classification of actor
authority at all, not even a narrow one. An earlier draft of this module
defined ACCEPTANCE_CAPABLE_AUTHORITY_CLASSES = {"ACCEPTANCE", "HUMAN"} plus
an authority_class_is_acceptance_capable() helper; both were REMOVED after
architectural review concluded the names could later be misread as "these
authority classes may authorize writing DecisionVerdict.ACCEPT" - exactly
the sole-writer boundary M8 exists to prevent any actor from crossing.
Neither name nor an equivalent replacement exists anywhere in this module.
HUMAN authority means policy/risk/lifecycle authority where applicable; it
does NOT mean "a human can manufacture technical ACCEPT". A legacy class
named ACCEPTANCE (see the mapping above - nogap.py's own bare, self-asserted
CLI flag) is not, and must never become, the authorization mechanism for the
future M8 technical decision writer. Safety Property S5 (Execution authority
!= Acceptance authority) is proven structurally, not by a permissioning
helper: derive_contract_verdict() below takes no actor/authority parameter
of any kind - there is no code path through which any AuthorityClass value,
including HUMAN or ACCEPTANCE, could influence a verdict. The eventual
sole-writer boundary (M8 Decision Engine owns all ACCEPT/REJECT/ABSTAIN
writes) is future kernel/persistence-layer work (M8-D/M8-F/M8-J); M8-A's
contribution is simply refusing to define a shortcut that would let a later
milestone reach for `actor.authority == HUMAN` or `== ACCEPTANCE` as if it
were an authorization check.

FORMAL SAFETY PROPERTIES this module's contracts make representable and
tests directly (see tests/test_decision_contracts.py for the regressions):
  S1  Any mandatory predicate UNKNOWN            -> verdict != ACCEPT
  S2  Any mandatory predicate CONFLICT           -> verdict != ACCEPT
  S3  A proven blocking violation exists         -> verdict != ACCEPT
  S4  STALE required evidence                    -> that predicate cannot be TRUE
  S5  Execution authority != Acceptance authority (no AuthorityClass, incl.
      HUMAN or ACCEPTANCE, is ever verdict-capable by itself - proven by
      derive_contract_verdict() having no actor/authority parameter at all)
  S6  FrozenGateHash != ExecutedGateHash          -> verdict != ACCEPT (GATE_TAMPERING)
  S7  EvidenceScope != DecisionScope              -> evidence cannot satisfy a
                                                      mandatory predicate
  S8  Research SUPPORTED                         -> never implies ACCEPT
  S9  Verification PASS alone                    -> never implies ACCEPT
  S10 Deployment SUCCEEDED                       -> never implies ACCEPT
  S11 Memory projection                          -> never implies ACCEPT
  S12 Model consensus                            -> never implies ACCEPT
Liveness: if every mandatory REQUIREMENT predicate is TRUE, no blocking
VIOLATION predicate is TRUE, and no mandatory predicate is UNKNOWN/CONFLICT,
derive_contract_verdict() returns ACCEPT - the contract makes ACCEPT reachable,
it is never the default branch of the algebra.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import hashlib
import json
import re
import types
from typing import Any, Mapping, Sequence

# --- versioning ---------------------------------------------------------------

M8_DECISION_SCHEMA_VERSION = "1"
M8_DECISION_ENGINE_VERSION = "1"
_SUPPORTED_SCHEMA_VERSIONS = {M8_DECISION_SCHEMA_VERSION}
_SUPPORTED_ENGINE_VERSIONS = {M8_DECISION_ENGINE_VERSION}


class DecisionValidationError(Exception):
    """Raised for any malformed M8 decision contract. Fail closed, never a
    silent skip or partial acceptance of malformed input. Deliberately NOT
    MethodologyValidationError - a different semantic owner (M7 methodology
    contracts vs. M8 decision contracts); conflating them would blur which
    milestone's invariant was actually violated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DecisionValidationError(message)


def _require_supported_schema_version(value: str) -> None:
    _require(value in _SUPPORTED_SCHEMA_VERSIONS, f"unsupported schema_version: {value!r}")


def _require_supported_engine_version(value: str) -> None:
    _require(value in _SUPPORTED_ENGINE_VERSIONS, f"unsupported engine_version: {value!r}")


def _require_str_tuple(value: Any, field_name: str, *, allow_empty_tuple: bool = True) -> tuple[str, ...]:
    _require(isinstance(value, (tuple, list)), f"{field_name} must be a tuple/list of str")
    items = tuple(value)
    for item in items:
        _require(isinstance(item, str) and item.strip() != "", f"{field_name} entries must be non-empty strings")
    if not allow_empty_tuple:
        _require(bool(items), f"{field_name} must not be empty")
    _require(len(set(items)) == len(items), f"{field_name} must not contain duplicates")
    return items


def _require_nonempty_str(value: Any, field_name: str) -> None:
    _require(isinstance(value, str) and value.strip() != "", f"{field_name} must be a non-empty string")


def _require_json_compatible(value: Any, field_name: str) -> None:
    try:
        json.dumps(value)
    except TypeError as exc:
        raise DecisionValidationError(f"{field_name} must be JSON-compatible: {exc}") from None


# --- core vocabularies ----------------------------------------------------------

# The ONLY technical verdict vocabulary. PASS/FAIL/APPROVE/DENY/SUCCESS/SUPPORTED
# etc. may never substitute for these - see namespace-separation tests.
DECISION_VERDICTS = frozenset({"ACCEPT", "REJECT", "ABSTAIN"})

# Four-valued predicate truth. Never collapse UNKNOWN to FALSE or CONFLICT to an
# arbitrary winner - that collapse is exactly what this vocabulary exists to
# make structurally impossible (bool cannot represent it at all).
DECISION_TRUTH_VALUES = frozenset({"TRUE", "FALSE", "UNKNOWN", "CONFLICT"})

# Minimal initial decision-type vocabulary. Deliberately NOT used for research
# claim outcomes, deployment status, operational health, or methodology
# lifecycle outcomes - those already have their own semantic owners elsewhere
# in this codebase (nogap_research.py, nogap_lifecycle.py).
DECISION_TYPES = frozenset({"TASK_ACCEPTANCE", "REPAIR_ACCEPTANCE", "RELEASE_ACCEPTANCE"})

DECISION_SCOPE_TYPES = frozenset({"TASK", "REPAIR", "RELEASE"})

# REQUIREMENT: TRUE=satisfied, FALSE=positively failed, UNKNOWN=insufficient
#              evidence, CONFLICT=conflicting evidence.
# VIOLATION:   TRUE=blocking violation positively exists, FALSE=violation
#              positively absent, UNKNOWN=cannot determine, CONFLICT=conflicting
#              evidence.
PREDICATE_ROLES = frozenset({"REQUIREMENT", "VIOLATION"})

# See module docstring's AUTHORITY CLASS MAPPING for the M7 correspondence.
AUTHORITY_CLASSES = frozenset({
    "EXECUTION", "VERIFICATION", "ACCEPTANCE", "HUMAN", "SYSTEM_DETERMINISTIC", "ADVISORY",
})

## Deliberately NO "acceptance capable" authority-class classification exists
## here (see module docstring: removed after architectural review). Do not
## reintroduce ACCEPTANCE_CAPABLE_AUTHORITY_CLASSES or an
## authority_class_is_acceptance_capable()-shaped helper - AuthorityClass is
## descriptive provenance only, and no actor identity or class may ever be
## consulted by derive_contract_verdict() to influence a verdict.

FRESHNESS_STATUSES = frozenset({"FRESH", "STALE", "UNKNOWN"})

# Stable, non-overlapping machine-readable reason codes. Free prose is never
# authoritative on its own (see `details` field docs below).
DECISION_REASON_CODES = frozenset({
    "MISSING_REQUIRED_EVIDENCE",
    "STALE_REQUIRED_EVIDENCE",
    "EVIDENCE_CONFLICT",
    "SCOPE_MISMATCH",
    "INVALID_AUTHORITY",
    "MANDATORY_PREDICATE_FALSE",
    "MANDATORY_PREDICATE_UNKNOWN",
    "MANDATORY_PREDICATE_CONFLICT",
    "BLOCKING_FAILURE",
    "GATE_FAILURE",
    "GATE_TAMPERING",
    "VERIFICATION_INCOMPLETE",
    "VERIFICATION_STALE",
    "METHODOLOGY_NOT_READY",
    "DECISION_POLICY_INVALID",
    "INPUT_INVALID",
})


# --- canonical serialization -----------------------------------------------------

# Excluded, by field name, from canonical form / semantic equality wherever
# they occur on ANY dataclass in this module: created_at/evaluated_at/
# captured_at record *when* a contract was produced, never *what* it means
# (two evaluations of the same inputs a second apart must canonicalize
# identically); `locator` (SnapshotReference's WHERE-to-find-it metadata) is
# explicitly non-authoritative and must never participate in identity - see
# SnapshotReference's own docstring. A field with one of these names is
# non-semantic on every dataclass in this module; none of them happens to
# carry a DIFFERENT, semantically-meaningful field under the same name.
_NON_SEMANTIC_FIELD_NAMES = frozenset({"created_at", "evaluated_at", "captured_at", "locator"})


def _canonicalize(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        result = {}
        for f in dataclasses.fields(value):
            if f.name in _NON_SEMANTIC_FIELD_NAMES:
                continue
            result[f.name] = _canonicalize(getattr(value, f.name))
        return result
    if isinstance(value, (list, tuple)):
        items = [_canonicalize(v) for v in value]
        if items and all(isinstance(v, str) for v in items):
            return sorted(items)
        if items and all(isinstance(v, dict) for v in items):
            return sorted(items, key=lambda d: json.dumps(d, sort_keys=True, separators=(",", ":")))
        return items
    if isinstance(value, collections.abc.Mapping):
        # Mapping, not bare dict: also handles types.MappingProxyType, the
        # deep-frozen representation _deep_freeze() below produces - so this
        # stays correct even if canonical_json() is ever pointed at a raw
        # DecisionSnapshot instead of its semantic_payload().
        return {k: _canonicalize(v) for k, v in sorted(value.items())}
    return value


def _deep_freeze(value: Any) -> Any:
    """Recursively converts dict -> types.MappingProxyType (over a dict whose
    values are themselves already deep-frozen) and list/tuple -> tuple (of
    already deep-frozen elements), so NO mutable container is reachable
    anywhere in the returned structure - not the top level, and not any
    nested level. Scalars (str/int/float/bool/None - the only other types
    JSON-compatible metadata can contain, per _require_json_compatible)
    pass through unchanged, since they are already immutable.

    A single-level `dict(...)` or `tuple(...)` copy is NOT sufficient: it
    protects only the outermost container, while any nested dict/list
    remains the SAME mutable object the caller can still reach and mutate
    through their own original reference (an aliasing attack). This function
    closes that gap by freezing every level, not just the first."""
    if isinstance(value, dict):
        return types.MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


def canonical_json(contract: Any) -> str:
    """Deterministic canonical JSON for any contract dataclass in this module -
    stable field ordering, set-like collections sorted, timestamps excluded.
    Does not implement cryptographic hash chaining (that is M8-G); this only
    guarantees hashing/replay are not made impossible later."""
    return json.dumps(_canonicalize(contract), sort_keys=True, separators=(",", ":"))


# --- DecisionScope ----------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class DecisionScope:
    scope_type: str
    scope_id: str
    project_id: str
    revision_ref: str | None = None
    candidate_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(self.scope_type in DECISION_SCOPE_TYPES, f"unknown scope_type: {self.scope_type!r}")
        _require_nonempty_str(self.scope_id, "scope_id")
        _require_nonempty_str(self.project_id, "project_id")
        if self.revision_ref is not None:
            _require_nonempty_str(self.revision_ref, "revision_ref")
        if self.candidate_ref is not None:
            _require_nonempty_str(self.candidate_ref, "candidate_ref")
        object.__setattr__(self, "artifact_refs", _require_str_tuple(self.artifact_refs, "artifact_refs"))

    def canonical_id(self) -> str:
        """Deterministic canonical scope identity string - the value predicate
        results' `scope_ref` must match to satisfy a mandatory predicate (S7)."""
        return f"{self.scope_type}:{self.project_id}:{self.scope_id}"


# --- DecisionPredicateResult -------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class DecisionPredicateResult:
    predicate_id: str
    role: str
    truth_value: str
    required: bool
    blocking: bool
    reason_codes: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    authority_refs: tuple[str, ...] = ()
    scope_ref: str | None = None
    freshness_status: str | None = None
    details: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty_str(self.predicate_id, "predicate_id")
        _require(self.role in PREDICATE_ROLES, f"unknown predicate role: {self.role!r}")
        _require(self.truth_value in DECISION_TRUTH_VALUES, f"unknown truth_value: {self.truth_value!r}")
        _require(isinstance(self.required, bool), "required must be an explicit bool")
        _require(isinstance(self.blocking, bool), "blocking must be an explicit bool")

        reason_codes = _require_str_tuple(self.reason_codes, "reason_codes")
        for code in reason_codes:
            _require(code in DECISION_REASON_CODES, f"unknown reason code: {code!r}")
        object.__setattr__(self, "reason_codes", reason_codes)

        object.__setattr__(self, "source_refs", _require_str_tuple(self.source_refs, "source_refs"))
        object.__setattr__(self, "authority_refs", _require_str_tuple(self.authority_refs, "authority_refs"))

        if self.scope_ref is not None:
            _require_nonempty_str(self.scope_ref, "scope_ref")
        if self.freshness_status is not None:
            _require(self.freshness_status in FRESHNESS_STATUSES, f"unknown freshness_status: {self.freshness_status!r}")
        if self.details is not None:
            _require(isinstance(self.details, str), "details must be a string when provided")

        # Safety Property S4: stale required evidence can never prove TRUE.
        # `details` (free prose) is explicitly NOT consulted anywhere in this
        # module for truth - only structured fields are.
        if self.freshness_status == "STALE":
            _require(self.truth_value != "TRUE", "S4 violation: STALE evidence cannot prove a predicate TRUE")


# --- DecisionPolicyContract --------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class DecisionPolicyContract:
    decision_type: str
    policy_id: str
    policy_version: str
    required_predicate_ids: tuple[str, ...] = ()
    blocking_predicate_ids: tuple[str, ...] = ()
    optional_predicate_ids: tuple[str, ...] = ()
    required_authority_classes: tuple[str, ...] = ()
    profile_constraints: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    schema_version: str = M8_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.decision_type in DECISION_TYPES, f"unknown decision_type: {self.decision_type!r}")
        _require_nonempty_str(self.policy_id, "policy_id")
        _require_nonempty_str(self.policy_version, "policy_version")
        _require_supported_schema_version(self.schema_version)

        required = _require_str_tuple(self.required_predicate_ids, "required_predicate_ids")
        blocking = _require_str_tuple(self.blocking_predicate_ids, "blocking_predicate_ids")
        optional = _require_str_tuple(self.optional_predicate_ids, "optional_predicate_ids")
        object.__setattr__(self, "required_predicate_ids", required)
        object.__setattr__(self, "blocking_predicate_ids", blocking)
        object.__setattr__(self, "optional_predicate_ids", optional)

        # A predicate_id may belong to exactly one category - contradictory
        # simultaneous categorization fails closed rather than picking a winner.
        req_set, block_set, opt_set = set(required), set(blocking), set(optional)
        _require(not (req_set & block_set), f"predicate(s) classified both required and blocking: {sorted(req_set & block_set)}")
        _require(not (req_set & opt_set), f"predicate(s) classified both required and optional: {sorted(req_set & opt_set)}")
        _require(not (block_set & opt_set), f"predicate(s) classified both blocking and optional: {sorted(block_set & opt_set)}")

        authority_classes = _require_str_tuple(self.required_authority_classes, "required_authority_classes")
        for authority in authority_classes:
            _require(authority in AUTHORITY_CLASSES, f"unknown authority class in policy: {authority!r}")
        object.__setattr__(self, "required_authority_classes", authority_classes)

        object.__setattr__(self, "profile_constraints", _require_str_tuple(self.profile_constraints, "profile_constraints"))

        _require(isinstance(self.metadata, dict), "metadata must be a dict")
        _require_json_compatible(self.metadata, "metadata")  # validated on the plain input, before freezing
        # M8-A-H1 hardening: a shallow dict(...) copy only protects the top
        # level - nested dict/list values remained the SAME mutable objects
        # the caller could still reach and mutate (an aliasing attack),
        # exactly the gap M8-B's DecisionSnapshot.metadata had before its own
        # hardening fix. Reuses that SAME _deep_freeze() primitive - no
        # second, competing deep-freeze implementation exists in this module.
        object.__setattr__(self, "metadata", _deep_freeze(self.metadata))


# --- DecisionRequestContract --------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class DecisionRequestContract:
    """A REQUEST asks the Decision Engine to evaluate. It never tells the
    engine what result to return - there is deliberately no requested_verdict
    (or similarly named) field anywhere in this dataclass. Passing one raises
    TypeError at construction (an unknown dataclass field), which is the
    intended, structural enforcement - not a runtime string check."""

    request_id: str
    project_id: str
    decision_type: str
    scope: DecisionScope
    requested_by: str
    requester_authority: str
    reason: str
    policy_ref: str | None = None
    schema_version: str = M8_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty_str(self.request_id, "request_id")
        _require_nonempty_str(self.project_id, "project_id")
        _require(self.decision_type in DECISION_TYPES, f"unknown decision_type: {self.decision_type!r}")
        _require(isinstance(self.scope, DecisionScope), "scope must be a DecisionScope")
        _require_nonempty_str(self.requested_by, "requested_by")
        _require(self.requester_authority in AUTHORITY_CLASSES, f"unknown requester_authority: {self.requester_authority!r}")
        _require_nonempty_str(self.reason, "reason")
        if self.policy_ref is not None:
            _require_nonempty_str(self.policy_ref, "policy_ref")
        _require_supported_schema_version(self.schema_version)


# --- DecisionEvaluationContract ------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class DecisionEvaluationContract:
    """Represents the future pure kernel's output. M8-A does not compute a real
    immutable DecisionSnapshot (M8-B); `input_fingerprint` is a placeholder
    field only, to keep that future binding representable."""

    evaluation_id: str
    request_id: str
    decision_type: str
    scope: DecisionScope
    policy_ref: str
    predicate_results: tuple[DecisionPredicateResult, ...]
    satisfied_predicates: tuple[str, ...]
    failed_predicates: tuple[str, ...]
    unknown_predicates: tuple[str, ...]
    conflicting_predicates: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    reason_codes: tuple[str, ...]
    verdict: str
    input_fingerprint: str | None = None
    engine_version: str = M8_DECISION_ENGINE_VERSION
    schema_version: str = M8_DECISION_SCHEMA_VERSION
    evaluated_at: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty_str(self.evaluation_id, "evaluation_id")
        _require_nonempty_str(self.request_id, "request_id")
        _require(self.decision_type in DECISION_TYPES, f"unknown decision_type: {self.decision_type!r}")
        _require(isinstance(self.scope, DecisionScope), "scope must be a DecisionScope")
        _require_nonempty_str(self.policy_ref, "policy_ref")
        _require_supported_schema_version(self.schema_version)
        _require_supported_engine_version(self.engine_version)

        _require(isinstance(self.predicate_results, (tuple, list)), "predicate_results must be a tuple/list")
        predicate_results = tuple(self.predicate_results)
        for pr in predicate_results:
            _require(isinstance(pr, DecisionPredicateResult), "predicate_results entries must be DecisionPredicateResult")
        ids = [pr.predicate_id for pr in predicate_results]
        _require(len(set(ids)) == len(ids), "predicate_results contains duplicate predicate_id")
        object.__setattr__(self, "predicate_results", predicate_results)

        by_id = {pr.predicate_id: pr for pr in predicate_results}
        satisfied = _require_str_tuple(self.satisfied_predicates, "satisfied_predicates")
        failed = _require_str_tuple(self.failed_predicates, "failed_predicates")
        unknown = _require_str_tuple(self.unknown_predicates, "unknown_predicates")
        conflicting = _require_str_tuple(self.conflicting_predicates, "conflicting_predicates")
        buckets = {"satisfied": (satisfied, "TRUE"), "failed": (failed, "FALSE"), "unknown": (unknown, "UNKNOWN"), "conflicting": (conflicting, "CONFLICT")}
        seen: set[str] = set()
        for bucket_name, (bucket_ids, expected_truth) in buckets.items():
            for pid in bucket_ids:
                _require(pid in by_id, f"{bucket_name}_predicates references unknown predicate_id {pid!r}")
                _require(by_id[pid].truth_value == expected_truth, f"{bucket_name}_predicates lists {pid!r} but its truth_value is {by_id[pid].truth_value!r}")
                _require(pid not in seen, f"predicate {pid!r} appears in more than one result bucket")
                seen.add(pid)
        _require(seen == set(by_id), "every predicate_results entry must appear in exactly one result bucket")
        object.__setattr__(self, "satisfied_predicates", satisfied)
        object.__setattr__(self, "failed_predicates", failed)
        object.__setattr__(self, "unknown_predicates", unknown)
        object.__setattr__(self, "conflicting_predicates", conflicting)

        object.__setattr__(self, "blocking_reasons", _require_str_tuple(self.blocking_reasons, "blocking_reasons"))
        reason_codes = _require_str_tuple(self.reason_codes, "reason_codes")
        for code in reason_codes:
            _require(code in DECISION_REASON_CODES, f"unknown reason code: {code!r}")
        object.__setattr__(self, "reason_codes", reason_codes)

        _require(self.verdict in DECISION_VERDICTS, f"unknown verdict: {self.verdict!r}")
        if self.input_fingerprint is not None:
            _require_nonempty_str(self.input_fingerprint, "input_fingerprint")


# --- DecisionRecordContract ----------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class DecisionRecordContract:
    """Conceptually IMMUTABLE. There is no update_verdict()/set_accept()/
    rewrite_decision() method anywhere on this class or module, and being a
    frozen dataclass, any attempt to assign an attribute after construction
    raises dataclasses.FrozenInstanceError. New evidence must produce a NEW
    DecisionRecordContract (with `supersedes` pointing at the old one), never
    a mutation of this one. Persistence, hash chaining, and a real
    get_current_decision() selector are explicitly out of scope for M8-A
    (M8-G territory) - the fields below only avoid blocking that later work."""

    decision_id: str
    evaluation_id: str
    request_id: str
    decision_type: str
    scope: DecisionScope
    verdict: str
    reason_codes: tuple[str, ...]
    evaluation_ref: str
    policy_ref: str
    created_at: str
    engine_version: str = M8_DECISION_ENGINE_VERSION
    schema_version: str = M8_DECISION_SCHEMA_VERSION
    supersedes: str | None = None
    previous_decision_hash: str | None = None
    decision_hash: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty_str(self.decision_id, "decision_id")
        _require_nonempty_str(self.evaluation_id, "evaluation_id")
        _require_nonempty_str(self.request_id, "request_id")
        _require(self.decision_type in DECISION_TYPES, f"unknown decision_type: {self.decision_type!r}")
        _require(isinstance(self.scope, DecisionScope), "scope must be a DecisionScope")
        _require(self.verdict in DECISION_VERDICTS, f"unknown verdict: {self.verdict!r}")

        reason_codes = _require_str_tuple(self.reason_codes, "reason_codes")
        for code in reason_codes:
            _require(code in DECISION_REASON_CODES, f"unknown reason code: {code!r}")
        object.__setattr__(self, "reason_codes", reason_codes)

        _require_nonempty_str(self.evaluation_ref, "evaluation_ref")
        _require_nonempty_str(self.policy_ref, "policy_ref")
        _require_nonempty_str(self.created_at, "created_at")
        _require_supported_engine_version(self.engine_version)
        _require_supported_schema_version(self.schema_version)
        if self.supersedes is not None:
            _require_nonempty_str(self.supersedes, "supersedes")
        if self.previous_decision_hash is not None:
            _require_nonempty_str(self.previous_decision_hash, "previous_decision_hash")
        if self.decision_hash is not None:
            _require_nonempty_str(self.decision_hash, "decision_hash")


# --- pure verdict derivation algebra --------------------------------------------------

@dataclasses.dataclass(frozen=True)
class DecisionAlgebraResult:
    verdict: str
    blocking_reasons: tuple[str, ...]
    reason_codes: tuple[str, ...]


def derive_contract_verdict(
    predicate_results: Sequence[DecisionPredicateResult],
    *,
    policy_contract: DecisionPolicyContract,
    scope: DecisionScope | None = None,
) -> DecisionAlgebraResult:
    """Pure contract-level verdict algebra. Operates ONLY on already-formed
    DecisionPredicateResult objects and a DecisionPolicyContract - no
    filesystem, runtime evidence, methodology state, verification records,
    failure records, research, memory, or CLI access of any kind.

    CANONICAL CONTRACT ALGEBRA (order matters for which branch fires, not for
    the final verdict's correctness under permutation of `predicate_results`,
    since predicates are looked up by id, not by list position):
      1. Validate all input; malformed input raises DecisionValidationError.
      2. Any acceptance-critical (required or blocking) predicate CONFLICT
         -> ABSTAIN.
      3. Any blocking VIOLATION predicate TRUE -> REJECT.
      4. Any mandatory REQUIREMENT predicate FALSE -> REJECT.
      5. Any mandatory predicate (REQUIREMENT or blocking VIOLATION) UNKNOWN
         -> ABSTAIN.
      6. Every mandatory REQUIREMENT TRUE and every blocking VIOLATION FALSE
         -> ACCEPT.
    ACCEPT is never a default branch; every other path returns before it.
    """
    _require(isinstance(policy_contract, DecisionPolicyContract), "policy_contract must be a DecisionPolicyContract")
    _require(isinstance(predicate_results, (list, tuple)), "predicate_results must be a list/tuple")
    results = list(predicate_results)
    for pr in results:
        _require(isinstance(pr, DecisionPredicateResult), "predicate_results entries must be DecisionPredicateResult")

    by_id: dict[str, DecisionPredicateResult] = {}
    for pr in results:
        _require(pr.predicate_id not in by_id, f"duplicate predicate_id in predicate_results: {pr.predicate_id!r}")
        by_id[pr.predicate_id] = pr

    required_ids = policy_contract.required_predicate_ids
    blocking_ids = policy_contract.blocking_predicate_ids
    optional_ids = policy_contract.optional_predicate_ids
    classified = set(required_ids) | set(blocking_ids) | set(optional_ids)

    for pid in required_ids:
        _require(pid in by_id, f"policy requires predicate {pid!r} but no result was supplied")
        pr = by_id[pid]
        _require(pr.role == "REQUIREMENT", f"policy classifies {pid!r} as required but its role is {pr.role!r}")
        _require(pr.required, f"policy classifies {pid!r} as required but the result's required flag is False")

    for pid in blocking_ids:
        _require(pid in by_id, f"policy references blocking predicate {pid!r} but no result was supplied")
        pr = by_id[pid]
        _require(pr.role == "VIOLATION", f"policy classifies {pid!r} as blocking but its role is {pr.role!r}")
        _require(pr.blocking, f"policy classifies {pid!r} as blocking but the result's blocking flag is False")

    for pid in optional_ids:
        if pid in by_id:
            pr = by_id[pid]
            _require(not pr.required and not pr.blocking, f"policy classifies {pid!r} as optional but the result declares required/blocking")

    for pid in by_id:
        _require(pid in classified, f"predicate_results contains {pid!r}, which the policy does not classify as required/blocking/optional")

    if scope is not None:
        expected = scope.canonical_id()
        for pid in (*required_ids, *blocking_ids):
            pr = by_id[pid]
            if pr.scope_ref is not None:
                _require(pr.scope_ref == expected, f"S7 scope mismatch on {pid!r}: predicate scope_ref {pr.scope_ref!r} != decision scope {expected!r}")

    mandatory_ids = (*required_ids, *blocking_ids)

    conflict_ids = [pid for pid in mandatory_ids if by_id[pid].truth_value == "CONFLICT"]
    if conflict_ids:
        reasons = tuple(f"{pid}: CONFLICT" for pid in conflict_ids)
        return DecisionAlgebraResult("ABSTAIN", reasons, ("MANDATORY_PREDICATE_CONFLICT",))

    violation_true_ids = [pid for pid in blocking_ids if by_id[pid].truth_value == "TRUE"]
    if violation_true_ids:
        reasons = tuple(f"{pid}: blocking violation TRUE" for pid in violation_true_ids)
        return DecisionAlgebraResult("REJECT", reasons, ("BLOCKING_FAILURE",))

    required_false_ids = [pid for pid in required_ids if by_id[pid].truth_value == "FALSE"]
    if required_false_ids:
        reasons = tuple(f"{pid}: FALSE" for pid in required_false_ids)
        return DecisionAlgebraResult("REJECT", reasons, ("MANDATORY_PREDICATE_FALSE",))

    unknown_ids = [pid for pid in mandatory_ids if by_id[pid].truth_value == "UNKNOWN"]
    if unknown_ids:
        reasons = tuple(f"{pid}: UNKNOWN" for pid in unknown_ids)
        return DecisionAlgebraResult("ABSTAIN", reasons, ("MANDATORY_PREDICATE_UNKNOWN",))

    return DecisionAlgebraResult("ACCEPT", (), ())


# ================================================================================
# M8-B: Immutable Decision Snapshot
# ================================================================================

def fingerprint_payload(payload: Any) -> str:
    """SHA-256 hex digest (64 lowercase hex chars, no prefix - the SAME bare
    format scripts/nogap.py's stable_hash()/gate_hash() and
    scripts/nogap_lifecycle.py's compute_candidate_fingerprint()/
    _artifact_content_hash() already use throughout this codebase) of a
    payload's canonical JSON form. Reuses canonical_json() - never a second,
    competing canonicalizer. A general-purpose utility; it does NOT become the
    owner of candidate/gate/methodology fingerprint semantics - those stay
    exactly where they already are."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
# Full immutable Git commit id only: 40-hex SHA-1 (the format every Git
# repository in practice still uses today) or 64-hex SHA-256 (the newer,
# still-uncommon Git object-format option) - both fixed lengths, lowercase
# hex, and both refer to an unchangeable commit object, never a branch name,
# "HEAD", or any other mutable locator. A branch name is exactly as long and
# as hex-shaped as neither of these in the general case, but even a
# coincidentally hex-looking branch name is still rejected on principle
# alone: revision_ref accepts only pre-validated, already-resolved commit
# ids from the caller - this module never resolves Git itself (M8-B does not
# invoke Git; a future integration seam does).
_GIT_REVISION_RE = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})$")


def _require_valid_digest(value: Any, field_name: str) -> None:
    _require(isinstance(value, str) and bool(_SHA256_HEX_RE.match(value)), f"{field_name} must be a 64-character lowercase hex SHA-256 digest")


def _require_valid_revision_ref(value: Any, field_name: str = "revision_ref") -> None:
    _require(isinstance(value, str), f"{field_name} must be a string")
    _require(
        bool(_GIT_REVISION_RE.match(value)),
        f"{field_name} must be a full immutable Git commit id (40-hex SHA-1 or 64-hex SHA-256) - "
        f"a branch name or other mutable locator is never accepted as revision identity",
    )


# Minimal, sufficient reference-kind vocabulary. Unknown kinds fail closed.
REFERENCE_KINDS = frozenset({
    "POLICY", "METHODOLOGY", "REQUIREMENT", "GATE", "EXECUTION_EVIDENCE",
    "VERIFICATION_EVIDENCE", "REVIEW", "FAILURE", "RESEARCH", "RELEASE", "ARTIFACT",
})

SUBJECT_TYPES = frozenset({"TASK", "REPAIR", "RELEASE"})


@dataclasses.dataclass(frozen=True)
class SnapshotReference:
    """An immutable provenance binding: WHAT this snapshot points at, by
    stable identity (ref_kind + ref_id) AND content fingerprint - never by
    locator alone. `locator` (e.g. a filesystem path) is non-authoritative
    metadata explaining WHERE something might currently be found; it never
    participates in identity or in the snapshot fingerprint. A later file
    replacement at the same locator is NOT the same SnapshotReference unless
    its fingerprint also matches (Mandatory Scenario 11).

    `fingerprint` is always caller-supplied. This module never computes it by
    hashing `ref_id` (that would only prove a name was hashed, never that any
    real content was inspected) and never reads the referenced content itself
    - the true owner of that content (nogap_lifecycle.py's
    compute_candidate_fingerprint(), nogap.py's gate_hash(), or a future
    M8-D/E evidence loader) computes it; this module only carries it."""

    ref_kind: str
    ref_id: str
    fingerprint: str
    schema_version: str = M8_DECISION_SCHEMA_VERSION
    locator: str | None = None

    def __post_init__(self) -> None:
        _require(self.ref_kind in REFERENCE_KINDS, f"unknown ref_kind: {self.ref_kind!r}")
        _require_nonempty_str(self.ref_id, "ref_id")
        _require_valid_digest(self.fingerprint, "fingerprint")
        _require_supported_schema_version(self.schema_version)
        if self.locator is not None:
            _require_nonempty_str(self.locator, "locator")

    def identity_key(self) -> tuple[str, str]:
        return (self.ref_kind, self.ref_id)


def _validate_reference_set(refs: Any, field_name: str, *, expected_kind: str | None = None) -> tuple[SnapshotReference, ...]:
    """Validates a collection of SnapshotReference for a snapshot field: type-
    checks every entry, optionally enforces a single expected ref_kind (so
    e.g. `gate_refs` cannot silently accept a REVIEW reference), converts to
    an immutable tuple (defeating mutable-input-attack - the caller's
    original list/set can be mutated afterward with zero effect), and fails
    closed on ANY duplicate ref_kind+ref_id pair - matching fingerprints or
    not. Duplicates are never silently deduplicated or resolved by
    first/last-wins; they signal malformed or ambiguous provenance."""
    _require(isinstance(refs, (tuple, list, set, frozenset)), f"{field_name} must be a tuple/list of SnapshotReference")
    refs = tuple(refs)
    for ref in refs:
        _require(isinstance(ref, SnapshotReference), f"{field_name} entries must be SnapshotReference")
        if expected_kind is not None:
            _require(ref.ref_kind == expected_kind, f"{field_name} entries must be ref_kind {expected_kind!r}, got {ref.ref_kind!r}")
    seen: dict[tuple[str, str], str] = {}
    for ref in refs:
        key = ref.identity_key()
        if key in seen:
            raise DecisionValidationError(
                f"{field_name}: duplicate reference {key} - conflicting or repeated provenance is never silently "
                f"resolved (existing fingerprint {seen[key]!r}, new fingerprint {ref.fingerprint!r})"
            )
        seen[key] = ref.fingerprint
    return refs


@dataclasses.dataclass(frozen=True)
class DecisionSubject:
    """WHAT EXACT ENTITY/STATE IS BEING JUDGED - immutable concrete state
    within a DecisionScope's logical boundary, not merely the scope's mutable
    logical name. Example: scope names TASK/TASK-17 (a mutable logical
    boundary that can be re-evaluated many times); subject pins TASK-17 at a
    specific immutable Git revision, with an optional release-candidate
    fingerprint and artifact identities - THIS exact state, not "whatever
    TASK-17 currently looks like"."""

    subject_type: str
    subject_id: str
    project_id: str
    revision_ref: str
    candidate_fingerprint: str | None = None
    artifact_refs: tuple[SnapshotReference, ...] = ()

    def __post_init__(self) -> None:
        _require(self.subject_type in SUBJECT_TYPES, f"unknown subject_type: {self.subject_type!r}")
        _require_nonempty_str(self.subject_id, "subject_id")
        _require_nonempty_str(self.project_id, "project_id")
        _require_valid_revision_ref(self.revision_ref)
        if self.candidate_fingerprint is not None:
            _require_valid_digest(self.candidate_fingerprint, "candidate_fingerprint")
        object.__setattr__(self, "artifact_refs", _validate_reference_set(self.artifact_refs, "artifact_refs", expected_kind="ARTIFACT"))

    def canonical_id(self) -> str:
        return f"{self.subject_type}:{self.project_id}:{self.subject_id}@{self.revision_ref}"


_SNAPSHOT_REFERENCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("requirement_refs", "REQUIREMENT"),
    ("gate_refs", "GATE"),
    ("execution_evidence_refs", "EXECUTION_EVIDENCE"),
    ("verification_evidence_refs", "VERIFICATION_EVIDENCE"),
    ("review_refs", "REVIEW"),
    ("failure_refs", "FAILURE"),
    ("research_refs", "RESEARCH"),
    ("release_refs", "RELEASE"),
)


@dataclasses.dataclass(frozen=True)
class DecisionSnapshot:
    """Immutable identity layer binding a future decision to the exact state
    it is about (Principle 2). Contains facts/references ONLY - there is
    deliberately no verdict, requested_verdict, accept/reject/abstain result,
    confidence, score, or vote field anywhere on this class, and no method
    that derives one; snapshot construction cannot decide anything
    (Principle 6). A SnapshotReference captured here is a provenance binding,
    never a truth claim about freshness, independence, authority validity, or
    methodology readiness (Principle 7) - those remain M8-D/M8-E/M8-F.

    `subject` must lie WITHIN `scope`'s logical boundary (same project_id,
    same type, same id) - a snapshot cannot claim to be about scope
    TASK/TASK-17 while its subject silently names TASK-99.

    Reference collections (`requirement_refs`, `gate_refs`, ... `release_refs`)
    are set-like: constructor order never affects `snapshot_fingerprint`
    (canonical_json() sorts them), but any duplicate ref_kind+ref_id pair
    fails closed. Each collection enforces its own single ref_kind, so
    provenance types (execution evidence vs. verification evidence vs.
    review vs. research vs. failure vs. release) can never be silently mixed
    - preserving M8-A's namespace-separation guarantee at the snapshot layer.

    `captured_at` and `metadata` are explicitly NON-SEMANTIC: they participate
    in neither `semantic_payload()` nor `snapshot_fingerprint`. `metadata` may
    contain arbitrary diagnostic text (even text that happens to spell
    "ACCEPT" or "PASS") with zero effect on identity or fingerprint, and with
    no path anywhere in this class to convert it into a verdict. `metadata`
    is deep-frozen at construction (see `_deep_freeze()`) - not merely a
    shallow `dict(...)` copy - so no dict/list reachable from it, at any
    nesting depth, is mutable either through the snapshot itself
    (`snap.metadata["x"] = 2` raises `TypeError`) or via the caller's
    original input object after construction (an aliasing attack: mutating
    the caller's own nested dict/list post-construction has zero effect on
    the stored snapshot).

    `request_id` IS EXCLUDED from semantic identity: two different requests
    evaluating the exact same semantic state are recognized as the same
    snapshot identity; only WHAT the decision is about is semantic, never WHO
    asked. `request_id` remains provenance/correlation metadata for tracing
    which request produced this snapshot - it must never be treated as, or
    substituted for, content identity.

    `snapshot_id` is likewise EXCLUDED from semantic identity. It is an
    optional caller-supplied event/record/correlation identifier - a
    convenience label for a future persistence or audit layer, analogous to
    `SnapshotReference.locator` (a WHERE/WHICH-RECORD label, not a WHAT-IS-IT
    claim). `snapshot_fingerprint` - and ONLY `snapshot_fingerprint` - is the
    semantic, immutable content identity. Two snapshots sharing the same
    `snapshot_id` (e.g. a caller reusing a label, deliberately or by mistake)
    are NOT thereby proven to have the same content; `snapshot_id` must never
    be read as evidence of content equality, and no code anywhere in this
    class does so - only `snapshot_fingerprint` equality means that."""

    request_id: str
    decision_type: str
    scope: DecisionScope
    subject: DecisionSubject
    policy_ref: SnapshotReference
    methodology_ref: SnapshotReference | None = None
    requirement_refs: tuple[SnapshotReference, ...] = ()
    gate_refs: tuple[SnapshotReference, ...] = ()
    execution_evidence_refs: tuple[SnapshotReference, ...] = ()
    verification_evidence_refs: tuple[SnapshotReference, ...] = ()
    review_refs: tuple[SnapshotReference, ...] = ()
    failure_refs: tuple[SnapshotReference, ...] = ()
    research_refs: tuple[SnapshotReference, ...] = ()
    release_refs: tuple[SnapshotReference, ...] = ()
    captured_at: str | None = None
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    schema_version: str = M8_DECISION_SCHEMA_VERSION
    engine_version: str = M8_DECISION_ENGINE_VERSION
    snapshot_id: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty_str(self.request_id, "request_id")
        _require(self.decision_type in DECISION_TYPES, f"unknown decision_type: {self.decision_type!r}")
        _require(isinstance(self.scope, DecisionScope), "scope must be a DecisionScope")
        _require(isinstance(self.subject, DecisionSubject), "subject must be a DecisionSubject")
        _require(
            self.subject.subject_type == self.scope.scope_type
            and self.subject.subject_id == self.scope.scope_id
            and self.subject.project_id == self.scope.project_id,
            "subject must lie within scope's logical boundary (matching subject_type/subject_id/project_id) - "
            f"scope was {self.scope.canonical_id()!r}, subject was {self.subject.canonical_id()!r}",
        )
        _require(isinstance(self.policy_ref, SnapshotReference), "policy_ref must be a SnapshotReference")
        _require(self.policy_ref.ref_kind == "POLICY", f"policy_ref must be ref_kind POLICY, got {self.policy_ref.ref_kind!r}")

        if self.methodology_ref is not None:
            _require(isinstance(self.methodology_ref, SnapshotReference), "methodology_ref must be a SnapshotReference")
            _require(self.methodology_ref.ref_kind == "METHODOLOGY", f"methodology_ref must be ref_kind METHODOLOGY, got {self.methodology_ref.ref_kind!r}")

        for field_name, expected_kind in _SNAPSHOT_REFERENCE_FIELDS:
            object.__setattr__(self, field_name, _validate_reference_set(getattr(self, field_name), field_name, expected_kind=expected_kind))

        if self.captured_at is not None:
            _require_nonempty_str(self.captured_at, "captured_at")

        _require(isinstance(self.metadata, dict), "metadata must be a dict")
        _require_json_compatible(self.metadata, "metadata")  # validated on the plain input, before freezing
        # A single-level dict(...) copy only protects the top level - nested
        # dict/list values would remain the SAME mutable objects the caller
        # still holds a reference to (an aliasing attack: mutate a nested
        # value in the original after construction and the "immutable"
        # snapshot changes too). _deep_freeze() recursively converts every
        # level to MappingProxyType/tuple, so nothing mutable is reachable
        # from `self.metadata` at any depth - not even through the metadata
        # attribute itself (`snapshot.metadata["x"] = 2` now raises
        # TypeError, since MappingProxyType has no __setitem__).
        object.__setattr__(self, "metadata", _deep_freeze(self.metadata))

        _require_supported_schema_version(self.schema_version)
        _require_supported_engine_version(self.engine_version)
        if self.snapshot_id is not None:
            _require_nonempty_str(self.snapshot_id, "snapshot_id")

    def semantic_payload(self) -> dict[str, Any]:
        """The explicit, audited subset of fields that participate in
        `snapshot_fingerprint`. Deliberately excludes request_id, captured_at,
        metadata, and snapshot_id - see the class docstring for why each is
        non-semantic."""
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "decision_type": self.decision_type,
            "scope": self.scope,
            "subject": self.subject,
            "policy_ref": self.policy_ref,
            "methodology_ref": self.methodology_ref,
            "requirement_refs": self.requirement_refs,
            "gate_refs": self.gate_refs,
            "execution_evidence_refs": self.execution_evidence_refs,
            "verification_evidence_refs": self.verification_evidence_refs,
            "review_refs": self.review_refs,
            "failure_refs": self.failure_refs,
            "research_refs": self.research_refs,
            "release_refs": self.release_refs,
        }

    @property
    def snapshot_fingerprint(self) -> str:
        """Computed, never caller-supplied - a stored/settable fingerprint
        field would let a caller claim an identity its own content doesn't
        match. Deterministic: same semantic_payload() -> same fingerprint,
        independent of capture time, request identity, or reference-tuple
        construction order."""
        return fingerprint_payload(self.semantic_payload())


def build_decision_snapshot(
    *,
    request_id: str,
    decision_type: str,
    scope: DecisionScope,
    subject: DecisionSubject,
    policy_ref: SnapshotReference,
    methodology_ref: SnapshotReference | None = None,
    requirement_refs: Sequence[SnapshotReference] = (),
    gate_refs: Sequence[SnapshotReference] = (),
    execution_evidence_refs: Sequence[SnapshotReference] = (),
    verification_evidence_refs: Sequence[SnapshotReference] = (),
    review_refs: Sequence[SnapshotReference] = (),
    failure_refs: Sequence[SnapshotReference] = (),
    research_refs: Sequence[SnapshotReference] = (),
    release_refs: Sequence[SnapshotReference] = (),
    captured_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    snapshot_id: str | None = None,
) -> DecisionSnapshot:
    """Pure snapshot builder. Accepts ONLY explicit, already-resolved values -
    no filesystem, Git, M7 methodology-state, verification-directory,
    decision-ledger, memory, research, environment, network, or implicit-
    clock access of any kind. `captured_at` must be injected by the caller
    (e.g. from a future integration seam's own clock read); this function
    never calls one itself. All reference-collection arguments accept any
    ordering - DecisionSnapshot's own construction canonicalizes them."""
    return DecisionSnapshot(
        request_id=request_id,
        decision_type=decision_type,
        scope=scope,
        subject=subject,
        policy_ref=policy_ref,
        methodology_ref=methodology_ref,
        requirement_refs=tuple(requirement_refs),
        gate_refs=tuple(gate_refs),
        execution_evidence_refs=tuple(execution_evidence_refs),
        verification_evidence_refs=tuple(verification_evidence_refs),
        review_refs=tuple(review_refs),
        failure_refs=tuple(failure_refs),
        research_refs=tuple(research_refs),
        release_refs=tuple(release_refs),
        captured_at=captured_at,
        metadata=dict(metadata or {}),
        snapshot_id=snapshot_id,
    )
