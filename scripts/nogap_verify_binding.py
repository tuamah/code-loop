#!/usr/bin/env python3
"""M7-G: binds the existing M6-D independent verification pipeline to methodology
VERIFY phases (P15-P18), the same way nogap_build.py (M7-F) bound M6 execution to
BUILD phases (P12-P14).

Boundaries, kept strict:
- MethodologyEngine (this module + nogap_methodology.py/nogap_artifacts.py) decides
  "what verification depth is required?" - it never runs a check or judges a patch.
- M6-D (nogap_verification.py: run_deterministic_layer, run_independent_review_layer)
  decides "what verification actually happened?" - untouched by this milestone.
- The Trust Runtime evidence ledger decides "what facts were observed?" - this module
  never writes evidence itself; `cmd_verify` (nogap.py) does that, calling
  write_isolated_run_evidence exactly as it already did before this milestone, now
  with the same methodology-tagging kwargs M7-F added. This mirrors nogap_build.py's
  own layering: pure logic here, evidence-writing orchestration in nogap.py.
- Nothing here ever produces or writes authority="acceptance", and nothing here ever
  decides ACCEPT. `nogap decide` remains the sole acceptance authority (M8 territory
  for its actual DecisionEngine redesign) - the one narrow exception is
  verification_acceptance_precondition() below (added post-M7-G to close a
  live-discovered false-pass path): it is consulted by cmd_decide as a NECESSARY,
  never sufficient, gate - "methodology verification isn't ready" can block ACCEPT,
  but "methodology verification is ready" never by itself grants it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from nogap_artifacts import list_artifacts
from nogap_build import _frozen_gate, load_task_contract  # reused, not duplicated
from nogap_methodology import (
    MethodologyValidationError,
    _effective_profile_for_phase,
    _is_skippable,
    _require_state,
    load_methodology,
    load_state,
)

# The canonical 9-rung ladder from the brief, and the 3-level validation model - both
# represented explicitly as vocabularies, not implied by strings scattered through code.
LADDER_LEVELS = [
    "STATIC_CHECKS", "UNIT_TESTS", "INTEGRATION_TESTS", "E2E_TESTS", "LOCAL_VALIDATION",
    "CLEAN_ENV_VALIDATION", "EXTERNAL_VALIDATION", "REGRESSION", "INDEPENDENT_REVIEW",
]
VALIDATION_LEVELS = ["LEVEL_1_CONTROLLED", "LEVEL_2_REPRESENTATIVE", "LEVEL_3_DIFFICULT"]

VERIFY_PHASES = ("P15", "P16", "P17", "P18")
# `nogap verify` (BUILD_COMPLETE_AWAITING_VERIFICATION -> VERIFY) may begin from P14
# (the first candidate to reach verification) or resume from any VERIFY phase already
# entered - never from P0-P13 (nothing to verify yet) or P19+ (out of this milestone's
# scope; RELEASE is untouched).
VERIFY_ENTRY_PHASES = ("P14",) + VERIFY_PHASES


def compute_candidate_hash(task_id: str, patch_hash_value: str) -> str:
    """Identifies THIS specific (task, patch) pairing - deliberately distinct from
    patch_hash alone, so a patch somehow reused under a different task_id (or a task
    re-executed producing a byte-identical patch) still gets its own candidate identity."""
    return hashlib.sha256(f"{task_id}:{patch_hash_value}".encode("utf-8")).hexdigest()


def task_snapshot_hash_of(fields: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode("utf-8")).hexdigest()


def latest_self_check(project: Path, task_id: str) -> dict[str, Any] | None:
    """Sorted by created_at, NOT by artifact listing order: artifact_id carries a
    random uuid suffix, so file-listing order does not reflect chronology once a
    task has more than one self-check (e.g. an original attempt plus one or more
    M7-H repair re-attempts)."""
    checks = [r for r in list_artifacts(project, artifact_type="P14_SELF_CHECK") if r["fields"].get("task_id") == task_id]
    if not checks:
        return None
    return max(checks, key=lambda r: r.get("created_at", ""))


def derive_verification_depth(project: Path) -> dict[str, Any]:
    """Derives required verification depth from the CANONICAL contracts wherever one
    exists, never an independent guess layered on top of them:

    - reproducibility_required and independent_review_required come directly from
      _is_skippable() against P17/P18's own minimum_profile and the active profile's
      skippable_phases (methodology/profiles/*.json) - the single existing source of
      truth for "LIGHT may skip reproducibility and independent review; STANDARD/
      STRICT may not". This function never second-guesses that.
    - external_validation_required is a STRICTER tier layered on top of
      reproducibility_required (only at STRICT): no canonical field distinguishes
      "reproducibility" from "external validation" specifically (P17's own contract
      names them together, "Reproducibility & Independent Validation"), so this is a
      disclosed, narrower interpretation, not a claim that STRICT-only is written
      anywhere else.
    - required_levels (the 9-rung ladder) and required_validation_levels (the 3-level
      model) have NO canonical per-profile field at all - P15/P16 are never in any
      profile's skippable_phases, so there is nothing to defer to. This function's
      LIGHT/STANDARD/STRICT mapping for those two is this module's own documented
      choice, using the effective profile for P16 (three-level validation's own phase)
      as the single driver, honoring a phase_profile_override on P16 or the VERIFY
      macro phase exactly the way M7-C's engine already does for every other phase.
    """
    state, definition = _require_state(project)
    p16 = definition.get_phase("P16")
    p17 = definition.get_phase("P17")
    p18 = definition.get_phase("P18")

    depth_profile = _effective_profile_for_phase(state, p16)
    reproducibility_required = not _is_skippable(definition, state, p17)
    independent_review_required = not _is_skippable(definition, state, p18)
    external_validation_required = reproducibility_required and depth_profile == "STRICT"

    if depth_profile == "LIGHT":
        required_validation_levels = ["LEVEL_1_CONTROLLED"]
        required_levels = ["STATIC_CHECKS", "UNIT_TESTS"]
    elif depth_profile == "STANDARD":
        required_validation_levels = ["LEVEL_1_CONTROLLED", "LEVEL_2_REPRESENTATIVE"]
        required_levels = ["STATIC_CHECKS", "UNIT_TESTS", "INTEGRATION_TESTS", "LOCAL_VALIDATION", "REGRESSION"]
    else:
        required_validation_levels = list(VALIDATION_LEVELS)
        required_levels = [
            "STATIC_CHECKS", "UNIT_TESTS", "INTEGRATION_TESTS", "E2E_TESTS",
            "LOCAL_VALIDATION", "CLEAN_ENV_VALIDATION", "REGRESSION",
        ]
    if external_validation_required:
        required_levels.append("EXTERNAL_VALIDATION")
    if independent_review_required:
        required_levels.append("INDEPENDENT_REVIEW")

    return {
        "profile": depth_profile,
        "required_levels": required_levels,
        "required_validation_levels": required_validation_levels,
        "independent_review_required": independent_review_required,
        "reproducibility_required": reproducibility_required,
        "external_validation_required": external_validation_required,
    }


def reviewer_is_independent(executor_actor_id: str | None, reviewer_actor_id: str | None) -> bool:
    """Mirrors nogap.py's acceptability() identity-separation rule at the methodology
    layer too (belt-and-suspenders, not a replacement): a renamed role does not change
    actor_id (write_isolated_run_evidence derives it from `provider` alone), so this
    cannot be fooled by relabeling the same identity under a different role name."""
    return bool(executor_actor_id) and bool(reviewer_actor_id) and executor_actor_id != reviewer_actor_id


def evaluate_reproducibility(rerun_consistent: bool, external_validation_required: bool) -> tuple[str, str]:
    """external validation has no real mechanism configured anywhere in this codebase,
    so when it is required (STRICT only - see derive_verification_depth), this never
    pretends it happened: the honest result is INCONCLUSIVE, never a fabricated pass."""
    if not rerun_consistent:
        return "failed", "deterministic result did not reproduce on a second independent fresh worktree"
    if external_validation_required:
        return "inconclusive", "external validation is required at this profile but no external validation mechanism is configured in this environment"
    return "passed", "deterministic result reproduced identically on a second independent fresh worktree"


def verification_binding_snapshot(project: Path, task_id: str, frozen_gate_hash: str | None) -> dict[str, Any]:
    """What a FRESH VerificationResult's binding fields would be right now, for
    comparing against a previously stored one to detect staleness."""
    contract = load_task_contract(project, task_id)
    self_check = latest_self_check(project, task_id)
    if self_check is None:
        raise MethodologyValidationError(f"no P14_SELF_CHECK recorded yet for task {task_id!r}")
    patch_hash_value = self_check["fields"]["patch_hash"]
    definition = load_methodology()
    return {
        "candidate_hash": compute_candidate_hash(task_id, patch_hash_value),
        "patch_hash": patch_hash_value,
        "gate_hash": frozen_gate_hash,
        "methodology_version_at_verification": definition.version,
        "requirement_refs": sorted(contract["fields"].get("requirement_refs", [])),
        "task_snapshot_hash": task_snapshot_hash_of(contract["fields"]),
    }


def verification_staleness(project: Path, result_record: dict[str, Any], frozen_gate_hash: str | None) -> list[str]:
    """Reasons a stored P18_VERIFICATION_RESULT no longer reflects the live candidate/
    gate/methodology/task/requirement binding - empty means still fresh. Checked before
    ever reporting VERIFICATION_COMPLETE_AWAITING_DECISION, not deferred to M8."""
    fields = result_record["fields"]
    task_id = fields["task_id"]
    try:
        current = verification_binding_snapshot(project, task_id, frozen_gate_hash)
    except MethodologyValidationError as exc:
        return [f"task {task_id!r} binding no longer resolvable: {exc}"]

    reasons: list[str] = []
    if current["candidate_hash"] != fields["candidate_hash"]:
        reasons.append("candidate hash changed since this verification ran")
    if current["patch_hash"] != fields["patch_hash"]:
        reasons.append("patch hash changed since this verification ran")
    if current["gate_hash"] != fields["gate_hash"]:
        reasons.append("frozen gate hash changed since this verification ran")
    if current["methodology_version_at_verification"] != fields["methodology_version_at_verification"]:
        reasons.append("methodology version changed since this verification ran")
    if current["task_snapshot_hash"] != fields["task_snapshot_hash"]:
        reasons.append("task contract content changed since this verification ran")
    if sorted(fields.get("requirement_refs", [])) != current["requirement_refs"]:
        reasons.append("requirement set changed since this verification ran")
    return reasons


def verification_acceptance_precondition(project: Path, task_id: str | None) -> dict[str, Any]:
    """A NECESSARY, not sufficient, precondition for ACCEPT on a methodology-tracked
    project: the given task's current candidate must have a P18_VERIFICATION_RESULT
    that is genuinely VERIFICATION_COMPLETE_AWAITING_DECISION under the LIVE
    methodology_version/task/requirement-set/candidate/patch/gate bindings - reusing
    verification_staleness() rather than re-deriving any of that here.

    This function only ever answers "is methodology verification ready?" - it never
    accepts or rejects a decision itself. DecisionEngine (nogap.py's cmd_decide)
    remains the sole acceptance authority and still applies its own independent-
    evidence/identity checks on top of this; a caller must never treat
    satisfied=True as itself sufficient for ACCEPT.

    LEGACY COMPATIBILITY (temporary technical debt, matching M7-E/F/G's "smallest
    explicit compatibility policy"): a project with no methodology state at all
    reports satisfied=True - once a project runs `methodology init`, this precondition
    becomes mandatory and fail-closed, including when no task_id is resolvable at all
    (e.g. the evidence under consideration was never bound to a BUILD candidate).
    """
    state = load_state(project)
    if state is None:
        return {"satisfied": True, "reason": "no methodology state at this project; legacy compatibility (temporary)"}
    if not task_id:
        return {"satisfied": False, "reason": "methodology is initialized but no task_id is associated with the evidence under consideration"}

    gate = _frozen_gate(project)
    frozen_gate_hash = gate.get("hash") if gate else None

    results = [
        r for r in list_artifacts(project, artifact_type="P18_VERIFICATION_RESULT")
        if r["fields"].get("task_id") == task_id
    ]
    if not results:
        return {"satisfied": False, "reason": f"no methodology verification result recorded for task {task_id!r}"}
    # Sorted by updated_at, NOT list/file order (artifact_id carries a random uuid
    # suffix): a task can legitimately have more than one P18_VERIFICATION_RESULT
    # over time (repeated `nogap verify` runs across distinct candidates, e.g. after
    # an M7-H repair produced a new patch) - only the most recently touched one
    # reflects the CURRENT candidate.
    result = max(results, key=lambda r: r.get("updated_at", ""))
    if result.get("status") != "VERIFICATION_COMPLETE_AWAITING_DECISION":
        return {
            "satisfied": False,
            "reason": f"methodology verification status is {result.get('status')!r}, not VERIFICATION_COMPLETE_AWAITING_DECISION",
        }

    stale_reasons = verification_staleness(project, result, frozen_gate_hash)
    if stale_reasons:
        return {"satisfied": False, "reason": "methodology verification evidence is stale: " + "; ".join(stale_reasons)}
    return {"satisfied": True, "reason": f"methodology verification {result['fields']['verification_run_id']} is complete and current"}
