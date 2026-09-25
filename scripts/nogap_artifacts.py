#!/usr/bin/env python3
"""M7-E/M7-F: executable pre-build (P0-P11) and BUILD-entry (P12, P14) artifacts.

Turns DEFINE/RESEARCH/DESIGN/PREPARE/BUILD from lifecycle labels into structured,
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

P12 (Task Contract) is the canonical, structured record of what a BUILD
attempt is allowed to do - never a free-form agent prompt. P14 (Self-Check)
captures what the implementer observed about its own execution (changed
files, patch hash, process outcome, expected-effect result, limitations,
unresolved issues); its `self_check_authority` field is always forced to
"execution" here, never accepted from caller input, so it can never be
mistaken for or smuggled in as independent verification. P13 (the isolated
execution itself) has no artifact type of its own - it is represented by
the existing M6 execution evidence in .code-loop/runtime/, which P14
references by evidence_refs (see nogap_build.py for the actual binding).

Binding this registry's prebuild_readiness()/P12/P14 into `nogap run` so
that it causally gates execution is nogap_build.py's job (M7-F), kept in a
separate module deliberately: this file stays the artifact registry, that
one is where "may execution begin?" gets decided and enforced.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nogap_artifact_types import ARTIFACT_TYPES, PHASE_TO_ARTIFACT_TYPE, PHASE_TO_ARTIFACT_TYPES
from nogap_evidence_classes import EVIDENCE_CLASSES
from nogap_methodology import (
    CLAIM_STRENGTHS,
    MethodologyValidationError,
    PROFILE_ORDER,
    RISK_LEVELS,
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

# One entry per artifact type; the data itself lives in nogap_artifact_types.py (see that
# module's docstring for why) and is re-exported here so every existing
# nogap_artifacts.ARTIFACT_TYPES call site keeps working unchanged.
PREBUILD_PHASES = [f"P{n}" for n in range(12)]  # P0..P11

VERIFICATION_RESULT_STATUSES = {
    "VERIFICATION_PENDING", "VERIFICATION_IN_PROGRESS", "VERIFICATION_FAILED",
    "VERIFICATION_INCONCLUSIVE", "VERIFICATION_COMPLETE_AWAITING_DECISION",
}

# D6 (docs/d6-runtime-structure-contract.md, Rev 3): closed enums for P9_RUNTIME_STRUCTURE, taken
# verbatim from docs/nogapcode-runtime.md's own Planes and Authority Model sections - no new
# vocabulary invented here.
RUNTIME_STRUCTURE_PLANES = frozenset({
    "CONTROL_DECISION", "EXECUTION", "TOOL_CAPABILITY",
    "VERIFICATION_EVIDENCE", "STATE_EVENT", "OBSERVABILITY",
})
RUNTIME_STRUCTURE_AUTHORITY_ROLES = frozenset({"execution", "verification", "acceptance", "human", "tool"})
RUNTIME_STRUCTURE_BOUNDARY_TYPES = frozenset({"authority", "trust", "execution", "verification", "state"})
RUNTIME_STRUCTURE_ENFORCEMENT_STATUSES = frozenset({"ENFORCED", "DOCUMENTED_ONLY"})
RUNTIME_STRUCTURE_VERSIONS = frozenset({"1"})

# D6 sec 2.3: implementation_ref/enforcement_ref resolve against THIS repository (the runtime
# the contract describes is code-loop's own Trust Runtime, not whatever project happens to hold
# the artifact record) - nogap_artifacts.py lives in <repo>/scripts/, so its own grandparent is
# the repo root, matching the contract's "resolvable under scripts/" wording for the dotted form.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _runtime_structure_ref_resolves(ref: Any) -> bool:
    """D6 sec 2.3: existence-only guarantee, never a functional one. Repo-relative path form
    (rejects absolute paths and '..' traversal) or dotted-module form resolved to a real .py
    file directly under scripts/ - the dotted form only proves the top-level module exists, not
    that any attribute after the first '.' does, matching the contract's own limitation."""
    if not isinstance(ref, str) or not ref:
        return False
    normalized = ref.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("~"):
        return False
    if any(part == ".." for part in normalized.split("/")):
        return False
    if "/" in normalized:
        return (_REPO_ROOT / normalized).exists()
    module_name = normalized.split(".", 1)[0]
    if not module_name or not all(c.isalnum() or c == "_" for c in module_name):
        return False
    return (_REPO_ROOT / "scripts" / f"{module_name}.py").is_file()


def _check_runtime_structure_schema(fields: dict[str, Any]) -> list[str]:
    """D6 (docs/d6-runtime-structure-contract.md, Rev 3): P9_RUNTIME_STRUCTURE's own nested
    schema, enum, uniqueness, endpoint, version, ref-syntax, authority-conflict and
    plane-coverage invariants. Schema-level only, runs on every validate_record call (creation
    and prebuild_readiness) - this enforces the already-frozen contract, it never defines one; a
    RUNTIME_STRUCTURE required_kinds resolver remains a separate, not-yet-authorized step."""
    problems: list[str] = []

    version = fields.get("runtime_structure_version")
    if version is not None and version not in RUNTIME_STRUCTURE_VERSIONS:
        problems.append(
            f"runtime_structure_version must be one of {sorted(RUNTIME_STRUCTURE_VERSIONS)}, got {version!r}"
        )

    plane_status = fields.get("plane_status")
    plane_status_valid = isinstance(plane_status, dict)
    if plane_status is not None and not plane_status_valid:
        problems.append("plane_status must be an object mapping each Plane to an EnforcementStatus")
    elif plane_status_valid:
        if set(plane_status.keys()) != RUNTIME_STRUCTURE_PLANES:
            problems.append(
                f"plane_status keys must be exactly {sorted(RUNTIME_STRUCTURE_PLANES)}, "
                f"got {sorted(plane_status.keys())}"
            )
        bad_values = {p: s for p, s in plane_status.items() if s not in RUNTIME_STRUCTURE_ENFORCEMENT_STATUSES}
        if bad_values:
            problems.append(
                f"plane_status values must be one of {sorted(RUNTIME_STRUCTURE_ENFORCEMENT_STATUSES)}, "
                f"got {bad_values!r}"
            )

    components = fields.get("components")
    if components is not None and not isinstance(components, list):
        problems.append("components must be a list")
        components = []
    components = [c for c in (components or []) if isinstance(c, dict)]
    for entry in (fields.get("components") or []):
        if not isinstance(entry, dict):
            problems.append(f"components entry must be an object, got {entry!r}")

    boundaries = fields.get("boundaries")
    if boundaries is not None and not isinstance(boundaries, list):
        problems.append("boundaries must be a list")
        boundaries = []
    boundaries = [b for b in (boundaries or []) if isinstance(b, dict)]
    for entry in (fields.get("boundaries") or []):
        if not isinstance(entry, dict):
            problems.append(f"boundaries entry must be an object, got {entry!r}")

    component_ids: list[str] = []
    component_by_id: dict[str, dict[str, Any]] = {}
    for entry in components:
        cid = entry.get("component_id")
        plane = entry.get("plane")
        impl_ref = entry.get("implementation_ref")
        roles = entry.get("authority_roles")

        if not isinstance(cid, str) or not cid:
            problems.append(f"component missing a non-empty component_id: {entry!r}")
        else:
            component_ids.append(cid)
            component_by_id[cid] = entry

        if plane is not None and plane not in RUNTIME_STRUCTURE_PLANES:
            problems.append(f"component {cid!r} plane must be one of {sorted(RUNTIME_STRUCTURE_PLANES)}, got {plane!r}")

        if not _runtime_structure_ref_resolves(impl_ref):
            problems.append(f"component {cid!r} implementation_ref does not resolve to a real path: {impl_ref!r}")

        if not isinstance(roles, list) or not roles:
            problems.append(f"component {cid!r} authority_roles must be a non-empty list")
        else:
            bad_roles = [r for r in roles if r not in RUNTIME_STRUCTURE_AUTHORITY_ROLES]
            if bad_roles:
                problems.append(f"component {cid!r} authority_roles has unknown role(s) {bad_roles!r}")
            if "execution" in roles and "acceptance" in roles:
                problems.append(f"component {cid!r} authority_roles must not contain both execution and acceptance")

    dup_components = sorted({cid for cid in component_ids if component_ids.count(cid) > 1})
    if dup_components:
        problems.append(f"duplicate component_id(s): {dup_components}")

    boundary_ids: list[str] = []
    for entry in boundaries:
        bid = entry.get("boundary_id")
        source = entry.get("source_component_id")
        target = entry.get("target_component_id")
        boundary_type = entry.get("boundary_type")
        flows = entry.get("permitted_flows")
        enforcement_status = entry.get("enforcement_status")
        enforcement_ref = entry.get("enforcement_ref")

        if not isinstance(bid, str) or not bid:
            problems.append(f"boundary missing a non-empty boundary_id: {entry!r}")
        else:
            boundary_ids.append(bid)

        if source not in component_by_id:
            problems.append(f"boundary {bid!r} source_component_id {source!r} does not resolve to a declared component")
        if target not in component_by_id:
            problems.append(f"boundary {bid!r} target_component_id {target!r} does not resolve to a declared component")

        if boundary_type is not None and boundary_type not in RUNTIME_STRUCTURE_BOUNDARY_TYPES:
            problems.append(
                f"boundary {bid!r} boundary_type must be one of {sorted(RUNTIME_STRUCTURE_BOUNDARY_TYPES)}, "
                f"got {boundary_type!r}"
            )

        if not isinstance(flows, list) or not flows:
            problems.append(f"boundary {bid!r} permitted_flows must be a non-empty list")

        if enforcement_status is not None and enforcement_status not in RUNTIME_STRUCTURE_ENFORCEMENT_STATUSES:
            problems.append(
                f"boundary {bid!r} enforcement_status must be one of "
                f"{sorted(RUNTIME_STRUCTURE_ENFORCEMENT_STATUSES)}, got {enforcement_status!r}"
            )
        elif enforcement_status == "ENFORCED":
            if not _runtime_structure_ref_resolves(enforcement_ref):
                problems.append(f"boundary {bid!r} is ENFORCED but enforcement_ref does not resolve: {enforcement_ref!r}")
        elif enforcement_status == "DOCUMENTED_ONLY" and enforcement_ref is not None:
            problems.append(
                f"boundary {bid!r} is DOCUMENTED_ONLY but declares a non-null enforcement_ref "
                f"{enforcement_ref!r} - must be null"
            )

    dup_boundaries = sorted({bid for bid in boundary_ids if boundary_ids.count(bid) > 1})
    if dup_boundaries:
        problems.append(f"duplicate boundary_id(s): {dup_boundaries}")

    # D6 Rev 3, V-PLANE-COVERAGE: biconditional between plane_status[p] == ENFORCED and a real,
    # resolvable component declaring plane == p - checked only once plane_status itself is
    # well-formed (avoids compounding an already-reported malformed-plane_status problem).
    if plane_status_valid and set(plane_status.keys()) == RUNTIME_STRUCTURE_PLANES:
        for plane in RUNTIME_STRUCTURE_PLANES:
            backing = [
                c for c in components
                if c.get("plane") == plane and _runtime_structure_ref_resolves(c.get("implementation_ref"))
            ]
            status = plane_status.get(plane)
            if status == "ENFORCED" and not backing:
                problems.append(
                    f"plane_status[{plane!r}] is ENFORCED but no component declares that plane "
                    f"with a resolvable implementation_ref"
                )
            if status == "DOCUMENTED_ONLY" and backing:
                problems.append(
                    f"plane_status[{plane!r}] is DOCUMENTED_ONLY but a real, resolvable component "
                    f"({[c.get('component_id') for c in backing]!r}) declares that plane - mark it "
                    f"ENFORCED instead"
                )

        # D6 Rev 3, V-VERIFIER-INDEPENDENCE: conditioned on VERIFICATION_EVIDENCE's own status,
        # never unconditional - see docs/d6-runtime-structure-contract.md sec 3 item 7.
        if plane_status.get("VERIFICATION_EVIDENCE") == "ENFORCED":
            verifier_evidence_components = [c for c in components if c.get("plane") == "VERIFICATION_EVIDENCE"]
            verifier_components = [
                c for c in verifier_evidence_components
                if "verification" in (c.get("authority_roles") or [])
            ]
            if not verifier_components:
                problems.append(
                    "plane_status['VERIFICATION_EVIDENCE'] is ENFORCED but no component with "
                    "plane == VERIFICATION_EVIDENCE holds the verification authority role"
                )
            for c in verifier_components:
                roles = c.get("authority_roles") or []
                cid = c.get("component_id")
                if "execution" in roles:
                    problems.append(f"component {cid!r} holds both verification and execution - not independent")
                if "acceptance" in roles and "human" not in roles:
                    problems.append(
                        f"component {cid!r} holds verification and acceptance without human - collapses "
                        f"independent verification into self-acceptance"
                    )

    return problems

# Stable, monotonically-increasing ID namespaces distinct from the generic artifact_id -
# never reused, checked for uniqueness whether auto-generated or explicitly supplied.
# Maps artifact_type -> (field_name, id_prefix).
_STABLE_ID_FIELDS: dict[str, tuple[str, str]] = {
    "P6_REQUIREMENT": ("requirement_id", "REQ"),
    "P12_TASK_CONTRACT": ("task_id", "TASK"),
    "P15_VERIFICATION_PLAN": ("verification_plan_id", "VPLAN"),
    "P18_VERIFICATION_RESULT": ("verification_run_id", "VRUN"),
}


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


def _next_sequence(project: Path) -> int:
    """Per-project monotonic write counter, recorded on every artifact.

    created_at cannot order two artifacts written in the same clock tick, and the
    artifact_id carries a random uuid, so file listing order is not chronology. The
    sequence is the tie-break that makes "which one is current?" a fact on disk
    instead of an accident of the filesystem. Artifacts written before this field
    existed report -1 and fall back to timestamp-only ordering - the behaviour they
    already had, never worse."""
    highest = -1
    for record in list_artifacts(project):
        value = record.get("sequence")
        if isinstance(value, int):
            highest = max(highest, value)
    return highest + 1


def _parse_timestamp(value: Any) -> datetime:
    """Parsed, never string-compared: ISO timestamps of different precision do not
    sort lexicographically ('...:19.5Z' < '...:19Z' because '.' < 'Z'), so a newer
    microsecond stamp would lose to an older whole-second one. Unparsable or missing
    stamps sort oldest so they can never win a "latest" lookup."""
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def order_key(record: dict[str, Any], timestamp_field: str = "created_at") -> tuple[datetime, int]:
    """Chronological sort key for records: parsed timestamp, then write sequence."""
    sequence = record.get("sequence")
    return (_parse_timestamp(record.get(timestamp_field)), sequence if isinstance(sequence, int) else -1)


def latest(records: list[dict[str, Any]], timestamp_field: str = "created_at") -> dict[str, Any] | None:
    """The chronologically newest record, or None when there is none.

    Use this instead of max(..., key=lambda r: r["created_at"]): max() returns the
    FIRST of equal keys, which on an artifact listing means the one whose random uuid
    happened to sort first. Remaining ties resolve to the last element of the input,
    so an append-ordered list still yields its newest entry."""
    if not records:
        return None
    return max(enumerate(records), key=lambda pair: (order_key(pair[1], timestamp_field), pair[0]))[1]


def _next_stable_id(project: Path, artifact_type: str, id_field: str, prefix: str) -> str:
    existing = list_artifacts(project, artifact_type=artifact_type)
    max_n = 0
    for record in existing:
        stable_id = record.get("fields", {}).get(id_field, "")
        if stable_id.startswith(f"{prefix}-"):
            try:
                max_n = max(max_n, int(stable_id[len(prefix) + 1:]))
            except ValueError:
                continue
    return f"{prefix}-{max_n + 1:03d}"


def next_requirement_id(project: Path) -> str:
    return _next_stable_id(project, "P6_REQUIREMENT", *_STABLE_ID_FIELDS["P6_REQUIREMENT"])


def next_task_id(project: Path) -> str:
    return _next_stable_id(project, "P12_TASK_CONTRACT", *_STABLE_ID_FIELDS["P12_TASK_CONTRACT"])


def next_verification_plan_id(project: Path) -> str:
    return _next_stable_id(project, "P15_VERIFICATION_PLAN", *_STABLE_ID_FIELDS["P15_VERIFICATION_PLAN"])


def next_verification_run_id(project: Path) -> str:
    return _next_stable_id(project, "P18_VERIFICATION_RESULT", *_STABLE_ID_FIELDS["P18_VERIFICATION_RESULT"])


def _resolve_reference(project: Path, ref: str, target: str) -> bool:
    if target == "P6_REQUIREMENT_ID":
        return any(r.get("fields", {}).get("requirement_id") == ref for r in list_artifacts(project, artifact_type="P6_REQUIREMENT"))
    artifact = load_artifact(project, ref)
    return artifact is not None and artifact.get("artifact_type") == target


def _check_fields(artifact_type: str, fields: dict[str, Any], effective_profile: str) -> list[str]:
    info = ARTIFACT_TYPES[artifact_type]
    problems = []
    required = list(info["required_fields"]) + _cumulative_profile_fields(artifact_type, effective_profile)
    # A required field ordinarily means "present AND non-empty". allow_empty_fields names the
    # closed, per-type exception: "present" is still mandatory (an absent field is still
    # rejected), but an empty value (e.g. []) is legitimate content, not a missing requirement.
    allow_empty = info.get("allow_empty_fields", frozenset())
    for key in required:
        if key not in fields or fields[key] is None:
            problems.append(f"missing or empty required field: {key}")
        elif key not in allow_empty and _is_empty(fields[key]):
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

    for owner, field in (("P11_GATE_PLAN", "evidence_requirements"),
                         ("P15_VERIFICATION_PLAN", "required_evidence_kinds")):
        if artifact_type == owner and isinstance(fields.get(field), list):
            unknown = [v for v in fields[field] if v not in EVIDENCE_CLASSES]
            if unknown:
                problems.append(f"{field} values must be in {sorted(EVIDENCE_CLASSES)}, got unknown {unknown!r}")

    if artifact_type == "P5_STRATEGY_DECISION":
        strategy = fields.get("selected_strategy")
        if strategy is not None and strategy not in STRATEGY_OPTIONS:
            problems.append(f"selected_strategy must be one of {sorted(STRATEGY_OPTIONS)}, got {strategy!r}")

    if artifact_type == "P2_SUCCESS_CRITERIA":
        risk = fields.get("risk_level")
        if risk is not None and risk not in RISK_LEVELS:
            problems.append(f"risk_level must be one of {sorted(RISK_LEVELS)}, got {risk!r}")
        claim_strength = fields.get("claim_strength")
        if claim_strength is not None and claim_strength not in CLAIM_STRENGTHS:
            problems.append(f"claim_strength must be one of {sorted(CLAIM_STRENGTHS)}, got {claim_strength!r}")

    if artifact_type == "P0_PROJECT_INTENT":
        intent_type = fields.get("intent_type")
        if intent_type is not None and intent_type != state.get("intent"):
            problems.append(
                f"intent_type {intent_type!r} does not match the project's methodology state intent "
                f"{state.get('intent')!r} - state.json is the canonical owner of intent"
            )

    if artifact_type == "P12_TASK_CONTRACT":
        criteria = fields.get("acceptance_criteria")
        if isinstance(criteria, list):
            malformed = [c for c in criteria if not isinstance(c, str) or not c.strip()]
            if malformed:
                problems.append(f"acceptance_criteria must be a list of non-empty strings, found: {malformed!r}")
        requirement_refs = fields.get("requirement_refs") or []
        allow_non_active = bool(fields.get("allow_non_active_requirement_refs", False))
        if not allow_non_active and isinstance(requirement_refs, list):
            requirements = list_artifacts(project, artifact_type="P6_REQUIREMENT")
            for ref in requirement_refs:
                matches = [r for r in requirements if r.get("fields", {}).get("requirement_id") == ref]
                if matches and matches[0].get("status") in {"SUPERSEDED", "REJECTED"}:
                    problems.append(
                        f"requirement_refs references {matches[0]['status']} requirement {ref!r}; "
                        f"set allow_non_active_requirement_refs=true to reference it explicitly"
                    )

    if artifact_type in {"P14_SELF_CHECK", "P15_VERIFICATION_PLAN", "P18_VERIFICATION_RESULT"}:
        task_id = fields.get("task_id")
        if task_id is not None:
            known = any(
                r.get("fields", {}).get("task_id") == task_id
                for r in list_artifacts(project, artifact_type="P12_TASK_CONTRACT")
            )
            if not known:
                problems.append(f"task_id references unknown P12_TASK_CONTRACT: {task_id!r}")

    if artifact_type == "P9_RUNTIME_STRUCTURE":
        problems.extend(_check_runtime_structure_schema(fields))

    if artifact_type == "P18_VERIFICATION_RESULT":
        plan_id = fields.get("verification_plan_id")
        if plan_id is not None:
            known = any(
                r.get("fields", {}).get("verification_plan_id") == plan_id
                for r in list_artifacts(project, artifact_type="P15_VERIFICATION_PLAN")
            )
            if not known:
                problems.append(f"verification_plan_id references unknown P15_VERIFICATION_PLAN: {plan_id!r}")
        result_status = record.get("status")
        if result_status is not None and result_status not in VERIFICATION_RESULT_STATUSES:
            problems.append(f"status must be one of {sorted(VERIFICATION_RESULT_STATUSES)}, got {result_status!r}")

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

    if artifact_type in _STABLE_ID_FIELDS:
        id_field, id_prefix = _STABLE_ID_FIELDS[artifact_type]
        stable_id = fields.get(id_field) or _next_stable_id(project, artifact_type, id_field, id_prefix)
        duplicate = any(
            r.get("fields", {}).get(id_field) == stable_id
            for r in list_artifacts(project, artifact_type=artifact_type)
        )
        if duplicate:
            raise MethodologyValidationError(f"duplicate {id_field}: {stable_id}")
        fields = {**fields, id_field: stable_id}
        status_history: list[dict[str, Any]] | None = [{"status": status, "actor_id": actor, "reason": "created", "changed_at": _now()}]
    else:
        status_history = None

    if artifact_type == "P14_SELF_CHECK":
        # Never mark P14 as verified acceptance: authority is forced, not accepted from input,
        # so a caller cannot smuggle "verification" in here by setting the field themselves.
        fields = {**fields, "self_check_authority": "execution"}

    timestamp = _now()
    record: dict[str, Any] = {
        "artifact_id": artifact_id,
        "sequence": _next_sequence(project),
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


def update_verification_result(
    project: Path,
    verification_run_id: str,
    actor: str,
    reason: str,
    *,
    status: str | None = None,
    field_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A P18_VERIFICATION_RESULT is one evolving record across P16/P17/P18, never a new
    artifact per phase - updated in place with an append-only status_history, mirroring
    update_requirement_status. Re-validates after the update so a caller cannot silently
    write the record into an invalid state (e.g. an unknown status)."""
    _require(bool(actor and actor.strip()), "verification result update requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "verification result update requires a non-empty reason")
    matches = [
        r for r in list_artifacts(project, artifact_type="P18_VERIFICATION_RESULT")
        if r.get("fields", {}).get("verification_run_id") == verification_run_id
    ]
    _require(bool(matches), f"unknown verification_run_id: {verification_run_id}")
    record = matches[0]
    if status is not None:
        _require(status in VERIFICATION_RESULT_STATUSES, f"unknown verification status: {status!r}")
        record["status"] = status
    if field_updates:
        record["fields"] = {**record["fields"], **field_updates}
    record.setdefault("status_history", []).append({
        "status": record["status"], "actor_id": actor.strip(), "reason": reason.strip(), "changed_at": _now(),
    })
    record["updated_at"] = _now()
    problems = validate_record(project, record)
    if problems:
        raise MethodologyValidationError(f"verification result update rejected: " + "; ".join(problems))
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


def _enforced_artifact_types() -> frozenset[str]:
    """D6-PRE-B REPAIR: ownership (PHASE_TO_ARTIFACT_TYPES) is never obligation on its own.
    A type existing under a phase only means it CAN be created and validated there - whether a
    record of it is REQUIRED for readiness is decided by the methodology's own required_kinds
    map (the phase contract's actual required-artifact semantics), never inferred from the
    ownership map itself. A type backing only a currently-DEFERRED kind (e.g.
    P9_RUNTIME_STRUCTURE while RUNTIME_STRUCTURE is deferred) is real, creatable, and
    independently validatable, but its absence is not yet a readiness blocker - that starts
    the moment its kind moves to ENFORCED_KINDS, and nowhere else."""
    from nogap_required_kinds import ENFORCED_KINDS

    return frozenset(
        spec.artifact_type for spec in ENFORCED_KINDS.values() if hasattr(spec, "artifact_type")
    )


def prebuild_readiness(project: Path) -> dict[str, Any]:
    """Whether P0-P11's obligations are satisfied for the project's active profile.
    Explains WHY when not: one reason string per missing/invalid obligation, never a bare
    "not ready". Not consulted by nogap run/execute - that wiring is M7-F."""
    state, definition = _require_state(project)
    required_types = _enforced_artifact_types()
    missing: list[str] = []
    for phase_id in PREBUILD_PHASES:
        # D6-PRE-A: a phase may own more than one artifact type (P9). Index by the real 1:N
        # ownership map directly - an unknown phase_id fails closed with a plain KeyError rather
        # than being silently skipped.
        artifact_types = PHASE_TO_ARTIFACT_TYPES[phase_id]
        for artifact_type in artifact_types:
            records = list_artifacts(project, artifact_type=artifact_type, phase_id=phase_id)
            # a requirement phase (P6) may have many records; every other required type needs
            # at least one. An owned-but-not-yet-required type (its kind still DEFERRED) is
            # simply skipped when absent - it is real, just not yet obligatory.
            if not records:
                if artifact_type in required_types:
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
