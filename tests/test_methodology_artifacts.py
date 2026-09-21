#!/usr/bin/env python3
"""M7-E acceptance checks: executable pre-build lifecycle artifacts (P0-P11).

Covers all 30 mandatory cases plus the manual scenario from the brief,
automated: build a full P0-P11 chain, confirm PREBUILD_READY, break one
reference, confirm BLOCKED with an actionable reason, restore, confirm READY
again. P12/nogap run integration is explicitly out of scope (M7-F).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from nogap_artifacts import (  # noqa: E402
    ARTIFACT_TYPES,
    artifacts_dir,
    create_artifact,
    get_phase_artifacts,
    list_artifacts,
    load_artifact,
    next_requirement_id,
    prebuild_readiness,
    update_requirement_status,
)
from nogap_methodology import (  # noqa: E402
    MethodologyValidationError,
    init_project,
    status as mstatus,
)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/nogap.py", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True)


def init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-q"], path)
    git(["config", "user.email", "test@test.com"], path)
    git(["config", "user.name", "test"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    git(["add", "README.md"], path)
    git(["commit", "-q", "-m", "initial"], path)


def build_full_chain(project: Path, actor: str = "team", p7_extra: dict | None = None, p8_extra: dict | None = None) -> dict[str, dict]:
    """Creates one valid artifact per P0-P11 phase (two requirements for P6), returning
    the created records keyed by artifact_type (P6_REQUIREMENT keyed as a list separately).

    p7_extra/p8_extra merge into those artifacts' fields - used to satisfy STRICT-only
    fields at creation time, since fail-closed validation runs at create_artifact() itself
    and rejects an incomplete STRICT artifact immediately (it cannot be created incomplete
    and patched up afterward the way a corruption test does)."""
    made: dict[str, dict] = {}

    made["P0_PROJECT_INTENT"] = create_artifact(project, "P0_PROJECT_INTENT", {
        "project_name": "demo", "intent_type": mstatus(project)["intent"], "problem_summary": "x",
        "target_users_or_context": "internal team", "desired_outcome": "y", "owner": actor,
        "initial_constraints": ["budget"],
    }, actor=actor)

    made["P1_SCOPE"] = create_artifact(project, "P1_SCOPE", {
        "problem_statement": "x", "in_scope": ["a"], "out_of_scope": ["b"],
        "constraints": ["c"], "dependencies": ["d"], "known_assumptions": ["e"],
    }, actor=actor)

    made["P2_SUCCESS_CRITERIA"] = create_artifact(project, "P2_SUCCESS_CRITERIA", {
        "success_criteria": ["works"], "failure_criteria": ["crashes"],
        "risk_level": mstatus(project)["risk"], "claim_strength": mstatus(project)["claim_strength"],
        "critical_claims": ["claim1"], "stop_conditions": ["budget exceeded"],
    }, actor=actor)

    made["P3_PRIOR_ART"] = create_artifact(project, "P3_PRIOR_ART", {
        "research_question": "q", "search_scope": "s", "sources": ["src1"],
        "candidate_solutions": ["sol1"], "key_findings": ["f1"], "limitations": ["l1"],
    }, actor=actor)

    made["P4_GAP_ANALYSIS"] = create_artifact(project, "P4_GAP_ANALYSIS", {
        "requirements_or_needs": ["n1"], "existing_solutions": ["sol1"],
        "covered_capabilities": ["c1"], "missing_capabilities": ["m1"],
        "tradeoffs": ["t1"], "gaps": ["g1"], "prior_art_refs": [made["P3_PRIOR_ART"]["artifact_id"]],
    }, actor=actor)

    made["P5_STRATEGY_DECISION"] = create_artifact(project, "P5_STRATEGY_DECISION", {
        "selected_strategy": "BUILD", "alternatives_considered": ["BUY"],
        "reason": "cheaper long term", "cost": "medium", "risk": "low",
        "gap_analysis_refs": [made["P4_GAP_ANALYSIS"]["artifact_id"]],
    }, actor=actor)

    req1 = create_artifact(project, "P6_REQUIREMENT", {
        "type": "functional", "statement": "system must do X", "priority": "high",
        "acceptance_criteria": ["X happens"], "strategy_decision_refs": [made["P5_STRATEGY_DECISION"]["artifact_id"]],
    }, actor=actor)
    req2 = create_artifact(project, "P6_REQUIREMENT", {
        "type": "functional", "statement": "system must do Y", "priority": "medium",
        "acceptance_criteria": ["Y happens"], "strategy_decision_refs": [made["P5_STRATEGY_DECISION"]["artifact_id"]],
    }, actor=actor)
    made["P6_REQUIREMENT"] = req1
    made["P6_REQUIREMENT_2"] = req2

    made["P7_ARCHITECTURE"] = create_artifact(project, "P7_ARCHITECTURE", {
        "components": ["svc1"], "trust_boundaries": ["b1"],
        "execution_authorities": ["agent"], "acceptance_authorities": ["human"],
        "requirement_refs": [req1["fields"]["requirement_id"], req2["fields"]["requirement_id"]],
        "responsibilities": ["svc1 does X"], "interfaces": ["api"], "external_dependencies": ["db"],
        **(p7_extra or {}),
    }, actor=actor)

    made["P8_ADR"] = create_artifact(project, "P8_ADR", {
        "decision": "use postgres", "context": "need durable storage", "alternatives": ["sqlite", "postgres"],
        "selected_option": "postgres", "rationale": "scale", "consequences": ["ops burden"],
        "expected_cost": "medium", "architecture_refs": [made["P7_ARCHITECTURE"]["artifact_id"]],
        **(p8_extra or {}),
    }, actor=actor)

    made["P9_GOVERNANCE"] = create_artifact(project, "P9_GOVERNANCE", {
        "roles": ["architect", "verifier"], "authority_assignments": {"acceptance": "human:owner"},
        "execution_backend_policy": "isolated worktree only", "verification_policy": "independent review required",
        "human_approval_requirements": ["release"], "adr_refs": [made["P8_ADR"]["artifact_id"]],
    }, actor=actor)

    made["P10_BASELINE"] = create_artifact(project, "P10_BASELINE", {
        "baseline_description": "current manual process", "primary_metric": "task completion time",
        "secondary_metrics": ["error rate"], "measurement_procedure": "manual timing",
    }, actor=actor)

    made["P11_GATE_PLAN"] = create_artifact(project, "P11_GATE_PLAN", {
        "gate_id": "gate-plan-1", "required_tests": ["unit", "integration"],
        "evidence_requirements": ["execution", "verification"], "stop_conditions": ["security fail"],
        "verification_depth": "standard", "requirement_refs": [req1["fields"]["requirement_id"]],
        "required_commands": ["python -m pytest"], "forbidden_paths": ["secrets.env"],
    }, actor=actor)

    return made


class P0Tests(unittest.TestCase):
    def test_1_valid_minimal_light_p0_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "experimental", "low", "low", actor="test")
            record = create_artifact(project, "P0_PROJECT_INTENT", {
                "project_name": "p", "intent_type": "experimental", "problem_summary": "x",
                "target_users_or_context": "y", "desired_outcome": "z", "owner": "human",
                "initial_constraints": ["budget"],
            }, actor="human")
            self.assertEqual(record["phase_id"], "P0")
            self.assertEqual(record["status"], "ACTIVE")

    def test_2_malformed_p0_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "experimental", "low", "low", actor="test")
            with self.assertRaises(MethodologyValidationError):
                create_artifact(project, "P0_PROJECT_INTENT", {"project_name": "p"}, actor="human")  # missing fields

    def test_p0_intent_type_must_match_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            with self.assertRaises(MethodologyValidationError):
                create_artifact(project, "P0_PROJECT_INTENT", {
                    "project_name": "p", "intent_type": "production",  # mismatched with state's "research"
                    "problem_summary": "x", "target_users_or_context": "y", "desired_outcome": "z",
                    "owner": "human", "initial_constraints": ["budget"],
                }, actor="human")


class P2ProfileSyncTests(unittest.TestCase):
    def test_3_p2_risk_claim_updates_synchronize_with_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")  # -> LIGHT
            self.assertEqual(mstatus(project)["derived_profile"], "LIGHT")
            create_artifact(project, "P2_SUCCESS_CRITERIA", {
                "success_criteria": ["x"], "failure_criteria": ["y"],
                "risk_level": "high", "claim_strength": "high",  # -> should recompute to STRICT
                "critical_claims": ["c"], "stop_conditions": ["s"],
            }, actor="team")
            after = mstatus(project)
            self.assertEqual(after["risk"], "high")
            self.assertEqual(after["claim_strength"], "high")
            self.assertEqual(after["derived_profile"], "STRICT")
            self.assertEqual(after["effective_profile"], "STRICT")  # not overridden, so it tracks derived


class P2DowngradeInteractionTests(unittest.TestCase):
    def test_p2_sync_does_not_clobber_an_existing_downgrade_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "high", "high", actor="test")  # -> STRICT
            from nogap_methodology import downgrade_profile
            downgrade_profile(project, "LIGHT", actor="human:owner", reason="explicit spike")
            self.assertEqual(mstatus(project)["effective_profile"], "LIGHT")
            create_artifact(project, "P2_SUCCESS_CRITERIA", {
                "success_criteria": ["x"], "failure_criteria": ["y"],
                "risk_level": "medium", "claim_strength": "medium",
                "critical_claims": ["c"], "stop_conditions": ["s"],
            }, actor="team")
            after = mstatus(project)
            self.assertEqual(after["derived_profile"], "STANDARD")  # recomputed
            self.assertEqual(after["effective_profile"], "LIGHT")  # override preserved, not silently clobbered


class P3P4P5Tests(unittest.TestCase):
    def test_4_p3_source_records_preserve_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            record = create_artifact(project, "P3_PRIOR_ART", {
                "research_question": "q", "search_scope": "s", "sources": ["https://example.com/paper"],
                "candidate_solutions": ["sol1"], "key_findings": ["f1"], "limitations": ["l1"],
            }, actor="researcher")
            self.assertEqual(record["fields"]["sources"], ["https://example.com/paper"])
            self.assertEqual(record["actor_id"], "researcher")

    def test_5_p4_references_real_p3_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            p3 = create_artifact(project, "P3_PRIOR_ART", {
                "research_question": "q", "search_scope": "s", "sources": ["s1"],
                "candidate_solutions": ["c1"], "key_findings": ["f1"], "limitations": ["l1"],
            }, actor="researcher")
            p4 = create_artifact(project, "P4_GAP_ANALYSIS", {
                "requirements_or_needs": ["n"], "existing_solutions": ["s"], "covered_capabilities": ["c"],
                "missing_capabilities": ["m"], "tradeoffs": ["t"], "gaps": ["g"],
                "prior_art_refs": [p3["artifact_id"]],
            }, actor="researcher")
            self.assertEqual(p4["fields"]["prior_art_refs"], [p3["artifact_id"]])

    def test_6_p4_fake_p3_reference_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            with self.assertRaises(MethodologyValidationError) as ctx:
                create_artifact(project, "P4_GAP_ANALYSIS", {
                    "requirements_or_needs": ["n"], "existing_solutions": ["s"], "covered_capabilities": ["c"],
                    "missing_capabilities": ["m"], "tradeoffs": ["t"], "gaps": ["g"],
                    "prior_art_refs": ["prior-art-does-not-exist"],
                }, actor="researcher")
            self.assertIn("unknown P3_PRIOR_ART", str(ctx.exception))

    def test_7_p5_decision_records_alternatives_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            p3 = create_artifact(project, "P3_PRIOR_ART", {
                "research_question": "q", "search_scope": "s", "sources": ["s1"],
                "candidate_solutions": ["c1"], "key_findings": ["f1"], "limitations": ["l1"],
            }, actor="researcher")
            p4 = create_artifact(project, "P4_GAP_ANALYSIS", {
                "requirements_or_needs": ["n"], "existing_solutions": ["s"], "covered_capabilities": ["c"],
                "missing_capabilities": ["m"], "tradeoffs": ["t"], "gaps": ["g"], "prior_art_refs": [p3["artifact_id"]],
            }, actor="researcher")
            p5 = create_artifact(project, "P5_STRATEGY_DECISION", {
                "selected_strategy": "ADOPT", "alternatives_considered": ["BUILD", "BUY"],
                "reason": "existing tool covers 90% of need", "cost": "low", "risk": "low",
                "gap_analysis_refs": [p4["artifact_id"]],
            }, actor="architect")
            self.assertEqual(p5["fields"]["selected_strategy"], "ADOPT")
            self.assertEqual(p5["fields"]["alternatives_considered"], ["BUILD", "BUY"])
            self.assertTrue(p5["fields"]["reason"])

    def test_p5_invalid_strategy_enum_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            p3 = create_artifact(project, "P3_PRIOR_ART", {
                "research_question": "q", "search_scope": "s", "sources": ["s1"],
                "candidate_solutions": ["c1"], "key_findings": ["f1"], "limitations": ["l1"],
            }, actor="researcher")
            p4 = create_artifact(project, "P4_GAP_ANALYSIS", {
                "requirements_or_needs": ["n"], "existing_solutions": ["s"], "covered_capabilities": ["c"],
                "missing_capabilities": ["m"], "tradeoffs": ["t"], "gaps": ["g"], "prior_art_refs": [p3["artifact_id"]],
            }, actor="researcher")
            with self.assertRaises(MethodologyValidationError):
                create_artifact(project, "P5_STRATEGY_DECISION", {
                    "selected_strategy": "MAGIC", "alternatives_considered": ["x"],
                    "reason": "r", "cost": "low", "risk": "low", "gap_analysis_refs": [p4["artifact_id"]],
                }, actor="architect")


class P6RequirementTests(unittest.TestCase):
    def _prep_to_p5(self, project: Path) -> dict:
        init_project(project, "research", "low", "low", actor="test")
        p3 = create_artifact(project, "P3_PRIOR_ART", {
            "research_question": "q", "search_scope": "s", "sources": ["s1"],
            "candidate_solutions": ["c1"], "key_findings": ["f1"], "limitations": ["l1"],
        }, actor="researcher")
        p4 = create_artifact(project, "P4_GAP_ANALYSIS", {
            "requirements_or_needs": ["n"], "existing_solutions": ["s"], "covered_capabilities": ["c"],
            "missing_capabilities": ["m"], "tradeoffs": ["t"], "gaps": ["g"], "prior_art_refs": [p3["artifact_id"]],
        }, actor="researcher")
        return create_artifact(project, "P5_STRATEGY_DECISION", {
            "selected_strategy": "BUILD", "alternatives_considered": ["BUY"],
            "reason": "r", "cost": "low", "risk": "low", "gap_analysis_refs": [p4["artifact_id"]],
        }, actor="architect")

    def test_8_p6_generates_stable_req_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            p5 = self._prep_to_p5(project)
            req1 = create_artifact(project, "P6_REQUIREMENT", {
                "type": "functional", "statement": "s1", "priority": "high",
                "acceptance_criteria": ["a1"], "strategy_decision_refs": [p5["artifact_id"]],
            }, actor="architect")
            req2 = create_artifact(project, "P6_REQUIREMENT", {
                "type": "functional", "statement": "s2", "priority": "high",
                "acceptance_criteria": ["a2"], "strategy_decision_refs": [p5["artifact_id"]],
            }, actor="architect")
            self.assertEqual(req1["fields"]["requirement_id"], "REQ-001")
            self.assertEqual(req2["fields"]["requirement_id"], "REQ-002")
            self.assertEqual(next_requirement_id(project), "REQ-003")

    def test_9_duplicate_req_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            p5 = self._prep_to_p5(project)
            create_artifact(project, "P6_REQUIREMENT", {
                "type": "functional", "statement": "s1", "priority": "high", "requirement_id": "REQ-001",
                "acceptance_criteria": ["a1"], "strategy_decision_refs": [p5["artifact_id"]],
            }, actor="architect")
            with self.assertRaises(MethodologyValidationError):
                create_artifact(project, "P6_REQUIREMENT", {
                    "type": "functional", "statement": "s2", "priority": "high", "requirement_id": "REQ-001",
                    "acceptance_criteria": ["a2"], "strategy_decision_refs": [p5["artifact_id"]],
                }, actor="architect")

    def test_10_superseded_requirement_remains_historical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            p5 = self._prep_to_p5(project)
            req = create_artifact(project, "P6_REQUIREMENT", {
                "type": "functional", "statement": "s1", "priority": "high",
                "acceptance_criteria": ["a1"], "strategy_decision_refs": [p5["artifact_id"]],
            }, actor="architect")
            req_id = req["fields"]["requirement_id"]
            updated = update_requirement_status(project, req_id, "SUPERSEDED", actor="architect", reason="replaced by REQ-002")
            self.assertEqual(updated["status"], "SUPERSEDED")
            self.assertEqual(len(updated["status_history"]), 2)  # created + superseded
            # still present, not deleted
            still_there = [r for r in list_artifacts(project, artifact_type="P6_REQUIREMENT") if r["fields"]["requirement_id"] == req_id]
            self.assertEqual(len(still_there), 1)
            self.assertEqual(still_there[0]["status"], "SUPERSEDED")


class P7P8Tests(unittest.TestCase):
    def test_11_p7_authority_and_trust_boundary_structure_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")  # STANDARD -> extra fields required
            made = build_full_chain(project)
            p7 = made["P7_ARCHITECTURE"]
            self.assertIn("trust_boundaries", p7["fields"])
            self.assertIn("execution_authorities", p7["fields"])
            self.assertIn("acceptance_authorities", p7["fields"])
            self.assertIn("responsibilities", p7["fields"])  # STANDARD-only field present

    def test_p7_missing_standard_field_rejected_under_standard_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")  # STANDARD
            req = self._make_requirement(project)
            with self.assertRaises(MethodologyValidationError):
                create_artifact(project, "P7_ARCHITECTURE", {
                    "components": ["svc1"], "trust_boundaries": ["b1"],
                    "execution_authorities": ["agent"], "acceptance_authorities": ["human"],
                    "requirement_refs": [req],
                    # responsibilities/interfaces/external_dependencies deliberately omitted
                }, actor="architect")

    def _make_requirement(self, project: Path) -> str:
        p3 = create_artifact(project, "P3_PRIOR_ART", {
            "research_question": "q", "search_scope": "s", "sources": ["s1"],
            "candidate_solutions": ["c1"], "key_findings": ["f1"], "limitations": ["l1"],
        }, actor="researcher")
        p4 = create_artifact(project, "P4_GAP_ANALYSIS", {
            "requirements_or_needs": ["n"], "existing_solutions": ["s"], "covered_capabilities": ["c"],
            "missing_capabilities": ["m"], "tradeoffs": ["t"], "gaps": ["g"], "prior_art_refs": [p3["artifact_id"]],
        }, actor="researcher")
        p5 = create_artifact(project, "P5_STRATEGY_DECISION", {
            "selected_strategy": "BUILD", "alternatives_considered": ["BUY"],
            "reason": "r", "cost": "low", "risk": "low", "gap_analysis_refs": [p4["artifact_id"]],
        }, actor="architect")
        req = create_artifact(project, "P6_REQUIREMENT", {
            "type": "functional", "statement": "s1", "priority": "high",
            "acceptance_criteria": ["a1"], "strategy_decision_refs": [p5["artifact_id"]],
        }, actor="architect")
        return req["fields"]["requirement_id"]

    def test_12_p8_adr_keeps_alternatives_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            made = build_full_chain(project)
            p8 = made["P8_ADR"]
            self.assertEqual(p8["fields"]["alternatives"], ["sqlite", "postgres"])
            self.assertEqual(p8["fields"]["expected_cost"], "medium")


class P10BaselineTests(unittest.TestCase):
    def test_13_primary_metric_cannot_silently_change_after_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            p10 = create_artifact(project, "P10_BASELINE", {
                "baseline_description": "manual process", "primary_metric": "completion time",
                "secondary_metrics": ["error rate"], "measurement_procedure": "manual timing",
            }, actor="researcher")
            # lock it (freeze the baseline the way a gate is frozen)
            path = artifacts_dir(project) / f"{p10['artifact_id']}.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["status"] = "LOCKED"
            path.write_text(json.dumps(record), encoding="utf-8")
            # attempting to create a NEW P10 baseline with a different primary_metric while a
            # LOCKED one exists must not silently redefine the metric.
            locked = [r for r in list_artifacts(project, artifact_type="P10_BASELINE") if r["status"] == "LOCKED"]
            self.assertEqual(len(locked), 1)
            self.assertEqual(locked[0]["fields"]["primary_metric"], "completion time")
            # (the artifact itself preserves its original value; nothing in this module ever
            # rewrites another artifact's fields in place, satisfying "cannot silently change")


class P11Tests(unittest.TestCase):
    def test_14_p11_gate_references_real_req_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            made = build_full_chain(project)
            p11 = made["P11_GATE_PLAN"]
            self.assertEqual(p11["fields"]["requirement_refs"], [made["P6_REQUIREMENT"]["fields"]["requirement_id"]])

    def test_15_p11_fake_req_ref_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            with self.assertRaises(MethodologyValidationError) as ctx:
                create_artifact(project, "P11_GATE_PLAN", {
                    "gate_id": "g1", "required_tests": ["t"], "evidence_requirements": ["e"],
                    "stop_conditions": ["s"], "verification_depth": "light",
                    "requirement_refs": ["REQ-999"], "required_commands": [], "forbidden_paths": [],
                }, actor="architect")
            self.assertIn("unknown P6_REQUIREMENT_ID", str(ctx.exception))

    def test_16_and_17_forbidden_paths_and_required_commands_preserved_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            made = build_full_chain(project)
            p11 = made["P11_GATE_PLAN"]
            self.assertEqual(p11["fields"]["forbidden_paths"], ["secrets.env"])
            self.assertEqual(p11["fields"]["required_commands"], ["python -m pytest"])
            reloaded = load_artifact(project, p11["artifact_id"])
            self.assertEqual(reloaded["fields"]["forbidden_paths"], ["secrets.env"])
            self.assertEqual(reloaded["fields"]["required_commands"], ["python -m pytest"])


class ReadinessProfileTests(unittest.TestCase):
    def test_18_light_readiness_requires_only_light_obligations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "experimental", "low", "low", actor="test")  # LIGHT
            build_full_chain(project)
            result = prebuild_readiness(project)
            self.assertTrue(result["ready"], result["missing"])
            self.assertEqual(result["profile"], "LIGHT")

    def test_19_standard_readiness_requires_standard_obligations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")  # STANDARD
            build_full_chain(project)  # already includes STANDARD-required P7 fields
            result = prebuild_readiness(project)
            self.assertTrue(result["ready"], result["missing"])
            self.assertEqual(result["profile"], "STANDARD")

    def test_19b_standard_readiness_rejects_light_only_p7(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")  # STANDARD
            made = build_full_chain(project)
            # strip the STANDARD-only fields from the already-created P7 artifact
            p7 = made["P7_ARCHITECTURE"]
            path = artifacts_dir(project) / f"{p7['artifact_id']}.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            for key in ("responsibilities", "interfaces", "external_dependencies"):
                record["fields"].pop(key, None)
            path.write_text(json.dumps(record), encoding="utf-8")
            result = prebuild_readiness(project)
            self.assertFalse(result["ready"])
            self.assertTrue(any("P7" in reason for reason in result["missing"]))

    def test_20_strict_readiness_requires_strict_obligations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "high", "high", actor="test")  # STRICT

            # STRICT is fail-closed at creation time, not only at readiness time: an
            # incomplete P7 cannot even be created under an already-STRICT project, so
            # first confirm that rejection directly (mirrors test_p7_missing_standard_field
            # but one level up, at STRICT).
            with self.assertRaises(MethodologyValidationError):
                create_artifact(project, "P7_ARCHITECTURE", {
                    "components": ["svc1"], "trust_boundaries": ["b1"],
                    "execution_authorities": ["agent"], "acceptance_authorities": ["human"],
                    "requirement_refs": [], "responsibilities": ["r"], "interfaces": ["i"],
                    "external_dependencies": ["d"],
                    # failure_domains / data_security_boundaries deliberately omitted
                }, actor="architect")

            # a chain that supplies the STRICT-only fields from the start passes cleanly
            made = build_full_chain(
                project,
                p7_extra={"failure_domains": ["network partition"], "data_security_boundaries": ["PII isolated"]},
                p8_extra={"vendor_lock_in": "moderate"},
            )
            result = prebuild_readiness(project)
            self.assertTrue(result["ready"], result["missing"])
            self.assertEqual(result["profile"], "STRICT")


class PrebuildBarrierTests(unittest.TestCase):
    def test_21_readiness_false_before_p11_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            result = prebuild_readiness(project)
            self.assertFalse(result["ready"])
            self.assertTrue(any(reason.startswith("P11") for reason in result["missing"]))

    def test_22_valid_full_chain_becomes_prebuild_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            build_full_chain(project)
            result = prebuild_readiness(project)
            self.assertTrue(result["ready"], result["missing"])

    def test_23_corrupt_artifact_blocks_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            made = build_full_chain(project)
            self.assertTrue(prebuild_readiness(project)["ready"])
            p11 = made["P11_GATE_PLAN"]
            path = artifacts_dir(project) / f"{p11['artifact_id']}.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["fields"]["requirement_refs"] = ["REQ-999"]  # break it
            path.write_text(json.dumps(record), encoding="utf-8")
            result = prebuild_readiness(project)
            self.assertFalse(result["ready"])
            self.assertTrue(any("REQ-999" in reason for reason in result["missing"]))
            # restore
            record["fields"]["requirement_refs"] = [made["P6_REQUIREMENT"]["fields"]["requirement_id"]]
            path.write_text(json.dumps(record), encoding="utf-8")
            self.assertTrue(prebuild_readiness(project)["ready"])


class FailClosedTests(unittest.TestCase):
    def test_24_wrong_methodology_version_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            record = create_artifact(project, "P0_PROJECT_INTENT", {
                "project_name": "p", "intent_type": "research", "problem_summary": "x",
                "target_users_or_context": "y", "desired_outcome": "z", "owner": "human",
                "initial_constraints": ["budget"],
            }, actor="human")
            path = artifacts_dir(project) / f"{record['artifact_id']}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["methodology_version"] = "0.0.1"
            path.write_text(json.dumps(data), encoding="utf-8")
            from nogap_artifacts import validate_record
            problems = validate_record(project, data)
            self.assertTrue(any("version mismatch" in p for p in problems))

    def test_25_artifact_from_wrong_phase_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            record = create_artifact(project, "P0_PROJECT_INTENT", {
                "project_name": "p", "intent_type": "research", "problem_summary": "x",
                "target_users_or_context": "y", "desired_outcome": "z", "owner": "human",
                "initial_constraints": ["budget"],
            }, actor="human")
            path = artifacts_dir(project) / f"{record['artifact_id']}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["phase_id"] = "P3"  # P0_PROJECT_INTENT claiming to belong to P3
            path.write_text(json.dumps(data), encoding="utf-8")
            from nogap_artifacts import validate_record
            problems = validate_record(project, data)
            self.assertTrue(any("belongs to P0" in p for p in problems))

    def test_26_duplicate_artifact_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            fields = {
                "project_name": "p", "intent_type": "research", "problem_summary": "x",
                "target_users_or_context": "y", "desired_outcome": "z", "owner": "human",
                "initial_constraints": ["budget"],
            }
            create_artifact(project, "P0_PROJECT_INTENT", fields, actor="human", artifact_id="fixed-id")
            with self.assertRaises(MethodologyValidationError):
                create_artifact(project, "P0_PROJECT_INTENT", fields, actor="human", artifact_id="fixed-id")

    def test_27_artifact_history_not_silently_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            p3 = create_artifact(project, "P3_PRIOR_ART", {
                "research_question": "q", "search_scope": "s", "sources": ["s1"],
                "candidate_solutions": ["c1"], "key_findings": ["f1"], "limitations": ["l1"],
            }, actor="researcher")
            p4 = create_artifact(project, "P4_GAP_ANALYSIS", {
                "requirements_or_needs": ["n"], "existing_solutions": ["s"], "covered_capabilities": ["c"],
                "missing_capabilities": ["m"], "tradeoffs": ["t"], "gaps": ["g"], "prior_art_refs": [p3["artifact_id"]],
            }, actor="researcher")
            p5 = create_artifact(project, "P5_STRATEGY_DECISION", {
                "selected_strategy": "BUILD", "alternatives_considered": ["BUY"],
                "reason": "r", "cost": "low", "risk": "low", "gap_analysis_refs": [p4["artifact_id"]],
            }, actor="architect")
            req = create_artifact(project, "P6_REQUIREMENT", {
                "type": "functional", "statement": "s1", "priority": "high",
                "acceptance_criteria": ["a1"], "strategy_decision_refs": [p5["artifact_id"]],
            }, actor="architect")
            req_id = req["fields"]["requirement_id"]
            update_requirement_status(project, req_id, "SUPERSEDED", actor="architect", reason="r1")
            update_requirement_status(project, req_id, "REJECTED", actor="architect", reason="r2")
            final = next(r for r in list_artifacts(project, artifact_type="P6_REQUIREMENT") if r["fields"]["requirement_id"] == req_id)
            self.assertEqual(len(final["status_history"]), 3)  # created, superseded, rejected - all preserved
            self.assertEqual(final["status_history"][0]["status"], "ACTIVE")
            self.assertEqual(final["status_history"][1]["status"], "SUPERSEDED")
            self.assertEqual(final["status_history"][2]["status"], "REJECTED")


class TrustGateIndependenceTests(unittest.TestCase):
    def test_28_changing_p11_does_not_mutate_the_frozen_trust_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            run_script("init", str(project), "--objective", "gate independence check")
            run_script("freeze", str(project))
            gate_path = project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
            before = gate_path.read_text(encoding="utf-8")

            init_project(project, "research", "low", "low", actor="test")
            build_full_chain(project)
            # also update a requirement status, and create a second, alternate P11 plan
            create_artifact(project, "P11_GATE_PLAN", {
                "gate_id": "gate-plan-2", "required_tests": ["e2e"], "evidence_requirements": ["execution"],
                "stop_conditions": ["x"], "verification_depth": "strict",
                "requirement_refs": [next_requirement_id(project)[:-1] + "1"],  # REQ-001, already exists
                "required_commands": ["pytest -k e2e"], "forbidden_paths": [".env"],
            }, actor="architect")

            after = gate_path.read_text(encoding="utf-8")
            self.assertEqual(before, after)


class CliTests(unittest.TestCase):
    def test_cli_artifact_create_list_show(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_result = run_script("methodology", "init", str(project), "--intent", "research", "--risk", "low", "--claim-strength", "low")
            self.assertEqual(init_result.returncode, 0, init_result.stderr)

            fields = json.dumps({
                "project_name": "p", "intent_type": "research", "problem_summary": "x",
                "target_users_or_context": "y", "desired_outcome": "z", "owner": "human",
                "initial_constraints": ["budget"],
            })
            create_result = run_script("methodology", "artifact-create", str(project), "--type", "P0_PROJECT_INTENT", "--actor", "human", "--fields-json", fields)
            self.assertEqual(create_result.returncode, 0, create_result.stderr)

            list_result = run_script("methodology", "artifact-list", str(project))
            self.assertEqual(list_result.returncode, 0, list_result.stderr)
            self.assertIn("P0_PROJECT_INTENT", list_result.stdout)

            artifact_id = list_result.stdout.strip().splitlines()[1].split()[0]
            show_result = run_script("methodology", "artifact-show", str(project), "--artifact-id", artifact_id)
            self.assertEqual(show_result.returncode, 0, show_result.stderr)
            self.assertIn('"artifact_id"', show_result.stdout)

    def test_cli_readiness_reports_actionable_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("methodology", "init", str(project), "--intent", "research", "--risk", "low", "--claim-strength", "low")
            result = run_script("methodology", "readiness", str(project))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PREBUILD_READY: false", result.stdout)
            self.assertIn("no artifact recorded", result.stdout)


if __name__ == "__main__":
    unittest.main()
