#!/usr/bin/env python3
"""M7-K: Lifecycle - Release Candidate & Freeze (P19), Release Readiness & Deployment
(P20), Production Observation & Incident Handling (P21), Evidence-Driven Improvement
(P22), and Lifecycle Decision (P23).

CRITICAL INVARIANT, enforced structurally throughout: verification PASS, research
SUPPORTED, deployment SUCCEEDED, and the absence of an incident/failure record are
never, by themselves, converted into a stronger claim than what was actually
observed. Concretely:
  - evaluate_release_readiness() can only ever return READY_FOR_DECISION, never
    ACCEPT - nothing here writes a decision record or calls nogap.py's decide path.
  - create_deployment()/record_deployment_result() record execution facts
    (SUCCEEDED/FAILED/...) - never "production healthy".
  - get_operational_status()/compute_operational_status() return UNKNOWN when no
    observations exist, never HEALTHY - health is only ever derived from actual,
    referenced observations evaluated against explicit criteria, never inferred from
    deployment status or incident absence.
  - link_incident_failure()/set_incident_status() never let an incident be marked
    RESOLVED while its linked M7-H FailureRecord's own current_state isn't actually
    RESOLVED - this module never reimplements repair-lifecycle judgment, it only
    reads nogap_failure.load_failure()'s real state.

SINGLE-OWNER RULE (the exact lesson from the M7-J review fix, applied from the
start): every "which record is current" decision has exactly one pure implementation
here - select_current_release_candidate(), select_current_release_readiness(),
select_current_lifecycle_decision(), and compute_operational_status() - each taking
an already-loaded list and returning a decision, never touching disk. The public,
disk-reading API (get_current_release_candidate(), get_current_release_readiness(),
get_current_lifecycle_decision(), get_operational_status()) are thin wrappers around
these. nogap_memory.py calls the SAME pure functions on its own already-collected
records; it never re-derives the selection rule.

Like M7-I/M7-J, this module follows the stricter malformed-record convention:
list_* functions raise on unparseable JSON rather than silently skipping it.

Ordering never trusts filesystem listing order or created_at alone (1-second
resolution makes same-second collisions real): every record type gets an
engine-assigned monotonic `sequence` at creation time, and current-selection is
sequence-based with CONFLICT (never an arbitrary pick) on a genuine tie.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from nogap_artifacts import load_artifact
from nogap_methodology import (
    MethodologyValidationError,
    _now,
    _require,
    can_transition,
    load_methodology,
    load_state,
    methodology_state_dir,
    transition,
)

SCHEMA_VERSION = "1.0.0"

# --- vocabularies -----------------------------------------------------------

RC_STATUSES = {"DRAFT", "ASSEMBLED", "FROZEN", "INVALIDATED", "SUPERSEDED", "ABANDONED"}
RC_TERMINAL = {"INVALIDATED", "SUPERSEDED", "ABANDONED"}
RC_CRITICAL_FIELDS = {
    "version", "candidate_ref", "code_revision", "included_task_refs",
    "included_requirement_refs", "artifact_refs", "evidence_refs", "verification_refs",
}

READINESS_OUTCOMES = {"READY_FOR_DECISION", "NOT_READY", "INCONCLUSIVE", "STALE"}

DEPLOYMENT_STATUSES = {"PLANNED", "STARTED", "SUCCEEDED", "FAILED", "ROLLED_BACK", "CANCELLED", "INCONCLUSIVE"}
DEPLOYMENT_TERMINAL = {"SUCCEEDED", "FAILED", "ROLLED_BACK", "CANCELLED"}

OPERATIONAL_HEALTH_STATUSES = {"HEALTHY", "DEGRADED", "UNHEALTHY", "INCONCLUSIVE", "UNKNOWN"}

INCIDENT_STATUSES = {"OPEN", "TRIAGED", "LINKED_TO_FAILURE", "MITIGATED", "RESOLVED", "INCONCLUSIVE", "CLOSED"}
INCIDENT_TERMINAL = {"RESOLVED", "CLOSED"}

IMPROVEMENT_STATUSES = {
    "PROPOSED", "SUPPORTED", "SELECTED", "REENTERED", "IMPLEMENTED", "VALIDATED",
    "REJECTED", "DEFERRED", "INCONCLUSIVE", "ABANDONED",
}
IMPROVEMENT_TERMINAL = {"VALIDATED", "REJECTED", "ABANDONED"}
IMPROVEMENT_CATEGORIES = {
    "REQUIREMENT", "ARCHITECTURE", "IMPLEMENTATION", "VERIFICATION", "RESEARCH",
    "RELEASE", "OPERATIONS", "COST", "RELIABILITY", "SECURITY", "PERFORMANCE",
    "MAINTAINABILITY", "OTHER",
}
# Candidate target phase(s), most-direct first - a PROPOSAL vocabulary, not a
# promise of legality. reenter_for_improvement() dry-runs can_transition() and fails
# closed, honestly, exactly where M7-C's own P22.allowed_back_transitions (currently
# only P1/P6/P7/P21) does not cover a category - the graph is never broadened here
# to make a category "work".
IMPROVEMENT_ROUTING_MAP: dict[str, tuple[str, ...]] = {
    "REQUIREMENT": ("P6",),
    "ARCHITECTURE": ("P7", "P8"),
    "IMPLEMENTATION": ("P12", "P13"),
    "VERIFICATION": ("P15", "P16", "P17", "P18"),
    "RESEARCH": ("P3", "P4", "P5"),
    "RELEASE": ("P19", "P20"),
    "OPERATIONS": ("P21",),
    "COST": (), "RELIABILITY": (), "SECURITY": (), "PERFORMANCE": (),
    "MAINTAINABILITY": (), "OTHER": (),
}

LIFECYCLE_OUTCOMES = {"CONTINUE", "MAINTAIN", "IMPROVE", "REENTER", "SUSPEND", "RETIRE", "ARCHIVE", "INCONCLUSIVE"}
LIFECYCLE_IRREVERSIBLE_OUTCOMES = {"RETIRE", "ARCHIVE"}
# Deliberately "human" only, NOT the broader ACCEPTANCE_AUTHORITIES-style set:
# nogap.py's own "acceptance" authority_class is a bare, self-asserted CLI flag
# (`nogap decide --authority acceptance`, defaulted, with no check anywhere in this
# codebase that the caller is actually a human) - it is proven NOT equivalent to
# genuine Human Owner authorization. "human" is the one value in
# nogap_methodology.TRANSITION_AUTHORITY_CLASSES that this codebase already uses
# specifically to denote a human owner (see e.g. P19/P20/P23's own required_roles:
# ["human_owner"]); reusing it here is the existing vocabulary, not new IAM.
LIFECYCLE_IRREVERSIBLE_AUTHORITIES = {"human"}

_ID_PREFIXES = {
    "release_candidates": "RC", "release_readiness": "RDY", "deployments": "DEPLOY",
    "operations": "OPSOBS", "incidents": "INC", "improvements": "IMP", "lifecycle_decisions": "LCD",
}
_ID_FIELDS = {
    "release_candidates": "release_candidate_id", "release_readiness": "readiness_id",
    "deployments": "deployment_id", "operations": "observation_id", "incidents": "incident_id",
    "improvements": "improvement_id", "lifecycle_decisions": "lifecycle_decision_id",
}


# --- storage -----------------------------------------------------------------

def lifecycle_dir(project: Path) -> Path:
    return methodology_state_dir(project) / "lifecycle"


def _kind_dir(project: Path, kind: str) -> Path:
    return lifecycle_dir(project) / kind


def _load_json_dir_strict(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MethodologyValidationError(f"lifecycle: unreadable/malformed record {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise MethodologyValidationError(f"lifecycle: record {path} must contain a JSON object")
        records.append(data)
    return records


def _next_id(project: Path, kind: str) -> str:
    prefix = _ID_PREFIXES[kind]
    max_n = 0
    for record in _load_json_dir_strict(_kind_dir(project, kind)):
        rid = record.get(_ID_FIELDS[kind], "")
        if isinstance(rid, str) and rid.startswith(f"{prefix}-"):
            try:
                max_n = max(max_n, int(rid[len(prefix) + 1:]))
            except ValueError:
                continue
    return f"{prefix}-{max_n + 1:03d}"


def _next_sequence(project: Path, kind: str, scope_field: str | None = None, scope_value: Any = None) -> int:
    records = _load_json_dir_strict(_kind_dir(project, kind))
    if scope_field is not None:
        records = [r for r in records if r.get(scope_field) == scope_value]
    return len(records) + 1


def _save(project: Path, kind: str, record: dict[str, Any], id_field: str) -> dict[str, Any]:
    path = _kind_dir(project, kind) / f"{record[id_field]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _append_history(record: dict[str, Any], action: str, actor: str, reason: str, **extra: Any) -> None:
    entry = {"action": action, "actor_id": actor.strip(), "reason": reason.strip(), "changed_at": _now()}
    entry.update(extra)
    record.setdefault("history", []).append(entry)
    record["updated_at"] = entry["changed_at"]


def _require_actor_reason(actor: str, reason: str, label: str) -> None:
    _require(bool(actor and actor.strip()), f"{label} requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), f"{label} requires a non-empty reason")


# --- generic load/list ---------------------------------------------------------

def _load_one(project: Path, kind: str, record_id: str) -> dict[str, Any] | None:
    path = _kind_dir(project, kind) / f"{record_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MethodologyValidationError(f"lifecycle: {path} is invalid JSON: {exc}") from exc
    _require(isinstance(data, dict), f"lifecycle: {path} must be a JSON object")
    return data


def _load_or_raise(project: Path, kind: str, record_id: str, label: str) -> dict[str, Any]:
    record = _load_one(project, kind, record_id)
    if record is None:
        raise MethodologyValidationError(f"lifecycle: unknown {label} {record_id!r}")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise MethodologyValidationError(
            f"lifecycle: {label} {record_id!r} has unsupported schema_version {record.get('schema_version')!r}"
        )
    definition = load_methodology()
    if record.get("methodology_version") != definition.version:
        raise MethodologyValidationError(
            f"lifecycle: {label} {record_id!r} was recorded under methodology v{record.get('methodology_version')}, "
            f"current is v{definition.version}"
        )
    return record


def load_release_candidate(project: Path, release_candidate_id: str) -> dict[str, Any] | None:
    return _load_one(project, "release_candidates", release_candidate_id)


def list_release_candidates(project: Path) -> list[dict[str, Any]]:
    return _load_json_dir_strict(_kind_dir(project, "release_candidates"))


def load_release_readiness(project: Path, readiness_id: str) -> dict[str, Any] | None:
    return _load_one(project, "release_readiness", readiness_id)


def list_release_readiness(project: Path, release_candidate_id: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "release_readiness"))
    if release_candidate_id is not None:
        records = [r for r in records if r.get("release_candidate_id") == release_candidate_id]
    return records


def load_deployment(project: Path, deployment_id: str) -> dict[str, Any] | None:
    return _load_one(project, "deployments", deployment_id)


def list_deployments(project: Path, release_candidate_id: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "deployments"))
    if release_candidate_id is not None:
        records = [r for r in records if r.get("release_candidate_id") == release_candidate_id]
    return records


def load_operational_observation(project: Path, observation_id: str) -> dict[str, Any] | None:
    return _load_one(project, "operations", observation_id)


def list_operational_observations(project: Path, deployment_id: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "operations"))
    if deployment_id is not None:
        records = [r for r in records if r.get("deployment_id") == deployment_id]
    return records


def load_incident(project: Path, incident_id: str) -> dict[str, Any] | None:
    return _load_one(project, "incidents", incident_id)


def list_incidents(project: Path, deployment_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "incidents"))
    if deployment_id is not None:
        records = [r for r in records if r.get("deployment_id") == deployment_id]
    if status is not None:
        records = [r for r in records if r.get("status") == status]
    return records


def load_improvement(project: Path, improvement_id: str) -> dict[str, Any] | None:
    return _load_one(project, "improvements", improvement_id)


def list_improvements(project: Path, status: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "improvements"))
    if status is not None:
        records = [r for r in records if r.get("status") == status]
    return records


def load_lifecycle_decision(project: Path, lifecycle_decision_id: str) -> dict[str, Any] | None:
    return _load_one(project, "lifecycle_decisions", lifecycle_decision_id)


def list_lifecycle_decisions(project: Path) -> list[dict[str, Any]]:
    return _load_json_dir_strict(_kind_dir(project, "lifecycle_decisions"))


# --- reference resolution ----------------------------------------------------

def _evidence_ids(project: Path) -> set[str] | None:
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
    known = _evidence_ids(project)
    if known is None or not refs:
        return []
    return [ref for ref in refs if ref not in known]


def _check_artifact_refs(project: Path, refs: list[str]) -> list[str]:
    return [ref for ref in refs if load_artifact(project, ref) is None]


def _decisions_dir(project: Path) -> Path:
    return project.resolve() / ".code-loop" / "runtime" / "decisions"


def _resolve_decision_refs(project: Path, refs: list[str]) -> tuple[list[str], bool]:
    """Returns (unresolved refs, any_ref_is_accept). Reuses the EXISTING decision
    ledger only - never writes, never fabricates ACCEPT."""
    directory = _decisions_dir(project)
    known: dict[str, dict[str, Any]] = {}
    if directory.is_dir():
        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and isinstance(data.get("id"), str):
                known[data["id"]] = data
    unresolved = [ref for ref in refs if ref not in known]
    any_accept = any(known[ref].get("decision") == "accept" for ref in refs if ref in known)
    return unresolved, any_accept


def mark_superseded(project: Path, kind: str, record_id: str, *, superseded_by: str, actor: str, reason: str) -> dict[str, Any]:
    loaders = {
        "release_candidates": "release_candidate_id", "improvements": "improvement_id",
        "release_readiness": "readiness_id", "lifecycle_decisions": "lifecycle_decision_id",
    }
    _require(kind in loaders, f"lifecycle: unknown supersession kind: {kind!r}")
    id_field = loaders[kind]
    record = _load_or_raise(project, kind, record_id, id_field)
    _require_actor_reason(actor, reason, "mark_superseded")
    record["status"] = "SUPERSEDED"
    record["superseded_by"] = superseded_by
    _append_history(record, "SUPERSEDED", actor, reason, superseded_by=superseded_by)
    return _save(project, kind, record, id_field)


# --- P19: ReleaseCandidate -------------------------------------------------------

def _artifact_content_hash(project: Path, artifact_id: str) -> str:
    artifact = load_artifact(project, artifact_id)
    return hashlib.sha256(json.dumps(artifact, sort_keys=True, default=str).encode("utf-8")).hexdigest() if artifact else ""


def compute_candidate_fingerprint(
    code_revision: str | None, artifact_fingerprints: dict[str, str], included_task_refs: list[str],
    included_requirement_refs: list[str], verification_refs: list[str],
) -> str:
    """Pure, deterministic identity of a candidate's material inputs - never a
    function of timestamps. Same logical inputs -> same fingerprint."""
    payload = {
        "code_revision": code_revision or "",
        "artifact_fingerprints": dict(sorted(artifact_fingerprints.items())),
        "included_task_refs": sorted(included_task_refs),
        "included_requirement_refs": sorted(included_requirement_refs),
        "verification_refs": sorted(verification_refs),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def create_release_candidate(
    project: Path, *, version: str, candidate_ref: str, actor: str, reason: str,
    code_revision: str | None = None, branch: str | None = None, project_id: str | None = None,
    included_task_refs: list[str] = (), included_requirement_refs: list[str] = (), artifact_refs: list[str] = (),
    evidence_refs: list[str] = (), verification_refs: list[str] = (), research_refs: list[str] = (),
    decision_refs: list[str] = (), known_failures: list[str] = (), known_limitations: list[str] = (),
    known_risks: list[str] = (), release_candidate_id: str | None = None,
) -> dict[str, Any]:
    _require(bool(version and version.strip()), "create_release_candidate requires a non-empty version")
    _require(bool(candidate_ref and candidate_ref.strip()), "create_release_candidate requires a non-empty candidate_ref")
    _require_actor_reason(actor, reason, "create_release_candidate")
    unresolved = (
        _check_artifact_refs(project, list(artifact_refs))
        + _check_evidence_refs(project, list(evidence_refs) + list(verification_refs))
    )
    if unresolved:
        raise MethodologyValidationError(f"lifecycle: unresolved reference(s): {unresolved}")
    definition = load_methodology()

    release_candidate_id = release_candidate_id or _next_id(project, "release_candidates")
    if load_release_candidate(project, release_candidate_id) is not None:
        raise MethodologyValidationError(f"lifecycle: duplicate release_candidate_id: {release_candidate_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "release_candidate_id": release_candidate_id, "schema_version": SCHEMA_VERSION,
        "methodology_version": definition.version, "project_id": project_id, "version": version.strip(),
        "candidate_ref": candidate_ref.strip(), "code_revision": code_revision, "branch": branch,
        "created_at": timestamp, "created_by": actor.strip(), "actor_id": actor.strip(), "reason": reason.strip(),
        "included_task_refs": list(included_task_refs), "included_requirement_refs": list(included_requirement_refs),
        "artifact_refs": list(artifact_refs), "evidence_refs": list(evidence_refs), "verification_refs": list(verification_refs),
        "research_refs": list(research_refs), "decision_refs": list(decision_refs),
        "known_failures": list(known_failures), "known_limitations": list(known_limitations), "known_risks": list(known_risks),
        "freeze_status": "NOT_FROZEN", "freeze_record": None, "status": "DRAFT",
        "candidate_fingerprint": None, "artifact_fingerprints": {},
        "supersedes": None, "superseded_by": None,
        "sequence": _next_sequence(project, "release_candidates"),
        "updated_at": timestamp, "history": [],
    }
    _append_history(record, "CREATED", actor, reason)
    return _save(project, "release_candidates", record, "release_candidate_id")


def freeze_release_candidate(project: Path, release_candidate_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    """Freeze is about IDENTITY STABILITY, not declaring success: it locks the
    material fields and computes the candidate_fingerprint, but records no
    acceptance judgment whatsoever.

    For a methodology-governed project, freeze is also the sanctioned P19 entry
    point and must never silently bypass M7-C:
      - current_phase == P19 already: freeze proceeds, no further transition needed.
      - current_phase can legally reach P19 (per a real can_transition() dry run,
        covering both the forward chain and any real backward re-entry edge such as
        P20's own allowed_back_transitions): the sanctioned transition() is used.
      - current_phase cannot legally reach P19: freeze FAILS CLOSED before any
        record is mutated, reporting the exact graph conflict - never a silent
        no-op that leaves the candidate FROZEN while the methodology phase itself
        never actually reached P19.
    For a genuinely uninitialized project (no methodology state at all), freeze is
    permitted without any phase check - this reuses the SAME "no methodology state
    -> legacy compatibility" convention nogap_verify_binding.
    verification_acceptance_precondition() already established, not a newly
    invented policy. current_phase is never assigned directly; only
    can_transition()/transition() are used, and the P19 phase contract graph
    itself is never modified to accommodate this."""
    record = _load_or_raise(project, "release_candidates", release_candidate_id, "release_candidate_id")
    _require(record["status"] in {"DRAFT", "ASSEMBLED"}, f"lifecycle: cannot freeze from status {record['status']!r}")
    _require_actor_reason(actor, reason, "freeze_release_candidate")
    _require(bool(record["code_revision"]), "lifecycle: freeze requires a non-empty code_revision")

    known_evidence = _evidence_ids(project) or set()
    transition_evidence_refs = [ref for ref in record["verification_refs"] if ref in known_evidence]

    state = load_state(project)
    needs_transition = state is not None and state["current_phase"] != "P19"
    if needs_transition:
        dry_run = can_transition(project, "P19", evidence_refs=transition_evidence_refs, artifact_refs=[release_candidate_id])
        if not dry_run["allowed"]:
            raise MethodologyValidationError(
                f"lifecycle: cannot freeze release candidate {release_candidate_id} - P19 is not currently a legal "
                f"methodology transition from {state['current_phase']!r}: {'; '.join(dry_run['blocked_reasons'])}"
            )

    artifact_fingerprints = {ref: _artifact_content_hash(project, ref) for ref in record["artifact_refs"]}
    fingerprint = compute_candidate_fingerprint(
        record["code_revision"], artifact_fingerprints, record["included_task_refs"],
        record["included_requirement_refs"], record["verification_refs"],
    )
    record["artifact_fingerprints"] = artifact_fingerprints
    record["candidate_fingerprint"] = fingerprint
    record["status"] = "FROZEN"
    record["freeze_status"] = "FROZEN"
    record["freeze_record"] = {
        "actor_id": actor.strip(), "reason": reason.strip(), "timestamp": _now(), "candidate_fingerprint": fingerprint,
        "artifact_refs": list(record["artifact_refs"]), "verification_refs": list(record["verification_refs"]),
        "known_limitations": list(record["known_limitations"]),
    }
    _append_history(record, "FROZEN", actor, reason, candidate_fingerprint=fingerprint)
    saved = _save(project, "release_candidates", record, "release_candidate_id")

    if needs_transition:
        transition(
            project, "P19", actor, f"release candidate {release_candidate_id} frozen; entering RELEASE",
            artifact_refs=[release_candidate_id], evidence_refs=transition_evidence_refs, authority_class="human",
        )
    return saved


def invalidate_release_candidate(project: Path, release_candidate_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    record = _load_or_raise(project, "release_candidates", release_candidate_id, "release_candidate_id")
    _require(record["status"] not in RC_TERMINAL, f"lifecycle: candidate {release_candidate_id} is already terminal ({record['status']!r})")
    _require_actor_reason(actor, reason, "invalidate_release_candidate")
    record["status"] = "INVALIDATED"
    _append_history(record, "INVALIDATED", actor, reason)
    return _save(project, "release_candidates", record, "release_candidate_id")


def detect_candidate_drift(project: Path, release_candidate_id: str) -> list[str]:
    """Recomputes each frozen artifact's content hash NOW and compares to what was
    captured at freeze time. Never mutates the candidate - drift is reported, not
    silently tolerated or silently fixed."""
    record = _load_or_raise(project, "release_candidates", release_candidate_id, "release_candidate_id")
    if record["status"] != "FROZEN":
        return []
    reasons = []
    for artifact_id, frozen_hash in record["artifact_fingerprints"].items():
        current_hash = _artifact_content_hash(project, artifact_id)
        if not current_hash:
            reasons.append(f"artifact {artifact_id} no longer resolves")
        elif current_hash != frozen_hash:
            reasons.append(f"artifact {artifact_id} content changed since freeze")
    return reasons


def select_current_release_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """The single authoritative implementation of "which release candidate is
    current" - pure, over an already-loaded list. Eligible: status == FROZEN.
    Ordered by engine-assigned `sequence`; a genuine tie is CONFLICT."""
    eligible = [c for c in candidates if c.get("status") == "FROZEN"]
    if not eligible:
        return {"status": "NONE", "candidate": None}
    latest_seq = max(c.get("sequence", 0) for c in eligible)
    tied = [c for c in eligible if c.get("sequence", 0) == latest_seq]
    if len(tied) > 1:
        return {"status": "CONFLICT", "candidate": None, "conflicting_ids": sorted(c["release_candidate_id"] for c in tied)}
    return {"status": "OK", "candidate": tied[0]}


def get_current_release_candidate(project: Path) -> dict[str, Any]:
    return select_current_release_candidate(list_release_candidates(project))


# --- P20: ReleaseReadinessRecord -------------------------------------------------

def _profile_for_readiness(project: Path) -> str:
    state = load_state(project)
    return state["effective_profile"] if state is not None else "LIGHT"


def evaluate_release_readiness(
    project: Path, release_candidate_id: str, *, actor: str, reason: str,
    deployment_plan_ref: str | None = None, rollback_plan_ref: str | None = None,
    observability_plan_ref: str | None = None, decision_refs: list[str] = (), readiness_id: str | None = None,
) -> dict[str, Any]:
    """Deterministic precondition evaluation only - never a decision. The outcome
    vocabulary is READY_FOR_DECISION/NOT_READY/INCONCLUSIVE/STALE, never ACCEPT or
    REJECT; nothing here writes to the decision ledger."""
    _require_actor_reason(actor, reason, "evaluate_release_readiness")
    candidate = _load_or_raise(project, "release_candidates", release_candidate_id, "release_candidate_id")
    definition = load_methodology()
    profile = _profile_for_readiness(project)

    blocking: list[str] = []
    if candidate["status"] != "FROZEN":
        blocking.append(f"release candidate {release_candidate_id} is not FROZEN (status={candidate['status']!r})")

    drift_reasons = detect_candidate_drift(project, release_candidate_id) if candidate["status"] == "FROZEN" else []

    verification_status = "NOT_ATTEMPTED"
    if candidate["included_task_refs"]:
        import nogap_verify_binding as vb
        unresolved_tasks = []
        for task_id in sorted(set(candidate["included_task_refs"])):
            precondition = vb.verification_acceptance_precondition(project, task_id)
            if not precondition["satisfied"]:
                unresolved_tasks.append(f"{task_id}: {precondition['reason']}")
        if unresolved_tasks:
            verification_status = "INCOMPLETE"
            # Applies at every profile, including LIGHT: verification_acceptance_precondition()
            # (M7-G) already correctly encodes profile-aware depth on its own - at LIGHT, a
            # candidate legitimately reaches VERIFICATION_COMPLETE_AWAITING_DECISION with
            # P17/P18 marked SKIPPED_PER_PROFILE_POLICY (never "missing"), so this never
            # blocks LIGHT for lacking reproducibility/independent review. What it DOES still
            # require at every profile is that P15/P16 (the verification plan and the
            # mandatory deterministic layer) genuinely happened - LIGHT must never be
            # able to reach READY_FOR_DECISION with verification simply never attempted or
            # deterministic checks failed. No second verification definition is created
            # here; this reuses the exact same precondition M7-G's own decide interlock uses.
            blocking.extend(f"verification not current for task {item}" for item in unresolved_tasks)
        else:
            verification_status = "COMPLETE"
    else:
        blocking.append("no included_task_refs to verify against - minimum P15/P16 verification is required at every profile, including LIGHT")

    # Reused, not re-derived: M7-G's own derive_verification_depth() is the single
    # existing source of truth for "does this profile require reproducibility" -
    # never a second, independently-invented profile policy.
    reproducibility_status = "NOT_REQUIRED"
    if load_state(project) is not None:
        import nogap_verify_binding as vb
        depth = vb.derive_verification_depth(project)
        reproducibility_status = "REQUIRED" if depth["reproducibility_required"] else "NOT_REQUIRED"

    if profile == "STRICT":
        if not rollback_plan_ref:
            blocking.append("STRICT profile requires a rollback_plan_ref")
        if not observability_plan_ref:
            blocking.append("STRICT profile requires an observability_plan_ref")

    unresolved_decisions, _ = _resolve_decision_refs(project, list(decision_refs))
    if unresolved_decisions:
        raise MethodologyValidationError(f"lifecycle: unresolved decision reference(s): {unresolved_decisions}")

    readiness_id = readiness_id or _next_id(project, "release_readiness")
    if load_release_readiness(project, readiness_id) is not None:
        raise MethodologyValidationError(f"lifecycle: duplicate readiness_id: {readiness_id}")

    # PHASE-COMPLETING check, folded into the SAME blocking-reasons computation every
    # other criterion already uses - not a separate best-effort side path. Only
    # READY_FOR_DECISION is a phase-completing statement (NOT_READY/INCONCLUSIVE/STALE
    # remain useful evidence and never touch methodology at all - "readiness
    # evaluation may occur without phase transition" for those). If P19->P20 is not
    # currently legal, READY_FOR_DECISION is never reached in the first place - the
    # record is saved honestly as NOT_READY instead, so no Lifecycle/Methodology
    # split-brain can ever be persisted. Already being at P20 (or an uninitialized/
    # legacy project - the SAME state-is-None convention used throughout this module,
    # not a new one) needs no transition at all.
    state = load_state(project)
    would_be_ready = not drift_reasons and not blocking and verification_status != "INCOMPLETE"
    needs_transition = would_be_ready and state is not None and state["current_phase"] != "P20"
    if needs_transition:
        dry_run = can_transition(project, "P20", artifact_refs=[readiness_id])
        if not dry_run["allowed"]:
            blocking.append(
                f"P19->P20 is not currently a legal methodology transition: {'; '.join(dry_run['blocked_reasons'])}"
            )
            needs_transition = False

    if drift_reasons:
        outcome = "STALE"
    elif blocking:
        outcome = "NOT_READY"
    elif verification_status == "INCOMPLETE":
        outcome = "INCONCLUSIVE"
    else:
        outcome = "READY_FOR_DECISION"

    # Methodology truth commits BEFORE the lifecycle record that depends on it - if
    # this transition() succeeds but the _save() below then fails (e.g. a disk
    # error), the residual state is "P20 with no readiness record explaining why",
    # a missing-evidence gap, never a FALSE READY_FOR_DECISION claim outliving a
    # phase that was never actually entered. True cross-file transactional atomicity
    # does not exist in this architecture (disclosed, not solved here - no database/
    # transaction framework is introduced).
    if needs_transition:
        transition(
            project, "P20", actor, f"readiness {readiness_id} READY_FOR_DECISION; entering release readiness/deployment",
            artifact_refs=[readiness_id], authority_class="human",
        )

    timestamp = _now()
    record: dict[str, Any] = {
        "readiness_id": readiness_id, "release_candidate_id": release_candidate_id, "schema_version": SCHEMA_VERSION,
        "methodology_version": definition.version, "candidate_fingerprint": candidate.get("candidate_fingerprint"),
        "created_at": timestamp, "actor_id": actor.strip(), "reason": reason.strip(),
        "verification_status": verification_status, "verification_refs": list(candidate["verification_refs"]),
        "requirement_status": "ACCOUNTED_FOR" if candidate["included_requirement_refs"] else "NONE",
        "gate_status": "N/A", "artifact_status": "RESOLVED",
        "reproducibility_status": reproducibility_status,
        "research_status": None,
        "known_failures": list(candidate["known_failures"]), "known_limitations": list(candidate["known_limitations"]),
        "known_risks": list(candidate["known_risks"]),
        "deployment_plan_ref": deployment_plan_ref, "rollback_plan_ref": rollback_plan_ref,
        "observability_plan_ref": observability_plan_ref, "decision_refs": list(decision_refs),
        "criteria_results": {"drift_reasons": drift_reasons, "profile": profile},
        "blocking_reasons": blocking, "readiness_outcome": outcome, "status": "EVALUATED",
        "sequence": _next_sequence(project, "release_readiness", "release_candidate_id", release_candidate_id),
        "updated_at": timestamp, "history": [],
    }
    _append_history(record, "EVALUATED", actor, reason, outcome=outcome)
    return _save(project, "release_readiness", record, "readiness_id")


def select_current_release_readiness(readiness_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Single authoritative "current readiness" selector, pure, sequence-ordered."""
    if not readiness_records:
        return {"status": "NONE", "readiness": None}
    latest_seq = max(r.get("sequence", 0) for r in readiness_records)
    tied = [r for r in readiness_records if r.get("sequence", 0) == latest_seq]
    if len(tied) > 1:
        return {"status": "CONFLICT", "readiness": None, "conflicting_ids": sorted(r["readiness_id"] for r in tied)}
    return {"status": "OK", "readiness": tied[0]}


def get_current_release_readiness(project: Path, release_candidate_id: str) -> dict[str, Any]:
    return select_current_release_readiness(list_release_readiness(project, release_candidate_id=release_candidate_id))


# --- Deployment ------------------------------------------------------------------

def create_deployment(
    project: Path, *, release_candidate_id: str, readiness_id: str, environment: str, deployment_target: str,
    actor: str, reason: str, decision_refs: list[str] = (), execution_refs: list[str] = (), artifact_refs: list[str] = (),
    evidence_refs: list[str] = (), deployment_id: str | None = None,
) -> dict[str, Any]:
    """Fails closed on: unresolved candidate/readiness, fingerprint mismatch between
    candidate/readiness, candidate drift since freeze, readiness not
    READY_FOR_DECISION, and (at STANDARD/STRICT) a missing/unresolved/non-accept
    release decision reference. Never creates a decision - only resolves one that
    already exists."""
    _require_actor_reason(actor, reason, "create_deployment")
    candidate = _load_or_raise(project, "release_candidates", release_candidate_id, "release_candidate_id")
    readiness = _load_or_raise(project, "release_readiness", readiness_id, "readiness_id")
    _require(readiness["release_candidate_id"] == release_candidate_id, "lifecycle: readiness does not belong to this release candidate")
    _require(candidate["status"] not in {"SUPERSEDED", "INVALIDATED", "ABANDONED"},
              f"lifecycle: cannot deploy a {candidate['status']} release candidate")
    _require(candidate["status"] == "FROZEN", "lifecycle: cannot deploy an unfrozen release candidate")
    _require(
        candidate["candidate_fingerprint"] == readiness["candidate_fingerprint"],
        "lifecycle: candidate/readiness fingerprint mismatch - readiness was computed for a different candidate state",
    )
    drift_reasons = detect_candidate_drift(project, release_candidate_id)
    if drift_reasons:
        raise MethodologyValidationError(f"lifecycle: cannot deploy a stale/drifted candidate: {drift_reasons}")
    _require(
        readiness["readiness_outcome"] == "READY_FOR_DECISION",
        f"lifecycle: readiness outcome is {readiness['readiness_outcome']!r}, not READY_FOR_DECISION",
    )

    profile = _profile_for_readiness(project)
    unresolved_decisions, has_accept = _resolve_decision_refs(project, list(decision_refs))
    if unresolved_decisions:
        raise MethodologyValidationError(f"lifecycle: unresolved decision reference(s): {unresolved_decisions}")
    if profile != "LIGHT" and not has_accept:
        raise MethodologyValidationError(
            "lifecycle: deployment at this profile requires a resolvable release decision with decision=accept "
            "- this module never fabricates one"
        )

    unresolved_refs = _check_evidence_refs(project, list(evidence_refs)) + _check_artifact_refs(project, list(artifact_refs))
    if unresolved_refs:
        raise MethodologyValidationError(f"lifecycle: unresolved reference(s): {unresolved_refs}")

    definition = load_methodology()
    deployment_id = deployment_id or _next_id(project, "deployments")
    if load_deployment(project, deployment_id) is not None:
        raise MethodologyValidationError(f"lifecycle: duplicate deployment_id: {deployment_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "deployment_id": deployment_id, "release_candidate_id": release_candidate_id, "readiness_id": readiness_id,
        "schema_version": SCHEMA_VERSION, "methodology_version": definition.version,
        "candidate_fingerprint": candidate["candidate_fingerprint"], "decision_refs": list(decision_refs),
        "environment": environment, "deployment_target": deployment_target, "started_at": timestamp,
        "completed_at": None, "actor_id": actor.strip(), "reason": reason.strip(),
        "execution_refs": list(execution_refs), "evidence_refs": list(evidence_refs), "artifact_refs": list(artifact_refs),
        "status": "PLANNED", "observed_effect": None, "rollback_ref": None,
        "sequence": _next_sequence(project, "deployments", "release_candidate_id", release_candidate_id),
        "updated_at": timestamp, "history": [],
    }
    _append_history(record, "CREATED", actor, reason)
    return _save(project, "deployments", record, "deployment_id")


def record_deployment_result(
    project: Path, deployment_id: str, *, status: str, actor: str, reason: str,
    execution_refs: list[str] = (), evidence_refs: list[str] = (), observed_effect: str | None = None,
    rollback_ref: str | None = None,
) -> dict[str, Any]:
    """SUCCEEDED means the recorded execution evidence supports it - never
    "production healthy" (see get_operational_status, a wholly separate function
    that never reads this status).

    SUCCEEDED is the one PHASE-ENTERING outcome here (FAILED/CANCELLED/INCONCLUSIVE/
    ROLLED_BACK are historical execution facts only and never touch methodology).
    Unlike readiness, a deployment result can never be honestly "downgraded" -
    SUCCEEDED either really happened or it didn't - so when methodology is governed
    and P20->P21 is not currently legal, this FAILS CLOSED before mutating the
    deployment record AT ALL: no half-state where Deployment=SUCCEEDED while
    MethodologyState stays behind. The already-persisted PLANNED/STARTED record is
    left exactly as it was; the caller must resolve the methodology conflict (or the
    deployment stays truthfully un-finalized) rather than this module silently
    picking either a false status or a split-brain state."""
    _require(status in DEPLOYMENT_STATUSES, f"lifecycle: unknown deployment status: {status!r}")
    record = _load_or_raise(project, "deployments", deployment_id, "deployment_id")
    _require(record["status"] not in DEPLOYMENT_TERMINAL, f"lifecycle: deployment {deployment_id} is already terminal ({record['status']!r})")
    _require_actor_reason(actor, reason, "record_deployment_result")
    unresolved = _check_evidence_refs(project, list(evidence_refs))
    if unresolved:
        raise MethodologyValidationError(f"lifecycle: unresolved evidence reference(s): {unresolved}")

    prospective_evidence_refs = sorted(set(record["evidence_refs"]) | set(evidence_refs))
    if status == "SUCCEEDED":
        state = load_state(project)
        if state is not None and state["current_phase"] != "P21":
            known_evidence = _evidence_ids(project) or set()
            transition_evidence_refs = [ref for ref in prospective_evidence_refs if ref in known_evidence]
            dry_run = can_transition(project, "P21", artifact_refs=[deployment_id], evidence_refs=transition_evidence_refs)
            if not dry_run["allowed"]:
                raise MethodologyValidationError(
                    f"lifecycle: cannot record deployment {deployment_id} as SUCCEEDED - P21 is not currently a legal "
                    f"methodology transition from {state['current_phase']!r}: {'; '.join(dry_run['blocked_reasons'])}"
                )
            # methodology truth commits before the execution fact that depends on
            # it - see evaluate_release_readiness's own docstring for the same
            # ordering rationale and its disclosed cross-file atomicity limitation.
            transition(
                project, "P21", actor, f"deployment {deployment_id} succeeded; entering production observation",
                artifact_refs=[deployment_id], evidence_refs=transition_evidence_refs, authority_class="human",
            )

    record["status"] = status
    record["completed_at"] = _now()
    record["execution_refs"] = sorted(set(record["execution_refs"]) | set(execution_refs))
    record["evidence_refs"] = prospective_evidence_refs
    record["observed_effect"] = observed_effect
    if status == "ROLLED_BACK":
        record["rollback_ref"] = rollback_ref or f"rollback-{deployment_id}"
    _append_history(record, "RESULT_RECORDED", actor, reason, status=status)
    return _save(project, "deployments", record, "deployment_id")


# --- P21: OperationalObservation / health ----------------------------------------

def record_operational_observation(
    project: Path, *, deployment_id: str, signal_type: str, metric_name: str, metric_value: float, actor: str, reason: str,
    unit: str | None = None, window: str | None = None, baseline_ref: str | None = None, severity: str | None = None,
    evidence_refs: list[str] = (), artifact_refs: list[str] = (), notes: str | None = None, observation_id: str | None = None,
) -> dict[str, Any]:
    _require(bool(signal_type and signal_type.strip()), "record_operational_observation requires a non-empty signal_type")
    _require(bool(metric_name and metric_name.strip()), "record_operational_observation requires a non-empty metric_name")
    _require(isinstance(metric_value, (int, float)), "record_operational_observation requires a numeric metric_value")
    _require_actor_reason(actor, reason, "record_operational_observation")
    deployment = _load_or_raise(project, "deployments", deployment_id, "deployment_id")
    unresolved = _check_evidence_refs(project, list(evidence_refs)) + _check_artifact_refs(project, list(artifact_refs))
    if unresolved:
        raise MethodologyValidationError(f"lifecycle: unresolved reference(s): {unresolved}")
    definition = load_methodology()

    observation_id = observation_id or _next_id(project, "operations")
    if load_operational_observation(project, observation_id) is not None:
        raise MethodologyValidationError(f"lifecycle: duplicate observation_id: {observation_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "observation_id": observation_id, "deployment_id": deployment["deployment_id"], "schema_version": SCHEMA_VERSION,
        "methodology_version": definition.version, "environment": deployment.get("environment"), "observed_at": timestamp,
        "actor_id": actor.strip(), "signal_type": signal_type.strip(), "metric_name": metric_name.strip(),
        "metric_value": metric_value, "unit": unit, "window": window, "baseline_ref": baseline_ref,
        "evidence_refs": list(evidence_refs), "artifact_refs": list(artifact_refs), "status": "RECORDED",
        "severity": severity, "notes": notes, "updated_at": timestamp, "history": [],
    }
    _append_history(record, "RECORDED", actor, reason)
    return _save(project, "operations", record, "observation_id")


def compute_operational_status(observations: list[dict[str, Any]], health_criteria: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The single authoritative operational-health computation - pure, over an
    already-loaded observation list. UNKNOWN with no observations (never HEALTHY);
    without explicit health_criteria, present observations are INCONCLUSIVE (we have
    data but no declared threshold to judge it against) - never HEALTHY by default.
    Deployment status and incident presence/absence are never inputs here."""
    if not observations:
        return {"status": "UNKNOWN", "reason": "no operational observations recorded", "criteria_results": []}
    if not health_criteria:
        return {"status": "INCONCLUSIVE", "reason": "observations exist but no health criteria were supplied to judge them", "criteria_results": []}

    comparators = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b, "<=": lambda a, b: a <= b, "==": lambda a, b: a == b}
    results = []
    worst = "HEALTHY"
    rank = {"HEALTHY": 0, "INCONCLUSIVE": 1, "DEGRADED": 2, "UNHEALTHY": 3}
    for criterion in health_criteria:
        matching = [o for o in observations if o.get("metric_name") == criterion.get("metric_name")]
        comparator = comparators.get(criterion.get("comparator"))
        if not matching or comparator is None:
            results.append({"metric_name": criterion.get("metric_name"), "passed": False, "had_data": False})
            if rank["INCONCLUSIVE"] > rank[worst]:
                worst = "INCONCLUSIVE"
            continue
        latest = max(matching, key=lambda o: o.get("observed_at", ""))
        passed = comparator(latest["metric_value"], criterion["value"])
        results.append({"metric_name": criterion.get("metric_name"), "passed": passed, "had_data": True, "observed_value": latest["metric_value"]})
        if not passed:
            severity = criterion.get("severity_if_fails", "DEGRADED")
            if rank.get(severity, 2) > rank[worst]:
                worst = severity
    return {"status": worst, "reason": None, "criteria_results": results}


def get_operational_status(project: Path, deployment_id: str, health_criteria: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return compute_operational_status(list_operational_observations(project, deployment_id=deployment_id), health_criteria)


# --- P21: IncidentRecord -----------------------------------------------------

def create_incident(
    project: Path, *, deployment_id: str, summary: str, severity: str, actor: str, reason: str,
    observation_refs: list[str] = (), evidence_refs: list[str] = (), incident_id: str | None = None,
) -> dict[str, Any]:
    _require(severity in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}, f"lifecycle: unknown incident severity: {severity!r}")
    _require(bool(summary and summary.strip()), "create_incident requires a non-empty summary")
    _require_actor_reason(actor, reason, "create_incident")
    deployment = _load_or_raise(project, "deployments", deployment_id, "deployment_id")
    unresolved = [ref for ref in observation_refs if load_operational_observation(project, ref) is None]
    unresolved += _check_evidence_refs(project, list(evidence_refs))
    if unresolved:
        raise MethodologyValidationError(f"lifecycle: unresolved reference(s): {unresolved}")
    definition = load_methodology()

    incident_id = incident_id or _next_id(project, "incidents")
    if load_incident(project, incident_id) is not None:
        raise MethodologyValidationError(f"lifecycle: duplicate incident_id: {incident_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "incident_id": incident_id, "deployment_id": deployment["deployment_id"], "schema_version": SCHEMA_VERSION,
        "methodology_version": definition.version, "detected_at": timestamp, "actor_id": actor.strip(), "reason": reason.strip(),
        "severity": severity, "summary": summary.strip(), "observation_refs": list(observation_refs),
        "evidence_refs": list(evidence_refs), "failure_ref": None, "status": "OPEN",
        "updated_at": timestamp, "history": [],
    }
    _append_history(record, "CREATED", actor, reason)
    return _save(project, "incidents", record, "incident_id")


def link_incident_failure(project: Path, incident_id: str, failure_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    """Reuses nogap_failure.load_failure() as the sole authority on the failure's
    existence/state - never reproduces M7-H's repair lifecycle here."""
    import nogap_failure as nf

    record = _load_or_raise(project, "incidents", incident_id, "incident_id")
    _require(record["status"] not in INCIDENT_TERMINAL, f"lifecycle: incident {incident_id} is already terminal ({record['status']!r})")
    _require_actor_reason(actor, reason, "link_incident_failure")
    failure = nf.load_failure(project, failure_id)
    if failure is None:
        raise MethodologyValidationError(f"lifecycle: unknown failure_id: {failure_id!r}")

    record["failure_ref"] = failure_id
    record["status"] = "LINKED_TO_FAILURE"
    _append_history(record, "LINKED_TO_FAILURE", actor, reason, failure_id=failure_id)
    return _save(project, "incidents", record, "incident_id")


def set_incident_status(project: Path, incident_id: str, status: str, *, actor: str, reason: str) -> dict[str, Any]:
    """RESOLVED can never be set while a linked M7-H FailureRecord's own
    current_state isn't actually RESOLVED - this reads M7-H's real state, it never
    presents an unresolved failure as repaired."""
    _require(status in INCIDENT_STATUSES, f"lifecycle: unknown incident status: {status!r}")
    record = _load_or_raise(project, "incidents", incident_id, "incident_id")
    _require(record["status"] not in INCIDENT_TERMINAL, f"lifecycle: incident {incident_id} is already terminal ({record['status']!r})")
    _require_actor_reason(actor, reason, "set_incident_status")

    if status == "RESOLVED" and record.get("failure_ref"):
        import nogap_failure as nf
        failure = nf.load_failure(project, record["failure_ref"])
        if failure is None or failure["current_state"] != "RESOLVED":
            raise MethodologyValidationError(
                f"lifecycle: incident {incident_id} cannot be marked RESOLVED - linked failure "
                f"{record['failure_ref']!r} is not RESOLVED (state={failure['current_state'] if failure else 'unknown'!r})"
            )

    record["status"] = status
    _append_history(record, "STATUS_CHANGED", actor, reason, new_status=status)
    return _save(project, "incidents", record, "incident_id")


# --- P22: ImprovementRecord -------------------------------------------------------

def create_improvement(
    project: Path, *, problem_or_opportunity: str, proposed_change: str, source_type: str, actor: str, reason: str,
    category: str | None = None, source_refs: list[str] = (), expected_value: str | None = None, risk: str | None = None,
    cost_estimate: str | None = None, evidence_refs: list[str] = (), research_refs: list[str] = (),
    failure_refs: list[str] = (), operation_refs: list[str] = (), improvement_id: str | None = None,
) -> dict[str, Any]:
    """PREPARATORY only: a proposal (even one grounded in real operational evidence)
    never by itself means the project has entered P22 - operational systems must be
    able to record improvement ideas while still operating in P21. The phase-entering
    event is select_improvement(), not this function; see its own docstring."""
    _require(bool(problem_or_opportunity and problem_or_opportunity.strip()), "create_improvement requires a non-empty problem_or_opportunity")
    _require(bool(proposed_change and proposed_change.strip()), "create_improvement requires a non-empty proposed_change")
    _require(category is None or category in IMPROVEMENT_CATEGORIES, f"lifecycle: unknown category: {category!r}")
    _require_actor_reason(actor, reason, "create_improvement")

    unresolved = (
        _check_evidence_refs(project, list(evidence_refs))
        + [ref for ref in operation_refs if load_operational_observation(project, ref) is None]
        + [ref for ref in failure_refs if _load_failure_ref(project, ref) is None]
        + [ref for ref in research_refs if _load_research_ref(project, ref) is None]
    )
    if unresolved:
        raise MethodologyValidationError(f"lifecycle: unresolved reference(s): {unresolved}")
    definition = load_methodology()

    improvement_id = improvement_id or _next_id(project, "improvements")
    if load_improvement(project, improvement_id) is not None:
        raise MethodologyValidationError(f"lifecycle: duplicate improvement_id: {improvement_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "improvement_id": improvement_id, "schema_version": SCHEMA_VERSION, "methodology_version": definition.version,
        "created_at": timestamp, "actor_id": actor.strip(), "reason": reason.strip(), "category": category,
        "source_type": source_type, "source_refs": list(source_refs), "problem_or_opportunity": problem_or_opportunity.strip(),
        "proposed_change": proposed_change.strip(), "expected_value": expected_value, "risk": risk, "cost_estimate": cost_estimate,
        "evidence_refs": list(evidence_refs), "research_refs": list(research_refs), "failure_refs": list(failure_refs),
        "operation_refs": list(operation_refs), "target_phase": None, "status": "PROPOSED",
        "supersedes": None, "superseded_by": None, "updated_at": timestamp, "history": [],
    }
    _append_history(record, "CREATED", actor, reason)
    return _save(project, "improvements", record, "improvement_id")


def _load_failure_ref(project: Path, failure_id: str) -> dict[str, Any] | None:
    import nogap_failure as nf
    return nf.load_failure(project, failure_id)


def _load_research_ref(project: Path, ref: str) -> Any:
    import nogap_research as nr
    for loader in (nr.load_claim, nr.load_assessment, nr.load_research_question, nr.load_hypothesis):
        record = loader(project, ref)
        if record is not None:
            return record
    return None


def select_improvement(project: Path, improvement_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    """Requires at least one real, resolved evidence source - Agent prose alone
    (a bare problem_or_opportunity/proposed_change string with no refs) can never be
    sufficient for SELECTED.

    PHASE-ENTERING: this is the actual event that means the project now pursues the
    improvement (P22), not create_improvement()'s mere proposal. When methodology is
    governed and P21->P22 is not currently legal, this fails closed before mutating
    the improvement record at all - SELECTED is never persisted while methodology
    stays behind."""
    record = _load_or_raise(project, "improvements", improvement_id, "improvement_id")
    _require(record["status"] in {"PROPOSED", "SUPPORTED"}, f"lifecycle: cannot select from status {record['status']!r}")
    _require_actor_reason(actor, reason, "select_improvement")
    has_evidence = bool(record["evidence_refs"] or record["research_refs"] or record["failure_refs"] or record["operation_refs"])
    if not has_evidence:
        raise MethodologyValidationError(
            f"lifecycle: improvement {improvement_id} cannot be SELECTED without at least one real evidence/research/"
            f"failure/operation reference - a bare proposal is not sufficient"
        )

    state = load_state(project)
    if state is not None and state["current_phase"] != "P22":
        known_evidence = _evidence_ids(project) or set()
        transition_evidence_refs = [ref for ref in record["evidence_refs"] if ref in known_evidence]
        dry_run = can_transition(project, "P22", artifact_refs=[improvement_id], evidence_refs=transition_evidence_refs)
        if not dry_run["allowed"]:
            raise MethodologyValidationError(
                f"lifecycle: cannot select improvement {improvement_id} - P22 is not currently a legal methodology "
                f"transition from {state['current_phase']!r}: {'; '.join(dry_run['blocked_reasons'])}"
            )
        transition(
            project, "P22", actor, f"improvement {improvement_id} selected for pursuit; entering EVOLVE",
            artifact_refs=[improvement_id], evidence_refs=transition_evidence_refs, authority_class="human",
        )

    record["status"] = "SELECTED"
    _append_history(record, "SELECTED", actor, reason)
    return _save(project, "improvements", record, "improvement_id")


def reenter_for_improvement(
    project: Path, improvement_id: str, target_phase: str, *, actor: str, reason: str,
    evidence_refs: list[str] = (), artifact_refs: list[str] = (),
) -> dict[str, Any]:
    """Routes to target_phase strictly through can_transition()/transition() -
    never a direct current_phase assignment, and never a broadened graph edge. If
    M7-C's P22.allowed_back_transitions does not cover the requested target, this
    fails closed and reports the exact conflict."""
    record = _load_or_raise(project, "improvements", improvement_id, "improvement_id")
    _require(record["status"] == "SELECTED", f"lifecycle: cannot re-enter from status {record['status']!r}")
    _require_actor_reason(actor, reason, "reenter_for_improvement")
    category = record.get("category")
    if category is not None:
        allowed_targets = IMPROVEMENT_ROUTING_MAP.get(category, ())
        _require(
            target_phase in allowed_targets,
            f"lifecycle: invalid re-entry target {target_phase!r} for category {category!r} (allowed: {allowed_targets})",
        )

    dry_run = can_transition(project, target_phase, evidence_refs=list(evidence_refs), artifact_refs=[improvement_id] + list(artifact_refs))
    if not dry_run["allowed"]:
        raise MethodologyValidationError(
            f"lifecycle: re-entry target {target_phase!r} is not currently a legal methodology transition: "
            f"{'; '.join(dry_run['blocked_reasons'])}"
        )
    transition(
        project, target_phase, actor, f"improvement {improvement_id} selected for re-entry: {reason}",
        artifact_refs=[improvement_id] + list(artifact_refs), evidence_refs=list(evidence_refs), authority_class="human",
    )
    record["status"] = "REENTERED"
    record["target_phase"] = target_phase
    _append_history(record, "REENTERED", actor, reason, target_phase=target_phase)
    return _save(project, "improvements", record, "improvement_id")


def set_improvement_status(project: Path, improvement_id: str, status: str, *, actor: str, reason: str) -> dict[str, Any]:
    _require(status in IMPROVEMENT_STATUSES, f"lifecycle: unknown improvement status: {status!r}")
    record = _load_or_raise(project, "improvements", improvement_id, "improvement_id")
    _require(record["status"] not in IMPROVEMENT_TERMINAL, f"lifecycle: improvement {improvement_id} is already terminal ({record['status']!r})")
    _require_actor_reason(actor, reason, "set_improvement_status")
    if status == "VALIDATED":
        _require(record["status"] == "IMPLEMENTED", "lifecycle: VALIDATED requires prior IMPLEMENTED status")
    record["status"] = status
    _append_history(record, "STATUS_CHANGED", actor, reason, new_status=status)
    return _save(project, "improvements", record, "improvement_id")


# --- P23: LifecycleDecisionRecord -------------------------------------------------

def create_lifecycle_decision(
    project: Path, *, outcome: str, rationale: str, actor: str, reason: str, authority: str = "human",
    evidence_refs: list[str] = (), decision_refs: list[str] = (), failure_refs: list[str] = (),
    research_refs: list[str] = (), operation_refs: list[str] = (), improvement_refs: list[str] = (),
    current_project_state: str | None = None, constraints: list[str] = (), next_phase: str | None = None,
    lifecycle_decision_id: str | None = None,
) -> dict[str, Any]:
    """RETIRE/ARCHIVE require authority="human" specifically - not the broader
    "acceptance" class, which nogap.py's own Decision Engine exposes as a bare,
    self-asserted CLI flag with no verification anywhere that the caller is
    actually human. An ordinary Agent (execution/tool/verification/acceptance)
    cannot self-authorize an irreversible lifecycle action - only a genuine Human
    Owner can. Never deletes anything: research, failures, deployments, incidents,
    improvements, and evidence all remain exactly as they were."""
    _require(outcome in LIFECYCLE_OUTCOMES, f"lifecycle: unknown outcome: {outcome!r}")
    _require(bool(rationale and rationale.strip()), "create_lifecycle_decision requires a non-empty rationale")
    _require_actor_reason(actor, reason, "create_lifecycle_decision")
    if outcome in LIFECYCLE_IRREVERSIBLE_OUTCOMES:
        _require(
            authority in LIFECYCLE_IRREVERSIBLE_AUTHORITIES,
            f"lifecycle: {outcome} requires Human Owner authority (authority='human'; got {authority!r}) - generic "
            f"'acceptance' authority is self-asserted elsewhere in this codebase with no human verification, so it "
            f"cannot by itself authorize an irreversible lifecycle action",
        )

    unresolved = (
        _check_evidence_refs(project, list(evidence_refs))
        + [ref for ref in failure_refs if _load_failure_ref(project, ref) is None]
        + [ref for ref in research_refs if _load_research_ref(project, ref) is None]
        + [ref for ref in operation_refs if load_operational_observation(project, ref) is None]
        + [ref for ref in improvement_refs if load_improvement(project, ref) is None]
    )
    if unresolved:
        raise MethodologyValidationError(f"lifecycle: unresolved reference(s): {unresolved}")
    definition = load_methodology()

    lifecycle_decision_id = lifecycle_decision_id or _next_id(project, "lifecycle_decisions")
    if load_lifecycle_decision(project, lifecycle_decision_id) is not None:
        raise MethodologyValidationError(f"lifecycle: duplicate lifecycle_decision_id: {lifecycle_decision_id}")

    # PHASE-ENTERING, unconditionally: unlike readiness/deployment, EVERY outcome
    # here (including INCONCLUSIVE) is P23 semantics - a LifecycleDecisionRecord's
    # own existence IS the P23 event, there is no "weaker" preparatory variant of it.
    # Fails closed before any record is persisted - RETIRE/ARCHIVE/SUSPEND/CONTINUE/
    # MAINTAIN/IMPROVE/REENTER/INCONCLUSIVE must never be recorded as authoritative
    # while methodology cannot actually reach P23.
    state = load_state(project)
    needs_transition = state is not None and state["current_phase"] != "P23"
    transition_evidence_refs: list[str] = []
    if needs_transition:
        known_evidence = _evidence_ids(project) or set()
        transition_evidence_refs = [ref for ref in evidence_refs if ref in known_evidence]
        dry_run = can_transition(project, "P23", artifact_refs=[lifecycle_decision_id], evidence_refs=transition_evidence_refs)
        if not dry_run["allowed"]:
            raise MethodologyValidationError(
                f"lifecycle: cannot record lifecycle decision - P23 is not currently a legal methodology transition "
                f"from {state['current_phase']!r}: {'; '.join(dry_run['blocked_reasons'])}"
            )

    # methodology truth commits before the lifecycle_decision record - same ordering
    # rationale as evaluate_release_readiness/record_deployment_result.
    if needs_transition:
        transition(
            project, "P23", actor, f"lifecycle decision {lifecycle_decision_id} recorded; entering lifecycle decision phase",
            artifact_refs=[lifecycle_decision_id], evidence_refs=transition_evidence_refs, authority_class="human",
        )

    timestamp = _now()
    record: dict[str, Any] = {
        "lifecycle_decision_id": lifecycle_decision_id, "schema_version": SCHEMA_VERSION, "methodology_version": definition.version,
        "created_at": timestamp, "actor_id": actor.strip(), "reason": reason.strip(), "authority": authority,
        "evidence_refs": list(evidence_refs), "decision_refs": list(decision_refs), "failure_refs": list(failure_refs),
        "research_refs": list(research_refs), "operation_refs": list(operation_refs), "improvement_refs": list(improvement_refs),
        "current_project_state": current_project_state, "outcome": outcome, "rationale": rationale.strip(),
        "constraints": list(constraints), "next_phase": next_phase, "supersedes": None, "superseded_by": None,
        "sequence": _next_sequence(project, "lifecycle_decisions"),
        "updated_at": timestamp, "history": [],
    }
    _append_history(record, "CREATED", actor, reason, outcome=outcome)
    return _save(project, "lifecycle_decisions", record, "lifecycle_decision_id")


def select_current_lifecycle_decision(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Single authoritative "current lifecycle decision" selector, pure,
    sequence-ordered, project-wide (not scoped)."""
    if not records:
        return {"status": "NONE", "decision": None}
    latest_seq = max(r.get("sequence", 0) for r in records)
    tied = [r for r in records if r.get("sequence", 0) == latest_seq]
    if len(tied) > 1:
        return {"status": "CONFLICT", "decision": None, "conflicting_ids": sorted(r["lifecycle_decision_id"] for r in tied)}
    return {"status": "OK", "decision": tied[0]}


def get_current_lifecycle_decision(project: Path) -> dict[str, Any]:
    return select_current_lifecycle_decision(list_lifecycle_decisions(project))


# --- query -----------------------------------------------------------------------

def query_lifecycle(project: Path, kind: str, record_id: str | None = None) -> Any:
    listers = {
        "release_candidates": list_release_candidates, "release_readiness": list_release_readiness,
        "deployments": list_deployments, "operations": list_operational_observations,
        "incidents": list_incidents, "improvements": list_improvements, "lifecycle_decisions": list_lifecycle_decisions,
    }
    loaders = {
        "release_candidates": load_release_candidate, "release_readiness": load_release_readiness,
        "deployments": load_deployment, "operations": load_operational_observation,
        "incidents": load_incident, "improvements": load_improvement, "lifecycle_decisions": load_lifecycle_decision,
    }
    _require(kind in listers, f"lifecycle: unknown query kind: {kind!r}")
    if record_id is None:
        return listers[kind](project)
    record = loaders[kind](project, record_id)
    if record is None:
        raise MethodologyValidationError(f"lifecycle: unknown {kind} {record_id!r}")
    return record
