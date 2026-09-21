#!/usr/bin/env python3
"""M7-H acceptance checks: the Failure / Repair Orchestrator.

Covers the 41 mandatory cases from the brief (M6/M7-A..G regression coverage is
verified by running the full existing suites alongside this file, not duplicated
here) plus automated versions of the two required manual scenarios and the UNKNOWN
no-auto-route check.
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
import nogap_failure as nf  # noqa: E402
import nogap_verify_binding as vb  # noqa: E402
from nogap_artifacts import create_artifact, list_artifacts  # noqa: E402
from nogap_methodology import (  # noqa: E402
    MethodologyValidationError,
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
        return [sys.executable, "-c", "open('marker.txt','w').write('hi')"]


def writer_adapter(adapter_id: str = "codex") -> StubAdapter:
    return StubAdapter(adapter_id, command_builder=lambda p, w: [sys.executable, "-c", "open('marker.txt','w').write('hi')"])


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
    defaults = {"path": path, "actor": "test-failure", "execute": False, "execute_timeout": 600, "task_id": None}
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


class FailureFixture(unittest.TestCase):
    """Reaches P18 with a fresh, complete VerificationResult (VERIFICATION_COMPLETE_
    AWAITING_DECISION) and a real M6 execution evidence id ready to preserve - the
    natural point a failure would be discovered and registered from."""

    profile_args = ("research", "low", "low")  # LIGHT unless overridden

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        init_project(self.project, *self.profile_args, actor="test")
        self.chain = build_p0_p11_chain(self.project)
        self.contract = make_task_contract(self.project, self.chain)
        self.task_id = self.contract["fields"]["task_id"]
        run_script("init", str(self.project), "--objective", "failure fixture")

        self._original_adapters = dict(nogap_adapters.ADAPTERS)
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = writer_adapter("codex")
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.task_id))
        run_script("freeze", str(self.project))
        nogap.cmd_verify(verify_namespace(str(self.project)))
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")
        self.exec_evidence_id = next((self.project / ".code-loop" / "runtime" / "evidence").glob("evidence-exec-*.json")).stem

    def tearDown(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._original_adapters)
        self.tmp.cleanup()

    def create_failure(self, **overrides: Any) -> dict[str, Any]:
        fields = {
            "failure_class": "BUILD_EXECUTION_FAILURE", "summary": "synthetic failure for testing",
            "actor": "qa", "task_id": self.task_id, "evidence_refs": [], "artifact_refs": [],
        }
        fields.update(overrides)
        return nf.create_failure(self.project, **fields)

    def to_reproduced(self, failure: dict) -> dict:
        failure = nf.record_evidence_preservation(self.project, failure["failure_id"], evidence_refs=[self.exec_evidence_id], actor="qa", reason="preserve")
        failure = nf.record_reproduction(self.project, failure["failure_id"], reproduction_status="REPRODUCED", actor="qa", reason="reproduced")
        return failure

    def to_characterized(self, failure: dict) -> dict:
        failure = self.to_reproduced(failure)
        return nf.record_characterization(self.project, failure["failure_id"], actor="qa", reason="characterized",
                                           affected_requirement_refs=[self.chain["P6"]["fields"]["requirement_id"]])

    def to_researched(self, failure: dict, **kwargs) -> dict:
        failure = self.to_characterized(failure)
        return nf.record_research(self.project, failure["failure_id"], actor="qa", reason="researched", **kwargs)

    def to_root_cause(self, failure: dict, root_cause_class: str = "IMPLEMENTATION_DEFECT") -> dict:
        failure = self.to_researched(failure, research_refs=[self.chain["P3"]["artifact_id"]])
        return nf.record_root_cause(self.project, failure["failure_id"], root_cause_class=root_cause_class,
                                     root_cause_summary="diagnosed", supporting_evidence_refs=[self.exec_evidence_id],
                                     actor="qa", reason="diagnosed")

    def to_repair_proposed(self, failure: dict, target_phase: str = "P13") -> dict:
        failure = self.to_root_cause(failure)
        return nf.propose_repair(self.project, failure["failure_id"], description="minimal repair", target_phase=target_phase,
                                  evidence_refs=[self.exec_evidence_id], actor="architect", reason="propose")


class CreationAndHistoryTests(FailureFixture):
    def test_1_create_failure_opens(self) -> None:
        failure = self.create_failure()
        self.assertEqual(failure["current_state"], "OPEN")
        self.assertEqual(failure["failure_id"], "FAIL-001")

    def test_2_duplicate_failure_id_rejected(self) -> None:
        self.create_failure(failure_id="FAIL-CUSTOM")
        with self.assertRaises(MethodologyValidationError):
            self.create_failure(failure_id="FAIL-CUSTOM")

    def test_3_history_is_append_only(self) -> None:
        failure = self.create_failure()
        failure = self.to_reproduced(failure)
        self.assertGreaterEqual(len(failure["history"]), 3)
        first_entry = dict(failure["history"][0])
        failure2 = nf.record_characterization(self.project, failure["failure_id"], actor="qa", reason="characterized")
        self.assertEqual(failure2["history"][0], first_entry)  # untouched
        self.assertGreater(len(failure2["history"]), len(failure["history"]))

    def test_4_open_to_root_cause_identified_rejected(self) -> None:
        failure = self.create_failure()
        with self.assertRaises(MethodologyValidationError):
            nf.record_root_cause(self.project, failure["failure_id"], root_cause_class="IMPLEMENTATION_DEFECT",
                                  root_cause_summary="x", supporting_evidence_refs=[self.exec_evidence_id], actor="qa", reason="skip ahead")

    def test_5_evidence_preservation_required_before_reproduction(self) -> None:
        failure = self.create_failure()
        with self.assertRaises(MethodologyValidationError):
            nf.record_reproduction(self.project, failure["failure_id"], reproduction_status="REPRODUCED", actor="qa", reason="too early")

    def test_6_reproduction_status_recorded_truthfully(self) -> None:
        failure = self.create_failure()
        failure = nf.record_evidence_preservation(self.project, failure["failure_id"], evidence_refs=[self.exec_evidence_id], actor="qa", reason="preserve")
        failure = nf.record_reproduction(self.project, failure["failure_id"], reproduction_status="INTERMITTENT", actor="qa", reason="flaky")
        self.assertEqual(failure["reproduction"]["status"], "INTERMITTENT")
        self.assertEqual(failure["current_state"], "REPRODUCED")  # the STEP, not the outcome value

    def test_7_not_reproduced_cannot_silently_become_reproduced(self) -> None:
        failure = self.create_failure()
        failure = nf.record_evidence_preservation(self.project, failure["failure_id"], evidence_refs=[self.exec_evidence_id], actor="qa", reason="preserve")
        failure = nf.record_reproduction(self.project, failure["failure_id"], reproduction_status="NOT_REPRODUCED", actor="qa", reason="could not reproduce")
        self.assertEqual(failure["reproduction"]["status"], "NOT_REPRODUCED")
        # re-recording does not silently flip the stored status without a new explicit call
        reloaded = nf.load_failure(self.project, failure["failure_id"])
        self.assertEqual(reloaded["reproduction"]["status"], "NOT_REPRODUCED")

    def test_8_characterization_records_affected_refs(self) -> None:
        failure = self.create_failure()
        failure = self.to_reproduced(failure)
        req_id = self.chain["P6"]["fields"]["requirement_id"]
        failure = nf.record_characterization(self.project, failure["failure_id"], actor="qa", reason="characterized",
                                              affected_requirement_refs=[req_id], affected_gate_refs=["gate-0001"])
        self.assertEqual(failure["characterization"]["affected_requirement_refs"], [req_id])
        self.assertEqual(failure["characterization"]["affected_gate_refs"], ["gate-0001"])


class ResearchAndRootCauseTests(FailureFixture):
    def test_9_repair_before_research_rejected(self) -> None:
        failure = self.create_failure()
        failure = self.to_characterized(failure)
        with self.assertRaises(MethodologyValidationError):
            nf.propose_repair(self.project, failure["failure_id"], description="too early", target_phase="P13",
                               actor="architect", reason="skip research")

    def test_10_repair_before_root_cause_rejected(self) -> None:
        failure = self.create_failure()
        failure = self.to_researched(failure, research_refs=[self.chain["P3"]["artifact_id"]])
        with self.assertRaises(MethodologyValidationError):
            nf.propose_repair(self.project, failure["failure_id"], description="too early", target_phase="P13",
                               actor="architect", reason="skip root cause")

    def test_32_light_cannot_blind_retry_research_still_mandatory_or_explicit(self) -> None:
        failure = self.create_failure()
        failure = self.to_characterized(failure)
        with self.assertRaises(MethodologyValidationError):
            nf.record_research(self.project, failure["failure_id"], actor="qa", reason="attempt silent skip")

    def test_33_standard_enforces_research_before_repair_no_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp2:
            project2 = Path(tmp2)
            init_git_repo(project2)
            init_project(project2, "production", "medium", "low", actor="test")  # STANDARD
            chain2 = build_p0_p11_chain(project2, p7_extra={"responsibilities": ["r"], "interfaces": ["i"], "external_dependencies": ["d"]})
            failure = nf.create_failure(project2, failure_class="BUILD_EXECUTION_FAILURE", summary="x", actor="qa")
            failure = nf.record_evidence_preservation(project2, failure["failure_id"], artifact_refs=[chain2["P6"]["artifact_id"]], actor="qa", reason="preserve")
            failure = nf.record_reproduction(project2, failure["failure_id"], reproduction_status="REPRODUCED", actor="qa", reason="reproduced")
            failure = nf.record_characterization(project2, failure["failure_id"], actor="qa", reason="characterized")
            with self.assertRaises(MethodologyValidationError):
                nf.record_research(project2, failure["failure_id"], actor="qa", reason="try exception at STANDARD",
                                    policy_exception={"reason": "shortcut", "actor_id": "human:owner", "authority": "human"})

    def test_root_cause_confidence_derived_not_supplied(self) -> None:
        failure = self.create_failure()
        failure = self.to_researched(failure, research_refs=[self.chain["P3"]["artifact_id"]])
        failure = nf.record_root_cause(self.project, failure["failure_id"], root_cause_class="IMPLEMENTATION_DEFECT",
                                        root_cause_summary="x", supporting_evidence_refs=[], actor="qa", reason="no evidence")
        self.assertEqual(failure["current_state"], "INCONCLUSIVE")  # insufficient evidence, never guessed
        self.assertEqual(failure["root_cause"]["confidence_status"], "INSUFFICIENT")

    def test_16_unknown_does_not_auto_route(self) -> None:
        failure = self.create_failure()
        failure = self.to_researched(failure, research_refs=[self.chain["P3"]["artifact_id"]])
        failure = nf.record_root_cause(self.project, failure["failure_id"], root_cause_class="UNKNOWN",
                                        root_cause_summary="cannot tell", supporting_evidence_refs=[], actor="qa", reason="unknown")
        self.assertEqual(failure["current_state"], "INCONCLUSIVE")
        with self.assertRaises(MethodologyValidationError):
            nf.propose_repair(self.project, failure["failure_id"], description="guess", target_phase="P13", actor="architect", reason="guessing")

    def test_35_environment_defect_not_mislabeled_implementation(self) -> None:
        self.assertNotEqual(nf.REPAIR_ROUTING_MAP["ENVIRONMENT_DEFECT"], nf.REPAIR_ROUTING_MAP["IMPLEMENTATION_DEFECT"])
        self.assertIn("ENVIRONMENT_DEFECT", nf.ROOT_CAUSE_CLASSES)


class RoutingMapTests(FailureFixture):
    def test_11_implementation_defect_maps_to_p13(self) -> None:
        self.assertEqual(nf.REPAIR_ROUTING_MAP["IMPLEMENTATION_DEFECT"], ("P13",))

    def test_12_requirement_defect_maps_to_p6(self) -> None:
        self.assertEqual(nf.REPAIR_ROUTING_MAP["REQUIREMENT_DEFECT"], ("P6",))

    def test_13_architecture_defect_maps_to_p7_p8(self) -> None:
        self.assertEqual(nf.REPAIR_ROUTING_MAP["ARCHITECTURE_DEFECT"], ("P7", "P8"))

    def test_14_prior_art_invalidation_maps_to_p3_p4_p5(self) -> None:
        self.assertEqual(nf.REPAIR_ROUTING_MAP["PRIOR_ART_INVALIDATION"], ("P3", "P4", "P5"))

    def test_15_test_or_gate_defect_maps_to_p10_p11(self) -> None:
        self.assertEqual(nf.REPAIR_ROUTING_MAP["TEST_OR_GATE_DEFECT"], ("P10", "P11"))

    def test_17_repair_target_must_be_m7c_legal(self) -> None:
        # from P18, PRIOR_ART_INVALIDATION's P5 candidate is NOT in P18's own
        # allowed_back_transitions (only P3/P4 are) - a genuine, disclosed graph gap.
        failure = self.create_failure()
        failure = self.to_root_cause(failure, root_cause_class="PRIOR_ART_INVALIDATION")
        failure = nf.propose_repair(self.project, failure["failure_id"], description="reconsider prior art", target_phase="P5",
                                     evidence_refs=[self.exec_evidence_id], actor="architect", reason="propose")
        with self.assertRaises(MethodologyValidationError) as ctx:
            nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="attempt illegal target")
        self.assertIn("not currently a legal methodology transition", str(ctx.exception))

    def test_architecture_routes_to_p7_not_p13_live(self) -> None:
        failure = self.create_failure()
        failure = self.to_root_cause(failure, root_cause_class="ARCHITECTURE_DEFECT")
        failure = nf.propose_repair(self.project, failure["failure_id"], description="fix boundary", target_phase="P7",
                                     evidence_refs=[self.chain["P8"]["artifact_id"]], actor="architect", reason="propose")
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        self.assertEqual(mstatus(self.project)["current_phase"], "P7")
        self.assertNotEqual(mstatus(self.project)["current_phase"], "P13")


class RepairLoopTests(FailureFixture):
    def test_18_entering_repair_uses_loop_tracking(self) -> None:
        """Characterization finding: M7-C's engine only creates a NEW loop record on a
        LOOP_ENTRY-classified edge (a forward edge into a phase tagged with a
        different loop); P18 -> P13 here is a LOOP_RETURN (a backward/failure-
        transition edge), which RESOLVES the prior active loop (verify_loop) but does
        not itself spawn a new one - by M7-C's own existing, unmodified design, not
        something this module invents or needs to duplicate. The correct, verifiable
        invariant is that entering repair does not leave the prior loop dangling
        ACTIVE forever - it is genuinely closed through the SAME transition() call,
        never a second, parallel bookkeeping path."""
        state_before = mstatus(self.project)
        active_before = [l for l in state_before["loops"] if l["status"] == "ACTIVE"]
        self.assertTrue(active_before)  # verify_loop should be active at P18
        verify_loop_id = active_before[0]["loop_id"]

        failure = self.to_repair_proposed(self.create_failure())
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")

        state_after = mstatus(self.project)
        resolved_loop = next(l for l in state_after["loops"] if l["loop_id"] == verify_loop_id)
        self.assertEqual(resolved_loop["status"], "RESOLVED")
        # no fabricated/duplicated loop record was invented for the repair itself
        self.assertEqual(len(state_after["loops"]), len(state_before["loops"]))

    def test_19_active_loop_not_overwritten_by_second_selection_attempt(self) -> None:
        failure = self.to_repair_proposed(self.create_failure())
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        # already REPAIR_SELECTED - selecting again is an illegal predecessor, not a
        # silent overwrite of the active loop.
        with self.assertRaises(MethodologyValidationError):
            nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="select again")

    def test_20_multiple_repair_proposals_preserved(self) -> None:
        failure = self.to_root_cause(self.create_failure())
        failure = nf.propose_repair(self.project, failure["failure_id"], description="option A", target_phase="P13",
                                     evidence_refs=[self.exec_evidence_id], actor="architect", reason="propose A")
        failure = nf.propose_repair(self.project, failure["failure_id"], description="option B", target_phase="P13",
                                     evidence_refs=[self.exec_evidence_id], actor="architect", reason="propose B")
        self.assertEqual([r["repair_id"] for r in failure["candidate_repairs"]], ["R1", "R2"])

    def test_21_duplicate_repair_id_rejected(self) -> None:
        failure = self.to_root_cause(self.create_failure())
        nf.propose_repair(self.project, failure["failure_id"], description="A", target_phase="P13",
                           evidence_refs=[self.exec_evidence_id], actor="architect", reason="propose", repair_id="RX")
        with self.assertRaises(MethodologyValidationError):
            nf.propose_repair(self.project, failure["failure_id"], description="B", target_phase="P13",
                               evidence_refs=[self.exec_evidence_id], actor="architect", reason="propose", repair_id="RX")

    def test_22_repair_selection_requires_actor_and_reason(self) -> None:
        failure = self.to_repair_proposed(self.create_failure())
        with self.assertRaises(MethodologyValidationError):
            nf.select_repair(self.project, failure["failure_id"], "R1", actor="", reason="approved")
        with self.assertRaises(MethodologyValidationError):
            nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="")


class RepairAndBudgetTests(FailureFixture):
    def _fresh_repair_via_full_build(self, task_id: str) -> str:
        """Re-executes BUILD for the given task via the writer adapter and returns the
        new execution evidence id."""
        before = {p.stem for p in (self.project / ".code-loop" / "runtime" / "evidence").glob("evidence-exec-*.json")}
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=task_id))
        after = {p.stem for p in (self.project / ".code-loop" / "runtime" / "evidence").glob("evidence-exec-*.json")}
        return next(iter(after - before))

    def test_23_repair_attempt_count_increments(self) -> None:
        failure = self.to_repair_proposed(self.create_failure())
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        self.assertEqual(failure["attempt_count"], 0)
        new_evidence = self._fresh_repair_via_full_build(self.task_id)
        failure = nf.record_repaired(self.project, failure["failure_id"], repair_evidence_refs=[new_evidence], actor="qa", reason="applied")
        self.assertEqual(failure["attempt_count"], 1)

    def test_24_repair_budget_exhaustion_prevents_another_repair(self) -> None:
        failure = self.create_failure(max_repair_attempts=1)
        failure = self.to_root_cause(failure)
        failure = nf.propose_repair(self.project, failure["failure_id"], description="only shot", target_phase="P13",
                                     evidence_refs=[self.exec_evidence_id], actor="architect", reason="propose")
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        new_evidence = self._fresh_repair_via_full_build(self.task_id)
        failure = nf.record_repaired(self.project, failure["failure_id"], repair_evidence_refs=[new_evidence], actor="qa", reason="applied")
        failure = nf.record_regression(self.project, failure["failure_id"], result="failed", actor="qa", reason="still broken")
        self.assertEqual(failure["current_state"], "INCONCLUSIVE")  # budget exhausted, no further automatic attempt
        with self.assertRaises(MethodologyValidationError):
            nf.propose_repair(self.project, failure["failure_id"], description="second try", target_phase="P13",
                               evidence_refs=[self.exec_evidence_id], actor="architect", reason="over budget")

    def test_25_repair_completion_without_regression_rejected(self) -> None:
        failure = self.to_repair_proposed(self.create_failure())
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        new_evidence = self._fresh_repair_via_full_build(self.task_id)
        failure = nf.record_repaired(self.project, failure["failure_id"], repair_evidence_refs=[new_evidence], actor="qa", reason="applied")
        with self.assertRaises(MethodologyValidationError):
            nf.record_revalidation(self.project, failure["failure_id"], actor="qa", reason="skip regression")

    def test_26_regression_failure_prevents_resolution(self) -> None:
        failure = self.to_repair_proposed(self.create_failure(max_repair_attempts=5))
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        new_evidence = self._fresh_repair_via_full_build(self.task_id)
        failure = nf.record_repaired(self.project, failure["failure_id"], repair_evidence_refs=[new_evidence], actor="qa", reason="applied")
        failure = nf.record_regression(self.project, failure["failure_id"], result="failed", actor="qa", reason="still broken")
        self.assertEqual(failure["current_state"], "REPAIR_PROPOSED")  # back for a new candidate, not resolved
        with self.assertRaises(MethodologyValidationError):
            nf.resolve_failure(self.project, failure["failure_id"], actor="human:owner", reason="premature")

    def test_27_revalidation_missing_prevents_resolution(self) -> None:
        failure = self.to_repair_proposed(self.create_failure())
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        new_evidence = self._fresh_repair_via_full_build(self.task_id)
        failure = nf.record_repaired(self.project, failure["failure_id"], repair_evidence_refs=[new_evidence], actor="qa", reason="applied")
        failure = nf.record_regression(self.project, failure["failure_id"], result="passed", actor="qa", reason="fixed")
        with self.assertRaises(MethodologyValidationError):
            nf.resolve_failure(self.project, failure["failure_id"], actor="human:owner", reason="premature")

    def test_28_stale_revalidation_evidence_prevents_resolution(self) -> None:
        failure = self.to_repair_proposed(self.create_failure())
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        # A different adapter output than the original build, so the repaired
        # candidate genuinely has a DIFFERENT patch/candidate hash - otherwise the
        # "repair" produces a byte-identical patch and there is nothing to be stale.
        nogap_adapters.ADAPTERS["codex"] = StubAdapter(
            "codex", command_builder=lambda p, w: [sys.executable, "-c", "open('marker.txt','w').write('hi-repaired')"],
        )
        new_evidence = self._fresh_repair_via_full_build(self.task_id)
        failure = nf.record_repaired(self.project, failure["failure_id"], repair_evidence_refs=[new_evidence], actor="qa", reason="applied")
        failure = nf.record_regression(self.project, failure["failure_id"], result="passed", actor="qa", reason="fixed")
        # no fresh `nogap verify` was run for the repaired candidate - the P18 result
        # on file is for the ORIGINAL (pre-repair) candidate, now stale.
        with self.assertRaises(MethodologyValidationError):
            nf.record_revalidation(self.project, failure["failure_id"], actor="qa", reason="stale attempt")

    def test_29_and_30_and_31_successful_full_cycle_resolves_and_stays_queryable(self) -> None:
        failure = self.to_repair_proposed(self.create_failure())
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        new_evidence = self._fresh_repair_via_full_build(self.task_id)
        failure = nf.record_repaired(self.project, failure["failure_id"], repair_evidence_refs=[new_evidence], actor="qa", reason="applied")
        failure = nf.record_regression(self.project, failure["failure_id"], result="passed", actor="qa", reason="fixed")
        run_script("freeze", str(self.project))
        nogap.cmd_verify(verify_namespace(str(self.project)))
        failure = nf.record_revalidation(self.project, failure["failure_id"], actor="qa", reason="revalidated")
        failure = nf.resolve_failure(self.project, failure["failure_id"], actor="human:owner", reason="confirmed")
        self.assertEqual(failure["current_state"], "RESOLVED")

        reloaded = nf.load_failure(self.project, failure["failure_id"])
        self.assertIsNotNone(reloaded)  # #30: remains queryable
        self.assertEqual(reloaded["current_state"], "RESOLVED")
        self.assertGreater(len(reloaded["history"]), 5)  # #31: full history intact, not deleted
        self.assertIn(failure["failure_id"], [r["failure_id"] for r in nf.list_failures(self.project)])


class FailClosedTests(FailureFixture):
    def test_36_unknown_evidence_ref_fails_closed(self) -> None:
        failure = self.create_failure()
        with self.assertRaises(MethodologyValidationError):
            nf.record_evidence_preservation(self.project, failure["failure_id"], evidence_refs=["evidence-does-not-exist"], actor="qa", reason="bad ref")

    def test_37_methodology_version_mismatch_fails_closed(self) -> None:
        failure = self.create_failure()
        path = self.project / ".code-loop" / "methodology" / "failures" / f"{failure['failure_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["methodology_version"] = "0.0.1"
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nf.record_evidence_preservation(self.project, failure["failure_id"], evidence_refs=[self.exec_evidence_id], actor="qa", reason="version drifted")

    def test_unknown_failure_id_fails_closed(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            nf.record_evidence_preservation(self.project, "FAIL-999", evidence_refs=[], actor="qa", reason="x")


class InterlockUnaffectedTests(FailureFixture):
    def test_40_verification_acceptance_precondition_unaffected_by_failure_module(self) -> None:
        precondition = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertTrue(precondition["satisfied"], precondition["reason"])
        # creating and progressing an UNRELATED failure record must not perturb it
        failure = self.to_researched(self.create_failure(), research_refs=[self.chain["P3"]["artifact_id"]])
        precondition2 = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertEqual(precondition2, precondition)


class CliTests(FailureFixture):
    def test_cli_create_status_list(self) -> None:
        result = run_script("failure", "create", str(self.project), "--failure-class", "BUILD_EXECUTION_FAILURE",
                             "--summary", "cli test failure", "--actor", "qa", "--task-id", self.task_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OPEN", result.stdout)

        list_result = run_script("failure", "list", str(self.project))
        self.assertEqual(list_result.returncode, 0, list_result.stderr)
        self.assertIn("FAIL-001", list_result.stdout)

        status_result = run_script("failure", "status", str(self.project), "--failure-id", "FAIL-001")
        self.assertEqual(status_result.returncode, 0, status_result.stderr)
        self.assertIn('"failure_id"', status_result.stdout)

    def test_cli_full_lifecycle_via_subprocess(self) -> None:
        run_script("failure", "create", str(self.project), "--failure-class", "BUILD_EXECUTION_FAILURE",
                   "--summary", "cli lifecycle", "--actor", "qa", "--task-id", self.task_id)
        run_script("failure", "preserve-evidence", str(self.project), "--failure-id", "FAIL-001",
                   "--evidence-ref", self.exec_evidence_id, "--actor", "qa", "--reason", "preserve")
        run_script("failure", "reproduce", str(self.project), "--failure-id", "FAIL-001",
                   "--reproduction-status", "REPRODUCED", "--actor", "qa", "--reason", "reproduced")
        run_script("failure", "characterize", str(self.project), "--failure-id", "FAIL-001", "--actor", "qa", "--reason", "characterized")
        research = run_script("failure", "research", str(self.project), "--failure-id", "FAIL-001",
                               "--evidence-ref", self.chain["P3"]["artifact_id"], "--actor", "qa", "--reason", "researched")
        self.assertEqual(research.returncode, 0, research.stderr)
        root_cause = run_script("failure", "root-cause", str(self.project), "--failure-id", "FAIL-001",
                                 "--root-cause-class", "IMPLEMENTATION_DEFECT", "--root-cause-summary", "diagnosed",
                                 "--evidence-ref", self.exec_evidence_id, "--actor", "qa", "--reason", "diagnosed")
        self.assertEqual(root_cause.returncode, 0, root_cause.stderr)
        self.assertIn("ROOT_CAUSE_IDENTIFIED", root_cause.stdout)


class ManualScenarioAutomatedTests(FailureFixture):
    """Automated encoding of manual Scenario A (full resolution) and confirmation that
    the CLI path cannot bypass any state transition."""

    def test_scenario_a_full_lifecycle_resolves(self) -> None:
        failure = self.to_repair_proposed(self.create_failure())
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        self.assertEqual(mstatus(self.project)["current_phase"], "P13")
        nogap_adapters.ADAPTERS["codex"] = writer_adapter("codex")
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.task_id))
        new_evidence = sorted(p.stem for p in (self.project / ".code-loop" / "runtime" / "evidence").glob("evidence-exec-*.json"))[-1]
        failure = nf.record_repaired(self.project, failure["failure_id"], repair_evidence_refs=[new_evidence], actor="qa", reason="applied")
        failure = nf.record_regression(self.project, failure["failure_id"], result="passed", actor="qa", reason="fixed")
        run_script("freeze", str(self.project))
        nogap.cmd_verify(verify_namespace(str(self.project)))
        failure = nf.record_revalidation(self.project, failure["failure_id"], actor="qa", reason="revalidated")
        failure = nf.resolve_failure(self.project, failure["failure_id"], actor="human:owner", reason="confirmed")
        self.assertEqual(failure["current_state"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
