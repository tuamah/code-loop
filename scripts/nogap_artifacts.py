#!/usr/bin/env python3
"""M7-E: executable pre-build lifecycle artifacts (P0-P11).

Turns DEFINE/RESEARCH/DESIGN/PREPARE from lifecycle labels into structured,
versioned records the MethodologyEngine can evaluate. Artifacts are facts,
never agent prose treated as authority: creation and every later read both
run the same validation (required fields present, references resolve to
real prior artifacts, profile-conditional requirements satisfied).

Storage: <project>/.code-loop/methodology/artifacts/<artifact_id>.json - a
directory deliberately separate from .code-loop/runtime/ (Trust Runtime
evidence) and from .code-loop/methodology/state.json (lifecycle state). One
file per artifact, matching every other object store in this codebase.

P11 (Golden Gates & Test Plan) is a PLAN, never a second gate authority: it
proposes required_commands/forbidden_paths in the same shape gate.rules
already uses, but nothing here ever writes to .code-loop/runtime/gates/ -
the Trust Runtime's frozen gate stays the sole authority during execution
and acceptance.

BUILD (P12) is out of scope here entirely - see prebuild_readiness() for the
one thing this module exposes toward it: whether P0-P11's obligations, for
the project's active profile, are currently satisfied. Nothing here wires
that readiness check into `nogap run` - that integration is M7-F.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from nogap_methodology import (
    MethodologyValidationError,
    PROFILE_ORDER,
    _effective_profile_for_phase,
    _now,
    _require,
    _require_state,
    _write_state,
    derive_profile,
    load_methodology,
    load_state,
    methodology_state_dir,
)

STRATEGY_OPTIONS = {"BUILD", "BUY", "ADOPT", "FORK", "INTEGRATE", "HYBRID"}
REQUIREMENT_STATUSES = {"ACTIVE", "SUPERSEDED", "REJECTED", "SATISFIED"}
ADR_STATUSES = {"PROPOSED", "ACCEPTED", "SUPERSEDED"}

# One entry per artifact type. `required_fields` applies at every profile; `profile_required_fields`
# adds MORE fields cumulatively as profile rises (LIGHT subset of STANDARD subset of STRICT) -
# never a different schema per profile, per instruction. `reference_fields` maps a field name to
# the artifact_type (or "P6_REQUIREMENT_ID" for the requirement_id-keyed special case) it must
# resolve against; every listed reference field is required to be a non-empty list.
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
        "profile_required_fields": {},
        "reference_fields": {},
    },
    "P11_GATE_PLAN": {
        "phase_id": "P11",
        "required_fields": ["gate_id", "required_tests", "evidence_requirements", "stop_conditions", "verification_depth", "requirement_refs", "required_commands", "forbidden_paths"],
        "profile_required_fields": {},
        "reference_fields": {"requirement_refs": "P6_REQUIREMENT_ID"},
    },
}

PHASE_TO_ARTIFACT_TYPE = {info["phase_id"]: name for name, info in ARTIFACT_TYPES.items()}
PREBUILD_PHASES = [f"P{n}" for n in range(12)]  # P0..P11


def artifacts_dir(project: Path) -> Path:
    return methodology_state_dir(project) / "artifacts"


def _cumulative_profile_fields(artifact_type: str, effective_profile: str) -> list[str]:
    info = ARTIFACT_TYPES[artifact_type]
    fields: list[str] = []
    for profile in ("STANDARD", "STRICT"):
        if PROFILE_ORDER[effective_profile] >= PROFILE_ORDER[profile]:
            fields.extend(info["profile_required_fields"].get(profile, []))
    return fields


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)):
        return len(value) == 0
    return False


def load_artifact(project: Path, artifact_id: str) -> dict[str, Any] | None:
    path = artifacts_dir(project) / f"{artifact_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MethodologyValidationError(f"{path} is invalid JSON: {exc}") from exc
    _require(isinstance(data, dict), f"{path}: artifact must be a JSON object")
    return data


def list_artifacts(project: Path, artifact_type: str | None = None, phase_id: str | None = None) -> list[dict[str, Any]]:
    directory = artifacts_dir(project)
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        records.append(data)
    if artifact_type:
        records = [r for r in records if r.get("artifact_type") == artifact_type]
    if phase_id:
        records = [r for r in records if r.get("phase_id") == phase_id]
    return records


def get_phase_artifacts(project: Path, phase_id: str) -> list[dict[str, Any]]:
    return list_artifacts(project, phase_id=phase_id)


def next_requirement_id(project: Path) -> str:
    existing = list_artifacts(project, artifact_type="P6_REQUIREMENT")
    max_n = 0
    for record in existing:
        req_id = record.get("fields", {}).get("requirement_id", "")
        if req_id.startswith("REQ-"):
            try:
                max_n = max(max_n, int(req_id[4:]))
            except ValueError:
                continue
    return f"REQ-{max_n + 1:03d}"


def _resolve_reference(project: Path, ref: str, target: str) -> bool:
    if target == "P6_REQUIREMENT_ID":
        return any(r.get("fields", {}).get("requirement_id") == ref for r in list_artifacts(project, artifact_type="P6_REQUIREMENT"))
    artifact = load_artifact(project, ref)
    return artifact is not None and artifact.get("artifact_type") == target


def _check_fields(artifact_type: str, fields: dict[str, Any], effective_profile: str) -> list[str]:
    info = ARTIFACT_TYPES[artifact_type]
    problems = []
    required = list(info["required_fields"]) + _cumulative_profile_fields(artifact_type, effective_profile)
    for key in required:
        if key not in fields or _is_empty(fields[key]):
            problems.append(f"missing or empty required field: {key}")
    return problems


def _check_references(project: Path, artifact_type: str, fields: dict[str, Any]) -> list[str]:
    info = ARTIFACT_TYPES[artifact_type]
    problems = []
    for field_name, target_type in info["reference_fields"].items():
        refs = fields.get(field_name)
        if _is_empty(refs):
            continue  # already reported by _check_fields since these are also required
        if not isinstance(refs, list):
            problems.append(f"{field_name} must be a list of references")
            continue
        for ref in refs:
            if not _resolve_reference(project, ref, target_type):
                problems.append(f"{field_name} references unknown {target_type}: {ref!r}")
    return problems


def validate_record(project: Path, record: dict[str, Any]) -> list[str]:
    """Returns a list of problems (empty = valid). Never raises - callers decide whether to
    treat problems as fatal (create_artifact) or as an accumulating readiness report."""
    problems: list[str] = []
    artifact_type = record.get("artifact_type")
    if artifact_type not in ARTIFACT_TYPES:
        return [f"unknown artifact_type: {artifact_type!r}"]

    definition = load_methodology()
    if record.get("methodology_version") != definition.version:
        problems.append(f"methodology version mismatch: artifact has {record.get('methodology_version')!r}, current is {definition.version!r}")

    expected_phase = ARTIFACT_TYPES[artifact_type]["phase_id"]
    if record.get("phase_id") != expected_phase:
        problems.append(f"artifact_type {artifact_type} belongs to {expected_phase}, not {record.get('phase_id')!r}")

    state = load_state(project)
    if state is None:
        problems.append("no methodology state; run 'nogap methodology init' first")
        return problems  # can't determine effective profile without state

    phase_contract = definition.get_phase(expected_phase)
    effective_profile = _effective_profile_for_phase(state, phase_contract)

    fields = record.get("fields", {})
    if not isinstance(fields, dict):
        return problems + ["artifact 'fields' must be an object"]
    problems.extend(_check_fields(artifact_type, fields, effective_profile))
    problems.extend(_check_references(project, artifact_type, fields))

    if artifact_type == "P5_STRATEGY_DECISION":
        strategy = fields.get("selected_strategy")
        if strategy is not None and strategy not in STRATEGY_OPTIONS:
            problems.append(f"selected_strategy must be one of {sorted(STRATEGY_OPTIONS)}, got {strategy!r}")

    if artifact_type == "P0_PROJECT_INTENT":
        intent_type = fields.get("intent_type")
        if intent_type is not None and intent_type != state.get("intent"):
            problems.append(
                f"intent_type {intent_type!r} does not match the project's methodology state intent "
                f"{state.get('intent')!r} - state.json is the canonical owner of intent"
            )

    return problems


def create_artifact(
    project: Path,
    artifact_type: str,
    fields: dict[str, Any],
    actor: str,
    *,
    artifact_id: str | None = None,
    status: str = "ACTIVE",
    source_refs: list[str] = (),
    decision_refs: list[str] = (),
    evidence_refs: list[str] = (),
    assumptions: list[str] = (),
    limitations: list[str] = (),
) -> dict[str, Any]:
    _require(artifact_type in ARTIFACT_TYPES, f"unknown artifact_type: {artifact_type!r}")
    _require(bool(actor and actor.strip()), "create_artifact requires a non-empty actor_id")
    definition = load_methodology()
    phase_id = ARTIFACT_TYPES[artifact_type]["phase_id"]

    artifact_id = artifact_id or f"{artifact_type.lower()}-{uuid.uuid4().hex[:12]}"
    if load_artifact(project, artifact_id) is not None:
        raise MethodologyValidationError(f"duplicate artifact_id: {artifact_id}")

    if artifact_type == "P6_REQUIREMENT":
        requirement_id = fields.get("requirement_id") or next_requirement_id(project)
        duplicate = any(
            r.get("fields", {}).get("requirement_id") == requirement_id
            for r in list_artifacts(project, artifact_type="P6_REQUIREMENT")
        )
        if duplicate:
            raise MethodologyValidationError(f"duplicate requirement_id: {requirement_id}")
        fields = {**fields, "requirement_id": requirement_id}
        status_history: list[dict[str, Any]] | None = [{"status": status, "actor_id": actor, "reason": "created", "changed_at": _now()}]
    else:
        status_history = None

    timestamp = _now()
    record: dict[str, Any] = {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "methodology_version": definition.version,
        "phase_id": phase_id,
        "schema_version": "1.0.0",
        "created_at": timestamp,
        "updated_at": timestamp,
        "actor_id": actor.strip(),
        "status": status,
        "source_refs": list(source_refs),
        "decision_refs": list(decision_refs),
        "evidence_refs": list(evidence_refs),
        "assumptions": list(assumptions),
        "limitations": list(limitations),
        "fields": fields,
    }
    if status_history is not None:
        record["status_history"] = status_history

    problems = validate_record(project, record)
    if problems:
        raise MethodologyValidationError(f"artifact rejected ({artifact_type}): " + "; ".join(problems))

    if artifact_type == "P2_SUCCESS_CRITERIA":
        _sync_risk_and_claim_from_p2(project, fields, actor)

    path = artifacts_dir(project) / f"{artifact_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def update_requirement_status(project: Path, requirement_id: str, new_status: str, actor: str, reason: str) -> dict[str, Any]:
    """Requirements are never deleted or silently overwritten: this appends to
    status_history and updates the current status field in place, preserving history."""
    _require(new_status in REQUIREMENT_STATUSES, f"unknown requirement status: {new_status!r}")
    _require(bool(actor and actor.strip()), "requirement status update requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "requirement status update requires a non-empty reason")
    matches = [r for r in list_artifacts(project, artifact_type="P6_REQUIREMENT") if r.get("fields", {}).get("requirement_id") == requirement_id]
    _require(bool(matches), f"unknown requirement_id: {requirement_id}")
    record = matches[0]
    record["status"] = new_status
    record.setdefault("status_history", []).append({"status": new_status, "actor_id": actor.strip(), "reason": reason.strip(), "changed_at": _now()})
    record["updated_at"] = _now()
    path = artifacts_dir(project) / f"{record['artifact_id']}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _sync_risk_and_claim_from_p2(project: Path, fields: dict[str, Any], actor: str) -> None:
    """P2 recomputes the project's profile derivation rather than allowing risk/claim to
    silently drift from what M7-B's state actually derives its profile from."""
    risk, claim_strength = fields.get("risk_level"), fields.get("claim_strength")
    if risk is None or claim_strength is None:
        return
    state, _definition = _require_state(project)
    if state["risk"] == risk and state["claim_strength"] == claim_strength:
        return  # already in sync, nothing to reconcile
    was_overridden = state["effective_profile"] != state["derived_profile"]
    new_derivation = derive_profile(state["intent"], risk, claim_strength)
    state["risk"], state["claim_strength"] = risk, claim_strength
    state["derived_profile"] = new_derivation.profile
    state["derivation"] = new_derivation.as_dict()
    if not was_overridden:
        state["effective_profile"] = new_derivation.profile
    state["updated_at"] = _now()
    _write_state(project, state)


def prebuild_readiness(project: Path) -> dict[str, Any]:
    """Whether P0-P11's obligations are satisfied for the project's active profile.
    Explains WHY when not: one reason string per missing/invalid obligation, never a bare
    "not ready". Not consulted by nogap run/execute - that wiring is M7-F."""
    state, definition = _require_state(project)
    missing: list[str] = []
    for phase_id in PREBUILD_PHASES:
        artifact_type = PHASE_TO_ARTIFACT_TYPE[phase_id]
        records = get_phase_artifacts(project, phase_id)
        # a requirement phase (P6) may have many records; every other phase needs at least one
        if not records:
            missing.append(f"{phase_id} ({artifact_type}): no artifact recorded")
            continue
        if artifact_type == "P6_REQUIREMENT":
            active = [r for r in records if r.get("status") == "ACTIVE" or r.get("status") == "SATISFIED"]
            if not active:
                missing.append(f"{phase_id} (P6_REQUIREMENT): no ACTIVE or SATISFIED requirement recorded")
        for record in records:
            problems = validate_record(project, record)
            missing.extend(f"{phase_id} ({record.get('artifact_id')}): {p}" for p in problems)

    return {
        "ready": not missing,
        "profile": state["effective_profile"],
        "current_phase": state["current_phase"],
        "missing": missing,
    }
