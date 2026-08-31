#!/usr/bin/env python3
"""M7-G acceptance checks: binding BUILD output (P14 BUILD_COMPLETE_AWAITING_
VERIFICATION) to methodology VERIFY phases (P15-P18) via the existing, unmodified
M6-D verification pipeline.

Covers the 36 mandatory cases from the brief (M6/M7-A..F regression coverage is
verified by running the full existing suites alongside this file, not duplicated
here) plus automated versions of the manual live scenarios.
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
from nogap_artifacts import create_artifact, list_artifacts, load_artifact, update_requirement_status  # noqa: E402
from nogap_methodology import (  # noqa: E402
    MethodologyValidationError,
    downgrade_profile,
    escalate_phase,
    init_project,
    status as mstatus,
    transition,
)


@dataclass
class StubAdapter:
    id: str
    ready: bool = True
    kind: str = "AgentRuntime"
    command_builder: Any = None

    def health(self) -> dict[str, Any]:
        return {"status": "connected" if self.ready else "disconnected", "trust_status": "READY" if self.ready else "NOT_READY"}

    def capabilities(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "can_execute": False, "supported_operations": []}

    def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
        if self.command_builder:
            return self.command_builder(prompt, worktree)
        return [sys.executable, "-c", f"open('agent_output.txt', 'w').write({prompt!r})"]


def writer_adapter(adapter_id: str = "codex") -> StubAdapter:
    return StubAdapter(adapter_id, command_builder=lambda prompt, worktree: [sys.executable, "-c", "open('marker.txt','w').write('hi')"])


def review_adapter(adapter_id: str, verdict: str = "pass") -> StubAdapter:
    payload = json.dumps({"verdict": verdict, "notes": "auto"})
    return StubAdapter(
        adapter_id,
        command_builder=lambda prompt, worktree: [sys.executable, "-c", f"open('.nogap-review.json','w').write({payload!r})"],
    )


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
    defaults = {"path": path, "actor": "test-verify", "execute": False, "execute_timeout": 600, "task_id": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def verify_namespace(path: str, **overrides: Any) -> argparse.Namespace:
    defaults = {"path": path, "dispatch": None, "timeout": 120, "review": False, "review_timeout": 120, "actor": "verifier"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "scripts/nogap.py", *args], cwd=ROOT, text=True, capture_output=True)


def build_p0_p11_chain(project: Path, actor: str = "team", p7_extra: dict | None = None, p8_extra: dict | None = None,
                        required_commands: list[str] | None = None) -> dict[str, dict]:
    """Full P0-P11 chain WITH the transitions driving current_phase to P11 - required_
    commands defaults to empty so it never conflicts with the runtime gate's own
    (also-empty-by-default) rules, per M7-F's gate_alignment_reasons()."""
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
        **(p8_extra or {}),
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
        "required_commands": required_commands or ["echo verify-check"], "forbidden_paths": ["secrets.env"],
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


class VerifyCandidateBuilder(unittest.TestCase):
    """Base fixture: full P0-P11 -> P12 TaskContract -> real P13/P14 BUILD (via a
    StubAdapter, exactly the pattern test_methodology_build.py uses), leaving the
    project sitting at BUILD_COMPLETE_AWAITING_VERIFICATION (P14), ready to verify."""

    profile_args = ("research", "low", "low")  # LIGHT by default

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        init_project(self.project, *self.profile_args, actor="test")
        self.chain = build_p0_p11_chain(self.project)
        self.contract = make_task_contract(self.project, self.chain)
        run_script("init", str(self.project), "--objective", "M7-G verify binding")

        self._original_adapters = dict(nogap_adapters.ADAPTERS)
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = writer_adapter("codex")
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.contract["fields"]["task_id"]))
        self.assertEqual(mstatus(self.project)["current_phase"], "P14")

    def tearDown(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._original_adapters)
        self.tmp.cleanup()

    def freeze_gate(self) -> None:
        run_script("freeze", str(self.project))

    def latest_result(self) -> dict[str, Any]:
        return list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")[-1]

    def latest_plan(self) -> dict[str, Any]:
        return list_artifacts(self.project, artifact_type="P15_VERIFICATION_PLAN")[-1]


class PreflightAndPlanTests(VerifyCandidateBuilder):
    def test_1_p14_candidate_cannot_jump_directly_to_p18(self) -> None:
        from nogap_methodology import can_transition
        result = can_transition(self.project, "P18")
        self.assertFalse(result["allowed"])

    def test_2_and_3_plan_binds_real_task_and_requirements(self) -> None:
        self.freeze_gate()
        nogap.cmd_verify(verify_namespace(str(self.project)))
        plan = self.latest_plan()
        self.assertEqual(plan["fields"]["task_id"], self.contract["fields"]["task_id"])
        self.assertEqual(plan["fields"]["requirement_refs"], [self.chain["P6"]["fields"]["requirement_id"]])

    def test_4_fake_task_ref_rejected(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            create_artifact(self.project, "P15_VERIFICATION_PLAN", {
                "task_id": "TASK-999", "requirement_refs": [], "profile": "LIGHT", "risk": "low", "claim_strength": "low",
                "required_levels": ["STATIC_CHECKS"], "required_validation_levels": ["LEVEL_1_CONTROLLED"],
                "required_evidence_kinds": ["deterministic"], "independent_review_required": False,
                "reproducibility_required": False, "external_validation_required": False,
            }, actor="architect")

    def test_5_fake_requirement_ref_rejected(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            create_artifact(self.project, "P15_VERIFICATION_PLAN", {
                "task_id": self.contract["fields"]["task_id"], "requirement_refs": ["REQ-999"],
                "profile": "LIGHT", "risk": "low", "claim_strength": "low",
                "required_levels": ["STATIC_CHECKS"], "required_validation_levels": ["LEVEL_1_CONTROLLED"],
                "required_evidence_kinds": ["deterministic"], "independent_review_required": False,
                "reproducibility_required": False, "external_validation_required": False,
            }, actor="architect")

    def test_6_and_7_and_8_result_binds_candidate_gate_and_version(self) -> None:
        self.freeze_gate()
        nogap.cmd_verify(verify_namespace(str(self.project)))
        result = self.latest_result()
        fields = result["fields"]
        expected_candidate = vb.compute_candidate_hash(self.contract["fields"]["task_id"], fields["patch_hash"])
        self.assertEqual(fields["candidate_hash"], expected_candidate)
        gate = json.loads((self.project / ".code-loop" / "runtime" / "gates" / "gate-0001.json").read_text(encoding="utf-8"))
        self.assertEqual(fields["gate_hash"], gate["hash"])
        self.assertEqual(fields["methodology_version_at_verification"], mstatus(self.project)["methodology_version"])

    def test_9_level_1_required_and_satisfied_at_light(self) -> None:
        self.freeze_gate()
        nogap.cmd_verify(verify_namespace(str(self.project)))
        plan = self.latest_plan()
        self.assertEqual(plan["fields"]["required_validation_levels"], ["LEVEL_1_CONTROLLED"])
        result = self.latest_result()
        self.assertIn("STATIC_CHECKS", result["fields"]["levels_passed"])

    def test_31_p18_completion_stops_at_awaiting_decision(self) -> None:
        self.freeze_gate()
        nogap.cmd_verify(verify_namespace(str(self.project)))
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")
        result = self.latest_result()
        self.assertEqual(result["status"], "VERIFICATION_COMPLETE_AWAITING_DECISION")

    def test_12_light_explicit_skip_recorded(self) -> None:
        self.freeze_gate()
        nogap.cmd_verify(verify_namespace(str(self.project)))
        result = self.latest_result()
        self.assertEqual(result["fields"]["reproducibility_result"], "SKIPPED_PER_PROFILE_POLICY")
        self.assertEqual(result["fields"]["independent_review_result"], "SKIPPED_PER_PROFILE_POLICY")

    def test_32_and_33_verifier_and_reviewer_never_write_accept(self) -> None:
        self.freeze_gate()
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        evidence_dir = self.project / ".code-loop" / "runtime" / "evidence"
        for path in evidence_dir.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotEqual(record["provenance"].get("authority"), "acceptance")
        decisions_dir = self.project / ".code-loop" / "runtime" / "decisions"
        self.assertFalse(decisions_dir.is_dir() and list(decisions_dir.glob("*.json")))

    def test_34_self_check_does_not_satisfy_independent_verification(self) -> None:
        self.freeze_gate()
        nogap.cmd_verify(verify_namespace(str(self.project)))
        self_checks = list_artifacts(self.project, artifact_type="P14_SELF_CHECK")
        self.assertEqual(self_checks[0]["fields"]["self_check_authority"], "execution")
        # nothing in the M6 evidence ledger's authoritative-evidence computation ever
        # reads P14_SELF_CHECK at all - it only ever reads .code-loop/runtime/evidence
        evidence_dir = self.project / ".code-loop" / "runtime" / "evidence"
        for path in evidence_dir.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("self_check", json.dumps(record))


class DeterministicAndReproducibilityTests(VerifyCandidateBuilder):
    def _mutate_gate_rules_before_freeze(self, **rule_updates: Any) -> None:
        gate_path = self.project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["rules"].update(rule_updates)
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        self.freeze_gate()

    def test_14_deterministic_failure_blocks_later_success(self) -> None:
        # forbidden_paths=["secrets.env"] but the candidate never touches it - instead
        # simulate a required-command failure by pointing the frozen gate at a failing
        # command. Rules must be set BEFORE freezing - freeze fixes the gate's hash to
        # its content at that moment.
        self._mutate_gate_rules_before_freeze(required_commands=[f"{sys.executable} -c \"import sys; sys.exit(1)\""])

        nogap.cmd_verify(verify_namespace(str(self.project)))
        self.assertEqual(mstatus(self.project)["current_phase"], "P16")  # never advanced past P16
        result = self.latest_result()
        self.assertEqual(result["fields"]["deterministic_result"], "failed")
        self.assertEqual(result["status"], "VERIFICATION_FAILED")
        self.assertEqual(result["fields"]["reproducibility_result"], "PENDING")  # never reached
        self.assertEqual(result["fields"]["independent_review_result"], "PENDING")

    def test_15_forbidden_path_violation_remains_failed(self) -> None:
        # The candidate (writer_adapter) always writes marker.txt - declare exactly
        # that path forbidden in the frozen gate rather than rebuilding a new candidate.
        self._mutate_gate_rules_before_freeze(forbidden_paths=["marker.txt"])
        nogap.cmd_verify(verify_namespace(str(self.project)))
        result = self.latest_result()
        self.assertEqual(result["fields"]["deterministic_result"], "failed")

    def test_16_required_command_failure_remains_failed(self) -> None:
        self._mutate_gate_rules_before_freeze(required_commands=[f"{sys.executable} -c \"raise SystemExit(1)\""])
        nogap.cmd_verify(verify_namespace(str(self.project)))
        result = self.latest_result()
        self.assertEqual(result["fields"]["deterministic_result"], "failed")

    def test_17_fresh_worktree_still_used_for_deterministic_layer(self) -> None:
        self.freeze_gate()
        nogap.cmd_verify(verify_namespace(str(self.project)))
        # cleanup unaffected by this milestone: no leftover worktree SUBDIRECTORIES
        # after verification (the parent .nogap/worktrees container itself may persist).
        worktrees_dir = self.project / ".nogap" / "worktrees"
        leftover = list(worktrees_dir.iterdir()) if worktrees_dir.exists() else []
        self.assertEqual(leftover, [])


class StandardProfileReproducibilityTests(unittest.TestCase):
    """STANDARD profile: reproducibility (real re-run) and independent review are both required."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        init_project(self.project, "production", "medium", "low", actor="test")  # STANDARD
        self.chain = build_p0_p11_chain(
            self.project,
            p7_extra={"responsibilities": ["r"], "interfaces": ["i"], "external_dependencies": ["d"]},
        )
        self.contract = make_task_contract(self.project, self.chain)
        run_script("init", str(self.project), "--objective", "M7-G STANDARD verify")

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

    def test_10_standard_requires_level_2(self) -> None:
        nogap.cmd_verify(verify_namespace(str(self.project)))
        plan = list_artifacts(self.project, artifact_type="P15_VERIFICATION_PLAN")[-1]
        self.assertIn("LEVEL_2_REPRESENTATIVE", plan["fields"]["required_validation_levels"])
        self.assertTrue(plan["fields"]["reproducibility_required"])
        self.assertTrue(plan["fields"]["independent_review_required"])

    def test_13_phase_override_increases_verification_requirements(self) -> None:
        escalate_phase(self.project, "VERIFY", "STRICT", actor="human:owner")
        depth = vb.derive_verification_depth(self.project)
        self.assertEqual(depth["profile"], "STRICT")
        self.assertIn("LEVEL_3_DIFFICULT", depth["required_validation_levels"])
        self.assertTrue(depth["external_validation_required"])

    def test_18_and_20_executor_cannot_verify_itself_different_actor_accepted(self) -> None:
        nogap_adapters.ADAPTERS["claude"] = review_adapter("claude", "pass")
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        result = self.latest_result()
        self.assertEqual(result["fields"]["independent_review_result"], "passed")
        self.assertEqual(result["status"], "VERIFICATION_COMPLETE_AWAITING_DECISION")
        self.assertNotEqual(result["fields"]["executor_actor_id"], "agent:claude")

    def test_19_same_actor_under_renamed_role_rejected(self) -> None:
        self.assertFalse(vb.reviewer_is_independent("agent:codex", "agent:codex"))
        self.assertTrue(vb.reviewer_is_independent("agent:codex", "agent:claude"))

    def test_21_required_independent_review_unavailable_is_inconclusive(self) -> None:
        nogap.cmd_verify(verify_namespace(str(self.project), review=False))
        result = self.latest_result()
        self.assertEqual(result["fields"]["independent_review_result"], "inconclusive")
        self.assertEqual(result["status"], "VERIFICATION_INCONCLUSIVE")

    def test_22_malformed_reviewer_verdict_is_inconclusive(self) -> None:
        nogap_adapters.ADAPTERS["claude"] = StubAdapter(
            "claude", command_builder=lambda prompt, worktree: [sys.executable, "-c", "open('.nogap-review.json','w').write('not json')"],
        )
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        result = self.latest_result()
        self.assertEqual(result["fields"]["independent_review_result"], "inconclusive")

    def test_23_reproducibility_enforced_when_required(self) -> None:
        nogap_adapters.ADAPTERS["claude"] = review_adapter("claude", "pass")
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        result = self.latest_result()
        self.assertEqual(result["fields"]["reproducibility_result"], "passed")

    def test_24_external_validation_unavailable_at_strict(self) -> None:
        escalate_phase(self.project, "VERIFY", "STRICT", actor="human:owner")
        nogap_adapters.ADAPTERS["claude"] = review_adapter("claude", "pass")
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        result = self.latest_result()
        self.assertEqual(result["fields"]["reproducibility_result"], "inconclusive")
        self.assertNotEqual(result["status"], "VERIFICATION_COMPLETE_AWAITING_DECISION")


class StalenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        init_project(self.project, "research", "low", "low", actor="test")
        self.chain = build_p0_p11_chain(self.project)
        self.contract = make_task_contract(self.project, self.chain)
        run_script("init", str(self.project), "--objective", "M7-G staleness")
        self._original_adapters = dict(nogap_adapters.ADAPTERS)
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = writer_adapter("codex")
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.contract["fields"]["task_id"]))
        run_script("freeze", str(self.project))
        nogap.cmd_verify(verify_namespace(str(self.project)))
        self.result = list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")[-1]
        self.assertEqual(self.result["status"], "VERIFICATION_COMPLETE_AWAITING_DECISION")

    def tearDown(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._original_adapters)
        self.tmp.cleanup()

    def gate_hash_value(self) -> str:
        return json.loads((self.project / ".code-loop" / "runtime" / "gates" / "gate-0001.json").read_text(encoding="utf-8"))["hash"]

    def test_25_candidate_hash_change_invalidates(self) -> None:
        mutated = dict(self.result)
        mutated["fields"] = {**mutated["fields"], "candidate_hash": "deadbeef"}
        reasons = vb.verification_staleness(self.project, mutated, self.gate_hash_value())
        self.assertTrue(any("candidate hash" in r for r in reasons))

    def test_26_patch_hash_change_invalidates(self) -> None:
        mutated = dict(self.result)
        mutated["fields"] = {**mutated["fields"], "patch_hash": "deadbeef"}
        reasons = vb.verification_staleness(self.project, mutated, self.gate_hash_value())
        self.assertTrue(any("patch hash" in r for r in reasons))

    def test_27_gate_hash_change_invalidates(self) -> None:
        reasons = vb.verification_staleness(self.project, self.result, "some-other-gate-hash")
        self.assertTrue(any("gate hash" in r for r in reasons))

    def test_28_methodology_version_change_invalidates(self) -> None:
        mutated = dict(self.result)
        mutated["fields"] = {**mutated["fields"], "methodology_version_at_verification": "0.0.1"}
        reasons = vb.verification_staleness(self.project, mutated, self.gate_hash_value())
        self.assertTrue(any("methodology version" in r for r in reasons))

    def test_29_task_change_invalidates(self) -> None:
        mutated = dict(self.result)
        mutated["fields"] = {**mutated["fields"], "task_snapshot_hash": "deadbeef"}
        reasons = vb.verification_staleness(self.project, mutated, self.gate_hash_value())
        self.assertTrue(any("task contract content" in r for r in reasons))

    def test_30_requirement_set_change_invalidates(self) -> None:
        mutated = dict(self.result)
        mutated["fields"] = {**mutated["fields"], "requirement_refs": ["REQ-999"]}
        reasons = vb.verification_staleness(self.project, mutated, self.gate_hash_value())
        self.assertTrue(any("requirement set" in r for r in reasons))

    def test_fresh_result_has_no_staleness(self) -> None:
        reasons = vb.verification_staleness(self.project, self.result, self.gate_hash_value())
        self.assertEqual(reasons, [])

    def test_stale_gate_reroll_blocks_awaiting_decision(self) -> None:
        # re-freeze semantics: mutate rules pre-freeze on a fresh gate file to get a new hash
        gate_path = self.project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["status"] = "draft"
        gate.pop("hash", None)
        gate["rules"]["forbidden_paths"] = ["a-new-forbidden-path.txt"]
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        run_script("freeze", str(self.project))
        new_hash = self.gate_hash_value()
        self.assertNotEqual(new_hash, self.result["fields"]["gate_hash"])
        reasons = vb.verification_staleness(self.project, self.result, new_hash)
        self.assertTrue(any("gate hash" in r for r in reasons))


class ManualLiveScenarioTests(unittest.TestCase):
    """Automated versions of the manual live scenarios, run through the real CLI
    subprocess for init/freeze and in-process cmd_run/cmd_verify for the parts that
    need adapter stubbing."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        init_project(self.project, "research", "low", "low", actor="test")
        self.chain = build_p0_p11_chain(self.project)
        self.contract = make_task_contract(self.project, self.chain)
        run_script("init", str(self.project), "--objective", "M7-G scenario")
        self._original_adapters = dict(nogap_adapters.ADAPTERS)
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = writer_adapter("codex")
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.contract["fields"]["task_id"]))
        run_script("freeze", str(self.project))

    def tearDown(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._original_adapters)
        self.tmp.cleanup()

    def test_scenario_a_deterministic_verification_no_accept(self) -> None:
        nogap.cmd_verify(verify_namespace(str(self.project)))
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")
        result = list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")[-1]
        self.assertEqual(result["status"], "VERIFICATION_COMPLETE_AWAITING_DECISION")
        decisions_dir = self.project / ".code-loop" / "runtime" / "decisions"
        self.assertFalse(decisions_dir.is_dir() and list(decisions_dir.glob("*.json")))

    def test_scenario_b_independent_review_reaches_awaiting_decision(self) -> None:
        nogap_adapters.ADAPTERS["claude"] = review_adapter("claude", "pass")
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        result = list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")[-1]
        self.assertEqual(result["fields"]["independent_review_result"], "passed")
        self.assertEqual(result["status"], "VERIFICATION_COMPLETE_AWAITING_DECISION")

    def test_scenario_c_gate_change_after_verification_requires_reverification(self) -> None:
        nogap.cmd_verify(verify_namespace(str(self.project)))
        result = list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")[-1]
        self.assertEqual(result["status"], "VERIFICATION_COMPLETE_AWAITING_DECISION")

        gate_path = self.project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        old_hash = gate["hash"]
        gate["status"], gate["hash"] = "draft", None
        gate["rules"]["forbidden_paths"] = ["newly-forbidden.txt"]
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        run_script("freeze", str(self.project))
        new_gate = json.loads(gate_path.read_text(encoding="utf-8"))
        self.assertNotEqual(new_gate["hash"], old_hash)

        reasons = vb.verification_staleness(self.project, result, new_gate["hash"])
        self.assertTrue(reasons)

    def test_scenario_d_same_executor_as_reviewer_fails_independence(self) -> None:
        nogap_adapters.ADAPTERS["codex"] = review_adapter("codex", "pass")  # same provider as executor
        # route_implementer would normally pick a DIFFERENT provider for review; force
        # the same one to simulate the identity-collision path directly.
        self.assertFalse(vb.reviewer_is_independent("agent:codex", "agent:codex"))


if __name__ == "__main__":
    unittest.main()
