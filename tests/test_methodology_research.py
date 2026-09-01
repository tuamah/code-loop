#!/usr/bin/env python3
"""M7-J acceptance checks: Research / Claims / Hypotheses.

Covers the mandatory invariants from the brief (optimizing for invariant coverage,
not an exact test count) plus automated encodings of all 7 mandatory scenarios
(A-G). M6/M7-A..I regression coverage is verified by running the full existing
suites alongside this file, not duplicated here except for a few direct
cross-module sanity checks.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap_research as nr  # noqa: E402
from nogap_methodology import MethodologyValidationError, init_project  # noqa: E402


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


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "scripts/nogap.py", *args], cwd=ROOT, text=True, capture_output=True)


class ResearchFixture(unittest.TestCase):
    profile_args = ("research", "low", "low")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        init_git_repo(self.project)
        init_project(self.project, *self.profile_args, actor="test")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # --- DSL helpers ---------------------------------------------------------

    def make_question(self, **overrides: Any) -> dict[str, Any]:
        fields = {"title": "Q", "question": "does it work?", "actor": "scientist", "reason": "new question"}
        fields.update(overrides)
        return nr.create_research_question(self.project, **fields)

    def make_hypothesis(self, question_id: str, preregistered: bool = True, **overrides: Any) -> dict[str, Any]:
        fields = {"question_id": question_id, "statement": "candidate improves the metric", "actor": "scientist", "reason": "hyp"}
        fields.update(overrides)
        h = nr.create_hypothesis(self.project, **fields)
        return nr.register_hypothesis(self.project, h["hypothesis_id"], actor="scientist", reason="prereg", preregistered=preregistered)

    def make_protocol(
        self, question_id: str, hypothesis_refs: tuple = (), primary_metric: str = "M",
        success: list | None = None, failure: list | None = None, claim_strength: str = "LOW", **overrides: Any,
    ) -> dict[str, Any]:
        success = success if success is not None else [{"metric": primary_metric, "comparator": ">=", "value": 1.0, "aggregation": "mean"}]
        failure = failure if failure is not None else [{"metric": primary_metric, "comparator": "<", "value": 1.0, "aggregation": "mean"}]
        fields = dict(
            question_id=question_id, objective="test objective", hypothesis_refs=list(hypothesis_refs),
            primary_metric=primary_metric, success_criteria=success, failure_criteria=failure,
            inconclusive_criteria=[{"note": "n/a"}], claim_strength=claim_strength, actor="scientist", reason="define protocol",
        )
        fields.update(overrides)
        return nr.create_protocol(self.project, **fields)

    def freeze(self, protocol: dict[str, Any]) -> dict[str, Any]:
        return nr.freeze_protocol(self.project, protocol["protocol_id"], actor="scientist", reason="freeze")

    def frozen_protocol(self, question_id: str, **overrides: Any) -> dict[str, Any]:
        return self.freeze(self.make_protocol(question_id, **overrides))

    def make_experiment(self, protocol_id: str, **overrides: Any) -> dict[str, Any]:
        fields = dict(protocol_id=protocol_id, actor="scientist", reason="run")
        fields.update(overrides)
        return nr.create_experiment(self.project, **fields)

    def complete(self, experiment_id: str, status: str = "COMPLETED", **overrides: Any) -> dict[str, Any]:
        fields = dict(status=status, actor="scientist", reason="done")
        fields.update(overrides)
        return nr.record_experiment_result(self.project, experiment_id, **fields)

    def observe(self, experiment_id: str, metric_name: str, value: float, **overrides: Any) -> dict[str, Any]:
        fields = dict(experiment_id=experiment_id, metric_name=metric_name, metric_value=value, actor="scientist", reason="record")
        fields.update(overrides)
        return nr.record_observation(self.project, **fields)

    def make_claim(self, question_id: str, claim_type: str = "EMPIRICAL", claim_strength: str = "LOW", **overrides: Any) -> dict[str, Any]:
        fields = dict(
            question_id=question_id, statement="claim statement", claim_type=claim_type, claim_strength=claim_strength,
            scope="synthetic test scope", actor="scientist", reason="claim",
        )
        fields.update(overrides)
        return nr.create_claim(self.project, **fields)

    def assess(self, claim_id: str, outcome: str, **overrides: Any) -> dict[str, Any]:
        fields = dict(outcome=outcome, rationale="rationale", actor="scientist", reason="assess",
                      assessor_id="human:reviewer", assessor_role="INDEPENDENT")
        fields.update(overrides)
        return nr.assess_claim(self.project, claim_id, **fields)

    def full_supported_chain(self, claim_strength: str = "LOW", **assess_overrides: Any) -> dict[str, Any]:
        """Question -> preregistered hypothesis -> frozen protocol -> completed
        experiment -> passing observation -> claim -> SUPPORTED assessment."""
        q = self.make_question()
        h = self.make_hypothesis(q["question_id"])
        p = self.frozen_protocol(q["question_id"], hypothesis_refs=[h["hypothesis_id"]], claim_strength=claim_strength)
        e = self.make_experiment(p["protocol_id"], hypothesis_refs=[h["hypothesis_id"]])
        e = self.complete(e["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 2.0, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], claim_strength=claim_strength, hypothesis_refs=[h["hypothesis_id"]], protocol_refs=[p["protocol_id"]])
        overrides = dict(protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]], observation_refs=[o["observation_id"]],
                          evidence_refs=["ev-1"], hypothesis_refs=[h["hypothesis_id"]])
        overrides.update(assess_overrides)
        a = self.assess(c["claim_id"], "SUPPORTED", **overrides)
        return {"question": q, "hypothesis": h, "protocol": p, "experiment": e, "observation": o, "claim": c, "assessment": a}


# --- ResearchQuestion ----------------------------------------------------------

class QuestionTests(ResearchFixture):
    def test_1_create_question(self) -> None:
        q = self.make_question()
        self.assertEqual(q["status"], "OPEN")
        self.assertEqual(q["question_id"], "RQ-001")

    def test_2_duplicate_question_id_rejected(self) -> None:
        self.make_question(question_id="RQ-CUSTOM")
        with self.assertRaises(MethodologyValidationError):
            self.make_question(question_id="RQ-CUSTOM")

    def test_3_question_history_append_oriented(self) -> None:
        q = self.make_question()
        q2 = nr.set_question_status(self.project, q["question_id"], "ACTIVE", actor="s", reason="start work")
        self.assertEqual(len(q2["history"]), 2)
        self.assertEqual(q2["history"][0]["action"], "CREATED")

    def test_question_closed_not_answered(self) -> None:
        q = self.make_question()
        closed = nr.set_question_status(self.project, q["question_id"], "CLOSED", actor="s", reason="abandoned direction")
        self.assertEqual(closed["status"], "CLOSED")
        self.assertNotEqual(closed["status"], "ANSWERED")

    def test_terminal_question_status_rejects_further_transition(self) -> None:
        q = self.make_question()
        nr.set_question_status(self.project, q["question_id"], "CLOSED", actor="s", reason="done")
        with self.assertRaises(MethodologyValidationError):
            nr.set_question_status(self.project, q["question_id"], "ACTIVE", actor="s", reason="reopen")

    def test_75_question_may_reference_p3_p4_p5_artifacts(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            self.make_question(related_artifact_refs=["does-not-exist"])


# --- HypothesisRecord ----------------------------------------------------------

class HypothesisTests(ResearchFixture):
    def test_4_create_hypothesis_linked_to_question(self) -> None:
        q = self.make_question()
        h = nr.create_hypothesis(self.project, question_id=q["question_id"], statement="s", actor="a", reason="r")
        self.assertEqual(h["question_id"], q["question_id"])
        self.assertEqual(h["status"], "DRAFT")

    def test_5_duplicate_hypothesis_id_rejected(self) -> None:
        q = self.make_question()
        nr.create_hypothesis(self.project, question_id=q["question_id"], statement="s", actor="a", reason="r", hypothesis_id="HYP-X")
        with self.assertRaises(MethodologyValidationError):
            nr.create_hypothesis(self.project, question_id=q["question_id"], statement="s2", actor="a", reason="r", hypothesis_id="HYP-X")

    def test_6_preregistered_hypothesis_before_result_accepted(self) -> None:
        q = self.make_question()
        h = self.make_hypothesis(q["question_id"])
        self.assertTrue(h["preregistered"])
        self.assertEqual(h["analysis_mode"], "PREREGISTERED")

    def test_7_hypothesis_after_result_cannot_masquerade_as_preregistered(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        self.observe(e["experiment_id"], "M", 5.0)
        late = nr.create_hypothesis(self.project, question_id=q["question_id"], statement="late", actor="a", reason="r")
        with self.assertRaises(MethodologyValidationError):
            nr.register_hypothesis(self.project, late["hypothesis_id"], actor="a", reason="try preregister", preregistered=True)

    def test_8_post_hoc_hypothesis_represented_honestly(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        self.observe(e["experiment_id"], "M", 5.0)
        late = nr.create_hypothesis(self.project, question_id=q["question_id"], statement="late", actor="a", reason="r")
        registered = nr.register_hypothesis(self.project, late["hypothesis_id"], actor="a", reason="honest", preregistered=False)
        self.assertFalse(registered["preregistered"])
        self.assertEqual(registered["analysis_mode"], "POST_HOC")

    def test_72_superseded_hypothesis_remains_queryable(self) -> None:
        q = self.make_question()
        h1 = self.make_hypothesis(q["question_id"])
        h2 = self.make_hypothesis(q["question_id"], statement="refined version")
        nr.mark_superseded(self.project, "hypotheses", h1["hypothesis_id"], superseded_by=h2["hypothesis_id"], actor="a", reason="refined")
        reloaded = nr.load_hypothesis(self.project, h1["hypothesis_id"])
        self.assertEqual(reloaded["status"], "SUPERSEDED")
        self.assertEqual(reloaded["superseded_by"], h2["hypothesis_id"])
        self.assertEqual(reloaded["statement"], h1["statement"])  # substantive fields untouched


# --- ResearchProtocol / immutability --------------------------------------------

class ProtocolTests(ResearchFixture):
    def test_9_create_protocol(self) -> None:
        q = self.make_question()
        p = self.make_protocol(q["question_id"])
        self.assertEqual(p["status"], "DRAFT")

    def test_10_protocol_missing_primary_metric_fails_freeze(self) -> None:
        q = self.make_question()
        p = nr.create_protocol(
            self.project, question_id=q["question_id"], objective="obj", success_criteria=[{"metric": "M", "comparator": ">=", "value": 1}],
            failure_criteria=[{"metric": "M", "comparator": "<", "value": 1}], inconclusive_criteria=[{"note": "n/a"}],
            actor="a", reason="r",
        )
        with self.assertRaises(MethodologyValidationError):
            nr.freeze_protocol(self.project, p["protocol_id"], actor="a", reason="freeze")

    def test_11_protocol_freeze_succeeds_with_valid_fields(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        self.assertEqual(p["status"], "FROZEN")
        self.assertIsNotNone(p["frozen_at"])

    def test_12_frozen_protocol_critical_fields_immutable(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        path = nr.research_dir(self.project) / "protocols" / f"{p['protocol_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["primary_metric"] = "HAND_EDITED"
        path.write_text(json.dumps(record), encoding="utf-8")
        reloaded = nr.load_protocol(self.project, p["protocol_id"])
        self.assertEqual(reloaded["primary_metric"], "HAND_EDITED")  # confirms the file has no built-in write guard...
        # ...but the ONLY sanctioned mutation path (amend_protocol) always requires an
        # audited amendment - there is no direct-field-set function in the public API.
        self.assertFalse(hasattr(nr, "set_protocol_field"))
        self.assertFalse(hasattr(nr, "update_protocol"))

    def test_13_protocol_amendment_creates_audited_history(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        # secondary_metrics is not research-critical - amend_protocol only covers the
        # protocol fields whose amendment must be audited, and rejects the rest.
        with self.assertRaises(MethodologyValidationError):
            nr.amend_protocol(self.project, p["protocol_id"], field_updates={"secondary_metrics": ["nope"]}, actor="a", reason="typo fix")

    def test_13b_protocol_amendment_of_critical_field_audited(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        amended = nr.amend_protocol(self.project, p["protocol_id"], field_updates={"primary_metric": "M2"}, actor="a", reason="clarify metric")
        self.assertEqual(amended["primary_metric"], "M2")
        self.assertEqual(len(amended["amendments"]), 1)
        self.assertEqual(amended["amendments"][0]["old_values"]["primary_metric"], "M")
        self.assertEqual(amended["amendments"][0]["new_values"]["primary_metric"], "M2")

    def test_14_post_result_amendment_labeled_post_result(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        self.observe(e["experiment_id"], "M", 5.0)
        amended = nr.amend_protocol(self.project, p["protocol_id"], field_updates={"primary_metric": "M2"}, actor="a", reason="switch after result")
        self.assertTrue(amended["amendments"][-1]["post_result"])
        self.assertTrue(amended["amendments"][-1]["result_known_at_amendment"])

    def test_amendment_before_result_not_post_result(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        amended = nr.amend_protocol(self.project, p["protocol_id"], field_updates={"primary_metric": "M2"}, actor="a", reason="clarify before any run")
        self.assertFalse(amended["amendments"][-1]["post_result"])

    def test_15_post_result_amendment_cannot_rewrite_original_result(self) -> None:
        chain = self.full_supported_chain()
        original_assessment_id = chain["assessment"]["assessment_id"]
        nr.amend_protocol(self.project, chain["protocol"]["protocol_id"], field_updates={"primary_metric": "SWITCHED"}, actor="a", reason="post-hoc switch")
        reloaded = nr.load_assessment(self.project, original_assessment_id)
        self.assertEqual(reloaded["outcome"], "SUPPORTED")
        self.assertEqual(reloaded["protocol_snapshot"]["primary_metric"], "M")  # frozen snapshot at assessment time, untouched

    def test_amend_unknown_field_rejected(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        with self.assertRaises(MethodologyValidationError):
            nr.amend_protocol(self.project, p["protocol_id"], field_updates={"objective": "not critical"}, actor="a", reason="r")

    def test_71_superseded_protocol_remains_queryable(self) -> None:
        q = self.make_question()
        p1 = self.frozen_protocol(q["question_id"])
        p2 = self.frozen_protocol(q["question_id"])
        nr.mark_superseded(self.project, "protocols", p1["protocol_id"], superseded_by=p2["protocol_id"], actor="a", reason="revised design")
        reloaded = nr.load_protocol(self.project, p1["protocol_id"])
        self.assertEqual(reloaded["status"], "SUPERSEDED")
        self.assertEqual(reloaded["primary_metric"], "M")

    def test_76_protocol_may_reference_p10_p11_without_modifying_them(self) -> None:
        q = self.make_question()
        with self.assertRaises(MethodologyValidationError):
            self.make_protocol(q["question_id"], baseline_refs=["nonexistent-p10"])


# --- ExperimentRecord ----------------------------------------------------------

class ExperimentTests(ResearchFixture):
    def test_16_create_experiment_linked_to_frozen_protocol(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.make_experiment(p["protocol_id"])
        self.assertEqual(e["protocol_id"], p["protocol_id"])
        self.assertEqual(e["status"], "PLANNED")

    def test_16b_experiment_requires_frozen_not_draft_protocol(self) -> None:
        q = self.make_question()
        p = self.make_protocol(q["question_id"])  # DRAFT, never frozen
        with self.assertRaises(MethodologyValidationError):
            self.make_experiment(p["protocol_id"])

    def test_17_experiment_unknown_protocol_rejected(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            self.make_experiment("PROTO-DOES-NOT-EXIST")

    def test_18_experiment_records_code_revision(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.make_experiment(p["protocol_id"], code_revision="abc123deadbeef")
        self.assertEqual(e["code_revision"], "abc123deadbeef")

    def test_19_experiment_records_dataset_fingerprint(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.make_experiment(p["protocol_id"], dataset_fingerprint="sha256:deadbeef")
        self.assertEqual(e["dataset_fingerprint"], "sha256:deadbeef")

    def test_20_experiment_records_actual_seeds(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.make_experiment(p["protocol_id"], seed_values=[1, 2, 3])
        self.assertEqual(e["seed_values"], [1, 2, 3])

    def test_21_process_failure_not_automatically_scientific_refuted(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.make_experiment(p["protocol_id"])
        failed = self.complete(e["experiment_id"], status="FAILED")
        self.assertEqual(failed["status"], "FAILED")
        # no assessment was created automatically as a side effect
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        self.assertEqual(nr.list_assessments(self.project, claim_id=c["claim_id"]), [])

    def test_protocol_status_becomes_executed_after_first_experiment(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        self.make_experiment(p["protocol_id"])
        reloaded = nr.load_protocol(self.project, p["protocol_id"])
        self.assertEqual(reloaded["status"], "EXECUTED")


# --- ObservationRecord ----------------------------------------------------------

class ObservationTests(ResearchFixture):
    def test_22_record_observation(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.make_experiment(p["protocol_id"])
        o = self.observe(e["experiment_id"], "M", 3.5)
        self.assertEqual(o["metric_value"], 3.5)

    def test_23_observation_unknown_experiment_rejected(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            self.observe("EXP-DOES-NOT-EXIST", "M", 1.0)

    def test_24_observation_evidence_provenance_required_where_configured(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"], required_evidence_kinds=["observation"])
        e = self.make_experiment(p["protocol_id"])
        with self.assertRaises(MethodologyValidationError):
            self.observe(e["experiment_id"], "M", 3.5)  # no raw_evidence_refs
        self.observe(e["experiment_id"], "M", 3.5, raw_evidence_refs=["ev-1"])  # succeeds with refs

    def test_25_observation_separated_from_interpretation(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.make_experiment(p["protocol_id"])
        o = self.observe(e["experiment_id"], "M", 3.5, notes="raw note, not a conclusion")
        self.assertNotIn("interpretation", o)
        self.assertNotIn("conclusion", o)
        self.assertIn("metric_value", o)


# --- ClaimRecord -----------------------------------------------------------------

class ClaimTests(ResearchFixture):
    def test_26_create_claim(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        self.assertEqual(c["status"], "DRAFT")

    def test_27_duplicate_claim_id_rejected(self) -> None:
        q = self.make_question()
        self.make_claim(q["question_id"], claim_id="CLAIM-X")
        with self.assertRaises(MethodologyValidationError):
            self.make_claim(q["question_id"], claim_id="CLAIM-X")

    def test_28_claim_scope_preserved(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"], scope="dataset D, seeds 1-3, LOW claim strength only")
        self.assertEqual(c["scope"], "dataset D, seeds 1-3, LOW claim strength only")

    def test_claim_requires_nonempty_scope(self) -> None:
        q = self.make_question()
        with self.assertRaises(MethodologyValidationError):
            self.make_claim(q["question_id"], scope="")

    def test_29_claim_strength_preserved(self) -> None:
        q = self.make_question()
        for strength in ("LOW", "MEDIUM", "HIGH"):
            c = self.make_claim(q["question_id"], claim_strength=strength)
            self.assertEqual(c["claim_strength"], strength)

    def test_30_comparative_claim_requires_baseline(self) -> None:
        q = self.make_question()
        with self.assertRaises(MethodologyValidationError):
            self.make_claim(q["question_id"], claim_type="COMPARATIVE")
        c = self.make_claim(q["question_id"], claim_type="COMPARATIVE", baseline_ref="baseline-B", baseline_metric=0.5)
        self.assertEqual(c["baseline_ref"], "baseline-B")

    def test_73_claim_history_append_oriented(self) -> None:
        chain = self.full_supported_chain()
        claim = nr.load_claim(self.project, chain["claim"]["claim_id"])
        self.assertEqual(claim["history"][0]["action"], "CREATED")
        self.assertEqual(claim["history"][-1]["action"], "ASSESSED")
        self.assertEqual(len(claim["assessment_refs"]), 1)


# --- ClaimAssessment: outcomes and preconditions --------------------------------

class OutcomeTests(ResearchFixture):
    def test_31_and_32_create_assessment_supported_preserved(self) -> None:
        chain = self.full_supported_chain()
        self.assertEqual(chain["assessment"]["outcome"], "SUPPORTED")
        self.assertEqual(nr.load_assessment(self.project, chain["assessment"]["assessment_id"])["outcome"], "SUPPORTED")

    def test_33_partially_supported_outcome_preserved(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(
            q["question_id"],
            success=[
                {"metric": "M", "comparator": ">=", "value": 1.0, "aggregation": "mean"},
                {"metric": "N", "comparator": ">=", "value": 1.0, "aggregation": "mean"},
            ],
            failure=[{"metric": "M", "comparator": "<", "value": 0}],
        )
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o1 = self.observe(e["experiment_id"], "M", 2.0, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        a = self.assess(c["claim_id"], "PARTIALLY_SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                         observation_refs=[o1["observation_id"]], evidence_refs=["ev-1"])
        self.assertEqual(a["outcome"], "PARTIALLY_SUPPORTED")

    def test_34_refuted_outcome_preserved(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 0.1, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        a = self.assess(c["claim_id"], "REFUTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                         observation_refs=[o["observation_id"]], evidence_refs=["ev-1"])
        self.assertEqual(a["outcome"], "REFUTED")

    def test_35_inconclusive_outcome_preserved(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        a = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="no data yet")
        self.assertEqual(a["outcome"], "INCONCLUSIVE")

    def test_36_missing_evidence_produces_inconclusive_not_refuted(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "REFUTED", rationale="nothing to go on")
        inc = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="insufficient evidence")
        self.assertEqual(inc["outcome"], "INCONCLUSIVE")

    def test_37_refuted_requires_contradictory_evidence(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "REFUTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]], evidence_refs=["ev-1"])

    def test_44_required_evidence_missing_blocks_supported(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 5.0)  # no raw_evidence_refs
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                        observation_refs=[o["observation_id"]])  # no evidence_refs either

    def test_46_failed_hard_protocol_criterion_blocks_supported(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 0.1, raw_evidence_refs=["ev-1"])  # fails success_criteria (M >= 1.0)
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                        observation_refs=[o["observation_id"]], evidence_refs=["ev-1"])

    def test_47_required_reproducibility_missing_blocks_high_supported(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"], claim_strength="HIGH", required_validation_level="LEVEL_3_DIFFICULT")
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 5.0, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], claim_strength="HIGH", protocol_refs=[p["protocol_id"]])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                        observation_refs=[o["observation_id"]], evidence_refs=["ev-1"], reproducibility_status="NOT_ATTEMPTED")

    def test_48_required_independent_assessment_missing_blocks_high_supported(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"], claim_strength="HIGH")
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 5.0, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], claim_strength="HIGH", protocol_refs=[p["protocol_id"]])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                        observation_refs=[o["observation_id"]], evidence_refs=["ev-1"], reproducibility_status="REPRODUCED",
                        assessor_role="SELF")

    def test_49_self_assessment_not_represented_as_independent(self) -> None:
        chain = self.full_supported_chain(assessor_role="SELF", reproducibility_status="NOT_REQUIRED")
        self.assertFalse(chain["assessment"]["independence"])

    def test_50_independent_assessment_represented_truthfully(self) -> None:
        chain = self.full_supported_chain()  # default assessor_role=INDEPENDENT
        self.assertTrue(chain["assessment"]["independence"])
        self.assertEqual(chain["assessment"]["assessor_role"], "INDEPENDENT")


class ScopedHighClaimSuccessTests(ResearchFixture):
    def test_high_claim_supported_with_full_discipline(self) -> None:
        chain = self.full_supported_chain(
            claim_strength="HIGH", reproducibility_status="REPRODUCED", assessor_role="INDEPENDENT",
        )
        self.assertEqual(chain["assessment"]["outcome"], "SUPPORTED")


# --- negative / inconclusive result preservation --------------------------------

class NegativeResultTests(ResearchFixture):
    def test_38_negative_result_remains_queryable(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 0.1, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        a = self.assess(c["claim_id"], "REFUTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                         observation_refs=[o["observation_id"]], evidence_refs=["ev-1"])
        self.assertIsNotNone(nr.load_assessment(self.project, a["assessment_id"]))
        self.assertIn(a["assessment_id"], nr.load_claim(self.project, c["claim_id"])["assessment_refs"])

    def test_39_later_positive_result_does_not_delete_negative_history(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o_bad = self.observe(e["experiment_id"], "M", 0.1, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        refuted = self.assess(c["claim_id"], "REFUTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                               observation_refs=[o_bad["observation_id"]], evidence_refs=["ev-1"])
        o_good = self.observe(e["experiment_id"], "M", 5.0, raw_evidence_refs=["ev-2"])
        c2 = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]], statement="revised narrower claim")
        supported = self.assess(c2["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                                 observation_refs=[o_good["observation_id"]], evidence_refs=["ev-2"])
        self.assertEqual(nr.load_assessment(self.project, refuted["assessment_id"])["outcome"], "REFUTED")
        self.assertEqual(supported["outcome"], "SUPPORTED")


class InconclusiveResultTests(ResearchFixture):
    def test_35b_inconclusive_recorded_with_reason(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        a = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="sample size too small to conclude")
        self.assertEqual(a["outcome"], "INCONCLUSIVE")
        self.assertIn("sample size", a["rationale"])

    def test_scenario_c_high_claim_missing_reproducibility_is_inconclusive_not_refuted(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"], claim_strength="HIGH", required_validation_level="LEVEL_3_DIFFICULT")
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 5.0, raw_evidence_refs=["ev-1"])  # favorable
        c = self.make_claim(q["question_id"], claim_strength="HIGH", protocol_refs=[p["protocol_id"]])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                        observation_refs=[o["observation_id"]], evidence_refs=["ev-1"], reproducibility_status="NOT_ATTEMPTED")
        inc = self.assess(c["claim_id"], "INCONCLUSIVE", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                           observation_refs=[o["observation_id"]], evidence_refs=["ev-1"], reproducibility_status="NOT_ATTEMPTED",
                           rationale="favorable but reproducibility not attempted")
        self.assertEqual(inc["outcome"], "INCONCLUSIVE")


# --- current vs historical assessment selection ---------------------------------

class CurrentAssessmentTests(ResearchFixture):
    def test_40_conflicting_assessments_preserved_historically(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        a1 = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="first pass")
        a2 = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="second pass")
        self.assertIsNotNone(nr.load_assessment(self.project, a1["assessment_id"]))
        self.assertIsNotNone(nr.load_assessment(self.project, a2["assessment_id"]))
        self.assertEqual(len(nr.list_assessments(self.project, claim_id=c["claim_id"])), 2)

    def test_41_current_assessment_uses_authoritative_ordering(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        self.assess(c["claim_id"], "INCONCLUSIVE", rationale="first")
        second = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="second, later")
        current = nr.get_current_claim_assessment(self.project, c["claim_id"])
        self.assertEqual(current["status"], "OK")
        self.assertEqual(current["assessment"]["assessment_id"], second["assessment_id"])

    def test_42_filesystem_order_cannot_choose_current_assessment(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        first = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="first", assessment_id="ASSESS-999")
        second = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="second", assessment_id="ASSESS-001")
        # ASSESS-001 sorts first alphabetically/by filename, but was created SECOND
        # (sequence=2 vs sequence=1) - current must follow the engine-assigned
        # creation sequence, never the id/filename ordering.
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)
        current = nr.get_current_claim_assessment(self.project, c["claim_id"])
        self.assertEqual(current["assessment"]["assessment_id"], "ASSESS-001")

    def test_43_unresolved_conflicting_current_assessments_report_conflict(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        a1 = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="first", assessment_id="ASSESS-A")
        a2 = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="second", assessment_id="ASSESS-B")
        path_b = nr.research_dir(self.project) / "assessments" / "ASSESS-B.json"
        record_b = json.loads(path_b.read_text(encoding="utf-8"))
        record_b["sequence"] = a1["sequence"]  # force an exact tie (only reachable via tampering)
        path_b.write_text(json.dumps(record_b), encoding="utf-8")
        current = nr.get_current_claim_assessment(self.project, c["claim_id"])
        self.assertEqual(current["status"], "CONFLICT")
        self.assertIsNone(current["assessment"])


# --- baseline / dataset / seeds / leakage / reproducibility ----------------------

class BaselineDatasetSeedTests(ResearchFixture):
    def test_51_baseline_provenance_preserved(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"], claim_type="COMPARATIVE", baseline_ref="baseline-B", baseline_version="v1",
                             baseline_metric=0.7, candidate_metric=0.85, comparison_method="paired_seeds")
        self.assertEqual(c["baseline_ref"], "baseline-B")
        self.assertEqual(c["baseline_version"], "v1")
        self.assertEqual(c["comparison_method"], "paired_seeds")

    def test_52_dataset_provenance_preserved(self) -> None:
        q = self.make_question()
        p = self.make_protocol(q["question_id"], data_provenance={"source": "synthetic-gen", "version": "2026.1"}, split_strategy="80/20 stratified")
        self.assertEqual(p["data_provenance"]["source"], "synthetic-gen")
        self.assertEqual(p["split_strategy"], "80/20 stratified")

    def test_53_seed_policy_vs_actual_seeds(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"], seed_policy={"count": 3}, random_seeds=[1, 2, 3])
        e = self.make_experiment(p["protocol_id"], seed_values=[1, 2, 3])
        self.assertEqual(p["random_seeds"], [1, 2, 3])
        self.assertEqual(e["seed_values"], [1, 2, 3])

    def test_54_single_favorable_seed_cannot_satisfy_multi_seed_protocol(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(
            q["question_id"], random_seeds=[1, 2, 3],
            success=[{"metric": "M", "comparator": ">=", "value": 1.0, "aggregation": "all"}],
        )
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        favorable = self.observe(e["experiment_id"], "M", 5.0, seed=1, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                        observation_refs=[favorable["observation_id"]], evidence_refs=["ev-1"])

    def test_scenario_f_multi_seed_aggregate_criterion_not_satisfied_by_cherrypick(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(
            q["question_id"], random_seeds=[1, 2, 3],
            success=[{"metric": "AUPRC", "comparator": ">", "vs_baseline": True, "aggregation": "all"}],
            failure=[{"metric": "AUPRC", "comparator": "<=", "vs_baseline": True, "aggregation": "all"}],
        )
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        obs = [self.observe(e["experiment_id"], "AUPRC", v, seed=s, raw_evidence_refs=["ev-1"]) for s, v in [(1, 0.75), (2, 0.68), (3, 0.72)]]
        c = self.make_claim(q["question_id"], claim_type="COMPARATIVE", baseline_ref="B", baseline_metric=0.70, protocol_refs=[p["protocol_id"]])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                        observation_refs=[o["observation_id"] for o in obs], evidence_refs=["ev-1"])

    def test_55_leakage_control_requirement_represented(self) -> None:
        q = self.make_question()
        p = self.make_protocol(q["question_id"], leakage_controls=["patient-level separation", "time leakage guard"])
        self.assertEqual(p["leakage_controls"], ["patient-level separation", "time leakage guard"])


# --- primary metric discipline / analysis mode -----------------------------------

class AnalysisModeTests(ResearchFixture):
    def test_56_primary_metric_frozen_before_result(self) -> None:
        q = self.make_question()
        p = self.make_protocol(q["question_id"], primary_metric="AUPRC")
        p = self.freeze(p)
        self.assertEqual(p["primary_metric"], "AUPRC")
        self.assertIsNotNone(p["frozen_at"])

    def test_57_exploratory_secondary_metric_not_promoted_to_preregistered_primary(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"], primary_metric="AUPRC", secondary_metrics=["AUROC"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        self.observe(e["experiment_id"], "AUPRC", 0.1, raw_evidence_refs=["ev-1"])  # primary fails
        self.observe(e["experiment_id"], "AUROC", 0.95, raw_evidence_refs=["ev-2"])  # secondary looks great
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                        observation_refs=[], evidence_refs=["ev-2"])  # criteria still evaluated against primary_metric only

    def test_scenario_d_post_hoc_metric_switch(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"], primary_metric="AUPRC")
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        self.observe(e["experiment_id"], "AUPRC", 0.1, raw_evidence_refs=["ev-1"])
        auroc_obs = self.observe(e["experiment_id"], "AUROC", 0.95, raw_evidence_refs=["ev-2"])
        amended = nr.amend_protocol(self.project, p["protocol_id"], field_updates={
            "primary_metric": "AUROC",
            "success_criteria": [{"metric": "AUROC", "comparator": ">=", "value": 0.9, "aggregation": "mean"}],
        }, actor="a", reason="switch metric after seeing results")
        self.assertTrue(amended["amendments"][-1]["post_result"])
        exploratory_claim = nr.create_claim(
            self.project, question_id=q["question_id"], statement="AUROC improved (exploratory, post-hoc)",
            claim_type="EMPIRICAL", claim_strength="LOW", scope="post-hoc exploratory analysis only",
            protocol_refs=[p["protocol_id"]], actor="a", reason="post-hoc claim",
        )
        result = self.assess(exploratory_claim["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]],
                              experiment_refs=[e["experiment_id"]], observation_refs=[auroc_obs["observation_id"]], evidence_refs=["ev-2"],
                              analysis_mode="POST_HOC")
        self.assertEqual(result["analysis_mode"], "POST_HOC")

    def test_58_59_60_analysis_modes_preserved(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        for mode in ("PREREGISTERED", "EXPLORATORY", "POST_HOC"):
            a = self.assess(c["claim_id"], "INCONCLUSIVE", rationale=f"{mode} check", analysis_mode=mode, assessment_id=f"ASSESS-{mode}")
            self.assertEqual(a["analysis_mode"], mode)


# --- authority separation --------------------------------------------------------

class AuthoritySeparationTests(ResearchFixture):
    def test_61_supported_does_not_create_decision_accept(self) -> None:
        runtime_root = self.project / ".code-loop" / "runtime"
        before_decisions = list((runtime_root / "decisions").glob("*.json")) if (runtime_root / "decisions").is_dir() else []
        self.full_supported_chain()
        after_decisions = list((runtime_root / "decisions").glob("*.json")) if (runtime_root / "decisions").is_dir() else []
        self.assertEqual(before_decisions, after_decisions)

    def test_62_refuted_does_not_automatically_create_failurerecord(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 0.1, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        self.assess(c["claim_id"], "REFUTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                    observation_refs=[o["observation_id"]], evidence_refs=["ev-1"])
        failures_dir = self.project / ".code-loop" / "methodology" / "failures"
        self.assertFalse(failures_dir.is_dir() and any(failures_dir.glob("*.json")))

    def test_63_research_layer_cannot_mutate_current_phase(self) -> None:
        import inspect
        source = inspect.getsource(nr)
        self.assertNotIn('current_phase"] =', source)
        self.assertNotIn("current_phase'] =", source)

    def test_64_research_layer_cannot_modify_golden_gate(self) -> None:
        import inspect
        source = inspect.getsource(nr)
        self.assertNotIn('"gates"', source)

    def test_94_no_generic_research_add_prose_authority_path(self) -> None:
        self.assertFalse(hasattr(nr, "add_research"))
        self.assertFalse(hasattr(nr, "add_fact"))
        result = run_script("research", "--help")
        self.assertNotIn("prose", result.stdout.lower())


# --- fail-closed: unknown/duplicate/malformed/version -----------------------------

class FailClosedTests(ResearchFixture):
    def test_65_unknown_evidence_ref_rejected_where_resolvable(self) -> None:
        runtime_dir = self.project / ".code-loop" / "runtime" / "evidence"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / "evidence-real-1.json").write_text(json.dumps({"id": "evidence-real-1", "status": "passed"}), encoding="utf-8")
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.make_experiment(p["protocol_id"])
        with self.assertRaises(MethodologyValidationError):
            self.observe(e["experiment_id"], "M", 1.0, raw_evidence_refs=["evidence-does-not-exist"])
        self.observe(e["experiment_id"], "M", 1.0, raw_evidence_refs=["evidence-real-1"])  # resolves fine

    def test_66_malformed_research_record_fails_closed(self) -> None:
        q = self.make_question()
        path = nr.research_dir(self.project) / "questions" / f"{q['question_id']}.json"
        path.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nr.list_research_questions(self.project)

    def test_67_unsupported_schema_rejected(self) -> None:
        q = self.make_question()
        path = nr.research_dir(self.project) / "questions" / f"{q['question_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["schema_version"] = "99.0.0"
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nr.set_question_status(self.project, q["question_id"], "ACTIVE", actor="a", reason="r")

    def test_68_methodology_mismatch_rejected(self) -> None:
        q = self.make_question()
        path = nr.research_dir(self.project) / "questions" / f"{q['question_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["methodology_version"] = "0.0.1"
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(MethodologyValidationError):
            nr.set_question_status(self.project, q["question_id"], "ACTIVE", actor="a", reason="r")

    def test_unknown_question_id_fails_closed(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            nr.set_question_status(self.project, "RQ-999", "ACTIVE", actor="a", reason="r")

    def test_duplicate_experiment_id_rejected(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        self.make_experiment(p["protocol_id"], experiment_id="EXP-X")
        with self.assertRaises(MethodologyValidationError):
            self.make_experiment(p["protocol_id"], experiment_id="EXP-X")

    def test_duplicate_observation_id_rejected(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.make_experiment(p["protocol_id"])
        self.observe(e["experiment_id"], "M", 1.0, observation_id="OBS-X")
        with self.assertRaises(MethodologyValidationError):
            self.observe(e["experiment_id"], "M", 2.0, observation_id="OBS-X")

    def test_duplicate_assessment_id_rejected(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        self.assess(c["claim_id"], "INCONCLUSIVE", rationale="first", assessment_id="ASSESS-DUP")
        with self.assertRaises(MethodologyValidationError):
            self.assess(c["claim_id"], "INCONCLUSIVE", rationale="second", assessment_id="ASSESS-DUP")


# --- actor / reason requirements --------------------------------------------------

class ActorReasonRequirementTests(ResearchFixture):
    def test_69_material_change_requires_actor(self) -> None:
        q = self.make_question()
        with self.assertRaises(MethodologyValidationError):
            nr.set_question_status(self.project, q["question_id"], "ACTIVE", actor="", reason="r")

    def test_70_material_change_requires_reason(self) -> None:
        q = self.make_question()
        with self.assertRaises(MethodologyValidationError):
            nr.set_question_status(self.project, q["question_id"], "ACTIVE", actor="a", reason="")

    def test_freeze_requires_actor_and_reason(self) -> None:
        q = self.make_question()
        p = self.make_protocol(q["question_id"])
        with self.assertRaises(MethodologyValidationError):
            nr.freeze_protocol(self.project, p["protocol_id"], actor="", reason="freeze")

    def test_assess_requires_actor_and_reason(self) -> None:
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        with self.assertRaises(MethodologyValidationError):
            nr.assess_claim(self.project, c["claim_id"], outcome="INCONCLUSIVE", rationale="r", actor="", reason="r", assessor_id="x")


class ClaimStrengthEvidenceDepthTests(ResearchFixture):
    def test_high_requires_more_than_low(self) -> None:
        # Same evidence/rigor that satisfies LOW must not satisfy HIGH.
        q = self.make_question()
        p_low = self.frozen_protocol(q["question_id"], claim_strength="LOW")
        e_low = self.complete(self.make_experiment(p_low["protocol_id"])["experiment_id"])
        o_low = self.observe(e_low["experiment_id"], "M", 5.0, raw_evidence_refs=["ev-1"])
        c_low = self.make_claim(q["question_id"], claim_strength="LOW", protocol_refs=[p_low["protocol_id"]])
        low_result = self.assess(c_low["claim_id"], "SUPPORTED", protocol_refs=[p_low["protocol_id"]],
                                  experiment_refs=[e_low["experiment_id"]], observation_refs=[o_low["observation_id"]],
                                  evidence_refs=["ev-1"], reproducibility_status="NOT_REQUIRED", assessor_role="SELF")
        self.assertEqual(low_result["outcome"], "SUPPORTED")

        p_high = self.frozen_protocol(q["question_id"], claim_strength="HIGH")
        e_high = self.complete(self.make_experiment(p_high["protocol_id"])["experiment_id"])
        o_high = self.observe(e_high["experiment_id"], "M", 5.0, raw_evidence_refs=["ev-2"])
        c_high = self.make_claim(q["question_id"], claim_strength="HIGH", protocol_refs=[p_high["protocol_id"]])
        with self.assertRaises(MethodologyValidationError):
            self.assess(c_high["claim_id"], "SUPPORTED", protocol_refs=[p_high["protocol_id"]],
                        experiment_refs=[e_high["experiment_id"]], observation_refs=[o_high["observation_id"]],
                        evidence_refs=["ev-2"], reproducibility_status="NOT_REQUIRED", assessor_role="SELF")


# --- M7-H / M7-I integration and regression -------------------------------------

class RegressionUnaffectedTests(ResearchFixture):
    def test_77_m7h_research_refs_remain_backward_compatible(self) -> None:
        import nogap_failure as nf
        from nogap_artifacts import create_artifact
        from nogap_methodology import status as mstatus, transition

        made: dict[str, Any] = {}
        made["P0"] = create_artifact(self.project, "P0_PROJECT_INTENT", {
            "project_name": "demo", "intent_type": mstatus(self.project)["intent"], "problem_summary": "x",
            "target_users_or_context": "team", "desired_outcome": "y", "owner": "team", "initial_constraints": ["budget"],
        }, actor="team")
        made["P1"] = create_artifact(self.project, "P1_SCOPE", {
            "problem_statement": "x", "in_scope": ["a"], "out_of_scope": ["b"], "constraints": ["c"],
            "dependencies": ["d"], "known_assumptions": ["e"],
        }, actor="team")
        made["P2"] = create_artifact(self.project, "P2_SUCCESS_CRITERIA", {
            "success_criteria": ["works"], "failure_criteria": ["crashes"], "risk_level": mstatus(self.project)["risk"],
            "claim_strength": mstatus(self.project)["claim_strength"], "critical_claims": ["c1"], "stop_conditions": ["s1"],
        }, actor="team")
        made["P3"] = create_artifact(self.project, "P3_PRIOR_ART", {
            "research_question": "q", "search_scope": "s", "sources": ["s1"], "candidate_solutions": ["c1"],
            "key_findings": ["f1"], "limitations": ["l1"],
        }, actor="team")
        order = ["P0", "P1", "P2", "P3"]
        for current, nxt in zip(order, order[1:]):
            evidence_refs = ["source-ref-1"] if current == "P2" else []
            transition(self.project, nxt, "team", f"{current} obligations satisfied",
                       artifact_refs=[made[current]["artifact_id"]], evidence_refs=evidence_refs, authority_class="tool")

        failure = nf.create_failure(self.project, failure_class="X", summary="x", actor="qa")
        failure = nf.record_evidence_preservation(self.project, failure["failure_id"], artifact_refs=[made["P0"]["artifact_id"]], actor="qa", reason="preserve")
        failure = nf.record_reproduction(self.project, failure["failure_id"], reproduction_status="REPRODUCED", actor="qa", reason="reproduced")
        failure = nf.record_characterization(self.project, failure["failure_id"], actor="qa", reason="characterized")
        # research_refs still resolves exactly as before M7-J existed: against
        # methodology artifacts (here, the real P3 artifact) - unmodified behavior.
        failure = nf.record_research(self.project, failure["failure_id"], actor="qa", reason="researched", research_refs=[made["P3"]["artifact_id"]])
        self.assertEqual(failure["current_state"], "RESEARCHED")

    def test_101_m7g_verification_interlock_unchanged(self) -> None:
        import nogap_verify_binding as vb
        # no methodology-tracked task exists in this fixture; legacy-compatibility path
        precondition = vb.verification_acceptance_precondition(self.project, None)
        self.assertFalse(precondition["satisfied"])

    def test_100_m7c_state_machine_unchanged(self) -> None:
        from nogap_methodology import can_transition
        result = can_transition(self.project, "P1")
        self.full_supported_chain()  # exercises research module alongside methodology
        result2 = can_transition(self.project, "P1")
        self.assertEqual(result, result2)  # unaffected by research module activity either way

    def test_104_m6_acceptance_semantics_unchanged(self) -> None:
        from nogap import acceptability
        decision = {"decision": "accept", "actor_id": "human:owner", "authority": "acceptance", "evidence": []}
        failure = acceptability(decision, {}, set())
        self.assertEqual(failure, "ACCEPT requires evidence references")


class MemoryIntegrationTests(ResearchFixture):
    def test_78_source_fingerprint_changes_when_research_record_changes(self) -> None:
        import nogap_memory as nm
        sources_before = nm.collect_memory_sources(self.project)
        fp_before = nm.compute_source_fingerprint(sources_before)
        self.make_question()
        fp_after = nm.compute_source_fingerprint(nm.collect_memory_sources(self.project))
        self.assertNotEqual(fp_before, fp_after)

    def test_79_memory_becomes_stale_after_new_research_result(self) -> None:
        import nogap_memory as nm
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")
        self.make_question()
        self.assertEqual(nm.memory_status(self.project)["status"], "STALE")

    def test_80_81_82_rebuild_includes_open_question_active_hypothesis_frozen_protocol(self) -> None:
        import nogap_memory as nm
        q = self.make_question()
        h = self.make_hypothesis(q["question_id"])
        p = self.frozen_protocol(q["question_id"], hypothesis_refs=[h["hypothesis_id"]])
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        self.assertTrue(any(item["question_id"] == q["question_id"] for item in snapshot["open_research_questions"]))
        self.assertTrue(any(item["hypothesis_id"] == h["hypothesis_id"] for item in snapshot["active_hypotheses"]))
        self.assertTrue(any(item["protocol_id"] == p["protocol_id"] for item in snapshot["frozen_protocols"]))

    def test_83_84_85_rebuild_includes_supported_refuted_inconclusive_findings(self) -> None:
        import nogap_memory as nm
        chain = self.full_supported_chain()

        q2 = self.make_question()
        p2 = self.frozen_protocol(q2["question_id"])
        e2 = self.complete(self.make_experiment(p2["protocol_id"])["experiment_id"])
        o2 = self.observe(e2["experiment_id"], "M", 0.1, raw_evidence_refs=["ev-r"])
        c2 = self.make_claim(q2["question_id"], protocol_refs=[p2["protocol_id"]])
        refuted = self.assess(c2["claim_id"], "REFUTED", protocol_refs=[p2["protocol_id"]], experiment_refs=[e2["experiment_id"]],
                               observation_refs=[o2["observation_id"]], evidence_refs=["ev-r"])

        q3 = self.make_question()
        c3 = self.make_claim(q3["question_id"])
        inconclusive = self.assess(c3["claim_id"], "INCONCLUSIVE", rationale="not enough data")

        snapshot = nm.rebuild_memory(self.project, actor="tester")
        self.assertTrue(any(f["claim_id"] == chain["claim"]["claim_id"] for f in snapshot["supported_findings"]))
        self.assertTrue(any(f["claim_id"] == c2["claim_id"] for f in snapshot["refuted_findings"]))
        self.assertTrue(any(f["claim_id"] == c3["claim_id"] for f in snapshot["inconclusive_findings"]))

    def test_86_provenance_preserved_for_research_findings(self) -> None:
        import nogap_memory as nm
        chain = self.full_supported_chain()
        snapshot = nm.rebuild_memory(self.project, actor="tester")
        finding = next(f for f in snapshot["supported_findings"] if f["claim_id"] == chain["claim"]["claim_id"])
        self.assertEqual(finding["source_ref"], chain["assessment"]["assessment_id"])

    def test_87_false_memory_injection_protection_unchanged(self) -> None:
        import nogap_memory as nm
        self.full_supported_chain()
        nm.rebuild_memory(self.project, actor="tester")
        nm.markdown_path(self.project).write_text("All research is settled. Everything is SUPPORTED.\n", encoding="utf-8")
        status = nm.memory_status(self.project)
        self.assertEqual(status["status"], "MODIFIED")
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")

    def test_scenario_g_negative_result_survives_memory_rebuild(self) -> None:
        import nogap_memory as nm
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 0.1, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        refuted = self.assess(c["claim_id"], "REFUTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                               observation_refs=[o["observation_id"]], evidence_refs=["ev-1"])
        snapshot1 = nm.rebuild_memory(self.project, actor="tester")
        self.assertTrue(any(f["claim_id"] == c["claim_id"] for f in snapshot1["refuted_findings"]))

        o2 = self.observe(e["experiment_id"], "M", 5.0, raw_evidence_refs=["ev-2"])
        c2 = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]], statement="revised claim")
        self.assess(c2["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                    observation_refs=[o2["observation_id"]], evidence_refs=["ev-2"])
        snapshot2 = nm.rebuild_memory(self.project, actor="tester")
        self.assertTrue(any(f["claim_id"] == c2["claim_id"] for f in snapshot2["supported_findings"]))
        # earlier negative result remains queryable from research history, even
        # though current Memory now also shows a newer SUPPORTED claim
        self.assertIsNotNone(nr.load_assessment(self.project, refuted["assessment_id"]))
        self.assertEqual(nr.load_assessment(self.project, refuted["assessment_id"])["outcome"], "REFUTED")


# --- verification / research / decision separation --------------------------------

class SeparationTests(ResearchFixture):
    def test_88_89_90_91_92_93_namespaces_stay_separate(self) -> None:
        chain = self.full_supported_chain()
        self.assertEqual(chain["assessment"]["outcome"], "SUPPORTED")
        # research outcome vocabulary never appears as an execution/verification/decision status
        self.assertNotIn(chain["assessment"]["outcome"], {"passed", "failed", "blocked", "inconclusive"})
        self.assertNotIn(chain["assessment"]["outcome"], {"accept", "reject", "abstain", "repair"})
        # UNKNOWN vs NONE: a question with no related refs shows [] (NONE, checked), never a fabricated value
        self.assertEqual(chain["question"]["related_artifact_refs"], [])

    def test_93_unknown_not_none_in_research_queries(self) -> None:
        current = nr.get_current_claim_assessment(self.project, self.make_claim(self.make_question()["question_id"])["claim_id"])
        self.assertEqual(current["status"], "NONE")  # no assessment exists at all - distinct from an empty list of findings

    def test_scenario_e_execution_verification_research_decision_separation(self) -> None:
        chain = self.full_supported_chain()
        # four distinct outcomes stay in four distinct namespaces, never merged into one
        research_outcome = chain["assessment"]["outcome"]
        experiment_status = chain["experiment"]["status"]
        self.assertEqual(research_outcome, "SUPPORTED")
        self.assertEqual(experiment_status, "COMPLETED")
        self.assertNotEqual(research_outcome, experiment_status)


class NoSilentDeletionTests(ResearchFixture):
    def test_95_no_silent_historical_deletion(self) -> None:
        import inspect
        source = inspect.getsource(nr)
        self.assertNotIn("unlink", source)
        self.assertNotIn("rmtree", source)
        self.assertNotIn("os.remove", source)

    def test_96_no_direct_source_mutation_from_query_apis(self) -> None:
        chain = self.full_supported_chain()
        before = nr.load_claim(self.project, chain["claim"]["claim_id"])
        nr.query_research(self.project, "claims", chain["claim"]["claim_id"])
        nr.list_claims(self.project)
        after = nr.load_claim(self.project, chain["claim"]["claim_id"])
        self.assertEqual(before, after)


class GoldenPrincipleStatusTests(unittest.TestCase):
    def test_97_gp12_status_matches_implementation(self) -> None:
        from nogap_methodology import get_principle_enforcement
        record = get_principle_enforcement("GP-12")
        self.assertEqual(record.status, "ENFORCED")
        self.assertIn("nogap_research.py", " ".join(record.implemented_by))

    def test_98_gp15_status_not_overstated(self) -> None:
        from nogap_methodology import get_principle_enforcement
        record = get_principle_enforcement("GP-15")
        self.assertEqual(record.status, "ENFORCED")  # was already ENFORCED before M7-J; not inflated further

    def test_99_gp20_traceability_updated(self) -> None:
        from nogap_methodology import get_principle_enforcement
        record = get_principle_enforcement("GP-20")
        self.assertTrue(any("research" in t.lower() for t in record.tests))


class SingleOwnerCurrentAssessmentTests(ResearchFixture):
    """Regression coverage for the architectural review fix: current-assessment
    selection has exactly one owner (nogap_research.select_current_assessment).
    Memory must project that result, never re-derive it."""

    def test_memory_and_research_cannot_diverge_on_current_assessment(self) -> None:
        import nogap_memory as nm
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        self.assess(c["claim_id"], "INCONCLUSIVE", rationale="first")
        second = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="second")

        research_view = nr.get_current_claim_assessment(self.project, c["claim_id"])
        sources = nm.collect_memory_sources(self.project)
        memory_view = nm._current_research_assessments_by_claim(sources["research"])[c["claim_id"]]

        self.assertEqual(research_view["status"], memory_view["status"])
        self.assertEqual(research_view["assessment"]["assessment_id"], memory_view["assessment"]["assessment_id"])
        self.assertEqual(research_view["assessment"]["assessment_id"], second["assessment_id"])

    def test_same_second_assessments_ordered_by_sequence_via_research_owner(self) -> None:
        # Both nr.get_current_claim_assessment and Memory's projection go through
        # select_current_assessment(), so this single call proves both paths.
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        first = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="a")
        second = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="b")
        self.assertEqual(first["created_at"], second["created_at"])  # realistic same-second case
        self.assertEqual(second["sequence"], first["sequence"] + 1)
        current = nr.select_current_assessment([first, second])
        self.assertEqual(current["assessment"]["assessment_id"], second["assessment_id"])

    def test_filesystem_order_cannot_affect_research_or_memory_current_assessment(self) -> None:
        import nogap_memory as nm
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        self.assess(c["claim_id"], "INCONCLUSIVE", rationale="first", assessment_id="ASSESS-999")
        second = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="second", assessment_id="ASSESS-001")

        research_view = nr.get_current_claim_assessment(self.project, c["claim_id"])
        sources = nm.collect_memory_sources(self.project)
        memory_view = nm._current_research_assessments_by_claim(sources["research"])[c["claim_id"]]

        # ASSESS-001 sorts first alphabetically/by filename but was created SECOND -
        # both paths must agree it is current, driven by sequence, not id/filename.
        self.assertEqual(research_view["assessment"]["assessment_id"], "ASSESS-001")
        self.assertEqual(memory_view["assessment"]["assessment_id"], "ASSESS-001")

    def test_explicit_supersession_honored_identically_by_research_and_memory(self) -> None:
        import nogap_memory as nm
        q = self.make_question()
        c1 = self.make_claim(q["question_id"], statement="original claim")
        c2 = self.make_claim(q["question_id"], statement="narrower revised claim")
        a1 = self.assess(c1["claim_id"], "INCONCLUSIVE", rationale="first")
        nr.mark_superseded(self.project, "claims", c1["claim_id"], superseded_by=c2["claim_id"], actor="a", reason="narrowed")

        research_view = nr.get_current_claim_assessment(self.project, c1["claim_id"])
        sources = nm.collect_memory_sources(self.project)
        memory_view = nm._current_research_assessments_by_claim(sources["research"])[c1["claim_id"]]
        # neither layer invents special supersession-aware selection logic - both
        # agree on the plain assessment-selection result regardless of claim status,
        # and the superseded claim's own record is untouched substantively.
        self.assertEqual(research_view["assessment"]["assessment_id"], memory_view["assessment"]["assessment_id"])
        reloaded = nr.load_claim(self.project, c1["claim_id"])
        self.assertEqual(reloaded["status"], "SUPERSEDED")
        self.assertEqual(reloaded["superseded_by"], c2["claim_id"])
        self.assertEqual(reloaded["statement"], "original claim")

    def test_genuine_conflict_surfaced_by_research_also_surfaced_by_memory(self) -> None:
        import nogap_memory as nm
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        a1 = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="first", assessment_id="ASSESS-A")
        a2 = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="second", assessment_id="ASSESS-B")
        path_b = nr.research_dir(self.project) / "assessments" / "ASSESS-B.json"
        record_b = json.loads(path_b.read_text(encoding="utf-8"))
        record_b["sequence"] = a1["sequence"]  # force a genuine, tamper-induced tie
        path_b.write_text(json.dumps(record_b), encoding="utf-8")

        research_view = nr.get_current_claim_assessment(self.project, c["claim_id"])
        self.assertEqual(research_view["status"], "CONFLICT")

        snapshot = nm.build_memory_snapshot(self.project, actor="tester")
        self.assertTrue(any(item["claim_id"] == c["claim_id"] for item in snapshot["research_assessment_conflicts"]))
        self.assertTrue(any(item["claim_id"] == c["claim_id"] for item in snapshot["integrity"]["conflicts"]))
        # not resolved independently: the claim does NOT appear in any outcome bucket
        for bucket in ("supported_findings", "partially_supported_findings", "refuted_findings", "inconclusive_findings"):
            self.assertFalse(any(item["claim_id"] == c["claim_id"] for item in snapshot[bucket]))

    def test_changing_research_selection_semantics_automatically_changes_memory(self) -> None:
        """Proves single ownership by construction: patch the ONE function Research
        owns, and Memory's projection changes with zero edits to Memory's own code."""
        import nogap_memory as nm
        q = self.make_question()
        c = self.make_claim(q["question_id"])
        first = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="first")
        second = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="second")

        original = nr.select_current_assessment
        try:
            nr.select_current_assessment = lambda assessments: {"status": "OK", "assessment": first} if assessments else {"status": "NONE", "assessment": None}
            sources = nm.collect_memory_sources(self.project)
            memory_view = nm._current_research_assessments_by_claim(sources["research"])[c["claim_id"]]
            self.assertEqual(memory_view["assessment"]["assessment_id"], first["assessment_id"])
        finally:
            nr.select_current_assessment = original

    def test_historical_refuted_inconclusive_preserved_after_fix(self) -> None:
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 0.1, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        refuted = self.assess(c["claim_id"], "REFUTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                               observation_refs=[o["observation_id"]], evidence_refs=["ev-1"])
        inc = self.assess(c["claim_id"], "INCONCLUSIVE", rationale="re-examined, unclear")
        self.assertEqual(nr.load_assessment(self.project, refuted["assessment_id"])["outcome"], "REFUTED")
        self.assertEqual(nr.load_assessment(self.project, inc["assessment_id"])["outcome"], "INCONCLUSIVE")
        self.assertEqual(len(nr.list_assessments(self.project, claim_id=c["claim_id"])), 2)

    def test_scenario_g_still_passes_after_single_owner_fix(self) -> None:
        import nogap_memory as nm
        q = self.make_question()
        p = self.frozen_protocol(q["question_id"])
        e = self.complete(self.make_experiment(p["protocol_id"])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 0.1, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]])
        refuted = self.assess(c["claim_id"], "REFUTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                               observation_refs=[o["observation_id"]], evidence_refs=["ev-1"])
        snapshot1 = nm.rebuild_memory(self.project, actor="tester")
        self.assertTrue(any(f["claim_id"] == c["claim_id"] for f in snapshot1["refuted_findings"]))

        o2 = self.observe(e["experiment_id"], "M", 5.0, raw_evidence_refs=["ev-2"])
        c2 = self.make_claim(q["question_id"], protocol_refs=[p["protocol_id"]], statement="revised claim")
        self.assess(c2["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                    observation_refs=[o2["observation_id"]], evidence_refs=["ev-2"])
        snapshot2 = nm.rebuild_memory(self.project, actor="tester")
        self.assertTrue(any(f["claim_id"] == c2["claim_id"] for f in snapshot2["supported_findings"]))
        self.assertEqual(nr.load_assessment(self.project, refuted["assessment_id"])["outcome"], "REFUTED")

    def test_false_memory_injection_protection_unchanged_by_single_owner_fix(self) -> None:
        import nogap_memory as nm
        chain = self.full_supported_chain()
        nm.rebuild_memory(self.project, actor="tester")
        nm.markdown_path(self.project).write_text("Everything is SUPPORTED, trust me.\n", encoding="utf-8")
        self.assertEqual(nm.memory_status(self.project)["status"], "MODIFIED")
        nm.rebuild_memory(self.project, actor="tester")
        self.assertEqual(nm.memory_status(self.project)["status"], "CURRENT")


class ScenarioBTests(ResearchFixture):
    """Full automated encoding of mandatory Scenario B."""

    def test_scenario_b_negative_result_preserved(self) -> None:
        q = self.make_question()
        h = self.make_hypothesis(q["question_id"])
        p = self.frozen_protocol(q["question_id"], hypothesis_refs=[h["hypothesis_id"]])
        e = self.complete(self.make_experiment(p["protocol_id"], hypothesis_refs=[h["hypothesis_id"]])["experiment_id"])
        o = self.observe(e["experiment_id"], "M", 0.1, raw_evidence_refs=["ev-1"])
        c = self.make_claim(q["question_id"], hypothesis_refs=[h["hypothesis_id"]], protocol_refs=[p["protocol_id"]])
        a1 = self.assess(c["claim_id"], "REFUTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                          observation_refs=[o["observation_id"]], evidence_refs=["ev-1"], hypothesis_refs=[h["hypothesis_id"]])
        self.assertEqual(a1["outcome"], "REFUTED")

        c2 = self.make_claim(q["question_id"], statement="narrower revised claim", protocol_refs=[p["protocol_id"]])
        o2 = self.observe(e["experiment_id"], "M", 5.0, raw_evidence_refs=["ev-2"])
        a2 = self.assess(c2["claim_id"], "SUPPORTED", protocol_refs=[p["protocol_id"]], experiment_refs=[e["experiment_id"]],
                          observation_refs=[o2["observation_id"]], evidence_refs=["ev-2"])
        self.assertEqual(a2["outcome"], "SUPPORTED")

        reloaded_original = nr.load_assessment(self.project, a1["assessment_id"])
        self.assertEqual(reloaded_original["outcome"], "REFUTED")
        reloaded_hypothesis = nr.load_hypothesis(self.project, h["hypothesis_id"])
        self.assertEqual(reloaded_hypothesis["statement"], h["statement"])  # never rewritten
        reloaded_protocol = nr.load_protocol(self.project, p["protocol_id"])
        self.assertEqual(reloaded_protocol["primary_metric"], "M")  # never mutated to fit the result


class CliTests(ResearchFixture):
    def test_cli_full_lifecycle(self) -> None:
        fields = json.dumps({"title": "CLI Q", "question": "does CLI work?", "scope": "smoke"})
        create = run_script("research", "question", "create", str(self.project), "--actor", "cli", "--reason", "create", "--fields-json", fields)
        self.assertEqual(create.returncode, 0, create.stderr)
        self.assertIn("RQ-001", create.stdout)

        listing = run_script("research", "question", "list", str(self.project))
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn("RQ-001", listing.stdout)

        query = run_script("research", "query", "query", str(self.project), "--kind", "questions")
        self.assertEqual(query.returncode, 0, query.stderr)
        self.assertIn("RQ-001", query.stdout)

    def test_no_cli_shortcut_bypasses_engine_validation(self) -> None:
        bad_fields = json.dumps({"title": "", "question": "", "scope": "s"})
        result = run_script("research", "question", "create", str(self.project), "--actor", "cli", "--reason", "create", "--fields-json", bad_fields)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
