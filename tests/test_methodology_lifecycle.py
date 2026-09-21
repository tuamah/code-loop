#!/usr/bin/env python3
"""M7-K acceptance checks: Release / Operate / Evolve (P19-P23).

Covers the mandatory invariants from the brief (optimizing for invariant coverage,
not an exact test count) plus automated encodings of the 10 mandatory scenarios
(A-J) and a single-owner-selector regression class mirroring the M7-J review fix.
M6/M7-A..J regression coverage is verified by running the full existing suites
alongside this file, not duplicated here except for a few direct cross-module
sanity checks.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap  # noqa: E402
import nogap_adapters  # noqa: E402
import nogap_failure as nf  # noqa: E402
import nogap_lifecycle as nlc  # noqa: E402
from nogap_artifacts import create_artifact  # noqa: E402
from nogap_methodology import (  # noqa: E402
    MethodologyValidationError,
    init_project,
    status as mstatus,
    transition,
)


@dataclasses.dataclass
class StubAdapter:
    id: str
    ready: bool = True
    kind: str = "AgentRuntime"
    command_builder: Any = None

    def health(self) -> dict[str, Any]:
        return {"status": "connected", "trust_status": "READY"}

    def capabilities(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "can_execute": False, "supported_operations": []}

    def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
        if self.command_builder:
            return self.command_builder(prompt, worktree)
        return [sys.executable, "-c", "open('marker.txt','w').write('hi')"]


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


def run_namespace(path: str, **overrides: Any) -> Any:
    import argparse
    defaults = {"path": path, "actor": "test-lifecycle", "execute": False, "execute_timeout": 600, "task_id": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def verify_namespace(path: str, **overrides: Any) -> Any:
    import argparse
    defaults = {"path": path, "dispatch": None, "timeout": 120, "review": False, "review_timeout": 120, "actor": "verifier"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def decide_namespace(path: str, **overrides: Any) -> Any:
    import argparse
    defaults = {"path": path, "actor": "nogap decide", "actor_id": "human:owner", "authority": "acceptance"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "scripts/nogap.py", *args], cwd=ROOT, text=True, capture_output=True)


def review_adapter(adapter_id: str, verdict: str = "pass") -> StubAdapter:
    """Reuses the exact deterministic reviewer pattern already established in
    tests/test_methodology_decide_interlock.py - a stub AgentRuntime that writes a
    real, structured .nogap-review.json verdict M6-D's own review layer parses, so
    STANDARD/STRICT profile tests can reach a genuine independent-review PASS
    without needing any change to production code."""
    payload = json.dumps({"verdict": verdict, "notes": "auto"})
    return StubAdapter(adapter_id, command_builder=lambda p, w: [sys.executable, "-c", f"open('.nogap-review.json','w').write({payload!r})"])


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
        "expected_cost": "medium", "architecture_refs": [made["P7"]["artifact_id"]], "vendor_lock_in": "none",
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


def make_task_contract(project: Path, chain: dict, actor: str = "architect") -> dict:
    fields = {
        "goal": "implement X", "scope": ["svc1"], "forbidden_scope": ["unrelated services"],
        "acceptance_criteria": ["X happens"], "planned_tests": ["unit"], "required_evidence": ["execution"],
        "stop_conditions": ["security fail"], "requirement_refs": [chain["P6"]["fields"]["requirement_id"]],
        "gate_plan_refs": [chain["P11"]["artifact_id"]],
    }
    return create_artifact(project, "P12_TASK_CONTRACT", fields, actor=actor)


class LifecycleFixture(unittest.TestCase):
    """Reaches P18 with an ACCEPTED decision on real M6 execution/verification
    evidence (LIGHT profile - the same reliable path every prior milestone's test
    suite in this repo uses to reach P18), ready to build P19-P23 lifecycle state on
    top of."""

    profile_args = ("research", "low", "low")  # LIGHT unless overridden

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        init_project(self.project, *self.profile_args, actor="test")
        self.chain = build_p0_p11_chain(self.project)
        self.contract = make_task_contract(self.project, self.chain)
        self.task_id = self.contract["fields"]["task_id"]
        run_script("init", str(self.project), "--objective", "lifecycle fixture")

        self._original_adapters = dict(nogap_adapters.ADAPTERS)
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = StubAdapter("codex")
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.task_id))
        run_script("freeze", str(self.project))
        nogap.cmd_verify(verify_namespace(str(self.project)))
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")
        self.exec_evidence_id = next((self.project / ".code-loop" / "runtime" / "evidence").glob("evidence-exec-*.json")).stem
        nogap.cmd_decide(decide_namespace(str(self.project)))
        self.accepted_decision_id = "decision-0001"

    def tearDown(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._original_adapters)
        self.tmp.cleanup()

    # --- DSL helpers -----------------------------------------------------------

    def make_candidate(self, **overrides: Any) -> dict[str, Any]:
        fields = dict(
            version="1.0.0", candidate_ref="rc-1.0.0", code_revision="abc123",
            included_task_refs=[self.task_id], included_requirement_refs=[self.chain["P6"]["fields"]["requirement_id"]],
            artifact_refs=[self.chain["P11"]["artifact_id"]], verification_refs=[self.exec_evidence_id],
            known_limitations=["minor polish deferred"], actor="release-manager", reason="assemble candidate",
        )
        fields.update(overrides)
        return nlc.create_release_candidate(self.project, **fields)

    def frozen_candidate(self, **overrides: Any) -> dict[str, Any]:
        candidate = self.make_candidate(**overrides)
        return nlc.freeze_release_candidate(self.project, candidate["release_candidate_id"], actor="release-manager", reason="freeze")

    def evaluate(self, candidate_id: str, **overrides: Any) -> dict[str, Any]:
        fields = dict(actor="release-manager", reason="evaluate readiness")
        fields.update(overrides)
        return nlc.evaluate_release_readiness(self.project, candidate_id, **fields)

    def make_deployment(self, candidate_id: str, readiness_id: str, **overrides: Any) -> dict[str, Any]:
        fields = dict(
            release_candidate_id=candidate_id, readiness_id=readiness_id, environment="production",
            deployment_target="k8s", decision_refs=[self.accepted_decision_id], actor="release-manager", reason="deploy",
        )
        fields.update(overrides)
        return nlc.create_deployment(self.project, **fields)

    def succeed(self, deployment_id: str, **overrides: Any) -> dict[str, Any]:
        fields = dict(status="SUCCEEDED", actor="release-manager", reason="deploy completed")
        fields.update(overrides)
        return nlc.record_deployment_result(self.project, deployment_id, **fields)

    def observe(self, deployment_id: str, metric_name: str, value: float, **overrides: Any) -> dict[str, Any]:
        fields = dict(deployment_id=deployment_id, signal_type="metric", metric_name=metric_name, metric_value=value,
                      actor="operator", reason="record telemetry")
        fields.update(overrides)
        return nlc.record_operational_observation(self.project, **fields)

    def full_clean_release(self) -> dict[str, Any]:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        deployment = self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])
        deployment = self.succeed(deployment["deployment_id"])
        return {"candidate": rc, "readiness": readiness, "deployment": deployment}

    def _force_phase_p22(self) -> None:
        """Test-only helper: drives current_phase to P22 through the SAME sanctioned
        transition() API this module itself uses, purely to exercise
        reenter_for_improvement()/create_lifecycle_decision() without re-running the
        entire P19-P22 dance in every routing test. A no-op once already at/past P22."""
        state = mstatus(self.project)
        path = {"P18": "P19", "P19": "P20", "P20": "P21", "P21": "P22"}
        while state["current_phase"] in path:
            target = path[state["current_phase"]]
            transition(self.project, target, "test-harness", "force-advance for routing test",
                       artifact_refs=["test-artifact"], evidence_refs=[self.exec_evidence_id], authority_class="tool")
            state = mstatus(self.project)


class StandardProfileLifecycleFixture(LifecycleFixture):
    """Same P0-P18 progression as LifecycleFixture, but at STANDARD profile with a
    REAL independent-review PASS (via the deterministic review_adapter reused from
    tests/test_methodology_decide_interlock.py) - the actual, executable acceptance-
    critical boundary for 'STANDARD/STRICT deployment requires a resolvable ACCEPT
    decision', never skipped."""

    profile_args = ("production", "medium", "low")  # STANDARD

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        init_project(self.project, *self.profile_args, actor="test")
        p7_extra = {"responsibilities": ["r"], "interfaces": ["i"], "external_dependencies": ["d"]}
        if self.profile_args[1] == "high" and self.profile_args[2] == "high":  # STRICT needs additional P7 fields
            p7_extra.update({"failure_domains": ["fd1"], "data_security_boundaries": ["dsb1"]})
        self.chain = build_p0_p11_chain(self.project, p7_extra=p7_extra)
        self.contract = make_task_contract(self.project, self.chain)
        self.task_id = self.contract["fields"]["task_id"]
        run_script("init", str(self.project), "--objective", "standard lifecycle fixture")

        self._original_adapters = dict(nogap_adapters.ADAPTERS)
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = StubAdapter("codex")
        nogap_adapters.ADAPTERS["claude"] = review_adapter("claude", "pass")
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.task_id))
        run_script("freeze", str(self.project))
        nogap.cmd_verify(verify_namespace(str(self.project), review=True))
        result_path = next((self.project / ".code-loop" / "methodology" / "artifacts").glob("p18_verification_result-*.json"))
        self.verification_status = json.loads(result_path.read_text(encoding="utf-8"))["status"]
        if self.profile_args[1:] == ("medium", "low"):  # STANDARD: external validation is not required, so this always reaches COMPLETE
            self.assertEqual(mstatus(self.project)["current_phase"], "P18")
            self.assertEqual(self.verification_status, "VERIFICATION_COMPLETE_AWAITING_DECISION")
        # STRICT genuinely cannot reach COMPLETE in this codebase today - external
        # validation is required but no such mechanism is configured anywhere
        # (nogap_verify_binding.evaluate_reproducibility's own disclosed, honest
        # INCONCLUSIVE - never a fabricated pass). That is an existing, disclosed M7-G
        # limitation this fixture does not attempt to route around.
        self.exec_evidence_id = next((self.project / ".code-loop" / "runtime" / "evidence").glob("evidence-exec-*.json")).stem

    def tearDown(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._original_adapters)
        self.tmp.cleanup()

    def accept_decision(self) -> str:
        nogap.cmd_decide(decide_namespace(str(self.project)))
        decision = json.loads((self.project / ".code-loop" / "runtime" / "decisions" / "decision-0001.json").read_text(encoding="utf-8"))
        self.assertEqual(decision["decision"], "accept", decision.get("reason"))
        return "decision-0001"

    def make_candidate(self, **overrides: Any) -> dict[str, Any]:
        fields = dict(
            version="1.0.0", candidate_ref="rc-1.0.0", code_revision="abc123",
            included_task_refs=[self.task_id], included_requirement_refs=[self.chain["P6"]["fields"]["requirement_id"]],
            artifact_refs=[self.chain["P11"]["artifact_id"]], verification_refs=[self.exec_evidence_id],
            actor="release-manager", reason="assemble candidate",
        )
        fields.update(overrides)
        return nlc.create_release_candidate(self.project, **fields)

    def frozen_candidate(self, **overrides: Any) -> dict[str, Any]:
        candidate = self.make_candidate(**overrides)
        return nlc.freeze_release_candidate(self.project, candidate["release_candidate_id"], actor="release-manager", reason="freeze")

    def evaluate(self, candidate_id: str, **overrides: Any) -> dict[str, Any]:
        fields = dict(actor="release-manager", reason="evaluate readiness")
        fields.update(overrides)
        return nlc.evaluate_release_readiness(self.project, candidate_id, **fields)


class StrictProfileLifecycleFixture(StandardProfileLifecycleFixture):
    profile_args = ("production", "high", "high")  # STRICT


# --- P19: ReleaseCandidate --------------------------------------------------------

class ReleaseCandidateTests(LifecycleFixture):
    def test_1_create_release_candidate(self) -> None:
        rc = self.make_candidate()
        self.assertEqual(rc["status"], "DRAFT")
        self.assertEqual(rc["release_candidate_id"], "RC-001")

    def test_2_duplicate_release_candidate_rejected(self) -> None:
        self.make_candidate(release_candidate_id="RC-X")
        with self.assertRaises(MethodologyValidationError):
            self.make_candidate(release_candidate_id="RC-X")

    def test_3_4_5_stable_and_content_sensitive_fingerprint(self) -> None:
        fp1 = nlc.compute_candidate_fingerprint("rev1", {"a": "hash1"}, ["T1"], ["REQ-1"], ["ev-1"])
        fp2 = nlc.compute_candidate_fingerprint("rev1", {"a": "hash1"}, ["T1"], ["REQ-1"], ["ev-1"])
        self.assertEqual(fp1, fp2)  # same logical inputs -> same fingerprint
        fp3 = nlc.compute_candidate_fingerprint("rev2", {"a": "hash1"}, ["T1"], ["REQ-1"], ["ev-1"])
        self.assertNotEqual(fp1, fp3)  # changed material input -> different fingerprint

    def test_6_freeze_valid_candidate(self) -> None:
        rc = self.frozen_candidate()
        self.assertEqual(rc["status"], "FROZEN")
        self.assertIsNotNone(rc["candidate_fingerprint"])

    def test_7_freeze_records_actor_reason(self) -> None:
        rc = self.frozen_candidate()
        self.assertEqual(rc["freeze_record"]["actor_id"], "release-manager")
        self.assertEqual(rc["freeze_record"]["reason"], "freeze")

    def test_8_frozen_candidate_critical_fields_immutable_via_api(self) -> None:
        rc = self.frozen_candidate()
        self.assertFalse(hasattr(nlc, "update_release_candidate"))
        self.assertFalse(hasattr(nlc, "set_candidate_field"))

    def test_9_successor_candidate_preserves_old_candidate(self) -> None:
        rc1 = self.frozen_candidate()
        rc2 = self.frozen_candidate(candidate_ref="rc-1.0.1")
        nlc.mark_superseded(self.project, "release_candidates", rc1["release_candidate_id"], superseded_by=rc2["release_candidate_id"], actor="a", reason="new candidate")
        reloaded = nlc.load_release_candidate(self.project, rc1["release_candidate_id"])
        self.assertEqual(reloaded["status"], "SUPERSEDED")
        self.assertEqual(reloaded["version"], "1.0.0")  # untouched

    def test_10_invalidation_preserves_history(self) -> None:
        rc = self.make_candidate()
        invalidated = nlc.invalidate_release_candidate(self.project, rc["release_candidate_id"], actor="a", reason="bad candidate")
        self.assertEqual(invalidated["status"], "INVALIDATED")
        self.assertGreaterEqual(len(invalidated["history"]), 2)

    def test_11_superseded_candidate_remains_queryable(self) -> None:
        rc1 = self.frozen_candidate()
        rc2 = self.frozen_candidate(candidate_ref="rc-1.0.1")
        nlc.mark_superseded(self.project, "release_candidates", rc1["release_candidate_id"], superseded_by=rc2["release_candidate_id"], actor="a", reason="new")
        self.assertIsNotNone(nlc.load_release_candidate(self.project, rc1["release_candidate_id"]))

    def test_12_filesystem_order_cannot_select_current_candidate(self) -> None:
        self.frozen_candidate(release_candidate_id="RC-999")
        second = self.frozen_candidate(release_candidate_id="RC-001B", candidate_ref="rc-1.0.1")
        current = nlc.get_current_release_candidate(self.project)
        self.assertEqual(current["candidate"]["release_candidate_id"], second["release_candidate_id"])

    def test_13_unresolved_current_candidate_conflict_fails_closed(self) -> None:
        rc1 = self.frozen_candidate(release_candidate_id="RC-A")
        rc2 = self.frozen_candidate(release_candidate_id="RC-B", candidate_ref="rc-1.0.1")
        path_b = nlc.lifecycle_dir(self.project) / "release_candidates" / "RC-B.json"
        record_b = json.loads(path_b.read_text(encoding="utf-8"))
        record_b["sequence"] = rc1["sequence"]
        path_b.write_text(json.dumps(record_b), encoding="utf-8")
        current = nlc.get_current_release_candidate(self.project)
        self.assertEqual(current["status"], "CONFLICT")

    def test_14_15_16_17_candidate_carries_known_issues(self) -> None:
        rc = self.make_candidate(known_failures=["FAIL-999"], known_limitations=["no dark mode"], known_risks=["untested edge case"])
        self.assertEqual(rc["known_failures"], ["FAIL-999"])
        self.assertEqual(rc["known_limitations"], ["no dark mode"])
        self.assertEqual(rc["known_risks"], ["untested edge case"])
        self.assertEqual(rc["verification_refs"], [self.exec_evidence_id])

    def test_18_freeze_does_not_mutate_current_phase_directly(self) -> None:
        import inspect
        import re
        source = inspect.getsource(nlc)
        # excludes '==' comparisons (state["current_phase"] == "P18") - only a real
        # assignment (single '=' not followed by another '=') would match
        self.assertIsNone(re.search(r'current_phase"\]\s*=(?!=)', source))


# --- P20: Readiness ----------------------------------------------------------------

class ReadinessTests(LifecycleFixture):
    def test_19_create_evaluate_readiness(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertIn(readiness["readiness_outcome"], nlc.READINESS_OUTCOMES)

    def test_20_duplicate_readiness_id_rejected(self) -> None:
        rc = self.frozen_candidate()
        self.evaluate(rc["release_candidate_id"], readiness_id="RDY-X")
        with self.assertRaises(MethodologyValidationError):
            self.evaluate(rc["release_candidate_id"], readiness_id="RDY-X")

    def test_21_readiness_requires_frozen_candidate(self) -> None:
        rc = self.make_candidate()  # DRAFT, never frozen
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["readiness_outcome"], "NOT_READY")
        self.assertTrue(readiness["blocking_reasons"])

    def test_22_candidate_drift_yields_stale(self) -> None:
        rc = self.frozen_candidate()
        art_path = self.project / ".code-loop" / "methodology" / "artifacts" / f"{self.chain['P11']['artifact_id']}.json"
        record = json.loads(art_path.read_text(encoding="utf-8"))
        record["fields"]["gate_id"] = "MUTATED"
        art_path.write_text(json.dumps(record), encoding="utf-8")
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["readiness_outcome"], "STALE")

    def test_23_missing_mandatory_verification_blocks_ready(self) -> None:
        # LIGHT profile (this fixture) - proves LIGHT is NOT exempt from minimum
        # P15/P16 verification (Blocker 1): a candidate referencing a task that was
        # never verified at all must not reach READY_FOR_DECISION even at LIGHT.
        rc = self.frozen_candidate(included_task_refs=["TASK-NEVER-VERIFIED"])
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["readiness_outcome"], "NOT_READY")
        self.assertTrue(any("TASK-NEVER-VERIFIED" in r for r in readiness["blocking_reasons"]))

    def test_25_blocking_reasons_present_when_not_ready(self) -> None:
        rc = self.make_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertTrue(readiness["blocking_reasons"])

    def test_29_light_avoids_unnecessary_strict_burden(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])  # no rollback/observability plan supplied
        self.assertEqual(readiness["readiness_outcome"], "READY_FOR_DECISION")


    def test_31_32_33_34_outcomes_preserved(self) -> None:
        rc = self.frozen_candidate()
        ready = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(ready["readiness_outcome"], "READY_FOR_DECISION")
        rc2 = self.make_candidate(candidate_ref="rc2")  # not frozen -> NOT_READY
        not_ready = self.evaluate(rc2["release_candidate_id"])
        self.assertEqual(not_ready["readiness_outcome"], "NOT_READY")

    def test_35_ready_for_decision_does_not_create_accept(self) -> None:
        decisions_dir = self.project / ".code-loop" / "runtime" / "decisions"
        before = {p: p.read_text(encoding="utf-8") for p in decisions_dir.glob("*.json")}
        rc = self.frozen_candidate()
        self.evaluate(rc["release_candidate_id"])
        after = {p: p.read_text(encoding="utf-8") for p in decisions_dir.glob("*.json")}
        self.assertEqual(before, after)  # decision ledger untouched by readiness evaluation

    def test_38_readiness_history_preserved(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["history"][0]["action"], "EVALUATED")

    def test_39_current_readiness_selection_deterministic(self) -> None:
        rc = self.frozen_candidate()
        self.evaluate(rc["release_candidate_id"], readiness_id="RDY-999")
        second = self.evaluate(rc["release_candidate_id"], readiness_id="RDY-001B")
        current = nlc.get_current_release_readiness(self.project, rc["release_candidate_id"])
        self.assertEqual(current["readiness"]["readiness_id"], second["readiness_id"])

    def test_40_conflicting_readiness_fails_closed(self) -> None:
        rc = self.frozen_candidate()
        first = self.evaluate(rc["release_candidate_id"], readiness_id="RDY-A")
        second = self.evaluate(rc["release_candidate_id"], readiness_id="RDY-B")
        path_b = nlc.lifecycle_dir(self.project) / "release_readiness" / "RDY-B.json"
        record_b = json.loads(path_b.read_text(encoding="utf-8"))
        record_b["sequence"] = first["sequence"]
        path_b.write_text(json.dumps(record_b), encoding="utf-8")
        current = nlc.get_current_release_readiness(self.project, rc["release_candidate_id"])
        self.assertEqual(current["status"], "CONFLICT")


# --- Deployment ----------------------------------------------------------------

class DeploymentTests(LifecycleFixture):
    def test_41_create_deployment(self) -> None:
        result = self.full_clean_release()
        self.assertEqual(result["deployment"]["status"], "SUCCEEDED")

    def test_42_duplicate_deployment_id_rejected(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"], deployment_id="DEPLOY-X")
        with self.assertRaises(MethodologyValidationError):
            self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"], deployment_id="DEPLOY-X")

    def test_43_unknown_candidate_rejected(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            nlc.create_deployment(self.project, release_candidate_id="RC-999", readiness_id="RDY-999",
                                   environment="prod", deployment_target="k8s", actor="a", reason="r")

    def test_44_unknown_readiness_rejected(self) -> None:
        rc = self.frozen_candidate()
        with self.assertRaises(MethodologyValidationError):
            self.make_deployment(rc["release_candidate_id"], "RDY-999")

    def test_45_fingerprint_mismatch_rejected(self) -> None:
        rc1 = self.frozen_candidate()
        rc2 = self.frozen_candidate(candidate_ref="rc-1.0.1")
        readiness_for_rc1 = self.evaluate(rc1["release_candidate_id"])
        # readiness belongs to rc1, but we try to deploy rc2 against it - blocked by
        # the release_candidate_id ownership check before fingerprint is even compared
        with self.assertRaises(MethodologyValidationError):
            self.make_deployment(rc2["release_candidate_id"], readiness_for_rc1["readiness_id"])

    def test_46_stale_candidate_rejected(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        art_path = self.project / ".code-loop" / "methodology" / "artifacts" / f"{self.chain['P11']['artifact_id']}.json"
        record = json.loads(art_path.read_text(encoding="utf-8"))
        record["fields"]["gate_id"] = "MUTATED"
        art_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])

    def test_48_decision_ref_preserved(self) -> None:
        result = self.full_clean_release()
        self.assertEqual(result["deployment"]["decision_refs"], [self.accepted_decision_id])

    def test_49_50_51_52_53_54_deployment_statuses_preserved(self) -> None:
        # SUCCEEDED tested last deliberately: it is the only status that triggers the
        # sanctioned P20->P21 transition, which would make P19 unreachable for
        # subsequent loop iterations' fresh candidates (P21's allowed_back_transitions
        # does not include P19) - ordering here is a test-harness concern only, not a
        # production behavior change.
        for status in ("STARTED", "FAILED", "ROLLED_BACK", "CANCELLED", "INCONCLUSIVE", "SUCCEEDED"):
            rc = self.frozen_candidate(candidate_ref=f"rc-{status}")
            readiness = self.evaluate(rc["release_candidate_id"])
            deployment = self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])
            if status == "STARTED":
                result = nlc.record_deployment_result(self.project, deployment["deployment_id"], status="STARTED", actor="a", reason="starting")
            else:
                result = nlc.record_deployment_result(self.project, deployment["deployment_id"], status=status, actor="a", reason="result")
            self.assertEqual(result["status"], status)

    def test_55_process_success_does_not_imply_production_health(self) -> None:
        result = self.full_clean_release()
        health = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"])
        self.assertEqual(health["status"], "UNKNOWN")
        self.assertNotEqual(health["status"], "HEALTHY")

    def test_56_deployment_history_append_oriented(self) -> None:
        result = self.full_clean_release()
        deployment = nlc.load_deployment(self.project, result["deployment"]["deployment_id"])
        self.assertEqual(deployment["history"][0]["action"], "CREATED")
        self.assertEqual(deployment["history"][-1]["action"], "RESULT_RECORDED")

    def test_57_rollback_does_not_erase_original_deployment(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        deployment = self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])
        rolled_back = nlc.record_deployment_result(self.project, deployment["deployment_id"], status="ROLLED_BACK", actor="a", reason="rollback")
        self.assertIsNotNone(nlc.load_deployment(self.project, deployment["deployment_id"]))
        self.assertEqual(rolled_back["status"], "ROLLED_BACK")
        self.assertIsNotNone(rolled_back["rollback_ref"])

    def test_58_deployment_does_not_mutate_decision_records(self) -> None:
        decisions_dir = self.project / ".code-loop" / "runtime" / "decisions"
        before = (decisions_dir / "decision-0001.json").read_text(encoding="utf-8")
        self.full_clean_release()
        after = (decisions_dir / "decision-0001.json").read_text(encoding="utf-8")
        self.assertEqual(before, after)


# --- P21: Operations ---------------------------------------------------------------

class OperationsTests(LifecycleFixture):
    def test_59_record_operational_observation(self) -> None:
        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "error_rate", 1.5)
        self.assertEqual(obs["metric_value"], 1.5)

    def test_60_duplicate_observation_rejected(self) -> None:
        result = self.full_clean_release()
        self.observe(result["deployment"]["deployment_id"], "error_rate", 1.5, observation_id="OPSOBS-X")
        with self.assertRaises(MethodologyValidationError):
            self.observe(result["deployment"]["deployment_id"], "error_rate", 2.0, observation_id="OPSOBS-X")

    def test_61_observation_linked_to_deployment(self) -> None:
        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "error_rate", 1.5)
        self.assertEqual(obs["deployment_id"], result["deployment"]["deployment_id"])

    def test_62_unknown_deployment_rejected(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            self.observe("DEPLOY-999", "error_rate", 1.5)

    def test_63_observation_separate_from_interpretation(self) -> None:
        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "error_rate", 4.2)
        self.assertNotIn("interpretation", obs)
        self.assertNotIn("health_verdict", obs)

    def test_64_operational_health_unknown_with_no_telemetry(self) -> None:
        result = self.full_clean_release()
        health = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"])
        self.assertEqual(health["status"], "UNKNOWN")

    def test_65_deployment_success_does_not_imply_healthy(self) -> None:
        result = self.full_clean_release()
        self.assertEqual(result["deployment"]["status"], "SUCCEEDED")
        health = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"])
        self.assertNotEqual(health["status"], "HEALTHY")

    def test_66_no_incident_does_not_imply_healthy(self) -> None:
        result = self.full_clean_release()
        self.assertEqual(nlc.list_incidents(self.project, deployment_id=result["deployment"]["deployment_id"]), [])
        health = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"])
        self.assertNotEqual(health["status"], "HEALTHY")

    def test_67_healthy_requires_actual_supporting_observation(self) -> None:
        result = self.full_clean_release()
        self.observe(result["deployment"]["deployment_id"], "error_rate", 0.1)
        health = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"], health_criteria=[
            {"metric_name": "error_rate", "comparator": "<=", "value": 5.0, "severity_if_fails": "UNHEALTHY"},
        ])
        self.assertEqual(health["status"], "HEALTHY")

    def test_68_69_70_degraded_unhealthy_inconclusive_preserved(self) -> None:
        result = self.full_clean_release()
        self.observe(result["deployment"]["deployment_id"], "error_rate", 8.0)
        degraded = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"], health_criteria=[
            {"metric_name": "error_rate", "comparator": "<=", "value": 5.0, "severity_if_fails": "DEGRADED"},
        ])
        self.assertEqual(degraded["status"], "DEGRADED")
        unhealthy = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"], health_criteria=[
            {"metric_name": "error_rate", "comparator": "<=", "value": 5.0, "severity_if_fails": "UNHEALTHY"},
        ])
        self.assertEqual(unhealthy["status"], "UNHEALTHY")
        inconclusive = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"], health_criteria=[
            {"metric_name": "no_such_metric", "comparator": "<=", "value": 5.0, "severity_if_fails": "UNHEALTHY"},
        ])
        self.assertEqual(inconclusive["status"], "INCONCLUSIVE")

    def test_71_operational_evidence_provenance_preserved(self) -> None:
        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "error_rate", 1.0, evidence_refs=[self.exec_evidence_id])
        self.assertEqual(obs["evidence_refs"], [self.exec_evidence_id])


# --- Incident ------------------------------------------------------------------------

class IncidentTests(LifecycleFixture):
    def test_72_create_incident(self) -> None:
        result = self.full_clean_release()
        inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="spike",
                                    severity="HIGH", actor="operator", reason="incident")
        self.assertEqual(inc["status"], "OPEN")

    def test_73_duplicate_incident_rejected(self) -> None:
        result = self.full_clean_release()
        nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s", severity="LOW",
                              actor="a", reason="r", incident_id="INC-X")
        with self.assertRaises(MethodologyValidationError):
            nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s2", severity="LOW",
                                  actor="a", reason="r", incident_id="INC-X")

    def test_74_incident_unknown_deployment_rejected(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            nlc.create_incident(self.project, deployment_id="DEPLOY-999", summary="s", severity="LOW", actor="a", reason="r")

    def test_75_incident_severity_preserved(self) -> None:
        result = self.full_clean_release()
        for severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s",
                                        severity=severity, actor="a", reason="r")
            self.assertEqual(inc["severity"], severity)

    def test_76_incident_history_append_oriented(self) -> None:
        result = self.full_clean_release()
        inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s", severity="LOW", actor="a", reason="r")
        triaged = nlc.set_incident_status(self.project, inc["incident_id"], "TRIAGED", actor="a", reason="triage")
        self.assertEqual(len(triaged["history"]), 2)

    def test_77_link_incident_to_failure(self) -> None:
        result = self.full_clean_release()
        inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s", severity="HIGH", actor="a", reason="r")
        failure = nf.create_failure(self.project, failure_class="PRODUCTION_INCIDENT", summary="s", actor="a", task_id=self.task_id)
        linked = nlc.link_incident_failure(self.project, inc["incident_id"], failure["failure_id"], actor="a", reason="link")
        self.assertEqual(linked["failure_ref"], failure["failure_id"])
        self.assertEqual(linked["status"], "LINKED_TO_FAILURE")

    def test_78_unknown_failure_ref_rejected(self) -> None:
        result = self.full_clean_release()
        inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s", severity="LOW", actor="a", reason="r")
        with self.assertRaises(MethodologyValidationError):
            nlc.link_incident_failure(self.project, inc["incident_id"], "FAIL-999", actor="a", reason="link")

    def test_79_incident_does_not_duplicate_repair_lifecycle(self) -> None:
        import inspect
        source = inspect.getsource(nlc)
        self.assertNotIn("record_root_cause", source)
        self.assertNotIn("propose_repair", source)
        self.assertNotIn("REPAIR_ROUTING_MAP", source)

    def test_80_unresolved_failure_not_silently_presented_as_repaired(self) -> None:
        result = self.full_clean_release()
        inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s", severity="HIGH", actor="a", reason="r")
        failure = nf.create_failure(self.project, failure_class="PRODUCTION_INCIDENT", summary="s", actor="a", task_id=self.task_id)
        nlc.link_incident_failure(self.project, inc["incident_id"], failure["failure_id"], actor="a", reason="link")
        with self.assertRaises(MethodologyValidationError):
            nlc.set_incident_status(self.project, inc["incident_id"], "RESOLVED", actor="a", reason="premature")

    def test_81_resolved_incident_history_preserved(self) -> None:
        result = self.full_clean_release()
        inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s", severity="LOW", actor="a", reason="r")
        resolved = nlc.set_incident_status(self.project, inc["incident_id"], "RESOLVED", actor="a", reason="no failure link needed")
        self.assertEqual(resolved["status"], "RESOLVED")
        self.assertGreaterEqual(len(resolved["history"]), 2)

    def test_82_incident_is_not_a_failure_record(self) -> None:
        result = self.full_clean_release()
        inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s", severity="LOW", actor="a", reason="r")
        self.assertNotIn("root_cause_class", inc)
        self.assertNotIn("repair_target_phase", inc)

    def test_83_incident_does_not_direct_mutate_current_phase(self) -> None:
        import inspect
        source = inspect.getsource(nlc.create_incident) + inspect.getsource(nlc.set_incident_status) + inspect.getsource(nlc.link_incident_failure)
        self.assertNotIn('current_phase"] =', source)


# --- P22: Improvement ----------------------------------------------------------------

class ImprovementTests(LifecycleFixture):
    def test_84_create_improvement(self) -> None:
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       actor="a", reason="r")
        self.assertEqual(imp["status"], "PROPOSED")

    def test_85_duplicate_improvement_rejected(self) -> None:
        nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                 actor="a", reason="r", improvement_id="IMP-X")
        with self.assertRaises(MethodologyValidationError):
            nlc.create_improvement(self.project, problem_or_opportunity="p2", proposed_change="c2", source_type="operational",
                                     actor="a", reason="r", improvement_id="IMP-X")

    def test_86_proposal_may_exist_before_strong_evidence(self) -> None:
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="hunch",
                                       actor="a", reason="r")
        self.assertEqual(imp["status"], "PROPOSED")  # no evidence refs at all - still legally exists

    def test_87_88_selected_requires_evidence_prose_alone_insufficient(self) -> None:
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="hunch",
                                       actor="a", reason="r")
        with self.assertRaises(MethodologyValidationError):
            nlc.select_improvement(self.project, imp["improvement_id"], actor="a", reason="select")

        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "latency_ms", 900)
        imp2 = nlc.create_improvement(self.project, problem_or_opportunity="latency high", proposed_change="add cache",
                                        source_type="operational", operation_refs=[obs["observation_id"]],
                                        evidence_refs=[self.exec_evidence_id], actor="a", reason="r")
        selected = nlc.select_improvement(self.project, imp2["improvement_id"], actor="a", reason="select")
        self.assertEqual(selected["status"], "SELECTED")

    def test_89_improvement_source_provenance_preserved(self) -> None:
        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "latency_ms", 900)
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       operation_refs=[obs["observation_id"]], actor="a", reason="r")
        self.assertEqual(imp["operation_refs"], [obs["observation_id"]])

    def test_90_requirement_improvement_routes_to_p6(self) -> None:
        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "latency_ms", 900)
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       category="REQUIREMENT", operation_refs=[obs["observation_id"]],
                                       evidence_refs=[self.exec_evidence_id], actor="a", reason="r")
        nlc.select_improvement(self.project, imp["improvement_id"], actor="a", reason="select")
        # move current_phase to P22's real predecessor via an explicit test transition (bypassing full P19-P22 flow for this unit test)
        self._force_phase_p22()
        reentered = nlc.reenter_for_improvement(self.project, imp["improvement_id"], "P6", actor="a", reason="reenter",
                                                  evidence_refs=[self.exec_evidence_id])
        self.assertEqual(reentered["status"], "REENTERED")
        self.assertEqual(mstatus(self.project)["current_phase"], "P6")

    def test_91_architecture_improvement_routes_to_p7(self) -> None:
        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "latency_ms", 900)
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       category="ARCHITECTURE", operation_refs=[obs["observation_id"]],
                                       evidence_refs=[self.exec_evidence_id], actor="a", reason="r")
        nlc.select_improvement(self.project, imp["improvement_id"], actor="a", reason="select")
        self._force_phase_p22()
        reentered = nlc.reenter_for_improvement(self.project, imp["improvement_id"], "P7", actor="a", reason="reenter",
                                                  evidence_refs=[self.exec_evidence_id])
        self.assertEqual(mstatus(self.project)["current_phase"], "P7")

    def test_92_95_96_implementation_reentry_fails_closed_graph_not_broadened(self) -> None:
        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "latency_ms", 900)
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       category="IMPLEMENTATION", operation_refs=[obs["observation_id"]],
                                       evidence_refs=[self.exec_evidence_id], actor="a", reason="r")
        nlc.select_improvement(self.project, imp["improvement_id"], actor="a", reason="select")
        self._force_phase_p22()
        with self.assertRaises(MethodologyValidationError) as ctx:
            nlc.reenter_for_improvement(self.project, imp["improvement_id"], "P12", actor="a", reason="reenter")
        # disclosed, genuine gap: P22.allowed_back_transitions today is only P1/P6/P7/P21
        self.assertIn("not currently a legal methodology transition", str(ctx.exception))
        from nogap_methodology import load_methodology
        p22 = load_methodology().get_phase("P22")
        self.assertNotIn("P12", p22.allowed_back_transitions)  # graph genuinely not broadened

    def test_93_research_improvement_can_reference_m7j(self) -> None:
        import nogap_research as nr
        q = nr.create_research_question(self.project, title="Q", question="does X help?", actor="a", reason="r")
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="research",
                                       category="RESEARCH", research_refs=[q["question_id"]], actor="a", reason="r")
        self.assertEqual(imp["research_refs"], [q["question_id"]])

    def test_94_unknown_improvement_does_not_auto_route(self) -> None:
        self.assertEqual(nlc.IMPROVEMENT_ROUTING_MAP["OTHER"], ())
        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "latency_ms", 900)
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       category="OTHER", operation_refs=[obs["observation_id"]],
                                       evidence_refs=[self.exec_evidence_id], actor="a", reason="r")
        nlc.select_improvement(self.project, imp["improvement_id"], actor="a", reason="select")
        self._force_phase_p22()
        with self.assertRaises(MethodologyValidationError):
            nlc.reenter_for_improvement(self.project, imp["improvement_id"], "P6", actor="a", reason="reenter")

    def test_97_98_99_selected_implemented_validated_released_distinct(self) -> None:
        result = self.full_clean_release()
        obs = self.observe(result["deployment"]["deployment_id"], "latency_ms", 900)
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       operation_refs=[obs["observation_id"]], evidence_refs=[self.exec_evidence_id], actor="a", reason="r")
        selected = nlc.select_improvement(self.project, imp["improvement_id"], actor="a", reason="select")
        self.assertEqual(selected["status"], "SELECTED")
        with self.assertRaises(MethodologyValidationError):
            nlc.set_improvement_status(self.project, imp["improvement_id"], "VALIDATED", actor="a", reason="skip ahead")
        implemented = nlc.set_improvement_status(self.project, imp["improvement_id"], "IMPLEMENTED", actor="a", reason="done coding")
        self.assertEqual(implemented["status"], "IMPLEMENTED")
        validated = nlc.set_improvement_status(self.project, imp["improvement_id"], "VALIDATED", actor="a", reason="verified in prod")
        self.assertEqual(validated["status"], "VALIDATED")

    def test_100_101_rejected_inconclusive_improvement_retained(self) -> None:
        imp1 = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="hunch", actor="a", reason="r")
        rejected = nlc.set_improvement_status(self.project, imp1["improvement_id"], "REJECTED", actor="a", reason="not worth it")
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertIsNotNone(nlc.load_improvement(self.project, imp1["improvement_id"]))
        imp2 = nlc.create_improvement(self.project, problem_or_opportunity="p2", proposed_change="c2", source_type="hunch", actor="a", reason="r")
        inconclusive = nlc.set_improvement_status(self.project, imp2["improvement_id"], "INCONCLUSIVE", actor="a", reason="unclear")
        self.assertEqual(inconclusive["status"], "INCONCLUSIVE")

    def test_102_103_cost_and_risk_fields_preserved(self) -> None:
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       cost_estimate="2 engineer-weeks", risk="low", actor="a", reason="r")
        self.assertEqual(imp["cost_estimate"], "2 engineer-weeks")
        self.assertEqual(imp["risk"], "low")

    def test_104_improvement_history_preserved(self) -> None:
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="hunch", actor="a", reason="r")
        rejected = nlc.set_improvement_status(self.project, imp["improvement_id"], "REJECTED", actor="a", reason="no")
        self.assertEqual(len(rejected["history"]), 2)



# --- P23: Lifecycle Decision -----------------------------------------------------

class LifecycleDecisionTests(LifecycleFixture):
    # create_lifecycle_decision is unconditionally P23 phase-entering (final review
    # fix), so every test here must reach P22 first and supply real evidence_refs
    # for the P22->P23 transition. Not a setUp override: test_116_117 needs to build
    # its release/deployment/failure records BEFORE forcing the phase (freezing a
    # NEW candidate is no longer legal once already at P22).

    def test_105_create_lifecycle_decision(self) -> None:
        self._force_phase_p22()
        lcd = nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="all good", actor="human:owner",
                                              reason="review", evidence_refs=[self.exec_evidence_id])
        self.assertEqual(lcd["outcome"], "CONTINUE")

    def test_106_duplicate_lifecycle_decision_rejected(self) -> None:
        self._force_phase_p22()
        nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="r", actor="human:owner", reason="review",
                                        lifecycle_decision_id="LCD-X", evidence_refs=[self.exec_evidence_id])
        with self.assertRaises(MethodologyValidationError):
            nlc.create_lifecycle_decision(self.project, outcome="MAINTAIN", rationale="r", actor="human:owner", reason="review",
                                            lifecycle_decision_id="LCD-X", evidence_refs=[self.exec_evidence_id])

    def test_107_through_114_outcomes_preserved(self) -> None:
        self._force_phase_p22()
        for outcome in ("CONTINUE", "MAINTAIN", "IMPROVE", "REENTER", "SUSPEND", "RETIRE", "ARCHIVE", "INCONCLUSIVE"):
            authority = "human" if outcome in nlc.LIFECYCLE_IRREVERSIBLE_OUTCOMES else "acceptance"
            lcd = nlc.create_lifecycle_decision(self.project, outcome=outcome, rationale=f"testing {outcome}", actor="human:owner",
                                                  reason="review", authority=authority, evidence_refs=[self.exec_evidence_id])
            self.assertEqual(lcd["outcome"], outcome)

    def test_115_insufficient_evidence_yields_inconclusive(self) -> None:
        self._force_phase_p22()
        lcd = nlc.create_lifecycle_decision(self.project, outcome="INCONCLUSIVE", rationale="not enough operational history yet",
                                              actor="human:owner", reason="review", evidence_refs=[self.exec_evidence_id])
        self.assertEqual(lcd["outcome"], "INCONCLUSIVE")

    def test_116_117_retire_archive_do_not_delete_history(self) -> None:
        result = self.full_clean_release()
        failure = nf.create_failure(self.project, failure_class="X", summary="x", actor="a", task_id=self.task_id)
        self._force_phase_p22()
        nlc.create_lifecycle_decision(self.project, outcome="RETIRE", rationale="shutting down", actor="human:owner",
                                        reason="retire", authority="human", evidence_refs=[self.exec_evidence_id])
        self.assertIsNotNone(nf.load_failure(self.project, failure["failure_id"]))
        self.assertIsNotNone(nlc.load_release_candidate(self.project, result["candidate"]["release_candidate_id"]))
        self.assertIsNotNone(nlc.load_deployment(self.project, result["deployment"]["deployment_id"]))

    def test_irreversible_outcome_requires_authority(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            nlc.create_lifecycle_decision(self.project, outcome="RETIRE", rationale="r", actor="agent:codex", reason="r", authority="execution")
        with self.assertRaises(MethodologyValidationError):
            nlc.create_lifecycle_decision(self.project, outcome="ARCHIVE", rationale="r", actor="agent:codex", reason="r", authority="tool")
        self._force_phase_p22()
        ok = nlc.create_lifecycle_decision(self.project, outcome="RETIRE", rationale="r", actor="human:owner", reason="r",
                                             authority="human", evidence_refs=[self.exec_evidence_id])
        self.assertEqual(ok["outcome"], "RETIRE")

    def test_119_lifecycle_decision_does_not_use_accept_reject_namespace(self) -> None:
        self.assertNotIn("ACCEPT", nlc.LIFECYCLE_OUTCOMES)
        self.assertNotIn("REJECT", nlc.LIFECYCLE_OUTCOMES)
        self.assertNotIn("ABSTAIN", nlc.LIFECYCLE_OUTCOMES)

    def test_120_current_decision_deterministic(self) -> None:
        self._force_phase_p22()
        nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="r1", actor="human:owner", reason="r",
                                        lifecycle_decision_id="LCD-999", evidence_refs=[self.exec_evidence_id])
        second = nlc.create_lifecycle_decision(self.project, outcome="MAINTAIN", rationale="r2", actor="human:owner", reason="r",
                                                 lifecycle_decision_id="LCD-001B", evidence_refs=[self.exec_evidence_id])
        current = nlc.get_current_lifecycle_decision(self.project)
        self.assertEqual(current["decision"]["lifecycle_decision_id"], second["lifecycle_decision_id"])

    def test_121_conflict_fails_closed(self) -> None:
        self._force_phase_p22()
        first = nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="r1", actor="human:owner", reason="r",
                                                lifecycle_decision_id="LCD-A", evidence_refs=[self.exec_evidence_id])
        second = nlc.create_lifecycle_decision(self.project, outcome="MAINTAIN", rationale="r2", actor="human:owner", reason="r",
                                                 lifecycle_decision_id="LCD-B", evidence_refs=[self.exec_evidence_id])
        path_b = nlc.lifecycle_dir(self.project) / "lifecycle_decisions" / "LCD-B.json"
        record_b = json.loads(path_b.read_text(encoding="utf-8"))
        record_b["sequence"] = first["sequence"]
        path_b.write_text(json.dumps(record_b), encoding="utf-8")
        current = nlc.get_current_lifecycle_decision(self.project)
        self.assertEqual(current["status"], "CONFLICT")

    def test_122_superseded_lifecycle_decision_retained(self) -> None:
        self._force_phase_p22()
        lcd1 = nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="r1", actor="human:owner", reason="r",
                                               evidence_refs=[self.exec_evidence_id])
        lcd2 = nlc.create_lifecycle_decision(self.project, outcome="SUSPEND", rationale="r2", actor="human:owner", reason="r",
                                               evidence_refs=[self.exec_evidence_id])
        nlc.mark_superseded(self.project, "lifecycle_decisions", lcd1["lifecycle_decision_id"], superseded_by=lcd2["lifecycle_decision_id"], actor="a", reason="revised")
        reloaded = nlc.load_lifecycle_decision(self.project, lcd1["lifecycle_decision_id"])
        self.assertEqual(reloaded["status"], "SUPERSEDED")
        self.assertEqual(reloaded["outcome"], "CONTINUE")


# --- Fail-closed / malformed / duplicate / schema ---------------------------------

class FailClosedTests(LifecycleFixture):
    def test_malformed_lifecycle_record_fails_closed(self) -> None:
        rc = self.make_candidate()
        path = nlc.lifecycle_dir(self.project) / "release_candidates" / f"{rc['release_candidate_id']}.json"
        path.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nlc.list_release_candidates(self.project)

    def test_unsupported_schema_rejected(self) -> None:
        rc = self.make_candidate()
        path = nlc.lifecycle_dir(self.project) / "release_candidates" / f"{rc['release_candidate_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["schema_version"] = "99.0.0"
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nlc.freeze_release_candidate(self.project, rc["release_candidate_id"], actor="a", reason="r")

    def test_methodology_version_mismatch_rejected(self) -> None:
        rc = self.make_candidate()
        path = nlc.lifecycle_dir(self.project) / "release_candidates" / f"{rc['release_candidate_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["methodology_version"] = "0.0.1"
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nlc.freeze_release_candidate(self.project, rc["release_candidate_id"], actor="a", reason="r")

    def test_no_gate_mutation_anywhere_in_lifecycle(self) -> None:
        import inspect
        source = inspect.getsource(nlc)
        self.assertNotIn('"gates"', source)  # the module never references .code-loop/runtime/gates/ at all

    def test_unknown_evidence_ref_rejected_where_resolvable(self) -> None:
        runtime_dir = self.project / ".code-loop" / "runtime" / "evidence"
        (runtime_dir / "evidence-fake.json").write_text(json.dumps({"id": "evidence-fake", "status": "passed"}), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            self.make_candidate(verification_refs=["evidence-does-not-exist"])


class ActorReasonRequirementTests(LifecycleFixture):
    def test_freeze_requires_actor_and_reason(self) -> None:
        rc = self.make_candidate()
        with self.assertRaises(MethodologyValidationError):
            nlc.freeze_release_candidate(self.project, rc["release_candidate_id"], actor="", reason="r")
        with self.assertRaises(MethodologyValidationError):
            nlc.freeze_release_candidate(self.project, rc["release_candidate_id"], actor="a", reason="")

    def test_readiness_requires_actor_and_reason(self) -> None:
        rc = self.frozen_candidate()
        with self.assertRaises(MethodologyValidationError):
            nlc.evaluate_release_readiness(self.project, rc["release_candidate_id"], actor="", reason="r")

    def test_lifecycle_decision_requires_actor_and_reason(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="r", actor="", reason="r")


class ProfileAwareReadinessTests(LifecycleFixture):
    def test_light_vs_strict_readiness_burden_differs(self) -> None:
        rc = self.frozen_candidate()
        light_readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(light_readiness["readiness_outcome"], "READY_FOR_DECISION")


class StrictReadinessBurdenTests(StrictProfileLifecycleFixture):
    def test_30_strict_receives_deeper_burden(self) -> None:
        # STRICT genuinely cannot complete verification with a simple stub adapter
        # in this test harness (external validation has no configured mechanism
        # anywhere in this codebase - nogap_verify_binding.evaluate_reproducibility's
        # own disclosed, honest INCONCLUSIVE, never a fabricated pass) - so this
        # evaluates readiness directly on the DRAFT candidate rather than going
        # through freeze()/P19 first. The STRICT-specific rollback/observability
        # check runs unconditionally regardless of freeze status, so it is fully
        # exercised either way.
        rc = self.make_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertNotEqual(readiness["readiness_outcome"], "READY_FOR_DECISION")
        self.assertTrue(any("rollback_plan_ref" in r for r in readiness["blocking_reasons"]))
        self.assertTrue(any("observability_plan_ref" in r for r in readiness["blocking_reasons"]))


# --- Memory integration ------------------------------------------------------------

class MemoryIntegrationTests(LifecycleFixture):
    def test_123_lifecycle_source_changes_make_memory_stale(self) -> None:
        import nogap_memory as nm
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")
        self.make_candidate()
        self.assertEqual(nm.memory_status(self.project)["status"], "STALE")

    def test_124_125_126_rebuild_includes_candidate_readiness_deployment(self) -> None:
        import nogap_memory as nm
        result = self.full_clean_release()
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(snapshot["current_release_candidate"]["release_candidate_id"], result["candidate"]["release_candidate_id"])
        self.assertTrue(any(r["readiness_id"] == result["readiness"]["readiness_id"] for r in snapshot["release_readiness"]))
        self.assertTrue(any(d["deployment_id"] == result["deployment"]["deployment_id"] for d in snapshot["deployments"]))

    def test_127_rebuild_includes_operational_status(self) -> None:
        import nogap_memory as nm
        result = self.full_clean_release()
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        self.assertIn(result["deployment"]["deployment_id"], snapshot["operational_status"])
        self.assertEqual(snapshot["operational_status"][result["deployment"]["deployment_id"]], "UNKNOWN")

    def test_128_129_rebuild_includes_open_and_resolved_incidents(self) -> None:
        import nogap_memory as nm
        result = self.full_clean_release()
        open_inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s1", severity="HIGH", actor="a", reason="r")
        closed_inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s2", severity="LOW", actor="a", reason="r")
        nlc.set_incident_status(self.project, closed_inc["incident_id"], "RESOLVED", actor="a", reason="fixed")
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        self.assertTrue(any(i["incident_id"] == open_inc["incident_id"] for i in snapshot["open_incidents"]))
        self.assertTrue(any(i["incident_id"] == closed_inc["incident_id"] for i in snapshot["resolved_incidents"]))

    def test_130_rebuild_includes_active_improvement(self) -> None:
        import nogap_memory as nm
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="hunch", actor="a", reason="r")
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        self.assertTrue(any(i["improvement_id"] == imp["improvement_id"] for i in snapshot["active_improvements"]))

    def test_131_rebuild_includes_lifecycle_decision(self) -> None:
        import nogap_memory as nm
        self._force_phase_p22()
        lcd = nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="r", actor="human:owner", reason="r",
                                              evidence_refs=[self.exec_evidence_id])
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(snapshot["current_lifecycle_decision"]["lifecycle_decision_id"], lcd["lifecycle_decision_id"])

    def test_132_source_provenance_preserved(self) -> None:
        import nogap_memory as nm
        result = self.full_clean_release()
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(snapshot["current_release_candidate"]["source_ref"], result["candidate"]["release_candidate_id"])

    def test_133_unknown_preserved_as_unknown(self) -> None:
        import nogap_memory as nm
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertIsNone(snapshot["current_release_candidate"])  # NONE == UNKNOWN-equivalent for "no current" here
        self.assertEqual(snapshot["release_candidates"], [])  # checked, zero

    def test_134_memory_does_not_infer_healthy(self) -> None:
        import nogap_memory as nm
        result = self.full_clean_release()
        self.observe(result["deployment"]["deployment_id"], "error_rate", 0.1)  # favorable data, but no criteria known to Memory
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertNotEqual(snapshot["operational_status"][result["deployment"]["deployment_id"]], "HEALTHY")

    def test_139_false_memory_injection_protection_unchanged(self) -> None:
        import nogap_memory as nm
        self.full_clean_release()
        nm.rebuild_memory(self.project, actor="tester")
        nm.markdown_path(self.project).write_text("Release approved.\nProduction healthy.\nNo incidents.\n", encoding="utf-8")
        self.assertEqual(nm.memory_status(self.project)["status"], "MODIFIED")
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")


class SingleOwnerSelectorTests(LifecycleFixture):
    """Direct regression analogous to the M7-J review fix, applied preemptively:
    proves Memory uses the Lifecycle-owned selectors rather than re-deriving them."""

    def test_memory_and_lifecycle_cannot_diverge_on_current_candidate(self) -> None:
        import nogap_memory as nm
        self.frozen_candidate(release_candidate_id="RC-999")
        second = self.frozen_candidate(release_candidate_id="RC-001B", candidate_ref="rc-1.0.1")
        lifecycle_view = nlc.get_current_release_candidate(self.project)
        sources = nm.collect_memory_sources(self.project)
        memory_view = nm._derive_structured_lifecycle(sources)["current_release_candidate"]
        self.assertEqual(lifecycle_view["candidate"]["release_candidate_id"], memory_view["release_candidate_id"])
        self.assertEqual(memory_view["release_candidate_id"], second["release_candidate_id"])

    def test_changing_lifecycle_selection_semantics_changes_memory_with_zero_memory_edits(self) -> None:
        import nogap_memory as nm
        first = self.frozen_candidate(release_candidate_id="RC-A")
        self.frozen_candidate(release_candidate_id="RC-B", candidate_ref="rc-1.0.1")

        original = nlc.select_current_release_candidate
        try:
            nlc.select_current_release_candidate = lambda candidates: {"status": "OK", "candidate": first} if candidates else {"status": "NONE", "candidate": None}
            sources = nm.collect_memory_sources(self.project)
            memory_view = nm._derive_structured_lifecycle(sources)["current_release_candidate"]
            self.assertEqual(memory_view["release_candidate_id"], first["release_candidate_id"])
        finally:
            nlc.select_current_release_candidate = original

    def test_memory_never_computes_health_criteria_itself(self) -> None:
        import inspect
        source = inspect.getsource(__import__("nogap_memory"))
        self.assertNotIn("severity_if_fails", source)
        self.assertNotIn("comparators = {", source)


# --- Cross-layer separation ---------------------------------------------------------

class CrossLayerSeparationTests(LifecycleFixture):
    def test_140_verification_pass_not_release_approval(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertNotEqual(readiness["readiness_outcome"], "ACCEPT")
        self.assertIn(readiness["readiness_outcome"], nlc.READINESS_OUTCOMES)

    def test_141_research_supported_not_release_approval(self) -> None:
        import nogap_research as nr
        q = nr.create_research_question(self.project, title="Q", question="q?", actor="a", reason="r")
        c = nr.create_claim(self.project, question_id=q["question_id"], statement="s", claim_type="EMPIRICAL",
                              claim_strength="LOW", scope="scope", actor="a", reason="r")
        a = nr.assess_claim(self.project, c["claim_id"], outcome="INCONCLUSIVE", rationale="no evidence yet", actor="a",
                              reason="r", assessor_id="a")
        rc = self.make_candidate(research_refs=[c["claim_id"]])
        self.assertEqual(rc["status"], "DRAFT")  # research reference alone changes nothing about release status

    def test_142_decision_accept_not_deployment_success(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        deployment = self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])
        self.assertEqual(deployment["status"], "PLANNED")  # ACCEPT decision resolved, but deployment not yet executed

    def test_143_deployment_success_not_production_healthy(self) -> None:
        result = self.full_clean_release()
        health = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"])
        self.assertEqual(result["deployment"]["status"], "SUCCEEDED")
        self.assertEqual(health["status"], "UNKNOWN")

    def test_144_incident_not_failure(self) -> None:
        result = self.full_clean_release()
        inc = nlc.create_incident(self.project, deployment_id=result["deployment"]["deployment_id"], summary="s", severity="LOW", actor="a", reason="r")
        # incident-specific statuses (e.g. LINKED_TO_FAILURE, MITIGATED) are not part
        # of FailureRecord's own vocabulary at all - the two lifecycles are distinct,
        # even though both happen to start at the shared word "OPEN"
        self.assertIn("LINKED_TO_FAILURE", nlc.INCIDENT_STATUSES)
        self.assertNotIn("LINKED_TO_FAILURE", nf.FAILURE_ORDER)
        self.assertNotIn("root_cause_class", inc)

    def test_145_improvement_not_decision(self) -> None:
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="hunch", actor="a", reason="r")
        self.assertNotIn(imp["status"], {"accept", "reject", "abstain"})

    def test_146_lifecycle_decision_not_decision_engine_accept(self) -> None:
        self._force_phase_p22()
        lcd = nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="r", actor="human:owner", reason="r",
                                              evidence_refs=[self.exec_evidence_id])
        self.assertNotEqual(lcd["outcome"], "accept")

    def test_147_failure_resolved_not_deployment_healthy(self) -> None:
        result = self.full_clean_release()
        failure = nf.create_failure(self.project, failure_class="X", summary="x", actor="a", task_id=self.task_id)
        # even an unrelated resolved-looking failure state must not affect operational health computation
        health = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"])
        self.assertEqual(health["status"], "UNKNOWN")

    def test_148_operational_healthy_not_scientific_supported(self) -> None:
        result = self.full_clean_release()
        self.observe(result["deployment"]["deployment_id"], "error_rate", 0.1)
        health = nlc.get_operational_status(self.project, result["deployment"]["deployment_id"], health_criteria=[
            {"metric_name": "error_rate", "comparator": "<=", "value": 5.0, "severity_if_fails": "UNHEALTHY"},
        ])
        self.assertEqual(health["status"], "HEALTHY")
        self.assertNotEqual(health["status"], "SUPPORTED")

    def test_149_memory_projection_not_authority(self) -> None:
        import nogap_memory as nm
        before = mstatus(self.project)["current_phase"]
        self.full_clean_release()
        nm.build_memory_snapshot(self.project, actor="tester")
        nm.rebuild_memory(self.project, actor="tester")
        # Memory calls never themselves advanced the phase beyond what the lifecycle
        # calls already did
        self.assertIn(mstatus(self.project)["current_phase"], {"P19", "P20", "P21"})

    def test_150_no_direct_current_phase_mutation(self) -> None:
        import inspect
        import re
        source = inspect.getsource(nlc)
        self.assertIsNone(re.search(r'current_phase"\]\s*=(?!=)', source))

    def test_151_no_gate_dir_write(self) -> None:
        import inspect
        source = inspect.getsource(nlc)
        self.assertNotIn("runtime\" / \"gates\"", source)
        self.assertNotIn("runtime' / 'gates'", source)

    def test_152_no_parallel_evidence_ledger(self) -> None:
        import inspect
        source = inspect.getsource(nlc)
        self.assertNotIn("write_json(root / \"evidence\"", source)


# --- Regression: M6/M7-A..J unaffected ---------------------------------------------

class RegressionUnaffectedTests(LifecycleFixture):
    def test_154_m7h_failure_lifecycle_unchanged(self) -> None:
        failure = nf.create_failure(self.project, failure_class="X", summary="x", actor="a", task_id=self.task_id)
        with self.assertRaises(MethodologyValidationError):
            from nogap_failure import propose_repair
            propose_repair(self.project, failure["failure_id"], description="too early", target_phase="P13", actor="a", reason="skip")

    def test_155_m7i_memory_tamper_staleness_unchanged(self) -> None:
        import nogap_memory as nm
        nm.rebuild_memory(self.project, actor="tester")
        nm.markdown_path(self.project).write_text("tampered\n", encoding="utf-8")
        self.assertEqual(nm.memory_status(self.project)["status"], "MODIFIED")

    def test_156_m7j_research_unchanged(self) -> None:
        import nogap_research as nr
        q = nr.create_research_question(self.project, title="Q", question="q?", actor="a", reason="r")
        h = nr.create_hypothesis(self.project, question_id=q["question_id"], statement="s", actor="a", reason="r")
        registered = nr.register_hypothesis(self.project, h["hypothesis_id"], actor="a", reason="prereg")
        self.assertTrue(registered["preregistered"])

    def test_157_m7g_interlock_unchanged(self) -> None:
        import nogap_verify_binding as vb
        precondition = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertTrue(precondition["satisfied"])

    def test_158_m6_acceptance_semantics_unchanged(self) -> None:
        from nogap import acceptability
        decision = {"decision": "accept", "actor_id": "human:owner", "authority": "acceptance", "evidence": []}
        self.assertEqual(acceptability(decision, {}, set()), "ACCEPT requires evidence references")

    def test_159_enforcement_statuses_honest(self) -> None:
        from nogap_methodology import get_principle_enforcement
        gp12 = get_principle_enforcement("GP-12")
        self.assertEqual(gp12.status, "ENFORCED")  # unchanged by M7-K


# --- Review fix regressions: Blocker 1 - LIGHT must not bypass minimum verification

class LightVerificationSemanticsTests(LifecycleFixture):
    def test_blocker1_1_light_with_no_verification_cannot_be_ready(self) -> None:
        rc = self.frozen_candidate(included_task_refs=["TASK-NEVER-VERIFIED"])
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertNotEqual(readiness["readiness_outcome"], "READY_FOR_DECISION")
        self.assertEqual(readiness["readiness_outcome"], "NOT_READY")

    def test_blocker1_2_light_with_legitimate_minimum_verification_can_be_ready(self) -> None:
        rc = self.frozen_candidate()  # references self.task_id, genuinely verified in setUp
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["readiness_outcome"], "READY_FOR_DECISION")

    def test_blocker1_3_explicit_p17_p18_skips_remain_valid_at_light(self) -> None:
        result_path = next((self.project / ".code-loop" / "methodology" / "artifacts").glob("p18_verification_result-*.json"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(result["fields"]["reproducibility_result"], "SKIPPED_PER_PROFILE_POLICY")
        # LIGHT's own precondition is still satisfied despite the explicit skip -
        # M7-B/M7-G's own permitted skip, not something nogap_lifecycle invented
        import nogap_verify_binding as vb
        precondition = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertTrue(precondition["satisfied"], precondition["reason"])
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["readiness_outcome"], "READY_FOR_DECISION")

    def test_blocker1_4_local_pass_alone_is_insufficient(self) -> None:
        # A task whose execution succeeded but was never run through `nogap verify`
        # at all (no P18_VERIFICATION_RESULT exists for it whatsoever) must not
        # satisfy readiness - "local PASS" (raw execution evidence) is never
        # authoritative on its own, exactly as M6/M7-G already established.
        second_contract = create_artifact(self.project, "P12_TASK_CONTRACT", {
            "goal": "implement Y", "scope": ["svc2"], "forbidden_scope": ["unrelated"],
            "acceptance_criteria": ["Y happens"], "planned_tests": ["unit"], "required_evidence": ["execution"],
            "stop_conditions": ["security fail"], "requirement_refs": [self.chain["P6"]["fields"]["requirement_id"]],
            "gate_plan_refs": [self.chain["P11"]["artifact_id"]], "allow_non_active_requirement_refs": True,
        }, actor="architect")
        second_task_id = second_contract["fields"]["task_id"]
        # deliberately never call nogap.cmd_run/cmd_verify for this second task - only
        # its contract exists, standing in for "no verification ever attempted"
        rc = self.frozen_candidate(included_task_refs=[second_task_id])
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertNotEqual(readiness["readiness_outcome"], "READY_FOR_DECISION")

    def test_blocker1_5_no_second_verification_definition_in_lifecycle(self) -> None:
        import inspect
        import re
        source = inspect.getsource(nlc)
        # the module calls INTO nogap_verify_binding's real precondition/depth
        # functions rather than re-deriving them
        self.assertIn("verification_acceptance_precondition", source)
        self.assertIn("derive_verification_depth", source)
        # it must never itself COMPARE against or hardcode the verification status
        # vocabulary those functions own (a documentation comment mentioning the
        # status name is fine; a live equality check against it would mean this
        # module re-implemented the judgment instead of delegating it)
        executable_lines = [line for line in source.splitlines() if not line.strip().startswith("#")]
        executable_source = "\n".join(executable_lines)
        self.assertIsNone(re.search(r'==\s*"(SKIPPED_PER_PROFILE_POLICY|VERIFICATION_COMPLETE_AWAITING_DECISION)"', executable_source))


# --- Review fix regressions: Blocker 2 - STANDARD deployment decision boundary ---

class StandardDeploymentDecisionTests(StandardProfileLifecycleFixture):
    def test_blocker2_1_standard_ready_no_decision_fails_closed(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["readiness_outcome"], "READY_FOR_DECISION")
        with self.assertRaises(MethodologyValidationError):
            nlc.create_deployment(self.project, release_candidate_id=rc["release_candidate_id"], readiness_id=readiness["readiness_id"],
                                   environment="production", deployment_target="k8s", actor="a", reason="deploy without decision")

    def test_blocker2_2_standard_valid_accept_decision_allows_deployment(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["readiness_outcome"], "READY_FOR_DECISION")
        decision_id = self.accept_decision()
        deployment = nlc.create_deployment(self.project, release_candidate_id=rc["release_candidate_id"], readiness_id=readiness["readiness_id"],
                                             environment="production", deployment_target="k8s", decision_refs=[decision_id],
                                             actor="a", reason="deploy with accept")
        self.assertEqual(deployment["status"], "PLANNED")
        self.assertEqual(deployment["decision_refs"], [decision_id])

    def test_blocker2_3_reject_decision_cannot_authorize_deployment(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        decisions_dir = self.project / ".code-loop" / "runtime" / "decisions"
        decisions_dir.mkdir(parents=True, exist_ok=True)
        (decisions_dir / "decision-reject.json").write_text(json.dumps({
            "id": "decision-reject", "decision": "reject", "reason": "not good enough", "actor_id": "human:owner", "authority": "human",
        }), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nlc.create_deployment(self.project, release_candidate_id=rc["release_candidate_id"], readiness_id=readiness["readiness_id"],
                                   environment="production", deployment_target="k8s", decision_refs=["decision-reject"],
                                   actor="a", reason="deploy with reject")

    def test_blocker2_4_abstain_decision_cannot_authorize_deployment(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        # a real ABSTAIN, produced by nogap decide itself (authority=execution
        # cannot issue accept), never hand-fabricated
        nogap.cmd_decide(decide_namespace(str(self.project), authority="execution"))
        decision = json.loads((self.project / ".code-loop" / "runtime" / "decisions" / "decision-0001.json").read_text(encoding="utf-8"))
        self.assertEqual(decision["decision"], "abstain")
        with self.assertRaises(MethodologyValidationError):
            nlc.create_deployment(self.project, release_candidate_id=rc["release_candidate_id"], readiness_id=readiness["readiness_id"],
                                   environment="production", deployment_target="k8s", decision_refs=["decision-0001"],
                                   actor="a", reason="deploy with abstain")

    def test_blocker2_5_unknown_decision_cannot_authorize_deployment(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        with self.assertRaises(MethodologyValidationError):
            nlc.create_deployment(self.project, release_candidate_id=rc["release_candidate_id"], readiness_id=readiness["readiness_id"],
                                   environment="production", deployment_target="k8s", decision_refs=["decision-does-not-exist"],
                                   actor="a", reason="deploy with unresolvable ref")

    def test_blocker2_6_lifecycle_never_creates_or_mutates_decision(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        decision_id = self.accept_decision()
        decisions_dir = self.project / ".code-loop" / "runtime" / "decisions"
        before = (decisions_dir / "decision-0001.json").read_text(encoding="utf-8")
        nlc.create_deployment(self.project, release_candidate_id=rc["release_candidate_id"], readiness_id=readiness["readiness_id"],
                               environment="production", deployment_target="k8s", decision_refs=[decision_id],
                               actor="a", reason="deploy")
        after = (decisions_dir / "decision-0001.json").read_text(encoding="utf-8")
        self.assertEqual(before, after)
        import inspect
        source = inspect.getsource(nlc._resolve_decision_refs)
        # the ONLY function in this module that touches .code-loop/runtime/decisions/
        # only ever reads it (glob + read_text) - no write_text/write_json call exists
        self.assertNotIn("write_text", source)
        self.assertNotIn("write_json", source)


# --- Review fix regressions: Blocker 3 - P19 freeze cannot bypass M7-C -----------

class FreezeTransitionSemanticsTests(LifecycleFixture):
    def test_blocker3_1_p18_freeze_performs_legal_p19_transition(self) -> None:
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")
        self.frozen_candidate()
        self.assertEqual(mstatus(self.project)["current_phase"], "P19")

    def test_blocker3_2_already_p19_freeze_works_without_duplicate_transition(self) -> None:
        self.frozen_candidate()  # P18 -> P19
        self.assertEqual(mstatus(self.project)["current_phase"], "P19")
        state_before = mstatus(self.project)
        second = self.frozen_candidate(candidate_ref="rc-1.0.1")
        self.assertEqual(second["status"], "FROZEN")
        state_after = mstatus(self.project)
        self.assertEqual(state_after["current_phase"], "P19")
        # no duplicate transition_history entry was appended for the second freeze
        self.assertEqual(len(state_after["transition_history"]), len(state_before["transition_history"]))

    def test_blocker3_3_arbitrary_earlier_illegal_phase_freeze_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp2:
            project2 = Path(tmp2)
            init_git_repo(project2)
            init_project(project2, "research", "low", "low", actor="test")
            create_artifact(project2, "P0_PROJECT_INTENT", {
                "project_name": "demo", "intent_type": mstatus(project2)["intent"], "problem_summary": "x",
                "target_users_or_context": "team", "desired_outcome": "y", "owner": "a", "initial_constraints": ["budget"],
            }, actor="a")
            self.assertEqual(mstatus(project2)["current_phase"], "P0")
            rc = nlc.create_release_candidate(project2, version="1.0.0", candidate_ref="rc", code_revision="abc", actor="a", reason="r")
            with self.assertRaises(MethodologyValidationError) as ctx:
                nlc.freeze_release_candidate(project2, rc["release_candidate_id"], actor="a", reason="freeze")
            self.assertIn("not currently a legal methodology transition", str(ctx.exception))
            # fails CLOSED: candidate was never mutated into FROZEN
            reloaded = nlc.load_release_candidate(project2, rc["release_candidate_id"])
            self.assertEqual(reloaded["status"], "DRAFT")

    def test_blocker3_4_illegal_later_phase_reentry_freeze_rejected(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        deployment = self.make_deployment(readiness["release_candidate_id"], readiness["readiness_id"])
        self.succeed(deployment["deployment_id"])
        obs = self.observe(deployment["deployment_id"], "latency_ms", 900)
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       operation_refs=[obs["observation_id"]], actor="a", reason="r", evidence_refs=[self.exec_evidence_id])
        # drive current_phase to P22 via the module's own real transition() calls
        if mstatus(self.project)["current_phase"] != "P22":
            transition(self.project, "P22", "test-harness", "force-advance for test",
                       artifact_refs=[imp["improvement_id"]], evidence_refs=[self.exec_evidence_id], authority_class="tool")
        self.assertEqual(mstatus(self.project)["current_phase"], "P22")
        new_candidate = self.make_candidate(candidate_ref="rc-late")
        with self.assertRaises(MethodologyValidationError) as ctx:
            nlc.freeze_release_candidate(self.project, new_candidate["release_candidate_id"], actor="a", reason="freeze")
        self.assertIn("not currently a legal methodology transition", str(ctx.exception))
        reloaded = nlc.load_release_candidate(self.project, new_candidate["release_candidate_id"])
        self.assertEqual(reloaded["status"], "DRAFT")

    def test_blocker3_5_no_direct_current_phase_assignment(self) -> None:
        import re
        import inspect
        source = inspect.getsource(nlc)
        self.assertIsNone(re.search(r'current_phase"\]\s*=(?!=)', source))

    def test_blocker3_6_graph_unchanged(self) -> None:
        from nogap_methodology import load_methodology
        p19 = load_methodology().get_phase("P19")
        self.assertEqual(p19.allowed_next, ["P20"])
        self.assertEqual(p19.allowed_back_transitions, ["P18"])
        p22 = load_methodology().get_phase("P22")
        self.assertEqual(sorted(p22.allowed_back_transitions), ["P1", "P21", "P6", "P7"])

    def test_uninitialized_legacy_project_freeze_uses_existing_compatibility_only(self) -> None:
        # matches the SAME "no methodology state -> legacy compatibility" policy
        # nogap_verify_binding.verification_acceptance_precondition() already
        # established - not a newly invented exemption.
        with tempfile.TemporaryDirectory() as tmp2:
            project2 = Path(tmp2)
            init_git_repo(project2)
            self.assertIsNone(load_state_of(project2))
            rc = nlc.create_release_candidate(project2, version="1.0.0", candidate_ref="rc", code_revision="abc", actor="a", reason="r")
            frozen = nlc.freeze_release_candidate(project2, rc["release_candidate_id"], actor="a", reason="freeze")
            self.assertEqual(frozen["status"], "FROZEN")


def load_state_of(project: Path):
    from nogap_methodology import load_state
    return load_state(project)


# --- Mandatory authority review: RETIRE / ARCHIVE --------------------------------

class RetireArchiveAuthorityTests(LifecycleFixture):
    def test_authority_1_execution_agent_cannot_retire(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            nlc.create_lifecycle_decision(self.project, outcome="RETIRE", rationale="shutting down", actor="agent:codex",
                                            reason="auto-retire", authority="execution")

    def test_authority_2_reviewer_judge_agent_cannot_retire(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            nlc.create_lifecycle_decision(self.project, outcome="RETIRE", rationale="review says retire", actor="agent:claude-reviewer",
                                            reason="reviewer decision", authority="verification")

    def test_authority_3_generic_acceptance_authority_cannot_retire(self) -> None:
        # proven in this codebase: "acceptance" is a bare, self-asserted CLI flag
        # (nogap decide --authority acceptance, defaulted) with no verification
        # anywhere that the caller is human - so it must not authorize RETIRE/ARCHIVE
        with self.assertRaises(MethodologyValidationError):
            nlc.create_lifecycle_decision(self.project, outcome="RETIRE", rationale="acceptance authority only",
                                            actor="system:judge", reason="non-human acceptance", authority="acceptance")

    def test_authority_4_human_owner_can_retire(self) -> None:
        self._force_phase_p22()
        lcd = nlc.create_lifecycle_decision(self.project, outcome="RETIRE", rationale="shutting down", actor="human:owner",
                                              reason="owner decision", authority="human", evidence_refs=[self.exec_evidence_id])
        self.assertEqual(lcd["outcome"], "RETIRE")

    def test_authority_5_human_owner_can_archive(self) -> None:
        self._force_phase_p22()
        lcd = nlc.create_lifecycle_decision(self.project, outcome="ARCHIVE", rationale="archiving", actor="human:owner",
                                              reason="owner decision", authority="human", evidence_refs=[self.exec_evidence_id])
        self.assertEqual(lcd["outcome"], "ARCHIVE")

    def test_authority_6_irreversible_action_remains_fully_historical(self) -> None:
        result = self.full_clean_release()
        failure = nf.create_failure(self.project, failure_class="X", summary="x", actor="a", task_id=self.task_id)
        self._force_phase_p22()
        nlc.create_lifecycle_decision(self.project, outcome="RETIRE", rationale="shutting down", actor="human:owner",
                                        reason="owner decision", authority="human", evidence_refs=[self.exec_evidence_id])
        self.assertIsNotNone(nf.load_failure(self.project, failure["failure_id"]))
        self.assertIsNotNone(nlc.load_release_candidate(self.project, result["candidate"]["release_candidate_id"]))
        self.assertIsNotNone(nlc.load_deployment(self.project, result["deployment"]["deployment_id"]))


# --- Final review fix: no silent transition swallowing / split-brain prevention --

class ReadinessSplitBrainTests(LifecycleFixture):
    """P19 -> P20: only READY_FOR_DECISION is phase-completing."""

    def test_1_not_ready_does_not_force_p20_transition(self) -> None:
        rc = self.frozen_candidate(included_task_refs=["TASK-NEVER-VERIFIED"])
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["readiness_outcome"], "NOT_READY")
        self.assertEqual(mstatus(self.project)["current_phase"], "P19")

    def test_2_incomplete_verification_does_not_falsely_advance(self) -> None:
        # incomplete/unresolved task verification is folded into `blocking` (not left
        # as a bare INCONCLUSIVE-only signal) by the pre-existing evaluate_release_
        # readiness implementation, so the observable outcome here is NOT_READY - the
        # invariant under test (an incomplete-verification candidate must never force
        # a phase transition) holds either way, and NOT_READY is strictly MORE
        # conservative than INCONCLUSIVE would have been, never less.
        second_contract = create_artifact(self.project, "P12_TASK_CONTRACT", {
            "goal": "implement Y", "scope": ["svc2"], "forbidden_scope": ["unrelated"],
            "acceptance_criteria": ["Y happens"], "planned_tests": ["unit"], "required_evidence": ["execution"],
            "stop_conditions": ["security fail"], "requirement_refs": [self.chain["P6"]["fields"]["requirement_id"]],
            "gate_plan_refs": [self.chain["P11"]["artifact_id"]], "allow_non_active_requirement_refs": True,
        }, actor="architect")
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=second_contract["fields"]["task_id"]))
        rc = self.frozen_candidate(included_task_refs=[second_contract["fields"]["task_id"]])
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["verification_status"], "INCOMPLETE")
        self.assertIn(readiness["readiness_outcome"], {"NOT_READY", "INCONCLUSIVE"})
        self.assertNotEqual(readiness["readiness_outcome"], "READY_FOR_DECISION")
        self.assertEqual(mstatus(self.project)["current_phase"], "P19")

    def test_3_stale_does_not_falsely_advance(self) -> None:
        rc = self.frozen_candidate()
        art_path = self.project / ".code-loop" / "methodology" / "artifacts" / f"{self.chain['P11']['artifact_id']}.json"
        record = json.loads(art_path.read_text(encoding="utf-8"))
        record["fields"]["gate_id"] = "MUTATED"
        art_path.write_text(json.dumps(record), encoding="utf-8")
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["readiness_outcome"], "STALE")
        self.assertEqual(mstatus(self.project)["current_phase"], "P19")

    def test_4_ready_for_decision_from_legal_p19_enters_p20(self) -> None:
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")
        rc = self.frozen_candidate()
        self.assertEqual(mstatus(self.project)["current_phase"], "P19")
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(readiness["readiness_outcome"], "READY_FOR_DECISION")
        self.assertEqual(mstatus(self.project)["current_phase"], "P20")

    def test_5_ready_for_decision_from_illegal_phase_fails_closed(self) -> None:
        # freeze BOTH candidates while still at P19 (freezing rc2 later would itself
        # legally re-enter P19 from P20, which is not what this test wants to prove)
        rc1 = self.frozen_candidate()
        self.assertEqual(mstatus(self.project)["current_phase"], "P19")
        rc2 = self.frozen_candidate(candidate_ref="rc2", code_revision="abc124")
        self.assertEqual(mstatus(self.project)["current_phase"], "P19")  # freeze #2 was a no-op transition

        readiness1 = self.evaluate(rc1["release_candidate_id"])
        self.assertEqual(readiness1["readiness_outcome"], "READY_FOR_DECISION")
        self.assertEqual(mstatus(self.project)["current_phase"], "P20")
        deployment = self.make_deployment(rc1["release_candidate_id"], readiness1["readiness_id"])
        self.succeed(deployment["deployment_id"])
        self.assertEqual(mstatus(self.project)["current_phase"], "P21")
        # advance one more legal forward hop, past the point P20 is reachable from
        # (P20 is reachable forward from P19 and backward from P21 - but NOT from P22)
        transition(self.project, "P22", "test-harness", "advance past P20 reachability",
                   artifact_refs=["test-artifact"], evidence_refs=[self.exec_evidence_id], authority_class="tool")
        self.assertEqual(mstatus(self.project)["current_phase"], "P22")

        # rc2 is already FROZEN with no drift and its shared task already verified -
        # every OTHER readiness criterion is satisfied, only the phase-legality fold
        # blocks it. Must downgrade honestly, never split-brain.
        readiness2 = self.evaluate(rc2["release_candidate_id"])
        self.assertEqual(readiness2["readiness_outcome"], "NOT_READY")
        self.assertEqual(mstatus(self.project)["current_phase"], "P22")  # unchanged - no split-brain

    def test_6_failed_transition_leaves_no_authoritative_split(self) -> None:
        rc1 = self.frozen_candidate()
        rc2 = self.frozen_candidate(candidate_ref="rc2", code_revision="abc124")
        readiness1 = self.evaluate(rc1["release_candidate_id"])
        deployment = self.make_deployment(rc1["release_candidate_id"], readiness1["readiness_id"])
        self.succeed(deployment["deployment_id"])
        transition(self.project, "P22", "test-harness", "advance past P20 reachability",
                   artifact_refs=["test-artifact"], evidence_refs=[self.exec_evidence_id], authority_class="tool")
        readiness2 = self.evaluate(rc2["release_candidate_id"])
        # the persisted readiness record itself must be internally honest: outcome
        # NOT_READY, phase-conflict reason present, no orphaned P20 claim anywhere
        reloaded = nlc.load_release_readiness(self.project, readiness2["readiness_id"])
        self.assertEqual(reloaded["readiness_outcome"], "NOT_READY")
        self.assertTrue(any("P19->P20" in r for r in reloaded["blocking_reasons"]))


class DeploymentSplitBrainTests(LifecycleFixture):
    """P20 -> P21: only SUCCEEDED is phase-entering, and it fails closed atomically."""

    def test_7_failed_does_not_claim_p21_advancement(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        deployment = self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])
        result = nlc.record_deployment_result(self.project, deployment["deployment_id"], status="FAILED", actor="a", reason="r")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(mstatus(self.project)["current_phase"], "P20")

    def test_8_cancelled_does_not_claim_advancement(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        deployment = self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])
        result = nlc.record_deployment_result(self.project, deployment["deployment_id"], status="CANCELLED", actor="a", reason="r")
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(mstatus(self.project)["current_phase"], "P20")

    def test_9_inconclusive_does_not_claim_advancement(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        deployment = self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])
        result = nlc.record_deployment_result(self.project, deployment["deployment_id"], status="INCONCLUSIVE", actor="a", reason="r")
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual(mstatus(self.project)["current_phase"], "P20")

    def test_10_succeeded_from_legal_p20_enters_p21(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        self.assertEqual(mstatus(self.project)["current_phase"], "P20")
        deployment = self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])
        result = self.succeed(deployment["deployment_id"])
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(mstatus(self.project)["current_phase"], "P21")

    def test_11_succeeded_from_illegal_methodology_state_fails_closed(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        deployment = self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])
        self.assertEqual(mstatus(self.project)["current_phase"], "P20")
        # revert to P19 via the SAME legal back-transition freeze itself uses -
        # P21 is reachable forward from P20 and backward from P22/P23, so P19 is the
        # one honestly-reachable phase from which P20->P21 is genuinely illegal
        transition(self.project, "P19", "test-harness", "revert for test",
                   artifact_refs=["revert-artifact"], authority_class="tool")
        self.assertEqual(mstatus(self.project)["current_phase"], "P19")
        with self.assertRaises(MethodologyValidationError):
            nlc.record_deployment_result(self.project, deployment["deployment_id"], status="SUCCEEDED", actor="a", reason="r")

    def test_12_failed_transition_leaves_deployment_not_succeeded(self) -> None:
        rc = self.frozen_candidate()
        readiness = self.evaluate(rc["release_candidate_id"])
        deployment = self.make_deployment(rc["release_candidate_id"], readiness["readiness_id"])
        transition(self.project, "P19", "test-harness", "revert for test",
                   artifact_refs=["revert-artifact"], authority_class="tool")
        with self.assertRaises(MethodologyValidationError):
            nlc.record_deployment_result(self.project, deployment["deployment_id"], status="SUCCEEDED", actor="a", reason="r")
        # the deployment record itself was never mutated - still PLANNED, not a
        # dangling/half-written SUCCEEDED
        reloaded = nlc.load_deployment(self.project, deployment["deployment_id"])
        self.assertEqual(reloaded["status"], "PLANNED")
        self.assertEqual(len(reloaded["history"]), 1)  # only CREATED, no RESULT_RECORDED


class ImprovementSplitBrainTests(LifecycleFixture):
    """P21 -> P22: only SELECTED (not mere PROPOSED) is phase-entering."""

    def test_13_proposed_improvement_does_not_move_project_into_p22(self) -> None:
        result = self.full_clean_release()
        self.assertEqual(mstatus(self.project)["current_phase"], "P21")
        obs = self.observe(result["deployment"]["deployment_id"], "latency_ms", 900)
        nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                 operation_refs=[obs["observation_id"]], evidence_refs=[self.exec_evidence_id], actor="a", reason="r")
        self.assertEqual(mstatus(self.project)["current_phase"], "P21")  # unchanged by mere proposal

    def test_14_weak_unselected_proposal_does_not_move_phase(self) -> None:
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="hunch", actor="a", reason="r")
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")
        self.assertEqual(imp["status"], "PROPOSED")

    def test_15_selected_enters_p22_only_through_legal_transition(self) -> None:
        result = self.full_clean_release()
        self.assertEqual(mstatus(self.project)["current_phase"], "P21")
        obs = self.observe(result["deployment"]["deployment_id"], "latency_ms", 900)
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       operation_refs=[obs["observation_id"]], evidence_refs=[self.exec_evidence_id], actor="a", reason="r")
        self.assertEqual(mstatus(self.project)["current_phase"], "P21")  # still unchanged before selection
        selected = nlc.select_improvement(self.project, imp["improvement_id"], actor="a", reason="select")
        self.assertEqual(selected["status"], "SELECTED")
        self.assertEqual(mstatus(self.project)["current_phase"], "P22")  # NOW it advances

    def test_16_illegal_p21_p22_entry_fails_closed(self) -> None:
        # LifecycleFixture never leaves P18 - P21->P22 legality requires being at P21
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       evidence_refs=[self.exec_evidence_id], actor="a", reason="r")
        with self.assertRaises(MethodologyValidationError):
            nlc.select_improvement(self.project, imp["improvement_id"], actor="a", reason="select")
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")

    def test_17_failed_transition_does_not_leave_selected_falsely_committed(self) -> None:
        imp = nlc.create_improvement(self.project, problem_or_opportunity="p", proposed_change="c", source_type="operational",
                                       evidence_refs=[self.exec_evidence_id], actor="a", reason="r")
        with self.assertRaises(MethodologyValidationError):
            nlc.select_improvement(self.project, imp["improvement_id"], actor="a", reason="select")
        reloaded = nlc.load_improvement(self.project, imp["improvement_id"])
        self.assertEqual(reloaded["status"], "PROPOSED")  # never mutated to SELECTED
        self.assertEqual(len(reloaded["history"]), 1)  # only CREATED


class LifecycleDecisionSplitBrainTests(LifecycleFixture):
    """P22 -> P23: EVERY outcome is unconditionally phase-entering."""

    def test_18_lifecycle_decision_from_legal_p22_enters_p23(self) -> None:
        self._force_phase_p22()
        self.assertEqual(mstatus(self.project)["current_phase"], "P22")
        lcd = nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="r", actor="human:owner", reason="r",
                                              evidence_refs=[self.exec_evidence_id])
        self.assertEqual(lcd["outcome"], "CONTINUE")
        self.assertEqual(mstatus(self.project)["current_phase"], "P23")

    def test_19_already_p23_works_without_duplicate_transition(self) -> None:
        self._force_phase_p22()
        nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="r1", actor="human:owner", reason="r",
                                        lifecycle_decision_id="LCD-999", evidence_refs=[self.exec_evidence_id])
        self.assertEqual(mstatus(self.project)["current_phase"], "P23")
        state_before = mstatus(self.project)
        nlc.create_lifecycle_decision(self.project, outcome="MAINTAIN", rationale="r2", actor="human:owner", reason="r",
                                        lifecycle_decision_id="LCD-001B", evidence_refs=[self.exec_evidence_id])
        state_after = mstatus(self.project)
        self.assertEqual(state_after["current_phase"], "P23")
        self.assertEqual(len(state_after["transition_history"]), len(state_before["transition_history"]))

    def test_20_illegal_phase_rejected_before_authoritative_write(self) -> None:
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")
        with self.assertRaises(MethodologyValidationError):
            nlc.create_lifecycle_decision(self.project, outcome="CONTINUE", rationale="r", actor="human:owner", reason="r")
        self.assertEqual(nlc.list_lifecycle_decisions(self.project), [])  # nothing was ever persisted

    def test_21_retire_cannot_be_recorded_if_p23_unreachable(self) -> None:
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")
        with self.assertRaises(MethodologyValidationError):
            nlc.create_lifecycle_decision(self.project, outcome="RETIRE", rationale="r", actor="human:owner", reason="r", authority="human")
        self.assertEqual(nlc.list_lifecycle_decisions(self.project), [])

    def test_22_failed_p23_transition_leaves_no_authoritative_record(self) -> None:
        before_count = len(nlc.list_lifecycle_decisions(self.project))
        with self.assertRaises(MethodologyValidationError):
            nlc.create_lifecycle_decision(self.project, outcome="SUSPEND", rationale="r", actor="human:owner", reason="r")
        after_count = len(nlc.list_lifecycle_decisions(self.project))
        self.assertEqual(before_count, after_count)


class NoSilentSwallowingTests(LifecycleFixture):
    def test_23_no_transition_swallowing_pattern_remains(self) -> None:
        import inspect
        source = inspect.getsource(nlc)
        self.assertNotIn("except MethodologyValidationError", source)
        self.assertNotIn("except MethodologyValidationError:\n        pass", source)

    def test_24_methodology_phase_graph_files_unchanged(self) -> None:
        from nogap_methodology import load_methodology
        definition = load_methodology()
        expectations = {
            "P19": (["P20"], ["P18"]), "P20": (["P21"], ["P19"]), "P21": (["P22"], ["P20"]),
            "P22": (["P23"], sorted(["P1", "P6", "P7", "P21"])), "P23": ([], sorted(["P0", "P21"])),
        }
        for phase_id, (allowed_next, allowed_back) in expectations.items():
            phase = definition.get_phase(phase_id)
            self.assertEqual(phase.allowed_next, allowed_next)
            self.assertEqual(sorted(phase.allowed_back_transitions), allowed_back)

    def test_25_no_direct_current_phase_assignment(self) -> None:
        import re
        import inspect
        source = inspect.getsource(nlc)
        self.assertIsNone(re.search(r'current_phase"\]\s*=(?!=)', source))

    def test_26_legacy_uninitialized_behavior_explicitly_tested(self) -> None:
        # readiness, deployment, improvement-selection, and lifecycle-decision all
        # reuse the SAME "state is None -> no phase check" convention - proven for
        # each, not just freeze.
        with tempfile.TemporaryDirectory() as tmp2:
            project2 = Path(tmp2)
            init_git_repo(project2)
            self.assertIsNone(load_state_of(project2))
            rc = nlc.create_release_candidate(project2, version="1.0.0", candidate_ref="rc", code_revision="abc",
                                                included_task_refs=[], actor="a", reason="r")
            frozen = nlc.freeze_release_candidate(project2, rc["release_candidate_id"], actor="a", reason="freeze")
            readiness = nlc.evaluate_release_readiness(project2, frozen["release_candidate_id"], actor="a", reason="evaluate")
            # verification is still required regardless of legacy status (Blocker 1
            # never regressed) - only the PHASE check is exempted for legacy projects
            self.assertEqual(readiness["readiness_outcome"], "NOT_READY")
            lcd = nlc.create_lifecycle_decision(project2, outcome="CONTINUE", rationale="r", actor="human:owner", reason="r")
            self.assertEqual(lcd["outcome"], "CONTINUE")


class CliTests(LifecycleFixture):
    def test_cli_full_lifecycle(self) -> None:
        # verification_refs must reference this project's real M6 evidence so that
        # freeze's sanctioned P18->P19 transition (which requires non-empty
        # evidence_refs, since P18 declares required_evidence) can actually succeed.
        fields = json.dumps({"version": "1.0.0", "candidate_ref": "rc-cli", "code_revision": "abc", "verification_refs": [self.exec_evidence_id]})
        create = run_script("lifecycle", "candidate", "create", str(self.project), "--actor", "cli", "--reason", "create", "--fields-json", fields)
        self.assertEqual(create.returncode, 0, create.stderr)
        self.assertIn("RC-001", create.stdout)

        freeze = run_script("lifecycle", "candidate", "freeze", str(self.project), "--id", "RC-001", "--actor", "cli", "--reason", "freeze")
        self.assertEqual(freeze.returncode, 0, freeze.stderr)
        self.assertIn("FROZEN", freeze.stdout)

        current = run_script("lifecycle", "candidate", "current", str(self.project))
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertIn("RC-001", current.stdout)

        query = run_script("lifecycle", "query", "query", str(self.project), "--kind", "release_candidates")
        self.assertEqual(query.returncode, 0, query.stderr)
        self.assertIn("RC-001", query.stdout)


if __name__ == "__main__":
    unittest.main()
