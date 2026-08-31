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
                    "created_by": "verifier-1",
                    "actor_id": "verifier-1",
                    "authority": "verification",
                    "role": "verifier",
                    "created_at": "2026-08-15T00:00:00Z",
                    "gate_hash": gate_hash,
                    "command": "python scripts/nogap.py validate"
                },
                "summary": "Synthetic passing evidence for the runtime contract."
            }
            (runtime / "claims" / "claim-0001.json").write_text(json.dumps(claim), encoding="utf-8")
            (runtime / "evidence" / "evidence-0001.json").write_text(json.dumps(evidence), encoding="utf-8")

            run_script("scripts/nogap.py", "validate", str(project))
            result = run_script("scripts/nogap.py", "decide", str(project), "--actor-id", "acceptor-1")
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

    def test_executor_self_acceptance_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "block self accept")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            gate_hash = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))["hash"]
            self.write_claim(runtime, "evidence-exec")
            self.write_evidence(runtime, "evidence-exec", gate_hash, "passed", "agent-a", "execution", "implementer")
            result = run_script("scripts/nogap.py", "decide", str(project), "--actor-id", "agent-a")
            self.assertIn("repair:", result.stdout)
            self.assertIn("executor identity cannot issue ACCEPT", result.stdout)

    def test_independent_verifier_and_acceptor_allows_accept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "accept with separation")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            gate_hash = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))["hash"]
            self.write_claim(runtime, "evidence-verifier")
            self.write_evidence(runtime, "evidence-exec", gate_hash, "passed", "agent-a", "execution", "implementer")
            self.write_evidence(runtime, "evidence-verifier", gate_hash, "passed", "agent-b", "verification", "verifier")
            result = run_script("scripts/nogap.py", "decide", str(project), "--actor-id", "acceptor-1")
            self.assertIn("accept:", result.stdout)
            run_script("scripts/nogap.py", "validate", str(project))

    def test_independent_failed_verifier_blocks_accept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "block failed verifier")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            gate_hash = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))["hash"]
            self.write_claim(runtime, "evidence-exec")
            self.write_evidence(runtime, "evidence-exec", gate_hash, "passed", "agent-a", "execution", "implementer")
            self.write_evidence(runtime, "evidence-verifier", gate_hash, "failed", "agent-b", "verification", "verifier")
            result = run_script("scripts/nogap.py", "decide", str(project), "--actor-id", "acceptor-1")
            self.assertIn("repair:", result.stdout)

    def test_stale_verifier_gate_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "reject stale gate")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            self.write_claim(runtime, "evidence-verifier")
            self.write_evidence(runtime, "evidence-verifier", "stale-gate", "passed", "agent-b", "verification", "verifier")
            result = subprocess.run(
                [sys.executable, "scripts/nogap.py", "validate", str(project)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown gate_hash", result.stderr + result.stdout)

    def test_role_renaming_does_not_bypass_authority_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "block role spoof")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            gate_hash = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))["hash"]
            self.write_claim(runtime, "evidence-verifier")
            self.write_evidence(runtime, "evidence-exec", gate_hash, "passed", "agent-a", "execution", "implementer")
            self.write_evidence(runtime, "evidence-verifier", gate_hash, "passed", "agent-a", "verification", "verifier")
            result = run_script("scripts/nogap.py", "decide", str(project), "--actor-id", "acceptor-1")
            self.assertIn("abstain:", result.stdout)
            self.assertIn("independent authoritative verification", result.stdout)

    def test_conflicting_authoritative_evidence_blocks_accept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "block conflict")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            gate_hash = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))["hash"]
            self.write_claim(runtime, "evidence-pass")
            self.write_evidence(runtime, "evidence-pass", gate_hash, "passed", "agent-b", "verification", "verifier")
            self.write_evidence(runtime, "evidence-fail", gate_hash, "failed", "agent-c", "verification", "verifier")
            result = run_script("scripts/nogap.py", "decide", str(project), "--actor-id", "acceptor-1")
            self.assertIn("repair:", result.stdout)

    def test_literature_claim_needs_acceptance_evidence_to_be_trusted_lesson(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "literature trust")
            run_script("scripts/nogap.py", "freeze", str(project))
            run_script(
                "scripts/nogap.py", "literature", "add", str(project),
                "--id", "lit-no-evidence",
                "--title", "NoGapCode runtime docs",
                "--url", "docs/nogapcode-runtime.md",
                "--source-type", "official-doc",
                "--claim", "Learning needs independent acceptance evidence.",
                "--lesson", "Do not promote literature to trusted lessons without independent acceptance evidence.",
                "--tag", "literature",
                "--benefit", "reliability",
                "--evidence-strength", "primary",
                "--test", "python scripts/nogap.py validate PROJECT",
                "--accurate",
                "--concise",
                "--complete",
            )
            evaluated = run_script("scripts/nogap.py", "literature", "evaluate", str(project), "--id", "lit-no-evidence")
            self.assertIn("defer:", evaluated.stdout)
            self.assertIn("awaiting acceptance_evidence", evaluated.stdout)
            result = subprocess.run(
                [sys.executable, "scripts/nogap.py", "literature", "learn", str(project), "--id", "lit-no-evidence"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not approved", result.stderr + result.stdout)

    def test_provider_routing_metadata_does_not_change_gate_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "routing metadata")
            run_script("scripts/nogap.py", "freeze", str(project))
            gate_path = project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            before = gate["hash"]
            runtime = project / ".code-loop" / "runtime"
            self.write_claim(runtime, "evidence-verifier")
            self.write_evidence(runtime, "evidence-verifier", before, "passed", "agent-b", "verification", "verifier", provider="provider-a")
            evidence_path = runtime / "evidence" / "evidence-verifier.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["provenance"]["provider"] = "provider-b"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            gate_after = json.loads(gate_path.read_text(encoding="utf-8"))
            self.assertEqual(before, gate_after["hash"])
            run_script("scripts/nogap.py", "validate", str(project))

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

    def write_claim(self, runtime: Path, evidence_id: str) -> None:
        claim = {
            "id": "claim-0001",
            "run_id": "run-0001",
            "text": "The runtime trust boundary works.",
            "status": "supported",
            "evidence": [evidence_id],
        }
        (runtime / "claims" / "claim-0001.json").write_text(json.dumps(claim), encoding="utf-8")

    def write_evidence(
        self,
        runtime: Path,
        evidence_id: str,
        gate_hash: str,
        status: str,
        actor: str,
        authority: str,
        role: str,
        provider: str = "local",
    ) -> None:
        evidence = {
            "id": evidence_id,
            "run_id": "run-0001",
            "kind": "test",
            "status": status,
            "claim_ids": ["claim-0001"],
            "provenance": {
                "created_by": actor,
                "actor_id": actor,
                "authority": authority,
                "role": role,
                "provider": provider,
                "runtime": "nogap.py",
                "created_at": "2026-08-15T00:00:00Z",
                "gate_hash": gate_hash,
            },
        }
        (runtime / "evidence" / f"{evidence_id}.json").write_text(json.dumps(evidence), encoding="utf-8")

    def test_literature_learning_requires_compact_complete_meaning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "learn only gated context")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            gate_hash = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))["hash"]
            self.write_claim(runtime, "evidence-literature")
            self.write_evidence(runtime, "evidence-literature", gate_hash, "passed", "agent-b", "verification", "verifier")
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
                "--acceptance-evidence", "evidence-literature",
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

    def test_autolearn_uses_active_goal_and_available_literature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "continuous learning")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            gate_hash = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))["hash"]
            self.write_claim(runtime, "evidence-literature")
            self.write_evidence(runtime, "evidence-literature", gate_hash, "passed", "agent-b", "verification", "verifier")
            run_script(
                "scripts/nogap.py", "goal", "set", str(project),
                "--objective", "planning ai coding model like codex",
                "--tag", "planning",
                "--tag", "coding-agent",
            )
            run_script(
                "scripts/nogap.py", "literature", "add", str(project),
                "--id", "lit-codex-plan",
                "--title", "NoGapCode runtime docs",
                "--url", "docs/nogapcode-runtime.md",
                "--source-type", "official-doc",
                "--claim", "Planning an AI coding agent requires gates, evidence, bounded repair, and final decisions.",
                "--lesson", "Plan coding-agent work with gates, evidence, bounded repair, and final decisions.",
                "--tag", "planning",
                "--tag", "coding-agent",
                "--benefit", "reliability",
                "--benefit", "accuracy",
                "--evidence-strength", "primary",
                "--acceptance-evidence", "evidence-literature",
                "--test", "python scripts/nogap.py recall PROJECT --tag coding-agent",
                "--accurate",
                "--concise",
                "--complete",
            )
            run_script(
                "scripts/nogap.py", "literature", "add", str(project),
                "--id", "lit-unrelated",
                "--title", "NoGapCode runtime docs",
                "--url", "docs/nogapcode-runtime.md",
                "--source-type", "official-doc",
                "--claim", "Security gates can reduce untrusted tool use.",
                "--lesson", "Keep tool authority small at trust boundaries.",
                "--tag", "security",
                "--benefit", "security",
                "--evidence-strength", "primary",
                "--test", "python scripts/nogap.py recall PROJECT --tag security",
                "--accurate",
                "--concise",
                "--complete",
            )
            result = run_script("scripts/nogap.py", "autolearn", str(project))
            self.assertIn("learned=1", result.stdout)
            self.assertIn("deferred=1", result.stdout)
            recalled = run_script("scripts/nogap.py", "recall", str(project), "--tag", "coding-agent")
            self.assertIn("bounded repair", recalled.stdout)
            context = run_script("scripts/nogap.py", "context", str(project), "--show")
            self.assertIn("active-learning-goal", context.stdout)
            run_script("scripts/nogap.py", "validate", str(project))

    def test_status_reports_no_runtime_without_fake_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_script("scripts/nogap.py", "status", tmp, "--json")
            status = json.loads(result.stdout)
            self.assertFalse(status["runtime_exists"])
            self.assertIn("gates", status["missing_dirs"])
            self.assertIsNone(status["last_decision"])

    def test_status_reports_counts_for_initialized_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "status check")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            gate_hash = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))["hash"]
            self.write_claim(runtime, "evidence-verifier")
            self.write_evidence(runtime, "evidence-verifier", gate_hash, "passed", "agent-b", "verification", "verifier")
            run_script("scripts/nogap.py", "decide", str(project), "--actor-id", "acceptor-1")
            result = run_script("scripts/nogap.py", "status", str(project), "--json")
            status = json.loads(result.stdout)
            self.assertTrue(status["runtime_exists"])
            self.assertEqual(status["run_id"], "run-0001")
            self.assertEqual(status["gate_count"], 1)
            self.assertEqual(status["frozen_gate_count"], 1)
            self.assertEqual(status["evidence_count"], 1)
            self.assertEqual(status["authoritative_pass_count"], 1)
            self.assertEqual(status["decision_count"], 1)
            self.assertEqual(status["last_decision"]["decision"], "accept")

    def test_validate_accepts_run_lifecycle_records_and_dispatch_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "lifecycle scaffolding")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            (runtime / "plans" / "plan-0001.json").write_text(json.dumps({
                "id": "plan-0001",
                "run_id": "run-0001",
                "created_at": "2026-08-31T00:00:00Z",
                "actor_id": "terra-planner",
                "role": "planner",
                "status": "proposed",
            }), encoding="utf-8")
            (runtime / "routes" / "route-0001.json").write_text(json.dumps({
                "id": "route-0001",
                "run_id": "run-0001",
                "selected": {"provider": "codex", "runtime": "codex-cli"},
                "reason": "codex is configured and healthy",
                "policy_version": "v1",
                "created_at": "2026-08-31T00:00:00Z",
            }), encoding="utf-8")
            (runtime / "dispatches" / "dispatch-0001.json").write_text(json.dumps({
                "id": "dispatch-0001",
                "run_id": "run-0001",
                "created_at": "2026-08-31T00:00:00Z",
                "actor_id": "terra-planner",
                "role": "planner",
                "plan_id": "plan-0001",
                "route_id": "route-0001",
                "status": "intended",
            }), encoding="utf-8")
            run_script("scripts/nogap.py", "validate", str(project))

    def test_validate_rejects_dispatch_referencing_missing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "dangling dispatch")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            (runtime / "dispatches" / "dispatch-0001.json").write_text(json.dumps({
                "id": "dispatch-0001",
                "run_id": "run-0001",
                "created_at": "2026-08-31T00:00:00Z",
                "actor_id": "terra-planner",
                "role": "planner",
                "plan_id": "plan-missing",
                "status": "intended",
            }), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/nogap.py", "validate", str(project)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("references missing plan", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
