#!/usr/bin/env python3
"""M7-H: Failure / Repair Orchestrator.

Canonical invariant, never violated:
FAIL -> preserve evidence -> reproduce -> characterize -> research prior art ->
root cause -> compare candidate repairs -> minimal repair -> regression ->
revalidation -> resolution. No blind retry, ever - every forward step requires an
explicit, reasoned call; nothing here loops automatically.

A FailureRecord is a first-class, permanently queryable record - never deleted,
history never overwritten (only appended to). It is NOT an acceptance authority:
nothing here writes authority="acceptance" or decides ACCEPT (that remains
nogap_verify_binding.verification_acceptance_precondition + nogap.py's cmd_decide).
Repair destination is DIAGNOSED, never guessed: it follows root_cause_class through
REPAIR_ROUTING_MAP, and every actual phase movement goes through
nogap_methodology.transition() only - this module never mutates current_phase
directly, and never invents a legal edge the M7-C phase-contract graph does not
already have.

CHARACTERIZATION FINDING (documented, not "fixed" - fixing it would mean rewriting
the M7-C phase contracts, explicitly out of scope for this milestone): the symbolic
REPAIR_LOOP pseudo-phase is only ever a legal transition target from P21 in the
current canonical contracts (methodology/phases/p21.json is the ONLY phase file
whose failure_transition literally equals the string "REPAIR_LOOP"; every other
phase's failure_transition, where set, names a real phase id). P13-P19's OWN
failure_transition values (P12/P13) ARE their real, pre-existing repair-return
mechanism, already wired into M7-C's build_loop/verify_loop bookkeeping
(transition() resolves the old loop and, on a later forward LOOP_ENTRY edge,
creates the new one - no separate machinery needed). For BUILD/VERIFY-origin
failures (this milestone's actual scope, matching its own manual scenarios), this
module routes repairs through that real mechanism - each phase's own
failure_transition / allowed_back_transitions - rather than forcing the literal
"REPAIR_LOOP" string, which M7-C's own fail-closed check would reject from any of
P13-P18 today. Repair progress stays fully traceable via this module's own
append-only history plus a reference to whatever loop record transition() actually
produced - never a second, parallel loop state machine.

Reuses rather than re-derives: reference resolution against the M6 evidence ledger
and the methodology artifact registry (nogap_artifacts.py), and - for revalidation -
nogap_verify_binding.verification_acceptance_precondition() itself, the exact same
staleness/completeness check M7-G's decide interlock uses. Nothing here duplicates
that logic.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from nogap_artifacts import load_artifact
from nogap_methodology import (
    MethodologyValidationError,
    _now,
    _require,
    _require_state,
    can_transition,
    load_methodology,
    load_state,
    methodology_state_dir,
    resolve_loop,
    transition,
)

# --- vocabularies -----------------------------------------------------------

FAILURE_ORDER = [
    "OPEN", "EVIDENCE_PRESERVED", "REPRODUCED", "CHARACTERIZED", "RESEARCHED",
    "ROOT_CAUSE_IDENTIFIED", "REPAIR_PROPOSED", "REPAIR_SELECTED", "REPAIRED",
    "REGRESSION_TESTED", "REVALIDATED", "RESOLVED",
]
PARK_STATES = {"INCONCLUSIVE", "REJECTED", "ABANDONED"}
ALL_FAILURE_STATES = set(FAILURE_ORDER) | PARK_STATES

REPRODUCTION_STATUSES = {"REPRODUCED", "NOT_REPRODUCED", "INTERMITTENT", "INCONCLUSIVE"}

ROOT_CAUSE_CLASSES = {
    "IMPLEMENTATION_DEFECT", "REQUIREMENT_DEFECT", "ARCHITECTURE_DEFECT",
    "PRIOR_ART_INVALIDATION", "TEST_OR_GATE_DEFECT", "ENVIRONMENT_DEFECT",
    "DATA_DEFECT", "DEPENDENCY_DEFECT", "UNKNOWN",
}

# Root cause -> candidate target phase(s), in preference order (first = most
# minimal/direct). This is a PROPOSAL vocabulary, not a promise of legality: the
# M7-C phase-contract graph is the actual authority on which of these are reachable
# from wherever the project's current_phase is when a repair is selected (see the
# module docstring's characterization finding - several of these are only reachable
# from P18 today, and DATA/TEST_OR_GATE/ENVIRONMENT targets have real, disclosed
# gaps for phases earlier than P18). propose_repair/select_repair report the
# conflict honestly rather than inventing a graph edge to route around it.
REPAIR_ROUTING_MAP: dict[str, tuple[str, ...]] = {
    "IMPLEMENTATION_DEFECT": ("P13",),
    "REQUIREMENT_DEFECT": ("P6",),
    "ARCHITECTURE_DEFECT": ("P7", "P8"),
    "PRIOR_ART_INVALIDATION": ("P3", "P4", "P5"),
    "TEST_OR_GATE_DEFECT": ("P10", "P11"),
    "ENVIRONMENT_DEFECT": ("P9", "P13"),
    "DATA_DEFECT": ("P2", "P10"),
    "DEPENDENCY_DEFECT": ("P5", "P7", "P8"),
    "UNKNOWN": (),
}

DEFAULT_MAX_REPAIR_ATTEMPTS = 3


def failures_dir(project: Path) -> Path:
    return methodology_state_dir(project) / "failures"


def _next_failure_id(project: Path) -> str:
    existing = list_failures(project)
    max_n = 0
    for record in existing:
        fid = record.get("failure_id", "")
        if fid.startswith("FAIL-"):
            try:
                max_n = max(max_n, int(fid[5:]))
            except ValueError:
                continue
    return f"FAIL-{max_n + 1:03d}"


def load_failure(project: Path, failure_id: str) -> dict[str, Any] | None:
    path = failures_dir(project) / f"{failure_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MethodologyValidationError(f"{path} is invalid JSON: {exc}") from exc
    _require(isinstance(data, dict), f"{path}: failure record must be a JSON object")
    return data


def list_failures(project: Path, state: str | None = None) -> list[dict[str, Any]]:
    directory = failures_dir(project)
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    if state:
        records = [r for r in records if r.get("current_state") == state]
    return records


def _save(project: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = failures_dir(project) / f"{record['failure_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _append_history(record: dict[str, Any], action: str, actor: str, reason: str, **extra: Any) -> None:
    """Append-only: never edits or removes a prior history entry."""
    entry = {
        "action": action, "state": record["current_state"], "actor_id": actor.strip(),
        "reason": reason.strip(), "changed_at": _now(),
    }
    entry.update(extra)
    record.setdefault("history", []).append(entry)
    record["last_updated_at"] = entry["changed_at"]


def _require_predecessor(record: dict[str, Any], step_name: str, allowed: set[str]) -> None:
    current = record["current_state"]
    if current not in allowed:
        raise MethodologyValidationError(
            f"failure {record['failure_id']}: cannot record {step_name} from state {current!r} "
            f"(requires one of {sorted(allowed)}) - illegal state jump rejected"
        )


def _runtime_evidence_ids(project: Path) -> set[str] | None:
    evidence_dir = project.resolve() / ".code-loop" / "runtime" / "evidence"
    if not evidence_dir.is_dir():
        return None
    ids: set[str] = set()
    for path in evidence_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            ids.add(data["id"])
    return ids


def _check_evidence_refs(project: Path, refs: list[str]) -> list[str]:
    """Unknown/stale references are rejected where resolvable - i.e. only when the
    ledger exists at all; a project with no runtime yet accepts refs at face value
    (nothing to resolve against), matching nogap_methodology's own convention."""
    known = _runtime_evidence_ids(project)
    if known is None or not refs:
        return []
    return [ref for ref in refs if ref not in known]


def _check_artifact_refs(project: Path, refs: list[str]) -> list[str]:
    return [ref for ref in refs if load_artifact(project, ref) is None]


def _check_mixed_refs(project: Path, refs: list[str]) -> list[str]:
    """For a reference that may legitimately be EITHER a methodology artifact (an
    ADR, a P3_PRIOR_ART record, a requirement, ...) OR M6 runtime evidence (execution/
    verification evidence): unresolved only if it matches neither. Evidence
    resolution falls back to face-value acceptance when the ledger doesn't exist yet,
    matching the established convention elsewhere in this codebase."""
    known_evidence = _runtime_evidence_ids(project)

    def _resolves(ref: str) -> bool:
        if load_artifact(project, ref) is not None:
            return True
        return known_evidence is None or ref in known_evidence

    return [ref for ref in refs if not _resolves(ref)]


# --- creation -----------------------------------------------------------------

def create_failure(
    project: Path,
    *,
    failure_class: str,
    summary: str,
    actor: str,
    origin_phase: str | None = None,
    task_id: str | None = None,
    project_id: str | None = None,
    evidence_refs: list[str] = (),
    artifact_refs: list[str] = (),
    failure_id: str | None = None,
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
) -> dict[str, Any]:
    _require(bool(actor and actor.strip()), "create_failure requires a non-empty actor_id")
    _require(bool(failure_class and failure_class.strip()), "create_failure requires a non-empty failure_class")
    _require(bool(summary and summary.strip()), "create_failure requires a non-empty summary")
    state, definition = _require_state(project)

    if origin_phase is None:
        origin_phase = state["current_phase"]
    _require(origin_phase in definition.phases, f"unknown origin_phase: {origin_phase!r}")

    unknown_evidence = _check_evidence_refs(project, list(evidence_refs))
    if unknown_evidence:
        raise MethodologyValidationError(f"unknown evidence reference(s): {unknown_evidence}")
    unknown_artifacts = _check_artifact_refs(project, list(artifact_refs))
    if unknown_artifacts:
        raise MethodologyValidationError(f"unknown artifact reference(s): {unknown_artifacts}")

    failure_id = failure_id or _next_failure_id(project)
    if load_failure(project, failure_id) is not None:
        raise MethodologyValidationError(f"duplicate failure_id: {failure_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "failure_id": failure_id,
        "methodology_version": definition.version,
        "project_id": project_id,
        "task_id": task_id,
        "origin_phase": origin_phase,
        "current_state": "OPEN",
        "failure_class": failure_class.strip(),
        "summary": summary.strip(),
        "first_observed_at": timestamp,
        "last_updated_at": timestamp,
        "actor_id": actor.strip(),
        "evidence_refs": list(evidence_refs),
        "artifact_refs": list(artifact_refs),
        "reproduction": None,
        "reproduction_refs": [],
        "characterization": None,
        "research_refs": [],
        "research_policy_exception": None,
        "root_cause": None,
        "root_cause_class": None,
        "candidate_repairs": [],
        "selected_repair": None,
        "repair_target_phase": None,
        "active_loop_id": None,
        "attempt_count": 0,
        "max_repair_attempts": max_repair_attempts,
        "regression_refs": [],
        "regression_attempts": [],
        "revalidation_refs": [],
        "revalidation_attempts": [],
        "resolution": None,
        "history": [],
    }
    _append_history(record, "CREATED", actor, "failure registered")
    return _save(project, record)


# --- lifecycle steps ------------------------------------------------------------

def record_evidence_preservation(
    project: Path, failure_id: str, *, evidence_refs: list[str] = (), artifact_refs: list[str] = (),
    actor: str, reason: str,
) -> dict[str, Any]:
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "evidence preservation", {"OPEN"})
    _require(bool(evidence_refs) or bool(artifact_refs), "evidence preservation requires at least one evidence or artifact reference")
    unknown_evidence = _check_evidence_refs(project, list(evidence_refs))
    if unknown_evidence:
        raise MethodologyValidationError(f"unknown evidence reference(s): {unknown_evidence}")
    unknown_artifacts = _check_artifact_refs(project, list(artifact_refs))
    if unknown_artifacts:
        raise MethodologyValidationError(f"unknown artifact reference(s): {unknown_artifacts}")

    record["evidence_refs"] = sorted(set(record["evidence_refs"]) | set(evidence_refs))
    record["artifact_refs"] = sorted(set(record["artifact_refs"]) | set(artifact_refs))
    record["current_state"] = "EVIDENCE_PRESERVED"
    _append_history(record, "EVIDENCE_PRESERVED", actor, reason)
    return _save(project, record)


def record_reproduction(
    project: Path, failure_id: str, *, reproduction_status: str, actor: str, reason: str,
    environment: str | None = None, reproduction_evidence_refs: list[str] = (), attempt_note: str | None = None,
) -> dict[str, Any]:
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "reproduction", {"EVIDENCE_PRESERVED", "REPRODUCED"})
    _require(reproduction_status in REPRODUCTION_STATUSES, f"unknown reproduction_status: {reproduction_status!r}")
    unknown = _check_evidence_refs(project, list(reproduction_evidence_refs))
    if unknown:
        raise MethodologyValidationError(f"unknown evidence reference(s): {unknown}")

    attempt = {
        "status": reproduction_status, "environment": environment, "note": attempt_note,
        "evidence_refs": list(reproduction_evidence_refs), "recorded_at": _now(), "actor_id": actor.strip(),
    }
    if record["reproduction"] is None:
        record["reproduction"] = {"status": reproduction_status, "attempts": [attempt]}
    else:
        record["reproduction"]["status"] = reproduction_status
        record["reproduction"]["attempts"].append(attempt)
    record["reproduction_refs"] = sorted(set(record["reproduction_refs"]) | set(reproduction_evidence_refs))
    record["current_state"] = "REPRODUCED"
    _append_history(record, "REPRODUCTION_RECORDED", actor, reason, reproduction_status=reproduction_status)
    return _save(project, record)


def record_characterization(
    project: Path, failure_id: str, *, actor: str, reason: str,
    affected_requirement_refs: list[str] = (), affected_gate_refs: list[str] = (),
    scope: str | None = None, expected: str | None = None, observed: str | None = None,
    frequency: str | None = None, deterministic: bool | None = None, blast_radius: str | None = None,
) -> dict[str, Any]:
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "characterization", {"REPRODUCED"})
    record["characterization"] = {
        "affected_requirement_refs": list(affected_requirement_refs),
        "affected_gate_refs": list(affected_gate_refs),
        "scope": scope, "expected": expected, "observed": observed, "frequency": frequency,
        "deterministic": deterministic, "blast_radius": blast_radius, "recorded_at": _now(),
    }
    record["current_state"] = "CHARACTERIZED"
    _append_history(record, "CHARACTERIZED", actor, reason)
    return _save(project, record)


def record_research(
    project: Path, failure_id: str, *, actor: str, reason: str,
    research_refs: list[str] = (), policy_exception: dict[str, str] | None = None,
) -> dict[str, Any]:
    """RESEARCH BEFORE REPAIR: research_refs must be non-empty UNLESS an explicit,
    audited policy exception is supplied AND the project's effective profile is LIGHT
    (STANDARD/STRICT never accept the exception - "STANDARD/STRICT should require
    stronger research/evidence depth"). No silent bypass: an exception without its
    own actor/authority/reason is rejected exactly like missing research would be."""
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "research", {"CHARACTERIZED"})

    if research_refs:
        # A research ref may point to prior-art evidence in the runtime ledger OR a
        # methodology artifact (e.g. a P3_PRIOR_ART record).
        unresolved = _check_mixed_refs(project, list(research_refs))
        if unresolved:
            raise MethodologyValidationError(f"unknown research reference(s): {unresolved}")
        state, _definition = _require_state(project)
        record["research_refs"] = sorted(set(record["research_refs"]) | set(research_refs))
        record["research_policy_exception"] = None
    else:
        state, _definition = _require_state(project)
        if state["effective_profile"] != "LIGHT":
            raise MethodologyValidationError(
                f"research is required before repair at profile {state['effective_profile']!r} "
                f"(only LIGHT may request an explicit policy exception)"
            )
        _require(isinstance(policy_exception, dict), "no research_refs supplied and no policy_exception given - research before repair cannot be silently skipped")
        exc_reason = policy_exception.get("reason") if policy_exception else None
        exc_actor = policy_exception.get("actor_id") if policy_exception else None
        exc_authority = policy_exception.get("authority") if policy_exception else None
        _require(bool(exc_reason and str(exc_reason).strip()), "policy_exception requires a non-empty reason")
        _require(bool(exc_actor and str(exc_actor).strip()), "policy_exception requires a non-empty actor_id")
        _require(bool(exc_authority and str(exc_authority).strip()), "policy_exception requires a non-empty authority")
        record["research_policy_exception"] = {
            "reason": str(exc_reason).strip(), "actor_id": str(exc_actor).strip(),
            "authority": str(exc_authority).strip(), "profile_at_exception": state["effective_profile"],
            "recorded_at": _now(),
        }

    record["current_state"] = "RESEARCHED"
    _append_history(record, "RESEARCHED", actor, reason, skipped_via_policy_exception=bool(record["research_policy_exception"]))
    return _save(project, record)


def record_root_cause(
    project: Path, failure_id: str, *, root_cause_class: str, root_cause_summary: str,
    supporting_evidence_refs: list[str] = (), actor: str, reason: str,
) -> dict[str, Any]:
    """confidence_status is DERIVED from whether supporting evidence genuinely
    resolves and is non-empty - never accepted as a caller-supplied "confidence
    score" (that would be treating model confidence as evidence, explicitly
    forbidden). UNKNOWN, or evidence that fails to resolve/is empty, lands the
    record in INCONCLUSIVE rather than ROOT_CAUSE_IDENTIFIED - never guessed."""
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "root cause", {"RESEARCHED"})
    _require(root_cause_class in ROOT_CAUSE_CLASSES, f"unknown root_cause_class: {root_cause_class!r}")
    _require(bool(root_cause_summary and root_cause_summary.strip()), "root cause requires a non-empty summary")

    unknown = _check_mixed_refs(project, list(supporting_evidence_refs))
    if unknown:
        raise MethodologyValidationError(f"unknown evidence reference(s): {unknown}")

    supported = bool(supporting_evidence_refs) and not unknown
    confidence_status = "SUPPORTED" if supported else "INSUFFICIENT"

    record["root_cause_class"] = root_cause_class
    record["root_cause"] = {
        "summary": root_cause_summary.strip(), "supporting_evidence_refs": list(supporting_evidence_refs),
        "confidence_status": confidence_status, "recorded_at": _now(),
    }
    if root_cause_class == "UNKNOWN" or confidence_status == "INSUFFICIENT":
        record["current_state"] = "INCONCLUSIVE"
        _append_history(record, "ROOT_CAUSE_INCONCLUSIVE", actor, reason, root_cause_class=root_cause_class)
    else:
        record["current_state"] = "ROOT_CAUSE_IDENTIFIED"
        _append_history(record, "ROOT_CAUSE_IDENTIFIED", actor, reason, root_cause_class=root_cause_class)
    return _save(project, record)


# --- repair proposal / selection --------------------------------------------

def propose_repair(
    project: Path, failure_id: str, *, description: str, target_phase: str, actor: str, reason: str,
    expected_effect: str | None = None, risk: str | None = None, cost: str | None = None,
    affected_requirements: list[str] = (), evidence_refs: list[str] = (), repair_id: str | None = None,
) -> dict[str, Any]:
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "repair proposal", {"ROOT_CAUSE_IDENTIFIED", "REPAIR_PROPOSED"})
    root_cause_class = record["root_cause_class"]
    _require(root_cause_class is not None and root_cause_class != "UNKNOWN",
             "cannot propose a repair without an identified (non-UNKNOWN) root cause")

    definition = load_methodology()
    _require(target_phase in definition.phases, f"unknown target_phase: {target_phase!r}")
    allowed_targets = REPAIR_ROUTING_MAP.get(root_cause_class, ())
    _require(
        target_phase in allowed_targets,
        f"invalid repair target: {target_phase!r} is not an allowed destination for root_cause_class "
        f"{root_cause_class!r} (allowed: {allowed_targets})",
    )
    unknown = _check_mixed_refs(project, list(evidence_refs))
    if unknown:
        raise MethodologyValidationError(f"unknown evidence reference(s): {unknown}")

    repair_id = repair_id or f"R{len(record['candidate_repairs']) + 1}"
    if any(r["repair_id"] == repair_id for r in record["candidate_repairs"]):
        raise MethodologyValidationError(f"duplicate repair_id: {repair_id}")

    proposal = {
        "repair_id": repair_id, "description": description.strip() if description else description,
        "target_phase": target_phase, "expected_effect": expected_effect, "risk": risk, "cost": cost,
        "affected_requirements": list(affected_requirements), "evidence_refs": list(evidence_refs),
        "status": "PROPOSED", "proposed_by": actor.strip(), "proposed_at": _now(),
    }
    _require(bool(description and description.strip()), "repair proposal requires a non-empty description")
    record["candidate_repairs"].append(proposal)
    record["current_state"] = "REPAIR_PROPOSED"
    _append_history(record, "REPAIR_PROPOSED", actor, reason, repair_id=repair_id, target_phase=target_phase)
    return _save(project, record)


def select_repair(
    project: Path, failure_id: str, repair_id: str, *, actor: str, reason: str, authority: str = "human",
) -> dict[str, Any]:
    """Selecting a repair commits to it: this immediately requests the actual
    methodology transition to the repair's target_phase, through
    nogap_methodology.transition() only - never a direct current_phase mutation.
    If the M7-C phase-contract graph does not currently permit that edge, this
    fails closed and reports the exact conflict rather than forcing it."""
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "repair selection", {"REPAIR_PROPOSED"})
    _require(bool(actor and actor.strip()), "repair selection requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "repair selection requires a non-empty reason")

    candidate = next((r for r in record["candidate_repairs"] if r["repair_id"] == repair_id), None)
    _require(candidate is not None, f"unknown repair_id: {repair_id!r}")

    if record["attempt_count"] >= record["max_repair_attempts"]:
        raise MethodologyValidationError(
            f"repair budget exhausted: {record['attempt_count']}/{record['max_repair_attempts']} attempts already used"
        )

    target_phase = candidate["target_phase"]
    # nogap_methodology.transition()'s evidence_refs means REAL runtime evidence ids
    # specifically (resolved against .code-loop/runtime/evidence/) - never a
    # methodology artifact id, that is what artifact_refs is for. The failure's own
    # preserved evidence (record_evidence_preservation's whole point) is what
    # justifies this transition; the candidate's own supporting refs (often
    # methodology artifacts like an ADR) go through artifact_refs instead, alongside
    # the failure_id itself.
    known_evidence = _runtime_evidence_ids(project) or set()
    transition_evidence_refs = [ref for ref in record["evidence_refs"] if ref in known_evidence]
    if not transition_evidence_refs:
        transition_evidence_refs = [ref for ref in candidate["evidence_refs"] if ref in known_evidence]
    transition_artifact_refs = [failure_id] + [ref for ref in candidate["evidence_refs"] if ref not in known_evidence]
    # Structural required_artifacts/required_evidence checks apply to whatever refs
    # are actually supplied - the dry run must use the SAME refs the real transition
    # below will use, or it would (incorrectly) always see the current phase's
    # requirements as unsatisfied regardless of target legality.
    dry_run = can_transition(project, target_phase, evidence_refs=transition_evidence_refs, artifact_refs=transition_artifact_refs)
    if not dry_run["allowed"]:
        raise MethodologyValidationError(
            f"repair target {target_phase!r} is not currently a legal methodology transition: "
            f"{'; '.join(dry_run['blocked_reasons'])}"
        )

    new_state = transition(
        project, target_phase, actor, f"repair {repair_id} selected for failure {failure_id}: {reason}",
        artifact_refs=transition_artifact_refs, evidence_refs=transition_evidence_refs, authority_class=authority,
    )
    active_loop = next((loop for loop in new_state["loops"] if loop["status"] == "ACTIVE"), None)

    candidate["status"] = "SELECTED"
    record["selected_repair"] = {
        "repair_id": repair_id, "selected_by": actor.strip(), "reason": reason.strip(),
        "authority": authority, "timestamp": _now(),
    }
    record["repair_target_phase"] = target_phase
    record["active_loop_id"] = active_loop["loop_id"] if active_loop else record["active_loop_id"]
    record["current_state"] = "REPAIR_SELECTED"
    _append_history(record, "REPAIR_SELECTED", actor, reason, repair_id=repair_id, target_phase=target_phase)
    return _save(project, record)


def record_repaired(
    project: Path, failure_id: str, *, repair_evidence_refs: list[str], actor: str, reason: str,
) -> dict[str, Any]:
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "repair completion", {"REPAIR_SELECTED"})
    _require(bool(repair_evidence_refs), "repair completion requires at least one evidence reference")
    unknown = _check_evidence_refs(project, list(repair_evidence_refs))
    if unknown:
        raise MethodologyValidationError(f"unknown evidence reference(s): {unknown}")

    record["attempt_count"] += 1
    record["candidate_repairs"] = [
        {**r, "repair_evidence_refs": list(repair_evidence_refs)} if r["repair_id"] == record["selected_repair"]["repair_id"] else r
        for r in record["candidate_repairs"]
    ]
    record["current_state"] = "REPAIRED"
    _append_history(record, "REPAIRED", actor, reason, attempt_count=record["attempt_count"])
    return _save(project, record)


# --- regression / revalidation / resolution -----------------------------------

def record_regression(
    project: Path, failure_id: str, *, result: str, actor: str, reason: str,
    tests_executed: list[str] = (), gate_ids: list[str] = (), requirements_affected: list[str] = (),
    evidence_refs: list[str] = (),
) -> dict[str, Any]:
    """A repair is not complete after code changes alone - regression evidence is
    mandatory. A "failed" result never advances to REGRESSION_TESTED: it either
    returns to REPAIR_PROPOSED for a new, explicitly-reasoned candidate (never an
    automatic retry) or, once the repair budget is exhausted, parks at
    INCONCLUSIVE."""
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "regression", {"REPAIRED"})
    _require(result in {"passed", "failed"}, f"unknown regression result: {result!r}")
    unknown = _check_evidence_refs(project, list(evidence_refs))
    if unknown:
        raise MethodologyValidationError(f"unknown evidence reference(s): {unknown}")

    attempt = {
        "result": result, "tests_executed": list(tests_executed), "gate_ids": list(gate_ids),
        "requirements_affected": list(requirements_affected), "evidence_refs": list(evidence_refs),
        "recorded_at": _now(), "actor_id": actor.strip(),
    }
    record["regression_attempts"].append(attempt)
    record["regression_refs"] = sorted(set(record["regression_refs"]) | set(evidence_refs))

    if result == "passed":
        record["current_state"] = "REGRESSION_TESTED"
        _append_history(record, "REGRESSION_PASSED", actor, reason)
    elif record["attempt_count"] >= record["max_repair_attempts"]:
        record["current_state"] = "INCONCLUSIVE"
        _append_history(record, "REGRESSION_FAILED_BUDGET_EXHAUSTED", actor, reason)
    else:
        record["current_state"] = "REPAIR_PROPOSED"
        _append_history(record, "REGRESSION_FAILED", actor, reason)
    return _save(project, record)


def record_revalidation(project: Path, failure_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    """Resolution requires revalidation under the CURRENT methodology/gate context -
    stale verification evidence is never reused. Reuses
    nogap_verify_binding.verification_acceptance_precondition() (the exact same
    check the M7-G decide interlock uses) rather than re-deriving staleness here."""
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "revalidation", {"REGRESSION_TESTED"})

    import nogap_verify_binding as vb

    precondition = vb.verification_acceptance_precondition(project, record.get("task_id"))
    attempt = {
        "satisfied": precondition["satisfied"], "reason": precondition["reason"],
        "recorded_at": _now(), "actor_id": actor.strip(),
    }
    record["revalidation_attempts"].append(attempt)
    if not precondition["satisfied"]:
        raise MethodologyValidationError(f"revalidation evidence is not current: {precondition['reason']}")

    record["revalidation_refs"] = sorted(set(record["revalidation_refs"]) | {record.get("task_id") or ""} - {""})
    record["current_state"] = "REVALIDATED"
    _append_history(record, "REVALIDATED", actor, reason)
    return _save(project, record)


def resolve_failure(project: Path, failure_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "resolution", {"REVALIDATED"})

    import nogap_verify_binding as vb

    precondition = vb.verification_acceptance_precondition(project, record.get("task_id"))
    if not precondition["satisfied"]:
        raise MethodologyValidationError(
            f"resolution blocked: revalidation evidence is no longer current: {precondition['reason']}"
        )

    if record.get("active_loop_id"):
        state, _definition = _require_state(project)
        loop = next((loop for loop in state["loops"] if loop["loop_id"] == record["active_loop_id"]), None)
        if loop and loop["status"] == "ACTIVE":
            resolve_loop(project, record["active_loop_id"], "RESOLVED", actor, f"failure {failure_id} resolved")

    record["resolution"] = {"status": "RESOLVED", "resolved_by": actor.strip(), "reason": reason.strip(), "resolved_at": _now()}
    record["current_state"] = "RESOLVED"
    _append_history(record, "RESOLVED", actor, reason)
    return _save(project, record)


def mark_inconclusive(project: Path, failure_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, "mark inconclusive", set(FAILURE_ORDER) - {"RESOLVED"})
    record["current_state"] = "INCONCLUSIVE"
    _append_history(record, "MARKED_INCONCLUSIVE", actor, reason)
    return _save(project, record)


def close_failure(project: Path, failure_id: str, *, status: str, actor: str, reason: str) -> dict[str, Any]:
    """REJECTED or ABANDONED - a negative terminal outcome, never pretending success.
    Never deletes the record; it remains permanently queryable."""
    _require(status in {"REJECTED", "ABANDONED"}, f"unknown close status: {status!r}")
    record = _load_or_raise(project, failure_id)
    _require_predecessor(record, f"close as {status}", (set(FAILURE_ORDER) | {"INCONCLUSIVE"}) - {"RESOLVED"})
    record["resolution"] = {"status": status, "resolved_by": actor.strip(), "reason": reason.strip(), "resolved_at": _now()}
    record["current_state"] = status
    _append_history(record, f"CLOSED_{status}", actor, reason)
    return _save(project, record)


def _load_or_raise(project: Path, failure_id: str) -> dict[str, Any]:
    record = load_failure(project, failure_id)
    if record is None:
        raise MethodologyValidationError(f"unknown failure_id: {failure_id}")
    definition = load_methodology()
    if record.get("methodology_version") != definition.version:
        raise MethodologyValidationError(
            f"failure {failure_id} was recorded under methodology v{record.get('methodology_version')}, "
            f"current is v{definition.version}"
        )
    return record
