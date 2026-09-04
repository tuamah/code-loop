#!/usr/bin/env python3
"""M8-E4-B: Decision Replay Material - regression suite.

Covers DecisionReplayMaterial (construction, immutability, structural/cross-
object validation), build_decision_replay_material() (pure construction
helper), and validate_decision_replay_material() (pure completeness/
admissibility validation). This module tests the IN-MEMORY CLOSURE CONTRACT
ONLY - there is no replay execution, no historical-commitment comparison, no
serialization, no persistence, and no manifest anywhere in this file or in
the production code it exercises. M8-E4-C (a future replay verifier that
would actually recompute and compare fingerprints against
expected_input_fingerprint/expected_evaluation_fingerprint/
expected_decision_fingerprint) is explicitly NOT implemented or tested here.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap_decision as nd  # noqa: E402


# --- shared builders (self-contained - no cross-test-file import, matching
# tests/test_decision_journal.py's own established convention) -----------------

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


def code_only(*objs) -> str:
    """Concatenated source of `objs` with every triple-quoted docstring
    stripped - so a phase-purity/token-ban check inspects only executable
    code, never prose that legitimately DESCRIBES a banned token while
    documenting that the code never calls/uses it (e.g. a docstring saying
    "does not call evaluate_decision()" would otherwise itself trip a naive
    substring scan for "evaluate_decision(")."""
    source = "".join(inspect.getsource(obj) for obj in objs)
    return re.sub(r'"""[\s\S]*?"""', "", source)


def called_function_names(*objs) -> set[str]:
    """AST-based (not substring-based) proof of which functions `objs`
    actually CALL - immune to false positives from a comment/docstring that
    merely NAMES a function while documenting that it is never called (e.g.
    "the same checks evaluate_decision() itself performs")."""
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


def replay_material(**overrides) -> nd.DecisionReplayMaterial:
    """A valid, complete DecisionReplayMaterial built from a REAL
    evaluate_decision()/build_decision_record() run - exactly how material
    would be captured at ORIGINAL evaluation time (never as replay
    verification; this is ordinary test-fixture setup, not the production
    replay path this milestone deliberately does not implement)."""
    r1 = requirement("P1", "TRUE")
    b1 = m8d_binding(r1)
    executor_ids = frozenset()
    evaluation = nd.evaluate_decision(SNAPSHOT, POLICY, [r1], [b1], executor_ids, evaluation_id="eval-1")
    record = nd.build_decision_record(evaluation, decision_id="dec-1", created_at="2026-09-02T00:00:00Z")
    fields = dict(
        snapshot=SNAPSHOT, policy=POLICY, predicate_results=(r1,), predicate_evidence_bindings=(b1,),
        executor_ids=executor_ids, engine_version=nd.M8_DECISION_ENGINE_VERSION,
        expected_input_fingerprint=evaluation.input_fingerprint,
        expected_evaluation_fingerprint=evaluation.evaluation_fingerprint,
        expected_decision_fingerprint=record.decision_fingerprint,
    )
    fields.update(overrides)
    return nd.DecisionReplayMaterial(**fields)


# --- A. VALID CONSTRUCTION -----------------------------------------------------------

class ValidConstructionTests(unittest.TestCase):
    def test_1_valid_minimal_material_constructs(self) -> None:
        m = replay_material()
        self.assertIs(m.snapshot, SNAPSHOT)
        self.assertIs(m.policy, POLICY)
        self.assertEqual(len(m.predicate_results), 1)
        self.assertEqual(len(m.predicate_evidence_bindings), 1)

    def test_2_exactly_nine_fields(self) -> None:
        names = {f.name for f in dataclasses.fields(nd.DecisionReplayMaterial)}
        self.assertEqual(names, {
            "snapshot", "policy", "predicate_results", "predicate_evidence_bindings",
            "executor_ids", "engine_version", "expected_input_fingerprint",
            "expected_evaluation_fingerprint", "expected_decision_fingerprint",
        })

    def test_3_empty_executor_ids_permitted(self) -> None:
        m = replay_material(executor_ids=frozenset())
        self.assertEqual(m.executor_ids, frozenset())

    def test_4_nonempty_executor_ids_permitted(self) -> None:
        m = replay_material(executor_ids=frozenset({"executor-1", "executor-2"}))
        self.assertEqual(m.executor_ids, frozenset({"executor-1", "executor-2"}))

    def test_5_build_decision_replay_material_helper_constructs_equivalent_object(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1)
        evaluation = nd.evaluate_decision(SNAPSHOT, POLICY, [r1], [b1], frozenset(), evaluation_id="eval-1")
        record = nd.build_decision_record(evaluation, decision_id="dec-1", created_at="2026-09-02T00:00:00Z")
        m = nd.build_decision_replay_material(
            SNAPSHOT, POLICY, [r1], [b1], frozenset(),
            engine_version=nd.M8_DECISION_ENGINE_VERSION,
            expected_input_fingerprint=evaluation.input_fingerprint,
            expected_evaluation_fingerprint=evaluation.evaluation_fingerprint,
            expected_decision_fingerprint=record.decision_fingerprint,
        )
        self.assertIsInstance(m, nd.DecisionReplayMaterial)
        self.assertEqual(m.expected_decision_fingerprint, record.decision_fingerprint)

    def test_6_build_helper_accepts_list_inputs_and_coerces_to_immutable(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1)
        evaluation = nd.evaluate_decision(SNAPSHOT, POLICY, [r1], [b1], frozenset(), evaluation_id="eval-1")
        record = nd.build_decision_record(evaluation, decision_id="dec-1", created_at="2026-09-02T00:00:00Z")
        results_list = [r1]
        bindings_list = [b1]
        executor_list = ["executor-1"]
        m = nd.build_decision_replay_material(
            SNAPSHOT, POLICY, results_list, bindings_list, executor_list,
            engine_version=nd.M8_DECISION_ENGINE_VERSION,
            expected_input_fingerprint=evaluation.input_fingerprint,
            expected_evaluation_fingerprint=evaluation.evaluation_fingerprint,
            expected_decision_fingerprint=record.decision_fingerprint,
        )
        self.assertIsInstance(m.predicate_results, tuple)
        self.assertIsInstance(m.predicate_evidence_bindings, tuple)
        self.assertIsInstance(m.executor_ids, frozenset)


# --- B. IMMUTABILITY -------------------------------------------------------------------

class ImmutabilityTests(unittest.TestCase):
    def test_7_frozen_instance_rejects_field_assignment(self) -> None:
        m = replay_material()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            m.engine_version = "3"  # type: ignore[misc]

    def test_8_caller_list_mutation_after_construction_does_not_alter_material(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1)
        results_list = [r1]
        bindings_list = [b1]
        m = replay_material(predicate_results=results_list, predicate_evidence_bindings=bindings_list)
        results_list.append(requirement("P2", "TRUE"))
        bindings_list.clear()
        self.assertEqual(len(m.predicate_results), 1)
        self.assertEqual(len(m.predicate_evidence_bindings), 1)

    def test_9_caller_set_mutation_after_construction_does_not_alter_executor_ids(self) -> None:
        executor_set = {"executor-1"}
        m = replay_material(executor_ids=executor_set)
        executor_set.add("executor-2")
        executor_set.clear()
        self.assertEqual(m.executor_ids, frozenset({"executor-1"}))

    def test_10_predicate_results_is_a_tuple(self) -> None:
        self.assertIsInstance(replay_material().predicate_results, tuple)

    def test_11_predicate_evidence_bindings_is_a_tuple(self) -> None:
        self.assertIsInstance(replay_material().predicate_evidence_bindings, tuple)

    def test_12_executor_ids_is_a_frozenset(self) -> None:
        self.assertIsInstance(replay_material().executor_ids, frozenset)


# --- C. STRUCTURAL CLOSURE (Section 38) ---------------------------------------------

class StructuralClosureTests(unittest.TestCase):
    """Proves every future-replay-relevant intermediate value is obtainable
    solely from DecisionReplayMaterial's own fields - no model memory, policy
    registry, journal lookup, execution_run_id lookup, current repository
    state, or caller guesswork. Deliberately never calls evaluate_decision()
    as the proof - only pure fingerprint properties/derivations already
    reachable from the material's own fields."""

    def test_13_snapshot_fingerprint_derivable_from_material_alone(self) -> None:
        m = replay_material()
        self.assertTrue(m.snapshot.snapshot_fingerprint)

    def test_14_result_fingerprints_derivable_from_material_alone(self) -> None:
        m = replay_material()
        fps = [r.result_fingerprint for r in m.predicate_results]
        self.assertTrue(all(fps))

    def test_15_binding_fingerprints_derivable_from_material_alone(self) -> None:
        m = replay_material()
        fps = [b.binding_fingerprint for b in m.predicate_evidence_bindings]
        self.assertTrue(all(fps))

    def test_16_behavioral_context_derivable_from_material_alone(self) -> None:
        m = replay_material()
        ctx = nd.build_decision_behavioral_context(m.policy, m.predicate_evidence_bindings, m.executor_ids)
        self.assertTrue(ctx.behavioral_context_fingerprint)

    def test_17_behavioral_context_derivation_is_deterministic(self) -> None:
        m = replay_material()
        ctx_a = nd.build_decision_behavioral_context(m.policy, m.predicate_evidence_bindings, m.executor_ids)
        ctx_b = nd.build_decision_behavioral_context(m.policy, m.predicate_evidence_bindings, m.executor_ids)
        self.assertEqual(ctx_a.behavioral_context_fingerprint, ctx_b.behavioral_context_fingerprint)

    def test_18_expected_commitments_present_for_comparison(self) -> None:
        m = replay_material()
        self.assertTrue(m.expected_input_fingerprint)
        self.assertTrue(m.expected_evaluation_fingerprint)
        self.assertTrue(m.expected_decision_fingerprint)

    def test_19_no_journal_or_registry_access_needed(self) -> None:
        # Structural proof, not a runtime one: DecisionReplayMaterial has no
        # journal/registry-shaped field at all.
        names = {f.name for f in dataclasses.fields(nd.DecisionReplayMaterial)}
        self.assertFalse(names & {"journal_id", "checkpoint_fingerprint", "execution_run_id"})


# --- D. ENGINE VERSION INDEPENDENCE (Section 40) --------------------------------------

class EngineVersionIndependenceTests(unittest.TestCase):
    def test_20_engine_version_is_its_own_stored_field(self) -> None:
        names = {f.name for f in dataclasses.fields(nd.DecisionReplayMaterial)}
        self.assertIn("engine_version", names)

    def test_21_engine_version_never_read_from_snapshot_engine_version_in_source(self) -> None:
        source = code_only(nd.DecisionReplayMaterial, nd.build_decision_replay_material)
        self.assertNotIn("snapshot.engine_version", source)
        self.assertNotIn(".snapshot.engine_version", source)

    def test_22_material_engine_version_independent_of_snapshot_value(self) -> None:
        # Both currently equal "2" (only supported value) - independence is
        # proven by DATA FLOW (test_21), not by differing string values,
        # since the current version registry permits only one legal value.
        m = replay_material()
        self.assertEqual(m.engine_version, nd.M8_DECISION_ENGINE_VERSION)
        self.assertEqual(m.snapshot.engine_version, nd.M8_DECISION_ENGINE_VERSION)
        # No cross-validation exists between the two - constructing material
        # never reads m.snapshot.engine_version at all (test_21 proves this
        # structurally); this test only documents both fields' current values.


# --- E. LEGACY / UNSUPPORTED VERSION (Section 41) --------------------------------------

class LegacyVersionTests(unittest.TestCase):
    def test_23_unsupported_engine_version_fails_closed(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(engine_version="1")

    def test_24_empty_engine_version_fails_closed(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(engine_version="")

    def test_25_no_migration_or_backfill_path_exists(self) -> None:
        self.assertFalse(hasattr(nd, "migrate_decision_replay_material"))
        self.assertFalse(hasattr(nd, "upgrade_decision_replay_material"))
        self.assertFalse(hasattr(nd, "backfill_decision_replay_material"))


# --- F. MALFORMED EXPECTED COMMITMENTS (Section 44) -------------------------------------

class ExpectedCommitmentFormatTests(unittest.TestCase):
    def test_26_empty_expected_input_fingerprint_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(expected_input_fingerprint="")

    def test_27_wrong_length_expected_input_fingerprint_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(expected_input_fingerprint="abc123")

    def test_28_non_hex_expected_input_fingerprint_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(expected_input_fingerprint="g" * 64)

    def test_29_empty_expected_evaluation_fingerprint_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(expected_evaluation_fingerprint="")

    def test_30_malformed_expected_evaluation_fingerprint_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(expected_evaluation_fingerprint="not-a-digest")

    def test_31_empty_expected_decision_fingerprint_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(expected_decision_fingerprint="")

    def test_32_malformed_expected_decision_fingerprint_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(expected_decision_fingerprint="0" * 63)

    def test_33_uppercase_hex_expected_fingerprint_rejected(self) -> None:
        # Digest format is lowercase-hex only, same rule as every other
        # fingerprint field in this module - no second, looser digest format.
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(expected_input_fingerprint=digest("x").upper())


# --- G. DUPLICATE REJECTION (Section 45) ------------------------------------------------

class DuplicateRejectionTests(unittest.TestCase):
    def test_34_duplicate_predicate_id_rejected(self) -> None:
        r1 = requirement("P1", "TRUE")
        r1_dup = requirement("P1", "FALSE")
        b1 = m8d_binding(r1)
        b1_dup = m8d_binding(r1_dup)
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(predicate_results=(r1, r1_dup), predicate_evidence_bindings=(b1, b1_dup))

    def test_35_duplicate_binding_fingerprint_rejected(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1)
        b1_copy = m8d_binding(r1)  # identical semantic_payload -> identical binding_fingerprint
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(predicate_results=(r1,), predicate_evidence_bindings=(b1, b1_copy))


# --- H. ORPHAN / MISMATCH REJECTION (Sections 46-49) -------------------------------------

class CrossReferenceRejectionTests(unittest.TestCase):
    def test_36_orphan_binding_rejected(self) -> None:
        r1 = requirement("P1", "TRUE")
        orphan_result = requirement("P_GHOST", "TRUE")
        orphan_binding = m8d_binding(orphan_result)
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(predicate_results=(r1,), predicate_evidence_bindings=(orphan_binding,))

    def test_37_snapshot_fingerprint_mismatch_rejected(self) -> None:
        r1 = requirement("P1", "TRUE")
        other_snap = m8c_snapshot(subject=m8c_subject(revision_ref=revision("other-rev")))
        b1 = m8d_binding(r1, snap=other_snap)
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(predicate_results=(r1,), predicate_evidence_bindings=(b1,))

    def test_38_policy_id_mismatch_rejected(self) -> None:
        r1 = requirement("P1", "TRUE")
        other_pol = policy(required_ids=("P1",), policy_id="other-policy")
        b1 = m8d_binding(r1, pol=other_pol)
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(predicate_results=(r1,), predicate_evidence_bindings=(b1,))

    def test_39_policy_version_mismatch_rejected(self) -> None:
        r1 = requirement("P1", "TRUE")
        other_pol = policy(required_ids=("P1",), policy_version="99")
        b1 = m8d_binding(r1, pol=other_pol)
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(predicate_results=(r1,), predicate_evidence_bindings=(b1,))

    def test_40_decision_type_mismatch_rejected(self) -> None:
        other_pol = policy(required_ids=("P1",), decision_type="REPAIR_ACCEPTANCE")
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1, pol=other_pol)
        with self.assertRaises(nd.DecisionValidationError):
            replay_material(policy=other_pol, predicate_results=(r1,), predicate_evidence_bindings=(b1,))


# --- I. REQUIRED/BLOCKING CLASSIFICATION (Section 42/M8-E4-B1 correction) ----------------

class RequiredBlockingClassificationTests(unittest.TestCase):
    def test_41_required_change_alone_does_not_change_result_fingerprint(self) -> None:
        a = requirement("P1", "TRUE", required=True)
        b = requirement("P1", "TRUE", required=False)
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)

    def test_42_blocking_change_alone_does_not_change_result_fingerprint(self) -> None:
        a = requirement("P1", "TRUE", blocking=False)
        b = requirement("P1", "TRUE", blocking=True)
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)

    def test_43_required_blocking_vs_policy_consistency_is_deliberately_deferred(self) -> None:
        """M8-E4-B1 adjudication: required/blocking-vs-policy classification
        consistency is derive_contract_verdict()'s own validation-prelude
        concern, not DecisionReplayMaterial's - reusing it safely here would
        require either invoking derive_contract_verdict() (verdict
        computation, outside E4-B's phase boundary) or duplicating its
        private validation lines (drift risk). Material construction here
        deliberately does NOT reject a required/blocking value inconsistent
        with the policy's own classification; a future E4-C replay verifier
        catches this for real, at real replay time, via the one existing
        algebra - never a second, competing implementation of the same
        check."""
        inconsistent_result = requirement("P1", "TRUE", required=False)  # policy classifies P1 as required
        b1 = m8d_binding(inconsistent_result)
        m = replay_material(predicate_results=(inconsistent_result,), predicate_evidence_bindings=(b1,))
        self.assertFalse(inconsistent_result.required)
        self.assertIn("P1", m.policy.required_predicate_ids)


# --- J. NO REDUNDANT MATERIAL (Section 7 / Section 33 / Section 30 / Section 28) ---------

class NoRedundantMaterialTests(unittest.TestCase):
    def test_44_no_behavioral_context_field(self) -> None:
        names = {f.name for f in dataclasses.fields(nd.DecisionReplayMaterial)}
        self.assertNotIn("behavioral_context", names)
        self.assertNotIn("behavioral_context_fingerprint", names)

    def test_45_no_lower_layer_expected_fingerprint_fields(self) -> None:
        names = {f.name for f in dataclasses.fields(nd.DecisionReplayMaterial)}
        self.assertTrue(names.isdisjoint({
            "expected_snapshot_fingerprint", "expected_result_fingerprints",
            "expected_binding_fingerprints", "expected_behavioral_context_fingerprint",
        }))

    def test_46_no_manifest_type_introduced(self) -> None:
        self.assertFalse(hasattr(nd, "ReplayManifest"))
        self.assertFalse(hasattr(nd, "MaterialManifest"))
        self.assertFalse(hasattr(nd, "DecisionReplayManifest"))

    def test_47_no_content_digest_field(self) -> None:
        names = {f.name for f in dataclasses.fields(nd.DecisionReplayMaterial)}
        self.assertTrue(names.isdisjoint({"content_digest", "bundle_digest", "material_digest", "blob_hash", "cas_key"}))

    def test_48_no_new_semantic_fingerprint_property(self) -> None:
        self.assertFalse(hasattr(nd.DecisionReplayMaterial, "replay_material_fingerprint"))

    def test_49_no_semantic_payload_method(self) -> None:
        # DecisionReplayMaterial deliberately owns no fingerprint of its own -
        # unlike every other M8 contract, it has no semantic_payload() either.
        self.assertFalse(hasattr(nd.DecisionReplayMaterial, "semantic_payload"))

    def test_50_no_correlation_only_fields_added(self) -> None:
        names = {f.name for f in dataclasses.fields(nd.DecisionReplayMaterial)}
        self.assertTrue(names.isdisjoint({
            "evaluation_id", "decision_id", "request_id", "created_at", "evaluated_at",
            "recorded_at", "execution_run_id", "authority_class", "provider", "model", "metadata",
        }))


# --- K. PHASE PURITY (Sections 23/27/29/34/51) --------------------------------------------

class PhasePurityTests(unittest.TestCase):
    def test_51_construction_never_calls_evaluate_decision_or_build_decision_record(self) -> None:
        called = called_function_names(nd.DecisionReplayMaterial, nd.build_decision_replay_material)
        self.assertNotIn("evaluate_decision", called)
        self.assertNotIn("build_decision_record", called)

    def test_52_completeness_validation_never_calls_evaluate_decision_or_build_decision_record(self) -> None:
        called = called_function_names(nd.validate_decision_replay_material)
        self.assertNotIn("evaluate_decision", called)
        self.assertNotIn("build_decision_record", called)

    def test_53_no_serialization_tokens_in_new_surface(self) -> None:
        source = code_only(nd.DecisionReplayMaterial, nd.build_decision_replay_material, nd.validate_decision_replay_material)
        for banned in ("to_json", "from_json", "pickle", "msgpack", "protobuf", "CBOR", "json.dumps", "json.loads"):
            self.assertNotIn(banned, source)

    def test_54_no_persistence_or_io_tokens_in_new_surface(self) -> None:
        source = code_only(nd.DecisionReplayMaterial, nd.build_decision_replay_material, nd.validate_decision_replay_material)
        for banned in ("open(", "Path(", "sqlite3", "requests.", "urllib", "subprocess", "os.environ"):
            self.assertNotIn(banned, source)

    def test_55_no_nondeterminism_tokens_in_new_surface(self) -> None:
        source = code_only(nd.DecisionReplayMaterial, nd.build_decision_replay_material, nd.validate_decision_replay_material)
        for banned in ("random.", "uuid.", "time.time(", "datetime.now(", "hash("):
            self.assertNotIn(banned, source)

    def test_56_no_replayresult_or_replayengine_types_introduced(self) -> None:
        # verify_decision_replay() is deliberately NOT asserted absent here:
        # M8-E4-B's own phase boundary only forbids IT from implementing
        # replay execution - M8-E4-C is the later, separate, explicitly
        # authorized milestone that legitimately adds the single pure
        # verifier function (never a ReplayEngine/ReplayResult/ReplayStatus
        # class - those remain correctly absent below).
        self.assertFalse(hasattr(nd, "ReplayResult"))
        self.assertFalse(hasattr(nd, "ReplayStatus"))
        self.assertFalse(hasattr(nd, "ReplayEngine"))
        self.assertFalse(hasattr(nd, "replay_decision"))

    def test_57_no_false_authenticity_claims_in_docstrings(self) -> None:
        source = (
            (nd.DecisionReplayMaterial.__doc__ or "")
            + (nd.build_decision_replay_material.__doc__ or "")
            + (nd.validate_decision_replay_material.__doc__ or "")
        )
        for banned in ("proves authenticity", "trusted issuer", "correct evidence", "current validity", "guarantees truth"):
            self.assertNotIn(banned, source.lower())


# --- L. PROVIDER NEUTRALITY (Section 35) --------------------------------------------------

class ProviderNeutralityTests(unittest.TestCase):
    def test_58_no_provider_names_in_new_surface(self) -> None:
        source = code_only(nd.DecisionReplayMaterial, nd.build_decision_replay_material, nd.validate_decision_replay_material)
        for provider in ("Claude", "Codex", "OpenAI", "Anthropic", "Hermes", "Kimi", "Gemini", "DeepSeek", "Qwen"):
            self.assertNotIn(provider, source)


# --- M. COMPLETENESS VALIDATION (validate_decision_replay_material) -----------------------

class CompletenessValidationTests(unittest.TestCase):
    def test_59_valid_material_passes_completeness_validation(self) -> None:
        m = replay_material()
        self.assertIsNone(nd.validate_decision_replay_material(m))

    def test_60_self_verification_binding_fails_completeness_validation(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1, verifier_id="executor-1")
        m = replay_material(
            predicate_results=(r1,), predicate_evidence_bindings=(b1,),
            executor_ids=frozenset({"executor-1"}),
        )
        with self.assertRaises(nd.DecisionValidationError):
            nd.validate_decision_replay_material(m)

    def test_61_missing_evidence_for_true_claim_fails_completeness_validation(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1, evidence_refs=())
        m = replay_material(predicate_results=(r1,), predicate_evidence_bindings=(b1,))
        with self.assertRaises(nd.DecisionValidationError):
            nd.validate_decision_replay_material(m)

    def test_62_predicate_result_with_no_binding_fails_completeness_validation(self) -> None:
        r1 = requirement("P1", "TRUE")
        r2 = requirement("P2", "TRUE", required=False)
        b1 = m8d_binding(r1)
        pol = policy(required_ids=("P1",), optional_ids=("P2",))
        m = replay_material(policy=pol, predicate_results=(r1, r2), predicate_evidence_bindings=(b1,))
        with self.assertRaises(nd.DecisionValidationError):
            nd.validate_decision_replay_material(m)

    def test_63_completeness_validation_is_pure_and_repeatable(self) -> None:
        m = replay_material()
        nd.validate_decision_replay_material(m)
        nd.validate_decision_replay_material(m)  # no state mutation, safe to call twice

    def test_64_completeness_validation_rejects_non_material_input(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.validate_decision_replay_material("not-a-material")  # type: ignore[arg-type]


# --- N. EXISTING FINGERPRINT NON-REGRESSION (Section 63) ----------------------------------

class ExistingFingerprintNonRegressionTests(unittest.TestCase):
    def test_65_engine_version_constant_unchanged(self) -> None:
        self.assertEqual(nd.M8_DECISION_ENGINE_VERSION, "2")

    def test_66_schema_version_constant_unchanged(self) -> None:
        self.assertEqual(nd.M8_DECISION_SCHEMA_VERSION, "1")

    def test_67_snapshot_fingerprint_still_excludes_request_id(self) -> None:
        a = m8c_snapshot(request_id="req-a")
        b = m8c_snapshot(request_id="req-b")
        self.assertEqual(a.snapshot_fingerprint, b.snapshot_fingerprint)

    def test_68_evaluation_fingerprint_still_reachable_and_unchanged_shape(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1)
        evaluation = nd.evaluate_decision(SNAPSHOT, POLICY, [r1], [b1], frozenset(), evaluation_id="eval-1")
        self.assertEqual(
            set(evaluation.semantic_payload()),
            {"decision_type", "verdict", "reason_codes", "input_fingerprint", "engine_version", "schema_version"},
        )

    def test_69_decision_fingerprint_still_reachable_and_unchanged_shape(self) -> None:
        r1 = requirement("P1", "TRUE")
        b1 = m8d_binding(r1)
        evaluation = nd.evaluate_decision(SNAPSHOT, POLICY, [r1], [b1], frozenset(), evaluation_id="eval-1")
        record = nd.build_decision_record(evaluation, decision_id="dec-1", created_at="2026-09-02T00:00:00Z")
        self.assertEqual(
            set(record.semantic_payload()),
            {"decision_type", "verdict", "reason_codes", "evaluation_fingerprint", "engine_version", "schema_version"},
        )


if __name__ == "__main__":
    unittest.main()
