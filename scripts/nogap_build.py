#!/usr/bin/env python3
"""M7-F: binds methodology BUILD phases (P12-P14) to the existing M6 trusted
execution pipeline, making pre-build readiness causally gate execution.

Three authorities stay separate, on purpose:
- MethodologyEngine (this module + nogap_methodology.py/nogap_artifacts.py)
  decides "may execution begin?" - it never runs a process and never judges
  a patch.
- ExecutionBackend (nogap_execution.py) decides "what process ran and what
  raw effect occurred?" - it knows nothing about methodology state.
- Trust Runtime (nogap.py's evidence/gate/decide machinery, nogap_effects.py)
  decides "what evidence is acceptable?" - untouched by this module. P14
  self-check evidence is never authoritative for ACCEPT; only independent
  verification (M6-D) plus 'nogap decide' can produce that.

LEGACY COMPATIBILITY POLICY: a project with no methodology state at all is
not silently treated as READY - preflight_build() reports it under its own
explicit status, METHODOLOGY_NOT_INITIALIZED, distinct from READY. It is the
one case execution remains permitted in, preserving pre-M7 behavior for
projects that never opted into the MethodologyEngine. Once a project *has*
run `methodology init`, this barrier is fully fail-closed: BUILD_PHASES may
only be entered when prebuild_readiness() holds, current_phase is one this
module recognizes as BUILD-eligible, and (when comparable) a methodology P11
gate plan agrees with any already-frozen Trust Runtime gate. There is no
force-bypass flag - PROFILE_AWARE by construction, since prebuild_readiness()
itself already accounts for the project's effective profile.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from nogap_artifacts import (
    create_artifact,
    list_artifacts,
    validate_record,
)
from nogap_methodology import (
    MethodologyValidationError,
    load_methodology,
    load_state,
    transition,
)

# P11 is included because "prebuild readiness satisfied" means BUILD may begin from
# there; P12-P14 are already inside BUILD and remain governed the same way (a project
# cannot silently escape the barrier once inside it either).
BUILD_PHASES = {"P12", "P13", "P14"}
PERMITTED_PHASES = {"P11"} | BUILD_PHASES


def _frozen_gate(project: Path) -> dict[str, Any] | None:
    gate_path = project.resolve() / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
    if not gate_path.is_file():
        return None
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return gate if isinstance(gate, dict) and gate.get("status") == "frozen" else None


def gate_alignment_reasons(project: Path) -> list[str]:
    """Compares a frozen Trust Runtime gate against any P11_GATE_PLAN artifacts.

    Only compares a field when BOTH sides declare a non-empty list for it - an
    empty-by-default frozen gate (e.g. right after `nogap freeze` with no rules ever
    set) is treated as "not comparable yet", never as "the runtime gate requires
    nothing". When both sides do declare something and they disagree, that is a
    genuine conflict the barrier reports and blocks on - it is never silently
    reconciled by preferring one side, and this module never writes to
    .code-loop/runtime/gates/ to "fix" the mismatch itself.
    """
    gate = _frozen_gate(project)
    if gate is None:
        return []
    plans = list_artifacts(project, artifact_type="P11_GATE_PLAN")
    if not plans:
        return []
    rules = gate.get("rules", {})
    gate_commands = set(rules.get("required_commands", []))
    gate_forbidden = set(rules.get("forbidden_paths", []))
    reasons: list[str] = []
    for plan in plans:
        fields = plan.get("fields", {})
        plan_commands = set(fields.get("required_commands", []))
        plan_forbidden = set(fields.get("forbidden_paths", []))
        if gate_commands and plan_commands and gate_commands != plan_commands:
            reasons.append(
                f"P11 gate plan {plan['artifact_id']} required_commands {sorted(plan_commands)} "
                f"differs from frozen Trust gate required_commands {sorted(gate_commands)}"
            )
        if gate_forbidden and plan_forbidden and gate_forbidden != plan_forbidden:
            reasons.append(
                f"P11 gate plan {plan['artifact_id']} forbidden_paths {sorted(plan_forbidden)} "
                f"differs from frozen Trust gate forbidden_paths {sorted(gate_forbidden)}"
            )
    return reasons


def preflight_build(project: Path) -> dict[str, Any]:
    """"May execution begin?" - the one function `nogap run --execute` must consult
    before creating a worktree or launching any process. Never raises: always returns
    a structured, auditable result so a caller can print/log WHY, never just "blocked".
    """
    state = load_state(project)
    if state is None:
        return {
            "permitted": True,
            "status": "METHODOLOGY_NOT_INITIALIZED",
            "reasons": [
                "no methodology state at this project (methodology was never initialized); "
                "executing without pre-build governance (legacy compatibility mode)"
            ],
            "profile": None,
            "current_phase": None,
            "readiness": None,
        }

    definition = load_methodology()
    if state["methodology_version"] != definition.version:
        return {
            "permitted": False,
            "status": "METHODOLOGY_BLOCKED",
            "reasons": [
                f"methodology version mismatch: project state is v{state['methodology_version']}, "
                f"loaded definition is v{definition.version}"
            ],
            "profile": state["effective_profile"],
            "current_phase": state["current_phase"],
            "readiness": None,
        }

    from nogap_artifacts import prebuild_readiness  # local import: avoids a cycle at module load

    current_phase = state["current_phase"]
    readiness = prebuild_readiness(project)
    reasons: list[str] = []
    if current_phase not in PERMITTED_PHASES:
        reasons.append(
            f"current phase {current_phase!r} does not permit BUILD execution "
            f"(must be one of {sorted(PERMITTED_PHASES)})"
        )
    if not readiness["ready"]:
        reasons.extend(readiness["missing"])
    reasons.extend(gate_alignment_reasons(project))

    return {
        "permitted": not reasons,
        "status": "READY" if not reasons else "METHODOLOGY_BLOCKED",
        "reasons": reasons,
        "profile": readiness["profile"],
        "current_phase": current_phase,
        "readiness": readiness,
    }


def load_task_contract(project: Path, task_id: str) -> dict[str, Any]:
    """Loads a P12_TASK_CONTRACT by its stable task_id (not the generic artifact_id).
    Fail-closed: raises if it does not exist, is not ACTIVE, or now fails its own
    validation (e.g. it references a requirement that has since been superseded)."""
    matches = [
        record for record in list_artifacts(project, artifact_type="P12_TASK_CONTRACT")
        if record.get("fields", {}).get("task_id") == task_id
    ]
    if not matches:
        raise MethodologyValidationError(
            f"unknown task_id: {task_id!r}; create one first with "
            f"'nogap methodology artifact-create --type P12_TASK_CONTRACT ...'"
        )
    contract = matches[0]
    if contract.get("status") != "ACTIVE":
        raise MethodologyValidationError(f"task {task_id!r} is not ACTIVE (status={contract.get('status')!r})")
    problems = validate_record(project, contract)
    if problems:
        raise MethodologyValidationError(f"task {task_id!r} failed validation: " + "; ".join(problems))
    return contract


def enter_build_phase(project: Path, actor: str, reason: str) -> dict[str, Any]:
    """P11 -> P12, through the M7-C transition engine only. Callers must have already
    confirmed preflight_build().permitted - this still re-checks P11's own structural
    required_artifacts via transition() itself, so it cannot be called out of turn."""
    p11_artifacts = list_artifacts(project, artifact_type="P11_GATE_PLAN")
    artifact_refs = [record["artifact_id"] for record in p11_artifacts]
    return transition(project, "P12", actor, reason, artifact_refs=artifact_refs, authority_class="tool")


def record_plan_evidence(project: Path, run_id: str, task_contract: dict[str, Any], actor: str) -> str:
    """Writes a minimal runtime evidence record for the task contract itself, so the
    P12->P13 transition (required_evidence=["plan_record"]) has a real, resolvable
    evidence id to cite instead of a fabricated string. Deliberately NOT execution or
    verification evidence: authority="planning" is never counted by
    is_authoritative_evidence() toward ACCEPT."""
    evidence_dir = project.resolve() / ".code-loop" / "runtime" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    task_id = task_contract["fields"]["task_id"]
    evidence_id = f"evidence-plan-{task_id.lower()}"
    evidence = {
        "id": evidence_id,
        "run_id": run_id,
        "kind": "plan",
        "status": "recorded",
        "provenance": {
            "created_by": actor,
            "actor_id": actor,
            "authority": "planning",
            "task_id": task_id,
            "task_contract_artifact_id": task_contract["artifact_id"],
        },
        "summary": f"task contract {task_id} recorded",
    }
    (evidence_dir / f"{evidence_id}.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return evidence_id


def enter_execution_phase(
    project: Path, actor: str, reason: str, task_contract: dict[str, Any], plan_evidence_id: str,
) -> dict[str, Any]:
    """P12 -> P13: about to run inside the isolated backend."""
    return transition(
        project, "P13", actor, reason,
        artifact_refs=[task_contract["artifact_id"]],
        evidence_refs=[plan_evidence_id],
        authority_class="tool",
    )


def record_build_failure(
    project: Path, actor: str, reason: str, execution_evidence_id: str, patch_path: str,
) -> dict[str, Any]:
    """P13 -> P12, P13's own failure_transition: a failed execution never blindly
    advances to P14 self-check - it returns to task-contract scope for another attempt."""
    return transition(
        project, "P12", actor, reason,
        evidence_refs=[execution_evidence_id],
        artifact_refs=[patch_path],
        authority_class="tool",
    )


def enter_self_check_phase(
    project: Path, actor: str, reason: str, execution_evidence_id: str, patch_path: str,
) -> dict[str, Any]:
    """P13 -> P14: only reachable after a successful execution (see cmd_run's wiring -
    this function is never called on the failure path)."""
    return transition(
        project, "P14", actor, reason,
        evidence_refs=[execution_evidence_id],
        artifact_refs=[patch_path],
        authority_class="tool",
    )


def create_self_check(
    project: Path,
    task_contract: dict[str, Any],
    execution_evidence_id: str,
    changed_files: list[str],
    patch_hash: str,
    process_outcome: str,
    expected_effect_result: str,
    actor: str,
    *,
    planned_test_outcomes: list[str] = (),
    limitations: list[str] = (),
    unresolved_issues: list[str] = (),
) -> dict[str, Any]:
    """Records the P14 artifact. self_check_authority is forced to "execution" inside
    create_artifact() itself - it cannot be overridden here or by any caller, so this
    can never be mistaken for or smuggled in as independent verification."""
    return create_artifact(
        project,
        "P14_SELF_CHECK",
        {
            "task_id": task_contract["fields"]["task_id"],
            "execution_evidence_ids": [execution_evidence_id],
            "changed_files": list(changed_files),
            "patch_hash": patch_hash,
            "process_outcome": process_outcome,
            "expected_effect_result": expected_effect_result,
            "planned_test_outcomes": list(planned_test_outcomes),
            "limitations": list(limitations),
            "unresolved_issues": list(unresolved_issues),
        },
        actor=actor,
        evidence_refs=[execution_evidence_id],
    )


def patch_hash(patch: str) -> str:
    return hashlib.sha256(patch.encode("utf-8")).hexdigest()


def build_status_label(exec_status: str, execution_status: str) -> str:
    """Maps the existing M6-C EVIDENCE_STATUS/execution_status vocabulary
    (nogap_effects.classify_agent_execution) to the coarser BUILD-level status
    vocabulary this milestone introduces for `nogap run` reporting. Presentation only:
    nogap_effects.py's own vocabulary is untouched."""
    if execution_status in {
        "CANCELLED", "TIMED_OUT", "PROCESS_ABNORMAL_NO_EFFECT", "EFFECT_PRESENT_BUT_PROCESS_ABNORMAL",
    }:
        return "PROCESS_FAILED"
    if execution_status == "NO_EXPECTED_EFFECT":
        return "EXPECTED_EFFECT_FAILED"
    if exec_status == "passed":
        return "BUILD_COMPLETE_AWAITING_VERIFICATION"
    return "PROCESS_FAILED"
