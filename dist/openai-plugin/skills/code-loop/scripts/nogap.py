#!/usr/bin/env python3
"""Minimal NoGapCode runtime CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNTIME_DIRS = ["gates", "claims", "evidence", "events", "decisions", "lessons", "artifacts", "literature"]
EVIDENCE_STATUS = {"passed", "failed", "blocked", "inconclusive"}
CLAIM_STATUS = {"unverified", "supported", "contradicted", "superseded"}
DECISIONS = {"accept", "repair", "rerun", "ask-human", "reject", "abstain"}
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


def ensure_runtime(root: Path) -> None:
    for name in RUNTIME_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)


def require_string(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"FAIL: {path} missing non-empty string: {key}")
    return value


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
    decision = {
        "id": decision_id,
        "run_id": run_id,
        "decision": "accept",
        "reason": f"literature claim {item_id}: {item.get('reason', '')}",
        "evidence": [],
        "created_at": now(),
        "decided_by": actor,
    }
    lesson = {
        "id": lesson_id,
        "run_id": run_id,
        "text": item["lesson"],
        "applies_when": {
            "tags": tags,
            "decision": "accept",
            "reason": decision["reason"],
        },
        "evidence": [],
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
        gate_ref = provenance.get("gate_hash")
        if gate_ref and gate_ref not in frozen_hashes:
            raise SystemExit(f"FAIL: evidence {evidence_id} references unknown gate_hash")
        for claim_id in item.get("claim_ids", []):
            if claim_id not in claims:
                raise SystemExit(f"FAIL: evidence {evidence_id} references missing claim {claim_id}")

    for decision_id, decision in decisions.items():
        if decision.get("decision") not in DECISIONS:
            raise SystemExit(f"FAIL: decision {decision_id} has invalid decision")
        for evidence_id in decision.get("evidence", []):
            if evidence_id not in evidence:
                raise SystemExit(f"FAIL: decision {decision_id} references missing evidence {evidence_id}")
            if decision["decision"] == "accept" and evidence[evidence_id].get("status") != "passed":
                raise SystemExit(f"FAIL: decision {decision_id} accepts non-passing evidence {evidence_id}")

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


def cmd_decide(args: argparse.Namespace) -> None:
    root = runtime_root(Path(args.path))
    run_id = read_json(root / "run.json")["id"]
    evidence = [read_json(path) for path in sorted((root / "evidence").glob("*.json"))]
    claims = [read_json(path) for path in sorted((root / "claims").glob("*.json"))]
    passed = [item["id"] for item in evidence if item.get("status") == "passed"]
    failed = [item["id"] for item in evidence if item.get("status") == "failed"]
    unsupported = [
        claim["id"] for claim in claims
        if claim.get("status") == "supported"
        and (not claim.get("evidence") or any(eid not in passed for eid in claim.get("evidence", [])))
    ]

    if failed or unsupported:
        decision, reason, event_type = "repair", "failed evidence or unsupported supported-claim references require repair", "DECISION_REPAIR"
    elif not passed:
        decision, reason, event_type = "abstain", "no passing evidence is available", "DECISION_ABSTAIN"
    else:
        decision, reason, event_type = "accept", "all referenced evidence for the current decision passed", "DECISION_ACCEPTED"

    output = {
        "id": "decision-0001",
        "run_id": run_id,
        "decision": decision,
        "reason": reason,
        "evidence": passed,
        "created_at": now(),
        "decided_by": args.actor
    }
    write_json(root / "decisions" / "decision-0001.json", output)
    append_event(root, {
        "id": "event-decision-0001",
        "run_id": run_id,
        "type": event_type,
        "created_at": output["created_at"],
        "actor": args.actor,
        "payload": {"decision": decision, "evidence": passed}
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
        item["decision"] = "reject" if failures else "learn"
        item["reason"] = "; ".join(failures) if failures else "passed source, benefit, testability, and meaning-quality gates"
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
        item["decision"] = "reject" if failures else "learn"
        item["reason"] = "; ".join(failures) if failures else "auto-learned for active goal after all gates passed"
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

    decide = sub.add_parser("decide")
    decide.add_argument("path", nargs="?", default=".")
    decide.add_argument("--actor", default="nogap decide")
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

    args = parser.parse_args()
    if args.command == "goal" and args.action == "set" and not args.objective:
        raise SystemExit("FAIL: goal set requires --objective")
    args.func(args)


if __name__ == "__main__":
    main()
