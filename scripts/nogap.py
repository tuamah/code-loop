#!/usr/bin/env python3
"""Minimal NoGapCode runtime CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROUTER_POLICY_PATH = Path(__file__).resolve().parents[1] / "runtime" / "config" / "model-router.policy.json"
RUNTIME_DIRS = [
    "gates", "claims", "evidence", "events", "decisions", "lessons", "artifacts", "literature",
    "plans", "routes", "dispatches",
]
EVIDENCE_STATUS = {"passed", "failed", "blocked", "inconclusive"}
CLAIM_STATUS = {"unverified", "supported", "contradicted", "superseded"}
DECISIONS = {"accept", "repair", "rerun", "ask-human", "reject", "abstain"}
PLAN_STATUS = {"draft", "proposed", "superseded"}
DISPATCH_STATUS = {"intended", "cancelled", "superseded"}
AUTHORITY_CLASSES = {"execution", "verification", "acceptance", "human", "tool"}
AUTHORITATIVE_EVIDENCE_AUTHORITIES = {"verification", "human"}
ACCEPTANCE_AUTHORITIES = {"acceptance", "human"}
EXECUTION_ROLES = {"executor", "implementer", "repairer"}
LITERATURE_SOURCE_TYPES = {
    "official-doc", "standard", "security-guide", "paper", "systematic-review", "github-project", "engineering-post"
}
LITERATURE_BENEFITS = {"reliability", "security", "accuracy", "speed", "size", "token-cost"}
LITERATURE_COSTS = {"code", "latency", "tokens", "attack-surface", "maintenance", "complexity"}
LITERATURE_DECISIONS = {"learn", "defer", "reject"}
MAX_LITERATURE_CLAIM = 500
MAX_LITERATURE_LESSON = 280
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,}", re.IGNORECASE)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def runtime_root(path: Path) -> Path:
    root = path.resolve()
    if root.name == "runtime":
        return root
    if (root / "runtime").exists():
        return root / "runtime"
    return root / ".code-loop" / "runtime"


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"FAIL: {path} is invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"FAIL: {path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stable_hash(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def gate_hash(gate: dict[str, Any]) -> str:
    payload = dict(gate)
    payload.pop("hash", None)
    return stable_hash(payload)


def append_event(root: Path, event: dict[str, Any]) -> None:
    with (root / "events" / f"{event['run_id']}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def load_router_policy() -> dict[str, Any]:
    try:
        data = json.loads(ROUTER_POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def ensure_runtime(root: Path) -> None:
    for name in RUNTIME_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)


def require_string(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"FAIL: {path} missing non-empty string: {key}")
    return value


def actor_id(value: dict[str, Any]) -> str:
    for key in ("actor_id", "authority_id", "created_by", "decided_by", "agent_id"):
        actor = value.get(key)
        if isinstance(actor, str) and actor.strip():
            return actor.strip()
    return ""


def authority_class(value: dict[str, Any]) -> str:
    authority = value.get("authority") or value.get("authority_class")
    if isinstance(authority, str):
        return authority.strip().lower()
    return ""


def evidence_actor(item: dict[str, Any]) -> str:
    provenance = item.get("provenance")
    return actor_id(provenance) if isinstance(provenance, dict) else ""


def evidence_authority(item: dict[str, Any]) -> str:
    provenance = item.get("provenance")
    return authority_class(provenance) if isinstance(provenance, dict) else ""


def execution_actor_ids(evidence: dict[str, dict[str, Any]]) -> set[str]:
    actors: set[str] = set()
    for item in evidence.values():
        provenance = item.get("provenance")
        if not isinstance(provenance, dict):
            continue
        role = str(provenance.get("role", "")).strip().lower()
        if evidence_authority(item) == "execution" or role in EXECUTION_ROLES:
            actor = evidence_actor(item)
            if actor:
                actors.add(actor)
    return actors


def is_authoritative_evidence(item: dict[str, Any], frozen_hashes: set[str]) -> bool:
    provenance = item.get("provenance")
    if not isinstance(provenance, dict):
        return False
    return (
        item.get("status") == "passed"
        and authority_class(provenance) in AUTHORITATIVE_EVIDENCE_AUTHORITIES
        and actor_id(provenance) != ""
        and provenance.get("gate_hash") in frozen_hashes
    )


def acceptability(
    decision: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    frozen_hashes: set[str],
) -> str:
    if decision.get("decision") != "accept":
        return ""
    decision_actor = actor_id(decision)
    decision_authority = authority_class(decision)
    if decision_authority not in ACCEPTANCE_AUTHORITIES:
        return "ACCEPT requires acceptance or human decision authority"
    if not decision_actor:
        return "ACCEPT requires decision actor identity"
    executors = execution_actor_ids(evidence)
    if decision_actor in executors:
        return "executor identity cannot issue ACCEPT"

    referenced = decision.get("evidence", [])
    if not isinstance(referenced, list) or not referenced:
        return "ACCEPT requires evidence references"

    authoritative_passes: list[str] = []
    for evidence_id in referenced:
        item = evidence.get(evidence_id)
        if item is None:
            return f"ACCEPT references missing evidence {evidence_id}"
        if item.get("status") != "passed":
            return f"ACCEPT references non-passing evidence {evidence_id}"
        if is_authoritative_evidence(item, frozen_hashes):
            if evidence_actor(item) in executors:
                return f"authoritative evidence {evidence_id} uses execution identity"
            authoritative_passes.append(evidence_id)

    if not authoritative_passes:
        return "ACCEPT requires independent authoritative verification evidence"

    for evidence_id, item in evidence.items():
        if evidence_authority(item) in AUTHORITATIVE_EVIDENCE_AUTHORITIES and item.get("status") in {"failed", "blocked", "inconclusive"}:
            return f"contradictory authoritative evidence blocks ACCEPT: {evidence_id}"
    return ""


def load_objects(directory: Path) -> dict[str, dict[str, Any]]:
    objects: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        data = read_json(path)
        object_id = require_string(data, "id", path)
        if object_id in objects:
            raise SystemExit(f"FAIL: duplicate id {object_id} in {directory}")
        objects[object_id] = data
    return objects


def text_tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(value)}


def literature_goal_matches(item: dict[str, Any], goal: dict[str, Any]) -> bool:
    goal_text = " ".join([goal.get("objective", ""), *goal.get("tags", [])])
    item_text = " ".join([
        item.get("claim", ""),
        item.get("lesson", ""),
        item.get("source", {}).get("title", ""),
        " ".join(item.get("applies_when", [])),
    ])
    return bool(text_tokens(goal_text) & text_tokens(item_text))


def literature_checks(item: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    source = item.get("source")
    if not isinstance(source, dict):
        failures.append("missing source")
    else:
        if source.get("type") not in LITERATURE_SOURCE_TYPES:
            failures.append("untrusted source type")
        if not source.get("title") or not source.get("url"):
            failures.append("source title and url required")

    claim = item.get("claim")
    lesson = item.get("lesson")
    if not isinstance(claim, str) or not claim.strip():
        failures.append("claim required")
    elif len(claim) > MAX_LITERATURE_CLAIM:
        failures.append("claim too long")
    if not isinstance(lesson, str) or not lesson.strip():
        failures.append("lesson required")
    elif len(lesson) > MAX_LITERATURE_LESSON:
        failures.append("lesson too long")

    benefits = item.get("benefit")
    if not isinstance(benefits, list) or not benefits or any(value not in LITERATURE_BENEFITS for value in benefits):
        failures.append("valid benefit required")
    costs = item.get("cost", [])
    if not isinstance(costs, list) or any(value not in LITERATURE_COSTS for value in costs):
        failures.append("invalid cost")
    if item.get("evidence_strength") not in {"primary", "secondary"}:
        failures.append("primary or secondary evidence required")
    if not isinstance(item.get("can_be_tested_by"), str) or not item["can_be_tested_by"].strip():
        failures.append("testability required")

    quality = item.get("meaning_quality")
    if not isinstance(quality, dict):
        failures.append("meaning quality required")
    else:
        for key in ("accurate", "concise", "complete"):
            if quality.get(key) is not True:
                failures.append(f"meaning must be {key}")
    return failures


def learn_literature(root: Path, run_id: str, item_id: str, item: dict[str, Any], actor: str) -> str:
    decision_id = f"decision-literature-{item_id}"
    tags = sorted(set(["literature", *item.get("applies_when", [])]))
    lesson_id = f"lesson-{stable_hash({'run_id': run_id, 'source': item_id, 'text': item['lesson']})[:12]}"
    if (root / "lessons" / f"{lesson_id}.json").exists():
        return lesson_id
    evidence_refs = item.get("acceptance_evidence", [])
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise SystemExit(f"FAIL: literature claim {item_id} requires acceptance_evidence before learning")
    gates = load_objects(root / "gates")
    frozen_hashes = {
        gate_hash(gate)
        for gate in gates.values()
        if gate.get("run_id") == run_id and gate.get("status") == "frozen" and gate.get("hash") == gate_hash(gate)
    }
    evidence = load_objects(root / "evidence")
    decision = {
        "id": decision_id,
        "run_id": run_id,
        "decision": "accept",
        "reason": f"literature claim {item_id}: {item.get('reason', '')}",
        "evidence": evidence_refs,
        "created_at": now(),
        "decided_by": actor,
        "actor_id": actor,
        "authority": "acceptance",
    }
    failure = acceptability(decision, evidence, frozen_hashes)
    if failure:
        raise SystemExit(f"FAIL: literature claim {item_id} lacks admissible acceptance evidence: {failure}")
    lesson = {
        "id": lesson_id,
        "run_id": run_id,
        "text": item["lesson"],
        "applies_when": {
            "tags": tags,
            "decision": "accept",
            "reason": decision["reason"],
        },
        "evidence": evidence_refs,
        "source_decision": decision_id,
        "created_at": now(),
    }
    write_json(root / "decisions" / f"{decision_id}.json", decision)
    write_json(root / "lessons" / f"{lesson_id}.json", lesson)
    append_event(root, {
        "id": f"event-{lesson_id}",
        "run_id": run_id,
        "type": "LITERATURE_LESSON_LEARNED",
        "created_at": lesson["created_at"],
        "actor": actor,
        "payload": {"literature_id": item_id, "lesson_id": lesson_id, "tags": tags}
    })
    return lesson_id


def cmd_init(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.target))
    if root.exists() and args.force:
        shutil.rmtree(root)
    elif root.exists() and any(root.iterdir()):
        raise SystemExit(f"{root} already exists; use --force to replace it")

    ensure_runtime(root)
    write_json(root / "run.json", {
        "id": args.run_id,
        "objective": args.objective,
        "status": "planning",
        "created_at": now(),
        "decision": "undecided",
    })
    write_json(root / "gates" / "gate-0001.json", {
        "id": "gate-0001",
        "run_id": args.run_id,
        "version": 1,
        "status": "draft",
        "rules": {
            "protected_paths": [],
            "forbidden_paths": [],
            "required_commands": [],
            "forbidden_changes": [
                "delete failing tests",
                "relax thresholds without human approval",
                "rewrite baselines without human approval",
                "disable verifier"
            ],
            "metrics": [],
            "invariants": []
        }
    })
    append_event(root, {
        "id": "event-0001",
        "run_id": args.run_id,
        "type": "TASK_CREATED",
        "created_at": now(),
        "actor": "nogap init",
        "payload": {"objective": args.objective}
    })
    print(f"initialized NoGapCode runtime: {root}")


def cmd_freeze(args: argparse.Namespace) -> None:
    path = Path(args.path)
    gate_path = path.resolve() if path.suffix == ".json" else runtime_root(path) / "gates" / args.gate
    gate = read_json(gate_path)
    if gate.get("status") == "frozen" and gate.get("hash"):
        if gate["hash"] != gate_hash(gate):
            raise SystemExit("FAIL: frozen gate hash does not match its payload")
        print(f"gate already frozen: {gate_path}")
        return

    gate["status"] = "frozen"
    gate["frozen_by"] = args.actor
    gate["frozen_at"] = now()
    gate["hash"] = gate_hash(gate)
    write_json(gate_path, gate)
    root = gate_path.parents[1]
    append_event(root, {
        "id": f"event-freeze-{gate['id']}",
        "run_id": gate["run_id"],
        "type": "GATE_FROZEN",
        "created_at": gate["frozen_at"],
        "actor": args.actor,
        "payload": {"gate_id": gate["id"], "gate_hash": gate["hash"]}
    })
    print(f"frozen gate {gate['id']}: {gate['hash']}")


def cmd_validate(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    if not root.exists():
        raise SystemExit(f"FAIL: runtime directory does not exist: {root}")
    missing = [name for name in RUNTIME_DIRS if not (root / name).is_dir()]
    if missing:
        raise SystemExit("FAIL: missing runtime directories: " + ", ".join(missing))

    run = read_json(root / "run.json")
    run_id = require_string(run, "id", root / "run.json")
    gates = load_objects(root / "gates")
    claims = load_objects(root / "claims")
    evidence = load_objects(root / "evidence")
    decisions = load_objects(root / "decisions")
    lessons = load_objects(root / "lessons")
    literature = load_objects(root / "literature")
    plans = load_objects(root / "plans")
    routes = load_objects(root / "routes")
    dispatches = load_objects(root / "dispatches")

    frozen_hashes: set[str] = set()
    for gate_id, gate in gates.items():
        if gate.get("run_id") != run_id:
            raise SystemExit(f"FAIL: gate {gate_id} references a different run_id")
        if gate.get("status") == "frozen":
            actual = gate_hash(gate)
            if gate.get("hash") != actual:
                raise SystemExit(f"FAIL: frozen gate {gate_id} hash mismatch")
            frozen_hashes.add(actual)
        elif gate.get("status") not in {"draft", "superseded"}:
            raise SystemExit(f"FAIL: gate {gate_id} has invalid status")

    for claim_id, claim in claims.items():
        if claim.get("run_id") != run_id:
            raise SystemExit(f"FAIL: claim {claim_id} references a different run_id")
        if claim.get("status") not in CLAIM_STATUS:
            raise SystemExit(f"FAIL: claim {claim_id} has invalid status")
        if claim.get("status") == "supported" and not claim.get("evidence"):
            raise SystemExit(f"FAIL: supported claim {claim_id} has no evidence")
        for evidence_id in claim.get("evidence", []):
            if evidence_id not in evidence:
                raise SystemExit(f"FAIL: claim {claim_id} references missing evidence {evidence_id}")

    for evidence_id, item in evidence.items():
        if item.get("run_id") != run_id:
            raise SystemExit(f"FAIL: evidence {evidence_id} references a different run_id")
        if item.get("status") not in EVIDENCE_STATUS:
            raise SystemExit(f"FAIL: evidence {evidence_id} has invalid status")
        provenance = item.get("provenance")
        if not isinstance(provenance, dict):
            raise SystemExit(f"FAIL: evidence {evidence_id} missing provenance")
        require_string(provenance, "created_by", root / "evidence" / f"{evidence_id}.json")
        require_string(provenance, "created_at", root / "evidence" / f"{evidence_id}.json")
        authority = authority_class(provenance)
        if authority and authority not in AUTHORITY_CLASSES:
            raise SystemExit(f"FAIL: evidence {evidence_id} has invalid authority")
        gate_ref = provenance.get("gate_hash")
        if gate_ref and gate_ref not in frozen_hashes:
            raise SystemExit(f"FAIL: evidence {evidence_id} references unknown gate_hash")
        for claim_id in item.get("claim_ids", []):
            if claim_id not in claims:
                raise SystemExit(f"FAIL: evidence {evidence_id} references missing claim {claim_id}")

    for decision_id, decision in decisions.items():
        if decision.get("run_id") != run_id:
            raise SystemExit(f"FAIL: decision {decision_id} references a different run_id")
        if decision.get("decision") not in DECISIONS:
            raise SystemExit(f"FAIL: decision {decision_id} has invalid decision")
        authority = authority_class(decision)
        if authority and authority not in AUTHORITY_CLASSES:
            raise SystemExit(f"FAIL: decision {decision_id} has invalid authority")
        for evidence_id in decision.get("evidence", []):
            if evidence_id not in evidence:
                raise SystemExit(f"FAIL: decision {decision_id} references missing evidence {evidence_id}")
            if decision["decision"] == "accept" and evidence[evidence_id].get("status") != "passed":
                raise SystemExit(f"FAIL: decision {decision_id} accepts non-passing evidence {evidence_id}")
        failure = acceptability(decision, evidence, frozen_hashes)
        if failure:
            raise SystemExit(f"FAIL: decision {decision_id} inadmissible: {failure}")

    for lesson_id, lesson in lessons.items():
        if lesson.get("run_id") != run_id:
            raise SystemExit(f"FAIL: lesson {lesson_id} references a different run_id")
        applies_when = lesson.get("applies_when")
        if not isinstance(applies_when, dict) or not applies_when.get("tags"):
            raise SystemExit(f"FAIL: lesson {lesson_id} missing applies_when.tags")
        if lesson.get("source_decision") not in decisions:
            raise SystemExit(f"FAIL: lesson {lesson_id} references missing source_decision")
        for evidence_id in lesson.get("evidence", []):
            if evidence_id not in evidence:
                raise SystemExit(f"FAIL: lesson {lesson_id} references missing evidence {evidence_id}")

    for item_id, item in literature.items():
        if item.get("decision") not in LITERATURE_DECISIONS:
            raise SystemExit(f"FAIL: literature claim {item_id} has invalid decision")
        failures = literature_checks(item)
        if item.get("decision") == "learn" and failures:
            raise SystemExit(f"FAIL: literature claim {item_id} cannot be learned: {', '.join(failures)}")
        if item.get("decision") == "learn" and not item.get("acceptance_evidence"):
            raise SystemExit(f"FAIL: literature claim {item_id} cannot be learned without acceptance_evidence")

    for plan_id, plan in plans.items():
        if plan.get("run_id") != run_id:
            raise SystemExit(f"FAIL: plan {plan_id} references a different run_id")
        require_string(plan, "actor_id", root / "plans" / f"{plan_id}.json")
        if plan.get("status") not in PLAN_STATUS:
            raise SystemExit(f"FAIL: plan {plan_id} has invalid status")

    for route_id, route in routes.items():
        if route.get("run_id") != run_id:
            raise SystemExit(f"FAIL: route {route_id} references a different run_id")
        selected = route.get("selected")
        if not isinstance(selected, dict) or not selected.get("provider") or not selected.get("runtime"):
            raise SystemExit(f"FAIL: route {route_id} missing selected.provider/runtime")
        require_string(route, "reason", root / "routes" / f"{route_id}.json")

    for dispatch_id, dispatch in dispatches.items():
        if dispatch.get("run_id") != run_id:
            raise SystemExit(f"FAIL: dispatch {dispatch_id} references a different run_id")
        require_string(dispatch, "actor_id", root / "dispatches" / f"{dispatch_id}.json")
        if dispatch.get("status") not in DISPATCH_STATUS:
            raise SystemExit(f"FAIL: dispatch {dispatch_id} has invalid status")
        plan_ref = dispatch.get("plan_id")
        if plan_ref and plan_ref not in plans:
            raise SystemExit(f"FAIL: dispatch {dispatch_id} references missing plan {plan_ref}")
        route_ref = dispatch.get("route_id")
        if route_ref and route_ref not in routes:
            raise SystemExit(f"FAIL: dispatch {dispatch_id} references missing route {route_ref}")

    for path in sorted((root / "events").glob("*.jsonl")):
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"FAIL: {path}:{index} invalid JSONL event: {exc}") from exc
            if event.get("run_id") != run_id:
                raise SystemExit(f"FAIL: {path}:{index} references unknown run_id")
            require_string(event, "id", path)
            require_string(event, "type", path)
            require_string(event, "created_at", path)

    print(f"OK: runtime workspace valid: {root}")


def compute_status(root: Path) -> dict[str, Any]:
    missing_dirs = [name for name in RUNTIME_DIRS if not (root / name).is_dir()]
    runtime_exists = root.is_dir() and not missing_dirs
    if not runtime_exists:
        return {
            "runtime_path": str(root),
            "runtime_exists": False,
            "missing_dirs": missing_dirs if root.is_dir() else list(RUNTIME_DIRS),
            "run_id": None,
            "objective": None,
            "gate_count": 0,
            "frozen_gate_count": 0,
            "claim_count": 0,
            "evidence_count": 0,
            "authoritative_pass_count": 0,
            "authoritative_fail_count": 0,
            "decision_count": 0,
            "last_decision": None,
        }

    run = read_json(root / "run.json")
    gates = load_objects(root / "gates")
    claims = load_objects(root / "claims")
    evidence = load_objects(root / "evidence")
    decisions = load_objects(root / "decisions")

    frozen_hashes = {
        gate_hash(gate)
        for gate in gates.values()
        if gate.get("status") == "frozen" and gate.get("hash") == gate_hash(gate)
    }
    authoritative_pass_count = sum(
        1 for item in evidence.values() if is_authoritative_evidence(item, frozen_hashes)
    )
    authoritative_fail_count = sum(
        1 for item in evidence.values()
        if evidence_authority(item) in AUTHORITATIVE_EVIDENCE_AUTHORITIES
        and item.get("status") in {"failed", "blocked", "inconclusive"}
    )
    ordered_decisions = sorted(decisions.values(), key=lambda item: str(item.get("created_at", "")))
    last = ordered_decisions[-1] if ordered_decisions else None

    return {
        "runtime_path": str(root),
        "runtime_exists": True,
        "missing_dirs": [],
        "run_id": run.get("id", ""),
        "objective": run.get("objective", ""),
        "gate_count": len(gates),
        "frozen_gate_count": sum(1 for gate in gates.values() if gate.get("status") == "frozen"),
        "claim_count": len(claims),
        "evidence_count": len(evidence),
        "authoritative_pass_count": authoritative_pass_count,
        "authoritative_fail_count": authoritative_fail_count,
        "decision_count": len(decisions),
        "last_decision": {
            "id": last.get("id", ""),
            "decision": last.get("decision", ""),
            "reason": last.get("reason", ""),
            "created_at": last.get("created_at", ""),
        } if last else None,
    }


def cmd_status(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    status = compute_status(root)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return
    if not status["runtime_exists"]:
        print(f"NO-RUNTIME: {status['runtime_path']}")
        print(f"  missing: {', '.join(status['missing_dirs']) or 'unknown'}")
        return
    print(f"RUNTIME: {status['runtime_path']}")
    print(f"  run_id: {status['run_id']}")
    print(f"  objective: {status['objective']}")
    print(f"  gates: {status['gate_count']} ({status['frozen_gate_count']} frozen)")
    print(f"  claims: {status['claim_count']}")
    print(
        f"  evidence: {status['evidence_count']} "
        f"(authoritative pass={status['authoritative_pass_count']} fail={status['authoritative_fail_count']})"
    )
    print(f"  decisions: {status['decision_count']}")
    if status["last_decision"]:
        last = status["last_decision"]
        print(f"  last_decision: {last['decision']} ({last['id']}) - {last['reason']}")
    else:
        print("  last_decision: none")


def route_implementer() -> tuple[dict[str, str] | None, list[dict[str, Any]]]:
    """Pick a ready AgentRuntime for `role` from real adapter health, not policy config alone.

    The router policy file states an intended preference, but selection must reflect what is
    actually connected right now. An adapter that is not truly ready is never selected, even if
    the policy prefers it: this orchestrator never fabricates a working route.
    """
    from nogap_adapters import ADAPTERS

    considered: list[dict[str, Any]] = []
    selected: dict[str, str] | None = None
    for adapter in ADAPTERS.values():
        if adapter.kind != "AgentRuntime":
            continue
        health = adapter.health()
        ready = health.get("status") == "connected"
        considered.append({
            "provider": adapter.id,
            "runtime": adapter.id,
            "available": ready,
            "reason": str(health.get("trust_status", "NOT_READY")),
        })
        if ready and selected is None:
            selected = {"provider": adapter.id, "runtime": adapter.id}
    return selected, considered


def cmd_run(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    status = compute_status(root)
    if not status["runtime_exists"]:
        raise SystemExit(f"FAIL: no runtime at {root}; run 'nogap init' first")

    # M7-F: methodology preflight is computed up front and printed unconditionally, even
    # for a planning-only run (no --execute) - "planning may inspect/report methodology
    # blockers" - but it only actually GATES anything once --execute is requested, below.
    project_root = Path(args.path)
    from nogap_build import preflight_build

    preflight = preflight_build(project_root)
    phase_note = f" phase={preflight['current_phase']}" if preflight["current_phase"] else ""
    profile_note = f" profile={preflight['profile']}" if preflight["profile"] else ""
    print(f"methodology: status={preflight['status']}{profile_note}{phase_note}")
    if preflight["status"] == "METHODOLOGY_BLOCKED":
        for item in preflight["reasons"]:
            print(f"  - {item}")

    run = read_json(root / "run.json")
    run_id = require_string(run, "id", root / "run.json")
    objective = run.get("objective", "")
    actor = args.actor
    policy = load_router_policy()

    plan_id = f"plan-{stable_hash({'run_id': run_id, 'objective': objective, 'created_at': now()})[:12]}"
    plan = {
        "id": plan_id,
        "run_id": run_id,
        "created_at": now(),
        "actor_id": actor,
        "role": "planner",
        "status": "proposed",
        "objective": objective,
        "steps": [{"summary": objective, "role": "implementer"}],
        "reason": "orchestrator forwarded the run objective as a single implementer step",
    }
    write_json(root / "plans" / f"{plan_id}.json", plan)
    append_event(root, {
        "id": f"event-{plan_id}",
        "run_id": run_id,
        "type": "PLAN_PROPOSED",
        "created_at": plan["created_at"],
        "actor": actor,
        "payload": {"plan_id": plan_id},
    })

    selected, considered = route_implementer()
    if selected is None:
        append_event(root, {
            "id": f"event-route-unavailable-{plan_id}",
            "run_id": run_id,
            "type": "ROUTE_UNAVAILABLE",
            "created_at": now(),
            "actor": actor,
            "payload": {"plan_id": plan_id, "considered": considered},
        })
        names = ", ".join(item["provider"] for item in considered) or "none configured"
        print(f"plan {plan_id} proposed; no ready implementer AgentRuntime (checked: {names})")
        print("dispatch not created: connect Codex or Claude Code in the dashboard, then re-run.")
        if args.execute:
            print("build_status=DISPATCH_FAILED")
        return

    route_id = f"route-{stable_hash({'run_id': run_id, 'plan_id': plan_id, 'selected': selected})[:12]}"
    route = {
        "id": route_id,
        "run_id": run_id,
        "role": "implementer",
        "selected": selected,
        "considered": considered,
        "reason": f"{selected['provider']} reported a connected AgentRuntime health probe",
        "policy_version": str(policy.get("policy_version", "unversioned")),
        "created_at": now(),
    }
    write_json(root / "routes" / f"{route_id}.json", route)
    append_event(root, {
        "id": f"event-{route_id}",
        "run_id": run_id,
        "type": "ROUTE_SELECTED",
        "created_at": route["created_at"],
        "actor": actor,
        "payload": {"route_id": route_id, "selected": selected},
    })

    dispatch_id = f"dispatch-{stable_hash({'run_id': run_id, 'route_id': route_id})[:12]}"
    dispatch = {
        "id": dispatch_id,
        "run_id": run_id,
        "created_at": now(),
        "actor_id": actor,
        "role": "implementer",
        "provider": selected["provider"],
        "runtime": selected["runtime"],
        "plan_id": plan_id,
        "route_id": route_id,
        "status": "intended",
        "reason": "dispatch records intent only; execution outcome, if any, is recorded separately as execution evidence",
    }
    write_json(root / "dispatches" / f"{dispatch_id}.json", dispatch)
    append_event(root, {
        "id": f"event-{dispatch_id}",
        "run_id": run_id,
        "type": "DISPATCH_INTENDED",
        "created_at": dispatch["created_at"],
        "actor": actor,
        "payload": {"dispatch_id": dispatch_id, "provider": selected["provider"]},
    })
    print(f"plan {plan_id} -> route {route_id} ({selected['provider']}) -> dispatch {dispatch_id} [intended]")

    if not args.execute:
        print("execution dispatch is not implemented by default; pass --execute to run the selected AgentRuntime.")
        return

    # M7-F PREBUILD BARRIER: this is the one place real implementation execution can
    # begin, so it is the one place the gate is enforced - before any worktree or
    # process is created. A project with methodology initialized cannot bypass this via
    # any CLI flag; a project that never initialized methodology at all keeps its
    # pre-M7 behavior (see preflight_build()'s METHODOLOGY_NOT_INITIALIZED policy).
    methodology_tracked = preflight["status"] != "METHODOLOGY_NOT_INITIALIZED"
    if methodology_tracked and not preflight["permitted"]:
        print(f"execution BLOCKED by methodology: {preflight['status']}")
        for item in preflight["reasons"]:
            print(f"  - {item}")
        append_event(root, {
            "id": f"event-methodology-blocked-{plan_id}",
            "run_id": run_id,
            "type": "METHODOLOGY_BLOCKED",
            "created_at": now(),
            "actor": actor,
            "payload": {"plan_id": plan_id, "status": preflight["status"], "reasons": preflight["reasons"]},
        })
        return

    # getattr, not args.task_id: a Namespace built by hand (as some existing tests do,
    # bypassing argparse entirely) may not carry every argparse default.
    requested_task_id = getattr(args, "task_id", None)
    task_contract = None
    if methodology_tracked:
        # "Do not use free-form agent prompt as the canonical task contract": once a
        # project is methodology-tracked and BUILD is permitted, --execute requires a
        # real P12 task contract to bind the run to - not just the run's free-text
        # objective.
        if not requested_task_id:
            raise SystemExit(
                "FAIL: this project is methodology-tracked; --execute requires --task-id "
                "naming a P12_TASK_CONTRACT (create one with "
                "'nogap methodology artifact-create --type P12_TASK_CONTRACT ...')"
            )
        from nogap_build import (
            enter_build_phase,
            enter_execution_phase,
            load_task_contract,
            record_plan_evidence,
        )
        from nogap_methodology import MethodologyValidationError as _MethodologyValidationError

        try:
            task_contract = load_task_contract(project_root, requested_task_id)
            if preflight["current_phase"] == "P11":
                enter_build_phase(project_root, actor, "prebuild readiness satisfied; entering BUILD")
            # A repair selected by M7-H's Failure Orchestrator can legitimately land
            # current_phase directly at P13 (re-entering BUILD for the same task
            # without recreating P12) - only drive P12->P13 when we are not already
            # there, or this would attempt the illegal edge P13->P13.
            if preflight["current_phase"] in ("P11", "P12"):
                plan_evidence_id = record_plan_evidence(project_root, run_id, task_contract, actor)
                enter_execution_phase(
                    project_root, actor, "task contract recorded; entering minimal controlled implementation",
                    task_contract, plan_evidence_id,
                )
        except _MethodologyValidationError as exc:
            raise SystemExit(f"FAIL: {exc}") from exc
    elif requested_task_id:
        print(f"note: --task-id {requested_task_id!r} ignored - this project has no methodology state to bind it to")

    from nogap_adapters import ADAPTERS, ExecutorNotReady
    from nogap_execution import GitWorktreeExecutionBackend

    adapter = ADAPTERS.get(selected["provider"])
    if adapter is None or not hasattr(adapter, "build_exec_command"):
        print(f"execution not available: no execution-capable adapter registered for {selected['provider']!r}.")
        print("build_status=DISPATCH_FAILED")
        return

    prompt = plan["steps"][0]["summary"]
    try:
        backend = GitWorktreeExecutionBackend(Path(args.path).resolve())
        result = backend.run(
            lambda worktree: adapter.build_exec_command(prompt, worktree),
            timeout=args.execute_timeout,
        )
    except ExecutorNotReady as exc:
        print(f"execution aborted: {exc}")
        print("build_status=DISPATCH_FAILED")
        return

    from nogap_build import build_status_label, patch_hash as compute_patch_hash
    from nogap_effects import ExpectedEffect, classify_agent_execution, touched_paths, verify_effect

    # M6-C default: we only know the agent should produce *some* change addressing the
    # objective, not which files. change_type=ANY still refuses to call an empty patch a
    # pass - the RC=0-but-nothing-happened case observed live against Codex's Windows
    # sandbox. Execution success requires BOTH a normal process exit (per the adapter's
    # own allowed_exit_codes policy) AND a satisfied effect: a process that crashed after
    # leaving a partial effect in the patch is exactly as untrustworthy as a clean exit
    # with no effect at all, so neither fact alone is allowed to imply "passed".
    effect = verify_effect(result.patch, ExpectedEffect(change_type="ANY"))
    allowed_exit_codes = adapter.capabilities().get("allowed_exit_codes", [0])
    exec_status, execution_status, reason = classify_agent_execution(
        result.process_outcome, result.returncode, effect, allowed_exit_codes,
    )
    requirement_refs = task_contract["fields"].get("requirement_refs", []) if task_contract else None
    task_id = task_contract["fields"]["task_id"] if task_contract else None
    methodology_version = task_contract["methodology_version"] if task_contract else None
    evidence_id, artifact_path = write_isolated_run_evidence(
        root, run_id, result, actor, exec_status, execution_status, reason,
        dispatch_id=dispatch_id, provider=selected["provider"], runtime_id=selected["runtime"],
        task_id=task_id, requirement_refs=requirement_refs, methodology_version=methodology_version,
    )
    print(
        f"execute {result.execution_id}: {exec_status} ({execution_status}: {reason}) "
        f"evidence={evidence_id} patch={artifact_path}"
    )
    print("execution evidence is not authoritative on its own: independent verification is still required for ACCEPT.")

    build_status = build_status_label(exec_status, execution_status)
    if task_contract is not None:
        from nogap_build import create_self_check, enter_self_check_phase, record_build_failure
        from nogap_methodology import MethodologyValidationError as _MethodologyValidationError

        try:
            if exec_status == "passed":
                enter_self_check_phase(
                    project_root, actor, "execution succeeded; entering self-check", evidence_id, str(artifact_path),
                )
                create_self_check(
                    project_root, task_contract, evidence_id,
                    changed_files=sorted(touched_paths(result.patch)),
                    patch_hash=compute_patch_hash(result.patch),
                    process_outcome=result.process_outcome,
                    expected_effect_result=f"{effect.outcome}: {effect.reason}",
                    actor=actor,
                )
            else:
                record_build_failure(
                    project_root, actor, f"execution did not pass: {execution_status}: {reason}", evidence_id, str(artifact_path),
                )
        except _MethodologyValidationError as exc:
            build_status = "SELF_CHECK_FAILED"
            print(f"self-check recording FAILED: {exc}")
    print(f"build_status={build_status}")


def write_isolated_run_evidence(
    root: Path,
    run_id: str,
    result: Any,
    actor: str,
    status: str,
    execution_status: str,
    reason: str,
    *,
    authority: str = "execution",
    kind: str = "execution",
    role: str = "implementer",
    event_type: str = "EXECUTION_COMPLETED",
    dispatch_id: str | None = None,
    provider: str | None = None,
    runtime_id: str | None = None,
    task_id: str | None = None,
    requirement_refs: list[str] | None = None,
    methodology_version: str | None = None,
) -> tuple[str, Path]:
    """Records an isolated-worktree run (execution or verification) as evidence.

    status/execution_status/reason are supplied by the caller (classify_generic_execution,
    verify_effect+classify_agent_execution, or a verification-pipeline check): this function
    does not judge success itself. authority defaults to "execution" (M6-C dispatch: never
    authoritative for ACCEPT on its own) but M6-D's verification pipeline passes
    authority="verification" - is_authoritative_evidence() only ever counts verification/
    human authority. When `provider` is known, actor_id is provider-qualified
    ("agent:codex") rather than the generic CLI actor string, so that acceptability()'s
    identity-separation check (an executor's evidence cannot also verify) works correctly:
    if the same provider both executed and reviewed, its evidence correctly cannot count as
    independent verification.
    """
    gates = load_objects(root / "gates")
    frozen_hashes = [
        gate_hash(gate)
        for gate in gates.values()
        if gate.get("status") == "frozen" and gate.get("hash") == gate_hash(gate)
    ]

    artifact_path = root / "artifacts" / f"{result.execution_id}.patch"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(result.patch, encoding="utf-8")

    log_path = root / "artifacts" / f"{result.execution_id}.log"
    log_path.write_text(
        f"command: {' '.join(result.command)}\n"
        f"process_outcome: {result.process_outcome} returncode: {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n",
        encoding="utf-8",
    )

    evidence_id = f"evidence-{result.execution_id}"
    actor_id = f"agent:{provider}" if provider else actor
    provenance: dict[str, Any] = {
        "created_by": actor,
        "created_at": now(),
        "actor_id": actor_id,
        "authority": authority,
        "role": role,
        "commit": result.base_commit,
        "command": " ".join(result.command),
        "artifact_path": str(artifact_path),
        "log_path": str(log_path),
    }
    if frozen_hashes:
        provenance["gate_hash"] = frozen_hashes[0]
    if dispatch_id:
        provenance["dispatch_id"] = dispatch_id
    if provider:
        provenance["provider"] = provider
    if runtime_id:
        provenance["runtime"] = runtime_id
    if task_id:
        provenance["task_id"] = task_id
    if requirement_refs:
        provenance["requirement_refs"] = list(requirement_refs)
    if methodology_version:
        provenance["methodology_version"] = methodology_version
    evidence = {
        "id": evidence_id,
        "run_id": run_id,
        "kind": kind,
        "status": status,
        "provenance": provenance,
        "summary": f"{execution_status}: {reason} (process_outcome={result.process_outcome}, returncode={result.returncode})",
    }
    write_json(root / "evidence" / f"{evidence_id}.json", evidence)
    append_event(root, {
        "id": f"event-{evidence_id}",
        "run_id": run_id,
        "type": event_type,
        "created_at": now(),
        "actor": actor,
        "payload": {"execution_id": result.execution_id, "status": status, "evidence_id": evidence_id},
    })
    return evidence_id, artifact_path


def cmd_execute(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    status = compute_status(root)
    if not status["runtime_exists"]:
        raise SystemExit(f"FAIL: no runtime at {root}; run 'nogap init' first")
    command = args.worktree_command
    if not command:
        raise SystemExit("FAIL: execute requires a command, e.g. 'nogap execute . -- python -m pytest'")

    run = read_json(root / "run.json")
    run_id = require_string(run, "id", root / "run.json")

    from nogap_effects import classify_generic_execution
    from nogap_execution import GitWorktreeExecutionBackend

    project_root = Path(args.path).resolve()
    backend = GitWorktreeExecutionBackend(project_root)
    result = backend.run(command, timeout=args.timeout)

    exec_status, execution_status, reason = classify_generic_execution(result)
    evidence_id, artifact_path = write_isolated_run_evidence(
        root, run_id, result, args.actor, exec_status, execution_status, reason,
    )
    print(
        f"execution {result.execution_id}: {exec_status} (returncode={result.returncode}) "
        f"evidence={evidence_id} patch={artifact_path}"
    )
    print("execution evidence is not authoritative on its own: independent verification is still required for ACCEPT.")


def _write_skip_evidence(
    root: Path, run_id: str, actor: str, dispatch_id: str, phase_id: str, reason: str,
    task_id: str, methodology_version: str,
) -> str:
    """A tiny, honest evidence stub for a VERIFY phase explicitly skipped per profile
    policy - never a real check result, so the phase's required_evidence for
    transition() has a real, resolvable id to cite instead of a fabricated string
    (mirrors nogap_build.py's record_plan_evidence). kind="skip", authority=
    "methodology" - never "verification", so it can never be mistaken for a real check."""
    evidence_dir = root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_id = f"evidence-skip-{phase_id.lower()}-{uuid.uuid4().hex[:8]}"
    evidence = {
        "id": evidence_id,
        "run_id": run_id,
        "kind": "skip",
        "status": "recorded",
        "provenance": {
            "created_by": actor, "actor_id": actor, "authority": "methodology",
            "task_id": task_id, "methodology_version": methodology_version, "dispatch_id": dispatch_id,
        },
        "summary": f"{phase_id} explicitly skipped: {reason}",
    }
    (evidence_dir / f"{evidence_id}.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence_id


def _finalize_verification(project_root: Path, verification_result: dict[str, Any], gate: dict[str, Any], actor: str) -> dict[str, Any]:
    """The one place a P18_VERIFICATION_RESULT's terminal status is decided: never
    ACCEPTED, and never COMPLETE_AWAITING_DECISION if the binding it was computed
    against has since gone stale (checked here, not deferred to M8)."""
    import nogap_verify_binding as vb
    from nogap_artifacts import update_verification_result

    review_result = verification_result["fields"]["independent_review_result"]
    if review_result == "failed":
        status, label = "VERIFICATION_FAILED", "INDEPENDENT_REVIEW_FAILED"
    elif review_result == "inconclusive":
        status, label = "VERIFICATION_INCONCLUSIVE", "INDEPENDENT_REVIEW_INCONCLUSIVE"
    else:
        stale_reasons = vb.verification_staleness(project_root, verification_result, gate.get("hash"))
        if stale_reasons:
            status, label = "VERIFICATION_INCONCLUSIVE", "STALE_VERIFICATION_EVIDENCE"
            for reason in stale_reasons:
                print(f"  [staleness] {reason}")
        else:
            status, label = "VERIFICATION_COMPLETE_AWAITING_DECISION", "VERIFICATION_COMPLETE_AWAITING_DECISION"

    updated = update_verification_result(
        project_root, verification_result["fields"]["verification_run_id"], actor, f"verification finalized: {label}", status=status,
    )
    print(f"verification_status={label}")
    return updated


def cmd_verify(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    status = compute_status(root)
    if not status["runtime_exists"]:
        raise SystemExit(f"FAIL: no runtime at {root}; run 'nogap init' first")

    run = read_json(root / "run.json")
    run_id = require_string(run, "id", root / "run.json")
    objective = run.get("objective", "")

    dispatches = load_objects(root / "dispatches")
    if args.dispatch:
        dispatch = dispatches.get(args.dispatch)
        if dispatch is None:
            raise SystemExit(f"FAIL: unknown dispatch {args.dispatch}")
    else:
        ordered_dispatches = sorted(dispatches.values(), key=lambda item: str(item.get("created_at", "")))
        if not ordered_dispatches:
            raise SystemExit("FAIL: no dispatch records found; run 'nogap run --execute' first")
        dispatch = ordered_dispatches[-1]
    dispatch_id = dispatch["id"]

    evidence = load_objects(root / "evidence")
    execution_evidence = [
        item for item in evidence.values()
        if item.get("kind") == "execution" and item.get("provenance", {}).get("dispatch_id") == dispatch_id
    ]
    if not execution_evidence:
        raise SystemExit(f"FAIL: no execution evidence found for dispatch {dispatch_id}; run 'nogap run --execute' first")
    execution = sorted(execution_evidence, key=lambda item: str(item.get("provenance", {}).get("created_at", "")))[-1]
    patch_path = Path(execution["provenance"]["artifact_path"])
    if not patch_path.is_file():
        raise SystemExit(f"FAIL: patch artifact missing: {patch_path}")
    patch = patch_path.read_text(encoding="utf-8")
    executor_provider = execution["provenance"].get("provider")
    executor_actor_id = execution["provenance"].get("actor_id")

    gates = load_objects(root / "gates")
    frozen_gates = [gate for gate in gates.values() if gate.get("status") == "frozen" and gate.get("hash") == gate_hash(gate)]
    if not frozen_gates:
        raise SystemExit("FAIL: no frozen gate to verify against; run 'nogap freeze' first")
    gate = frozen_gates[0]

    from nogap_verification import run_deterministic_layer, run_independent_review_layer

    project_root = Path(args.path).resolve()
    written: list[str] = []
    print(f"verifying dispatch {dispatch_id} (executed by {executor_provider or 'unknown'}) against gate {gate['id']}")

    # M7-G: methodology binding only engages when the CANDIDATE itself carries a
    # task_id (written into execution evidence provenance by M7-F) on a
    # methodology-tracked project - the same "smallest explicit compatibility policy"
    # M7-F used for `nogap run`: a legacy execution with no task binding gets exactly
    # the pre-M7-G behavior below, never a fabricated methodology wrapper.
    from nogap_methodology import MethodologyValidationError as _MethodologyValidationError
    from nogap_methodology import load_state as _load_state
    from nogap_methodology import transition as _transition

    task_id = execution["provenance"].get("task_id")
    state = _load_state(project_root)
    methodology_tracked = state is not None and task_id is not None

    task_contract = None
    requirement_refs: list[str] = []
    depth = None
    plan = None
    verification_result = None
    halted = False

    if methodology_tracked:
        import nogap_verify_binding as vb
        from nogap_artifacts import create_artifact, list_artifacts as _list_artifacts, update_verification_result

        if state["current_phase"] not in vb.VERIFY_ENTRY_PHASES:
            print(
                f"verification BLOCKED by methodology: current phase {state['current_phase']!r} does not "
                f"permit VERIFY entry (must be one of {vb.VERIFY_ENTRY_PHASES})"
            )
            print("verification_status=METHODOLOGY_BLOCKED")
            return

        try:
            task_contract = vb.load_task_contract(project_root, task_id)
            requirement_refs = list(task_contract["fields"].get("requirement_refs", []))
            self_check = vb.latest_self_check(project_root, task_id)
            if self_check is None:
                raise _MethodologyValidationError(f"no P14_SELF_CHECK recorded for task {task_id!r}")
            patch_hash_value = self_check["fields"]["patch_hash"]
            candidate_hash = vb.compute_candidate_hash(task_id, patch_hash_value)
            depth = vb.derive_verification_depth(project_root)

            existing_plans = [
                r for r in _list_artifacts(project_root, artifact_type="P15_VERIFICATION_PLAN")
                if r["fields"].get("task_id") == task_id and r.get("status") == "ACTIVE"
            ]
            plan = existing_plans[-1] if existing_plans else create_artifact(
                project_root, "P15_VERIFICATION_PLAN",
                {
                    "task_id": task_id, "requirement_refs": requirement_refs,
                    "profile": depth["profile"], "risk": state["risk"], "claim_strength": state["claim_strength"],
                    "required_levels": depth["required_levels"],
                    "required_validation_levels": depth["required_validation_levels"],
                    "required_evidence_kinds": (
                        ["deterministic"]
                        + (["reproducibility"] if depth["reproducibility_required"] else [])
                        + (["independent_review"] if depth["independent_review_required"] else [])
                    ),
                    "independent_review_required": depth["independent_review_required"],
                    "reproducibility_required": depth["reproducibility_required"],
                    "external_validation_required": depth["external_validation_required"],
                },
                actor=args.actor,
            )
            print(f"verification plan {plan['fields']['verification_plan_id']} (profile={depth['profile']})")

            self_check_evidence_id = self_check["fields"]["execution_evidence_ids"][0]
            if state["current_phase"] == "P14":
                _transition(
                    project_root, "P15", args.actor, "BUILD candidate awaiting verification; entering verification ladder",
                    artifact_refs=[plan["artifact_id"]], evidence_refs=[self_check_evidence_id], authority_class="tool",
                )
                state = _load_state(project_root)
            if state["current_phase"] == "P15":
                _transition(
                    project_root, "P16", args.actor, "verification plan selected; entering three-level validation",
                    artifact_refs=[plan["artifact_id"]], authority_class="tool",
                )
                state = _load_state(project_root)
        except _MethodologyValidationError as exc:
            raise SystemExit(f"FAIL: {exc}") from exc

    deterministic_statuses: list[str] = []
    for check in run_deterministic_layer(project_root, patch, gate, timeout=args.timeout):
        kind = "review" if check.check == "effect-scope" else "test"
        evidence_id, _ = write_isolated_run_evidence(
            root, run_id, check, args.actor, check.status, check.execution_status, check.reason,
            authority="verification", kind=kind, role="verifier", event_type="VERIFICATION_COMPLETED",
            dispatch_id=dispatch_id,
            task_id=task_id if methodology_tracked else None,
            requirement_refs=requirement_refs if methodology_tracked else None,
            methodology_version=state["methodology_version"] if methodology_tracked else None,
        )
        written.append(evidence_id)
        deterministic_statuses.append(check.status)
        print(f"  [deterministic] {check.check}: {check.status} ({check.execution_status}: {check.reason})")

    if methodology_tracked:
        deterministic_passed = all(s == "passed" for s in deterministic_statuses)
        deterministic_result = "passed" if deterministic_passed else "failed"
        levels_attempted = ["STATIC_CHECKS"] + (["UNIT_TESTS"] if gate.get("rules", {}).get("required_commands") else [])
        levels_passed = list(levels_attempted) if deterministic_passed else []
        result_status = "VERIFICATION_IN_PROGRESS" if deterministic_passed else "VERIFICATION_FAILED"

        existing_results = [
            r for r in _list_artifacts(project_root, artifact_type="P18_VERIFICATION_RESULT")
            if r["fields"].get("task_id") == task_id and r["fields"].get("candidate_hash") == candidate_hash
        ]
        if existing_results:
            verification_result = update_verification_result(
                project_root, existing_results[-1]["fields"]["verification_run_id"], args.actor,
                "deterministic layer re-run", status=result_status,
                field_updates={"levels_attempted": levels_attempted, "levels_passed": levels_passed, "deterministic_result": deterministic_result},
            )
        else:
            verification_result = create_artifact(
                project_root, "P18_VERIFICATION_RESULT",
                {
                    "verification_plan_id": plan["fields"]["verification_plan_id"], "task_id": task_id,
                    "candidate_hash": candidate_hash, "patch_hash": patch_hash_value, "gate_hash": gate.get("hash"),
                    "methodology_version_at_verification": state["methodology_version"],
                    "profile_at_verification": depth["profile"],
                    "task_snapshot_hash": vb.task_snapshot_hash_of(task_contract["fields"]),
                    "requirement_refs": requirement_refs,
                    "executor_actor_id": executor_actor_id, "levels_attempted": levels_attempted,
                    "levels_passed": levels_passed, "deterministic_result": deterministic_result,
                    "reproducibility_result": "PENDING", "independent_review_result": "PENDING",
                },
                actor=args.actor, status=result_status, evidence_refs=list(written),
            )
        print(f"verification result {verification_result['fields']['verification_run_id']}: deterministic={deterministic_result}")

        if not deterministic_passed:
            print("verification_status=DETERMINISTIC_VERIFICATION_FAILED")
            halted = True

    if methodology_tracked and not halted:
        _transition(
            project_root, "P17", args.actor, "deterministic verification passed; entering reproducibility",
            artifact_refs=[verification_result["artifact_id"]], evidence_refs=list(written), authority_class="tool",
        )
        state = _load_state(project_root)

        if depth["reproducibility_required"]:
            rerun_ids: list[str] = []
            rerun_statuses: list[str] = []
            for check in run_deterministic_layer(project_root, patch, gate, timeout=args.timeout):
                kind = "review" if check.check == "effect-scope" else "test"
                evidence_id, _ = write_isolated_run_evidence(
                    root, run_id, check, args.actor, check.status, check.execution_status, check.reason,
                    authority="verification", kind=kind, role="verifier", event_type="VERIFICATION_COMPLETED",
                    dispatch_id=dispatch_id, task_id=task_id, requirement_refs=requirement_refs,
                    methodology_version=state["methodology_version"],
                )
                rerun_ids.append(evidence_id)
                rerun_statuses.append(check.status)
                print(f"  [reproducibility re-run] {check.check}: {check.status} ({check.execution_status}: {check.reason})")
            written.extend(rerun_ids)
            rerun_consistent = all(s == "passed" for s in rerun_statuses)
            reproducibility_result, reproducibility_reason = vb.evaluate_reproducibility(rerun_consistent, depth["external_validation_required"])
            evidence_refs_p17 = rerun_ids
        else:
            reproducibility_result = "SKIPPED_PER_PROFILE_POLICY"
            reproducibility_reason = f"P17 is skippable at profile {depth['profile']}"
            evidence_refs_p17 = [_write_skip_evidence(root, run_id, args.actor, dispatch_id, "P17", reproducibility_reason, task_id, state["methodology_version"])]
        print(f"  [reproducibility] {reproducibility_result}: {reproducibility_reason}")

        verification_result = update_verification_result(
            project_root, verification_result["fields"]["verification_run_id"], args.actor, reproducibility_reason,
            field_updates={"reproducibility_result": reproducibility_result},
        )

        if reproducibility_result not in {"passed", "SKIPPED_PER_PROFILE_POLICY"}:
            label = "REPRODUCIBILITY_FAILED" if reproducibility_result == "failed" else "EXTERNAL_VALIDATION_UNAVAILABLE"
            final_status = "VERIFICATION_FAILED" if reproducibility_result == "failed" else "VERIFICATION_INCONCLUSIVE"
            verification_result = update_verification_result(
                project_root, verification_result["fields"]["verification_run_id"], args.actor, f"halted: {label}", status=final_status,
            )
            print(f"verification_status={label}")
            halted = True
        else:
            _transition(
                project_root, "P18", args.actor, "reproducibility satisfied; entering independent review",
                artifact_refs=[verification_result["artifact_id"]], evidence_refs=evidence_refs_p17, authority_class="tool",
            )
            state = _load_state(project_root)

    # Independent review (P18) runs whenever --review is requested, regardless of
    # whether independent_review_required at this profile (nothing stops doing MORE
    # rigor than required); if it is required but not performed, the candidate is
    # marked inconclusive, never silently passed.
    review_performed = False
    check_status = None
    if args.review:
        from nogap_adapters import ADAPTERS, ExecutorNotReady

        reviewer = None
        for adapter in ADAPTERS.values():
            if adapter.id == executor_provider or not hasattr(adapter, "build_exec_command"):
                continue
            if adapter.health().get("status") == "connected":
                reviewer = adapter
                break
        if reviewer is None:
            print("independent review skipped: no other ready AgentRuntime available to review this work")
        else:
            try:
                check = run_independent_review_layer(project_root, patch, objective, reviewer, timeout=args.review_timeout)
            except ExecutorNotReady as exc:
                print(f"independent review aborted: {exc}")
            else:
                reviewer_actor_id = f"agent:{reviewer.id}"
                if methodology_tracked and not vb.reviewer_is_independent(executor_actor_id, reviewer_actor_id):
                    check_status, check_execution_status, check_reason = "inconclusive", "REVIEW_NOT_INDEPENDENT", (
                        f"reviewer identity {reviewer_actor_id!r} is not independent from executor identity {executor_actor_id!r}"
                    )
                else:
                    check_status, check_execution_status, check_reason = check.status, check.execution_status, check.reason
                evidence_id, _ = write_isolated_run_evidence(
                    root, run_id, check, args.actor, check_status, check_execution_status, check_reason,
                    authority="verification", kind="review", role="verifier", event_type="VERIFICATION_COMPLETED",
                    dispatch_id=dispatch_id, provider=reviewer.id, runtime_id=reviewer.id,
                    task_id=task_id if methodology_tracked else None,
                    requirement_refs=requirement_refs if methodology_tracked else None,
                    methodology_version=state["methodology_version"] if methodology_tracked else None,
                )
                written.append(evidence_id)
                review_performed = True
                print(f"  [independent review by {reviewer.id}] {check_status} ({check_execution_status}: {check_reason})")

    if methodology_tracked and not halted:
        if review_performed:
            independent_review_result = check_status
            review_reason = "independent review recorded"
        elif depth["independent_review_required"]:
            independent_review_result = "inconclusive"
            review_reason = "independent review is required at this profile but was not performed (pass --review with a second ready AgentRuntime)"
        else:
            independent_review_result = "SKIPPED_PER_PROFILE_POLICY"
            review_reason = f"P18 is skippable at profile {depth['profile']}"

        verification_result = update_verification_result(
            project_root, verification_result["fields"]["verification_run_id"], args.actor, review_reason,
            field_updates={"independent_review_result": independent_review_result},
        )
        _finalize_verification(project_root, verification_result, gate, args.actor)

    print(f"verification complete: {len(written)} evidence record(s) written")
    print("verification evidence is not ACCEPT: only 'nogap decide' can accept, and only from independent authoritative evidence.")


def cmd_decide(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    run_id = read_json(root / "run.json")["id"]
    gates = load_objects(root / "gates")
    frozen_hashes = {
        gate_hash(gate)
        for gate in gates.values()
        if gate.get("run_id") == run_id and gate.get("status") == "frozen" and gate.get("hash") == gate_hash(gate)
    }
    evidence_by_id = load_objects(root / "evidence")
    evidence = list(evidence_by_id.values())
    claims = [read_json(path) for path in sorted((root / "claims").glob("*.json"))]
    passed = [item["id"] for item in evidence if item.get("status") == "passed"]
    failed = [item["id"] for item in evidence if item.get("status") == "failed"]
    unsupported = [
        claim["id"] for claim in claims
        if claim.get("status") == "supported"
        and (not claim.get("evidence") or any(eid not in passed for eid in claim.get("evidence", [])))
    ]

    decision_actor = args.actor_id or args.actor
    decision_authority = args.authority
    executors = execution_actor_ids(evidence_by_id)
    authoritative_passed = [
        item["id"] for item in evidence
        if is_authoritative_evidence(item, frozen_hashes)
        and evidence_actor(item) not in executors
    ]
    authoritative_conflicts = [
        item["id"] for item in evidence
        if evidence_authority(item) in AUTHORITATIVE_EVIDENCE_AUTHORITIES
        and item.get("status") in {"failed", "blocked", "inconclusive"}
    ]

    # Methodology verification interlock (post-M7-G, closing a live-discovered
    # false-pass path): a necessary, never sufficient, precondition for ACCEPT.
    # "Methodology verification isn't ready" can block ACCEPT below; "it is ready"
    # never by itself grants it - every other check in this function still applies.
    # Reuses nogap_verify_binding's own staleness/depth logic; nothing here
    # re-derives it. Only evaluated once there is authoritative evidence to
    # potentially accept, matching every other check's ordering in this function.
    methodology_block_reason: str | None = None
    if authoritative_passed:
        from nogap_methodology import load_state as _load_state
        from nogap_verify_binding import verification_acceptance_precondition

        project_root = Path(args.path)
        if _load_state(project_root) is not None:
            candidate_task_ids = {
                evidence_by_id[eid]["provenance"].get("task_id")
                for eid in authoritative_passed
                if evidence_by_id[eid].get("provenance", {}).get("task_id")
            }
            if len(candidate_task_ids) > 1:
                methodology_block_reason = f"authoritative evidence references multiple tasks {sorted(candidate_task_ids)}; cannot determine a single candidate to check"
            else:
                task_id = next(iter(candidate_task_ids), None)
                precondition = verification_acceptance_precondition(project_root, task_id)
                if not precondition["satisfied"]:
                    methodology_block_reason = precondition["reason"]

    if failed or unsupported:
        decision, reason, event_type = "repair", "failed evidence or unsupported supported-claim references require repair", "DECISION_REPAIR"
    elif decision_actor in executors:
        decision, reason, event_type = "repair", "executor identity cannot issue ACCEPT", "AUTHORITY_CONFLICT"
    elif decision_authority not in ACCEPTANCE_AUTHORITIES:
        decision, reason, event_type = "abstain", "acceptance authority is required for final ACCEPT", "ACCEPTANCE_BLOCKED"
    elif authoritative_conflicts:
        decision, reason, event_type = "repair", "contradictory authoritative evidence requires repair", "DECISION_REPAIR"
    elif not authoritative_passed:
        decision, reason, event_type = "abstain", "independent authoritative verification evidence is required for ACCEPT", "ACCEPTANCE_BLOCKED"
    elif not passed:
        decision, reason, event_type = "abstain", "no passing evidence is available", "DECISION_ABSTAIN"
    elif methodology_block_reason:
        decision, reason, event_type = "abstain", f"methodology verification precondition not satisfied: {methodology_block_reason}", "ACCEPTANCE_BLOCKED"
    else:
        decision, reason, event_type = "accept", "independent authoritative verification evidence passed and acceptance authority is separate from execution", "DECISION_ACCEPTED"

    output = {
        "id": "decision-0001",
        "run_id": run_id,
        "decision": decision,
        "reason": reason,
        "evidence": authoritative_passed if decision == "accept" else passed,
        "created_at": now(),
        "decided_by": args.actor,
        "actor_id": decision_actor,
        "authority": decision_authority
    }
    write_json(root / "decisions" / "decision-0001.json", output)
    append_event(root, {
        "id": "event-decision-0001",
        "run_id": run_id,
        "type": event_type,
        "created_at": output["created_at"],
        "actor": args.actor,
        "payload": {"decision": decision, "evidence": output["evidence"], "authority": decision_authority}
    })
    print(f"{decision}: {reason}")


def cmd_learn(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    run_id = read_json(root / "run.json")["id"]
    decision_path = root / "decisions" / args.decision
    decision = read_json(decision_path)
    tags = sorted(set(args.tag))
    if not tags:
        tags = [decision.get("decision", "unknown")]

    lesson_id = args.id or f"lesson-{stable_hash({'run_id': run_id, 'tags': tags, 'text': args.text})[:12]}"
    lesson = {
        "id": lesson_id,
        "run_id": run_id,
        "text": args.text,
        "applies_when": {
            "tags": tags,
            "decision": decision.get("decision"),
            "reason": decision.get("reason", "")
        },
        "evidence": decision.get("evidence", []),
        "source_decision": decision.get("id"),
        "created_at": now()
    }
    write_json(root / "lessons" / f"{lesson_id}.json", lesson)
    append_event(root, {
        "id": f"event-{lesson_id}",
        "run_id": run_id,
        "type": "LESSON_LEARNED",
        "created_at": lesson["created_at"],
        "actor": args.actor,
        "payload": {"lesson_id": lesson_id, "tags": tags}
    })
    print(f"learned {lesson_id}")


def cmd_goal(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    run_path = root / "run.json"
    run = read_json(run_path)
    if args.action == "show":
        print(json.dumps(run.get("learning_goal", {}), indent=2, sort_keys=True))
        return
    goal = {
        "objective": args.objective,
        "tags": sorted(set(args.tag)),
        "status": "active",
        "created_at": now(),
    }
    run["learning_goal"] = goal
    write_json(run_path, run)
    append_event(root, {
        "id": f"event-learning-goal-{stable_hash(goal)[:12]}",
        "run_id": run["id"],
        "type": "LEARNING_GOAL_SET",
        "created_at": goal["created_at"],
        "actor": args.actor,
        "payload": goal,
    })
    print(f"learning goal set: {args.objective}")


def cmd_literature(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    run_id = read_json(root / "run.json")["id"]
    ensure_runtime(root)
    if args.action == "add":
        for key in ("title", "url", "claim", "lesson", "test"):
            if not getattr(args, key):
                raise SystemExit(f"FAIL: literature add requires --{key.replace('_', '-')}")
        item_id = args.id or f"lit-{stable_hash({'source': args.url, 'claim': args.claim})[:12]}"
        item = {
            "id": item_id,
            "source": {
                "title": args.title,
                "url": args.url,
                "type": args.source_type,
                "retrieved_at": now(),
            },
            "claim": args.claim,
            "lesson": args.lesson,
            "applies_when": sorted(set(args.tag)),
            "benefit": sorted(set(args.benefit)),
            "cost": sorted(set(args.cost)),
            "evidence_strength": args.evidence_strength,
            "acceptance_evidence": sorted(set(args.acceptance_evidence)),
            "decision": "defer",
            "reason": "not evaluated",
            "can_be_tested_by": args.test,
            "meaning_quality": {
                "accurate": args.accurate,
                "concise": args.concise,
                "complete": args.complete,
            },
        }
        write_json(root / "literature" / f"{item_id}.json", item)
        append_event(root, {
            "id": f"event-{item_id}-added",
            "run_id": run_id,
            "type": "LITERATURE_CLAIM_ADDED",
            "created_at": item["source"]["retrieved_at"],
            "actor": args.actor,
            "payload": {"literature_id": item_id}
        })
        print(f"added literature claim {item_id}")
        return

    item_path = root / "literature" / f"{args.id}.json"
    item = read_json(item_path)
    if args.action == "evaluate":
        failures = literature_checks(item)
        if failures:
            item["decision"] = "reject"
            item["reason"] = "; ".join(failures)
        elif not item.get("acceptance_evidence"):
            item["decision"] = "defer"
            item["reason"] = "passed source, benefit, testability, and meaning-quality gates; awaiting acceptance_evidence"
        else:
            item["decision"] = "learn"
            item["reason"] = "passed source, benefit, testability, meaning-quality, and acceptance-evidence gates"
        item["evaluated_at"] = now()
        write_json(item_path, item)
        append_event(root, {
            "id": f"event-{args.id}-evaluated",
            "run_id": run_id,
            "type": "LITERATURE_CLAIM_EVALUATED",
            "created_at": item["evaluated_at"],
            "actor": args.actor,
            "payload": {"literature_id": args.id, "decision": item["decision"], "reason": item["reason"]}
        })
        print(f"{item['decision']}: {item['reason']}")
        return

    if item.get("decision") != "learn":
        raise SystemExit(f"FAIL: literature claim {args.id} is not approved for learning")
    lesson_id = learn_literature(root, run_id, args.id, item, args.actor)
    print(f"learned {lesson_id} from {args.id}")


def cmd_autolearn(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    run = read_json(root / "run.json")
    goal = run.get("learning_goal")
    if not isinstance(goal, dict) or goal.get("status") != "active":
        raise SystemExit("FAIL: set an active learning goal first")
    learned: list[str] = []
    rejected: list[str] = []
    deferred: list[str] = []
    for path in sorted((root / "literature").glob("*.json")):
        item = read_json(path)
        item_id = require_string(item, "id", path)
        if item.get("decision") == "learn" and args.include_learned:
            learned.append(learn_literature(root, run["id"], item_id, item, args.actor))
            continue
        if item.get("decision") != "defer":
            continue
        if not literature_goal_matches(item, goal):
            item["reason"] = "deferred: not relevant to current learning goal"
            item["evaluated_at"] = now()
            write_json(path, item)
            deferred.append(item_id)
            continue
        failures = literature_checks(item)
        if failures:
            item["decision"] = "reject"
            item["reason"] = "; ".join(failures)
        elif not item.get("acceptance_evidence"):
            item["decision"] = "defer"
            item["reason"] = "deferred: awaiting acceptance_evidence"
            item["evaluated_at"] = now()
            write_json(path, item)
            deferred.append(item_id)
            continue
        else:
            item["decision"] = "learn"
            item["reason"] = "auto-learned for active goal after all gates passed"
        item["evaluated_at"] = now()
        write_json(path, item)
        if failures:
            rejected.append(item_id)
        else:
            learned.append(learn_literature(root, run["id"], item_id, item, args.actor))
    append_event(root, {
        "id": f"event-autolearn-{stable_hash({'learned': learned, 'rejected': rejected, 'deferred': deferred})[:12]}",
        "run_id": run["id"],
        "type": "AUTOLEARN_RUN",
        "created_at": now(),
        "actor": args.actor,
        "payload": {"goal": goal, "learned": learned, "rejected": rejected, "deferred": deferred},
    })
    print(f"autolearn: learned={len(learned)} rejected={len(rejected)} deferred={len(deferred)}")


def cmd_recall(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    wanted = set(args.tag)
    lessons = [read_json(path) for path in sorted((root / "lessons").glob("*.json"))]
    matches = []
    for lesson in lessons:
        tags = set(lesson.get("applies_when", {}).get("tags", []))
        if not wanted or wanted & tags:
            matches.append(lesson)
    if not matches:
        print("no matching lessons")
        return
    for lesson in matches:
        tags = ",".join(lesson.get("applies_when", {}).get("tags", []))
        print(f"{lesson['id']} [{tags}]: {lesson['text']}")


def cmd_context(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    run = read_json(root / "run.json")
    gates = load_objects(root / "gates")
    evidence = load_objects(root / "evidence")
    decisions = load_objects(root / "decisions")
    lessons = load_objects(root / "lessons")

    tags = sorted({
        tag
        for lesson in lessons.values()
        for tag in lesson.get("applies_when", {}).get("tags", [])
    })
    profile = {
        "run_id": run["id"],
        "updated_at": now(),
        "objective": run.get("objective", ""),
        "learning_goal": run.get("learning_goal", {}),
        "gate_statuses": sorted({gate.get("status", "unknown") for gate in gates.values()}),
        "evidence_statuses": sorted({item.get("status", "unknown") for item in evidence.values()}),
        "decisions": sorted({item.get("decision", "unknown") for item in decisions.values()}),
        "lesson_tags": tags,
        "risk_signals": sorted({
            signal
            for signal in [
                "frozen-gate" if any(gate.get("status") == "frozen" for gate in gates.values()) else "",
                "failed-evidence" if any(item.get("status") == "failed" for item in evidence.values()) else "",
                "repair-decision" if any(item.get("decision") == "repair" for item in decisions.values()) else "",
                "learned-context" if lessons else "",
                "active-learning-goal" if run.get("learning_goal", {}).get("status") == "active" else "",
            ]
            if signal
        }),
    }
    write_json(root / "context.json", profile)
    if args.show:
        print(json.dumps(profile, indent=2, sort_keys=True))
    else:
        print(f"updated context: {root / 'context.json'}")


def cmd_dashboard(args: argparse.Namespace) -> None:
    from nogap_dashboard import serve

    serve(Path(args.path), args.host, args.port)


def cmd_methodology(args: argparse.Namespace) -> None:
    """Thin CLI dispatcher only: all methodology logic lives in nogap_methodology.py / nogap_artifacts.py."""
    from nogap_methodology import (
        MethodologyValidationError,
        active_loops,
        can_transition,
        downgrade_profile,
        escalate_phase,
        evaluate_phase_status,
        init_project,
        methodology_compliance_summary,
    )
    from nogap_methodology import list_principle_enforcement
    from nogap_methodology import status as methodology_status
    from nogap_methodology import transition as do_transition

    if args.action in {"artifact-create", "artifact-list", "artifact-show", "readiness"}:
        return _cmd_methodology_artifacts(args)

    project = Path(args.path)
    try:
        if args.action == "principles":
            # Read-only, and deliberately project-independent: this reports enforcement
            # CAPABILITY (what NoGapCode can enforce today), never a specific project's
            # compliance - `path` is accepted for CLI consistency but unused here.
            summary = methodology_compliance_summary()
            print(f"{summary['total']} principles: enforced={summary['enforced']} partial={summary['partial']} "
                  f"declared={summary['declared']} advisory={summary['advisory']} deferred={summary['deferred']}")
            for record in list_principle_enforcement():
                print(f"  {record.principle_id} [{record.classification}] {record.status:9} owner={record.owner_component} - {record.mechanism}")
            return
        if args.action == "init":
            if not (args.intent and args.risk and args.claim_strength):
                raise SystemExit("FAIL: methodology init requires --intent, --risk, and --claim-strength")
            state = init_project(project, args.intent, args.risk, args.claim_strength, args.actor, force=args.force)
            print(f"methodology initialized: derived_profile={state['derived_profile']} effective_profile={state['effective_profile']}")
            print(f"derivation: {state['derivation']['reason']}")
            return
        if args.action == "status":
            result = methodology_status(project)
            if not result["initialized"]:
                print(f"NOT INITIALIZED: {result['path']}")
                return
            print(f"methodology: {result['methodology_id']} v{result['methodology_version']}")
            print(f"intent={result['intent']} risk={result['risk']} claim_strength={result['claim_strength']}")
            print(f"derived_profile={result['derived_profile']} effective_profile={result['effective_profile']}")
            if result["phase_profile_overrides"]:
                print(f"phase overrides: {result['phase_profile_overrides']}")
            if result["downgrade_log"]:
                print(f"downgrade history: {len(result['downgrade_log'])} entry(ies) - most recent: {result['downgrade_log'][-1]}")
            current = result["current_phase"]
            print(f"current_phase={current} status={evaluate_phase_status(project)}")
            active = active_loops(project)
            if active:
                print(f"active loop: {active[0]['loop_type']} (origin={active[0]['origin_phase']}, since {active[0]['entered_at']})")
            if result["transition_history"]:
                last = result["transition_history"][-1]
                print(f"last transition: {last['from_phase']} -> {last['to_phase']} ({last['transition_type']}) at {last['timestamp']}")
            return
        if args.action == "can-transition":
            if not args.phase:
                raise SystemExit("FAIL: methodology can-transition requires --phase as the target")
            result = can_transition(project, args.phase)
            print(f"can_transition({args.phase}): allowed={result['allowed']} transition_type={result['transition_type']}")
            for reason in result["blocked_reasons"]:
                print(f"  blocked: {reason}")
            return
        if args.action == "transition":
            if not (args.phase and args.reason):
                raise SystemExit("FAIL: methodology transition requires --phase (target) and --reason")
            evidence_refs = args.evidence_ref or []
            artifact_refs = args.artifact_ref or []
            state = do_transition(
                project, args.phase, args.actor, args.reason,
                evidence_refs=evidence_refs, artifact_refs=artifact_refs,
                authority_class=args.authority or "human",
            )
            last = state["transition_history"][-1]
            print(f"transitioned: {last['from_phase']} -> {last['to_phase']} ({last['transition_type']})")
            print(f"current_phase={state['current_phase']}")
            return
        if args.action == "escalate":
            if not (args.phase and args.profile):
                raise SystemExit("FAIL: methodology escalate requires --phase and --profile")
            escalate_phase(project, args.phase, args.profile, args.actor)
            print(f"escalated {args.phase} to {args.profile}")
            return
        if args.action == "downgrade":
            if not (args.profile and args.reason):
                raise SystemExit("FAIL: methodology downgrade requires --profile and --reason")
            downgrade_profile(project, args.profile, args.actor, args.reason)
            print(f"downgraded effective profile to {args.profile} (recorded: actor={args.actor}, reason={args.reason!r})")
            return
    except MethodologyValidationError as exc:
        raise SystemExit(f"FAIL: {exc}") from exc


def _cmd_methodology_artifacts(args: argparse.Namespace) -> None:
    """Thin dispatcher for the M7-E artifact actions; logic lives in nogap_artifacts.py."""
    from nogap_methodology import MethodologyValidationError
    from nogap_artifacts import (
        ARTIFACT_TYPES,
        create_artifact,
        list_artifacts,
        load_artifact,
        prebuild_readiness,
    )

    project = Path(args.path)
    try:
        if args.action == "artifact-create":
            if not (args.type and args.fields_json):
                raise SystemExit("FAIL: artifact-create requires --type and --fields-json")
            if args.type not in ARTIFACT_TYPES:
                raise SystemExit(f"FAIL: unknown artifact type {args.type!r}; choices: {sorted(ARTIFACT_TYPES)}")
            try:
                fields = json.loads(args.fields_json)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"FAIL: --fields-json is not valid JSON: {exc}") from exc
            record = create_artifact(
                project, args.type, fields, args.actor,
                source_refs=args.source_ref or [], decision_refs=args.decision_ref or [],
                evidence_refs=args.evidence_ref or [], assumptions=args.assumption or [],
                limitations=args.limitation or [],
            )
            print(f"created {record['artifact_type']} {record['artifact_id']} (phase {record['phase_id']})")
            if record["artifact_type"] == "P6_REQUIREMENT":
                print(f"requirement_id={record['fields']['requirement_id']}")
            return
        if args.action == "artifact-list":
            records = list_artifacts(project, artifact_type=args.type, phase_id=args.phase)
            print(f"{len(records)} artifact(s)")
            for record in records:
                print(f"  {record['artifact_id']} [{record['artifact_type']}] phase={record['phase_id']} status={record['status']}")
            return
        if args.action == "artifact-show":
            if not args.artifact_id:
                raise SystemExit("FAIL: artifact-show requires --artifact-id")
            record = load_artifact(project, args.artifact_id)
            if record is None:
                raise SystemExit(f"FAIL: unknown artifact_id {args.artifact_id!r}")
            print(json.dumps(record, indent=2, sort_keys=True))
            return
        if args.action == "readiness":
            result = prebuild_readiness(project)
            print(f"Current phase: {result['current_phase']}")
            print(f"Profile: {result['profile']}")
            if result["ready"]:
                print("PREBUILD_READY: true")
            else:
                print("PREBUILD_READY: false")
                print("Missing:")
                for reason in result["missing"]:
                    print(f"  - {reason}")
            # M7-F: minimal BUILD visibility - active task contract(s), the requirements
            # they link to, and whether a self-checked candidate is awaiting verification.
            if result["current_phase"] in {"P12", "P13", "P14"}:
                contracts = [
                    r for r in list_artifacts(project, artifact_type="P12_TASK_CONTRACT")
                    if r.get("status") == "ACTIVE"
                ]
                print(f"Active task contracts: {len(contracts)}")
                for contract in contracts:
                    print(
                        f"  {contract['fields']['task_id']} "
                        f"requirement_refs={contract['fields'].get('requirement_refs', [])}"
                    )
                self_checks = list_artifacts(project, artifact_type="P14_SELF_CHECK")
                if result["current_phase"] == "P14" and self_checks:
                    latest = max(self_checks, key=lambda r: r.get("created_at", ""))
                    print(
                        f"BUILD_COMPLETE_AWAITING_VERIFICATION: task_id={latest['fields']['task_id']} "
                        f"execution_evidence_ids={latest['fields']['execution_evidence_ids']}"
                    )
            return
    except MethodologyValidationError as exc:
        raise SystemExit(f"FAIL: {exc}") from exc


def cmd_failure(args: argparse.Namespace) -> None:
    """Thin CLI dispatcher only: every action calls straight into nogap_failure.py's
    engine API - no CLI shortcut here bypasses a state transition or re-derives logic
    that module already owns."""
    import nogap_failure as nf
    from nogap_methodology import MethodologyValidationError as _MethodologyValidationError

    project = Path(args.path)
    fields = json.loads(args.fields_json) if args.fields_json else {}

    def _print_failure(record: dict) -> None:
        print(f"{record['failure_id']}: {record['current_state']} (root_cause_class={record.get('root_cause_class')})")

    try:
        if args.action == "create":
            if not (args.failure_class and args.summary):
                raise SystemExit("FAIL: failure create requires --failure-class and --summary")
            record = nf.create_failure(
                project, failure_class=args.failure_class, summary=args.summary, actor=args.actor,
                origin_phase=args.origin_phase, task_id=args.task_id,
                evidence_refs=args.evidence_ref or [], artifact_refs=args.artifact_ref or [],
            )
            _print_failure(record)
            return

        if args.action == "list":
            records = nf.list_failures(project, state=args.state)
            print(f"{len(records)} failure(s)")
            for record in records:
                print(f"  {record['failure_id']} [{record['current_state']}] task_id={record.get('task_id')} class={record.get('failure_class')}")
            return

        if args.action == "status":
            if not args.failure_id:
                raise SystemExit("FAIL: failure status requires --failure-id")
            record = nf.load_failure(project, args.failure_id)
            if record is None:
                raise SystemExit(f"FAIL: unknown failure_id {args.failure_id!r}")
            print(json.dumps(record, indent=2, sort_keys=True))
            return

        if not args.failure_id:
            raise SystemExit(f"FAIL: failure {args.action} requires --failure-id")
        if not args.reason:
            raise SystemExit(f"FAIL: failure {args.action} requires --reason")

        if args.action == "preserve-evidence":
            record = nf.record_evidence_preservation(
                project, args.failure_id, evidence_refs=args.evidence_ref or [], artifact_refs=args.artifact_ref or [],
                actor=args.actor, reason=args.reason,
            )
        elif args.action == "reproduce":
            if not args.reproduction_status:
                raise SystemExit("FAIL: failure reproduce requires --reproduction-status")
            record = nf.record_reproduction(
                project, args.failure_id, reproduction_status=args.reproduction_status, actor=args.actor,
                reason=args.reason, environment=args.environment, reproduction_evidence_refs=args.evidence_ref or [],
            )
        elif args.action == "characterize":
            record = nf.record_characterization(
                project, args.failure_id, actor=args.actor, reason=args.reason,
                affected_requirement_refs=fields.get("affected_requirement_refs", []),
                affected_gate_refs=fields.get("affected_gate_refs", []), scope=fields.get("scope"),
                expected=fields.get("expected"), observed=fields.get("observed"), frequency=fields.get("frequency"),
                deterministic=fields.get("deterministic"), blast_radius=fields.get("blast_radius"),
            )
        elif args.action == "research":
            policy_exception = json.loads(args.policy_exception_json) if args.policy_exception_json else None
            record = nf.record_research(
                project, args.failure_id, actor=args.actor, reason=args.reason,
                research_refs=args.evidence_ref or [], policy_exception=policy_exception,
            )
        elif args.action == "root-cause":
            if not (args.root_cause_class and args.root_cause_summary):
                raise SystemExit("FAIL: failure root-cause requires --root-cause-class and --root-cause-summary")
            record = nf.record_root_cause(
                project, args.failure_id, root_cause_class=args.root_cause_class,
                root_cause_summary=args.root_cause_summary, supporting_evidence_refs=args.evidence_ref or [],
                actor=args.actor, reason=args.reason,
            )
        elif args.action == "propose-repair":
            if not (args.description and args.target_phase):
                raise SystemExit("FAIL: failure propose-repair requires --description and --target-phase")
            record = nf.propose_repair(
                project, args.failure_id, description=args.description, target_phase=args.target_phase,
                actor=args.actor, reason=args.reason, expected_effect=fields.get("expected_effect"),
                risk=fields.get("risk"), cost=fields.get("cost"),
                affected_requirements=fields.get("affected_requirements", []),
                evidence_refs=args.evidence_ref or [], repair_id=args.repair_id,
            )
        elif args.action == "select-repair":
            if not args.repair_id:
                raise SystemExit("FAIL: failure select-repair requires --repair-id")
            record = nf.select_repair(
                project, args.failure_id, args.repair_id, actor=args.actor, reason=args.reason, authority=args.authority,
            )
        elif args.action == "repaired":
            record = nf.record_repaired(
                project, args.failure_id, repair_evidence_refs=args.evidence_ref or [], actor=args.actor, reason=args.reason,
            )
        elif args.action == "regression":
            if not args.result:
                raise SystemExit("FAIL: failure regression requires --result")
            record = nf.record_regression(
                project, args.failure_id, result=args.result, actor=args.actor, reason=args.reason,
                tests_executed=fields.get("tests_executed", []), gate_ids=fields.get("gate_ids", []),
                requirements_affected=fields.get("requirements_affected", []), evidence_refs=args.evidence_ref or [],
            )
        elif args.action == "revalidate":
            record = nf.record_revalidation(project, args.failure_id, actor=args.actor, reason=args.reason)
        elif args.action == "resolve":
            record = nf.resolve_failure(project, args.failure_id, actor=args.actor, reason=args.reason)
        elif args.action == "inconclusive":
            record = nf.mark_inconclusive(project, args.failure_id, actor=args.actor, reason=args.reason)
        elif args.action == "close":
            if not args.close_status:
                raise SystemExit("FAIL: failure close requires --close-status")
            record = nf.close_failure(project, args.failure_id, status=args.close_status, actor=args.actor, reason=args.reason)
        else:
            raise SystemExit(f"FAIL: unknown failure action {args.action!r}")
    except _MethodologyValidationError as exc:
        raise SystemExit(f"FAIL: {exc}") from exc

    _print_failure(record)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("target", nargs="?", default=".")
    init.add_argument("--run-id", default="run-0001")
    init.add_argument("--objective", default="Replace this with the concrete runtime objective.")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    freeze = sub.add_parser("freeze")
    freeze.add_argument("path", nargs="?", default=".")
    freeze.add_argument("--gate", default="gate-0001.json")
    freeze.add_argument("--actor", default="nogap freeze")
    freeze.set_defaults(func=cmd_freeze)

    validate = sub.add_parser("validate")
    validate.add_argument("path", nargs="?", default=".")
    validate.set_defaults(func=cmd_validate)

    status = sub.add_parser("status")
    status.add_argument("path", nargs="?", default=".")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("path", nargs="?", default=".")
    run_cmd.add_argument("--actor", default="nogap orchestrator")
    run_cmd.add_argument(
        "--execute",
        action="store_true",
        help="After an intended dispatch, actually run the selected AgentRuntime inside an isolated worktree",
    )
    run_cmd.add_argument("--execute-timeout", type=int, default=600)
    run_cmd.add_argument(
        "--task-id",
        help="P12_TASK_CONTRACT task_id to bind this execution to; required for --execute "
        "once methodology is initialized and BUILD is permitted",
    )
    run_cmd.set_defaults(func=cmd_run)

    verify = sub.add_parser("verify")
    verify.add_argument("path", nargs="?", default=".")
    verify.add_argument("--dispatch", help="dispatch id to verify (default: most recent)")
    verify.add_argument("--timeout", type=int, default=300, help="per deterministic command timeout")
    verify.add_argument("--review", action="store_true", help="also dispatch an independent AgentRuntime to review the patch")
    verify.add_argument("--review-timeout", type=int, default=300)
    verify.add_argument("--actor", default="nogap verify")
    verify.set_defaults(func=cmd_verify)

    execute = sub.add_parser(
        "execute",
        description="Run one command inside an isolated git worktree. "
        "Pass the command after a literal '--', e.g. 'nogap execute . -- python -m pytest'.",
    )
    execute.add_argument("path", nargs="?", default=".")
    execute.add_argument("--timeout", type=int, default=300)
    execute.add_argument("--actor", default="nogap execute")
    execute.set_defaults(func=cmd_execute, worktree_command=[])

    decide = sub.add_parser("decide")
    decide.add_argument("path", nargs="?", default=".")
    decide.add_argument("--actor", default="nogap decide")
    decide.add_argument("--actor-id")
    decide.add_argument("--authority", choices=sorted(ACCEPTANCE_AUTHORITIES), default="acceptance")
    decide.set_defaults(func=cmd_decide)

    learn = sub.add_parser("learn")
    learn.add_argument("path", nargs="?", default=".")
    learn.add_argument("--decision", default="decision-0001.json")
    learn.add_argument("--text", required=True)
    learn.add_argument("--tag", action="append", default=[])
    learn.add_argument("--id")
    learn.add_argument("--actor", default="nogap learn")
    learn.set_defaults(func=cmd_learn)

    goal = sub.add_parser("goal")
    goal.add_argument("action", choices=["set", "show"])
    goal.add_argument("path", nargs="?", default=".")
    goal.add_argument("--objective", required=False)
    goal.add_argument("--tag", action="append", default=[])
    goal.add_argument("--actor", default="nogap goal")
    goal.set_defaults(func=cmd_goal)

    recall = sub.add_parser("recall")
    recall.add_argument("path", nargs="?", default=".")
    recall.add_argument("--tag", action="append", default=[])
    recall.set_defaults(func=cmd_recall)

    context = sub.add_parser("context")
    context.add_argument("path", nargs="?", default=".")
    context.add_argument("--show", action="store_true")
    context.set_defaults(func=cmd_context)

    literature = sub.add_parser("literature")
    literature.add_argument("action", choices=["add", "evaluate", "learn"])
    literature.add_argument("path", nargs="?", default=".")
    literature.add_argument("--id")
    literature.add_argument("--title")
    literature.add_argument("--url")
    literature.add_argument("--source-type", choices=sorted(LITERATURE_SOURCE_TYPES), default="official-doc")
    literature.add_argument("--claim")
    literature.add_argument("--lesson")
    literature.add_argument("--tag", action="append", default=[])
    literature.add_argument("--benefit", action="append", choices=sorted(LITERATURE_BENEFITS), default=[])
    literature.add_argument("--cost", action="append", choices=sorted(LITERATURE_COSTS), default=[])
    literature.add_argument("--evidence-strength", choices=["primary", "secondary", "weak"], default="primary")
    literature.add_argument("--acceptance-evidence", action="append", default=[])
    literature.add_argument("--test")
    literature.add_argument("--accurate", action="store_true")
    literature.add_argument("--concise", action="store_true")
    literature.add_argument("--complete", action="store_true")
    literature.add_argument("--actor", default="nogap literature")
    literature.set_defaults(func=cmd_literature)

    autolearn = sub.add_parser("autolearn")
    autolearn.add_argument("path", nargs="?", default=".")
    autolearn.add_argument("--include-learned", action="store_true")
    autolearn.add_argument("--actor", default="nogap autolearn")
    autolearn.set_defaults(func=cmd_autolearn)

    dashboard = sub.add_parser("dashboard")
    dashboard.add_argument("path", nargs="?", default=".")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.set_defaults(func=cmd_dashboard)

    methodology = sub.add_parser("methodology")
    methodology.add_argument("action", choices=[
        "init", "status", "principles", "can-transition", "transition", "escalate", "downgrade",
        "artifact-create", "artifact-list", "artifact-show", "readiness",
    ])
    methodology.add_argument("path", nargs="?", default=".")
    methodology.add_argument("--intent", choices=["research", "production", "experimental"])
    methodology.add_argument("--risk", choices=["low", "medium", "high"])
    methodology.add_argument("--claim-strength", dest="claim_strength", choices=["low", "medium", "high"])
    methodology.add_argument("--force", action="store_true")
    methodology.add_argument("--phase", help="P-id, REPAIR_LOOP, or macro phase (e.g. VERIFY) - transition target, phase to escalate, or artifact-list filter")
    methodology.add_argument("--profile", choices=["LIGHT", "STANDARD", "STRICT"])
    methodology.add_argument("--reason", help="required for transition/downgrade")
    methodology.add_argument("--actor", default="nogap methodology")
    methodology.add_argument("--evidence-ref", action="append", help="repeatable; evidence id(s) supporting a transition or artifact")
    methodology.add_argument("--artifact-ref", action="append", help="repeatable; artifact id(s) supporting a transition")
    methodology.add_argument("--authority", choices=["execution", "verification", "acceptance", "human", "tool"])
    methodology.add_argument("--type", dest="type", help="artifact type, e.g. P0_PROJECT_INTENT (artifact-create/artifact-list)")
    methodology.add_argument("--fields-json", help="artifact-create: a JSON object with the artifact type's fields")
    methodology.add_argument("--artifact-id", help="artifact-show: which artifact to print")
    methodology.add_argument("--source-ref", action="append", help="repeatable; artifact-create source_refs")
    methodology.add_argument("--decision-ref", action="append", help="repeatable; artifact-create decision_refs")
    methodology.add_argument("--assumption", action="append", help="repeatable; artifact-create assumptions")
    methodology.add_argument("--limitation", action="append", help="repeatable; artifact-create limitations")
    methodology.set_defaults(func=cmd_methodology)

    failure = sub.add_parser("failure")
    failure.add_argument("action", choices=[
        "create", "status", "list", "preserve-evidence", "reproduce", "characterize",
        "research", "root-cause", "propose-repair", "select-repair", "repaired",
        "regression", "revalidate", "resolve", "inconclusive", "close",
    ])
    failure.add_argument("path", nargs="?", default=".")
    failure.add_argument("--failure-id", help="target failure for every action except create/list")
    failure.add_argument("--actor", default="nogap failure")
    failure.add_argument("--reason", help="required for most state-changing actions")
    failure.add_argument("--failure-class", help="create: surface-level failure classification (free text)")
    failure.add_argument("--summary", help="create: what failed")
    failure.add_argument("--task-id", help="create: associated P12_TASK_CONTRACT task_id")
    failure.add_argument("--origin-phase", help="create: defaults to the project's current methodology phase")
    failure.add_argument("--evidence-ref", action="append", help="repeatable; evidence and/or methodology-artifact reference(s)")
    failure.add_argument("--artifact-ref", action="append", help="repeatable; methodology-artifact reference(s)")
    failure.add_argument("--reproduction-status", choices=sorted({"REPRODUCED", "NOT_REPRODUCED", "INTERMITTENT", "INCONCLUSIVE"}))
    failure.add_argument("--environment", help="reproduce: environment description")
    failure.add_argument("--root-cause-class", choices=sorted({
        "IMPLEMENTATION_DEFECT", "REQUIREMENT_DEFECT", "ARCHITECTURE_DEFECT", "PRIOR_ART_INVALIDATION",
        "TEST_OR_GATE_DEFECT", "ENVIRONMENT_DEFECT", "DATA_DEFECT", "DEPENDENCY_DEFECT", "UNKNOWN",
    }))
    failure.add_argument("--root-cause-summary")
    failure.add_argument("--repair-id", help="select-repair: which proposed candidate; propose-repair: optional explicit id")
    failure.add_argument("--target-phase", help="propose-repair: destination phase for this candidate")
    failure.add_argument("--description", help="propose-repair: what the candidate repair does")
    failure.add_argument("--authority", default="human", help="select-repair: authority class recorded for the selection")
    failure.add_argument("--result", choices=["passed", "failed"], help="regression: outcome")
    failure.add_argument("--policy-exception-json", help="research: JSON {reason, actor_id, authority} - LIGHT profile only")
    failure.add_argument("--fields-json", help="per-action extra structured fields (characterization details, repair proposal extras)")
    failure.add_argument("--state", help="list: filter by current_state")
    failure.add_argument("--close-status", choices=["REJECTED", "ABANDONED"], help="close: which negative terminal outcome")
    failure.set_defaults(func=cmd_failure)

    argv = sys.argv[1:]
    worktree_command: list[str] = []
    if argv and argv[0] == "execute" and "--" in argv:
        # argparse.REMAINDER is ambiguous when mixed with named options like --timeout, and its
        # dest would collide with the subparsers' own dest="command". Split the passthrough
        # command out by hand instead of asking argparse to parse it at all.
        separator = argv.index("--")
        worktree_command = argv[separator + 1:]
        argv = argv[:separator]

    args = parser.parse_args(argv)
    if args.command == "execute":
        args.worktree_command = worktree_command
    if args.command == "goal" and args.action == "set" and not args.objective:
        raise SystemExit("FAIL: goal set requires --objective")
    args.func(args)


if __name__ == "__main__":
    main()
