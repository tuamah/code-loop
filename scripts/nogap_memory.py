#!/usr/bin/env python3
"""M7-I: Project Memory / Trusted Memory Projection.

A read-only Memory Projector. It collects existing trusted records - methodology
state and transition history, structured P0-P18 artifacts, M7-H FailureRecords, the
trust runtime's decision/evidence/event ledgers, and (advisory only) Git metadata -
and deterministically projects them into a MemorySnapshot (.code-loop/memory/
snapshot.json) and human-readable Markdown (.code-loop/memory/projections/MEMORY.md).

CRITICAL TRUST RULE, enforced structurally, not just by convention: MEMORY.md and
snapshot.json are NOT sources of truth. They are DERIVED, REBUILDABLE projections.
Every function in this module only ever READS existing records; nothing here writes
a decision, a methodology transition, a failure state, or an artifact. There is no
generic "memory add <prose>" path - the only way anything enters a MemorySnapshot is
by being collected from a real, already-existing, independently-validated source
record (see collect_memory_sources). Losing snapshot.json/MEMORY.md is never loss of
project truth: rebuild_memory() regenerates both, deterministically, from the same
sources every time.

SOURCE-OF-TRUTH HIERARCHY (highest first; lower layers never overwrite higher ones -
this module reads each layer independently and never lets one layer's absence stand
in for another's content):
  1 immutable evidence / verification records  (.code-loop/runtime/evidence)
  2 Decision Engine records                     (.code-loop/runtime/decisions, events)
  3 Methodology State and transition history    (.code-loop/methodology/state.json)
  4 Failure Records                              (.code-loop/methodology/failures)
  5 structured methodology artifacts             (.code-loop/methodology/artifacts)
  6 research records (a subset of #5: P3_PRIOR_ART)
  7 Git metadata                                 (advisory only - see _collect_git)
  8 generated MemorySnapshot   (this module's own output - never fed back as input)
  9 generated MEMORY.md        (ditto)
  10 Agent prose                (never read by this module at all)

UNKNOWN vs NONE convention, used consistently everywhere in this module: a list-typed
field is `[]` when the underlying source was checked and is genuinely empty (NONE -
"zero of these exist"), and `null`/`None` when the source subsystem itself does not
exist yet, so nothing could be checked at all (UNKNOWN - "we cannot tell"). The same
holds for scalar fields: a real value when derivable, `None` when not. Never invent a
value to fill a gap.

Fails closed (raises MethodologyValidationError - reused from nogap_methodology.py
rather than inventing a second exception type, matching nogap_failure.py's own
convention) on: a malformed/unparseable authoritative source file (this module scans
runtime/methodology directories itself rather than delegating to the silently-
skip-on-parse-error loaders elsewhere in this codebase - a source parse failure must
never be silently dropped here), a duplicate stable id across artifacts that should be
unique (requirement_id/task_id/verification_plan_id/verification_run_id), an unresolved
reference from a failure record, an unsupported/mismatched snapshot schema or
methodology version, and a corrupted snapshot.json (self-consistency hash mismatch).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from nogap_artifacts import ARTIFACT_TYPES, _resolve_reference, artifacts_dir, load_artifact
from nogap_failure import PARK_STATES, failures_dir
from nogap_methodology import (
    MethodologyValidationError,
    _now,
    can_transition,
    list_principle_enforcement,
    load_methodology,
    load_state,
    methodology_state_dir,
)

SCHEMA_VERSION = "1.0.0"
GENERATOR_VERSION = "nogap_memory.py/M7-I/1.0.0"

# Which real artifact/record collections back which authority classification -
# used only for labeling provenance in the rendered projection, never to grant it.
AUTHORITY_KINDS = {"EVIDENCE", "DECISION", "METHODOLOGY", "FAILURE", "ARTIFACT", "DERIVED", "ADVISORY"}

_STABLE_ID_ARTIFACT_TYPES = {
    "P6_REQUIREMENT": "requirement_id",
    "P12_TASK_CONTRACT": "task_id",
    "P15_VERIFICATION_PLAN": "verification_plan_id",
    "P18_VERIFICATION_RESULT": "verification_run_id",
}

RECENT_CHANGES_LIMIT = 25

# --- redaction ---------------------------------------------------------------
# Projection-only: never applied to raw evidence, artifacts, decisions, or any
# other source file - only to the rendered MEMORY.md text.
_SECRET_KEY_VALUE_RE = re.compile(
    r'(?i)\b((?:api[_-]?key|secret|password|passwd|token|credential)s?)\b(\s*[:=]\s*)("?)([A-Za-z0-9/_\-\.\+]{6,})("?)'
)
_SECRET_TOKEN_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),                    # OpenAI-style secret key
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),             # GitHub tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),           # Slack tokens
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT-shaped
]


def _redact(text: str) -> str:
    out = _SECRET_KEY_VALUE_RE.sub(r"\1\2\3[REDACTED]\5", text)
    for pattern in _SECRET_TOKEN_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


# --- paths ---------------------------------------------------------------

def memory_dir(project: Path) -> Path:
    return project.resolve() / ".code-loop" / "memory"


def snapshot_path(project: Path) -> Path:
    return memory_dir(project) / "snapshot.json"


def markdown_path(project: Path) -> Path:
    return memory_dir(project) / "projections" / "MEMORY.md"


def runtime_dir(project: Path) -> Path:
    return project.resolve() / ".code-loop" / "runtime"


# --- low-level strict loaders ---------------------------------------------
# Deliberately NOT reusing nogap_artifacts.list_artifacts / nogap_failure.list_failures
# / nogap.py's load_objects: those all either skip malformed JSON silently or raise
# SystemExit (a CLI-only convention, wrong for a library). A source parse failure is
# trust-critical here and must never be silently dropped.

def _load_json_dir_strict(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MethodologyValidationError(f"memory: unreadable/malformed source file {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise MethodologyValidationError(f"memory: source file {path} must contain a JSON object")
        records.append(data)
    return records


def _load_jsonl_dir_strict(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise MethodologyValidationError(f"memory: unreadable event log {path}: {exc}") from exc
        for lineno, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MethodologyValidationError(f"memory: malformed event log line {path}:{lineno}: {exc}") from exc
            if not isinstance(data, dict):
                raise MethodologyValidationError(f"memory: event log entry {path}:{lineno} must be a JSON object")
            events.append(data)
    return events


# --- git metadata (tier 7: advisory only) -----------------------------------

def _collect_git(project: Path) -> dict[str, Any] | None:
    """Current commit/branch/dirty-flag only - never used to imply verified state.
    Returns None (UNKNOWN) if this isn't a git repo or git isn't available; never
    raises, since git metadata is advisory, not trust-critical."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, text=True, capture_output=True, timeout=10,
        )
        if head.returncode != 0:
            return None
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project, text=True, capture_output=True, timeout=10,
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=project, text=True, capture_output=True, timeout=10,
        )
        return {
            "commit": head.stdout.strip(),
            "branch": branch.stdout.strip() if branch.returncode == 0 else None,
            "working_tree_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        }
    except (OSError, subprocess.SubprocessError):
        return None


# --- collection --------------------------------------------------------------

def collect_memory_sources(project: Path) -> dict[str, Any]:
    """Deterministic collection of every existing source this module is allowed to
    read. Never invents, never mutates. Raises (fail closed) on a malformed source
    file, a duplicate stable id where uniqueness is required, or a failure record
    referencing evidence/artifacts that do not resolve."""
    project = project.resolve()
    state = load_state(project)

    artifacts: dict[str, list[dict[str, Any]]] = {}
    art_dir = artifacts_dir(project)
    if art_dir.is_dir():
        for record in _load_json_dir_strict(art_dir):
            artifact_type = record.get("artifact_type")
            if artifact_type not in ARTIFACT_TYPES:
                raise MethodologyValidationError(f"memory: artifact {record.get('artifact_id')} has unknown artifact_type {artifact_type!r}")
            artifacts.setdefault(artifact_type, []).append(record)

    _check_duplicate_stable_ids(artifacts)
    _check_artifact_references(project, artifacts)

    failures = _load_json_dir_strict(failures_dir(project))
    evidence = _load_json_dir_strict(runtime_dir(project) / "evidence")
    _check_failure_references(project, failures, evidence)

    decisions_current = _load_json_dir_strict(runtime_dir(project) / "decisions")
    events = _load_jsonl_dir_strict(runtime_dir(project) / "events")
    gates = _load_json_dir_strict(runtime_dir(project) / "gates")

    research = _collect_research(project)
    _check_research_duplicate_ids(research)
    _check_research_cross_refs(research)

    return {
        "methodology_state": state,
        "artifacts": artifacts,
        "failures": failures,
        "evidence": evidence,
        "decisions_current": decisions_current,
        "events": events,
        "gates": gates,
        "research": research,
        "git": _collect_git(project),
        "runtime_exists": (runtime_dir(project) / "run.json").is_file(),
        "methodology_exists": state is not None,
    }


# --- M7-J research collection (read-only; nogap_research.py owns all writes) -----

RESEARCH_KINDS = ("questions", "hypotheses", "protocols", "experiments", "observations", "claims", "assessments")
RESEARCH_ID_FIELDS = {
    "questions": "question_id", "hypotheses": "hypothesis_id", "protocols": "protocol_id",
    "experiments": "experiment_id", "observations": "observation_id", "claims": "claim_id",
    "assessments": "assessment_id",
}


def _collect_research(project: Path) -> dict[str, list[dict[str, Any]]]:
    from nogap_research import research_dir as _research_dir
    base = _research_dir(project)
    return {kind: _load_json_dir_strict(base / kind) for kind in RESEARCH_KINDS}


def _check_research_duplicate_ids(research: dict[str, list[dict[str, Any]]]) -> None:
    for kind, id_field in RESEARCH_ID_FIELDS.items():
        seen: set[str] = set()
        for record in research[kind]:
            rid = record.get(id_field)
            if not rid:
                continue
            if rid in seen:
                raise MethodologyValidationError(f"memory: duplicate authoritative {id_field} {rid!r} in research/{kind}")
            seen.add(rid)


def _check_research_cross_refs(research: dict[str, list[dict[str, Any]]]) -> None:
    known_questions = {r["question_id"] for r in research["questions"]}
    known_hypotheses = {r["hypothesis_id"] for r in research["hypotheses"]}
    known_protocols = {r["protocol_id"] for r in research["protocols"]}
    known_experiments = {r["experiment_id"] for r in research["experiments"]}
    known_claims = {r["claim_id"] for r in research["claims"]}

    for record in research["hypotheses"] + research["protocols"] + research["claims"]:
        if record.get("question_id") and record["question_id"] not in known_questions:
            raise MethodologyValidationError(f"memory: research record references unknown question_id {record['question_id']!r}")
    for record in research["protocols"] + research["experiments"] + research["claims"]:
        for ref in record.get("hypothesis_refs") or []:
            if ref not in known_hypotheses:
                raise MethodologyValidationError(f"memory: research record references unknown hypothesis_id {ref!r}")
    for record in research["experiments"]:
        if record.get("protocol_id") and record["protocol_id"] not in known_protocols:
            raise MethodologyValidationError(f"memory: experiment references unknown protocol_id {record['protocol_id']!r}")
    for record in research["observations"]:
        if record.get("experiment_id") and record["experiment_id"] not in known_experiments:
            raise MethodologyValidationError(f"memory: observation references unknown experiment_id {record['experiment_id']!r}")
    for record in research["claims"]:
        for ref in record.get("protocol_refs") or []:
            if ref not in known_protocols:
                raise MethodologyValidationError(f"memory: claim references unknown protocol_id {ref!r}")
    for record in research["assessments"]:
        if record.get("claim_id") and record["claim_id"] not in known_claims:
            raise MethodologyValidationError(f"memory: assessment references unknown claim_id {record['claim_id']!r}")


def _check_duplicate_stable_ids(artifacts: dict[str, list[dict[str, Any]]]) -> None:
    for artifact_type, id_field in _STABLE_ID_ARTIFACT_TYPES.items():
        seen: dict[str, str] = {}
        for record in artifacts.get(artifact_type, []):
            stable_id = record.get("fields", {}).get(id_field)
            if not stable_id:
                continue
            if stable_id in seen and seen[stable_id] != record.get("artifact_id"):
                raise MethodologyValidationError(
                    f"memory: duplicate authoritative {id_field} {stable_id!r} claimed by both "
                    f"{seen[stable_id]!r} and {record.get('artifact_id')!r} - conflicting/duplicate "
                    f"authoritative records, refusing to silently pick one"
                )
            seen[stable_id] = record.get("artifact_id")


def _check_artifact_references(project: Path, artifacts: dict[str, list[dict[str, Any]]]) -> None:
    """Every declared reference_fields entry must resolve to a real prior artifact -
    reuses nogap_artifacts._resolve_reference rather than re-deriving resolution."""
    for artifact_type, records in artifacts.items():
        reference_fields = ARTIFACT_TYPES[artifact_type]["reference_fields"]
        if not reference_fields:
            continue
        for record in records:
            fields = record.get("fields", {})
            for field_name, target_type in reference_fields.items():
                refs = fields.get(field_name)
                if not refs:
                    continue
                if not isinstance(refs, list):
                    raise MethodologyValidationError(f"memory: {record.get('artifact_id')}.{field_name} must be a list of references")
                for ref in refs:
                    if not _resolve_reference(project, ref, target_type):
                        raise MethodologyValidationError(
                            f"memory: {record.get('artifact_id')}.{field_name} references unknown {target_type} {ref!r} "
                            f"- invalid source reference"
                        )


def _check_failure_references(project: Path, failures: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> None:
    """revalidation_refs is deliberately excluded: nogap_failure.record_revalidation
    stores the failure's task_id there (see its own docstring), not an evidence or
    artifact id - a different id domain entirely, not a dangling reference."""
    known_evidence_ids = {item["id"] for item in evidence if isinstance(item.get("id"), str)}
    for failure in failures:
        for field_name in ("evidence_refs", "artifact_refs", "reproduction_refs", "research_refs", "regression_refs"):
            refs = failure.get(field_name) or []
            unresolved = [
                ref for ref in refs
                if ref not in known_evidence_ids and load_artifact(project, ref) is None
            ]
            if unresolved:
                raise MethodologyValidationError(
                    f"memory: failure {failure.get('failure_id')}.{field_name} references unknown record(s) {unresolved} "
                    f"- unresolvable authoritative reference"
                )


# --- fingerprinting ------------------------------------------------------------

def _content_hash(record: Any) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _flatten_sources(sources: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(category, source_id, content_hash) triples, deterministically ordered by
    (category, source_id) - never by file listing/collection order."""
    flat: list[tuple[str, str, str]] = []
    if sources["methodology_state"] is not None:
        flat.append(("methodology_state", "state", _content_hash(sources["methodology_state"])))
    for artifact_type, records in sources["artifacts"].items():
        for record in records:
            flat.append((f"artifact:{artifact_type}", record["artifact_id"], _content_hash(record)))
    for failure in sources["failures"]:
        flat.append(("failure", failure["failure_id"], _content_hash(failure)))
    for item in sources["evidence"]:
        flat.append(("evidence", item["id"], _content_hash(item)))
    for decision in sources["decisions_current"]:
        flat.append(("decision", decision.get("id", _content_hash(decision)), _content_hash(decision)))
    for idx, event in enumerate(sources["events"]):
        flat.append(("event", event.get("id", str(idx)) + f"#{idx}", _content_hash(event)))
    for gate in sources["gates"]:
        flat.append(("gate", gate.get("id", _content_hash(gate)), _content_hash(gate)))
    for kind, records in sources.get("research", {}).items():
        id_field = RESEARCH_ID_FIELDS[kind]
        for record in records:
            flat.append((f"research:{kind}", record[id_field], _content_hash(record)))
    return sorted(flat)


def compute_source_fingerprint(sources: dict[str, Any]) -> str:
    """Deterministic over full record CONTENT (not just a timestamp field), sorted by
    (category, id) - immune to filesystem listing order and to any change in a source
    record, timestamp or otherwise. A phase transition, a new failure, a new evidence
    record, or a decision all change at least one record's content hash, which changes
    this fingerprint."""
    flat = _flatten_sources(sources)
    return hashlib.sha256(json.dumps(flat, sort_keys=True).encode("utf-8")).hexdigest()


# --- derivation ----------------------------------------------------------------

def _evidence_by_id(sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in sources["evidence"] if isinstance(item.get("id"), str)}


def _derive_project_identity(sources: dict[str, Any]) -> dict[str, Any]:
    intents = sources["artifacts"].get("P0_PROJECT_INTENT", [])
    if not intents:
        return {"project_name": None, "intent_type": None, "owner": None, "source_refs": []}
    latest = max(intents, key=lambda r: r.get("updated_at", ""))
    fields = latest.get("fields", {})
    return {
        "project_name": fields.get("project_name"),
        "intent_type": fields.get("intent_type"),
        "owner": fields.get("owner"),
        "source_refs": [latest["artifact_id"]],
    }


def _derive_tasks(sources: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tasks = sources["artifacts"].get("P12_TASK_CONTRACT", [])
    verification_results = sources["artifacts"].get("P18_VERIFICATION_RESULT", [])
    accepted_task_ids = _accepted_task_ids(sources)

    blocked_task_ids: set[str] = set()
    for result in verification_results:
        task_id = result["fields"].get("task_id")
        if task_id and result.get("status") in {"VERIFICATION_FAILED", "VERIFICATION_INCONCLUSIVE"}:
            blocked_task_ids.add(task_id)
    for failure in sources["failures"]:
        task_id = failure.get("task_id")
        if task_id and failure.get("current_state") != "RESOLVED":
            blocked_task_ids.add(task_id)

    active, completed, blocked = [], [], []
    for task in tasks:
        task_id = task["fields"]["task_id"]
        entry = {"task_id": task_id, "goal": task["fields"].get("goal"), "source_ref": task["artifact_id"]}
        if task_id in accepted_task_ids:
            completed.append(entry)
        elif task_id in blocked_task_ids:
            blocked.append(entry)
        else:
            active.append(entry)
    return active, completed, blocked


def _derive_decisions(sources: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Current decisions (decisions/*.json) give the LIVE state; the append-only
    events ledger gives HISTORY (decisions/*.json is overwritten on each `nogap
    decide` call for the run's single live decision, so history would otherwise be
    lost - the events ledger is what actually preserves it). ACCEPT is never
    conflated with REJECT/ABSTAIN, and ABSTAIN is never conflated with REJECT."""
    buckets: dict[str, list[dict[str, Any]]] = {"accept": [], "reject": [], "abstain": [], "other": []}
    seen_keys: set[tuple[str, str]] = set()

    def _add(record: dict[str, Any], origin: str, source_ref: str) -> None:
        decision = record.get("decision")
        bucket = decision if decision in {"accept", "reject", "abstain"} else "other"
        key = (source_ref, bucket)
        if key in seen_keys:
            return
        seen_keys.add(key)
        buckets[bucket].append({
            "id": record.get("id"),
            "reason": record.get("reason"),
            "actor_id": record.get("actor_id") or record.get("decided_by"),
            "authority": record.get("authority"),
            "evidence": record.get("evidence", []),
            "created_at": record.get("created_at"),
            "origin": origin,
            "source_ref": source_ref,
        })

    for decision in sources["decisions_current"]:
        _add(decision, "current", f"decision:{decision.get('id')}")
    for idx, event in enumerate(sources["events"]):
        payload = event.get("payload", {})
        if "decision" not in payload:
            continue
        _add(
            {**payload, "id": event.get("id"), "created_at": event.get("created_at"), "actor_id": event.get("actor")},
            "event_history", f"event:{event.get('id')}#{idx}",
        )

    return {
        "accepted_decisions": buckets["accept"],
        "rejected_decisions": buckets["reject"],
        "abstained_decisions": buckets["abstain"],
        "other_decisions": buckets["other"],
    }


def _derive_failures(sources: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """RESOLVED is only ever a CURRENT projection: a failure's full history remains
    permanently queryable via source_refs -> failures/<id>.json regardless of which
    bucket it lands in here. Nothing here deletes or hides that a failure happened."""
    open_failures, resolved_failures, inconclusive_failures, other_closed = [], [], [], []
    for failure in sources["failures"]:
        entry = {
            "failure_id": failure["failure_id"],
            "current_state": failure["current_state"],
            "failure_class": failure.get("failure_class"),
            "summary": failure.get("summary"),
            "root_cause_class": failure.get("root_cause_class"),
            "repair_target_phase": failure.get("repair_target_phase"),
            "task_id": failure.get("task_id"),
            "first_observed_at": failure.get("first_observed_at"),
            "last_updated_at": failure.get("last_updated_at"),
            "source_ref": failure["failure_id"],
        }
        state = failure["current_state"]
        if state == "RESOLVED":
            resolved_failures.append(entry)
        elif state == "INCONCLUSIVE":
            inconclusive_failures.append(entry)
        elif state in PARK_STATES:
            other_closed.append(entry)
        else:
            open_failures.append(entry)
    return {
        "open_failures": open_failures,
        "resolved_failures": resolved_failures,
        "inconclusive_failures": inconclusive_failures,
        "other_closed_failures": other_closed,
    }


def _derive_research(sources: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prior_art = sources["artifacts"].get("P3_PRIOR_ART", [])
    gap_analyses = sources["artifacts"].get("P4_GAP_ANALYSIS", [])
    referenced_ids = {ref for gap in gap_analyses for ref in gap["fields"].get("prior_art_refs", [])}

    active_research, research_findings = [], []
    for record in prior_art:
        entry = {
            "artifact_id": record["artifact_id"],
            "research_question": record["fields"].get("research_question"),
            "source_ref": record["artifact_id"],
        }
        if record["artifact_id"] not in referenced_ids:
            active_research.append(entry)
        for finding in record["fields"].get("key_findings", []):
            research_findings.append({"finding": finding, "source_ref": record["artifact_id"]})
    return active_research, research_findings


def _derive_verification(sources: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results = sources["artifacts"].get("P18_VERIFICATION_RESULT", [])
    verified_artifacts = [
        {
            "task_id": r["fields"].get("task_id"),
            "verification_run_id": r["fields"].get("verification_run_id"),
            "status": r.get("status"),
            "deterministic_result": r["fields"].get("deterministic_result"),
            "reproducibility_result": r["fields"].get("reproducibility_result"),
            "independent_review_result": r["fields"].get("independent_review_result"),
            "candidate_hash": r["fields"].get("candidate_hash"),
            "patch_hash": r["fields"].get("patch_hash"),
            "source_ref": r["artifact_id"],
        }
        for r in results
    ]
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.get("status", "UNKNOWN")] = by_status.get(r.get("status", "UNKNOWN"), 0) + 1
    summary = {
        "total": len(results),
        "by_status": by_status,
        "awaiting_decision": by_status.get("VERIFICATION_COMPLETE_AWAITING_DECISION", 0),
    }
    return verified_artifacts, summary


def _derive_requirements(sources: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "requirement_id": r["fields"].get("requirement_id"),
            "status": r.get("status"),
            "statement": r["fields"].get("statement"),
            "source_ref": r["artifact_id"],
        }
        for r in sources["artifacts"].get("P6_REQUIREMENT", [])
    ]


def _derive_gate_status(sources: dict[str, Any]) -> dict[str, Any]:
    gates = [{"id": g.get("id"), "status": g.get("status"), "hash": g.get("hash")} for g in sources["gates"]]
    frozen = next((g["id"] for g in gates if g["status"] == "frozen"), None)
    return {"gates": gates, "frozen_gate_id": frozen}


def _derive_architecture(sources: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    adrs = sources["artifacts"].get("P8_ADR", [])
    architecture_decisions = [
        {
            "artifact_id": r["artifact_id"],
            "decision": r["fields"].get("decision"),
            "selected_option": r["fields"].get("selected_option"),
            "status": r.get("status"),
            "source_ref": r["artifact_id"],
        }
        for r in adrs
    ]
    frozen_decisions = [entry for entry in architecture_decisions if entry["status"] == "ACCEPTED"]
    return architecture_decisions, frozen_decisions


def _derive_constraints(sources: dict[str, Any]) -> list[dict[str, Any]]:
    constraints = []
    for record in sources["artifacts"].get("P1_SCOPE", []):
        for constraint in record["fields"].get("constraints", []):
            constraints.append({"constraint": constraint, "source_ref": record["artifact_id"]})
    return constraints


def _derive_known_limitations(project: Path) -> list[dict[str, Any]]:
    """Sourced from methodology/enforcement.json's own truthful, disclosed
    capability-vs-gap descriptions (M7-D) - reused, never re-derived or guessed."""
    limitations = []
    try:
        records = list_principle_enforcement()
    except MethodologyValidationError:
        return []
    for record in records:
        if record.status in {"PARTIAL", "DECLARED", "DEFERRED"}:
            limitations.append({
                "principle_id": record.principle_id,
                "status": record.status,
                "limitation": record.mechanism,
                "source_ref": f"methodology/enforcement.json:{record.principle_id}",
            })
    return limitations


def _derive_unresolved_questions(sources: dict[str, Any]) -> list[dict[str, Any]]:
    questions = []
    for failure in sources["failures"]:
        if failure["current_state"] == "INCONCLUSIVE":
            root_cause = failure.get("root_cause") or {}
            questions.append({
                "question": f"failure {failure['failure_id']} ({failure.get('summary')}) is INCONCLUSIVE: "
                             f"{root_cause.get('summary') or 'root cause not yet determined'}",
                "source_ref": failure["failure_id"],
            })
    for record in sources["artifacts"].get("P8_ADR", []):
        if record.get("status") == "PROPOSED":
            questions.append({
                "question": f"architecture decision {record['artifact_id']} ({record['fields'].get('decision')}) is still PROPOSED, not ACCEPTED",
                "source_ref": record["artifact_id"],
            })
    return questions


def _accepted_task_ids(sources: dict[str, Any]) -> set[str]:
    evidence_by_id = _evidence_by_id(sources)
    accepted: set[str] = set()
    for decision in sources["decisions_current"]:
        if decision.get("decision") != "accept":
            continue
        for evidence_id in decision.get("evidence", []):
            item = evidence_by_id.get(evidence_id)
            task_id = item.get("provenance", {}).get("task_id") if item else None
            if task_id:
                accepted.add(task_id)
    return accepted


def _derive_next_actions(project: Path, sources: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    state = sources["methodology_state"]
    accepted_task_ids = _accepted_task_ids(sources)

    if state is None:
        actions.append({
            "action": "no methodology state initialized - run `nogap methodology init` to begin a tracked lifecycle",
            "priority": "OPTIONAL", "source_ref": "methodology_state",
        })
    else:
        definition = load_methodology()
        phase = definition.get_phase(state["current_phase"])
        if phase.allowed_next:
            evaluation = can_transition(project, phase.allowed_next[0])
            if not evaluation["allowed"]:
                for reason in evaluation["blocked_reasons"]:
                    actions.append({
                        "action": f"advance past {state['current_phase']}: {reason}",
                        "priority": "REQUIRED", "source_ref": "methodology_state",
                    })
            else:
                actions.append({
                    "action": f"advance from {state['current_phase']} to {phase.allowed_next[0]}",
                    "priority": "RECOMMENDED", "source_ref": "methodology_state",
                })

    for failure in sources["failures"]:
        if failure["current_state"] not in ({"RESOLVED"} | PARK_STATES):
            actions.append({
                "action": f"continue failure {failure['failure_id']} lifecycle (currently {failure['current_state']})",
                "priority": "REQUIRED", "source_ref": failure["failure_id"],
            })

    for result in sources["artifacts"].get("P18_VERIFICATION_RESULT", []):
        # the artifact's own status never changes once `nogap decide` runs (decisions
        # live in a separate subsystem) - cross-check against accepted_task_ids so an
        # already-accepted task doesn't keep showing a stale "decide" action forever.
        if result.get("status") == "VERIFICATION_COMPLETE_AWAITING_DECISION" and result["fields"].get("task_id") not in accepted_task_ids:
            actions.append({
                "action": f"run `nogap decide` for task {result['fields'].get('task_id')} "
                          f"(verification {result['fields'].get('verification_run_id')} is awaiting decision)",
                "priority": "REQUIRED", "source_ref": result["artifact_id"],
            })

    return actions


def _derive_recent_changes(sources: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    state = sources["methodology_state"]
    if state is not None:
        for entry in state["transition_history"]:
            changes.append({
                "kind": "methodology_transition",
                "summary": f"{entry['from_phase']} -> {entry['to_phase']} ({entry['transition_type']}): {entry['reason']}",
                "timestamp": entry["timestamp"],
                "source_ref": entry["transition_id"],
            })
    for failure in sources["failures"]:
        for entry in failure.get("history", []):
            changes.append({
                "kind": "failure_history",
                "summary": f"{failure['failure_id']}: {entry['action']} - {entry['reason']}",
                "timestamp": entry["changed_at"],
                "source_ref": failure["failure_id"],
            })
    for idx, event in enumerate(sources["events"]):
        payload = event.get("payload", {})
        if "decision" in payload:
            changes.append({
                "kind": "decision_event",
                "summary": f"decision {payload['decision']}: {event.get('type')}",
                "timestamp": event.get("created_at", ""),
                "source_ref": f"event:{event.get('id')}#{idx}",
            })
    changes.sort(key=lambda item: item["timestamp"], reverse=True)
    return changes[:RECENT_CHANGES_LIMIT]


def _build_source_refs(sources: dict[str, Any]) -> dict[str, Any]:
    return {
        "methodology_state": "state" if sources["methodology_state"] is not None else None,
        "artifacts": {artifact_type: [r["artifact_id"] for r in records] for artifact_type, records in sources["artifacts"].items()},
        "failures": [f["failure_id"] for f in sources["failures"]],
        "evidence": [e["id"] for e in sources["evidence"] if isinstance(e.get("id"), str)],
        "decisions": [d.get("id") for d in sources["decisions_current"]],
        "gates": [g.get("id") for g in sources["gates"]],
    }


# --- M7-J structured research derivation --------------------------------------
# Additive to (never a replacement for) the older P3_PRIOR_ART-sourced
# active_research/research_findings fields above - both stay valid and tested;
# M7-J's own structured records get their own dedicated fields instead of being
# force-merged into the P3-era ones. Memory only ever READS these; nothing here
# reassesses a claim or picks a "better" outcome than what nogap_research.py itself
# already recorded.

def _current_research_assessments_by_claim(research: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Groups already-collected assessments by claim and delegates the actual
    "which one is current" decision to nogap_research.select_current_assessment() -
    the single authoritative owner of that semantic. Memory projects the result;
    it does not re-derive it. Operates on the sources already collected (rather than
    re-reading disk per claim) so this reflects exactly this snapshot's own
    point-in-time view, but the SELECTION RULE ITSELF lives in exactly one place."""
    from nogap_research import select_current_assessment

    by_claim: dict[str, list[dict[str, Any]]] = {}
    for assessment in research["assessments"]:
        by_claim.setdefault(assessment["claim_id"], []).append(assessment)
    return {claim_id: select_current_assessment(assessments) for claim_id, assessments in by_claim.items()}


def _derive_structured_research(sources: dict[str, Any]) -> dict[str, Any]:
    research = sources["research"]
    claims_by_id = {c["claim_id"]: c for c in research["claims"]}

    open_questions = [
        {"question_id": q["question_id"], "title": q["title"], "status": q["status"], "source_ref": q["question_id"]}
        for q in research["questions"] if q["status"] not in {"ANSWERED", "INCONCLUSIVE", "CLOSED", "ABANDONED"}
    ]
    active_hypotheses = [
        {"hypothesis_id": h["hypothesis_id"], "question_id": h["question_id"], "statement": h["statement"],
         "status": h["status"], "preregistered": h["preregistered"], "analysis_mode": h["analysis_mode"],
         "source_ref": h["hypothesis_id"]}
        for h in research["hypotheses"] if h["status"] in {"REGISTERED", "UNDER_TEST"}
    ]
    frozen_protocols = [
        {"protocol_id": p["protocol_id"], "question_id": p["question_id"], "objective": p["objective"],
         "primary_metric": p["primary_metric"], "status": p["status"], "source_ref": p["protocol_id"]}
        for p in research["protocols"] if p["status"] in {"FROZEN", "EXECUTED"}
    ]

    current_by_claim = _current_research_assessments_by_claim(research)
    buckets: dict[str, list[dict[str, Any]]] = {"SUPPORTED": [], "PARTIALLY_SUPPORTED": [], "REFUTED": [], "INCONCLUSIVE": []}
    current_claim_assessments = []
    conflicts = []
    for claim_id, current in current_by_claim.items():
        claim = claims_by_id.get(claim_id, {})
        if current["status"] == "CONFLICT":
            conflicts.append({"claim_id": claim_id, "conflicting_assessment_ids": current["conflicting_assessment_ids"]})
            continue
        assessment = current["assessment"]
        entry = {
            "claim_id": claim_id, "statement": claim.get("statement"), "outcome": assessment["outcome"],
            "assessment_id": assessment["assessment_id"], "assessor_role": assessment["assessor_role"],
            "created_at": assessment["created_at"], "source_ref": assessment["assessment_id"],
        }
        current_claim_assessments.append(entry)
        buckets.setdefault(assessment["outcome"], []).append(entry)

    return {
        "open_research_questions": open_questions,
        "active_hypotheses": active_hypotheses,
        "frozen_protocols": frozen_protocols,
        "current_claim_assessments": current_claim_assessments,
        "supported_findings": buckets["SUPPORTED"],
        "partially_supported_findings": buckets["PARTIALLY_SUPPORTED"],
        "refuted_findings": buckets["REFUTED"],
        "inconclusive_findings": buckets["INCONCLUSIVE"],
        "research_assessment_conflicts": conflicts,
    }


# --- snapshot build --------------------------------------------------------

def build_memory_snapshot(project: Path, actor: str) -> dict[str, Any]:
    """Pure(ish) read + derive: collects sources, checks them, and projects a
    MemorySnapshot. Never writes anything - see rebuild_memory for persistence."""
    project = project.resolve()
    sources = collect_memory_sources(project)
    definition = load_methodology()
    state = sources["methodology_state"]

    active_tasks, completed_tasks, blocked_tasks = _derive_tasks(sources)
    decisions_view = _derive_decisions(sources)
    failures_view = _derive_failures(sources)
    active_research, research_findings = _derive_research(sources)
    verified_artifacts, verification_summary = _derive_verification(sources)
    architecture_decisions, frozen_decisions = _derive_architecture(sources)
    structured_research = _derive_structured_research(sources)

    flat = _flatten_sources(sources)
    source_fingerprint = hashlib.sha256(json.dumps(flat, sort_keys=True).encode("utf-8")).hexdigest()

    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "methodology_version": definition.version,
        "project_id": _derive_project_identity(sources)["project_name"],
        "generated_at": _now(),
        "generated_by": actor,

        "project_identity": _derive_project_identity(sources),
        "current_methodology_state": (
            {
                "intent": state["intent"], "risk": state["risk"], "claim_strength": state["claim_strength"],
                "derived_profile": state["derived_profile"], "effective_profile": state["effective_profile"],
                "phase_profile_overrides": state["phase_profile_overrides"],
                "downgrade_log": state["downgrade_log"],
                "active_loops": [loop for loop in state["loops"] if loop["status"] == "ACTIVE"],
                "completed_phase_count": len({e["from_phase"] for e in state["transition_history"] if e["transition_type"] in {"FORWARD", "LOOP_ENTRY", "SKIP"}}),
            } if state is not None else None
        ),
        "active_phase": state["current_phase"] if state is not None else None,
        "effective_profile": state["effective_profile"] if state is not None else None,

        "active_tasks": active_tasks,
        "completed_tasks": completed_tasks,
        "blocked_tasks": blocked_tasks,

        **decisions_view,
        **failures_view,

        "active_research": active_research,
        "research_findings": research_findings,
        **structured_research,

        "verified_artifacts": verified_artifacts,
        "verification_summary": verification_summary,

        "requirements_status": _derive_requirements(sources),
        "gate_status": _derive_gate_status(sources),

        "architecture_decisions": architecture_decisions,

        "known_constraints": _derive_constraints(sources),
        "frozen_decisions": frozen_decisions,
        "known_limitations": _derive_known_limitations(project),
        "known_graph_gaps": [
            item for item in _derive_known_limitations(project) if item["principle_id"] == "GP-3"
        ],

        "unresolved_questions": _derive_unresolved_questions(sources),
        "next_actions": _derive_next_actions(project, sources),
        "recent_changes": _derive_recent_changes(sources),

        "source_refs": _build_source_refs(sources),
        "git": sources["git"],

        "integrity": {
            "source_count": len(flat),
            "source_fingerprint": source_fingerprint,
            "projection_hash": None,  # filled in by rebuild_memory once markdown body is rendered
            "generator_version": GENERATOR_VERSION,
            "conflicts": list(structured_research["research_assessment_conflicts"]),
            "stale": False,
        },
    }
    return snapshot


# --- persisted snapshot load/validate ----------------------------------------

_REQUIRED_SNAPSHOT_KEYS = {
    "schema_version", "methodology_version", "project_id", "generated_at", "generated_by",
    "integrity",
}


def load_memory_snapshot(project: Path) -> dict[str, Any] | None:
    """Returns None if no snapshot exists yet (truthful 'nothing built' state, never
    an error). Raises on malformed JSON, unsupported schema_version, or a
    methodology_version mismatch against the currently loaded methodology contracts."""
    path = snapshot_path(project)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MethodologyValidationError(f"memory: {path} is invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MethodologyValidationError(f"memory: {path} must contain a JSON object")
    missing = _REQUIRED_SNAPSHOT_KEYS - set(data)
    if missing:
        raise MethodologyValidationError(f"memory: {path} is missing required field(s): {sorted(missing)}")
    if data["schema_version"] != SCHEMA_VERSION:
        raise MethodologyValidationError(
            f"memory: unsupported snapshot schema_version {data['schema_version']!r} (expected {SCHEMA_VERSION!r})"
        )
    definition = load_methodology()
    if data["methodology_version"] != definition.version:
        raise MethodologyValidationError(
            f"memory: snapshot was built under methodology v{data['methodology_version']}, "
            f"current is v{definition.version} - rebuild required"
        )
    return data


# --- markdown rendering --------------------------------------------------------

def _bullets(items: list[str], empty_note: str) -> str:
    if not items:
        return f"_{empty_note}_\n"
    return "".join(f"- {item}\n" for item in items)


def _fmt_source(ref: Any) -> str:
    return f" _(source: {ref})_" if ref else ""


def _render_body_sections(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []

    def section(title: str) -> None:
        lines.append(f"\n## {title}\n")

    lines.append("# Project Memory\n")
    lines.append(
        "\n> **AUTO-GENERATED — DO NOT EDIT.** This file is a derived projection, not a "
        "source of truth. Manual edits are detected and discarded on the next "
        "`nogap memory rebuild`. Every fact below is sourced from an existing methodology, "
        "failure, decision, evidence, or artifact record - see Source Integrity at the end.\n"
    )

    identity = snapshot["project_identity"]
    section("Project Identity")
    lines.append(f"- project_name: {identity.get('project_name') or 'UNKNOWN'}\n")
    lines.append(f"- intent_type: {identity.get('intent_type') or 'UNKNOWN'}\n")
    lines.append(f"- owner: {identity.get('owner') or 'UNKNOWN'}\n")

    section("Current Lifecycle State")
    if snapshot["current_methodology_state"] is None:
        lines.append("_no methodology state initialized (UNKNOWN)_\n")
    else:
        cms = snapshot["current_methodology_state"]
        lines.append(f"- current phase: {snapshot['active_phase']}\n")
        lines.append(f"- effective profile: {snapshot['effective_profile']} (derived: {cms['derived_profile']})\n")
        lines.append(f"- intent / risk / claim_strength: {cms['intent']} / {cms['risk']} / {cms['claim_strength']}\n")
        lines.append(f"- completed phase count: {cms['completed_phase_count']}\n")
        active_loop_desc = [f"{loop['loop_type']} (origin {loop['origin_phase']}, active since {loop['entered_at']})" for loop in cms["active_loops"]]
        lines.append(f"- active loops: {', '.join(active_loop_desc) if active_loop_desc else 'none'}\n")

    section("Active Work")
    lines.append("Active tasks:\n")
    lines.append(_bullets([f"{t['task_id']}: {t['goal']}{_fmt_source(t['source_ref'])}" for t in snapshot["active_tasks"]], "none"))
    lines.append("\nBlocked tasks:\n")
    lines.append(_bullets([f"{t['task_id']}: {t['goal']}{_fmt_source(t['source_ref'])}" for t in snapshot["blocked_tasks"]], "none"))
    lines.append("\nCompleted tasks:\n")
    lines.append(_bullets([f"{t['task_id']}: {t['goal']}{_fmt_source(t['source_ref'])}" for t in snapshot["completed_tasks"]], "none"))

    section("Verified Decisions")
    lines.append(
        "_ACCEPT here means the trust runtime's Decision Engine recorded 'accept' - a "
        "verification PASS alone is never rendered as ACCEPTED here; see Verification "
        "Status below for that separately._\n"
    )
    lines.append(_bullets(
        [f"{d.get('id')}: {d.get('reason')} (actor={d.get('actor_id')}){_fmt_source(d['source_ref'])}" for d in snapshot["accepted_decisions"]],
        "none",
    ))
    lines.append("\nAbstained:\n")
    lines.append(_bullets(
        [f"{d.get('id')}: {d.get('reason')}{_fmt_source(d['source_ref'])}" for d in snapshot["abstained_decisions"]],
        "none",
    ))
    lines.append("\nRejected:\n")
    lines.append(_bullets(
        [f"{d.get('id')}: {d.get('reason')}{_fmt_source(d['source_ref'])}" for d in snapshot["rejected_decisions"]],
        "none",
    ))

    section("Frozen Decisions")
    lines.append(_bullets(
        [f"{d['artifact_id']}: {d['decision']} -> {d['selected_option']} ({d['status']}){_fmt_source(d['source_ref'])}" for d in snapshot["frozen_decisions"]],
        "none frozen yet",
    ))

    section("Open Failures")
    lines.append(_bullets(
        [f"{f['failure_id']} [{f['current_state']}]: {f['summary']}{_fmt_source(f['source_ref'])}" for f in snapshot["open_failures"]],
        "none open",
    ))

    section("Resolved Failures")
    lines.append(_bullets(
        [f"{f['failure_id']}: {f['summary']} (root_cause={f['root_cause_class']}){_fmt_source(f['source_ref'])}" for f in snapshot["resolved_failures"]],
        "none resolved yet",
    ))
    if snapshot["inconclusive_failures"] or snapshot["other_closed_failures"]:
        lines.append("\nInconclusive / closed without resolution:\n")
        lines.append(_bullets(
            [f"{f['failure_id']} [{f['current_state']}]: {f['summary']}{_fmt_source(f['source_ref'])}"
             for f in snapshot["inconclusive_failures"] + snapshot["other_closed_failures"]],
            "none",
        ))

    section("Verification Status")
    summary = snapshot["verification_summary"]
    lines.append(f"- total verification results: {summary['total']} (awaiting decision: {summary['awaiting_decision']})\n")
    lines.append(f"- by status: {summary['by_status'] or 'none'}\n")
    lines.append(_bullets(
        [f"{v['verification_run_id']} (task {v['task_id']}): deterministic={v['deterministic_result']}, "
         f"reproducibility={v['reproducibility_result']}, independent_review={v['independent_review_result']}{_fmt_source(v['source_ref'])}"
         for v in snapshot["verified_artifacts"]],
        "no verification results recorded",
    ))

    section("Research State")
    lines.append("Active (not yet gap-analyzed):\n")
    lines.append(_bullets([f"{r['artifact_id']}: {r['research_question']}{_fmt_source(r['source_ref'])}" for r in snapshot["active_research"]], "none"))
    lines.append("\nFindings:\n")
    lines.append(_bullets([f"{r['finding']}{_fmt_source(r['source_ref'])}" for r in snapshot["research_findings"]], "none recorded"))
    lines.append("\nOpen research questions:\n")
    lines.append(_bullets([f"{q['question_id']} [{q['status']}]: {q['title']}{_fmt_source(q['source_ref'])}" for q in snapshot["open_research_questions"]], "none"))
    lines.append("\nActive hypotheses:\n")
    lines.append(_bullets(
        [f"{h['hypothesis_id']}: {h['statement']} (preregistered={h['preregistered']}, {h['analysis_mode']}){_fmt_source(h['source_ref'])}"
         for h in snapshot["active_hypotheses"]], "none",
    ))
    lines.append("\nFrozen protocols:\n")
    lines.append(_bullets(
        [f"{p['protocol_id']}: {p['objective']} (primary_metric={p['primary_metric']}){_fmt_source(p['source_ref'])}"
         for p in snapshot["frozen_protocols"]], "none",
    ))
    lines.append("\nCurrent claim assessments (SUPPORTED):\n")
    lines.append(_bullets(
        [f"{c['claim_id']}: {c['statement']} ({c['assessment_id']}, assessor_role={c['assessor_role']}){_fmt_source(c['source_ref'])}"
         for c in snapshot["supported_findings"]], "none",
    ))
    lines.append("\nCurrent claim assessments (PARTIALLY_SUPPORTED):\n")
    lines.append(_bullets(
        [f"{c['claim_id']}: {c['statement']} ({c['assessment_id']}){_fmt_source(c['source_ref'])}"
         for c in snapshot["partially_supported_findings"]], "none",
    ))
    lines.append("\nCurrent claim assessments (REFUTED - negative results, permanently preserved):\n")
    lines.append(_bullets(
        [f"{c['claim_id']}: {c['statement']} ({c['assessment_id']}){_fmt_source(c['source_ref'])}"
         for c in snapshot["refuted_findings"]], "none",
    ))
    lines.append("\nCurrent claim assessments (INCONCLUSIVE):\n")
    lines.append(_bullets(
        [f"{c['claim_id']}: {c['statement']} ({c['assessment_id']}){_fmt_source(c['source_ref'])}"
         for c in snapshot["inconclusive_findings"]], "none",
    ))
    if snapshot["research_assessment_conflicts"]:
        lines.append("\nUNRESOLVED CONFLICTING ASSESSMENTS (fail-closed, no current outcome selected):\n")
        lines.append(_bullets(
            [f"{c['claim_id']}: conflicting assessment ids {c['conflicting_assessment_ids']}" for c in snapshot["research_assessment_conflicts"]],
            "none",
        ))

    section("Known Constraints")
    lines.append(_bullets([f"{c['constraint']}{_fmt_source(c['source_ref'])}" for c in snapshot["known_constraints"]], "none recorded"))

    section("Known Limitations")
    lines.append(_bullets(
        [f"[{l['principle_id']}] ({l['status']}) {l['limitation']}{_fmt_source(l['source_ref'])}" for l in snapshot["known_limitations"]],
        "none disclosed",
    ))

    section("Unresolved Questions")
    lines.append(_bullets([f"{q['question']}{_fmt_source(q['source_ref'])}" for q in snapshot["unresolved_questions"]], "none open"))

    section("Recent Verified Changes")
    lines.append(_bullets(
        [f"[{c['timestamp']}] ({c['kind']}) {c['summary']}{_fmt_source(c['source_ref'])}" for c in snapshot["recent_changes"]],
        "no recent changes recorded",
    ))

    section("Next Required Actions")
    for priority in ("REQUIRED", "RECOMMENDED", "OPTIONAL"):
        items = [a for a in snapshot["next_actions"] if a["priority"] == priority]
        lines.append(f"\n{priority.title()}:\n")
        lines.append(_bullets([f"{a['action']}{_fmt_source(a['source_ref'])}" for a in items], "none"))

    body = "".join(lines)
    return _redact(body)


def render_memory_markdown(snapshot: dict[str, Any]) -> str:
    body = _render_body_sections(snapshot)
    integrity = snapshot["integrity"]
    section = (
        "\n## Source Integrity\n"
        f"- generated_at: {snapshot['generated_at']} by {snapshot['generated_by']}\n"
        f"- methodology_version: {snapshot['methodology_version']}\n"
        f"- source_count: {integrity['source_count']}\n"
        f"- source_fingerprint: {integrity['source_fingerprint']}\n"
        f"- projection_hash: {integrity['projection_hash']}\n"
        f"- generator_version: {integrity['generator_version']}\n"
        f"- conflicts: {integrity['conflicts'] or 'none'}\n"
        "\nThis is a snapshot as of generation time; sources may have changed since. "
        "Run `nogap memory status` to check for staleness before relying on this file.\n"
    )
    return _redact(body + section)


# --- persistence / status / query -----------------------------------------

def rebuild_memory(project: Path, actor: str) -> dict[str, Any]:
    """Always regenerates and overwrites both snapshot.json and MEMORY.md from
    current sources, unconditionally. Safe to call any time - both files are purely
    derived, so overwriting them can never lose project truth."""
    project = project.resolve()
    snapshot = build_memory_snapshot(project, actor)
    body = _render_body_sections(snapshot)
    snapshot["integrity"]["projection_hash"] = hashlib.sha256(body.encode("utf-8")).hexdigest()

    snap_path = snapshot_path(project)
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    markdown = render_memory_markdown(snapshot)
    md_path = markdown_path(project)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")

    return snapshot


def memory_status(project: Path) -> dict[str, Any]:
    """CURRENT | STALE | MODIFIED | MISSING | INVALID, with reasons. Never rebuilds -
    read-only. Precedence: MISSING > INVALID > MODIFIED > STALE > CURRENT."""
    project = project.resolve()
    snap_path, md_path = snapshot_path(project), markdown_path(project)

    if not snap_path.is_file() or not md_path.is_file():
        missing = [str(p) for p in (snap_path, md_path) if not p.is_file()]
        return {"status": "MISSING", "reasons": [f"missing: {m}" for m in missing]}

    try:
        snapshot = load_memory_snapshot(project)
    except MethodologyValidationError as exc:
        return {"status": "INVALID", "reasons": [str(exc)]}

    body = _render_body_sections(snapshot)
    expected_projection_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if expected_projection_hash != snapshot["integrity"].get("projection_hash"):
        return {"status": "INVALID", "reasons": ["snapshot.json integrity.projection_hash does not match its own content - snapshot.json was corrupted or hand-edited"]}

    expected_markdown = render_memory_markdown(snapshot)
    actual_markdown = md_path.read_text(encoding="utf-8")
    if actual_markdown != expected_markdown:
        return {"status": "MODIFIED", "reasons": ["MEMORY.md does not match what would be rendered from the current snapshot - it was hand-edited; rebuild to restore it"]}

    try:
        sources = collect_memory_sources(project)
    except MethodologyValidationError as exc:
        return {"status": "INVALID", "reasons": [f"a current source is malformed: {exc}"]}
    current_fingerprint = compute_source_fingerprint(sources)
    if current_fingerprint != snapshot["integrity"]["source_fingerprint"]:
        return {"status": "STALE", "reasons": ["one or more sources changed since this snapshot was built - rebuild required"]}

    return {"status": "CURRENT", "reasons": []}


def query_memory(project: Path, category: str | None = None, item_id: str | None = None) -> Any:
    """Read-only query against the PERSISTED snapshot (never rebuilds implicitly -
    staleness must be visible via memory_status, not silently papered over)."""
    snapshot = load_memory_snapshot(project)
    if snapshot is None:
        raise MethodologyValidationError("memory: no snapshot exists yet; run `nogap memory build` first")
    if category is None:
        return snapshot
    if category not in snapshot:
        raise MethodologyValidationError(f"memory: unknown query category {category!r}")
    result = snapshot[category]
    if item_id is None:
        return result
    if isinstance(result, list):
        matches = [
            item for item in result
            if isinstance(item, dict) and item_id in {
                item.get("failure_id"), item.get("task_id"), item.get("artifact_id"),
                item.get("id"), item.get("requirement_id"), item.get("source_ref"),
            }
        ]
        return matches
    raise MethodologyValidationError(f"memory: category {category!r} is not a list; item_id lookup not applicable")


def verify_projection_integrity(project: Path) -> dict[str, Any]:
    """A focused subset of memory_status(): only the tamper/consistency checks
    (snapshot self-consistency + MEMORY.md-matches-snapshot), never source staleness."""
    status = memory_status(project)
    if status["status"] == "MISSING":
        return {"valid": False, "status": "MISSING", "reasons": status["reasons"]}
    if status["status"] in {"INVALID", "MODIFIED"}:
        return {"valid": False, "status": status["status"], "reasons": status["reasons"]}
    return {"valid": True, "status": status["status"], "reasons": []}
