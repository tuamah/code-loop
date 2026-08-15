#!/usr/bin/env python3
"""End-to-end checks for the minimal NoGapCode runtime scripts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


class RuntimeScriptTests(unittest.TestCase):
    def test_runtime_accepts_only_after_frozen_gate_and_passing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "demo")
            run_script("scripts/nogap.py", "freeze", str(project))

            runtime = project / ".code-loop" / "runtime"
            gate = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))
            gate_hash = gate["hash"]

            claim = {
                "id": "claim-0001",
                "run_id": "run-0001",
                "text": "The runtime validation path works.",
                "status": "supported",
                "evidence": ["evidence-0001"],
                "provenance": {"agent_id": "test", "role": "verifier"}
            }
            evidence = {
                "id": "evidence-0001",
                "run_id": "run-0001",
                "kind": "test",
                "status": "passed",
                "claim_ids": ["claim-0001"],
                "provenance": {
                    "created_by": "test",
                    "created_at": "2026-08-15T00:00:00Z",
                    "gate_hash": gate_hash,
                    "command": "python scripts/nogap.py validate"
                },
                "summary": "Synthetic passing evidence for the runtime contract."
            }
            (runtime / "claims" / "claim-0001.json").write_text(json.dumps(claim), encoding="utf-8")
            (runtime / "evidence" / "evidence-0001.json").write_text(json.dumps(evidence), encoding="utf-8")

            run_script("scripts/nogap.py", "validate", str(project))
            result = run_script("scripts/nogap.py", "decide", str(project))
            self.assertIn("accept:", result.stdout)
            run_script("scripts/nogap.py", "validate", str(project))
            run_script(
                "scripts/nogap.py", "learn", str(project),
                "--tag", "gate",
                "--text", "Freeze the gate before trusting evidence."
            )
            recalled = run_script("scripts/nogap.py", "recall", str(project), "--tag", "gate")
            self.assertIn("Freeze the gate", recalled.stdout)
            context = run_script("scripts/nogap.py", "context", str(project), "--show")
            self.assertIn("learned-context", context.stdout)
            self.assertIn("frozen-gate", context.stdout)

    def test_runtime_rejects_tampered_frozen_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "demo")
            run_script("scripts/nogap.py", "freeze", str(project))

            gate_path = project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            gate["rules"]["required_commands"].append("echo tampered")
            gate_path.write_text(json.dumps(gate), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, "scripts/nogap.py", "validate", str(project)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hash mismatch", result.stderr + result.stdout)

    def test_literature_learning_requires_compact_complete_meaning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "learn only gated context")
            run_script(
                "scripts/nogap.py", "literature", "add", str(project),
                "--id", "lit-context-0001",
                "--title", "NoGapCode runtime docs",
                "--url", "docs/nogapcode-runtime.md",
                "--source-type", "official-doc",
                "--claim", "Useful context learning should be conditional, evidence-linked, and recalled only when matching tags apply.",
                "--lesson", "Learn conditional, evidence-linked lessons; recall them only by matching tags.",
                "--tag", "context",
                "--benefit", "accuracy",
                "--benefit", "token-cost",
                "--cost", "maintenance",
                "--evidence-strength", "primary",
                "--test", "python scripts/nogap.py recall PROJECT --tag context",
                "--accurate",
                "--concise",
                "--complete",
            )
            evaluated = run_script("scripts/nogap.py", "literature", "evaluate", str(project), "--id", "lit-context-0001")
            self.assertIn("learn:", evaluated.stdout)
            run_script("scripts/nogap.py", "literature", "learn", str(project), "--id", "lit-context-0001")
            recalled = run_script("scripts/nogap.py", "recall", str(project), "--tag", "context")
            self.assertIn("conditional, evidence-linked", recalled.stdout)
            run_script("scripts/nogap.py", "validate", str(project))

    def test_literature_learning_rejects_incomplete_meaning_even_with_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "reject vague learning")
            run_script(
                "scripts/nogap.py", "literature", "add", str(project),
                "--id", "lit-vague-0001",
                "--title", "NoGapCode runtime docs",
                "--url", "docs/nogapcode-runtime.md",
                "--source-type", "official-doc",
                "--claim", "Context lessons should stay scoped.",
                "--lesson", "Use scoped lessons.",
                "--tag", "context",
                "--benefit", "accuracy",
                "--evidence-strength", "primary",
                "--test", "python scripts/nogap.py recall PROJECT --tag context",
                "--accurate",
                "--concise",
            )
            evaluated = run_script("scripts/nogap.py", "literature", "evaluate", str(project), "--id", "lit-vague-0001")
            self.assertIn("reject:", evaluated.stdout)
            self.assertIn("meaning must be complete", evaluated.stdout)
            result = subprocess.run(
                [sys.executable, "scripts/nogap.py", "literature", "learn", str(project), "--id", "lit-vague-0001"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not approved", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
