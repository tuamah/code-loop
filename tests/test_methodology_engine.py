#!/usr/bin/env python3
"""M7-C acceptance checks: the P0-P23 Methodology State Machine.

Covers all 24 mandatory cases from the M7-C brief. current_phase is authoritative
lifecycle state now (no longer a fixed "P0" placeholder), changed only through
transition(); the contract graph from M7-A is the sole authority for what's legal.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from nogap_methodology import (  # noqa: E402
    MethodologyValidationError,
    active_loops,
    can_transition,
    evaluate_phase_status,
    init_project,
    load_state,
    methodology_state_path,
    resolve_loop,
    status,
    transition,
)


def advance(project: Path, *targets: str, actor: str = "team",
            materialize_evidence: bool = True) -> dict:
    """Fast-forwards through forward transitions, satisfying each phase's obligations FOR REAL.

    This used to pass `artifact_refs=["artifact-placeholder"]` at every step, and its own
    docstring said why: "content doesn't matter here, only presence/absence does at this
    milestone". That was true of the rule as it then existed. F2a made it false - a reference
    must now resolve to something of the declared semantic kind - and this suite was standing
    on scaffolding that resolved to nothing.

    The repair is a shared fixture factory, not a seam inside transition(). That function is
    F2a's enforcement point, so a test-only bypass there would route these tests around the
    very property they exist to exercise.
    """
    from methodology_fixture_builder import FixtureBuilder

    if "P21" in targets and project not in _BUILDERS:
        # P21 is entered by a SUCCEEDED deployment, which needs an ACCEPT decision, which
        # needs independent authoritative verification. None of that can be advanced past,
        # so the fixture performs the real chain instead of arranging its appearance.
        from methodology_fixture_builder import advance_via_real_pipeline

        _BUILDERS[project] = advance_via_real_pipeline(project, actor=actor)
        remaining = [t for t in targets
                     if t not in {*FULL_FORWARD_TO_P18, "P19", "P20", "P21"}]
        if not remaining:
            return load_state(project)
        targets = tuple(remaining)

    builder = _BUILDERS.get(project)
    if builder is None:
        builder = _BUILDERS[project] = FixtureBuilder(
            project, actor=actor, materialize_evidence=materialize_evidence)
    state = None
    for target in targets:
        current = status(project)["current_phase"]
        if current == "P18" and target in {"P19", "P20", "P21"}:
            # Past P18 the lifecycle module owns the phase movement: evaluate_release_
            # readiness() performs P19->P20 itself, so stepping manually here would be a
            # second copy of its rules. Hand the walk to the builder, which delegates.
            state = builder.advance_to(target)
            continue
        if status(project)["current_phase"] == target:
            continue
        artifact_refs, evidence_refs = builder.obligations(current)
        state = transition(
            project, target, actor=actor, reason=f"advance to {target}",
            evidence_refs=evidence_refs, artifact_refs=artifact_refs,
        )
    return state


#: One builder per project, so refs created for an earlier phase are still reachable later.
_BUILDERS: dict[Path, object] = {}


def real_refs(project: Path, phase_id: str | None = None,
              materialize_evidence: bool = True) -> tuple[list[str], list[str]]:
    """Genuine (artifact_refs, evidence_refs) for leaving `phase_id` (default: current).

    Tests that only need to BE somewhere use this instead of inventing ids. A negative test
    that supplies a fictitious reference no longer proves what it claims: it would be
    rejected for the missing reference rather than for the reason under test.
    """
    from methodology_fixture_builder import FixtureBuilder

    builder = _BUILDERS.get(project)
    if builder is None:
        builder = _BUILDERS[project] = FixtureBuilder(
            project, materialize_evidence=materialize_evidence)
    return builder.obligations(phase_id or status(project)["current_phase"])


FULL_FORWARD_TO_P18 = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18"]


class BasicForwardTransitionTests(unittest.TestCase):
    def test_1_p0_to_p1_valid_when_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            _artifacts, _evidence = real_refs(project, "P0")
            state = transition(project, "P1", actor="human:owner", reason="intent recorded",
                               artifact_refs=_artifacts, evidence_refs=_evidence)
            self.assertEqual(state["current_phase"], "P1")
            self.assertEqual(state["transition_history"][-1]["transition_type"], "FORWARD")

    def test_2_p0_to_p2_arbitrary_jump_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            # Pinned to the INTENDED reason. With a fictitious artifact_refs this would now
            # also be rejected for the missing reference, so a bare assertRaises would pass
            # while proving nothing about edge legality.
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P2", actor="human:owner", reason="skip P1",
                           artifact_refs=real_refs(project, "P0")[0])
            self.assertIn("not a legal transition", str(ctx.exception))

    def test_3_p2_to_build_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            advance(project, "P1", "P2")
            for build_phase in ("P12", "P13", "P14"):
                _a, _e = real_refs(project)
                with self.assertRaises(MethodologyValidationError, msg=build_phase) as ctx:
                    transition(project, build_phase, actor="human", reason="jump to build",
                               artifact_refs=_a, evidence_refs=_e)
                self.assertIn("not a legal transition", str(ctx.exception), build_phase)

    def test_4_p11_to_p12_only_when_prepare_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            advance(project, "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10")
            # P11 not yet reached: from P10, P12 isn't even a legal edge
            with self.assertRaises(MethodologyValidationError):
                transition(project, "P12", actor="team", reason="skip P11")
            # P10 -> P11 with no artifacts: PREPARE's own contract not satisfied
            with self.assertRaises(MethodologyValidationError):
                transition(project, "P11", actor="team", reason="no golden gates yet")
            # now satisfy it properly
            state = advance(project, "P11", "P12")
            self.assertEqual(state["current_phase"], "P12")


class BackwardTransitionTests(unittest.TestCase):
    def _to_p18(self, project: Path) -> dict:
        init_project(project, "research", "high", "high", actor="test")  # STRICT: P17/P18 mandatory
        return advance(project, *FULL_FORWARD_TO_P18)

    def test_5_p18_to_p13_repair_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self._to_p18(project)
            state = transition(project, "P13", actor="verifier", reason="implementation defect found",
                                evidence_refs=real_refs(project)[1], artifact_refs=real_refs(project)[0],
                                authority_class="verification")
            self.assertEqual(state["current_phase"], "P13")
            self.assertEqual(state["transition_history"][-1]["transition_type"], "LOOP_RETURN")

    def test_6_p18_to_p6_requirement_defect_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self._to_p18(project)
            state = transition(project, "P6", actor="verifier", reason="requirement defect found",
                                evidence_refs=real_refs(project)[1], artifact_refs=real_refs(project)[0],
                                authority_class="verification")
            self.assertEqual(state["current_phase"], "P6")

    def test_7_p18_to_p7_architecture_defect_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self._to_p18(project)
            state = transition(project, "P7", actor="verifier", reason="architecture defect found",
                                evidence_refs=real_refs(project)[1], artifact_refs=real_refs(project)[0],
                                authority_class="verification")
            self.assertEqual(state["current_phase"], "P7")

    def test_p18_to_p3_prior_art_reconsideration_allowed(self) -> None:
        # The characterization fix: P18 -> P3/P4 was missing from M7-A, added before building the engine.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self._to_p18(project)
            state = transition(project, "P3", actor="verifier", reason="prior art reconsideration justified",
                                evidence_refs=real_refs(project)[1], artifact_refs=real_refs(project)[0],
                                authority_class="verification")
            self.assertEqual(state["current_phase"], "P3")


class RepairLoopTests(unittest.TestCase):
    def test_8_p21_incident_enters_repair_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")
            advance(project, *FULL_FORWARD_TO_P18, "P19", "P20", "P21")
            state = transition(project, "REPAIR_LOOP", actor="operator", reason="production incident",
                                evidence_refs=["incident-1"])
            self.assertEqual(state["current_phase"], "P21")  # unchanged: REPAIR_LOOP is symbolic, not a real phase
            loops = active_loops(project)
            self.assertEqual(len(loops), 1)
            self.assertEqual(loops[0]["loop_type"], "repair_loop")
            self.assertEqual(loops[0]["origin_phase"], "P21")

    def test_22_active_loop_cannot_be_silently_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")
            advance(project, *FULL_FORWARD_TO_P18, "P19", "P20", "P21")
            transition(project, "REPAIR_LOOP", actor="operator", reason="incident A", evidence_refs=["a"])
            with self.assertRaises(MethodologyValidationError):
                transition(project, "REPAIR_LOOP", actor="operator", reason="incident B", evidence_refs=["b"])

    def test_23_resolved_loop_remains_historically_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")
            advance(project, *FULL_FORWARD_TO_P18, "P19", "P20", "P21")
            loops_before_repair = len(load_state(project)["loops"])  # research/build/verify loops already opened+resolved en route
            transition(project, "REPAIR_LOOP", actor="operator", reason="incident", evidence_refs=["a"])
            state = transition(project, "P13", actor="operator", reason="root cause found, repairing",
                                evidence_refs=real_refs(project)[1], artifact_refs=real_refs(project)[0])
            # nothing removed: every prior loop (research/build/verify) plus this repair loop remains
            self.assertEqual(len(state["loops"]), loops_before_repair + 1)
            repair_loop = next(loop for loop in state["loops"] if loop["loop_type"] == "repair_loop")
            self.assertEqual(repair_loop["status"], "RESOLVED")
            self.assertIsNotNone(repair_loop["resolved_at"])

    def test_manual_loop_resolution_as_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")
            advance(project, *FULL_FORWARD_TO_P18, "P19", "P20", "P21")
            transition(project, "REPAIR_LOOP", actor="operator", reason="incident", evidence_refs=["a"])
            loop_id = active_loops(project)[0]["loop_id"]
            state = resolve_loop(project, loop_id, "BLOCKED", actor="operator", reason="waiting on vendor")
            resolved = next(loop for loop in state["loops"] if loop["loop_id"] == loop_id)
            self.assertEqual(resolved["status"], "BLOCKED")


class EvolveLoopTests(unittest.TestCase):
    def test_9_p22_may_reenter_allowed_earlier_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")
            advance(project, *FULL_FORWARD_TO_P18, "P19", "P20", "P21", "P22")
            state = transition(project, "P6", actor="owner", reason="evolution requires new requirements",
                                evidence_refs=real_refs(project)[1], artifact_refs=real_refs(project)[0])
            self.assertEqual(state["current_phase"], "P6")


class RejectionAndFailClosedTests(unittest.TestCase):
    def test_10_unknown_target_phase_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            with self.assertRaises(MethodologyValidationError):
                transition(project, "P99", actor="team", reason="nonsense target")

    def test_11_malformed_transition_graph_fails_closed(self) -> None:
        # A malformed methodology.json (simulated by corrupting the state's own methodology_version
        # so it no longer matches the real, valid definition) must fail closed rather than silently
        # applying mismatched rules.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            path = methodology_state_path(project)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["methodology_version"] = "corrupted-999"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P1", actor="team", reason="x")
            self.assertIn("version", str(ctx.exception).lower())

    def test_12_missing_required_artifact_blocks_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P1", actor="team", reason="no artifact supplied")
            self.assertIn("requires artifacts", str(ctx.exception))

    def test_13_missing_required_evidence_blocks_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            advance(project, "P1", "P2", "P3")  # P3 requires evidence (source_references) to leave
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P4", actor="team", reason="no evidence", artifact_refs=["gap-doc"])
            self.assertIn("requires evidence", str(ctx.exception))

    def test_18_transition_without_actor_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P1", actor="", reason="x")
            self.assertIn("non-empty actor_id", str(ctx.exception))

    def test_19_transition_without_reason_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P1", actor="team", reason="")
            self.assertIn("non-empty reason", str(ctx.exception))

    def test_21_methodology_version_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            path = methodology_state_path(project)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["methodology_version"] = "0.0.1"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P1", actor="team", reason="x")
            self.assertIn("version mismatch", str(ctx.exception))


class EvidenceResolutionTests(unittest.TestCase):
    def test_14_unknown_evidence_reference_rejected_when_resolvable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            advance(project, "P1", "P2", "P3")
            # Artifacts first: the builder establishes the Trust runtime on first need, and
            # `nogap init` refuses a project whose runtime directory already exists - so a
            # bare mkdir here would lock it out.
            p3_artifacts = real_refs(project, "P3")[0]
            evidence_dir = project / ".code-loop" / "runtime" / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "evidence-real.json").write_text(json.dumps({"id": "evidence-real", "status": "passed"}), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P4", actor="team", reason="cite a fake ref",
                           evidence_refs=["evidence-does-not-exist"],
                           artifact_refs=p3_artifacts)
            self.assertIn("unknown evidence reference", str(ctx.exception))
            # the real one works fine
            state = transition(project, "P4", actor="team", reason="cite the real ref",
                                evidence_refs=["evidence-real"],
                                artifact_refs=p3_artifacts)
            self.assertEqual(state["current_phase"], "P4")

    def test_evidence_ref_blocked_when_no_runtime_exists(self) -> None:
        # D4-PRE-B2 revoked the old "accepted at face value" convention: absence of a
        # runtime is NOT evidence of validity when there are refs to resolve. A non-empty
        # evidence_refs with no ledger to resolve against is now unresolved, same as an
        # unknown ref against a real ledger - never blanket acceptance.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            # materialize_evidence=False: this test is ABOUT the absence of a ledger, so the
            # fixture must not create one. The unresolvable evidence ref is the SUBJECT here -
            # it is what "blocked with no ledger to resolve against" means.
            advance(project, "P1", "P2", "P3", materialize_evidence=False)
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P4", actor="team", reason="no runtime to check against",
                           evidence_refs=["anything-goes-here"],
                           artifact_refs=real_refs(project, "P3",
                                                   materialize_evidence=False)[0])
            self.assertIn("unknown evidence reference", str(ctx.exception))
            self.assertEqual(status(project)["current_phase"], "P3")

    def test_evidence_ref_resolution_matrix_at_the_transition_gate(self) -> None:
        """Dedicated coverage for D4-PRE-B2's shared evidence-ledger reader, at the one
        site with the largest blast radius (the phase-transition gate in
        nogap_methodology._evaluate_transition). Several other suites (test_f2a_verdict_
        matrix.py, test_f2b_*.py) moved their `forward()` dry-run helpers to
        `evidence_refs=[]` because the artifact-verdict matrix they test has nothing to do
        with evidence resolution - this test is the explicit replacement coverage for the
        evidence-resolution path itself, in one place, proving all three outcomes:
          1. a transition citing a REAL evidence ref present in the ledger passes
          2. the same transition citing an UNKNOWN ref fails
          3. non-empty refs with NO ledger at all (never materialized) fails
        (2) is already exercised by test_14 above and (3) by the test right above this one;
        this test exists so the three outcomes are visible together as one matrix, not
        scattered incidentally across other tests' setup.
        """
        # (1) and (2): real ledger, resolvable vs. unresolvable ref.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            advance(project, "P1", "P2", "P3")
            p3_artifacts = real_refs(project, "P3")[0]
            evidence_dir = project / ".code-loop" / "runtime" / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "evidence-matrix-real.json").write_text(
                json.dumps({"id": "evidence-matrix-real", "status": "passed"}), encoding="utf-8")

            # (1) PASSES: the ref resolves against the real ledger.
            state = transition(project, "P4", actor="team", reason="real ref resolves",
                               evidence_refs=["evidence-matrix-real"], artifact_refs=p3_artifacts)
            self.assertEqual(state["current_phase"], "P4")

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            advance(project, "P1", "P2", "P3")
            p3_artifacts = real_refs(project, "P3")[0]
            evidence_dir = project / ".code-loop" / "runtime" / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "evidence-matrix-real.json").write_text(
                json.dumps({"id": "evidence-matrix-real", "status": "passed"}), encoding="utf-8")

            # (2) FAILS: a ledger exists, but this ref isn't in it.
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P4", actor="team", reason="unknown ref against a real ledger",
                           evidence_refs=["evidence-matrix-unknown"], artifact_refs=p3_artifacts)
            self.assertIn("unknown evidence reference", str(ctx.exception))
            self.assertEqual(status(project)["current_phase"], "P3")

        # (3) FAILS: non-empty refs, no ledger materialized at all.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            advance(project, "P1", "P2", "P3", materialize_evidence=False)
            with self.assertRaises(MethodologyValidationError) as ctx:
                transition(project, "P4", actor="team", reason="no ledger to resolve against",
                           evidence_refs=["evidence-matrix-missing-ledger"],
                           artifact_refs=real_refs(project, "P3", materialize_evidence=False)[0])
            self.assertIn("unknown evidence reference", str(ctx.exception))
            self.assertEqual(status(project)["current_phase"], "P3")


class ProfileAndSkipTests(unittest.TestCase):
    def test_16_light_skip_is_explicit_and_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "experimental", "low", "low", actor="test")  # -> LIGHT
            advance(project, "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11",
                    "P12", "P13", "P14", "P15", "P16")
            _a, _e = real_refs(project)
            state = transition(project, "P19", actor="team", reason="light profile allows skipping deep verification",
                                evidence_refs=_e, artifact_refs=_a)
            self.assertEqual(state["current_phase"], "P19")
            last = state["transition_history"][-1]
            self.assertEqual(last["transition_type"], "SKIP")
            self.assertEqual(last["skipped_phases"], ["P17", "P18"])

    def test_15_phase_level_strict_override_blocks_the_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "experimental", "low", "low", actor="test")  # -> LIGHT
            from nogap_methodology import escalate_phase
            escalate_phase(project, "VERIFY", "STRICT", actor="owner")
            advance(project, "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11",
                    "P12", "P13", "P14", "P15", "P16")
            # with VERIFY escalated to STRICT, P17/P18 are no longer skippable: P19 is not a legal edge
            with self.assertRaises(MethodologyValidationError):
                _a, _e = real_refs(project)
                transition(project, "P19", actor="team", reason="try to skip anyway",
                           artifact_refs=_a, evidence_refs=_e)
            # but going through P17 properly still works
            state = transition(project, "P17", actor="team", reason="STRICT requires this",
                                evidence_refs=real_refs(project)[1], artifact_refs=real_refs(project)[0])
            self.assertEqual(state["current_phase"], "P17")

    def test_explicit_phase_still_reachable_even_when_skippable(self) -> None:
        # skippable != forbidden: explicitly requesting a skippable phase still works normally.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "experimental", "low", "low", actor="test")
            advance(project, "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11",
                    "P12", "P13", "P14", "P15", "P16")
            _a, _e = real_refs(project)
            state = transition(project, "P17", actor="team", reason="doing it anyway",
                               evidence_refs=_e, artifact_refs=_a)
            self.assertEqual(state["current_phase"], "P17")
            self.assertEqual(state["transition_history"][-1]["transition_type"], "FORWARD")


class PhaseStatusTests(unittest.TestCase):
    def test_not_started_before_reached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            self.assertEqual(evaluate_phase_status(project, "P5"), "NOT_STARTED")

    def test_completed_after_forward_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            advance(project, "P1")
            self.assertEqual(evaluate_phase_status(project, "P0"), "COMPLETED")

    def test_ready_to_exit_vs_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            # Every phase in the current P0-P23 data requires at least one artifact, so with no
            # refs supplied evaluate_phase_status is honestly BLOCKED, never a false READY_TO_EXIT.
            self.assertEqual(evaluate_phase_status(project), "BLOCKED")
            # can_transition confirms the same edge genuinely becomes allowed once real refs exist.
            # This asserted `artifact_refs=["intent-doc"]` - a string resolving to nothing, which
            # satisfied the pre-F2a rule. The CLAIM was always right; only its choice of
            # reference was obsolete, and the comment above says so in its own words. It now
            # proves both halves: a fictitious reference is refused, a real one is accepted.
            self.assertFalse(can_transition(project, "P1")["allowed"])
            self.assertFalse(can_transition(project, "P1", artifact_refs=["intent-doc"])["allowed"])
            self.assertTrue(
                can_transition(project, "P1", artifact_refs=real_refs(project, "P0")[0])["allowed"])
            advance(project, "P1")
            self.assertEqual(evaluate_phase_status(project), "BLOCKED")  # P1 requires artifacts too


class ApiIntegrityTests(unittest.TestCase):
    def test_17_and_24_current_phase_changes_only_through_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            from nogap_methodology import escalate_phase
            escalate_phase(project, "VERIFY", "STRICT", actor="owner")
            state = load_state(project)
            self.assertEqual(state["current_phase"], "P0")  # unaffected by escalate/status calls
            status(project)
            state = load_state(project)
            self.assertEqual(state["current_phase"], "P0")

    def test_20_transition_history_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            advance(project, "P1")
            advance(project, "P2")
            state = load_state(project)
            self.assertEqual(len(state["transition_history"]), 2)
            self.assertEqual(state["transition_history"][0]["to_phase"], "P1")
            self.assertEqual(state["transition_history"][1]["to_phase"], "P2")
            # every field required by the transition record shape is present
            for entry in state["transition_history"]:
                for key in ("transition_id", "methodology_id", "methodology_version", "from_phase", "to_phase",
                            "transition_type", "reason", "actor_id", "authority_class", "evidence_refs",
                            "artifact_refs", "timestamp", "profile_at_transition"):
                    self.assertIn(key, entry)


if __name__ == "__main__":
    unittest.main()
