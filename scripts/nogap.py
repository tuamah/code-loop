#!/usr/bin/env python3
"""Minimal NoGapCode runtime CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNTIME_DIRS = ["gates", "claims", "evidence", "events", "decisions", "lessons", "artifacts"]
EVIDENCE_STATUS = {"passed", "failed", "blocked", "inconclusive"}
CLAIM_STATUS = {"unverified", "supported", "contradicted", "superseded"}
DECISIONS = {"accept", "repair", "rerun", "ask-human", "reject", "abstain"}


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

    recall = sub.add_parser("recall")
    recall.add_argument("path", nargs="?", default=".")
    recall.add_argument("--tag", action="append", default=[])
    recall.set_defaults(func=cmd_recall)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
