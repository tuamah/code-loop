#!/usr/bin/env python3
"""M8-E4-C: Semantic Replay Verifier - regression suite.

Covers verify_decision_replay() and DecisionReplayVerificationResult:
instance-level semantic replay verification against a DecisionReplayMaterial
object, using ONLY the existing frozen kernel path
(validate_decision_replay_material/compute_input_fingerprint/
evaluate_decision/build_decision_record). This module tests SEMANTIC REPLAY
VERIFICATION ONLY - there is no journal/checkpoint dependency, no
persistence, no evidence re-fetch, no retrieval, and no current-applicability
check anywhere in this file or in the production code it exercises.

Kept deliberately separate from tests/test_decision_replay_material.py:
E4-B = material contract, E4-C = semantic replay verification.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap_decision as nd  # noqa: E402


# --- shared builders (self-contained, matching every other M8 test file's
# own established convention - no cross-test-file import) -----------------

def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def scope(**overrides) -> nd.DecisionScope:
    fields = dict(scope_type="TASK", scope_id="TASK-1", project_id="proj-1")
    fields.update(overrides)
    return nd.DecisionScope(**fields)


def requirement(predicate_id: str, truth: str, *, required: bool = True, **overrides) -> nd.DecisionPredicateResult:
    fields = dict(predicate_id=predicate_id, role="REQUIREMENT", truth_value=truth, required=required, blocking=False)
    fields.update(overrides)
    return nd.DecisionPredicateResult(**fields)


def policy(required_ids=(), blocking_ids=(), optional_ids=(), **overrides) -> nd.DecisionPolicyContract:
    fields = dict(
        decision_type="TASK_ACCEPTANCE", policy_id="policy-1", policy_version="1",
        required_predicate_ids=tuple(required_ids), blocking_predicate_ids=tuple(blocking_ids),
        optional_predicate_ids=tuple(optional_ids),
    )
    fields.update(overrides)
    return nd.DecisionPolicyContract(**fields)


def revision(seed: str) -> str:
    return digest(seed)[:40]


def m8c_subject(**overrides) -> nd.DecisionSubject:
    fields = dict(subject_type="TASK", subject_id="TASK-1", project_id="proj-1", revision_ref=revision("rev-1"))
    fields.update(overrides)
    return nd.DecisionSubject(**fields)


def m8c_snapshot(**overrides) -> nd.DecisionSnapshot:
    fields = dict(
        request_id="req-1", decision_type="TASK_ACCEPTANCE", scope=scope(), subject=m8c_subject(),
        policy_ref=nd.SnapshotReference(ref_kind="POLICY", ref_id="policy-1", fingerprint=digest("policy-content")),
    )
    fields.update(overrides)
    return nd.build_decision_snapshot(**fields)


def evidence_ref(ref_id: str = "ev-1", fingerprint: str | None = None, ref_kind: str = "VERIFICATION_EVIDENCE", **overrides) -> nd.SnapshotReference:
    fields = dict(ref_kind=ref_kind, ref_id=ref_id, fingerprint=fingerprint or digest(f"{ref_kind}:{ref_id}"))
    fields.update(overrides)
    return nd.SnapshotReference(**fields)


SNAPSHOT = m8c_snapshot()
POLICY = policy(required_ids=("P1",))


def m8d_binding(result: nd.DecisionPredicateResult, *, snap: nd.DecisionSnapshot | None = None, pol: nd.DecisionPolicyContract | None = None, **overrides) -> nd.PredicateEvidenceBinding:
    snap = snap if snap is not None else SNAPSHOT
    pol = pol if pol is not None else POLICY
    needs_evidence = result.truth_value in {"TRUE", "FALSE"}
    fields = dict(
        predicate_result_fingerprint=result.result_fingerprint,
        snapshot_fingerprint=snap.snapshot_fingerprint,
        policy_id=pol.policy_id, policy_version=pol.policy_version,
        evidence_refs=(evidence_ref(ref_id=f"ev-{result.predicate_id}"),) if needs_evidence else (),
        verifier_id="verifier-x",
    )
    fields.update(overrides)
    return nd.PredicateEvidenceBinding(**fields)


def historical_material(*, snap=None, pol=None, results=None, bindings=None, executor_ids=frozenset(), evaluation_id="historical-eval", created_at="2026-01-01T00:00:00Z", **material_overrides) -> nd.DecisionReplayMaterial:
    """Runs the REAL historical decision-production pipeline exactly once
    through the live kernel (evaluate_decision/build_decision_record) - this
    is ordinary test-fixture setup for 'what happened historically', never
    the production replay path this module tests."""
    snap = snap if snap is not None else SNAPSHOT
    pol = pol if pol is not None else POLICY
    if results is None:
        results = (requirement("P1", "TRUE"),)
    if bindings is None:
        bindings = tuple(m8d_binding(r, snap=snap, pol=pol) for r in results)
    evaluation = nd.evaluate_decision(snap, pol, results, bindings, executor_ids, evaluation_id=evaluation_id)
    record = nd.build_decision_record(evaluation, decision_id="historical-decision", created_at=created_at)
    fields = dict(
        snapshot=snap, policy=pol, predicate_results=tuple(results), predicate_evidence_bindings=tuple(bindings),
        executor_ids=executor_ids, engine_version=nd.M8_DECISION_ENGINE_VERSION,
        expected_input_fingerprint=evaluation.input_fingerprint,
        expected_evaluation_fingerprint=evaluation.evaluation_fingerprint,
        expected_decision_fingerprint=record.decision_fingerprint,
    )
    fields.update(material_overrides)
    return nd.DecisionReplayMaterial(**fields)


def retamper(m: nd.DecisionReplayMaterial, **overrides) -> nd.DecisionReplayMaterial:
    """Builds a new DecisionReplayMaterial reusing every field of `m` except
    the ones overridden - used to construct adversarial variants that keep
    stale expected_* commitments from a DIFFERENT (historical) raw input."""
    fields = dict(
        snapshot=m.snapshot, policy=m.policy, predicate_results=m.predicate_results,
        predicate_evidence_bindings=m.predicate_evidence_bindings, executor_ids=m.executor_ids,
        engine_version=m.engine_version, expected_input_fingerprint=m.expected_input_fingerprint,
        expected_evaluation_fingerprint=m.expected_evaluation_fingerprint,
        expected_decision_fingerprint=m.expected_decision_fingerprint,
    )
    fields.update(overrides)
    return nd.DecisionReplayMaterial(**fields)


def code_only(*objs) -> str:
    source = "".join(inspect.getsource(obj) for obj in objs)
    return re.sub(r'"""[\s\S]*?"""', "", source)


def called_function_names(*objs) -> set[str]:
    names: set[str] = set()
    for obj in objs:
        tree = ast.parse(inspect.getsource(obj))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    names.add(func.attr)
    return names


# --- A. VALID REPLAY MATCH ------------------------------------------------------------

class ValidReplayMatchTests(unittest.TestCase):
    def test_1_valid_material_replays_to_match(self) -> None:
        result = nd.verify_decision_replay(historical_material())
        self.assertEqual(result.status, "REPLAY_MATCH")
        self.assertTrue(result.verified)
        self.assertEqual(result.reason_code, "REPLAY_MATCH")

    def test_2_result_type_is_decision_replay_verification_result(self) -> None:
        result = nd.verify_decision_replay(historical_material())
        self.assertIsInstance(result, nd.DecisionReplayVerificationResult)

    def test_3_result_is_frozen(self) -> None:
        result = nd.verify_decision_replay(historical_material())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.verified = False  # type: ignore[misc]

    def test_4_verified_true_iff_status_replay_match_enforced_at_construction(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.DecisionReplayVerificationResult(status="REPLAY_MATCH", verified=False, reason_code="REPLAY_MATCH")
        with self.assertRaises(nd.DecisionValidationError):
            nd.DecisionReplayVerificationResult(status="MATERIAL_INVALID", verified=True, reason_code="MATERIAL_INVALID")

    def test_5_reason_code_must_mirror_status(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.DecisionReplayVerificationResult(status="REPLAY_MATCH", verified=True, reason_code="MATERIAL_INVALID")

    def test_6_unknown_status_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.DecisionReplayVerificationResult(status="TOTALLY_BOGUS", verified=False, reason_code="TOTALLY_BOGUS")


# --- B. DETERMINISM --------------------------------------------------------------------

class DeterminismTests(unittest.TestCase):
    def test_7_repeated_replay_of_same_material_yields_identical_result(self) -> None:
        m = historical_material()
        r1 = nd.verify_decision_replay(m)
        r2 = nd.verify_decision_replay(m)
        self.assertEqual(r1, r2)

    def test_8_repeated_replay_of_mismatched_material_yields_identical_result(self) -> None:
        m = retamper(historical_material(), expected_input_fingerprint=digest("bogus"))
        r1 = nd.verify_decision_replay(m)
        r2 = nd.verify_decision_replay(m)
        self.assertEqual(r1, r2)


# --- C. MATERIAL / ENGINE-VERSION GATES -------------------------------------------------

class MaterialAndEngineVersionGateTests(unittest.TestCase):
    def test_9_invalid_material_type_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.verify_decision_replay("not-a-material")  # type: ignore[arg-type]

    def test_10_self_verification_binding_yields_material_invalid(self) -> None:
        # Built directly (not through historical_material()'s live-kernel
        # pipeline) - the live kernel would ALSO reject a self-verifying
        # binding at production time, so this exact material could never
        # have been produced historically in the first place; placeholder
        # expected_* digests are sufficient since verify_decision_replay's
        # material-validity gate (step 1) must fail before any fingerprint
        # comparison is ever attempted.
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1, verifier_id="executor-1")
        m = nd.DecisionReplayMaterial(
            snapshot=SNAPSHOT, policy=POLICY, predicate_results=(r1,), predicate_evidence_bindings=(b1,),
            executor_ids=frozenset({"executor-1"}), engine_version=nd.M8_DECISION_ENGINE_VERSION,
            expected_input_fingerprint=digest("placeholder-input"),
            expected_evaluation_fingerprint=digest("placeholder-eval"),
            expected_decision_fingerprint=digest("placeholder-decision"),
        )
        result = nd.verify_decision_replay(m)
        self.assertEqual(result.status, "MATERIAL_INVALID")
        self.assertFalse(result.verified)

    def test_11_unsupported_engine_version_cannot_be_constructed_fails_closed_at_e4b(self) -> None:
        # M8-E4-B's own frozen construction-time gate already refuses
        # unsupported engine_version - M8-E4-C never even receives such
        # material. NO FALSE UPGRADE.
        with self.assertRaises(nd.DecisionValidationError):
            historical_material(engine_version="1")

    def test_12_no_migration_upgrade_or_backfill_exists(self) -> None:
        self.assertFalse(hasattr(nd, "migrate_decision_replay_material"))
        self.assertFalse(hasattr(nd, "upgrade_decision_replay_material"))
        self.assertFalse(hasattr(nd, "replay_legacy_engine_version"))


# --- D. EXPECTED-COMMITMENT TAMPERING (Sections 24/31/32) -------------------------------

class ExpectedCommitmentTamperingTests(unittest.TestCase):
    def test_13_expected_input_fingerprint_tampering_detected_no_evaluation_replayed(self) -> None:
        m = retamper(historical_material(), expected_input_fingerprint=digest("tampered-input"))
        with mock.patch.object(nd, "evaluate_decision", wraps=nd.evaluate_decision) as spy:
            result = nd.verify_decision_replay(m)
        self.assertEqual(result.status, "INPUT_FINGERPRINT_MISMATCH")
        self.assertFalse(result.verified)
        spy.assert_not_called()

    def test_14_expected_evaluation_fingerprint_tampering_detected_no_record_built(self) -> None:
        m = retamper(historical_material(), expected_evaluation_fingerprint=digest("tampered-eval"))
        with mock.patch.object(nd, "build_decision_record", wraps=nd.build_decision_record) as spy:
            result = nd.verify_decision_replay(m)
        self.assertEqual(result.status, "EVALUATION_FINGERPRINT_MISMATCH")
        self.assertFalse(result.verified)
        spy.assert_not_called()

    def test_15_expected_decision_fingerprint_tampering_detected(self) -> None:
        m = retamper(historical_material(), expected_decision_fingerprint=digest("tampered-decision"))
        result = nd.verify_decision_replay(m)
        self.assertEqual(result.status, "DECISION_FINGERPRINT_MISMATCH")
        self.assertFalse(result.verified)


# --- E. BEHAVIORAL-CONTEXT-COMMITTED SUBSTITUTION ADVERSARIAL CASES (Sections 25-29) -----

class BehavioralContextSubstitutionTests(unittest.TestCase):
    """Every case here changes a value E4-A's behavioral context commits
    (policy classification / verifier identity / verifier-binding pairing /
    executor identity) or a value M8-C's own result_fingerprint commits
    (truth_value), while retaining the STALE historical expected commitments
    - proving replay detects the divergence no later than input commitment."""

    def test_16_policy_required_classification_substitution_detected_at_input(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1)
        m_hist = historical_material(results=(r1,), bindings=(b1,))
        tampered_pol = policy(required_ids=(), optional_ids=("P1",), policy_id=POLICY.policy_id, policy_version=POLICY.policy_version)
        tampered = retamper(m_hist, policy=tampered_pol)
        result = nd.verify_decision_replay(tampered)
        self.assertEqual(result.status, "INPUT_FINGERPRINT_MISMATCH")

    def test_17_blocking_classification_substitution_detected_at_input(self) -> None:
        v1 = nd.DecisionPredicateResult(predicate_id="V1", role="VIOLATION", truth_value="FALSE", required=False, blocking=True)
        pol = policy(blocking_ids=("V1",))
        b1 = m8d_binding(v1, pol=pol, evidence_refs=(evidence_ref(ref_id="ev-v1"),))
        m_hist = historical_material(pol=pol, results=(v1,), bindings=(b1,))
        tampered_pol = policy(blocking_ids=(), optional_ids=("V1",), policy_id=pol.policy_id, policy_version=pol.policy_version)
        tampered = retamper(m_hist, policy=tampered_pol)
        result = nd.verify_decision_replay(tampered)
        self.assertEqual(result.status, "INPUT_FINGERPRINT_MISMATCH")

    def test_18_verifier_substitution_detected_despite_unchanged_binding_fingerprint(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1, verifier_id="verifier-A")
        m_hist = historical_material(results=(r1,), bindings=(b1,))
        b1_new_verifier = m8d_binding(r1, verifier_id="verifier-B")
        self.assertEqual(b1.binding_fingerprint, b1_new_verifier.binding_fingerprint)  # M8-C frozen identity unchanged
        tampered = retamper(m_hist, predicate_evidence_bindings=(b1_new_verifier,))
        result = nd.verify_decision_replay(tampered)
        self.assertEqual(result.status, "INPUT_FINGERPRINT_MISMATCH")

    def test_19_binding_verifier_swap_detected(self) -> None:
        pol = policy(required_ids=("P1", "P2"))
        r1 = requirement("P1", "TRUE")
        r2 = requirement("P2", "TRUE")
        b1 = m8d_binding(r1, pol=pol, verifier_id="V1")
        b2 = m8d_binding(r2, pol=pol, verifier_id="V2")
        m_hist = historical_material(pol=pol, results=(r1, r2), bindings=(b1, b2))
        b1_swapped = m8d_binding(r1, pol=pol, verifier_id="V2")
        b2_swapped = m8d_binding(r2, pol=pol, verifier_id="V1")
        tampered = retamper(m_hist, predicate_evidence_bindings=(b1_swapped, b2_swapped))
        result = nd.verify_decision_replay(tampered)
        self.assertEqual(result.status, "INPUT_FINGERPRINT_MISMATCH")

    def test_20_executor_substitution_detected(self) -> None:
        m_hist = historical_material(executor_ids=frozenset())
        tampered = retamper(m_hist, executor_ids=frozenset({"someone-else"}))
        result = nd.verify_decision_replay(tampered)
        self.assertEqual(result.status, "INPUT_FINGERPRINT_MISMATCH")

    def test_21_predicate_truth_substitution_detected(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1)
        m_hist = historical_material(results=(r1,), bindings=(b1,))
        r1_false = requirement("P1", "FALSE")
        b1_false = m8d_binding(r1_false)
        self.assertNotEqual(r1.result_fingerprint, r1_false.result_fingerprint)
        tampered = retamper(m_hist, predicate_results=(r1_false,), predicate_evidence_bindings=(b1_false,))
        result = nd.verify_decision_replay(tampered)
        self.assertEqual(result.status, "INPUT_FINGERPRINT_MISMATCH")


# --- F. SNAPSHOT SUBSTITUTION (Section 30 - both paths) ---------------------------------

class SnapshotSubstitutionTests(unittest.TestCase):
    def test_22_snapshot_substitution_with_updated_bindings_detected_at_input(self) -> None:
        m_hist = historical_material()
        other_snap = m8c_snapshot(subject=m8c_subject(revision_ref=revision("other-revision")))
        r1 = requirement("P1", "TRUE")
        b1_updated = m8d_binding(r1, snap=other_snap)
        tampered = retamper(m_hist, snapshot=other_snap, predicate_results=(r1,), predicate_evidence_bindings=(b1_updated,))
        result = nd.verify_decision_replay(tampered)
        self.assertEqual(result.status, "INPUT_FINGERPRINT_MISMATCH")

    def test_23_snapshot_substitution_without_updated_bindings_rejected_at_construction(self) -> None:
        # E4-B's own frozen structural gate (snapshot_fingerprint cross-check)
        # catches this BEFORE any DecisionReplayMaterial - and therefore
        # verify_decision_replay - can even be reached.
        m_hist = historical_material()
        other_snap = m8c_snapshot(subject=m8c_subject(revision_ref=revision("other-revision")))
        with self.assertRaises(nd.DecisionValidationError):
            retamper(m_hist, snapshot=other_snap)  # bindings still point at the OLD snapshot_fingerprint


# --- G. ENGINE VERSION INDEPENDENCE (Section 34) -----------------------------------------

class EngineVersionIndependenceTests(unittest.TestCase):
    def test_24_verifier_never_reads_snapshot_engine_version_in_source(self) -> None:
        source = code_only(nd.verify_decision_replay)
        self.assertNotIn("snapshot.engine_version", source)
        self.assertNotIn(".snapshot.engine_version", source)

    def test_25_engine_version_gate_compares_material_engine_version_only(self) -> None:
        called = called_function_names(nd.verify_decision_replay)
        # No new equality invariant introduced between the two version fields
        # - this is a structural, not a behavioral, proof (both fields are
        # currently forced to "2" by the shared version registry, so a
        # differing-value test cannot exist under the current baseline).
        self.assertNotIn("_require_supported_engine_version", called)  # engine gate is a direct == comparison, not a second validator


# --- H. CORRELATION-FIELD / PRESENTATION-ORDER INVARIANCE (Sections 35-36) --------------

class CorrelationAndOrderInvarianceTests(unittest.TestCase):
    def test_26_historical_correlation_ids_never_stored_or_required_for_match(self) -> None:
        # The historical evaluation_id/decision_id/created_at used to PRODUCE
        # the material are deliberately unrelated to the verifier's own
        # internal replay-local sentinels - proving the match does not depend
        # on recovering historical correlation identity.
        m = historical_material(evaluation_id="totally-unrelated-historical-id", created_at="1999-12-31T23:59:59Z")
        result = nd.verify_decision_replay(m)
        self.assertEqual(result.status, "REPLAY_MATCH")

    def test_27_presentation_order_of_results_and_bindings_does_not_affect_match(self) -> None:
        pol = policy(required_ids=("P1", "P2"))
        r1 = requirement("P1", "TRUE")
        r2 = requirement("P2", "TRUE")
        b1 = m8d_binding(r1, pol=pol)
        b2 = m8d_binding(r2, pol=pol)
        m_forward = historical_material(pol=pol, results=(r1, r2), bindings=(b1, b2))
        m_reversed = retamper(
            historical_material(pol=pol, results=(r2, r1), bindings=(b2, b1)),
        )
        result_forward = nd.verify_decision_replay(m_forward)
        result_reversed = nd.verify_decision_replay(m_reversed)
        self.assertEqual(result_forward.status, "REPLAY_MATCH")
        self.assertEqual(result_reversed.status, "REPLAY_MATCH")

    def test_28_executor_ids_presentation_order_does_not_affect_match(self) -> None:
        m_a = historical_material(executor_ids=frozenset({"executor-1", "executor-2"}))
        m_b = historical_material(executor_ids=frozenset({"executor-2", "executor-1"}))
        self.assertEqual(nd.verify_decision_replay(m_a).status, "REPLAY_MATCH")
        self.assertEqual(nd.verify_decision_replay(m_b).status, "REPLAY_MATCH")


# --- I. PHASE PURITY: NO JOURNAL / CHECKPOINT / PERSISTENCE / RETRIEVAL / APPLICABILITY -

class PhasePurityTests(unittest.TestCase):
    def test_29_no_journal_module_import(self) -> None:
        tree = ast.parse(inspect.getsource(sys.modules["nogap_decision"]))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertNotIn("nogap_decision_journal", imported)

    def test_30_no_checkpoint_or_journal_function_called(self) -> None:
        called = called_function_names(nd.verify_decision_replay)
        self.assertNotIn("verify_journal_checkpoint", called)
        self.assertNotIn("verify_decision_journal", called)
        self.assertNotIn("append_decision_entry", called)
        self.assertNotIn("create_journal_checkpoint", called)

    def test_31_no_journal_or_checkpoint_tokens_in_source(self) -> None:
        source = code_only(nd.verify_decision_replay, nd.DecisionReplayVerificationResult)
        for banned in ("journal", "checkpoint", "Journal", "Checkpoint"):
            self.assertNotIn(banned, source)

    def test_32_no_persistence_or_serialization_tokens(self) -> None:
        source = code_only(nd.DecisionReplayVerificationResult, nd.verify_decision_replay)
        for banned in ("to_json", "from_json", "pickle", "msgpack", "protobuf", "CBOR", "json.dumps", "json.loads", "sqlite3", "content_digest"):
            self.assertNotIn(banned, source)

    def test_33_no_io_or_evidence_refetch_tokens(self) -> None:
        source = code_only(nd.DecisionReplayVerificationResult, nd.verify_decision_replay)
        for banned in ("open(", "Path(", "requests.", "urllib", "subprocess", "os.environ"):
            self.assertNotIn(banned, source)

    def test_34_no_retrieval_or_memory_tokens(self) -> None:
        source = code_only(nd.DecisionReplayVerificationResult, nd.verify_decision_replay)
        for banned in ("vector", "embedding", "retrieve", "MEMORY.md", "rag", "RAG"):
            self.assertNotIn(banned, source)
        self.assertFalse(hasattr(nd, "search_decision_memory"))
        self.assertFalse(hasattr(nd, "retrieve_relevant_decisions"))

    def test_35_no_current_applicability_tokens(self) -> None:
        source = code_only(nd.DecisionReplayVerificationResult, nd.verify_decision_replay)
        for banned in ("git.", "glob(", "iterdir", "os.listdir", "current_repository"):
            self.assertNotIn(banned, source)

    def test_36_no_nondeterminism_tokens(self) -> None:
        source = code_only(nd.DecisionReplayVerificationResult, nd.verify_decision_replay)
        for banned in ("random.", "uuid.", "time.time(", "datetime.now(", "hash("):
            self.assertNotIn(banned, source)

    def test_37_no_replay_result_fingerprint_property(self) -> None:
        self.assertFalse(hasattr(nd.DecisionReplayVerificationResult, "replay_result_fingerprint"))
        self.assertFalse(hasattr(nd.DecisionReplayVerificationResult, "semantic_payload"))

    def test_38_verifier_never_calls_derive_contract_verdict_or_is_binding_admissible_directly(self) -> None:
        called = called_function_names(nd.verify_decision_replay)
        self.assertNotIn("derive_contract_verdict", called)
        self.assertNotIn("is_binding_admissible", called)

    def test_39_verifier_reuses_existing_authoritative_functions_only(self) -> None:
        called = called_function_names(nd.verify_decision_replay)
        self.assertIn("validate_decision_replay_material", called)
        self.assertIn("compute_input_fingerprint", called)
        self.assertIn("evaluate_decision", called)
        self.assertIn("build_decision_record", called)


# --- J. REPLAY FAILURE != DECISIONTRUTH (Section 52) --------------------------------------

class ReplayVocabularyDisjointnessTests(unittest.TestCase):
    def test_40_replay_statuses_disjoint_from_decision_truth_values(self) -> None:
        self.assertTrue(nd.REPLAY_VERIFICATION_STATUSES.isdisjoint(nd.DECISION_TRUTH_VALUES))

    def test_41_replay_statuses_disjoint_from_decision_verdicts(self) -> None:
        self.assertTrue(nd.REPLAY_VERIFICATION_STATUSES.isdisjoint(nd.DECISION_VERDICTS))

    def test_42_mismatch_statuses_never_equal_unknown_or_abstain_or_reject(self) -> None:
        for status in ("MATERIAL_INVALID", "ENGINE_VERSION_MISMATCH", "INPUT_FINGERPRINT_MISMATCH", "EVALUATION_FINGERPRINT_MISMATCH", "DECISION_FINGERPRINT_MISMATCH"):
            self.assertNotIn(status, nd.DECISION_TRUTH_VALUES)
            self.assertNotIn(status, nd.DECISION_VERDICTS)


# --- K. EXCEPTION BOUNDARY (Section 21-23) -------------------------------------------------

class ExceptionBoundaryTests(unittest.TestCase):
    def test_43_unexpected_type_error_propagates_not_swallowed(self) -> None:
        with self.assertRaises((TypeError, AttributeError, nd.DecisionValidationError)):
            nd.verify_decision_replay(None)  # type: ignore[arg-type]

    def test_44_required_blocking_deferred_check_surfaces_as_material_invalid(self) -> None:
        # M8-E4-B deliberately deferred required/blocking-vs-policy
        # consistency (see DecisionReplayMaterial.__post_init__) rather than
        # duplicate derive_contract_verdict()'s own validation prelude.
        # Historically P2 is properly classified optional (so the live
        # kernel accepts it and produces real commitments); the tampered
        # replay policy (same policy_id/version) drops P2's classification
        # entirely. optional_predicate_ids is NOT part of
        # DecisionBehavioralContext's commitment (only required_predicate_ids/
        # blocking_predicate_ids/binding_authority/executor_ids are), so
        # input_fingerprint is UNCHANGED by this tamper - the divergence can
        # only surface where E4-B deferred it to: evaluate_decision()'s own
        # derive_contract_verdict() classification-completeness check.
        pol = policy(required_ids=("P1",), optional_ids=("P2",))
        r1 = requirement("P1", "TRUE")
        r2 = requirement("P2", "TRUE", required=False)
        b1 = m8d_binding(r1, pol=pol)
        b2 = m8d_binding(r2, pol=pol)
        m = historical_material(pol=pol, results=(r1, r2), bindings=(b1, b2))
        tampered_pol = policy(required_ids=("P1",), policy_id=pol.policy_id, policy_version=pol.policy_version)  # P2 now unclassified
        tampered = retamper(m, policy=tampered_pol)
        result = nd.verify_decision_replay(tampered)
        self.assertEqual(result.status, "MATERIAL_INVALID")
        self.assertFalse(result.verified)


# --- L. K2-STYLE COMMITTED-KNOWLEDGE-LOSS REGRESSION (Section 51, provider-neutral) -------

class CommittedKnowledgeLossRegressionTests(unittest.TestCase):
    """Demonstrates the architectural property this whole milestone exists
    for: a decision instance historically ACCEPTed under one behavioral
    context cannot have that context silently rewritten (by a process with
    zero memory of the original conversation) while still claiming the same
    historical decision commitments. Deliberately provider-neutral - no
    project-specific production behavior is hard-coded here."""

    def test_45_historically_accepted_decision_replays_to_match_with_original_context(self) -> None:
        pol = policy(required_ids=("REVIEWED",))
        r1 = requirement("REVIEWED", "TRUE")
        b1 = m8d_binding(r1, pol=pol, verifier_id="independent-reviewer")
        m = historical_material(pol=pol, results=(r1,), bindings=(b1,), executor_ids=frozenset({"proposing-agent"}))
        result = nd.verify_decision_replay(m)
        self.assertEqual(result.status, "REPLAY_MATCH")
        self.assertTrue(result.verified)

    def test_46_forgetting_original_verifier_and_substituting_a_fresh_one_cannot_silently_reproduce_the_same_commitment(self) -> None:
        pol = policy(required_ids=("REVIEWED",))
        r1 = requirement("REVIEWED", "TRUE")
        b1 = m8d_binding(r1, pol=pol, verifier_id="independent-reviewer")
        m_hist = historical_material(pol=pol, results=(r1,), bindings=(b1,), executor_ids=frozenset({"proposing-agent"}))
        # A later, zero-memory process re-derives "the same" claim but with a
        # DIFFERENT (equally plausible-looking) verifier identity - it cannot
        # know this diverges from history without the original material,
        # exactly the failure mode this milestone closes.
        b1_rederived = m8d_binding(r1, pol=pol, verifier_id="a-different-reviewer")
        tampered = retamper(m_hist, predicate_evidence_bindings=(b1_rederived,))
        result = nd.verify_decision_replay(tampered)
        self.assertEqual(result.status, "INPUT_FINGERPRINT_MISMATCH")
        self.assertFalse(result.verified)


# --- M. PROVIDER NEUTRALITY (Section 55) ---------------------------------------------------

class ProviderNeutralityTests(unittest.TestCase):
    def test_47_no_provider_names_in_new_surface(self) -> None:
        source = code_only(nd.DecisionReplayVerificationResult, nd.verify_decision_replay)
        for provider in ("Claude", "Codex", "OpenAI", "Anthropic", "Hermes", "Kimi", "Gemini", "DeepSeek", "Qwen"):
            self.assertNotIn(provider, source)


if __name__ == "__main__":
    unittest.main()
