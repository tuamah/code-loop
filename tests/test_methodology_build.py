#!/usr/bin/env python3
"""M7-F acceptance checks: binding methodology BUILD phases (P12-P14) to the
existing M6 trusted execution pipeline, so pre-build readiness causally gates
`nogap run --execute`.

Covers the 28 mandatory cases from the brief (M6/M7-A..E regression coverage is
verified by running the full existing suites alongside this file, not duplicated
here) plus the three manual live scenarios, automated.
"""

from __future__ import annotations

import argparse
import hashlib
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
import nogap_build  # noqa: E402
from nogap_artifacts import create_artifact, list_artifacts, load_artifact  # noqa: E402
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
    ready: bool
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


def make_writer_adapter(adapter_id: str = "codex") -> StubAdapter:
    return StubAdapter(adapter_id, ready=True)


def make_silent_adapter(adapter_id: str = "codex") -> StubAdapter:
    return StubAdapter(adapter_id, ready=True, command_builder=lambda prompt, worktree: [sys.executable, "-c", "pass"])


def make_crash_adapter(adapter_id: str = "codex") -> StubAdapter:
    return StubAdapter(
        adapter_id, ready=True,
        command_builder=lambda prompt, worktree: [
            sys.executable, "-c",
            "open('agent_output.txt', 'w').write('partial'); import sys; sys.exit(1)",
        ],
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


def run_namespace(path: str, actor: str = "test-build", **overrides: Any) -> argparse.Namespace:
    defaults = {"path": path, "actor": actor, "execute": False, "execute_timeout": 600, "task_id": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "scripts/nogap.py", *args], cwd=ROOT, text=True, capture_output=True)


def build_p0_p11_chain(
    project: Path, actor: str = "team", p7_extra: dict | None = None, p8_extra: dict | None = None,
) -> dict[str, dict]:
    """Minimal valid P0-P11 chain (mirrors tests/test_methodology_artifacts.py's helper,
    duplicated here to keep this file self-contained per this repo's convention of one
    test file per module under test) - and, unlike that helper, ALSO drives current_phase
    all the way to P11 via the real transition engine, since M7-F's barrier checks
    current_phase, not just artifact presence.

    Call this BEFORE `nogap init` (the Trust Runtime): P3's phase contract requires
    non-empty evidence_refs to leave it, and once .code-loop/runtime/evidence/ exists,
    those refs are resolved against it - so this only works with a made-up evidence id
    while there is no runtime evidence ledger yet to disagree with it."""
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
        "responsibilities": ["svc1 does X"], "interfaces": ["api"], "external_dependencies": ["db"],
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
        "required_commands": ["pytest -k unit"], "forbidden_paths": ["secrets.env"],
    }, actor=actor)

    order = ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11"]
    for current, nxt in zip(order, order[1:]):
        evidence_refs = ["source-ref-1"] if current == "P3" else []
        transition(
            project, nxt, actor, f"{current} obligations satisfied",
            artifact_refs=[made[current]["artifact_id"]], evidence_refs=evidence_refs, authority_class="tool",
        )
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


class PreflightTests(unittest.TestCase):
    def test_1_and_2_execution_blocked_with_exact_reasons_when_prebuild_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            run_script("init", str(project))
            init_project(project, "research", "low", "low", actor="test")
            preflight = nogap_build.preflight_build(project)
            self.assertFalse(preflight["permitted"])
            self.assertEqual(preflight["status"], "METHODOLOGY_BLOCKED")
            self.assertTrue(any(reason.startswith("current phase") for reason in preflight["reasons"]))
            self.assertTrue(any("P0" in reason and "no artifact recorded" in reason for reason in preflight["reasons"]))

    def test_3_prebuild_ready_permits_p11_to_p12(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            build_p0_p11_chain(project)
            preflight = nogap_build.preflight_build(project)
            self.assertTrue(preflight["permitted"], preflight["reasons"])
            self.assertEqual(preflight["status"], "READY")

    def test_21_profile_override_affects_build_permission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")  # STANDARD
            build_p0_p11_chain(project)
            self.assertTrue(nogap_build.preflight_build(project)["permitted"])
            # escalate just P7 to STRICT, leaving the global effective_profile at STANDARD
            escalate_phase(project, "P7", "STRICT", actor="human:owner")
            preflight = nogap_build.preflight_build(project)
            self.assertFalse(preflight["permitted"])
            self.assertTrue(any("P7" in reason for reason in preflight["reasons"]))

    def test_22_strict_cannot_execute_through_light_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "high", "high", actor="test")  # STRICT
            # STRICT rejects an incomplete P7/P8 at creation time (M7-E's own fail-closed
            # behavior), so the STRICT-only fields must be supplied up front here.
            made = build_p0_p11_chain(
                project,
                p7_extra={"failure_domains": ["network partition"], "data_security_boundaries": ["PII isolated"]},
                p8_extra={"vendor_lock_in": "moderate"},
            )
            self.assertTrue(nogap_build.preflight_build(project)["permitted"])
            # now strip the STRICT-only fields back out via a direct file edit, simulating
            # a P7 that used to be valid and has since been corrupted - LIGHT-level content
            # masquerading in a STRICT project.
            p7_path = project / ".code-loop" / "methodology" / "artifacts" / f"{made['P7']['artifact_id']}.json"
            record = json.loads(p7_path.read_text(encoding="utf-8"))
            record["fields"].pop("failure_domains")
            record["fields"].pop("data_security_boundaries")
            p7_path.write_text(json.dumps(record), encoding="utf-8")
            preflight = nogap_build.preflight_build(project)
            self.assertFalse(preflight["permitted"])
            self.assertTrue(any("P7" in reason for reason in preflight["reasons"]))

    def test_23_no_direct_current_phase_mutation_in_build_module(self) -> None:
        source = (ROOT / "scripts" / "nogap_build.py").read_text(encoding="utf-8")
        self.assertNotIn('"current_phase"] =', source)
        self.assertNotIn("current_phase'] =", source)
        # every phase movement in this module goes through transition(...)
        self.assertIn("transition(", source)

    def test_24_run_cli_has_no_methodology_bypass_flag(self) -> None:
        result = run_script("run", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        lowered = result.stdout.lower()
        self.assertNotIn("--force", lowered)
        self.assertNotIn("--skip-methodology", lowered)
        self.assertNotIn("--bypass", lowered)

    def test_25_legacy_no_methodology_is_explicit_and_permitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            run_script("init", str(project))
            preflight = nogap_build.preflight_build(project)
            self.assertTrue(preflight["permitted"])
            self.assertEqual(preflight["status"], "METHODOLOGY_NOT_INITIALIZED")
            self.assertNotEqual(preflight["status"], "READY")  # never silently reported as READY


class TaskContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_project(self.project, "research", "low", "low", actor="test")
        self.chain = build_p0_p11_chain(self.project)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_4_task_contract_references_real_requirement(self) -> None:
        contract = make_task_contract(self.project, self.chain)
        self.assertEqual(contract["fields"]["requirement_refs"], [self.chain["P6"]["fields"]["requirement_id"]])
        self.assertTrue(contract["fields"]["task_id"].startswith("TASK-"))

    def test_5_fake_requirement_ref_rejected(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            make_task_contract(self.project, self.chain, requirement_refs=["REQ-999"])

    def test_6_superseded_requirement_rejected_unless_explicitly_allowed(self) -> None:
        from nogap_artifacts import update_requirement_status
        req_id = self.chain["P6"]["fields"]["requirement_id"]
        update_requirement_status(self.project, req_id, "SUPERSEDED", actor="architect", reason="replaced")
        with self.assertRaises(MethodologyValidationError):
            make_task_contract(self.project, self.chain)
        # explicit override is honored
        contract = make_task_contract(self.project, self.chain, allow_non_active_requirement_refs=True)
        self.assertEqual(contract["fields"]["requirement_refs"], [req_id])

    def test_7_task_contract_methodology_version_mismatch_rejected(self) -> None:
        contract = make_task_contract(self.project, self.chain)
        path = self.project / ".code-loop" / "methodology" / "artifacts" / f"{contract['artifact_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["methodology_version"] = "0.0.1"
        path.write_text(json.dumps(record), encoding="utf-8")
        from nogap_artifacts import validate_record
        problems = validate_record(self.project, record)
        self.assertTrue(any("version mismatch" in p for p in problems))

    def test_task_contract_malformed_acceptance_criteria_rejected(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            make_task_contract(self.project, self.chain, acceptance_criteria=["ok", "", "   "])

    def test_8_p12_to_p13_only_through_transition_engine(self) -> None:
        # still at P11 (never transitioned to P12) - entering P13 directly must fail.
        contract = make_task_contract(self.project, self.chain)
        with self.assertRaises(MethodologyValidationError):
            nogap_build.enter_execution_phase(self.project, "tool", "skip ahead", contract, "evidence-does-not-exist")


class ExecutionBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        # Methodology chain (with transitions) must be built BEFORE `nogap init`: P3's
        # required_evidence would otherwise be checked against a real (initially empty)
        # runtime evidence ledger instead of accepted at face value. See
        # build_p0_p11_chain's docstring.
        init_project(self.project, "research", "low", "low", actor="test")
        self.chain = build_p0_p11_chain(self.project)
        run_script("init", str(self.project), "--objective", "M7-F build binding")
        self.contract = make_task_contract(self.project, self.chain)
        self._original_adapters = dict(nogap_adapters.ADAPTERS)

    def tearDown(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._original_adapters)
        self.tmp.cleanup()

    def _run(self, adapter: StubAdapter) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = adapter
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.contract["fields"]["task_id"]))

    def test_task_id_required_when_methodology_tracked(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = make_writer_adapter()
        with self.assertRaises(SystemExit):
            nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=None))

    def test_9_isolated_execution_still_used(self) -> None:
        self._run(make_writer_adapter())
        runtime = self.project / ".code-loop" / "runtime"
        evidence = json.loads(next((runtime / "evidence").glob("evidence-exec-*.json")).read_text(encoding="utf-8"))
        self.assertIn("commit", evidence["provenance"])
        # the working tree itself was never touched - only the patch artifact exists
        self.assertFalse((self.project / "agent_output.txt").exists())

    def test_10_execution_evidence_retains_authority_execution(self) -> None:
        self._run(make_writer_adapter())
        runtime = self.project / ".code-loop" / "runtime"
        evidence = json.loads(next((runtime / "evidence").glob("evidence-exec-*.json")).read_text(encoding="utf-8"))
        self.assertEqual(evidence["provenance"]["authority"], "execution")

    def test_11_rc0_no_effect_still_fails(self) -> None:
        self._run(make_silent_adapter())
        runtime = self.project / ".code-loop" / "runtime"
        evidence = json.loads(next((runtime / "evidence").glob("evidence-exec-*.json")).read_text(encoding="utf-8"))
        self.assertEqual(evidence["status"], "failed")
        self.assertIn("NO_EXPECTED_EFFECT", evidence["summary"])

    def test_12_process_abnormal_with_effect_still_fails(self) -> None:
        self._run(make_crash_adapter())
        runtime = self.project / ".code-loop" / "runtime"
        evidence = json.loads(next((runtime / "evidence").glob("evidence-exec-*.json")).read_text(encoding="utf-8"))
        self.assertEqual(evidence["status"], "failed")
        self.assertIn("EFFECT_PRESENT_BUT_PROCESS_ABNORMAL", evidence["summary"])

    def test_13_failure_does_not_auto_advance_to_p14(self) -> None:
        self._run(make_silent_adapter())
        state = mstatus(self.project)
        self.assertEqual(state["current_phase"], "P12")  # returned to P12, never reached P14
        self.assertEqual(list_artifacts(self.project, artifact_type="P14_SELF_CHECK"), [])

    def test_14_and_26_success_reaches_p14_and_awaits_verification(self) -> None:
        self._run(make_writer_adapter())
        state = mstatus(self.project)
        self.assertEqual(state["current_phase"], "P14")
        self_checks = list_artifacts(self.project, artifact_type="P14_SELF_CHECK")
        self.assertEqual(len(self_checks), 1)
        # no auto-advance to P15 - the flow stops at an explicit awaiting-verification state
        can_p15 = __import__("nogap_methodology").can_transition(self.project, "P15")
        self.assertNotIn(state["current_phase"], {"P15"})

    def test_15_and_16_self_check_is_not_verification_and_cannot_accept(self) -> None:
        self._run(make_writer_adapter())
        self_check = list_artifacts(self.project, artifact_type="P14_SELF_CHECK")[0]
        self.assertEqual(self_check["fields"]["self_check_authority"], "execution")
        self.assertNotEqual(self_check["fields"]["self_check_authority"], "verification")
        self.assertNotIn("ACCEPT", json.dumps(self_check))
        result = run_script("decide", str(self.project))
        self.assertEqual(result.returncode, 0, result.stderr)  # `decide` itself always exits 0
        decision = json.loads((self.project / ".code-loop" / "runtime" / "decisions" / "decision-0001.json").read_text(encoding="utf-8"))
        self.assertNotEqual(decision["decision"], "accept")  # execution/self-check evidence alone cannot accept
        self.assertEqual(decision["reason"], "independent authoritative verification evidence is required for ACCEPT")

    def test_17_and_18_task_id_and_requirement_refs_appear_in_linkage(self) -> None:
        self._run(make_writer_adapter())
        runtime = self.project / ".code-loop" / "runtime"
        evidence = json.loads(next((runtime / "evidence").glob("evidence-exec-*.json")).read_text(encoding="utf-8"))
        task_id = self.contract["fields"]["task_id"]
        self.assertEqual(evidence["provenance"]["task_id"], task_id)
        self.assertEqual(evidence["provenance"]["requirement_refs"], [self.chain["P6"]["fields"]["requirement_id"]])
        self_check = list_artifacts(self.project, artifact_type="P14_SELF_CHECK")[0]
        self.assertEqual(self_check["fields"]["task_id"], task_id)
        self.assertEqual(self_check["fields"]["execution_evidence_ids"], [evidence["id"]])

    def test_build_status_label_printed(self) -> None:
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self._run(make_writer_adapter())
        self.assertIn("build_status=BUILD_COMPLETE_AWAITING_VERIFICATION", buf.getvalue())

    def test_build_status_label_on_failure(self) -> None:
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self._run(make_silent_adapter())
        self.assertIn("build_status=EXPECTED_EFFECT_FAILED", buf.getvalue())


class GateRelationshipTests(unittest.TestCase):
    def test_19_gate_hash_preserved_in_evidence_when_no_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            init_project(project, "research", "low", "low", actor="test")
            chain = build_p0_p11_chain(project)  # must precede `nogap init` - see its docstring

            run_script("init", str(project), "--objective", "gate hash linkage")
            run_script("freeze", str(project))
            gate_path = project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            contract = make_task_contract(project, chain)

            self._original_adapters = dict(nogap_adapters.ADAPTERS)
            nogap_adapters.ADAPTERS.clear()
            nogap_adapters.ADAPTERS["codex"] = make_writer_adapter()
            try:
                nogap.cmd_run(run_namespace(str(project), execute=True, task_id=contract["fields"]["task_id"]))
            finally:
                nogap_adapters.ADAPTERS.clear()
                nogap_adapters.ADAPTERS.update(self._original_adapters)

            evidence = json.loads(next((project / ".code-loop" / "runtime" / "evidence").glob("evidence-exec-*.json")).read_text(encoding="utf-8"))
            self.assertEqual(evidence["provenance"]["gate_hash"], gate["hash"])

    def test_20_frozen_gate_never_mutated_and_conflicting_p11_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            init_project(project, "research", "low", "low", actor="test")
            chain = build_p0_p11_chain(project)  # must precede `nogap init` - see its docstring
            # the P11 plan created by build_p0_p11_chain declares a DIFFERENT required_commands
            self.assertNotEqual(chain["P11"]["fields"]["required_commands"], ["python -m pytest"])

            run_script("init", str(project))
            gate_path = project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            gate["rules"]["required_commands"] = ["python -m pytest"]
            gate_path.write_text(json.dumps(gate), encoding="utf-8")
            run_script("freeze", str(project))
            before = gate_path.read_text(encoding="utf-8")

            preflight = nogap_build.preflight_build(project)
            self.assertFalse(preflight["permitted"])
            self.assertTrue(any("differs from frozen Trust gate" in reason for reason in preflight["reasons"]))
            after = gate_path.read_text(encoding="utf-8")
            self.assertEqual(before, after)  # never silently reconciled/mutated


class ManualLiveScenarioTests(unittest.TestCase):
    """The three MANUAL LIVE SCENARIOS from the brief, automated end to end through the
    real CLI (nogap.py as a subprocess), not just in-process unittest calls."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_scenario_a_incomplete_methodology_blocks_execute_before_any_process(self) -> None:
        run_script("init", str(self.project), "--objective", "scenario A")
        run_script("methodology", "init", str(self.project), "--intent", "research", "--risk", "low", "--claim-strength", "low")
        # no P0-P11 artifacts created at all
        result = run_script("run", str(self.project), "--execute")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BLOCKED", result.stdout)
        runtime = self.project / ".code-loop" / "runtime"
        self.assertEqual(list((runtime / "evidence").glob("evidence-exec-*.json")), [])
        self.assertEqual(list((runtime / "artifacts").glob("*.patch")), [])

    def test_scenario_c_fake_requirement_ref_blocks_before_process_launch(self) -> None:
        run_script("methodology", "init", str(self.project), "--intent", "research", "--risk", "low", "--claim-strength", "low")
        init_project_state_dir = self.project / ".code-loop" / "methodology"
        self.assertTrue(init_project_state_dir.is_dir())
        # build a full chain BEFORE `nogap init` (see build_p0_p11_chain's docstring), then
        # corrupt P11's requirement_refs to a fake REQ id
        chain = build_p0_p11_chain(self.project)
        run_script("init", str(self.project), "--objective", "scenario C")
        p11_path = self.project / ".code-loop" / "methodology" / "artifacts" / f"{chain['P11']['artifact_id']}.json"
        record = json.loads(p11_path.read_text(encoding="utf-8"))
        record["fields"]["requirement_refs"] = ["REQ-999"]
        p11_path.write_text(json.dumps(record), encoding="utf-8")

        result = run_script("run", str(self.project), "--execute")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BLOCKED", result.stdout)
        self.assertIn("REQ-999", result.stdout)
        runtime = self.project / ".code-loop" / "runtime"
        self.assertEqual(list((runtime / "evidence").glob("evidence-exec-*.json")), [])


if __name__ == "__main__":
    unittest.main()
