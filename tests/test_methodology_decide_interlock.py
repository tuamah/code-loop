#!/usr/bin/env python3
"""Post-M7-G fix: closes a live-discovered false-pass path.

ROOT CAUSE: `nogap decide`'s acceptance logic had no methodology awareness at all.
A methodology-tracked candidate whose required independent review was INCONCLUSIVE
(or simply never attempted) could still reach ACCEPT purely from passing
deterministic + reproducibility evidence with an independent actor_id, because
neither of those evidence records were themselves "failed"/"blocked"/"inconclusive" -
the ledger held no direct signal of the missing review at all.

FIX: verification_acceptance_precondition() (nogap_verify_binding.py) is a NECESSARY,
never sufficient, precondition consulted by cmd_decide before it may reach "accept"
on a methodology-tracked project: the current candidate's P18_VERIFICATION_RESULT
must genuinely be VERIFICATION_COMPLETE_AWAITING_DECISION under the LIVE bindings
(reusing verification_staleness() - never re-derived here). This file is the
permanent regression suite for that fix.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap  # noqa: E402
import nogap_adapters  # noqa: E402
import nogap_verify_binding as vb  # noqa: E402
from nogap_artifacts import create_artifact, list_artifacts  # noqa: E402
from nogap_methodology import init_project, status as mstatus, transition  # noqa: E402


@dataclass
class StubAdapter:
    id: str
    ready: bool = True
    kind: str = "AgentRuntime"
    command_builder: Any = None

    def health(self) -> dict[str, Any]:
        return {"status": "connected" if self.ready else "disconnected", "trust_status": "READY"}

    def capabilities(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "can_execute": False, "supported_operations": []}

    def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
        if self.command_builder:
            return self.command_builder(prompt, worktree)
        return [sys.executable, "-c", "open('marker.txt','w').write('hi')"]


def writer_adapter(adapter_id: str = "codex") -> StubAdapter:
    return StubAdapter(adapter_id, command_builder=lambda p, w: [sys.executable, "-c", "open('marker.txt','w').write('hi')"])


def review_adapter(adapter_id: str, verdict: str = "pass") -> StubAdapter:
    payload = json.dumps({"verdict": verdict, "notes": "auto"})
    return StubAdapter(adapter_id, command_builder=lambda p, w: [sys.executable, "-c", f"open('.nogap-review.json','w').write({payload!r})"])


def silent_reviewer(adapter_id: str) -> StubAdapter:
    return StubAdapter(adapter_id, command_builder=lambda p, w: [sys.executable, "-c", "pass"])


def init_git_repo(path: Path) -> None:
    def git(args: list[str]) -> None:
        subprocess.run(["git", *args], cwd=path, check=True, text=True, capture_output=True)

    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-q"])
    git(["config", "user.email", "test@test.com"])
    git(["config", "user.name", "test"])
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    git(["add", "README.md"])
    git(["commit", "-q", "-m", "initial"])


def run_namespace(path: str, **overrides: Any) -> argparse.Namespace:
    defaults = {"path": path, "actor": "test-interlock", "execute": False, "execute_timeout": 600, "task_id": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def verify_namespace(path: str, **overrides: Any) -> argparse.Namespace:
    defaults = {"path": path, "dispatch": None, "timeout": 120, "review": False, "review_timeout": 120, "actor": "verifier"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "scripts/nogap.py", *args], cwd=ROOT, text=True, capture_output=True)


def build_p0_p11_chain(project: Path, actor: str = "team", p7_extra: dict | None = None) -> dict[str, dict]:
    made: dict[str, dict] = {}
    made["P0"] = create_artifact(project, "P0_PROJECT_INTENT", {
        "project_name": "demo", "intent_type": mstatus(project)["intent"], "problem_summary": "x",
        "target_users_or_context": "team", "desired_outcome": "y", "owner": actor, "initial_constraints": ["budget"],
    }, actor=actor)
    made["P1"] = create_artifact(project, "P1_SCOPE", {
        "problem_statement": "x", "in_scope": ["a"], "out_of_scope": ["b"], "constraints": ["c"],
        "dependencies": ["d"], "known_assumptions": ["e"],
    }, actor=actor)
    made["P2"] = create_artifact(project, "P2_SUCCESS_CRITERIA", {
        "success_criteria": ["works"], "failure_criteria": ["crashes"], "risk_level": mstatus(project)["risk"],
        "claim_strength": mstatus(project)["claim_strength"], "critical_claims": ["c1"], "stop_conditions": ["s1"],
    }, actor=actor)
    made["P3"] = create_artifact(project, "P3_PRIOR_ART", {
        "research_question": "q", "search_scope": "s", "sources": ["s1"], "candidate_solutions": ["c1"],
        "key_findings": ["f1"], "limitations": ["l1"],
    }, actor=actor)
    made["P4"] = create_artifact(project, "P4_GAP_ANALYSIS", {
        "requirements_or_needs": ["n"], "existing_solutions": ["s"], "covered_capabilities": ["c"],
        "missing_capabilities": ["m"], "tradeoffs": ["t"], "gaps": ["g"], "prior_art_refs": [made["P3"]["artifact_id"]],
    }, actor=actor)
    made["P5"] = create_artifact(project, "P5_STRATEGY_DECISION", {
        "selected_strategy": "BUILD", "alternatives_considered": ["BUY"], "reason": "r", "cost": "low",
        "risk": "low", "gap_analysis_refs": [made["P4"]["artifact_id"]],
    }, actor=actor)
    made["P6"] = create_artifact(project, "P6_REQUIREMENT", {
        "type": "functional", "statement": "system must do X", "priority": "high",
        "acceptance_criteria": ["X happens"], "strategy_decision_refs": [made["P5"]["artifact_id"]],
    }, actor=actor)
    req_id = made["P6"]["fields"]["requirement_id"]
    made["P7"] = create_artifact(project, "P7_ARCHITECTURE", {
        "components": ["svc1"], "trust_boundaries": ["b1"], "execution_authorities": ["agent"],
        "acceptance_authorities": ["human"], "requirement_refs": [req_id],
        **(p7_extra or {}),
    }, actor=actor)
    made["P8"] = create_artifact(project, "P8_ADR", {
        "decision": "use postgres", "context": "need durable storage", "alternatives": ["sqlite", "postgres"],
        "selected_option": "postgres", "rationale": "scale", "consequences": ["ops burden"],
        "expected_cost": "medium", "architecture_refs": [made["P7"]["artifact_id"]],
    }, actor=actor)
    made["P9"] = create_artifact(project, "P9_GOVERNANCE", {
        "roles": ["architect", "verifier"], "authority_assignments": {"acceptance": "human:owner"},
        "execution_backend_policy": "isolated worktree only", "verification_policy": "independent review required",
        "human_approval_requirements": ["release"], "adr_refs": [made["P8"]["artifact_id"]],
    }, actor=actor)
    made["P10"] = create_artifact(project, "P10_BASELINE", {
        "baseline_description": "manual process", "primary_metric": "completion time",
        "secondary_metrics": ["error rate"], "measurement_procedure": "manual timing",
    }, actor=actor)
    made["P11"] = create_artifact(project, "P11_GATE_PLAN", {
        "gate_id": "gate-plan-1", "required_tests": ["unit"], "evidence_requirements": ["execution"],
        "stop_conditions": ["security fail"], "verification_depth": "standard", "requirement_refs": [req_id],
        "required_commands": ["echo verify-check"], "forbidden_paths": ["secrets.env"],
    }, actor=actor)
    order = ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11"]
    for current, nxt in zip(order, order[1:]):
        evidence_refs = ["source-ref-1"] if current == "P3" else []
        transition(project, nxt, actor, f"{current} obligations satisfied",
                   artifact_refs=[made[current]["artifact_id"]], evidence_refs=evidence_refs, authority_class="tool")
    return made


def make_task_contract(project: Path, made_chain: dict, actor: str = "architect", **field_overrides: Any) -> dict:
    fields = {
        "goal": "implement X", "scope": ["svc1"], "forbidden_scope": ["unrelated services"],
        "acceptance_criteria": ["X happens"], "planned_tests": ["unit"], "required_evidence": ["execution"],
        "stop_conditions": ["security fail"], "requirement_refs": [made_chain["P6"]["fields"]["requirement_id"]],
        "gate_plan_refs": [made_chain["P11"]["artifact_id"]],
    }
    fields.update(field_overrides)
    return create_artifact(project, "P12_TASK_CONTRACT", fields, actor=actor)


class InterlockFixture(unittest.TestCase):
    profile_args = ("production", "medium", "low")  # STANDARD: reproducibility + review required
    p7_extra: dict | None = {"responsibilities": ["r"], "interfaces": ["i"], "external_dependencies": ["d"]}

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        init_project(self.project, *self.profile_args, actor="test")
        self.chain = build_p0_p11_chain(self.project, p7_extra=self.p7_extra)
        self.contract = make_task_contract(self.project, self.chain)
        run_script("init", str(self.project), "--objective", "interlock fixture")

        self._original_adapters = dict(nogap_adapters.ADAPTERS)
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = writer_adapter("codex")
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.contract["fields"]["task_id"]))
        run_script("freeze", str(self.project))

    def tearDown(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._original_adapters)
        self.tmp.cleanup()

    def latest_result(self) -> dict[str, Any]:
        return list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")[-1]

    def decide(self) -> dict[str, Any]:
        result = run_script("decide", str(self.project))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((self.project / ".code-loop" / "runtime" / "decisions" / "decision-0001.json").read_text(encoding="utf-8"))


class BlockedAcceptTests(InterlockFixture):
    def test_1_standard_independent_review_inconclusive_cannot_accept(self) -> None:
        nogap_adapters.ADAPTERS["claude"] = silent_reviewer("claude")
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        self.assertEqual(self.latest_result()["status"], "VERIFICATION_INCONCLUSIVE")
        # The methodology interlock alone would reach "abstain: methodology
        # verification precondition not satisfied"; here the pre-existing
        # authoritative_conflicts check (the review evidence itself is real
        # authority="verification" status="inconclusive") already refuses first with
        # "repair" - both are correct, non-accept outcomes, and either is acceptable
        # proof of "cannot ACCEPT". The precondition itself is asserted directly too.
        precondition = vb.verification_acceptance_precondition(self.project, self.contract["fields"]["task_id"])
        self.assertFalse(precondition["satisfied"])
        decision = self.decide()
        self.assertNotEqual(decision["decision"], "accept")

    def test_critical_adversarial_deterministic_pass_review_inconclusive(self) -> None:
        """The EXACT live-discovered false-pass shape: deterministic verification
        PASSES, required independent review is never attempted at all (not even a
        failed/inconclusive evidence record exists for it - only a methodology-level
        skip/gap). Before the fix this reached ACCEPT; after the fix it must not."""
        nogap.cmd_verify(verify_namespace(str(self.project), review=False))
        result = self.latest_result()
        self.assertEqual(result["fields"]["deterministic_result"], "passed")
        self.assertEqual(result["fields"]["independent_review_result"], "inconclusive")
        self.assertEqual(result["status"], "VERIFICATION_INCONCLUSIVE")
        decision = self.decide()
        self.assertNotEqual(decision["decision"], "accept")
        self.assertIn("VERIFICATION_INCONCLUSIVE", decision["reason"])

    def test_2_strict_missing_required_review_cannot_accept(self) -> None:
        from nogap_methodology import escalate_phase
        escalate_phase(self.project, "VERIFY", "STRICT", actor="human:owner")
        nogap.cmd_verify(verify_namespace(str(self.project), review=False))
        decision = self.decide()
        self.assertNotEqual(decision["decision"], "accept")

    def test_3_required_reproducibility_failed_cannot_accept(self) -> None:
        # Exercising a genuine non-reproducible re-run is covered precisely in
        # test_methodology_verify.py; here the interlock itself is what's under test,
        # so a P18_VERIFICATION_RESULT record whose reproducibility_result is "failed"
        # (the exact shape _finalize_verification would never let reach COMPLETE) is
        # constructed directly, proving decide's interlock honors that status.
        nogap_adapters.ADAPTERS["claude"] = review_adapter("claude", "pass")
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        result = self.latest_result()
        path = self.project / ".code-loop" / "methodology" / "artifacts" / f"{result['artifact_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["status"] = "VERIFICATION_FAILED"
        record["fields"]["reproducibility_result"] = "failed"
        path.write_text(json.dumps(record), encoding="utf-8")

        precondition = vb.verification_acceptance_precondition(self.project, self.contract["fields"]["task_id"])
        self.assertFalse(precondition["satisfied"])
        self.assertIn("VERIFICATION_FAILED", precondition["reason"])
        decision = self.decide()
        self.assertNotEqual(decision["decision"], "accept")


class StalePreconditionTests(InterlockFixture):
    """Tests 4-8: each of the six acceptance-critical bindings, individually mutated
    on an otherwise-COMPLETE result, must independently block the precondition."""

    def setUp(self) -> None:
        super().setUp()
        nogap_adapters.ADAPTERS["claude"] = review_adapter("claude", "pass")
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        self.result = self.latest_result()
        self.assertEqual(self.result["status"], "VERIFICATION_COMPLETE_AWAITING_DECISION")
        self.task_id = self.contract["fields"]["task_id"]

    def _mutate_result_field(self, **field_updates: Any) -> None:
        path = self.project / ".code-loop" / "methodology" / "artifacts" / f"{self.result['artifact_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"].update(field_updates)
        path.write_text(json.dumps(record), encoding="utf-8")

    def test_9_fresh_result_satisfies_precondition(self) -> None:
        precondition = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertTrue(precondition["satisfied"], precondition["reason"])

    def test_4_stale_candidate_hash_cannot_accept(self) -> None:
        self._mutate_result_field(candidate_hash="deadbeef")
        precondition = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertFalse(precondition["satisfied"])
        self.assertIn("stale", precondition["reason"])

    def test_5_stale_gate_hash_cannot_accept(self) -> None:
        self._mutate_result_field(gate_hash="deadbeef")
        precondition = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertFalse(precondition["satisfied"])

    def test_6_stale_methodology_version_cannot_accept(self) -> None:
        self._mutate_result_field(methodology_version_at_verification="0.0.1")
        precondition = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertFalse(precondition["satisfied"])

    def test_7_stale_task_content_cannot_accept(self) -> None:
        self._mutate_result_field(task_snapshot_hash="deadbeef")
        precondition = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertFalse(precondition["satisfied"])

    def test_8_stale_requirement_set_cannot_accept(self) -> None:
        self._mutate_result_field(requirement_refs=["REQ-999"])
        precondition = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertFalse(precondition["satisfied"])

    def test_stale_candidate_end_to_end_through_decide(self) -> None:
        self._mutate_result_field(patch_hash="deadbeef")
        decision = self.decide()
        self.assertNotEqual(decision["decision"], "accept")
        self.assertIn("stale", decision["reason"])


class LightSkipSatisfiesPreconditionTests(unittest.TestCase):
    """Test 9 (LIGHT-specific reading): a policy-valid LIGHT flow with explicit,
    auditable P17/P18 skips must be able to satisfy the precondition - the interlock
    must never blindly demand P18 reviewer evidence regardless of profile."""

    def test_light_explicit_skips_satisfy_precondition_and_decide_may_accept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            init_project(project, "research", "low", "low", actor="test")  # LIGHT
            chain = build_p0_p11_chain(project)
            contract = make_task_contract(project, chain)
            run_script("init", str(project), "--objective", "light skip precondition")

            original_adapters = dict(nogap_adapters.ADAPTERS)
            nogap_adapters.ADAPTERS.clear()
            nogap_adapters.ADAPTERS["codex"] = writer_adapter("codex")
            try:
                nogap.cmd_run(run_namespace(str(project), execute=True, task_id=contract["fields"]["task_id"]))
                run_script("freeze", str(project))
                nogap.cmd_verify(verify_namespace(str(project), review=False))

                result = list_artifacts(project, artifact_type="P18_VERIFICATION_RESULT")[-1]
                self.assertEqual(result["fields"]["reproducibility_result"], "SKIPPED_PER_PROFILE_POLICY")
                self.assertEqual(result["fields"]["independent_review_result"], "SKIPPED_PER_PROFILE_POLICY")
                self.assertEqual(result["status"], "VERIFICATION_COMPLETE_AWAITING_DECISION")

                precondition = vb.verification_acceptance_precondition(project, contract["fields"]["task_id"])
                self.assertTrue(precondition["satisfied"], precondition["reason"])

                decide_result = run_script("decide", str(project))
                decision = json.loads((project / ".code-loop" / "runtime" / "decisions" / "decision-0001.json").read_text(encoding="utf-8"))
                self.assertEqual(decision["decision"], "accept")  # genuinely reached, not forced
            finally:
                nogap_adapters.ADAPTERS.clear()
                nogap_adapters.ADAPTERS.update(original_adapters)


class NecessaryNotSufficientTests(InterlockFixture):
    def test_10_complete_status_necessary_but_not_sufficient(self) -> None:
        """A COMPLETE_AWAITING_DECISION methodology result does not itself manufacture
        ACCEPT - the Trust Runtime's own independent-evidence/identity checks still
        apply on top of it."""
        nogap_adapters.ADAPTERS["claude"] = review_adapter("claude", "pass")
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        self.assertEqual(self.latest_result()["status"], "VERIFICATION_COMPLETE_AWAITING_DECISION")
        precondition = vb.verification_acceptance_precondition(self.project, self.contract["fields"]["task_id"])
        self.assertTrue(precondition["satisfied"])
        # but decide, called with an actor that IS the executor, must still refuse -
        # the methodology precondition being satisfied does not override this.
        result = run_script("decide", str(self.project), "--actor-id", "agent:codex")
        decision = json.loads((self.project / ".code-loop" / "runtime" / "decisions" / "decision-0001.json").read_text(encoding="utf-8"))
        self.assertNotEqual(decision["decision"], "accept")
        self.assertEqual(decision["reason"], "executor identity cannot issue ACCEPT")

    def test_11_self_check_evidence_alone_cannot_satisfy_interlock(self) -> None:
        # No verify has been run at all yet - only P13/P14 BUILD evidence and the
        # P14_SELF_CHECK artifact exist. There is no P18_VERIFICATION_RESULT at all.
        precondition = vb.verification_acceptance_precondition(self.project, self.contract["fields"]["task_id"])
        self.assertFalse(precondition["satisfied"])
        self.assertIn("no methodology verification result", precondition["reason"])
        decision = self.decide()
        self.assertNotEqual(decision["decision"], "accept")


class LegacyCompatibilityTests(unittest.TestCase):
    def test_12_legacy_uninitialized_project_unaffected(self) -> None:
        # verification_acceptance_precondition on a project with no methodology state
        # at all must report satisfied=True (the documented, temporary compatibility
        # exception) - it never fabricates a task_id requirement for such a project.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            precondition = vb.verification_acceptance_precondition(project, None)
            self.assertTrue(precondition["satisfied"])
            self.assertIn("legacy compatibility", precondition["reason"])

    def test_legacy_orchestrator_decide_flow_unaffected(self) -> None:
        """End-to-end: the pre-existing M6 orchestrator test flow (no methodology
        init at all) must still be able to reach ACCEPT exactly as before."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            run_script("init", str(project), "--objective", "legacy decide flow")

            original_adapters = dict(nogap_adapters.ADAPTERS)
            nogap_adapters.ADAPTERS.clear()
            nogap_adapters.ADAPTERS["codex"] = writer_adapter("codex")
            try:
                nogap.cmd_run(run_namespace(str(project), execute=True))
                run_script("freeze", str(project))
                nogap_adapters.ADAPTERS["claude"] = review_adapter("claude", "pass")
                nogap.cmd_verify(verify_namespace(str(project), review=True))
                result = run_script("decide", str(project))
                decision = json.loads((project / ".code-loop" / "runtime" / "decisions" / "decision-0001.json").read_text(encoding="utf-8"))
                self.assertEqual(decision["decision"], "accept")
            finally:
                nogap_adapters.ADAPTERS.clear()
                nogap_adapters.ADAPTERS.update(original_adapters)


if __name__ == "__main__":
    unittest.main()
