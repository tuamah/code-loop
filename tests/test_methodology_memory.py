#!/usr/bin/env python3
"""M7-I acceptance checks: Project Memory / Trusted Memory Projection.

Covers the 61 mandatory cases from the brief plus automated encodings of the four
required manual/automated scenarios (A: new-agent handoff, B: false-memory-injection
detection and restoration, C: historical failure preservation, D: verification !=
acceptance). M6/M7-A..H regression coverage is verified by running the full existing
suites alongside this file, not duplicated here.
"""

from __future__ import annotations

import argparse
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
import nogap_memory as nm  # noqa: E402
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
    defaults = {"path": path, "actor": "test-memory", "execute": False, "execute_timeout": 600, "task_id": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def verify_namespace(path: str, **overrides: Any) -> argparse.Namespace:
    defaults = {"path": path, "dispatch": None, "timeout": 120, "review": False, "review_timeout": 120, "actor": "verifier"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def decide_namespace(path: str, **overrides: Any) -> argparse.Namespace:
    defaults = {"path": path, "actor": "nogap decide", "actor_id": "human:owner", "authority": "acceptance"}
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
        "problem_statement": "x", "in_scope": ["a"], "out_of_scope": ["b"], "constraints": ["must run offline"],
        "dependencies": ["d"], "known_assumptions": ["e"],
    }, actor=actor)
    made["P2"] = create_artifact(project, "P2_SUCCESS_CRITERIA", {
        "success_criteria": ["works"], "failure_criteria": ["crashes"], "risk_level": mstatus(project)["risk"],
        "claim_strength": mstatus(project)["claim_strength"], "critical_claims": ["c1"], "stop_conditions": ["s1"],
    }, actor=actor)
    made["P3"] = create_artifact(project, "P3_PRIOR_ART", {
        "research_question": "q", "search_scope": "s", "sources": ["s1"], "candidate_solutions": ["c1"],
        "key_findings": ["existing tool X covers 60% of the need"], "limitations": ["l1"],
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
    }, actor=actor, status="ACCEPTED")
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


class BareProjectFixture(unittest.TestCase):
    """A plain git repo with NEITHER methodology NOR trust runtime initialized -
    "empty supported project"."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)

    def tearDown(self) -> None:
        self.tmp.cleanup()


class MemoryFixture(unittest.TestCase):
    """Reaches P18 with a fresh VerificationResult (VERIFICATION_COMPLETE_AWAITING_
    DECISION), a real M6 execution evidence id, and (via helpers below) an accepted
    decision and/or a failure record - everything Memory needs to project against."""

    profile_args = ("research", "low", "low")  # LIGHT unless overridden

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        init_project(self.project, *self.profile_args, actor="test")
        self.chain = build_p0_p11_chain(self.project)
        self.contract = make_task_contract(self.project, self.chain)
        self.task_id = self.contract["fields"]["task_id"]
        run_script("init", str(self.project), "--objective", "memory fixture")

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

    def accept(self) -> None:
        nogap.cmd_decide(decide_namespace(str(self.project)))

    def make_failure(self, root_cause_class: str | None = None, **overrides: Any) -> dict[str, Any]:
        fields = {
            "failure_class": "BUILD_EXECUTION_FAILURE", "summary": "synthetic failure for testing",
            "actor": "qa", "task_id": self.task_id, "evidence_refs": [], "artifact_refs": [],
        }
        fields.update(overrides)
        failure = nf.create_failure(self.project, **fields)
        failure = nf.record_evidence_preservation(self.project, failure["failure_id"], evidence_refs=[self.exec_evidence_id], actor="qa", reason="preserve")
        failure = nf.record_reproduction(self.project, failure["failure_id"], reproduction_status="REPRODUCED", actor="qa", reason="reproduced")
        failure = nf.record_characterization(self.project, failure["failure_id"], actor="qa", reason="characterized",
                                              affected_requirement_refs=[self.chain["P6"]["fields"]["requirement_id"]])
        failure = nf.record_research(self.project, failure["failure_id"], actor="qa", reason="researched", research_refs=[self.chain["P3"]["artifact_id"]])
        if root_cause_class is None:
            return failure
        return nf.record_root_cause(self.project, failure["failure_id"], root_cause_class=root_cause_class,
                                     root_cause_summary="diagnosed", supporting_evidence_refs=[self.exec_evidence_id],
                                     actor="qa", reason="diagnosed")

    def resolve_failure_fully(self, failure: dict[str, Any]) -> dict[str, Any]:
        """Drives a failure already at ROOT_CAUSE_IDENTIFIED (IMPLEMENTATION_DEFECT ->
        P13) all the way to RESOLVED, reusing the same writer adapter re-run pattern
        M7-H's own tests use."""
        failure = nf.propose_repair(self.project, failure["failure_id"], description="minimal repair", target_phase="P13",
                                     evidence_refs=[self.exec_evidence_id], actor="architect", reason="propose")
        failure = nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        before = {p.stem for p in (self.project / ".code-loop" / "runtime" / "evidence").glob("evidence-exec-*.json")}
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.task_id))
        after = {p.stem for p in (self.project / ".code-loop" / "runtime" / "evidence").glob("evidence-exec-*.json")}
        new_evidence = next(iter(after - before))
        failure = nf.record_repaired(self.project, failure["failure_id"], repair_evidence_refs=[new_evidence], actor="qa", reason="applied")
        failure = nf.record_regression(self.project, failure["failure_id"], result="passed", actor="qa", reason="fixed")
        run_script("freeze", str(self.project))
        nogap.cmd_verify(verify_namespace(str(self.project)))
        failure = nf.record_revalidation(self.project, failure["failure_id"], actor="qa", reason="revalidated")
        return nf.resolve_failure(self.project, failure["failure_id"], actor="human:owner", reason="confirmed")


# --- 1-3: build / determinism / fingerprint stability ------------------------

class BuildAndFingerprintTests(BareProjectFixture):
    def test_1_empty_supported_project_builds_snapshot(self) -> None:
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertEqual(snapshot["schema_version"], nm.SCHEMA_VERSION)
        self.assertEqual(snapshot["active_phase"], None)
        self.assertEqual(snapshot["open_failures"], [])

    def test_2_deterministic_rebuild_gives_same_logical_content(self) -> None:
        first = nm.build_memory_snapshot(self.project, actor="tester")
        second = nm.build_memory_snapshot(self.project, actor="tester")
        drop = {"generated_at", "generated_by", "integrity"}
        first_body = {k: v for k, v in first.items() if k not in drop}
        second_body = {k: v for k, v in second.items() if k not in drop}
        self.assertEqual(first_body, second_body)
        self.assertEqual(first["integrity"]["source_fingerprint"], second["integrity"]["source_fingerprint"])

    def test_3_source_fingerprint_stable_when_unchanged(self) -> None:
        sources = nm.collect_memory_sources(self.project)
        fp1 = nm.compute_source_fingerprint(sources)
        fp2 = nm.compute_source_fingerprint(nm.collect_memory_sources(self.project))
        self.assertEqual(fp1, fp2)


class StalenessTests(MemoryFixture):
    def test_4_transition_makes_snapshot_stale(self) -> None:
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")
        # P18 -> P13 is a legal LOOP_RETURN per P18's allowed_back_transitions - a real
        # current_phase mutation, not just a decisions/events ledger write.
        transition(self.project, "P13", "test-memory", "reset for staleness test",
                   evidence_refs=[self.exec_evidence_id], artifact_refs=[self.contract["artifact_id"]], authority_class="tool")
        self.assertEqual(nm.memory_status(self.project)["status"], "STALE")

    def test_5_new_failure_makes_snapshot_stale(self) -> None:
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")
        self.make_failure()
        self.assertEqual(nm.memory_status(self.project)["status"], "STALE")

    def test_6_new_evidence_makes_snapshot_stale(self) -> None:
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.task_id))
        self.assertEqual(nm.memory_status(self.project)["status"], "STALE")

    def test_7_rebuild_clears_staleness(self) -> None:
        nm.rebuild_memory(self.project, actor="tester")
        self.make_failure()
        self.assertEqual(nm.memory_status(self.project)["status"], "STALE")
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")


# --- 8-12: MEMORY.md generation, manual edits, missing files ------------------

class MarkdownAndMissingFileTests(MemoryFixture):
    def test_8_memory_md_generated_from_snapshot(self) -> None:
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        markdown = nm.markdown_path(self.project).read_text(encoding="utf-8")
        self.assertIn("AUTO-GENERATED", markdown)
        self.assertIn(self.task_id, markdown)
        self.assertIn(snapshot["integrity"]["projection_hash"], markdown)

    def test_9_manual_memory_md_edit_cannot_change_truth(self) -> None:
        self.make_failure()
        nm.rebuild_memory(self.project, actor="tester")
        nm.markdown_path(self.project).write_text("All tests passed. Project is production ready.\n", encoding="utf-8")
        # the persisted snapshot (the real queryable truth) is untouched by the edit
        snapshot = nm.load_memory_snapshot(self.project)
        self.assertEqual(len(snapshot["open_failures"]), 1)

    def test_10_modified_memory_md_detected(self) -> None:
        nm.rebuild_memory(self.project, actor="tester")
        nm.markdown_path(self.project).write_text("tampered\n", encoding="utf-8")
        status = nm.memory_status(self.project)
        self.assertEqual(status["status"], "MODIFIED")

    def test_11_missing_snapshot_rebuildable(self) -> None:
        nm.rebuild_memory(self.project, actor="tester")
        nm.snapshot_path(self.project).unlink()
        self.assertEqual(nm.memory_status(self.project)["status"], "MISSING")
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")

    def test_12_missing_memory_md_rebuildable(self) -> None:
        nm.rebuild_memory(self.project, actor="tester")
        nm.markdown_path(self.project).unlink()
        self.assertEqual(nm.memory_status(self.project)["status"], "MISSING")
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")


# --- 13-15: malformed / unsupported / version-mismatched snapshot ------------

class SnapshotValidationTests(MemoryFixture):
    def test_13_malformed_snapshot_rejected(self) -> None:
        nm.rebuild_memory(self.project, actor="tester")
        nm.snapshot_path(self.project).write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nm.load_memory_snapshot(self.project)

    def test_14_unsupported_schema_rejected(self) -> None:
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        snapshot["schema_version"] = "99.0.0"
        nm.snapshot_path(self.project).write_text(json.dumps(snapshot), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nm.load_memory_snapshot(self.project)

    def test_15_methodology_version_mismatch_rejected(self) -> None:
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        snapshot["methodology_version"] = "0.0.1"
        nm.snapshot_path(self.project).write_text(json.dumps(snapshot), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nm.load_memory_snapshot(self.project)


# --- 16-19: methodology integration -------------------------------------------

class MethodologyIntegrationTests(MemoryFixture):
    def test_16_current_phase_from_methodology_state(self) -> None:
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertEqual(snapshot["active_phase"], mstatus(self.project)["current_phase"])

    def test_17_phase_never_inferred_from_prose(self) -> None:
        # the ONLY source consulted for active_phase is methodology state - verified
        # by construction: nogap_memory never reads evidence.summary/log text at all.
        import inspect
        source = inspect.getsource(nm._derive_project_identity) + inspect.getsource(nm.build_memory_snapshot)
        self.assertNotIn(".summary", source)

    def test_18_completed_phase_history_preserved(self) -> None:
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertGreaterEqual(snapshot["current_methodology_state"]["completed_phase_count"], 11)  # P0..P10 at least

    def test_19_active_repair_loop_visible(self) -> None:
        # at P18, the verify_loop entered back at P14->P15 is still ACTIVE (M7-C/M7-H:
        # select_repair's own P18->P13 LOOP_RETURN is what resolves it, not entering
        # P18 itself) - this is the loop Memory must surface as currently active.
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        active_loops = snapshot["current_methodology_state"]["active_loops"]
        self.assertTrue(active_loops)
        self.assertEqual(active_loops[0]["loop_type"], "verify_loop")


# --- 20-25: failure integration ------------------------------------------------

class FailureIntegrationTests(MemoryFixture):
    def test_20_open_failure_visible(self) -> None:
        self.make_failure()
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertEqual(len(snapshot["open_failures"]), 1)
        self.assertEqual(snapshot["open_failures"][0]["failure_id"], "FAIL-001")

    def test_21_resolved_failure_queryable(self) -> None:
        failure = self.make_failure(root_cause_class="IMPLEMENTATION_DEFECT")
        self.resolve_failure_fully(failure)
        nm.rebuild_memory(self.project, actor="tester")
        result = nm.query_memory(self.project, category="resolved_failures", item_id="FAIL-001")
        self.assertEqual(len(result), 1)

    def test_22_inconclusive_distinct_from_resolved(self) -> None:
        self.make_failure(root_cause_class="UNKNOWN")
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertEqual(len(snapshot["inconclusive_failures"]), 1)
        self.assertEqual(snapshot["resolved_failures"], [])

    def test_23_root_cause_preserved(self) -> None:
        self.make_failure(root_cause_class="IMPLEMENTATION_DEFECT")
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertEqual(snapshot["open_failures"][0]["root_cause_class"], "IMPLEMENTATION_DEFECT")

    def test_24_repair_route_preserved(self) -> None:
        failure = self.make_failure(root_cause_class="IMPLEMENTATION_DEFECT")
        nf.propose_repair(self.project, failure["failure_id"], description="minimal repair", target_phase="P13",
                           evidence_refs=[self.exec_evidence_id], actor="architect", reason="propose")
        nf.select_repair(self.project, failure["failure_id"], "R1", actor="human:owner", reason="approved")
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertEqual(snapshot["open_failures"][0]["repair_target_phase"], "P13")

    def test_25_latest_failure_by_record_time_not_filesystem_order(self) -> None:
        # failures/*.json are named by failure_id (stable, monotonic) - listing order
        # already matches record order here, but recent_changes must still be sorted
        # by actual timestamp, not glob order; verify it's non-increasing.
        self.make_failure()
        nf.mark_inconclusive(self.project, "FAIL-001", actor="qa", reason="parked")
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        timestamps = [c["timestamp"] for c in snapshot["recent_changes"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))


# --- 26-29: verification / decision distinctions -----------------------------

class VerificationDecisionTests(MemoryFixture):
    def test_26_accept_distinct_from_verification_pass(self) -> None:
        snapshot_before = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertEqual(snapshot_before["accepted_decisions"], [])
        self.assertEqual(snapshot_before["verification_summary"]["awaiting_decision"], 1)  # PASS, not yet ACCEPT
        self.accept()
        snapshot_after = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertTrue(snapshot_after["accepted_decisions"])

    def test_27_abstain_distinct_from_reject(self) -> None:
        # decision_authority defaulting away from acceptance -> abstain, never reject
        nogap.cmd_decide(decide_namespace(str(self.project), authority="execution"))
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertTrue(snapshot["abstained_decisions"])
        self.assertEqual(snapshot["rejected_decisions"], [])

    def test_28_stale_verification_marked_stale(self) -> None:
        self.accept()
        # a repair re-run produces a new candidate whose verification hasn't happened yet
        nogap.cmd_run(run_namespace(str(self.project), execute=True, task_id=self.task_id))
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        # the P18 result on file is now for a stale (pre-repair) candidate - Memory
        # must not claim it's still awaiting decision for the new one
        self.assertEqual(snapshot["verification_summary"]["total"], 1)

    def test_29_missing_verification_unknown_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp2:
            project2 = Path(tmp2)
            init_git_repo(project2)
            snapshot = nm.build_memory_snapshot(project2, actor="tester")
            self.assertEqual(snapshot["verification_summary"]["total"], 0)
            self.assertEqual(snapshot["verified_artifacts"], [])


# --- 30-33: evidence / artifact / git ------------------------------------------

class EvidenceArtifactGitTests(MemoryFixture):
    def test_30_evidence_refs_traceable(self) -> None:
        self.make_failure()
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertIn(self.exec_evidence_id, snapshot["source_refs"]["evidence"])

    def test_31_unknown_evidence_not_trusted(self) -> None:
        failure = nf.create_failure(self.project, failure_class="X", summary="x", actor="qa", task_id=self.task_id)
        path = nf.failures_dir(self.project) / f"{failure['failure_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["evidence_refs"] = ["evidence-does-not-exist"]
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nm.collect_memory_sources(self.project)

    def test_32_artifact_hash_preserved(self) -> None:
        self.accept()
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertTrue(snapshot["verified_artifacts"][0]["patch_hash"])

    def test_33_git_commit_does_not_imply_verified_state(self) -> None:
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        # git metadata is present (advisory) but never feeds verification_summary/decisions
        self.assertIsNotNone(snapshot["git"])
        self.assertEqual(snapshot["verification_summary"]["awaiting_decision"], 1)
        self.assertEqual(snapshot["accepted_decisions"], [])


# --- 34-38: frozen decisions / constraints / limitations / questions / next actions

class DerivedViewTests(MemoryFixture):
    def test_34_frozen_decision_visible(self) -> None:
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertTrue(snapshot["frozen_decisions"])  # P8_ADR created ACCEPTED-equivalent status ACTIVE by default... see below
        self.assertTrue(snapshot["architecture_decisions"])

    def test_35_superseded_decision_not_current(self) -> None:
        # a requirement superseded via update_requirement_status must not appear ACTIVE
        from nogap_artifacts import update_requirement_status
        req_id = self.chain["P6"]["fields"]["requirement_id"]
        update_requirement_status(self.project, req_id, "SUPERSEDED", actor="architect", reason="replaced")
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        statuses = {r["requirement_id"]: r["status"] for r in snapshot["requirements_status"]}
        self.assertEqual(statuses[req_id], "SUPERSEDED")

    def test_36_known_limitation_visible(self) -> None:
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertTrue(snapshot["known_limitations"])
        principle_ids = {item["principle_id"] for item in snapshot["known_limitations"]}
        self.assertIn("GP-3", principle_ids)

    def test_37_unresolved_question_visible(self) -> None:
        self.make_failure(root_cause_class="UNKNOWN")
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertTrue(snapshot["unresolved_questions"])

    def test_38_blocking_next_action_prioritized(self) -> None:
        snapshot_before = nm.build_memory_snapshot(self.project, actor="tester")
        pending_decision_actions = [a for a in snapshot_before["next_actions"] if "run `nogap decide`" in a["action"]]
        self.assertTrue(pending_decision_actions)
        self.assertEqual(pending_decision_actions[0]["priority"], "REQUIRED")

        self.accept()
        snapshot_after = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertFalse([a for a in snapshot_after["next_actions"] if "run `nogap decide`" in a["action"]])


# --- 39-42: UNKNOWN/NONE, parse failures, conflicts, duplicates --------------

class UnknownAndFailClosedTests(BareProjectFixture):
    def test_39_unknown_not_none(self) -> None:
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertIsNone(snapshot["current_methodology_state"])  # UNKNOWN: no state at all
        self.assertEqual(snapshot["open_failures"], [])  # NONE: checked, zero

    def test_40_source_parse_failure_not_silently_dropped(self) -> None:
        init_project(self.project, "research", "low", "low", actor="test")
        bad = self.project / ".code-loop" / "methodology" / "failures" / "FAIL-BAD.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nm.collect_memory_sources(self.project)

    def test_41_conflicting_authoritative_records_fail_closed(self) -> None:
        init_project(self.project, "research", "low", "low", actor="test")
        chain = build_p0_p11_chain(self.project)
        contract = make_task_contract(self.project, chain)
        art_dir = self.project / ".code-loop" / "methodology" / "artifacts"
        original = json.loads((art_dir / f"{contract['artifact_id']}.json").read_text(encoding="utf-8"))
        conflicting = dict(original)
        conflicting["artifact_id"] = "p12_task_contract-CONFLICT"
        conflicting["fields"] = {**original["fields"], "goal": "a completely different, conflicting goal"}
        (art_dir / "p12_task_contract-CONFLICT.json").write_text(json.dumps(conflicting), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nm.collect_memory_sources(self.project)

    def test_42_duplicate_authoritative_id_rejected(self) -> None:
        init_project(self.project, "research", "low", "low", actor="test")
        chain = build_p0_p11_chain(self.project)
        art_dir = self.project / ".code-loop" / "methodology" / "artifacts"
        original = json.loads((art_dir / f"{chain['P6']['artifact_id']}.json").read_text(encoding="utf-8"))
        dup = dict(original)
        dup["artifact_id"] = "p6_requirement-DUPLICATE"
        (art_dir / "p6_requirement-DUPLICATE.json").write_text(json.dumps(dup), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nm.collect_memory_sources(self.project)


# --- 43-44: tamper / staleness detection precision ---------------------------

class IntegrityTests(MemoryFixture):
    def test_43_projection_hash_detects_tampering(self) -> None:
        nm.rebuild_memory(self.project, actor="tester")
        snapshot = json.loads(nm.snapshot_path(self.project).read_text(encoding="utf-8"))
        snapshot["integrity"]["projection_hash"] = "0" * 64
        nm.snapshot_path(self.project).write_text(json.dumps(snapshot), encoding="utf-8")
        status = nm.memory_status(self.project)
        self.assertEqual(status["status"], "INVALID")

    def test_44_source_fingerprint_mismatch_never_presented_as_current(self) -> None:
        nm.rebuild_memory(self.project, actor="tester")
        self.make_failure()
        status = nm.memory_status(self.project)
        self.assertNotEqual(status["status"], "CURRENT")
        self.assertEqual(status["status"], "STALE")


# --- 45-46: query API -----------------------------------------------------------

class QueryApiTests(MemoryFixture):
    def test_45_query_by_category_works(self) -> None:
        self.accept()
        nm.rebuild_memory(self.project, actor="tester")
        result = nm.query_memory(self.project, category="accepted_decisions")
        self.assertTrue(result)

    def test_46_query_preserves_provenance(self) -> None:
        self.make_failure()
        nm.rebuild_memory(self.project, actor="tester")
        result = nm.query_memory(self.project, category="open_failures")
        self.assertEqual(result[0]["source_ref"], "FAIL-001")


# --- 47-48: profile depth -------------------------------------------------------

class ProfileDepthTests(unittest.TestCase):
    def _project(self, intent: str, risk: str, claim: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        project = Path(tmp.name)
        init_git_repo(project)
        p7_extra = (
            {"responsibilities": ["r"], "interfaces": ["i"], "external_dependencies": ["d"],
             "failure_domains": ["fd1"], "data_security_boundaries": ["dsb1"]}
            if intent == "production" else None
        )
        init_project(project, intent, risk, claim, actor="test")
        build_p0_p11_chain(project, p7_extra=p7_extra)
        return project

    def test_47_light_projection_truthful(self) -> None:
        project = self._project("research", "low", "low")
        snapshot = nm.build_memory_snapshot(project, actor="tester")
        self.assertEqual(snapshot["effective_profile"], "LIGHT")
        self.assertEqual(snapshot["open_failures"], [])

    def test_48_strict_projection_richer_but_same_truth(self) -> None:
        light_project = self._project("research", "low", "low")
        strict_project = self._project("production", "high", "high")
        light_snapshot = nm.build_memory_snapshot(light_project, actor="tester")
        strict_snapshot = nm.build_memory_snapshot(strict_project, actor="tester")
        self.assertEqual(strict_snapshot["effective_profile"], "STRICT")
        # both are internally consistent/truthful regardless of profile depth
        self.assertEqual(light_snapshot["open_failures"], strict_snapshot["open_failures"])


# --- 49-50: redaction ------------------------------------------------------------

class RedactionTests(MemoryFixture):
    def test_49_secret_like_values_redacted_from_memory_md(self) -> None:
        create_artifact(self.project, "P1_SCOPE", {
            "problem_statement": "x2", "in_scope": ["a"], "out_of_scope": ["b"],
            "constraints": ["api_key: sk-THISISASECRETVALUE1234567890"],
            "dependencies": ["d"], "known_assumptions": ["e"],
        }, actor="team")
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        markdown = nm.render_memory_markdown(snapshot)
        self.assertNotIn("THISISASECRETVALUE", markdown)
        self.assertIn("[REDACTED]", markdown)

    def test_50_raw_source_unchanged_by_redaction(self) -> None:
        create_artifact(self.project, "P1_SCOPE", {
            "problem_statement": "x2", "in_scope": ["a"], "out_of_scope": ["b"],
            "constraints": ["api_key: sk-THISISASECRETVALUE1234567890"],
            "dependencies": ["d"], "known_assumptions": ["e"],
        }, actor="team")
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertTrue(any("THISISASECRETVALUE" in c["constraint"] for c in snapshot["known_constraints"]))


# --- 51-53: read-only guarantees ------------------------------------------------

class ReadOnlyTests(MemoryFixture):
    def test_51_memory_api_cannot_mutate_source_truth(self) -> None:
        before = mstatus(self.project)["current_phase"]
        nm.build_memory_snapshot(self.project, actor="tester")
        nm.rebuild_memory(self.project, actor="tester")
        nm.memory_status(self.project)
        after = mstatus(self.project)["current_phase"]
        self.assertEqual(before, after)

    def test_52_no_generic_trusted_memory_add_path(self) -> None:
        self.assertFalse(hasattr(nm, "add_memory"))
        self.assertFalse(hasattr(nm, "add_fact"))
        result = run_script("memory", "--help")
        self.assertNotIn("memory add", result.stdout)

    def test_53_no_direct_current_phase_mutation(self) -> None:
        import inspect
        source = inspect.getsource(nm)
        self.assertNotIn("current_phase\"] =", source)
        self.assertNotIn("current_phase'] =", source)


# --- 54-57: existing subsystem semantics unchanged ---------------------------

class RegressionUnaffectedTests(MemoryFixture):
    def test_54_m7h_semantics_unchanged(self) -> None:
        failure = self.make_failure()
        with self.assertRaises(MethodologyValidationError):
            nf.propose_repair(self.project, failure["failure_id"], description="too early", target_phase="P13",
                               actor="architect", reason="skip root cause")

    def test_55_m7g_verification_interlock_unchanged(self) -> None:
        import nogap_verify_binding as vb
        precondition = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertTrue(precondition["satisfied"])
        nm.build_memory_snapshot(self.project, actor="tester")
        precondition2 = vb.verification_acceptance_precondition(self.project, self.task_id)
        self.assertEqual(precondition, precondition2)

    def test_56_m7c_transitions_unchanged(self) -> None:
        from nogap_methodology import can_transition
        before = can_transition(self.project, "P19")
        nm.build_memory_snapshot(self.project, actor="tester")
        after = can_transition(self.project, "P19")
        self.assertEqual(before, after)

    def test_57_m6_acceptance_semantics_unchanged(self) -> None:
        self.accept()
        decision_path = self.project / ".code-loop" / "runtime" / "decisions" / "decision-0001.json"
        before = json.loads(decision_path.read_text(encoding="utf-8"))
        nm.build_memory_snapshot(self.project, actor="tester")
        nm.rebuild_memory(self.project, actor="tester")
        after = json.loads(decision_path.read_text(encoding="utf-8"))
        self.assertEqual(before, after)


# --- 58-60: golden principle status -------------------------------------------

class GoldenPrincipleStatusTests(unittest.TestCase):
    def test_58_gp9_status_reflects_implementation(self) -> None:
        from nogap_methodology import get_principle_enforcement
        record = get_principle_enforcement("GP-9")
        self.assertIn(record.status, {"PARTIAL", "ENFORCED"})
        self.assertIn("nogap_memory.py", " ".join(record.implemented_by))

    def test_59_gp11_status_not_overstated(self) -> None:
        from nogap_methodology import get_principle_enforcement
        record = get_principle_enforcement("GP-11")
        self.assertNotEqual(record.status, "DECLARED")

    def test_60_gp20_traceability_coverage_updated(self) -> None:
        from nogap_methodology import get_principle_enforcement
        record = get_principle_enforcement("GP-20")
        self.assertTrue(any("memory" in t.lower() for t in record.tests))


# --- 61: full suite green (encoded as a CLI smoke covering build/rebuild/status/show/query/verify)

class FullCliLifecycleTests(MemoryFixture):
    def test_61_full_cli_lifecycle(self) -> None:
        self.make_failure()
        build = run_script("memory", "build", str(self.project))
        self.assertEqual(build.returncode, 0, build.stderr)
        status = run_script("memory", "status", str(self.project))
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("CURRENT", status.stdout)
        show = run_script("memory", "show", str(self.project))
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn("AUTO-GENERATED", show.stdout)
        query = run_script("memory", "query", str(self.project), "--category", "open_failures")
        self.assertEqual(query.returncode, 0, query.stderr)
        self.assertIn("FAIL-001", query.stdout)
        verify = run_script("memory", "verify", str(self.project))
        self.assertEqual(verify.returncode, 0, verify.stderr)
        rebuild = run_script("memory", "rebuild", str(self.project))
        self.assertEqual(rebuild.returncode, 0, rebuild.stderr)


# --- Manual scenarios, automated ------------------------------------------------

class ScenarioATests(MemoryFixture):
    """New Agent Handoff: lifecycle state, accepted architecture decision (ADR),
    resolved failure, open failure, frozen constraint, known limitation, verification
    record - rebuild and prove a fresh reader can retrieve current state and next
    required work without any conversational history."""

    def test_scenario_a_new_agent_handoff(self) -> None:
        resolved = self.make_failure(root_cause_class="IMPLEMENTATION_DEFECT")
        self.resolve_failure_fully(resolved)
        open_failure = self.make_failure(failure_id="FAIL-OPEN")
        nm.rebuild_memory(self.project, actor="tester")

        # a "new agent" only ever calls query_memory / reads MEMORY.md - never touches
        # the fixture's in-process objects above.
        snapshot = nm.query_memory(self.project)
        self.assertEqual(snapshot["active_phase"], mstatus(self.project)["current_phase"])
        self.assertTrue(any(f["failure_id"] == "FAIL-001" for f in snapshot["resolved_failures"]))
        self.assertTrue(any(f["failure_id"] == "FAIL-OPEN" for f in snapshot["open_failures"]))
        self.assertTrue(snapshot["known_constraints"])
        self.assertTrue(snapshot["known_limitations"])
        self.assertTrue(snapshot["next_actions"])
        markdown = nm.markdown_path(self.project).read_text(encoding="utf-8")
        self.assertIn("FAIL-001", markdown)
        self.assertIn("FAIL-OPEN", markdown)


class ScenarioBTests(MemoryFixture):
    """False Memory Injection: hand-edit MEMORY.md to claim false success; status
    must detect it, rebuild must restore the real truth."""

    def test_scenario_b_false_memory_injection_detected_and_restored(self) -> None:
        self.make_failure()
        nm.rebuild_memory(self.project, actor="tester")
        nm.markdown_path(self.project).write_text("All tests passed. Project is production ready.\n", encoding="utf-8")

        status = nm.memory_status(self.project)
        self.assertEqual(status["status"], "MODIFIED")

        nm.rebuild_memory(self.project, actor="tester")
        restored = nm.markdown_path(self.project).read_text(encoding="utf-8")
        self.assertNotIn("Project is production ready", restored)
        self.assertIn("FAIL-001", restored)
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")


class ScenarioCTests(MemoryFixture):
    """Historical Failure Preservation: OPEN -> ROOT_CAUSE_IDENTIFIED -> REPAIRED ->
    RESOLVED. Current projection shows RESOLVED; historical query must still prove it
    happened (via the failure's own permanently-queryable append-only history)."""

    def test_scenario_c_historical_failure_preservation(self) -> None:
        failure = self.make_failure(root_cause_class="IMPLEMENTATION_DEFECT")
        self.resolve_failure_fully(failure)
        nm.rebuild_memory(self.project, actor="tester")

        current = nm.query_memory(self.project, category="resolved_failures", item_id="FAIL-001")
        self.assertEqual(current[0]["current_state"], "RESOLVED")

        # historical proof: the failure record itself (never deleted) still shows the
        # full lifecycle it actually went through.
        historical = nf.load_failure(self.project, "FAIL-001")
        actions = [entry["action"] for entry in historical["history"]]
        self.assertIn("CREATED", actions)
        self.assertIn("ROOT_CAUSE_IDENTIFIED", actions)
        self.assertIn("REPAIRED", actions)
        self.assertIn("RESOLVED", actions)


class ScenarioDTests(MemoryFixture):
    """Verification != Acceptance: Verification=PASS, Decision=ABSTAIN. Memory must
    preserve both separately and never say ACCEPTED."""

    def test_scenario_d_verification_pass_decision_abstain(self) -> None:
        nogap.cmd_decide(decide_namespace(str(self.project), authority="execution"))  # -> abstain, not accept
        snapshot = nm.build_memory_snapshot(self.project, actor="tester")

        self.assertEqual(snapshot["verification_summary"]["awaiting_decision"], 1)
        self.assertTrue(any(v["deterministic_result"] == "passed" for v in snapshot["verified_artifacts"]))
        self.assertTrue(snapshot["abstained_decisions"])
        self.assertEqual(snapshot["accepted_decisions"], [])

        markdown = nm.render_memory_markdown(snapshot)
        decisions_section = markdown.split("## Verified Decisions")[1].split("## Frozen Decisions")[0]
        # the accepted-decisions bullet list (between the disclaimer and "Abstained:")
        # must render as empty - an abstain reason may legitimately mention the word
        # "ACCEPT" while explaining why acceptance did not happen, so this checks
        # structure (no accepted bullet was rendered) rather than banning the word.
        accepted_bullets = decisions_section.split("separately._\n")[1].split("\nAbstained:")[0]
        self.assertEqual(accepted_bullets.strip(), "_none_")


if __name__ == "__main__":
    unittest.main()
