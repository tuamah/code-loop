#!/usr/bin/env python3
"""NoGapBench: minimal false-success traps for NoGapCode."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_nogap(project: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/nogap.py", *args, str(project)],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def add_claim_and_evidence(
    runtime: Path,
    gate_hash: str,
    status: str = "passed",
    actor: str = "nogapbench-verifier",
    authority: str = "verification",
    evidence_id: str = "evidence-0001",
) -> None:
    write_json(runtime / "claims" / "claim-0001.json", {
        "id": "claim-0001",
        "run_id": "run-0001",
        "text": "Benchmark claim.",
        "status": "supported",
        "evidence": [evidence_id],
    })
    write_json(runtime / "evidence" / f"{evidence_id}.json", {
        "id": evidence_id,
        "run_id": "run-0001",
        "kind": "test",
        "status": status,
        "claim_ids": ["claim-0001"],
        "provenance": {
            "created_by": actor,
            "actor_id": actor,
            "authority": authority,
            "role": "verifier" if authority == "verification" else "implementer",
            "created_at": "2026-08-15T00:00:00Z",
            "gate_hash": gate_hash,
        },
    })


class NoGapBench(unittest.TestCase):
    def test_gate_tampering_trap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_nogap(project, "init")
            run_nogap(project, "freeze")
            gate_path = project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
            gate = read_json(gate_path)
            gate["rules"]["forbidden_changes"].clear()
            write_json(gate_path, gate)
            result = run_nogap(project, "validate", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hash mismatch", result.stderr + result.stdout)

    def test_failed_evidence_cannot_be_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_nogap(project, "init")
            run_nogap(project, "freeze")
            runtime = project / ".code-loop" / "runtime"
            gate_hash = read_json(runtime / "gates" / "gate-0001.json")["hash"]
            add_claim_and_evidence(runtime, gate_hash, status="failed")
            result = run_nogap(project, "decide")
            self.assertIn("repair:", result.stdout)
            run_nogap(project, "validate")
            context = run_nogap(project, "context", "--show")
            self.assertIn("failed-evidence", context.stdout)
            self.assertIn("repair-decision", context.stdout)

    def test_lesson_without_source_decision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_nogap(project, "init")
            runtime = project / ".code-loop" / "runtime"
            write_json(runtime / "lessons" / "lesson-0001.json", {
                "id": "lesson-0001",
                "run_id": "run-0001",
                "text": "Never trust orphan lessons.",
                "applies_when": {"tags": ["lesson"]},
                "evidence": [],
                "source_decision": "missing-decision",
            })
            result = run_nogap(project, "validate", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing source_decision", result.stderr + result.stdout)

    def test_self_verification_escape_rate_trap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_nogap(project, "init")
            run_nogap(project, "freeze")
            runtime = project / ".code-loop" / "runtime"
            gate_hash = read_json(runtime / "gates" / "gate-0001.json")["hash"]
            add_claim_and_evidence(runtime, gate_hash, actor="agent-a", authority="execution")
            result = run_nogap(project, "decide", "--actor-id", "agent-a")
            self.assertIn("repair:", result.stdout)
            self.assertIn("executor identity cannot issue ACCEPT", result.stdout)

    def test_stale_evidence_rejection_rate_trap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_nogap(project, "init")
            run_nogap(project, "freeze")
            runtime = project / ".code-loop" / "runtime"
            add_claim_and_evidence(runtime, "stale-gate-hash")
            result = run_nogap(project, "validate", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown gate_hash", result.stderr + result.stdout)

    def test_authority_conflict_rejection_rate_trap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_nogap(project, "init")
            run_nogap(project, "freeze")
            runtime = project / ".code-loop" / "runtime"
            gate_hash = read_json(runtime / "gates" / "gate-0001.json")["hash"]
            add_claim_and_evidence(runtime, gate_hash, actor="agent-a", authority="execution", evidence_id="evidence-exec")
            write_json(runtime / "evidence" / "evidence-verifier.json", {
                "id": "evidence-verifier",
                "run_id": "run-0001",
                "kind": "test",
                "status": "passed",
                "claim_ids": ["claim-0001"],
                "provenance": {
                    "created_by": "agent-a",
                    "actor_id": "agent-a",
                    "authority": "verification",
                    "role": "verifier",
                    "created_at": "2026-08-15T00:00:00Z",
                    "gate_hash": gate_hash,
                },
            })
            result = run_nogap(project, "decide", "--actor-id", "acceptor-1")
            self.assertIn("abstain:", result.stdout)

    def test_false_pass_rate_trap_requires_independent_authoritative_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_nogap(project, "init")
            run_nogap(project, "freeze")
            runtime = project / ".code-loop" / "runtime"
            gate_hash = read_json(runtime / "gates" / "gate-0001.json")["hash"]
            add_claim_and_evidence(runtime, gate_hash, actor="agent-a", authority="tool")
            result = run_nogap(project, "decide", "--actor-id", "acceptor-1")
            self.assertIn("abstain:", result.stdout)
            self.assertIn("independent authoritative verification", result.stdout)


if __name__ == "__main__":
    unittest.main()
