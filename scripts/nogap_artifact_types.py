#!/usr/bin/env python3
"""Shared artifact-type metadata: pure data, no imports from this codebase.

`ARTIFACT_TYPES` (and its derived `PHASE_TO_ARTIFACT_TYPE`) is the declaration both
nogap_artifacts.py (the artifact registry: creation, validation, storage) and
nogap_methodology.py (phase contracts, including artifact_field_bindings validation) need to
read. nogap_artifacts.py already imports FROM nogap_methodology at its own module level, so
either of those two modules importing this data back from the other would be circular.
Putting the data here, in a module that depends on neither, removes the cycle entirely - at
import time and at runtime - rather than routing around it with a deferred import. Both
modules import `ARTIFACT_TYPES` from here; nogap_artifacts.py re-exports it under its own name
so every existing `nogap_artifacts.ARTIFACT_TYPES` call site keeps working unchanged.
"""

from __future__ import annotations

from typing import Any

ARTIFACT_TYPES: dict[str, dict[str, Any]] = {
    "P0_PROJECT_INTENT": {
        "phase_id": "P0",
        "required_fields": ["project_name", "intent_type", "problem_summary", "target_users_or_context", "desired_outcome", "owner", "initial_constraints"],
        "profile_required_fields": {},
        "reference_fields": {},
    },
    "P1_SCOPE": {
        "phase_id": "P1",
        "required_fields": ["problem_statement", "in_scope", "out_of_scope", "constraints", "dependencies", "known_assumptions"],
        "profile_required_fields": {},
        "reference_fields": {},
    },
    "P2_SUCCESS_CRITERIA": {
        "phase_id": "P2",
        "required_fields": ["success_criteria", "failure_criteria", "risk_level", "claim_strength", "critical_claims", "stop_conditions"],
        "profile_required_fields": {},
        "reference_fields": {},
    },
    "P3_PRIOR_ART": {
        "phase_id": "P3",
        "required_fields": ["research_question", "search_scope", "sources", "candidate_solutions", "key_findings", "limitations"],
        "profile_required_fields": {},
        "reference_fields": {},
    },
    "P4_GAP_ANALYSIS": {
        "phase_id": "P4",
        "required_fields": ["requirements_or_needs", "existing_solutions", "covered_capabilities", "missing_capabilities", "tradeoffs", "gaps", "prior_art_refs"],
        "profile_required_fields": {},
        "reference_fields": {"prior_art_refs": "P3_PRIOR_ART"},
    },
    "P5_STRATEGY_DECISION": {
        "phase_id": "P5",
        "required_fields": ["selected_strategy", "alternatives_considered", "reason", "cost", "risk", "gap_analysis_refs"],
        "profile_required_fields": {},
        "reference_fields": {"gap_analysis_refs": "P4_GAP_ANALYSIS"},
    },
    "P6_REQUIREMENT": {
        "phase_id": "P6",
        "required_fields": ["requirement_id", "type", "statement", "priority", "acceptance_criteria", "strategy_decision_refs"],
        "profile_required_fields": {},
        "reference_fields": {"strategy_decision_refs": "P5_STRATEGY_DECISION"},
    },
    "P7_ARCHITECTURE": {
        "phase_id": "P7",
        "required_fields": ["components", "trust_boundaries", "execution_authorities", "acceptance_authorities", "requirement_refs"],
        "profile_required_fields": {
            "STANDARD": ["responsibilities", "interfaces", "external_dependencies"],
            "STRICT": ["failure_domains", "data_security_boundaries"],
        },
        "reference_fields": {"requirement_refs": "P6_REQUIREMENT_ID"},
    },
    "P8_ADR": {
        "phase_id": "P8",
        "required_fields": ["decision", "context", "alternatives", "selected_option", "rationale", "consequences", "expected_cost", "architecture_refs"],
        "profile_required_fields": {
            "STRICT": ["vendor_lock_in"],
        },
        "reference_fields": {"architecture_refs": "P7_ARCHITECTURE"},
    },
    "P9_GOVERNANCE": {
        "phase_id": "P9",
        "required_fields": ["roles", "authority_assignments", "execution_backend_policy", "verification_policy", "human_approval_requirements", "adr_refs"],
        "profile_required_fields": {},
        "reference_fields": {"adr_refs": "P8_ADR"},
    },
    "P10_BASELINE": {
        "phase_id": "P10",
        "required_fields": ["baseline_description", "primary_metric", "secondary_metrics", "measurement_procedure"],
        # F2b METRICS (Rev 2.1 sec 2.5): secondary_metrics MUST exist but MAY be empty - "a
        # baseline with one measure is legitimate". primary_metric has no such exception.
        "allow_empty_fields": frozenset({"secondary_metrics"}),
        "profile_required_fields": {},
        "reference_fields": {},
    },
    "P11_GATE_PLAN": {
        "phase_id": "P11",
        "required_fields": ["gate_id", "required_tests", "evidence_requirements", "stop_conditions", "verification_depth", "requirement_refs", "required_commands", "forbidden_paths"],
        "profile_required_fields": {},
        "reference_fields": {"requirement_refs": "P6_REQUIREMENT_ID"},
    },
    # M7-F: BUILD phases. requirement_refs/gate_plan_refs are deliberately absent from
    # required_fields (only present in reference_fields) - "TaskContract must reference real
    # active P6 requirements *where applicable*": a task can legitimately reference zero
    # requirements or zero gate plans, but any reference it does supply must resolve.
    "P12_TASK_CONTRACT": {
        "phase_id": "P12",
        "required_fields": ["task_id", "goal", "scope", "forbidden_scope", "acceptance_criteria", "planned_tests", "required_evidence", "stop_conditions"],
        "profile_required_fields": {},
        "reference_fields": {"requirement_refs": "P6_REQUIREMENT_ID", "gate_plan_refs": "P11_GATE_PLAN"},
    },
    "P14_SELF_CHECK": {
        "phase_id": "P14",
        "required_fields": ["task_id", "execution_evidence_ids", "changed_files", "patch_hash", "process_outcome", "expected_effect_result"],
        "profile_required_fields": {},
        "reference_fields": {},
    },
    # M7-G: VERIFY phases. task_id/verification_plan_id are scalar references (not lists),
    # so - like P14_SELF_CHECK's task_id - they get a dedicated validate_record special
    # case instead of living in reference_fields (which always expects a list).
    "P15_VERIFICATION_PLAN": {
        # requirement_refs and required_commands are deliberately NOT required, mirroring
        # P12_TASK_CONTRACT's "where applicable" precedent: a task with zero requirement
        # refs or a gate with zero required_commands must still be verifiable, but any
        # requirement_refs given must resolve.
        "phase_id": "P15",
        "required_fields": [
            "verification_plan_id", "task_id", "profile", "risk", "claim_strength",
            "required_levels", "required_validation_levels", "required_evidence_kinds",
            "independent_review_required", "reproducibility_required", "external_validation_required",
        ],
        "profile_required_fields": {},
        "reference_fields": {"requirement_refs": "P6_REQUIREMENT_ID"},
    },
    "P18_VERIFICATION_RESULT": {
        # `status` (VERIFICATION_PENDING/IN_PROGRESS/FAILED/INCONCLUSIVE/COMPLETE_AWAITING_
        # DECISION) lives on the common envelope's `status` field, not in `fields` - the same
        # convention P6_REQUIREMENT uses for its own lifecycle status.
        # levels_passed is deliberately NOT required-non-empty: a failed deterministic
        # layer legitimately passes zero levels, and that must be representable, not
        # rejected as "missing".
        "phase_id": "P18",
        "required_fields": [
            "verification_run_id", "verification_plan_id", "task_id", "candidate_hash", "patch_hash",
            "gate_hash", "methodology_version_at_verification", "profile_at_verification", "task_snapshot_hash",
            "executor_actor_id", "levels_attempted",
            "deterministic_result", "reproducibility_result", "independent_review_result",
            "independent_review_performed",
        ],
        "profile_required_fields": {},
        "reference_fields": {"requirement_refs": "P6_REQUIREMENT_ID"},
    },
}

def _validate_allow_empty_fields() -> None:
    """Fail-closed at import time: allow_empty_fields is an exception to a NAMED required
    field's non-empty rule, never a free-standing declaration. A typo'd or stale name here
    would silently do nothing at validation time (the field it meant to loosen stays
    strictly required, and the name it actually spells matches no real field) - which is
    exactly the kind of quiet no-op this whole methodology's fail-closed discipline exists
    to rule out, so it is caught here instead, the moment the module loads."""
    from nogap_errors import MethodologyValidationError

    for artifact_type, info in ARTIFACT_TYPES.items():
        allow_empty = info.get("allow_empty_fields", frozenset())
        unknown = allow_empty - set(info["required_fields"])
        if unknown:
            raise MethodologyValidationError(
                f"{artifact_type}: allow_empty_fields names {sorted(unknown)}, which "
                f"{'is' if len(unknown) == 1 else 'are'} not in required_fields"
            )


_validate_allow_empty_fields()

# D6-PRE-A: a phase_id can own more than one artifact type (P9 -> GOVERNANCE, RUNTIME_STRUCTURE,
# MEMORY_CONFIGURATION are three independent representations, not three fields of one artifact -
# see docs/d6-runtime-structure-contract.md). PHASE_TO_ARTIFACT_TYPES is the real 1:N ownership
# map; order matches ARTIFACT_TYPES' own declaration order, deterministically.
PHASE_TO_ARTIFACT_TYPES: dict[str, tuple[str, ...]] = {}
for _name, _info in ARTIFACT_TYPES.items():
    PHASE_TO_ARTIFACT_TYPES.setdefault(_info["phase_id"], ())
    PHASE_TO_ARTIFACT_TYPES[_info["phase_id"]] += (_name,)
del _name, _info

# Legacy compatibility map, single-owner phases ONLY. A phase with more than one artifact type
# is deliberately ABSENT here - not resolved to a "first" or "last" type - so any old call site
# still indexing this map on a multi-owner phase_id fails closed with a plain KeyError instead of
# silently picking a winner by insertion order.
PHASE_TO_ARTIFACT_TYPE: dict[str, str] = {
    phase_id: types[0] for phase_id, types in PHASE_TO_ARTIFACT_TYPES.items() if len(types) == 1
}
