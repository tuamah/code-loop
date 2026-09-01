#!/usr/bin/env python3
"""M7-J: Research / Claims / Hypotheses - the structured scientific reasoning layer.

Canonical flow, never bypassed:
Question -> (prior evidence/prior art) -> Hypothesis -> Protocol -> Experiment ->
Observation -> Evidence -> Claim Assessment -> SUPPORTED/PARTIALLY_SUPPORTED/
REFUTED/INCONCLUSIVE.

HYPOTHESIS BEFORE RESULT is the central invariant: register_hypothesis() refuses to
mark a hypothesis preregistered if any experiment/observation/assessment already
exists for its question - fabricated preregistration is rejected outright, never
silently downgraded to look honest.

This module is NOT an acceptance authority, NOT a second Decision Engine, NOT a
second Failure lifecycle, NOT a second Memory projection, and NOT a second Golden
Gate: assess_claim() only ever writes ClaimAssessment records under
.code-loop/research/ - nothing here calls nogap.py's decision path, nogap_failure.py's
resolution path, nogap_methodology.transition(), or ever touches
.code-loop/runtime/gates/. Research outcome (SUPPORTED/REFUTED/...) and engineering
acceptance (ACCEPT/REJECT/ABSTAIN) are permanently separate namespaces.

Like nogap_memory.py (M7-I), this module follows the STRICTER malformed-record
convention: list_* functions here raise on unparseable JSON rather than silently
skipping it (unlike the older list_artifacts/list_failures precedent) - a corrupted
authoritative research record must never just quietly vanish from a query.

Records are append-oriented: a ClaimAssessment is never edited or deleted once
written; a REFUTED or INCONCLUSIVE result stays permanently queryable via
claim["assessment_refs"] even after a later assessment reports SUPPORTED for a
revised claim/protocol. A frozen ResearchProtocol's research-critical fields
(primary_metric, baseline_refs, dataset_refs/data_provenance, split_strategy,
seed_policy, success/failure/inconclusive_criteria, required_validation_level) can
only change through amend_protocol(), which records old/new values and - if any
result already existed for the protocol at amendment time - forces
result_known_at_amendment=True and labels the amendment POST_RESULT. A POST_RESULT
amendment changes the LIVE protocol for future experiments; it can never rewrite an
assessment record that already exists (those are immutable, and each captures its own
protocol_snapshot at assessment time).
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from statistics import mean
from typing import Any

from nogap_artifacts import load_artifact, list_artifacts
from nogap_methodology import (
    MethodologyValidationError,
    _now,
    _require,
    _require_state,
    load_methodology,
    load_state,
    methodology_state_dir,
)

SCHEMA_VERSION = "1.0.0"

# --- vocabularies -----------------------------------------------------------

QUESTION_STATUSES = {"OPEN", "ACTIVE", "ANSWERED", "INCONCLUSIVE", "CLOSED", "ABANDONED"}
QUESTION_TERMINAL = {"ANSWERED", "INCONCLUSIVE", "CLOSED", "ABANDONED"}

HYPOTHESIS_STATUSES = {"DRAFT", "REGISTERED", "UNDER_TEST", "ASSESSED", "SUPERSEDED", "ABANDONED"}

PROTOCOL_STATUSES = {"DRAFT", "FROZEN", "EXECUTED", "SUPERSEDED", "ABANDONED"}
# Research-critical fields: immutable once FROZEN except through amend_protocol().
PROTOCOL_CRITICAL_FIELDS = {
    "primary_metric", "baseline_refs", "dataset_refs", "data_provenance", "split_strategy",
    "seed_policy", "success_criteria", "failure_criteria", "inconclusive_criteria",
    "required_validation_level",
}
PROTOCOL_FREEZE_REQUIRED_FIELDS = {"primary_metric", "success_criteria", "failure_criteria", "inconclusive_criteria"}

EXPERIMENT_STATUSES = {"PLANNED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "INCONCLUSIVE"}

CLAIM_TYPES = {
    "EMPIRICAL", "COMPARATIVE", "PERFORMANCE", "CORRECTNESS", "ROBUSTNESS",
    "SCIENTIFIC", "ARCHITECTURAL", "OPERATIONAL",
}
CLAIM_STRENGTHS = {"LOW", "MEDIUM", "HIGH"}
CLAIM_STATUSES = {"DRAFT", "ASSESSED", "SUPERSEDED", "ABANDONED"}

ASSESSMENT_OUTCOMES = {"SUPPORTED", "PARTIALLY_SUPPORTED", "REFUTED", "INCONCLUSIVE"}
ASSESSOR_ROLES = {"SELF", "INDEPENDENT", "HUMAN", "SYSTEM_DETERMINISTIC"}
INDEPENDENT_ASSESSOR_ROLES = {"INDEPENDENT", "HUMAN", "SYSTEM_DETERMINISTIC"}
ANALYSIS_MODES = {"PREREGISTERED", "EXPLORATORY", "POST_HOC"}
REPRODUCIBILITY_STATUSES = {
    "NOT_REQUIRED", "NOT_ATTEMPTED", "REPRODUCED", "NOT_REPRODUCED", "PARTIALLY_REPRODUCED", "INCONCLUSIVE",
}
COMPARATORS = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
               "<=": lambda a, b: a <= b, "==": lambda a, b: a == b}

_ID_PREFIXES = {
    "questions": "RQ", "hypotheses": "HYP", "protocols": "PROTO",
    "experiments": "EXP", "observations": "OBS", "claims": "CLAIM", "assessments": "ASSESS",
}
_ID_FIELDS = {
    "questions": "question_id", "hypotheses": "hypothesis_id", "protocols": "protocol_id",
    "experiments": "experiment_id", "observations": "observation_id", "claims": "claim_id",
    "assessments": "assessment_id",
}


# --- storage -----------------------------------------------------------------

def research_dir(project: Path) -> Path:
    return methodology_state_dir(project) / "research"


def _kind_dir(project: Path, kind: str) -> Path:
    return research_dir(project) / kind


def _load_json_dir_strict(directory: Path) -> list[dict[str, Any]]:
    """Malformed records are never silently dropped - the stricter M7-I convention,
    not the older list_artifacts/list_failures silent-skip precedent."""
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MethodologyValidationError(f"research: unreadable/malformed record {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise MethodologyValidationError(f"research: record {path} must contain a JSON object")
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


# --- generic load/list per kind ------------------------------------------------

def load_research_question(project: Path, question_id: str) -> dict[str, Any] | None:
    return _load_one(project, "questions", "question_id", question_id)


def list_research_questions(project: Path, status: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "questions"))
    return [r for r in records if status is None or r.get("status") == status]


def load_hypothesis(project: Path, hypothesis_id: str) -> dict[str, Any] | None:
    return _load_one(project, "hypotheses", "hypothesis_id", hypothesis_id)


def list_hypotheses(project: Path, question_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "hypotheses"))
    if question_id is not None:
        records = [r for r in records if r.get("question_id") == question_id]
    if status is not None:
        records = [r for r in records if r.get("status") == status]
    return records


def load_protocol(project: Path, protocol_id: str) -> dict[str, Any] | None:
    return _load_one(project, "protocols", "protocol_id", protocol_id)


def list_protocols(project: Path, question_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "protocols"))
    if question_id is not None:
        records = [r for r in records if r.get("question_id") == question_id]
    if status is not None:
        records = [r for r in records if r.get("status") == status]
    return records


def load_experiment(project: Path, experiment_id: str) -> dict[str, Any] | None:
    return _load_one(project, "experiments", "experiment_id", experiment_id)


def list_experiments(project: Path, protocol_id: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "experiments"))
    if protocol_id is not None:
        records = [r for r in records if r.get("protocol_id") == protocol_id]
    return records


def load_observation(project: Path, observation_id: str) -> dict[str, Any] | None:
    return _load_one(project, "observations", "observation_id", observation_id)


def list_observations(project: Path, experiment_id: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "observations"))
    if experiment_id is not None:
        records = [r for r in records if r.get("experiment_id") == experiment_id]
    return records


def load_claim(project: Path, claim_id: str) -> dict[str, Any] | None:
    return _load_one(project, "claims", "claim_id", claim_id)


def list_claims(project: Path, question_id: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "claims"))
    if question_id is not None:
        records = [r for r in records if r.get("question_id") == question_id]
    return records


def load_assessment(project: Path, assessment_id: str) -> dict[str, Any] | None:
    return _load_one(project, "assessments", "assessment_id", assessment_id)


def list_assessments(project: Path, claim_id: str | None = None) -> list[dict[str, Any]]:
    records = _load_json_dir_strict(_kind_dir(project, "assessments"))
    if claim_id is not None:
        records = [r for r in records if r.get("claim_id") == claim_id]
    return records


def _load_one(project: Path, kind: str, id_field: str, record_id: str) -> dict[str, Any] | None:
    path = _kind_dir(project, kind) / f"{record_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MethodologyValidationError(f"research: {path} is invalid JSON: {exc}") from exc
    _require(isinstance(data, dict), f"research: {path} must be a JSON object")
    return data


def _load_or_raise(project: Path, loader, record_id: str, label: str) -> dict[str, Any]:
    record = loader(project, record_id)
    if record is None:
        raise MethodologyValidationError(f"research: unknown {label} {record_id!r}")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise MethodologyValidationError(
            f"research: {label} {record_id!r} has unsupported schema_version {record.get('schema_version')!r} "
            f"(expected {SCHEMA_VERSION!r})"
        )
    definition = load_methodology()
    if record.get("methodology_version") != definition.version:
        raise MethodologyValidationError(
            f"research: {label} {record_id!r} was recorded under methodology v{record.get('methodology_version')}, "
            f"current is v{definition.version}"
        )
    return record


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


def _check_requirement_refs(project: Path, refs: list[str]) -> list[str]:
    requirements = list_artifacts(project, artifact_type="P6_REQUIREMENT")
    known = {r["fields"].get("requirement_id") for r in requirements}
    return [ref for ref in refs if ref not in known]


def _check_failure_refs(project: Path, refs: list[str]) -> list[str]:
    if not refs:
        return []
    failures_dir = project.resolve() / ".code-loop" / "methodology" / "failures"
    known = {p.stem for p in failures_dir.glob("*.json")} if failures_dir.is_dir() else set()
    return [ref for ref in refs if ref not in known]


def _check_question_refs(project: Path, refs: list[str]) -> list[str]:
    return [ref for ref in refs if load_research_question(project, ref) is None]


def _check_hypothesis_refs(project: Path, refs: list[str]) -> list[str]:
    return [ref for ref in refs if load_hypothesis(project, ref) is None]


def _check_protocol_refs(project: Path, refs: list[str]) -> list[str]:
    return [ref for ref in refs if load_protocol(project, ref) is None]


def _check_experiment_refs(project: Path, refs: list[str]) -> list[str]:
    return [ref for ref in refs if load_experiment(project, ref) is None]


def _check_observation_refs(project: Path, refs: list[str]) -> list[str]:
    return [ref for ref in refs if load_observation(project, ref) is None]


# --- ResearchQuestion ----------------------------------------------------------

def create_research_question(
    project: Path, *, title: str, question: str, actor: str, reason: str,
    scope: str | None = None, project_id: str | None = None,
    related_requirement_refs: list[str] = (), related_artifact_refs: list[str] = (),
    related_failure_refs: list[str] = (), source_refs: list[str] = (), question_id: str | None = None,
) -> dict[str, Any]:
    _require(bool(title and title.strip()), "create_research_question requires a non-empty title")
    _require(bool(question and question.strip()), "create_research_question requires a non-empty question")
    _require(bool(actor and actor.strip()), "create_research_question requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "create_research_question requires a non-empty reason")
    definition = load_methodology()

    unresolved = (
        _check_requirement_refs(project, list(related_requirement_refs))
        + _check_artifact_refs(project, list(related_artifact_refs))
        + _check_failure_refs(project, list(related_failure_refs))
    )
    if unresolved:
        raise MethodologyValidationError(f"research: unresolved reference(s): {unresolved}")

    question_id = question_id or _next_id(project, "questions")
    if load_research_question(project, question_id) is not None:
        raise MethodologyValidationError(f"research: duplicate question_id: {question_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "question_id": question_id, "schema_version": SCHEMA_VERSION, "methodology_version": definition.version, "project_id": project_id,
        "title": title.strip(), "question": question.strip(), "scope": scope, "status": "OPEN",
        "created_at": timestamp, "created_by": actor.strip(), "actor_id": actor.strip(), "reason": reason.strip(),
        "related_requirement_refs": list(related_requirement_refs), "related_artifact_refs": list(related_artifact_refs),
        "related_failure_refs": list(related_failure_refs), "source_refs": list(source_refs),
        "updated_at": timestamp, "history": [],
    }
    _append_history(record, "CREATED", actor, reason)
    return _save(project, "questions", record, "question_id")


def set_question_status(project: Path, question_id: str, status: str, *, actor: str, reason: str) -> dict[str, Any]:
    _require(status in QUESTION_STATUSES, f"research: unknown question status: {status!r}")
    record = _load_or_raise(project, load_research_question, question_id, "question_id")
    _require(bool(actor and actor.strip()), "set_question_status requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "set_question_status requires a non-empty reason")
    if record["status"] in QUESTION_TERMINAL:
        raise MethodologyValidationError(
            f"research: question {question_id} is already terminal ({record['status']!r}) - illegal state jump rejected"
        )
    record["status"] = status
    _append_history(record, "STATUS_CHANGED", actor, reason, new_status=status)
    return _save(project, "questions", record, "question_id")


# --- HypothesisRecord ----------------------------------------------------------

def _question_has_prior_results(project: Path, question_id: str, hypothesis_id: str | None = None) -> bool:
    """Whether any experiment/observation/assessment already exists for this
    question (or, once known, this hypothesis specifically) - the honesty check
    register_hypothesis() uses to refuse fabricated preregistration."""
    protocol_ids = {p["protocol_id"] for p in list_protocols(project, question_id=question_id)}
    experiments = [e for e in list_experiments(project) if e.get("protocol_id") in protocol_ids]
    if hypothesis_id:
        experiments = experiments + [e for e in list_experiments(project) if hypothesis_id in (e.get("hypothesis_refs") or [])]
    if any(e.get("status") in {"COMPLETED", "FAILED", "INCONCLUSIVE"} for e in experiments):
        return True
    experiment_ids = {e["experiment_id"] for e in experiments}
    if any(o.get("experiment_id") in experiment_ids for o in list_observations(project)):
        return True
    claims = list_claims(project, question_id=question_id)
    for claim in claims:
        if hypothesis_id and hypothesis_id not in (claim.get("hypothesis_refs") or []):
            continue
        if list_assessments(project, claim_id=claim["claim_id"]):
            return True
    return False


def create_hypothesis(
    project: Path, *, question_id: str, statement: str, actor: str, reason: str,
    direction: str | None = None, expected_effect: str | None = None,
    null_hypothesis: str | None = None, alternative_hypothesis: str | None = None,
    hypothesis_id: str | None = None,
) -> dict[str, Any]:
    _require(bool(statement and statement.strip()), "create_hypothesis requires a non-empty statement")
    _require(bool(actor and actor.strip()), "create_hypothesis requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "create_hypothesis requires a non-empty reason")
    question = _load_or_raise(project, load_research_question, question_id, "question_id")
    definition = load_methodology()

    hypothesis_id = hypothesis_id or _next_id(project, "hypotheses")
    if load_hypothesis(project, hypothesis_id) is not None:
        raise MethodologyValidationError(f"research: duplicate hypothesis_id: {hypothesis_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "hypothesis_id": hypothesis_id, "question_id": question["question_id"], "schema_version": SCHEMA_VERSION, "methodology_version": definition.version,
        "statement": statement.strip(), "direction": direction, "expected_effect": expected_effect,
        "null_hypothesis": null_hypothesis, "alternative_hypothesis": alternative_hypothesis,
        "status": "DRAFT", "created_at": timestamp, "created_by": actor.strip(), "actor_id": actor.strip(),
        "preregistered": False, "preregistered_at": None, "analysis_mode": None, "protocol_ref": None,
        "evidence_refs": [], "assessment_refs": [], "supersedes": None, "superseded_by": None,
        "updated_at": timestamp, "history": [],
    }
    _append_history(record, "CREATED", actor, reason)
    return _save(project, "hypotheses", record, "hypothesis_id")


def register_hypothesis(
    project: Path, hypothesis_id: str, *, actor: str, reason: str,
    preregistered: bool = True, protocol_ref: str | None = None,
) -> dict[str, Any]:
    """Fails closed rather than silently downgrading: requesting preregistered=True
    when prior results already exist for this question/hypothesis is rejected
    outright - a fabricated preregistration must never look honest. Call again with
    preregistered=False (an honest POST_HOC registration) instead."""
    record = _load_or_raise(project, load_hypothesis, hypothesis_id, "hypothesis_id")
    _require(record["status"] in {"DRAFT", "REGISTERED"}, f"research: cannot register hypothesis from status {record['status']!r}")
    _require(bool(actor and actor.strip()), "register_hypothesis requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "register_hypothesis requires a non-empty reason")
    if protocol_ref is not None and load_protocol(project, protocol_ref) is None:
        raise MethodologyValidationError(f"research: unknown protocol_ref: {protocol_ref!r}")

    has_prior_results = _question_has_prior_results(project, record["question_id"], hypothesis_id)
    if preregistered and has_prior_results:
        raise MethodologyValidationError(
            f"research: hypothesis {hypothesis_id} cannot be marked preregistered - results already exist for "
            f"question {record['question_id']!r} (or this hypothesis); register with preregistered=False instead"
        )

    record["status"] = "REGISTERED"
    record["preregistered"] = bool(preregistered)
    record["preregistered_at"] = _now() if preregistered else None
    record["analysis_mode"] = "PREREGISTERED" if preregistered else "POST_HOC"
    record["protocol_ref"] = protocol_ref
    _append_history(record, "REGISTERED", actor, reason, preregistered=bool(preregistered))
    return _save(project, "hypotheses", record, "hypothesis_id")


def mark_superseded(project: Path, kind: str, record_id: str, *, superseded_by: str, actor: str, reason: str) -> dict[str, Any]:
    """Shared supersession helper for hypotheses/protocols/claims - records
    supersedes/superseded_by without ever mutating the superseded record's own
    substantive fields or deleting it."""
    loaders = {"hypotheses": (load_hypothesis, "hypothesis_id"), "protocols": (load_protocol, "protocol_id"), "claims": (load_claim, "claim_id")}
    _require(kind in loaders, f"research: unknown supersession kind: {kind!r}")
    loader, id_field = loaders[kind]
    record = _load_or_raise(project, loader, record_id, id_field)
    _require(bool(actor and actor.strip()), "mark_superseded requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "mark_superseded requires a non-empty reason")
    record["status"] = "SUPERSEDED"
    record["superseded_by"] = superseded_by
    _append_history(record, "SUPERSEDED", actor, reason, superseded_by=superseded_by)
    return _save(project, kind, record, id_field)


# --- ResearchProtocol ----------------------------------------------------------

def create_protocol(
    project: Path, *, question_id: str, objective: str, actor: str, reason: str,
    hypothesis_refs: list[str] = (), primary_metric: str | None = None, secondary_metrics: list[str] = (),
    baseline_refs: list[str] = (), dataset_refs: list[str] = (), data_provenance: dict[str, Any] | None = None,
    split_strategy: str | None = None, seed_policy: dict[str, Any] | None = None, random_seeds: list[int] = (),
    evaluation_method: str | None = None, success_criteria: list[dict[str, Any]] = (),
    failure_criteria: list[dict[str, Any]] = (), inconclusive_criteria: list[dict[str, Any]] = (),
    leakage_controls: list[str] = (), required_evidence_kinds: list[str] = (),
    required_validation_level: str | None = None, claim_strength: str = "LOW", protocol_id: str | None = None,
) -> dict[str, Any]:
    _require(bool(objective and objective.strip()), "create_protocol requires a non-empty objective")
    _require(bool(actor and actor.strip()), "create_protocol requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "create_protocol requires a non-empty reason")
    _require(claim_strength in CLAIM_STRENGTHS, f"research: unknown claim_strength: {claim_strength!r}")
    question = _load_or_raise(project, load_research_question, question_id, "question_id")
    unresolved = _check_hypothesis_refs(project, list(hypothesis_refs)) + _check_artifact_refs(project, list(baseline_refs) + list(dataset_refs))
    if unresolved:
        raise MethodologyValidationError(f"research: unresolved reference(s): {unresolved}")
    definition = load_methodology()

    protocol_id = protocol_id or _next_id(project, "protocols")
    if load_protocol(project, protocol_id) is not None:
        raise MethodologyValidationError(f"research: duplicate protocol_id: {protocol_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "protocol_id": protocol_id, "question_id": question["question_id"], "hypothesis_refs": list(hypothesis_refs),
        "schema_version": SCHEMA_VERSION, "methodology_version": definition.version, "objective": objective.strip(),
        "primary_metric": primary_metric, "secondary_metrics": list(secondary_metrics),
        "baseline_refs": list(baseline_refs), "dataset_refs": list(dataset_refs), "data_provenance": data_provenance,
        "split_strategy": split_strategy, "seed_policy": seed_policy, "random_seeds": list(random_seeds),
        "evaluation_method": evaluation_method, "success_criteria": list(success_criteria),
        "failure_criteria": list(failure_criteria), "inconclusive_criteria": list(inconclusive_criteria),
        "leakage_controls": list(leakage_controls), "required_evidence_kinds": list(required_evidence_kinds),
        "required_validation_level": required_validation_level, "claim_strength": claim_strength,
        "created_at": timestamp, "created_by": actor.strip(), "actor_id": actor.strip(),
        "frozen_at": None, "status": "DRAFT", "amendments": [], "supersedes": None, "superseded_by": None,
        "updated_at": timestamp, "history": [],
    }
    _append_history(record, "CREATED", actor, reason)
    return _save(project, "protocols", record, "protocol_id")


def freeze_protocol(project: Path, protocol_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    record = _load_or_raise(project, load_protocol, protocol_id, "protocol_id")
    _require(record["status"] == "DRAFT", f"research: cannot freeze protocol from status {record['status']!r}")
    _require(bool(actor and actor.strip()), "freeze_protocol requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "freeze_protocol requires a non-empty reason")

    missing = [f for f in PROTOCOL_FREEZE_REQUIRED_FIELDS if not record.get(f)]
    if missing:
        raise MethodologyValidationError(f"research: protocol {protocol_id} cannot freeze - missing required field(s): {sorted(missing)}")

    record["status"] = "FROZEN"
    record["frozen_at"] = _now()
    _append_history(record, "FROZEN", actor, reason)
    return _save(project, "protocols", record, "protocol_id")


def amend_protocol(
    project: Path, protocol_id: str, *, field_updates: dict[str, Any], actor: str, reason: str, authority: str = "human",
) -> dict[str, Any]:
    """Applies to the LIVE protocol going forward. Never rewrites an assessment
    already made (those are immutable and carry their own protocol_snapshot). If any
    result already existed for this protocol at amendment time, the amendment is
    forced POST_RESULT - a post-result amendment can change what FUTURE experiments
    use, but can never retroactively relabel an existing assessment as preregistered."""
    record = _load_or_raise(project, load_protocol, protocol_id, "protocol_id")
    _require(record["status"] in {"FROZEN", "EXECUTED"}, f"research: amend_protocol only applies to a frozen protocol (status={record['status']!r})")
    _require(bool(field_updates), "amend_protocol requires at least one field update")
    _require(bool(actor and actor.strip()), "amend_protocol requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "amend_protocol requires a non-empty reason")
    unknown_fields = set(field_updates) - PROTOCOL_CRITICAL_FIELDS
    _require(not unknown_fields, f"research: amend_protocol only covers research-critical fields, unknown: {sorted(unknown_fields)}")

    result_known = bool(list_experiments(project, protocol_id=protocol_id)) or bool(
        [c for c in list_claims(project) if protocol_id in (c.get("protocol_refs") or []) and list_assessments(project, claim_id=c["claim_id"])]
    )
    old_values = {field: record.get(field) for field in field_updates}
    amendment = {
        "amendment_id": f"AMEND-{len(record['amendments']) + 1:03d}", "actor_id": actor.strip(), "reason": reason.strip(),
        "timestamp": _now(), "fields_changed": sorted(field_updates), "old_values": old_values, "new_values": dict(field_updates),
        "result_known_at_amendment": result_known, "authority": authority,
        "post_result": result_known,
    }
    record["amendments"].append(amendment)
    for field, value in field_updates.items():
        record[field] = value
    _append_history(record, "AMENDED", actor, reason, amendment_id=amendment["amendment_id"], post_result=result_known)
    return _save(project, "protocols", record, "protocol_id")


# --- ExperimentRecord ----------------------------------------------------------

def create_experiment(
    project: Path, *, protocol_id: str, actor: str, reason: str, hypothesis_refs: list[str] = (),
    candidate_id: str | None = None, task_id: str | None = None, environment: str | None = None,
    dataset_fingerprint: str | None = None, code_revision: str | None = None, seed_values: list[int] = (),
    execution_refs: list[str] = (), artifact_refs: list[str] = (), evidence_refs: list[str] = (),
    experiment_id: str | None = None,
) -> dict[str, Any]:
    _require(bool(actor and actor.strip()), "create_experiment requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "create_experiment requires a non-empty reason")
    protocol = _load_or_raise(project, load_protocol, protocol_id, "protocol_id")
    _require(protocol["status"] in {"FROZEN", "EXECUTED"}, f"research: experiment requires a frozen protocol (status={protocol['status']!r})")
    unresolved = (
        _check_hypothesis_refs(project, list(hypothesis_refs))
        + _check_evidence_refs(project, list(evidence_refs))
        + _check_artifact_refs(project, list(artifact_refs))
    )
    if unresolved:
        raise MethodologyValidationError(f"research: unresolved reference(s): {unresolved}")
    if task_id is not None:
        known_tasks = {r["fields"].get("task_id") for r in list_artifacts(project, artifact_type="P12_TASK_CONTRACT")}
        _require(task_id in known_tasks, f"research: unknown task_id: {task_id!r}")
    definition = load_methodology()

    experiment_id = experiment_id or _next_id(project, "experiments")
    if load_experiment(project, experiment_id) is not None:
        raise MethodologyValidationError(f"research: duplicate experiment_id: {experiment_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "experiment_id": experiment_id, "protocol_id": protocol["protocol_id"], "hypothesis_refs": list(hypothesis_refs),
        "schema_version": SCHEMA_VERSION, "methodology_version": definition.version, "candidate_id": candidate_id, "task_id": task_id,
        "started_at": timestamp, "completed_at": None, "actor_id": actor.strip(),
        "execution_refs": list(execution_refs), "artifact_refs": list(artifact_refs), "evidence_refs": list(evidence_refs),
        "environment": environment, "dataset_fingerprint": dataset_fingerprint, "code_revision": code_revision,
        "seed_values": list(seed_values), "status": "PLANNED", "updated_at": timestamp, "history": [],
    }
    _append_history(record, "CREATED", actor, reason)
    saved = _save(project, "experiments", record, "experiment_id")
    if protocol["status"] == "FROZEN":
        protocol["status"] = "EXECUTED"
        _append_history(protocol, "EXECUTED", actor, f"experiment {experiment_id} created")
        _save(project, "protocols", protocol, "protocol_id")
    return saved


def record_experiment_result(
    project: Path, experiment_id: str, *, status: str, actor: str, reason: str,
    execution_refs: list[str] = (), evidence_refs: list[str] = (),
) -> dict[str, Any]:
    """process failure is recorded as an ExperimentRecord status only - it never by
    itself creates or implies any ClaimAssessment outcome (M6 ProcessOutcome
    semantics stay authoritative for execution; research REFUTED requires its own,
    separate, evidence-based assess_claim() call)."""
    _require(status in EXPERIMENT_STATUSES, f"research: unknown experiment status: {status!r}")
    record = _load_or_raise(project, load_experiment, experiment_id, "experiment_id")
    _require(record["status"] in {"PLANNED", "RUNNING"}, f"research: cannot record result from status {record['status']!r}")
    _require(bool(actor and actor.strip()), "record_experiment_result requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "record_experiment_result requires a non-empty reason")
    unresolved = _check_evidence_refs(project, list(evidence_refs))
    if unresolved:
        raise MethodologyValidationError(f"research: unresolved evidence reference(s): {unresolved}")

    record["status"] = status
    record["completed_at"] = _now()
    record["execution_refs"] = sorted(set(record["execution_refs"]) | set(execution_refs))
    record["evidence_refs"] = sorted(set(record["evidence_refs"]) | set(evidence_refs))
    _append_history(record, "RESULT_RECORDED", actor, reason, status=status)
    return _save(project, "experiments", record, "experiment_id")


# --- ObservationRecord ----------------------------------------------------------

def record_observation(
    project: Path, *, experiment_id: str, metric_name: str, metric_value: float, actor: str, reason: str,
    metric_unit: str | None = None, dataset_or_slice: str | None = None, sample_size: int | None = None,
    seed: int | None = None, aggregation: str | None = None, uncertainty: float | None = None,
    confidence_interval: list[float] | None = None, raw_evidence_refs: list[str] = (),
    notes: str | None = None, observation_id: str | None = None,
) -> dict[str, Any]:
    """Structured facts only: 'what was measured', never 'what it proves' - there is
    no free-text interpretation field that could smuggle in an unbacked claim like
    "Model A is clearly better"."""
    _require(bool(metric_name and metric_name.strip()), "record_observation requires a non-empty metric_name")
    _require(isinstance(metric_value, (int, float)), "record_observation requires a numeric metric_value")
    _require(bool(actor and actor.strip()), "record_observation requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "record_observation requires a non-empty reason")
    experiment = _load_or_raise(project, load_experiment, experiment_id, "experiment_id")
    protocol = load_protocol(project, experiment["protocol_id"])

    if protocol and protocol.get("required_evidence_kinds"):
        _require(bool(raw_evidence_refs), "research: this protocol requires evidence provenance for every observation")
    unresolved = _check_evidence_refs(project, list(raw_evidence_refs))
    if unresolved:
        raise MethodologyValidationError(f"research: unresolved evidence reference(s): {unresolved}")
    definition = load_methodology()

    observation_id = observation_id or _next_id(project, "observations")
    if load_observation(project, observation_id) is not None:
        raise MethodologyValidationError(f"research: duplicate observation_id: {observation_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "observation_id": observation_id, "experiment_id": experiment["experiment_id"], "schema_version": SCHEMA_VERSION, "methodology_version": definition.version,
        "metric_name": metric_name.strip(), "metric_value": metric_value, "metric_unit": metric_unit,
        "dataset_or_slice": dataset_or_slice, "sample_size": sample_size, "seed": seed, "aggregation": aggregation,
        "uncertainty": uncertainty, "confidence_interval": list(confidence_interval) if confidence_interval else None,
        "raw_evidence_refs": list(raw_evidence_refs), "observed_at": timestamp, "actor_id": actor.strip(), "notes": notes,
        "updated_at": timestamp, "history": [],
    }
    _append_history(record, "RECORDED", actor, reason)
    return _save(project, "observations", record, "observation_id")


# --- ClaimRecord -----------------------------------------------------------------

def create_claim(
    project: Path, *, question_id: str, statement: str, claim_type: str, claim_strength: str, scope: str,
    actor: str, reason: str, hypothesis_refs: list[str] = (), protocol_refs: list[str] = (),
    baseline_ref: str | None = None, baseline_version: str | None = None, baseline_metric: float | None = None,
    candidate_metric: float | None = None, comparison_method: str | None = None, claim_id: str | None = None,
) -> dict[str, Any]:
    _require(bool(statement and statement.strip()), "create_claim requires a non-empty statement")
    _require(claim_type in CLAIM_TYPES, f"research: unknown claim_type: {claim_type!r}")
    _require(claim_strength in CLAIM_STRENGTHS, f"research: unknown claim_strength: {claim_strength!r}")
    _require(bool(scope and scope.strip()), "create_claim requires a non-empty scope (avoid an unscoped universal claim)")
    _require(bool(actor and actor.strip()), "create_claim requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "create_claim requires a non-empty reason")
    if claim_type == "COMPARATIVE":
        _require(bool(baseline_ref and str(baseline_ref).strip()), "research: a COMPARATIVE claim requires a baseline_ref")
    question = _load_or_raise(project, load_research_question, question_id, "question_id")
    unresolved = _check_hypothesis_refs(project, list(hypothesis_refs)) + _check_protocol_refs(project, list(protocol_refs))
    if unresolved:
        raise MethodologyValidationError(f"research: unresolved reference(s): {unresolved}")
    definition = load_methodology()

    claim_id = claim_id or _next_id(project, "claims")
    if load_claim(project, claim_id) is not None:
        raise MethodologyValidationError(f"research: duplicate claim_id: {claim_id}")

    timestamp = _now()
    record: dict[str, Any] = {
        "claim_id": claim_id, "question_id": question["question_id"], "schema_version": SCHEMA_VERSION, "methodology_version": definition.version,
        "hypothesis_refs": list(hypothesis_refs),
        "statement": statement.strip(), "claim_type": claim_type, "claim_strength": claim_strength, "scope": scope.strip(),
        "created_at": timestamp, "created_by": actor.strip(), "actor_id": actor.strip(),
        "protocol_refs": list(protocol_refs), "experiment_refs": [], "evidence_refs": [], "assessment_refs": [],
        "baseline_ref": baseline_ref, "baseline_version": baseline_version, "baseline_metric": baseline_metric,
        "candidate_metric": candidate_metric, "comparison_method": comparison_method,
        "status": "DRAFT", "supersedes": None, "superseded_by": None, "updated_at": timestamp, "history": [],
    }
    _append_history(record, "CREATED", actor, reason)
    return _save(project, "claims", record, "claim_id")


# --- criteria evaluation ---------------------------------------------------------

def _evaluate_criterion(criterion: dict[str, Any], observations: list[dict[str, Any]], claim: dict[str, Any]) -> dict[str, Any]:
    metric = criterion.get("metric")
    comparator = COMPARATORS.get(criterion.get("comparator"))
    aggregation = criterion.get("aggregation", "all")
    matching = [o for o in observations if o.get("metric_name") == metric]
    if not matching or comparator is None:
        return {"metric": metric, "comparator": criterion.get("comparator"), "aggregation": aggregation,
                "passed": False, "had_data": False, "detail": f"no observations for metric {metric!r}"}

    target = claim.get("baseline_metric") if criterion.get("vs_baseline") else criterion.get("value")
    if target is None:
        return {"metric": metric, "comparator": criterion.get("comparator"), "aggregation": aggregation,
                "passed": False, "had_data": False, "detail": "no comparison target (missing baseline_metric or value)"}

    values = [o["metric_value"] for o in matching]
    if aggregation == "mean":
        passed = comparator(mean(values), target)
        detail = f"mean({values})={mean(values)} vs {target}"
    elif aggregation == "any":
        passed = any(comparator(v, target) for v in values)
        detail = f"any({values}) vs {target}"
    else:  # "all"
        passed = all(comparator(v, target) for v in values)
        detail = f"all({values}) vs {target}"
    return {"metric": metric, "comparator": criterion.get("comparator"), "aggregation": aggregation,
            "passed": passed, "had_data": True, "detail": detail}


def _check_seed_coverage(protocol: dict[str, Any] | None, observations: list[dict[str, Any]]) -> list[str]:
    if not protocol or not protocol.get("random_seeds"):
        return []
    required_seeds = set(protocol["random_seeds"])
    primary_metric = protocol.get("primary_metric")
    observed_seeds = {o.get("seed") for o in observations if o.get("metric_name") == primary_metric and o.get("seed") is not None}
    missing = sorted(required_seeds - observed_seeds)
    if missing:
        return [f"missing observations for required seed(s) {missing} (protocol requires {sorted(required_seeds)})"]
    return []


def _staleness_reasons(project: Path, experiments: list[dict[str, Any]], protocol: dict[str, Any] | None) -> list[str]:
    """Reuses M7-G's own staleness precondition rather than re-deriving one, only
    where the protocol's required_validation_level actually implies it matters."""
    if not protocol or protocol.get("required_validation_level") not in {"LEVEL_2_REPRESENTATIVE", "LEVEL_3_DIFFICULT"}:
        return []
    reasons = []
    for experiment in experiments:
        task_id = experiment.get("task_id")
        if not task_id:
            continue
        import nogap_verify_binding as vb
        precondition = vb.verification_acceptance_precondition(project, task_id)
        if not precondition["satisfied"]:
            reasons.append(f"experiment {experiment['experiment_id']}: methodology verification not current: {precondition['reason']}")
    return reasons


# --- ClaimAssessment ---------------------------------------------------------

def assess_claim(
    project: Path, claim_id: str, *, outcome: str, rationale: str, actor: str, reason: str,
    assessor_id: str, assessor_role: str = "SELF",
    protocol_refs: list[str] = (), experiment_refs: list[str] = (), observation_refs: list[str] = (),
    evidence_refs: list[str] = (), hypothesis_refs: list[str] = (),
    limitations: list[str] = (), confounders: list[str] = (), validity_notes: str | None = None,
    reproducibility_status: str = "NOT_REQUIRED", analysis_mode: str = "PREREGISTERED", assessment_id: str | None = None,
) -> dict[str, Any]:
    """The one place research outcome preconditions are enforced. Fails closed
    (raises) rather than silently downgrading a dishonestly-requested outcome - the
    caller must supply an outcome the evidence actually supports."""
    _require(outcome in ASSESSMENT_OUTCOMES, f"research: unknown outcome: {outcome!r}")
    _require(assessor_role in ASSESSOR_ROLES, f"research: unknown assessor_role: {assessor_role!r}")
    _require(reproducibility_status in REPRODUCIBILITY_STATUSES, f"research: unknown reproducibility_status: {reproducibility_status!r}")
    _require(analysis_mode in ANALYSIS_MODES, f"research: unknown analysis_mode: {analysis_mode!r}")
    _require(bool(rationale and rationale.strip()), "assess_claim requires a non-empty rationale")
    _require(bool(actor and actor.strip()), "assess_claim requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "assess_claim requires a non-empty reason")
    _require(bool(assessor_id and assessor_id.strip()), "assess_claim requires a non-empty assessor_id")

    claim = _load_or_raise(project, load_claim, claim_id, "claim_id")
    protocol_refs = list(protocol_refs) or list(claim.get("protocol_refs") or [])
    unresolved = (
        _check_protocol_refs(project, protocol_refs)
        + _check_experiment_refs(project, list(experiment_refs))
        + _check_observation_refs(project, list(observation_refs))
        + _check_evidence_refs(project, list(evidence_refs))
        + _check_hypothesis_refs(project, list(hypothesis_refs))
    )
    if unresolved:
        raise MethodologyValidationError(f"research: unresolved reference(s): {unresolved}")

    protocol = load_protocol(project, protocol_refs[0]) if protocol_refs else None
    experiments = [load_experiment(project, eid) for eid in experiment_refs]
    observations = [load_observation(project, oid) for oid in observation_refs]
    independence = assessor_role in INDEPENDENT_ASSESSOR_ROLES

    criteria_results: list[dict[str, Any]] = []
    if protocol and protocol.get("success_criteria"):
        criteria_results = [_evaluate_criterion(c, observations, claim) for c in protocol["success_criteria"]]
    seed_coverage_reasons = _check_seed_coverage(protocol, observations)
    stale_reasons = _staleness_reasons(project, [e for e in experiments if e], protocol)

    has_observation_data = bool(observations)
    has_evidence = bool(evidence_refs) or any(o.get("raw_evidence_refs") for o in observations)
    all_criteria_passed = bool(criteria_results) and all(c["passed"] for c in criteria_results) and not seed_coverage_reasons
    any_criterion_failed_with_data = any((not c["passed"]) and c["had_data"] for c in criteria_results)
    strength = claim["claim_strength"]
    requires_high_discipline = strength == "HIGH"

    blocking_supported: list[str] = []
    if not has_observation_data:
        blocking_supported.append("no observations referenced")
    if not has_evidence:
        blocking_supported.append("no evidence provenance referenced")
    if claim["claim_type"] == "COMPARATIVE" and not claim.get("baseline_ref"):
        blocking_supported.append("comparative claim has no resolvable baseline")
    if protocol and protocol.get("success_criteria") and not all_criteria_passed:
        blocking_supported.append("protocol success criteria not fully satisfied")
    blocking_supported.extend(seed_coverage_reasons)
    blocking_supported.extend(stale_reasons)
    if requires_high_discipline:
        if reproducibility_status != "REPRODUCED":
            blocking_supported.append("HIGH claim requires REPRODUCED reproducibility_status")
        if not independence:
            blocking_supported.append("HIGH claim requires an independent assessor (assessor_role != SELF)")

    if outcome == "SUPPORTED" and blocking_supported:
        raise MethodologyValidationError(f"research: SUPPORTED rejected for {claim_id}: {blocking_supported}")
    if outcome == "PARTIALLY_SUPPORTED" and not has_observation_data:
        raise MethodologyValidationError(f"research: PARTIALLY_SUPPORTED requires at least some real observation data for {claim_id}")
    if outcome == "REFUTED" and not any_criterion_failed_with_data:
        raise MethodologyValidationError(
            f"research: REFUTED requires actual contradictory evidence for {claim_id} - missing evidence alone must "
            f"produce INCONCLUSIVE, never REFUTED"
        )

    definition = load_methodology()
    assessment_id = assessment_id or _next_id(project, "assessments")
    if load_assessment(project, assessment_id) is not None:
        raise MethodologyValidationError(f"research: duplicate assessment_id: {assessment_id}")

    protocol_snapshot = (
        {field: protocol.get(field) for field in PROTOCOL_CRITICAL_FIELDS | {"protocol_id", "status", "frozen_at"}}
        if protocol else None
    )
    timestamp = _now()
    # A monotonic, engine-assigned creation sequence per claim - never caller-suppliable
    # (unlike assessment_id) - so "current" selection has a real ordering signal even
    # when two assessments land in the same wall-clock second (_now() has 1s
    # resolution). A genuine tie only arises from external tampering with this field.
    sequence = len(list_assessments(project, claim_id=claim["claim_id"])) + 1
    record: dict[str, Any] = {
        "assessment_id": assessment_id, "claim_id": claim["claim_id"], "schema_version": SCHEMA_VERSION, "methodology_version": definition.version,
        "hypothesis_refs": list(hypothesis_refs), "protocol_refs": protocol_refs, "experiment_refs": list(experiment_refs),
        "observation_refs": list(observation_refs), "evidence_refs": list(evidence_refs),
        "assessor_id": assessor_id.strip(), "assessor_role": assessor_role, "created_at": timestamp, "sequence": sequence,
        "outcome": outcome, "rationale": rationale.strip(), "criteria_results": criteria_results,
        "limitations": list(limitations), "confounders": list(confounders), "validity_notes": validity_notes,
        "independence": independence, "staleness_status": "STALE" if stale_reasons else "CURRENT",
        "reproducibility_status": reproducibility_status, "analysis_mode": analysis_mode,
        "protocol_snapshot": protocol_snapshot, "blocking_reasons_considered": blocking_supported,
    }
    _save(project, "assessments", record, "assessment_id")

    claim["assessment_refs"] = claim["assessment_refs"] + [assessment_id]
    claim["experiment_refs"] = sorted(set(claim["experiment_refs"]) | set(experiment_refs))
    claim["evidence_refs"] = sorted(set(claim["evidence_refs"]) | set(evidence_refs))
    claim["status"] = "ASSESSED"
    _append_history(claim, "ASSESSED", actor, reason, assessment_id=assessment_id, outcome=outcome)
    _save(project, "claims", claim, "claim_id")
    return record


def select_current_assessment(assessments: list[dict[str, Any]]) -> dict[str, Any]:
    """The single authoritative implementation of "which assessment is current" -
    pure and deterministic over an already-loaded list of assessments for ONE claim.
    nogap_research.py is the sole owner of this semantic; nothing outside this module
    may re-derive it. Ordered by the engine-assigned monotonic `sequence` (never by
    created_at alone - _now() has 1-second resolution, so same-second calls would
    otherwise collide - and never by assessment_id/filesystem order, which a caller
    can influence via an explicit assessment_id). CONFLICT (never an arbitrary pick)
    if two assessments genuinely tie on sequence, which only external tampering can
    produce in the normal API path.

    Any caller that already has a project's assessments loaded (e.g. nogap_memory.py's
    Memory Projector, which collects them once for fingerprinting) MUST call this
    function rather than re-deriving the same decision - Memory projects this result,
    it never recomputes it."""
    if not assessments:
        return {"status": "NONE", "assessment": None}
    latest_seq = max(a.get("sequence", 0) for a in assessments)
    tied = [a for a in assessments if a.get("sequence", 0) == latest_seq]
    if len(tied) > 1:
        return {"status": "CONFLICT", "assessment": None, "conflicting_assessment_ids": sorted(a["assessment_id"] for a in tied)}
    return {"status": "OK", "assessment": tied[0]}


def get_current_claim_assessment(project: Path, claim_id: str) -> dict[str, Any]:
    """Loads this claim's assessments from disk and delegates the actual selection
    decision to select_current_assessment() - the one place that logic lives."""
    return select_current_assessment(list_assessments(project, claim_id=claim_id))


# --- query -----------------------------------------------------------------------

def query_research(project: Path, kind: str, record_id: str | None = None) -> Any:
    listers = {
        "questions": list_research_questions, "hypotheses": list_hypotheses, "protocols": list_protocols,
        "experiments": list_experiments, "observations": list_observations, "claims": list_claims,
        "assessments": list_assessments,
    }
    loaders = {
        "questions": load_research_question, "hypotheses": load_hypothesis, "protocols": load_protocol,
        "experiments": load_experiment, "observations": load_observation, "claims": load_claim,
        "assessments": load_assessment,
    }
    _require(kind in listers, f"research: unknown query kind: {kind!r}")
    if record_id is None:
        return listers[kind](project)
    record = loaders[kind](project, record_id)
    if record is None:
        raise MethodologyValidationError(f"research: unknown {kind[:-1]} {record_id!r}")
    return record
