#!/usr/bin/env python3
"""F3-A/F3-B: the exit-check registry (docs/f3-a-exit-check-registry-contract.md), and the
resolvers for F3-B1's 21 `DIRECT_COMPOSITION` rows.

This module is the code form of the frozen F3-A contract, nothing more. `MANIFEST` below is a
literal transcription of §9's canonical 50-row appendix - it decides no new classification, it
only encodes the one already accepted. `load_registry()` enforces §6's registry-load invariants
against the real, live `methodology/phases/p*.json` tree, exactly the "partition guard" shape
`nogap_required_kinds.declared_required_kinds()` already uses for F2b's closed map (§6, closing
note).

F3-B1 scope only (per the GO): resolvers exist for the 21 `DIRECT_COMPOSITION` rows whose
`unimplemented_reason` was `RESOLVER_PENDING` AND whose authoritative source is reachable from
`ResolverContext{project, phase_id}` alone, with no new selection logic. Two rows are
DELIBERATELY left `RESOLVER_PENDING` with no resolver bound - P13 `patch_artifact_recorded` and
P14 `execution_evidence_authority_is_execution` (F3-B2, BLOCKED on `RESOLVER-CONTEXT-REF-GAP-
PRE`): both require a transition-scoped reference (a patch file path, an evidence id) that has
no persisted, `phase_id`-indexed record to discover, and no existing authoritative "current"
selector exists for either - unlike release candidates (`nogap_lifecycle.
get_current_release_candidate`, reused below, not reinvented). Inventing one here would be
exactly the kind of new selection semantics the contract forbids (§4.1). P5/P8 (registry-
blocked on their own wording fixes) and every SMALL_BINDING/NO_REPRESENTATION/BUILD_INVARIANT/
CONFLICT row are equally out of scope - F3-D/F3-E/`BUILD-INVARIANT-PRE`/`P23-LIFECYCLE-OUTCOME-
PRE` own those, not this module.

F3-B2 (RESOLVER-CONTEXT-REF-GAP-PRE) added P13/P14's shared `lifecycle:transition_history`
resolver (§4.4.1's frozen lineage rule - see `_current_p13_attempt_binding`), so all 23
`RESOLVER_PENDING` rows are IMPLEMENTED as of that closure; only P5/P8 (registry-blocked on
their own wording fixes) remain UNIMPLEMENTED among the `DIRECT_COMPOSITION` rows.

F3-C adds `evaluate_exit_gate(project, phase_id) -> ExitGateEvaluation`: a read-only, report-
only evaluator, never called from `_evaluate_transition`, never blocking anything - it only
produces real PASS/FAIL/ERROR/UNIMPLEMENTED results for a phase's declared exit_gate.checks
for the first time. Nothing in this module is wired into `_evaluate_transition`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import nogap_artifacts as na
import nogap_required_kinds as rk

# -- result/outcome vocabulary (docs/f3-a-exit-check-registry-contract.md §3, §4) -----------

PASS = "PASS"
FAIL = "FAIL"
ERROR = "ERROR"

# -- classification (§9 legend) --------------------------------------------------------------

DIRECT_COMPOSITION = "DIRECT_COMPOSITION"
SMALL_BINDING = "SMALL_BINDING"
NO_REPRESENTATION = "NO_REPRESENTATION"
BUILD_INVARIANT = "BUILD_INVARIANT"
CONFLICT = "CONFLICT"

IMPLEMENTED = "IMPLEMENTED"
UNIMPLEMENTED = "UNIMPLEMENTED"

PROJECT = "PROJECT"
BUILD = "BUILD"

NOT_BOUND = "NOT_BOUND"
NO_REPRESENTATION_REASON = "NO_REPRESENTATION"
WORDING_CONFLICT = "WORDING_CONFLICT"
SCOPE_MISMATCH = "SCOPE_MISMATCH"
RESOLVER_PENDING = "RESOLVER_PENDING"

#: §6 invariant 12 - the only legal (classification -> unimplemented_reason) pairs while
#: implementation_status is UNIMPLEMENTED. DIRECT_COMPOSITION additionally allows
#: WORDING_CONFLICT, but ONLY for the rows §9 itself names as registry-blocked (checked
#: separately, not by this table alone).
_LEGAL_REASON_FOR_CLASSIFICATION: dict[str, tuple[str, ...]] = {
    DIRECT_COMPOSITION: (RESOLVER_PENDING, WORDING_CONFLICT),
    SMALL_BINDING: (NOT_BOUND,),
    NO_REPRESENTATION: (NO_REPRESENTATION_REASON,),
    BUILD_INVARIANT: (SCOPE_MISMATCH,),
    CONFLICT: (WORDING_CONFLICT,),
}

#: The only DIRECT_COMPOSITION rows whose reason is legally WORDING_CONFLICT rather than
#: RESOLVER_PENDING (§9 rows 13, 18) - named explicitly, never inferred.
_REGISTRY_BLOCKED_DC = frozenset({("P5", "decision_value_is_one_of_build_buy_adopt_fork_integrate"),
                                   ("P8", "adr_records_reason")})


@dataclass(frozen=True)
class ResolverOutcome:
    """§4 - immutable, never a bare tuple."""

    status: str  # PASS | FAIL | ERROR
    detail: str
    semantic_source: str


@dataclass(frozen=True)
class ResolverContext:
    """§4 - the minimum real information a DIRECT_COMPOSITION resolver needs. No caller-
    supplied artifact/evidence ref - a resolver looks up its own relevant record(s) by
    phase_id."""

    project: Path
    phase_id: str


@dataclass(frozen=True)
class RegistryEntry:
    """§2, verbatim."""

    check_name: str
    phase_id: str
    classification: str
    implementation_status: str
    obligation_scope: str
    resolver_id: str | None
    semantic_source: str | None
    planned_resolver_id: str | None
    unimplemented_reason: str | None
    blocked_by: str | None


class RegistryLoadError(Exception):
    """§2.1/§6 - the registry does not load partially. Any invariant violation raises this,
    fail-closed, before any row is usable."""


Resolver = Callable[[ResolverContext, RegistryEntry], ResolverOutcome]


# -- §9 canonical manifest, transcribed verbatim ---------------------------------------------
#
# One entry per declared check. `planned_resolver_id` is populated only for DIRECT_COMPOSITION
# rows (§2, §6 invariant 11); every other classification carries `None` there. This table
# decides nothing new - see this module's own docstring.

MANIFEST: tuple[dict[str, Any], ...] = (
    {"phase_id": "P0", "check_name": "intent_classified_as_research_production_or_experimental",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:PROJECT_INTENT"},
    {"phase_id": "P0", "check_name": "objective_stated_in_one_paragraph_or_less",
     "classification": NO_REPRESENTATION, "obligation_scope": PROJECT},
    {"phase_id": "P1", "check_name": "problem_statement_exists",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:PROBLEM_STATEMENT"},
    {"phase_id": "P1", "check_name": "in_scope_list_nonempty",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:SCOPE"},
    {"phase_id": "P1", "check_name": "out_of_scope_list_exists",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:SCOPE"},
    {"phase_id": "P1", "check_name": "constraints_recorded",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:CONSTRAINTS"},
    {"phase_id": "P2", "check_name": "success_criteria_measurable",
     "classification": NO_REPRESENTATION, "obligation_scope": PROJECT},
    {"phase_id": "P2", "check_name": "failure_criteria_recorded",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:FAILURE_CRITERIA"},
    {"phase_id": "P2", "check_name": "risk_level_set",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:RISK_LEVEL"},
    {"phase_id": "P2", "check_name": "claim_strength_set",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:CLAIM_STRENGTH"},
    {"phase_id": "P3", "check_name": "prior_art_map_has_at_least_one_source_or_explicit_none_found_justification",
     "classification": NO_REPRESENTATION, "obligation_scope": PROJECT},
    {"phase_id": "P4", "check_name": "gap_analysis_references_prior_art_map",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:GAP_ANALYSIS"},
    {"phase_id": "P5", "check_name": "decision_value_is_one_of_build_buy_adopt_fork_integrate",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:STRATEGY_DECISION"},
    {"phase_id": "P5", "check_name": "decision_has_reason",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "artifact_field:P5_STRATEGY_DECISION.reason"},
    {"phase_id": "P6", "check_name": "requirements_have_stable_ids_req_prefix",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT,
     "resolver_id": "artifact_field:P6_REQUIREMENT.requirement_id_prefix"},
    {"phase_id": "P6", "check_name": "critical_requirements_link_acceptance_criterion_and_planned_test",
     "classification": NO_REPRESENTATION, "obligation_scope": PROJECT},
    {"phase_id": "P7", "check_name": "execution_authority_and_acceptance_authority_are_distinct_identities_or_roles",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT,
     "resolver_id": "artifact_field:P7_ARCHITECTURE.disjoint_authorities"},
    {"phase_id": "P8", "check_name": "adr_records_reason",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:ADR"},
    {"phase_id": "P8", "check_name": "cost_model_covers_at_least_one_dimension",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:COST_MODEL"},
    {"phase_id": "P9", "check_name": "governance_defines_acceptance_authority",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT,
     "resolver_id": "artifact_field:P9_GOVERNANCE.authority_assignments.acceptance"},
    {"phase_id": "P9", "check_name": "runtime_structure_initialized",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:RUNTIME_STRUCTURE"},
    {"phase_id": "P10", "check_name": "baseline_recorded",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:BASELINE"},
    {"phase_id": "P10", "check_name": "at_least_one_primary_metric_defined",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:METRICS"},
    {"phase_id": "P11", "check_name": "frozen_gate_exists",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:GOLDEN_GATES"},
    {"phase_id": "P11", "check_name": "test_plan_covers_critical_requirements",
     "classification": NO_REPRESENTATION, "obligation_scope": PROJECT},
    {"phase_id": "P11", "check_name": "stop_conditions_defined",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "artifact_field:P11_GATE_PLAN.stop_conditions"},
    {"phase_id": "P12", "check_name": "task_contract_has_goal_and_scope",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:TASK_CONTRACT"},
    {"phase_id": "P12", "check_name": "task_contract_has_forbidden_scope",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:TASK_CONTRACT"},
    {"phase_id": "P12", "check_name": "task_contract_has_acceptance_criteria",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:TASK_CONTRACT"},
    {"phase_id": "P13", "check_name": "execution_ran_inside_isolated_worktree",
     "classification": BUILD_INVARIANT, "obligation_scope": BUILD},
    {"phase_id": "P13", "check_name": "patch_artifact_recorded",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "lifecycle:transition_history"},
    {"phase_id": "P14", "check_name": "execution_evidence_authority_is_execution",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "lifecycle:transition_history"},
    {"phase_id": "P14", "check_name": "execution_evidence_never_self_marked_authoritative",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT},
    {"phase_id": "P15", "check_name": "verification_ladder_depth_matches_active_profile_risk_and_claim_strength",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT},
    {"phase_id": "P16", "check_name": "deterministic_verification_ran_in_fresh_worktree",
     "classification": BUILD_INVARIANT, "obligation_scope": BUILD},
    {"phase_id": "P16", "check_name": "required_commands_and_forbidden_paths_checked",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT},
    {"phase_id": "P17", "check_name": "result_reproduced_independently_of_original_worktree",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT},
    {"phase_id": "P18", "check_name": "reviewer_identity_distinct_from_executor_identity",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT},
    {"phase_id": "P18", "check_name": "verdict_is_structured_not_narrative",
     "classification": NO_REPRESENTATION, "obligation_scope": PROJECT},
    {"phase_id": "P18", "check_name": "verifier_did_not_write_a_decision",
     "classification": BUILD_INVARIANT, "obligation_scope": BUILD},
    {"phase_id": "P19", "check_name": "release_candidate_commit_matches_verified_commit",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "lifecycle:candidate_binding"},
    {"phase_id": "P19", "check_name": "evidence_bundle_references_verification_evidence",
     "classification": DIRECT_COMPOSITION, "obligation_scope": PROJECT,
     "planned_resolver_id": "required_kind:EVIDENCE_BUNDLE"},
    {"phase_id": "P19", "check_name": "known_limitations_recorded",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT,
     "resolver_id": "lifecycle:release_candidate.known_limitations"},
    {"phase_id": "P20", "check_name": "security_reviewed",
     "classification": NO_REPRESENTATION, "obligation_scope": PROJECT},
    {"phase_id": "P20", "check_name": "rollback_plan_exists",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT},
    {"phase_id": "P20", "check_name": "deployment_decision_recorded",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT},
    {"phase_id": "P21", "check_name": "observation_stream_active",
     "classification": NO_REPRESENTATION, "obligation_scope": PROJECT},
    {"phase_id": "P21", "check_name": "incidents_preserve_evidence_before_repair",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT},
    {"phase_id": "P22", "check_name": "improvement_proposal_cites_evidence",
     "classification": SMALL_BINDING, "obligation_scope": PROJECT},
    {"phase_id": "P23", "check_name": "lifecycle_decision_is_one_of_continue_maintain_start_v2_pivot_freeze_archive_abandon",
     "classification": CONFLICT, "obligation_scope": PROJECT},
)

assert len({(row["phase_id"], row["check_name"]) for row in MANIFEST}) == len(MANIFEST) == 50


def _reason_and_blocked_by(row: dict[str, Any]) -> tuple[str, str | None]:
    """§6 invariants 9 and 12, applied to one manifest row."""
    classification = row["classification"]
    key = (row["phase_id"], row["check_name"])
    if classification == DIRECT_COMPOSITION:
        if key in _REGISTRY_BLOCKED_DC:
            wording_fix = "P5-STRATEGY-WORDING-FIX" if row["phase_id"] == "P5" else "P8-ADR-WORDING-FIX"
            return WORDING_CONFLICT, wording_fix
        return RESOLVER_PENDING, None
    if classification == SMALL_BINDING:
        return NOT_BOUND, None
    if classification == NO_REPRESENTATION:
        return NO_REPRESENTATION_REASON, None
    if classification == BUILD_INVARIANT:
        return SCOPE_MISMATCH, "BUILD-INVARIANT-PRE"
    if classification == CONFLICT:
        return WORDING_CONFLICT, "P23-LIFECYCLE-OUTCOME-PRE"
    raise RegistryLoadError(f"{key}: unknown classification {classification!r}")  # pragma: no cover


#: F3-B1 scope only - resolver_id -> Resolver, for the 21 rows this batch implements. Keyed by
#: the SAME string as `planned_resolver_id` (§6 invariant 11: flipping to IMPLEMENTED binds
#: `resolver_id == planned_resolver_id` exactly, never a new mapping invented at bind time).
RESOLVERS: dict[str, Resolver] = {}


def _register(resolver_id: str) -> Callable[[Resolver], Resolver]:
    def decorator(fn: Resolver) -> Resolver:
        RESOLVERS[resolver_id] = fn
        return fn
    return decorator


def _required_kind_outcome(kind: str, verdict: "rk.Verdict") -> ResolverOutcome:
    """§3.1's translation rule, applied once: the authoritative verdict's own PASS/MISSING/
    WRONG_TYPE/INVALID/STALE/OUT_OF_BOUNDS vocabulary maps straight onto PASS/FAIL - F3 never
    re-classifies it. UNMAPPED/DEFERRED cannot occur here (`kind` is always a real
    ENFORCED_KINDS member, asserted at import time by every factory below)."""
    semantic_source = f"required_kind:{kind}"
    if verdict.status == rk.PASS:
        return ResolverOutcome(PASS, str(verdict), semantic_source)
    return ResolverOutcome(FAIL, str(verdict), semantic_source)


def _make_artifact_required_kind_resolver(kind: str) -> Resolver:
    """ArtifactField/WholeArtifact-shaped ENFORCED_KINDS entries: the ref(s) to feed
    `check_required_kinds` come from `nogap_artifacts.list_artifacts(project, artifact_type,
    phase_id)` - the same phase-scoped selection `prebuild_readiness` already uses, not a new
    one."""
    spec = rk.ENFORCED_KINDS[kind]
    if not isinstance(spec, (rk.ArtifactField, rk.WholeArtifact)):
        raise RegistryLoadError(f"{kind} is not ArtifactField/WholeArtifact-shaped")  # pragma: no cover
    artifact_type = spec.artifact_type

    def resolver(ctx: ResolverContext, entry: RegistryEntry) -> ResolverOutcome:
        records = na.list_artifacts(ctx.project, artifact_type=artifact_type, phase_id=ctx.phase_id)
        refs = [r["artifact_id"] for r in records]
        verdict = rk.check_required_kinds(ctx.project, [kind], refs)[0]
        return _required_kind_outcome(kind, verdict)

    return resolver


for _kind in ("PROJECT_INTENT", "PROBLEM_STATEMENT", "SCOPE", "CONSTRAINTS", "FAILURE_CRITERIA",
              "RISK_LEVEL", "CLAIM_STRENGTH", "GAP_ANALYSIS", "COST_MODEL", "RUNTIME_STRUCTURE",
              "BASELINE", "METRICS", "TASK_CONTRACT"):
    RESOLVERS[f"required_kind:{_kind}"] = _make_artifact_required_kind_resolver(_kind)


@_register("required_kind:GOLDEN_GATES")
def _golden_gates_resolver(ctx: ResolverContext, entry: RegistryEntry) -> ResolverOutcome:
    """GOLDEN_GATES never resolves against artifact_refs at all (its own docstring) - project
    alone is enough, no phase_id-scoped lookup needed."""
    verdict = rk.check_required_kinds(ctx.project, ["GOLDEN_GATES"], [])[0]
    return _required_kind_outcome("GOLDEN_GATES", verdict)


def _make_artifact_field_resolver(resolver_id: str, artifact_type: str, field: str) -> Resolver:
    """artifact_field:<TYPE>.<field> (§4.1's second namespace): composes over
    `nogap_artifacts.check_required_field` (ARTIFACT-FIELD-ATTRIBUTION-PRE) - the public,
    field-scoped surface for exactly the "required and non-empty" rule, on the record
    `list_artifacts(project, artifact_type, phase_id)` resolves.

    NOT `validate_record`: an earlier version of this resolver composed over
    `validate_record`'s WHOLE-RECORD verdict, and mutation testing proved a real, reproducible
    mis-attribution bug - a corrupted UNRELATED field on the same record (e.g.
    P5_STRATEGY_DECISION.selected_strategy while `reason` stayed valid) made this resolver
    report FAIL while blaming a field it never inspected (tests/test_f3b1_exit_check_resolvers.
    py's ArtifactFieldAttributionFinding reproduces the original bug; tests/
    test_artifact_field_attribution.py proves `check_required_field` does not have it).
    `check_required_field` never runs `_check_references` or any artifact_type-specific
    semantic block - structurally, not just by convention - so this class of mis-attribution
    cannot recur here."""

    def resolver(ctx: ResolverContext, entry: RegistryEntry) -> ResolverOutcome:
        records = na.list_artifacts(ctx.project, artifact_type=artifact_type, phase_id=ctx.phase_id)
        if not records:
            return ResolverOutcome(FAIL, f"no {artifact_type} artifact recorded for phase {ctx.phase_id}",
                                    resolver_id)
        problems: list[str] = []
        for record in sorted(records, key=lambda r: str(r.get("artifact_id"))):
            status = record.get("status")
            if status in rk.NON_SATISFYING_STATUSES:
                problems.append(f"{record.get('artifact_id')} is {status}")
                continue
            verdict = na.check_required_field(ctx.project, artifact_type, field, record.get("fields", {}))
            if not verdict.satisfied:
                problems.append(f"{record.get('artifact_id')}: {verdict.detail}")
                continue
            return ResolverOutcome(PASS, f"{record.get('artifact_id')} ({artifact_type}.{field})", resolver_id)
        return ResolverOutcome(FAIL, "; ".join(problems), resolver_id)

    return resolver


RESOLVERS["artifact_field:P5_STRATEGY_DECISION.reason"] = _make_artifact_field_resolver(
    "artifact_field:P5_STRATEGY_DECISION.reason", "P5_STRATEGY_DECISION", "reason")
RESOLVERS["artifact_field:P11_GATE_PLAN.stop_conditions"] = _make_artifact_field_resolver(
    "artifact_field:P11_GATE_PLAN.stop_conditions", "P11_GATE_PLAN", "stop_conditions")


def _current_release_candidate(project: Path):
    from nogap_lifecycle import get_current_release_candidate
    return get_current_release_candidate(project)


@_register("required_kind:EVIDENCE_BUNDLE")
def _evidence_bundle_resolver(ctx: ResolverContext, entry: RegistryEntry) -> ResolverOutcome:
    """The ref EVIDENCE_BUNDLE needs is a release-candidate id. `nogap_lifecycle.
    get_current_release_candidate` is the ALREADY-EXISTING, pure, authoritative "current RC"
    selector (`select_current_release_candidate`, used in production) - reused verbatim, not
    invented for this resolver."""
    semantic_source = "required_kind:EVIDENCE_BUNDLE"
    result = _current_release_candidate(ctx.project)
    status = result["status"]
    if status == "NONE":
        return ResolverOutcome(FAIL, "no FROZEN release candidate exists for this project", semantic_source)
    if status == "CONFLICT":
        return ResolverOutcome(
            FAIL, f"ambiguous current release candidate: {result.get('conflicting_ids')}", semantic_source)
    rc_id = result["candidate"]["release_candidate_id"]
    verdict = rk.check_required_kinds(ctx.project, ["EVIDENCE_BUNDLE"], [rc_id])[0]
    return _required_kind_outcome("EVIDENCE_BUNDLE", verdict)


@_register("lifecycle:candidate_binding")
def _candidate_binding_resolver(ctx: ResolverContext, entry: RegistryEntry) -> ResolverOutcome:
    """Same current-RC selector as EVIDENCE_BUNDLE above, then reuses
    `nogap_lifecycle.resolve_candidate_bindings` (G1-C2's own bulk pair resolver) directly - no
    new binding logic."""
    from nogap_lifecycle import resolve_candidate_bindings
    from nogap_methodology import MethodologyValidationError

    semantic_source = "lifecycle:candidate_binding"
    result = _current_release_candidate(ctx.project)
    status = result["status"]
    if status == "NONE":
        return ResolverOutcome(FAIL, "no FROZEN release candidate exists for this project", semantic_source)
    if status == "CONFLICT":
        return ResolverOutcome(
            FAIL, f"ambiguous current release candidate: {result.get('conflicting_ids')}", semantic_source)
    candidate = result["candidate"]
    bindings = candidate.get("candidate_bindings")
    if not isinstance(bindings, dict) or not bindings:
        return ResolverOutcome(
            FAIL, f"{candidate.get('release_candidate_id')} declares no candidate_bindings", semantic_source)
    try:
        resolve_candidate_bindings(ctx.project, bindings)
    except MethodologyValidationError as exc:
        return ResolverOutcome(FAIL, str(exc), semantic_source)
    return ResolverOutcome(
        PASS, f"{candidate.get('release_candidate_id')} candidate_bindings all resolve", semantic_source)


# -- F3-D1: 4 SMALL_BINDING rows (P6, P7, P9, P19) - each a small, newly-designed predicate ---
#
# Unlike F3-B's DIRECT_COMPOSITION rows, no pre-existing required_kind/authoritative check does
# this work already - each predicate below is new, but built ONLY from real, already-declared
# fields (never a new stored field, never invented semantics), exactly what SMALL_BINDING means
# (F3-D-PRE, ACCEPTED WITH REPAIR).


def _valid_records_for_phase(project: Path, artifact_type: str, phase_id: str) -> list[dict[str, Any]]:
    """The same list_artifacts(phase_id=...) + validate_record + NON_SATISFYING_STATUSES
    filter every other artifact-scoped resolver in this module already uses - never a new
    selection rule, just the shared shape."""
    records = na.list_artifacts(project, artifact_type=artifact_type, phase_id=phase_id)
    valid = []
    for record in sorted(records, key=lambda r: str(r.get("artifact_id"))):
        if record.get("status") in rk.NON_SATISFYING_STATUSES:
            continue
        if na.validate_record(project, record):
            continue
        valid.append(record)
    return valid


@_register("artifact_field:P6_REQUIREMENT.requirement_id_prefix")
def _requirement_stable_id_prefix_resolver(ctx: ResolverContext, entry: RegistryEntry) -> ResolverOutcome:
    """Every P6_REQUIREMENT under this phase must carry a requirement_id in the exact
    "REQ-NNN" shape nogap_artifacts._next_stable_id assigns at creation
    (_STABLE_ID_FIELDS["P6_REQUIREMENT"] = ("requirement_id", "REQ")) - re-checked here, at
    read time, never assumed from the creation-time guarantee alone (F3-D-PRE row 1)."""
    semantic_source = "artifact_field:P6_REQUIREMENT.requirement_id_prefix"
    records = _valid_records_for_phase(ctx.project, "P6_REQUIREMENT", ctx.phase_id)
    if not records:
        return ResolverOutcome(FAIL, "no valid P6_REQUIREMENT recorded for this phase", semantic_source)
    bad = [r["fields"]["requirement_id"] for r in records
           if not str(r["fields"].get("requirement_id", "")).startswith("REQ-")]
    if bad:
        return ResolverOutcome(FAIL, f"requirement_id(s) not in REQ-NNN form: {bad}", semantic_source)
    return ResolverOutcome(PASS, f"{len(records)} requirement(s), all REQ-NNN", semantic_source)


@_register("artifact_field:P7_ARCHITECTURE.disjoint_authorities")
def _architecture_authority_disjointness_resolver(ctx: ResolverContext, entry: RegistryEntry) -> ResolverOutcome:
    """P7_ARCHITECTURE.execution_authorities and .acceptance_authorities are both real,
    required fields (validate_record already enforces non-empty presence); this checks the
    ONE thing no existing check covers - that the two sets share no identity/role
    (F3-D-PRE row 2)."""
    semantic_source = "artifact_field:P7_ARCHITECTURE.disjoint_authorities"
    records = _valid_records_for_phase(ctx.project, "P7_ARCHITECTURE", ctx.phase_id)
    if not records:
        return ResolverOutcome(FAIL, "no valid P7_ARCHITECTURE recorded for this phase", semantic_source)
    problems: list[str] = []
    for record in records:
        execution = set(record["fields"].get("execution_authorities") or [])
        acceptance = set(record["fields"].get("acceptance_authorities") or [])
        overlap = execution & acceptance
        if overlap:
            problems.append(f"{record['artifact_id']}: shared authority/role(s) {sorted(overlap)}")
            continue
        return ResolverOutcome(PASS, f"{record['artifact_id']}: execution/acceptance authorities disjoint",
                                semantic_source)
    return ResolverOutcome(FAIL, "; ".join(problems), semantic_source)


@_register("artifact_field:P9_GOVERNANCE.authority_assignments.acceptance")
def _governance_acceptance_authority_resolver(ctx: ResolverContext, entry: RegistryEntry) -> ResolverOutcome:
    """P9_GOVERNANCE.authority_assignments is a real, required dict field; this checks that
    its "acceptance" key is present with a real, non-empty value - never merely that the key
    exists (F3-D-PRE row 3, empty-value negative case required)."""
    semantic_source = "artifact_field:P9_GOVERNANCE.authority_assignments.acceptance"
    records = _valid_records_for_phase(ctx.project, "P9_GOVERNANCE", ctx.phase_id)
    if not records:
        return ResolverOutcome(FAIL, "no valid P9_GOVERNANCE recorded for this phase", semantic_source)
    problems: list[str] = []
    for record in records:
        assignments = record["fields"].get("authority_assignments")
        value = assignments.get("acceptance") if isinstance(assignments, dict) else None
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"{record['artifact_id']}: authority_assignments carries no 'acceptance' entry")
            continue
        return ResolverOutcome(PASS, f"{record['artifact_id']}: acceptance authority = {value!r}", semantic_source)
    return ResolverOutcome(FAIL, "; ".join(problems), semantic_source)


@_register("lifecycle:release_candidate.known_limitations")
def _release_candidate_known_limitations_resolver(ctx: ResolverContext, entry: RegistryEntry) -> ResolverOutcome:
    """The current release candidate's own known_limitations field, non-empty - reuses
    get_current_release_candidate() exactly as EVIDENCE_BUNDLE/candidate_binding already do
    (F3-B1), never a new RC selector (F3-D-PRE row 9)."""
    semantic_source = "lifecycle:release_candidate.known_limitations"
    result = _current_release_candidate(ctx.project)
    status = result["status"]
    if status == "NONE":
        return ResolverOutcome(FAIL, "no FROZEN release candidate exists for this project", semantic_source)
    if status == "CONFLICT":
        return ResolverOutcome(
            FAIL, f"ambiguous current release candidate: {result.get('conflicting_ids')}", semantic_source)
    candidate = result["candidate"]
    limitations = candidate.get("known_limitations")
    if not limitations:
        return ResolverOutcome(
            FAIL, f"{candidate.get('release_candidate_id')} declares no known_limitations", semantic_source)
    return ResolverOutcome(
        PASS, f"{candidate.get('release_candidate_id')} known_limitations: {limitations!r}", semantic_source)


# -- F3-B2: P13/P14, lifecycle:transition_history (§4.4.1's frozen lineage rule) -------------


def _current_p13_attempt_binding(project: Path) -> dict[str, Any] | None:
    """§4.4.1, verbatim: scan `transition_history` in append order, tracking only two event
    kinds - `to_phase == "P13"` (a fresh attempt begins, forward or repair LOOP_RETURN alike)
    and `from_phase == "P13" and to_phase == "P14"` (the ONLY function that ever writes this,
    `nogap_build.enter_self_check_phase`). The LAST occurrence of either kind decides: a
    close-of-P13 is the current, authoritative binding for both P13's and P14's checks; an
    entry-into-P13 with no close since means no valid binding exists yet. One shared lookup -
    P13's and P14's resolvers both call this, never scanning independently."""
    from nogap_methodology import load_state

    state = load_state(project)
    if state is None:
        return None
    last_kind: str | None = None
    last_record: dict[str, Any] | None = None
    for record in state.get("transition_history", []):
        if record.get("to_phase") == "P13":
            last_kind, last_record = "entry", record
        elif record.get("from_phase") == "P13" and record.get("to_phase") == "P14":
            last_kind, last_record = "close", record
    return last_record if last_kind == "close" else None


_NO_CURRENT_BINDING_DETAIL = (
    "no current P13-attempt binding: either no P13→P14 transition has ever occurred, or "
    "the project re-entered P13 (repair) and has not closed it again"
)


@_register("lifecycle:transition_history")
def _transition_history_resolver(ctx: ResolverContext, entry: RegistryEntry) -> ResolverOutcome:
    """P13 `patch_artifact_recorded` and P14 `execution_evidence_authority_is_execution` share
    this ONE resolver_id (§4.4.1: both read the SAME transition record) - so this is one
    function, dispatching on `entry.phase_id`, not two independently-registered resolvers under
    a colliding key. One shared lookup (`_current_p13_attempt_binding`) either way; P13 reads
    the binding's `artifact_refs` and feeds `required_kind:PATCH`'s own authoritative check
    (`_check_file_kind`); P14 reads its `evidence_refs` and feeds `required_kind:
    EXECUTION_EVIDENCE`'s own authoritative check (`_check_evidence_kind`,
    `authorities=('execution',)`). Neither reimplements PATCH/authority semantics - both defer
    entirely to `nogap_required_kinds.check_required_kinds`."""
    semantic_source = "lifecycle:transition_history"
    binding = _current_p13_attempt_binding(ctx.project)
    if binding is None:
        return ResolverOutcome(FAIL, _NO_CURRENT_BINDING_DETAIL, semantic_source)

    if entry.phase_id == "P13":
        refs = list(binding.get("artifact_refs") or [])
        verdict = rk.check_required_kinds(ctx.project, ["PATCH"], refs)[0]
        outcome = _required_kind_outcome("PATCH", verdict)
    elif entry.phase_id == "P14":
        refs = list(binding.get("evidence_refs") or [])
        verdict = rk.check_required_kinds(ctx.project, ["EXECUTION_EVIDENCE"], refs)[0]
        outcome = _required_kind_outcome("EXECUTION_EVIDENCE", verdict)
    else:  # pragma: no cover - only P13/P14 rows carry this resolver_id (registry-load invariant 11)
        return ResolverOutcome(ERROR, f"lifecycle:transition_history has no binding for phase {entry.phase_id!r}",
                                semantic_source)

    return ResolverOutcome(outcome.status, outcome.detail, semantic_source)


# -- registry loader (§6) ---------------------------------------------------------------------


def _declared_exit_checks(methodology_dir: Path | None = None) -> set[tuple[str, str]]:
    """Every (phase_id, check_name) any phase contract declares - mirrors
    `nogap_required_kinds.declared_required_kinds`'s own pattern exactly."""
    import json

    from nogap_methodology import METHODOLOGY_DIR

    directory = Path(methodology_dir) if methodology_dir else METHODOLOGY_DIR
    declared: set[tuple[str, str]] = set()
    for path in sorted((directory / "phases").glob("p*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        phase_id = data["id"]
        for check_name in data["exit_gate"]["checks"]:
            declared.add((phase_id, check_name))
    return declared


def load_registry(methodology_dir: Path | None = None) -> dict[tuple[str, str], RegistryEntry]:
    """§6: fail-closed, all-or-nothing. Raises RegistryLoadError on any invariant violation
    rather than loading a partial or inconsistent registry."""
    declared = _declared_exit_checks(methodology_dir)
    manifest_keys = {(row["phase_id"], row["check_name"]) for row in MANIFEST}

    # invariants 1-4: exact bijection
    unknown = declared - manifest_keys
    if unknown:
        raise RegistryLoadError(f"declared checks with no registry row: {sorted(unknown)}")
    orphans = manifest_keys - declared
    if orphans:
        raise RegistryLoadError(f"registry rows with no declared check: {sorted(orphans)}")

    entries: dict[tuple[str, str], RegistryEntry] = {}
    for row in MANIFEST:
        key = (row["phase_id"], row["check_name"])
        classification = row["classification"]
        obligation_scope = row["obligation_scope"]
        planned_resolver_id = row.get("planned_resolver_id")
        # SMALL_BINDING's own manifest key for a resolver F3-D has designed and bound for this
        # specific row (§6 invariant 12, REPAIR). Deliberately NOT "planned_resolver_id" and
        # NOT a separate concept/field name either - it is literally this row's real
        # resolver_id, the same name RegistryEntry itself uses, because unlike DIRECT_
        # COMPOSITION (whose mechanism is known at F3-A freeze, so planned_resolver_id names
        # it ahead of the binding), a SMALL_BINDING row's predicate does not exist until F3-D
        # designs it - there is no earlier "planned" state to distinguish from the final one.
        manifest_resolver_id = row.get("resolver_id")

        # invariant 11: planned_resolver_id is DIRECT_COMPOSITION-only, always - required for
        # every DC row, forbidden for every other classification INCLUDING SMALL_BINDING, at
        # every point in a SMALL_BINDING row's life (never set retroactively once F3-D
        # implements one either).
        if classification == DIRECT_COMPOSITION and not planned_resolver_id:
            raise RegistryLoadError(f"{key}: DIRECT_COMPOSITION row with no planned_resolver_id")
        if classification != DIRECT_COMPOSITION and planned_resolver_id:
            raise RegistryLoadError(f"{key}: non-DIRECT_COMPOSITION row carries a planned_resolver_id")

        # invariant 12 (REPAIR, F3-A/F3-D micro-repair): the MANIFEST "resolver_id" key is
        # legal only on SMALL_BINDING rows (and only once F3-D has actually bound one for it -
        # enforced below via RESOLVERS membership, not just presence in MANIFEST).
        if classification != SMALL_BINDING and manifest_resolver_id:
            raise RegistryLoadError(f"{key}: {classification} row must not carry a resolver_id in MANIFEST")

        # invariant 10: obligation_scope BUILD <-> SCOPE_MISMATCH
        if obligation_scope == BUILD and classification != BUILD_INVARIANT:
            raise RegistryLoadError(f"{key}: obligation_scope BUILD requires classification BUILD_INVARIANT")

        reason, blocked_by = _reason_and_blocked_by(row)

        # invariant 13: classification/reason matrix
        legal = _LEGAL_REASON_FOR_CLASSIFICATION[classification]
        if reason not in legal:
            raise RegistryLoadError(f"{key}: reason {reason!r} illegal for classification {classification!r}")
        if classification == DIRECT_COMPOSITION and reason == WORDING_CONFLICT and key not in _REGISTRY_BLOCKED_DC:
            raise RegistryLoadError(f"{key}: WORDING_CONFLICT on a DIRECT_COMPOSITION row not named registry-blocked")

        # invariant 9: reason/blocked_by direction
        if reason in (WORDING_CONFLICT, SCOPE_MISMATCH) and not blocked_by:
            raise RegistryLoadError(f"{key}: {reason} requires blocked_by")
        if reason in (NOT_BOUND, NO_REPRESENTATION_REASON, RESOLVER_PENDING) and blocked_by:
            raise RegistryLoadError(f"{key}: {reason} must not carry blocked_by")

        resolver_id: str | None = None
        semantic_source: str | None = None
        implementation_status = UNIMPLEMENTED

        # Flip a row to IMPLEMENTED along exactly one of two SEPARATE paths, never conflated:
        #   DC path (F3-B): classification DIRECT_COMPOSITION, reason RESOLVER_PENDING (never
        #     WORDING_CONFLICT - P5/P8 stay UNIMPLEMENTED regardless of RESOLVERS), binds
        #     against planned_resolver_id (the mechanism already known at F3-A freeze).
        #   SB path (F3-D): classification SMALL_BINDING, reason NOT_BOUND, binds directly
        #     against the row's own MANIFEST resolver_id (a predicate F3-D designed fresh for
        #     this row - no "planned" precursor state). A row with no resolver bound (every
        #     SMALL_BINDING row not yet reached by an authorized F3-D batch) simply stays
        #     UNIMPLEMENTED - §6 invariant 5.
        binding_id: str | None = None
        if classification == DIRECT_COMPOSITION and reason == RESOLVER_PENDING:
            binding_id = planned_resolver_id
        elif classification == SMALL_BINDING and reason == NOT_BOUND and manifest_resolver_id:
            binding_id = manifest_resolver_id
            # fail-closed (REPAIR): a MANIFEST resolver_id on a SMALL_BINDING row is F3-D
            # declaring this row bound and implemented - unlike DC's planned_resolver_id
            # (which may legitimately predate F3-B ever building the adapter), there is no
            # earlier "planned" state for SB to fall back to. A missing RESOLVERS symbol here
            # is a runtime fault, never a silent regression to UNIMPLEMENTED/NOT_BOUND.
            if RESOLVERS.get(binding_id) is None:
                raise RegistryLoadError(
                    f"{key}: SMALL_BINDING row declares resolver_id {binding_id!r} in MANIFEST "
                    "but no such resolver is registered"
                )

        if binding_id is not None and RESOLVERS.get(binding_id) is not None:
            resolver_id = binding_id
            semantic_source = binding_id  # invariant 8: identical namespace string
            implementation_status = IMPLEMENTED
            reason = None
            blocked_by = None

        if implementation_status == UNIMPLEMENTED and (resolver_id is not None or semantic_source is not None):
            raise RegistryLoadError(f"{key}: UNIMPLEMENTED row must have null resolver_id/semantic_source")  # pragma: no cover
        if implementation_status == IMPLEMENTED and (resolver_id is None or semantic_source is None):
            raise RegistryLoadError(f"{key}: IMPLEMENTED row must have non-null resolver_id/semantic_source")  # pragma: no cover
        if implementation_status == IMPLEMENTED and resolver_id != binding_id:
            raise RegistryLoadError(f"{key}: resolver_id must equal its binding source when IMPLEMENTED")  # pragma: no cover
        if classification == SMALL_BINDING and planned_resolver_id is not None:
            raise RegistryLoadError(f"{key}: SMALL_BINDING row must never carry a planned_resolver_id")  # pragma: no cover

        entries[key] = RegistryEntry(
            check_name=row["check_name"], phase_id=row["phase_id"], classification=classification,
            implementation_status=implementation_status, obligation_scope=obligation_scope,
            resolver_id=resolver_id, semantic_source=semantic_source,
            planned_resolver_id=planned_resolver_id,
            unimplemented_reason=(reason if implementation_status == UNIMPLEMENTED else None),
            blocked_by=(blocked_by if implementation_status == UNIMPLEMENTED else None),
        )

    # invariant 3: no duplicate row (MANIFEST -> dict keyed by (phase_id, check_name) already
    # collapses duplicates; the assertion at import time on MANIFEST's own length is the real
    # guard, checked again here defensively)
    if len(entries) != len(MANIFEST):
        raise RegistryLoadError("duplicate (phase_id, check_name) row in MANIFEST")  # pragma: no cover

    return entries


def resolve(entry: RegistryEntry, ctx: ResolverContext) -> ResolverOutcome:
    """Invoke an IMPLEMENTED row's resolver, wrapped exactly as §4.2 requires: any exception is
    caught and converted to ERROR, never propagated. Not called `evaluate_exit_gate` - that is
    F3-C's own deliverable, not built here."""
    if entry.implementation_status != IMPLEMENTED:
        raise ValueError(f"{entry.phase_id}/{entry.check_name} is not IMPLEMENTED")  # pragma: no cover
    resolver = RESOLVERS.get(entry.resolver_id)
    if resolver is None:  # pragma: no cover - invariant 5 already prevents this
        return ResolverOutcome(ERROR, f"resolver_id {entry.resolver_id!r} does not resolve to a bound resolver",
                                entry.semantic_source or "")
    try:
        outcome = resolver(ctx, entry)
    except Exception as exc:  # noqa: BLE001 - §4.2: any exception becomes ERROR, never propagates
        return ResolverOutcome(ERROR, f"{type(exc).__name__}: {exc}", entry.semantic_source or "")
    if outcome.semantic_source != entry.semantic_source:  # §3.2
        return ResolverOutcome(ERROR, f"semantic_source mismatch: resolver reported "
                                       f"{outcome.semantic_source!r}, registry row is {entry.semantic_source!r}",
                                entry.semantic_source or "")
    return outcome


# -- F3-C: report-only evaluator ---------------------------------------------------------------
#
# `evaluate_exit_gate` is read-only and self-contained: it never mutates project state, never
# writes an evidence/artifact/decision record, and is never called from `_evaluate_transition`
# (nogap_methodology.py) - nothing here blocks anything. It only PRODUCES, for the first time,
# real PASS/FAIL/ERROR/UNIMPLEMENTED results for a phase's declared exit_gate.checks - it does
# not decide what any of that means for a transition (F3-F's own, later, deliberately separate
# question).

UNIMPLEMENTED_RESULT = "UNIMPLEMENTED"  # §3 - the fourth ExitCheckResult.status value
REGISTRY_VERSION_SENTINEL = "unversioned"  # §3 - fixed until F3-F assigns real versions/digests


@dataclass(frozen=True)
class ExitCheckResult:
    """§3, verbatim."""

    phase_id: str
    check_name: str
    status: str  # PASS | FAIL | ERROR | UNIMPLEMENTED
    detail: str
    semantic_source: str | None


@dataclass(frozen=True)
class ExitGateEvaluation:
    """§3, verbatim. `all_implemented`/`all_passed` are computed in `evaluate_exit_gate` at
    construction time - never stored as an independently-settable field, so they can never
    disagree with `results` itself (§3's own REPAIR note)."""

    phase_id: str
    results: tuple[ExitCheckResult, ...]
    all_implemented: bool
    all_passed: bool
    registry_version: str


def _declared_checks_for_phase(phase_id: str, methodology_dir: Path | None = None) -> list[str]:
    """The one phase's own `exit_gate.checks`, in DECLARED ORDER - never a registry dict's
    iteration order, never sorted. Mirrors `_declared_exit_checks`'s own file-reading shape,
    scoped to a single phase."""
    import json

    from nogap_methodology import METHODOLOGY_DIR

    directory = Path(methodology_dir) if methodology_dir else METHODOLOGY_DIR
    for path in sorted((directory / "phases").glob("p*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["id"] == phase_id:
            return list(data["exit_gate"]["checks"])
    raise ValueError(f"unknown phase_id: {phase_id!r}")  # fail closed on a bad phase id


def _unimplemented_detail(entry: RegistryEntry) -> str:
    detail = f"UNIMPLEMENTED: {entry.unimplemented_reason}"
    if entry.blocked_by:
        detail += f" (blocked_by: {entry.blocked_by})"
    return detail


def evaluate_exit_gate(project: Path, phase_id: str,
                       methodology_dir: Path | None = None) -> ExitGateEvaluation:
    """§7 item 2's own deliverable, verbatim signature. Loads the registry (fail-closed, §6),
    resolves every declared check for `phase_id` in its declared order, and returns one
    immutable `ExitGateEvaluation` - PASS/FAIL/ERROR for every IMPLEMENTED row (via `resolve`,
    §4.2's exception/mismatch handling included), UNIMPLEMENTED for every row that is not.
    Never raises for an ordinary UNIMPLEMENTED row - only `load_registry`'s own fail-closed
    invariants, or an unknown `phase_id`, can raise here."""
    registry = load_registry(methodology_dir)
    ctx = ResolverContext(project=project, phase_id=phase_id)

    results: list[ExitCheckResult] = []
    for check_name in _declared_checks_for_phase(phase_id, methodology_dir):
        entry = registry[(phase_id, check_name)]
        if entry.implementation_status == IMPLEMENTED:
            outcome = resolve(entry, ctx)
            results.append(ExitCheckResult(
                phase_id=phase_id, check_name=check_name, status=outcome.status,
                detail=outcome.detail, semantic_source=outcome.semantic_source))
        else:
            results.append(ExitCheckResult(
                phase_id=phase_id, check_name=check_name, status=UNIMPLEMENTED_RESULT,
                detail=_unimplemented_detail(entry), semantic_source=entry.semantic_source))

    results_tuple = tuple(results)
    return ExitGateEvaluation(
        phase_id=phase_id,
        results=results_tuple,
        all_implemented=all(r.status != UNIMPLEMENTED_RESULT for r in results_tuple),
        all_passed=all(r.status == PASS for r in results_tuple),
        registry_version=REGISTRY_VERSION_SENTINEL,
    )
