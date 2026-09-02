#!/usr/bin/env python3
"""M8-A: Decision Contracts & Safety Model - regression suite.

Covers the formal vocabulary, structural contract validation, the pure
verdict algebra (derive_contract_verdict), the 10 mandatory scenarios, the
22 required property-style tests, and adversarial contract attacks A-J from
the M8-A review brief. This module tests CONTRACTS ONLY - there is no
filesystem, runtime, methodology, or CLI dependency anywhere in this file
except sys.path setup and imports of vocabulary constants from other modules
used strictly for namespace-separation assertions (never executed as
production logic).
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap_decision as nd  # noqa: E402


# --- shared builders ---------------------------------------------------------------

def scope(**overrides) -> nd.DecisionScope:
    fields = dict(scope_type="TASK", scope_id="TASK-1", project_id="proj-1")
    fields.update(overrides)
    return nd.DecisionScope(**fields)


def requirement(predicate_id: str, truth: str, *, required: bool = True, **overrides) -> nd.DecisionPredicateResult:
    fields = dict(predicate_id=predicate_id, role="REQUIREMENT", truth_value=truth, required=required, blocking=False)
    fields.update(overrides)
    return nd.DecisionPredicateResult(**fields)


def violation(predicate_id: str, truth: str, *, blocking: bool = True, **overrides) -> nd.DecisionPredicateResult:
    fields = dict(predicate_id=predicate_id, role="VIOLATION", truth_value=truth, required=False, blocking=blocking)
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


def request(**overrides) -> nd.DecisionRequestContract:
    fields = dict(
        request_id="req-1", project_id="proj-1", decision_type="TASK_ACCEPTANCE", scope=scope(),
        requested_by="agent-1", requester_authority="EXECUTION", reason="evaluate task",
    )
    fields.update(overrides)
    return nd.DecisionRequestContract(**fields)


# --- M8-C shared builders (PredicateEvidenceBinding / admissibility) ---------------

def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def revision(seed: str) -> str:
    return digest(seed)[:40]  # 40-hex, matches DecisionSubject's SHA-1-shaped revision contract


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


M8C_RESULT = requirement("P1", "TRUE")
M8C_SNAPSHOT = m8c_snapshot()
M8C_POLICY = policy(required_ids=("P1",))
M8C_EVIDENCE = evidence_ref()


def m8c_binding(**overrides) -> nd.PredicateEvidenceBinding:
    fields = dict(
        predicate_result_fingerprint=M8C_RESULT.result_fingerprint,
        snapshot_fingerprint=M8C_SNAPSHOT.snapshot_fingerprint,
        policy_id=M8C_POLICY.policy_id, policy_version=M8C_POLICY.policy_version,
        evidence_refs=(M8C_EVIDENCE,), verifier_id="verifier-x",
    )
    fields.update(overrides)
    return nd.PredicateEvidenceBinding(**fields)


def m8c_admit(binding_obj: nd.PredicateEvidenceBinding, **overrides) -> nd.AdmissibilityResult:
    fields = dict(predicate_result=M8C_RESULT, current_snapshot=M8C_SNAPSHOT, current_policy=M8C_POLICY, executor_ids=frozenset())
    fields.update(overrides)
    return nd.is_binding_admissible(binding_obj, **fields)


# A canonical "complete proof" set matching M8-A Mandatory Scenario 1.
def complete_proof_predicates() -> tuple[nd.DecisionPredicateResult, ...]:
    return (
        requirement("EXPECTED_EFFECT", "TRUE"),
        requirement("DETERMINISTIC_VERIFICATION", "TRUE"),
        requirement("METHODOLOGY_READY", "TRUE"),
        violation("GATE_TAMPERING", "FALSE"),
        violation("BLOCKING_FAILURE", "FALSE"),
    )


COMPLETE_PROOF_POLICY = policy(
    required_ids=("EXPECTED_EFFECT", "DETERMINISTIC_VERIFICATION", "METHODOLOGY_READY"),
    blocking_ids=("GATE_TAMPERING", "BLOCKING_FAILURE"),
)


# --- DecisionEnumTests ----------------------------------------------------------

class DecisionEnumTests(unittest.TestCase):
    def test_decision_verdicts_exact_vocabulary(self) -> None:
        self.assertEqual(nd.DECISION_VERDICTS, frozenset({"ACCEPT", "REJECT", "ABSTAIN"}))

    def test_decision_types_minimal_vocabulary(self) -> None:
        self.assertEqual(nd.DECISION_TYPES, frozenset({"TASK_ACCEPTANCE", "REPAIR_ACCEPTANCE", "RELEASE_ACCEPTANCE"}))

    def test_decision_scope_types_minimal(self) -> None:
        self.assertEqual(nd.DECISION_SCOPE_TYPES, frozenset({"TASK", "REPAIR", "RELEASE"}))

    def test_predicate_roles(self) -> None:
        self.assertEqual(nd.PREDICATE_ROLES, frozenset({"REQUIREMENT", "VIOLATION"}))

    def test_no_pass_fail_approve_deny_success_supported_as_verdict(self) -> None:
        for banned in ("PASS", "FAIL", "APPROVE", "DENY", "SUCCESS", "SUPPORTED"):
            self.assertNotIn(banned, nd.DECISION_VERDICTS)


# --- DecisionTruthValueTests ------------------------------------------------------

class DecisionTruthValueTests(unittest.TestCase):
    def test_exact_four_values(self) -> None:
        self.assertEqual(nd.DECISION_TRUTH_VALUES, frozenset({"TRUE", "FALSE", "UNKNOWN", "CONFLICT"}))

    def test_no_bool_used_for_truth_value(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("P1", True)  # bool is not a member of DECISION_TRUTH_VALUES

    def test_unknown_truth_value_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("P1", "MAYBE")


# --- DecisionScopeTests -------------------------------------------------------------

class DecisionScopeTests(unittest.TestCase):
    def test_valid_scope_constructs(self) -> None:
        s = scope()
        self.assertEqual(s.scope_type, "TASK")

    def test_rejects_unknown_scope_type(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            scope(scope_type="RELEASE_CANDIDATE")

    def test_rejects_empty_project_id(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            scope(project_id="")

    def test_rejects_empty_scope_id(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            scope(scope_id="")

    def test_canonical_id_deterministic(self) -> None:
        s = scope()
        self.assertEqual(s.canonical_id(), "TASK:proj-1:TASK-1")
        self.assertEqual(s.canonical_id(), scope().canonical_id())

    def test_artifact_refs_duplicate_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            scope(artifact_refs=("a", "a"))

    def test_scope_is_immutable(self) -> None:
        s = scope()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            s.project_id = "other"

    def test_scope_not_representable_by_free_prose_alone(self) -> None:
        # scope has no field that accepts a single free-text blob in place of
        # the structured (scope_type, scope_id, project_id) triple.
        field_names = {f.name for f in dataclasses.fields(nd.DecisionScope)}
        self.assertEqual(field_names, {"scope_type", "scope_id", "project_id", "revision_ref", "candidate_ref", "artifact_refs"})


# --- DecisionAuthorityContractTests -------------------------------------------------

class DecisionAuthorityContractTests(unittest.TestCase):
    def test_authority_classes_vocabulary(self) -> None:
        self.assertEqual(
            nd.AUTHORITY_CLASSES,
            frozenset({"EXECUTION", "VERIFICATION", "ACCEPTANCE", "HUMAN", "SYSTEM_DETERMINISTIC", "ADVISORY"}),
        )

    def test_authority_class_context_only_no_verdict_side_effect(self) -> None:
        # Constructing a predicate result with EXECUTION authority_refs and
        # truth_value TRUE does not, by itself, alter its role/required/blocking
        # semantics - authority is metadata, never a verdict override.
        pr = requirement("P1", "TRUE", authority_refs=("exec-actor-1",))
        self.assertEqual(pr.truth_value, "TRUE")
        self.assertEqual(pr.authority_refs, ("exec-actor-1",))

    # --- final M8-A review fix: no "acceptance capable" authority classification --
    #
    # An earlier draft defined ACCEPTANCE_CAPABLE_AUTHORITY_CLASSES =
    # {"ACCEPTANCE", "HUMAN"} and authority_class_is_acceptance_capable(). Both
    # were removed: the names could later be misread as "these authority classes
    # may authorize writing DecisionVerdict.ACCEPT", which is exactly the
    # sole-writer boundary M8 exists to prevent any actor from crossing. These
    # regressions lock the removal in - reintroducing either name (or an
    # equivalent under a different name) regresses this fix.

    def test_no_acceptance_capable_constant_exists(self) -> None:
        self.assertFalse(hasattr(nd, "ACCEPTANCE_CAPABLE_AUTHORITY_CLASSES"))

    def test_no_acceptance_capable_helper_exists(self) -> None:
        self.assertFalse(hasattr(nd, "authority_class_is_acceptance_capable"))

    def test_no_authority_permission_helper_of_any_name(self) -> None:
        # Broader guard: no function anywhere in the module returns a bool
        # keyed on authority class that could serve as an accept/reject gate.
        import inspect
        for name, member in vars(nd).items():
            if not inspect.isfunction(member):
                continue
            self.assertNotIn("acceptance_capable", name.lower())
            self.assertNotIn("can_accept", name.lower())
            self.assertNotIn("authority_can", name.lower())

    def test_every_authority_class_alone_is_insufficient_for_accept(self) -> None:
        # Required invariant: for EVERY AuthorityClass, membership alone is
        # insufficient to construct, authorize, or derive technical ACCEPT.
        # derive_contract_verdict() takes no actor/authority argument at all, so
        # constructing a request under any authority class - including HUMAN and
        # ACCEPTANCE - has zero effect on the algebra's output for the same
        # predicates/policy.
        baseline = nd.derive_contract_verdict(complete_proof_predicates(), policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(baseline.verdict, "ACCEPT")
        for authority in sorted(nd.AUTHORITY_CLASSES):
            req = request(requester_authority=authority)  # must construct without raising
            self.assertEqual(req.requester_authority, authority)
            result = nd.derive_contract_verdict(complete_proof_predicates(), policy_contract=COMPLETE_PROOF_POLICY)
            self.assertEqual(result.verdict, baseline.verdict, f"authority class {authority} must not affect the verdict")

    def test_mandatory_unknown_plus_human_requester_still_abstains(self) -> None:
        request(requester_authority="HUMAN")
        predicates = [dataclasses.replace(pr, truth_value="UNKNOWN") if pr.predicate_id == "DETERMINISTIC_VERIFICATION" else pr for pr in complete_proof_predicates()]
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "ABSTAIN")

    def test_mandatory_unknown_plus_acceptance_requester_still_abstains(self) -> None:
        request(requester_authority="ACCEPTANCE")
        predicates = [dataclasses.replace(pr, truth_value="UNKNOWN") if pr.predicate_id == "DETERMINISTIC_VERIFICATION" else pr for pr in complete_proof_predicates()]
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "ABSTAIN")

    def test_blocking_violation_true_plus_human_requester_still_rejects(self) -> None:
        request(requester_authority="HUMAN")
        predicates = [dataclasses.replace(pr, truth_value="TRUE") if pr.predicate_id == "BLOCKING_FAILURE" else pr for pr in complete_proof_predicates()]
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "REJECT")

    def test_blocking_violation_true_plus_acceptance_requester_still_rejects(self) -> None:
        request(requester_authority="ACCEPTANCE")
        predicates = [dataclasses.replace(pr, truth_value="TRUE") if pr.predicate_id == "BLOCKING_FAILURE" else pr for pr in complete_proof_predicates()]
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "REJECT")

    def test_authority_cannot_convert_abstain_to_accept(self) -> None:
        predicates = [dataclasses.replace(pr, truth_value="UNKNOWN") if pr.predicate_id == "DETERMINISTIC_VERIFICATION" else pr for pr in complete_proof_predicates()]
        for authority in ("HUMAN", "ACCEPTANCE"):
            request(requester_authority=authority)
            result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
            self.assertEqual(result.verdict, "ABSTAIN")
            self.assertNotEqual(result.verdict, "ACCEPT")

    def test_authority_cannot_convert_reject_to_accept(self) -> None:
        predicates = [dataclasses.replace(pr, truth_value="TRUE") if pr.predicate_id == "GATE_TAMPERING" else pr for pr in complete_proof_predicates()]
        for authority in ("HUMAN", "ACCEPTANCE"):
            request(requester_authority=authority)
            result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
            self.assertEqual(result.verdict, "REJECT")
            self.assertNotEqual(result.verdict, "ACCEPT")

    def test_derive_contract_verdict_accepts_no_actor_authority_argument(self) -> None:
        # Structural proof, not just behavioral: the algebra's signature has no
        # parameter through which an actor/authority could even be threaded in.
        import inspect
        params = set(inspect.signature(nd.derive_contract_verdict).parameters)
        self.assertEqual(params, {"predicate_results", "policy_contract", "scope"})

    def test_human_authority_class_is_not_a_verdict(self) -> None:
        self.assertNotIn("HUMAN", nd.DECISION_VERDICTS)
        with self.assertRaises(nd.DecisionValidationError):
            make_record(verdict="HUMAN")

    def test_acceptance_authority_class_is_not_a_verdict(self) -> None:
        self.assertNotIn("ACCEPTANCE", nd.DECISION_VERDICTS)
        with self.assertRaises(nd.DecisionValidationError):
            make_record(verdict="ACCEPTANCE")


# --- DecisionReasonCodeTests --------------------------------------------------------

class DecisionReasonCodeTests(unittest.TestCase):
    def test_reason_code_vocabulary_matches_brief(self) -> None:
        expected = {
            "MISSING_REQUIRED_EVIDENCE", "STALE_REQUIRED_EVIDENCE", "EVIDENCE_CONFLICT", "SCOPE_MISMATCH",
            "INVALID_AUTHORITY", "MANDATORY_PREDICATE_FALSE", "MANDATORY_PREDICATE_UNKNOWN",
            "MANDATORY_PREDICATE_CONFLICT", "BLOCKING_FAILURE", "GATE_FAILURE", "GATE_TAMPERING",
            "VERIFICATION_INCOMPLETE", "VERIFICATION_STALE", "METHODOLOGY_NOT_READY",
            "DECISION_POLICY_INVALID", "INPUT_INVALID",
        }
        self.assertEqual(nd.DECISION_REASON_CODES, frozenset(expected))

    def test_unknown_reason_code_rejected_on_predicate_result(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("P1", "FALSE", reason_codes=("NOT_A_REAL_CODE",))

    def test_duplicate_reason_code_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("P1", "FALSE", reason_codes=("MANDATORY_PREDICATE_FALSE", "MANDATORY_PREDICATE_FALSE"))


# --- DecisionPredicateResultTests ---------------------------------------------------

class DecisionPredicateResultTests(unittest.TestCase):
    def test_valid_requirement_constructs(self) -> None:
        pr = requirement("P1", "TRUE")
        self.assertEqual(pr.role, "REQUIREMENT")

    def test_valid_violation_constructs(self) -> None:
        pr = violation("V1", "FALSE")
        self.assertEqual(pr.role, "VIOLATION")

    def test_empty_predicate_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("", "TRUE")

    def test_unknown_role_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.DecisionPredicateResult(predicate_id="P1", role="MAYBE", truth_value="TRUE", required=True, blocking=False)

    def test_required_must_be_explicit_bool(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.DecisionPredicateResult(predicate_id="P1", role="REQUIREMENT", truth_value="TRUE", required=1, blocking=False)

    def test_duplicate_source_refs_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("P1", "TRUE", source_refs=("evidence-1", "evidence-1"))

    def test_duplicate_authority_refs_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("P1", "TRUE", authority_refs=("actor-1", "actor-1"))

    def test_details_is_not_authoritative(self) -> None:
        # `details` free prose has no bearing on truth_value validity - a
        # contradiction between details text and truth_value is not even checked,
        # because details is documented as non-authoritative explanatory metadata.
        pr = requirement("P1", "FALSE", details="looks fine to me")
        self.assertEqual(pr.truth_value, "FALSE")

    def test_stale_evidence_cannot_prove_true_s4(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("P1", "TRUE", freshness_status="STALE")

    def test_stale_evidence_can_prove_false_or_unknown(self) -> None:
        requirement("P1", "FALSE", freshness_status="STALE")
        requirement("P1", "UNKNOWN", freshness_status="STALE")

    def test_predicate_result_is_immutable(self) -> None:
        pr = requirement("P1", "TRUE")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            pr.truth_value = "FALSE"

    def test_unknown_freshness_status_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("P1", "TRUE", freshness_status="EXPIRED")


# --- DecisionPolicyContractTests ----------------------------------------------------

class DecisionPolicyContractTests(unittest.TestCase):
    def test_valid_policy_constructs(self) -> None:
        p = policy(required_ids=("P1",), blocking_ids=("V1",))
        self.assertEqual(p.required_predicate_ids, ("P1",))

    def test_unknown_decision_type_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(decision_type="RESEARCH_OUTCOME")

    def test_empty_policy_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(policy_id="")

    def test_empty_policy_version_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(policy_version="")

    def test_duplicate_predicate_id_within_required_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(required_ids=("P1", "P1"))

    def test_predicate_id_required_and_blocking_simultaneously_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(required_ids=("P1",), blocking_ids=("P1",))

    def test_predicate_id_required_and_optional_simultaneously_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(required_ids=("P1",), optional_ids=("P1",))

    def test_predicate_id_blocking_and_optional_simultaneously_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(blocking_ids=("V1",), optional_ids=("V1",))

    def test_malformed_authority_requirement_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(required_authority_classes=("SUPERUSER",))

    def test_metadata_must_be_json_compatible(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(metadata={"bad": object()})

    def test_policy_is_immutable(self) -> None:
        p = policy()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.policy_id = "other"

    def test_unsupported_schema_version_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(schema_version="99")


# --- DecisionPolicyContractDeepImmutabilityTests (M8-A-H1 hardening) ------------------

class DecisionPolicyContractDeepImmutabilityTests(unittest.TestCase):
    """DecisionPolicyContract.metadata had the identical shallow-copy /
    caller-aliasing weakness M8-B's DecisionSnapshot.metadata had before its
    own hardening fix (a plain `dict(self.metadata)` copy protects only the
    top level, leaving nested dict/list values as the SAME mutable objects
    the caller could still reach). Fixed by reusing nogap_decision.py's
    existing `_deep_freeze()` primitive verbatim - there is no second,
    competing deep-freeze implementation anywhere in the module."""

    # 1. Top-level mutation.
    def test_1_top_level_metadata_assignment_rejected(self) -> None:
        p = policy(metadata={"x": 1})
        with self.assertRaises(TypeError):
            p.metadata["x"] = 2
        self.assertEqual(p.metadata["x"], 1)

    # 2. Nested dict mutation.
    def test_2_nested_metadata_dict_mutation_rejected(self) -> None:
        p = policy(metadata={"nested": {"x": 1}})
        with self.assertRaises(TypeError):
            p.metadata["nested"]["x"] = 2
        self.assertEqual(p.metadata["nested"]["x"], 1)

    # 3. Nested list mutation.
    def test_3_nested_metadata_list_append_rejected(self) -> None:
        p = policy(metadata={"items": [1, 2]})
        with self.assertRaises(AttributeError):
            p.metadata["items"].append(3)
        self.assertEqual(p.metadata["items"], (1, 2))

    # 4. Caller aliasing after construction - exact scenario from the brief.
    def test_4_caller_aliasing_after_construction_defeated(self) -> None:
        original = {"a": [1, {"b": 2}]}
        p = policy(metadata=original)
        original["a"].append(3)
        original["a"][1]["b"] = 999
        self.assertEqual(len(p.metadata["a"]), 2)
        self.assertEqual(p.metadata["a"][0], 1)
        self.assertEqual(p.metadata["a"][1]["b"], 2)

    def test_4b_arbitrary_post_construction_mutation_of_original_cannot_modify_policy(self) -> None:
        original = {"nested": {"x": 1}, "items": [1, 2]}
        p = policy(metadata=original)
        original["nested"]["x"] = 999
        original["items"].append(3)
        original["new_top_level_key"] = "injected"
        self.assertEqual(p.metadata["nested"]["x"], 1)
        self.assertEqual(p.metadata["items"], (1, 2))
        self.assertNotIn("new_top_level_key", p.metadata)

    # 5. Failed mutation attempts have no effect on policy identity fields.
    def test_5_failed_mutation_attempts_do_not_affect_policy_identity(self) -> None:
        p = policy(metadata={"nested": {"x": 1}})
        with self.assertRaises(TypeError):
            p.metadata["nested"]["x"] = 2
        self.assertEqual(p.policy_id, "policy-1")
        self.assertEqual(p.policy_version, "1")
        self.assertEqual(p.required_predicate_ids, ())

    # 6. Serialization remains JSON-compatible after freezing.
    def test_6_frozen_metadata_still_json_serializable_via_canonical_json(self) -> None:
        p = policy(metadata={"nested": {"x": 1}, "items": [1, 2]})
        serialized = nd.canonical_json(p)
        parsed = json.loads(serialized)
        self.assertIn("metadata", parsed)

    # 7. Deterministic canonicalization still works with frozen mappings.
    def test_7_canonicalization_deterministic_with_frozen_metadata(self) -> None:
        p1 = policy(metadata={"nested": {"x": 1}, "items": [1, 2]})
        p2 = policy(metadata={"nested": {"x": 1}, "items": [1, 2]})
        self.assertEqual(nd.canonical_json(p1), nd.canonical_json(p2))

    def test_metadata_representation_is_mappingproxy(self) -> None:
        p = policy(metadata={"x": 1})
        self.assertIsInstance(p.metadata, types.MappingProxyType)

    def test_nested_metadata_dict_is_mappingproxy(self) -> None:
        p = policy(metadata={"nested": {"x": 1}})
        self.assertIsInstance(p.metadata["nested"], types.MappingProxyType)

    def test_nested_metadata_list_is_tuple(self) -> None:
        p = policy(metadata={"items": [1, 2, 3]})
        self.assertIsInstance(p.metadata["items"], tuple)

    def test_metadata_not_the_same_object_as_caller_input(self) -> None:
        original = {"x": 1}
        p = policy(metadata=original)
        self.assertIsNot(p.metadata, original)

    def test_metadata_must_still_be_json_compatible_before_freezing(self) -> None:
        # Validation still happens BEFORE freezing - an un-JSON-serializable
        # value fails closed exactly as before, not silently accepted because
        # freezing might otherwise succeed on arbitrary Python objects.
        with self.assertRaises(nd.DecisionValidationError):
            policy(metadata={"bad": object()})

    def test_reuses_same_deep_freeze_primitive_as_decision_snapshot(self) -> None:
        # No second, competing deep-freeze implementation exists - both
        # DecisionPolicyContract and DecisionSnapshot route metadata through
        # the exact same module-level _deep_freeze() function.
        import inspect
        policy_source = inspect.getsource(nd.DecisionPolicyContract.__post_init__)
        self.assertIn("_deep_freeze(self.metadata)", policy_source)
        self.assertTrue(hasattr(nd, "_deep_freeze"))
        source = inspect.getsource(nd)
        self.assertEqual(source.count("def _deep_freeze"), 1)  # exactly one implementation in the whole module

    def test_no_effect_on_decision_snapshot_behavior(self) -> None:
        # Cross-contract consistency check: fixing DecisionPolicyContract does
        # not alter DecisionSnapshot's own already-hardened metadata behavior.
        scope_obj = nd.DecisionScope(scope_type="TASK", scope_id="TASK-1", project_id="proj-1")
        subject_obj = nd.DecisionSubject(subject_type="TASK", subject_id="TASK-1", project_id="proj-1", revision_ref="a" * 40)
        policy_reference = nd.SnapshotReference(ref_kind="POLICY", ref_id="policy-1", fingerprint="b" * 64)
        snap = nd.build_decision_snapshot(
            request_id="r1", decision_type="TASK_ACCEPTANCE", scope=scope_obj, subject=subject_obj,
            policy_ref=policy_reference, metadata={"nested": {"x": 1}},
        )
        with self.assertRaises(TypeError):
            snap.metadata["nested"]["x"] = 2
        self.assertEqual(snap.metadata["nested"]["x"], 1)


# --- DecisionRequestContractTests ---------------------------------------------------

class DecisionRequestContractTests(unittest.TestCase):
    def test_valid_request_constructs(self) -> None:
        r = request()
        self.assertEqual(r.decision_type, "TASK_ACCEPTANCE")

    def test_empty_request_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            request(request_id="")

    def test_unknown_decision_type_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            request(decision_type="OPERATIONAL_HEALTH")

    def test_scope_must_be_decision_scope_instance(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            request(scope={"scope_type": "TASK"})

    def test_unknown_requester_authority_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            request(requester_authority="SUPERUSER")

    def test_empty_reason_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            request(reason="")

    def test_no_requested_verdict_field_exists(self) -> None:
        field_names = {f.name for f in dataclasses.fields(nd.DecisionRequestContract)}
        self.assertNotIn("requested_verdict", field_names)
        self.assertNotIn("desired_verdict", field_names)
        self.assertNotIn("requested_outcome", field_names)

    def test_requested_verdict_kwarg_raises_type_error(self) -> None:
        with self.assertRaises(TypeError):
            nd.DecisionRequestContract(
                request_id="r1", project_id="p1", decision_type="TASK_ACCEPTANCE", scope=scope(),
                requested_by="a", requester_authority="EXECUTION", reason="r", requested_verdict="ACCEPT",
            )

    def test_request_is_immutable(self) -> None:
        r = request()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.reason = "changed"


# --- DecisionEvaluationContractTests -------------------------------------------------

def make_evaluation(**overrides) -> nd.DecisionEvaluationContract:
    predicate_results = complete_proof_predicates()
    fields = dict(
        evaluation_id="eval-1", request_id="req-1", decision_type="TASK_ACCEPTANCE", scope=scope(),
        policy_ref="policy-1", predicate_results=predicate_results,
        satisfied_predicates=tuple(pr.predicate_id for pr in predicate_results if pr.truth_value == "TRUE"),
        failed_predicates=tuple(pr.predicate_id for pr in predicate_results if pr.truth_value == "FALSE"),
        unknown_predicates=(), conflicting_predicates=(),
        blocking_reasons=(), reason_codes=(), verdict="ACCEPT",
    )
    fields.update(overrides)
    return nd.DecisionEvaluationContract(**fields)


class DecisionEvaluationContractTests(unittest.TestCase):
    def test_valid_evaluation_constructs(self) -> None:
        ev = make_evaluation()
        self.assertEqual(ev.verdict, "ACCEPT")

    def test_unknown_verdict_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_evaluation(verdict="PASS")

    def test_duplicate_predicate_result_ids_rejected(self) -> None:
        dup = complete_proof_predicates() + (requirement("EXPECTED_EFFECT", "TRUE"),)
        with self.assertRaises(nd.DecisionValidationError):
            make_evaluation(predicate_results=dup)

    def test_bucket_must_reference_known_predicate(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_evaluation(failed_predicates=("NOT_A_REAL_PREDICATE",))

    def test_bucket_truth_value_must_match(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_evaluation(failed_predicates=("EXPECTED_EFFECT",))  # EXPECTED_EFFECT is TRUE, not FALSE

    def test_predicate_cannot_appear_in_two_buckets(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_evaluation(
                satisfied_predicates=("EXPECTED_EFFECT",),
                unknown_predicates=("EXPECTED_EFFECT",),
            )

    def test_every_predicate_must_appear_in_exactly_one_bucket(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_evaluation(satisfied_predicates=())  # drops EXPECTED_EFFECT etc. from any bucket

    def test_unsupported_engine_version_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_evaluation(engine_version="99")

    def test_evaluation_is_immutable(self) -> None:
        ev = make_evaluation()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ev.verdict = "REJECT"


# --- DecisionRecordContractTests ----------------------------------------------------

def make_record(**overrides) -> nd.DecisionRecordContract:
    fields = dict(
        decision_id="dec-1", evaluation_id="eval-1", request_id="req-1", decision_type="TASK_ACCEPTANCE",
        scope=scope(), verdict="ACCEPT", reason_codes=(), evaluation_ref="eval-1", policy_ref="policy-1",
        created_at="2026-09-02T00:00:00Z",
    )
    fields.update(overrides)
    return nd.DecisionRecordContract(**fields)


class DecisionRecordContractTests(unittest.TestCase):
    def test_valid_record_constructs(self) -> None:
        rec = make_record()
        self.assertEqual(rec.verdict, "ACCEPT")

    def test_unknown_verdict_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_record(verdict="APPROVE")

    def test_empty_decision_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_record(decision_id="")

    def test_record_is_immutable(self) -> None:
        rec = make_record()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            rec.verdict = "REJECT"

    def test_no_mutating_verdict_api_exists(self) -> None:
        rec = make_record()
        for forbidden in ("update_verdict", "set_accept", "rewrite_decision", "set_verdict", "accept", "reject"):
            self.assertFalse(hasattr(rec, forbidden), f"DecisionRecordContract must not expose {forbidden}()")
        self.assertFalse(hasattr(nd.DecisionRecordContract, "update_verdict"))
        self.assertFalse(hasattr(nd.DecisionRecordContract, "set_accept"))
        self.assertFalse(hasattr(nd.DecisionRecordContract, "rewrite_decision"))

    def test_supersedes_is_optional_and_only_a_reference(self) -> None:
        rec = make_record(supersedes="dec-0")
        self.assertEqual(rec.supersedes, "dec-0")
        # supersedes is a plain string ref; there is no current-decision selector
        # anywhere in this module (get_current_decision intentionally does not exist).
        self.assertFalse(hasattr(nd, "get_current_decision"))

    def test_no_current_decision_selector_yet(self) -> None:
        self.assertFalse(hasattr(nd, "get_current_decision"))
        self.assertFalse(hasattr(nd, "select_current_decision"))


# --- DecisionAlgebraTests (mandatory scenarios 1-5, property tests 1-4,12-15) --------

class DecisionAlgebraTests(unittest.TestCase):
    # Mandatory Scenario 1: complete proof -> ACCEPT
    def test_scenario_1_complete_proof_accepts(self) -> None:
        result = nd.derive_contract_verdict(complete_proof_predicates(), policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "ACCEPT")
        self.assertEqual(result.blocking_reasons, ())

    # Mandatory Scenario 2: missing verification -> ABSTAIN, never REJECT/ACCEPT
    def test_scenario_2_missing_verification_abstains(self) -> None:
        predicates = (
            requirement("EXPECTED_EFFECT", "TRUE"),
            requirement("DETERMINISTIC_VERIFICATION", "UNKNOWN"),
            requirement("METHODOLOGY_READY", "TRUE"),
            violation("GATE_TAMPERING", "FALSE"),
            violation("BLOCKING_FAILURE", "FALSE"),
        )
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "ABSTAIN")

    # Mandatory Scenario 3: proven failure -> REJECT
    def test_scenario_3_proven_blocking_failure_rejects(self) -> None:
        predicates = (
            requirement("EXPECTED_EFFECT", "TRUE"),
            requirement("DETERMINISTIC_VERIFICATION", "TRUE"),
            requirement("METHODOLOGY_READY", "TRUE"),
            violation("GATE_TAMPERING", "FALSE"),
            violation("BLOCKING_FAILURE", "TRUE"),
        )
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "REJECT")

    # Mandatory Scenario 4: conflict -> ABSTAIN, never an arbitrary winner
    def test_scenario_4_conflict_abstains(self) -> None:
        predicates = (
            requirement("EXPECTED_EFFECT", "TRUE"),
            requirement("DETERMINISTIC_VERIFICATION", "CONFLICT"),
            requirement("METHODOLOGY_READY", "TRUE"),
            violation("GATE_TAMPERING", "FALSE"),
            violation("BLOCKING_FAILURE", "FALSE"),
        )
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "ABSTAIN")

    # Mandatory Scenario 5: gate tampering -> REJECT, no positive evidence compensates
    def test_scenario_5_gate_tampering_rejects_despite_all_else_true(self) -> None:
        predicates = (
            requirement("EXPECTED_EFFECT", "TRUE"),
            requirement("DETERMINISTIC_VERIFICATION", "TRUE"),
            requirement("METHODOLOGY_READY", "TRUE"),
            violation("GATE_TAMPERING", "TRUE"),
            violation("BLOCKING_FAILURE", "FALSE"),
        )
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "REJECT")
        self.assertIn("GATE_TAMPERING", result.blocking_reasons[0])

    # Property 1: any mandatory UNKNOWN prevents ACCEPT (sweep every predicate slot)
    def test_property_1_any_mandatory_unknown_prevents_accept(self) -> None:
        base = list(complete_proof_predicates())
        for i, pr in enumerate(base):
            mutated = list(base)
            mutated[i] = dataclasses.replace(pr, truth_value="UNKNOWN")
            result = nd.derive_contract_verdict(mutated, policy_contract=COMPLETE_PROOF_POLICY)
            self.assertNotEqual(result.verdict, "ACCEPT", f"predicate {pr.predicate_id} UNKNOWN must prevent ACCEPT")

    # Property 2: any mandatory CONFLICT prevents ACCEPT
    def test_property_2_any_mandatory_conflict_prevents_accept(self) -> None:
        base = list(complete_proof_predicates())
        for i, pr in enumerate(base):
            mutated = list(base)
            mutated[i] = dataclasses.replace(pr, truth_value="CONFLICT")
            result = nd.derive_contract_verdict(mutated, policy_contract=COMPLETE_PROOF_POLICY)
            self.assertNotEqual(result.verdict, "ACCEPT", f"predicate {pr.predicate_id} CONFLICT must prevent ACCEPT")

    # Property 3: any blocking violation TRUE prevents ACCEPT
    def test_property_3_any_blocking_violation_true_prevents_accept(self) -> None:
        for violation_id in ("GATE_TAMPERING", "BLOCKING_FAILURE"):
            predicates = [dataclasses.replace(pr, truth_value="TRUE") if pr.predicate_id == violation_id else pr for pr in complete_proof_predicates()]
            result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
            self.assertEqual(result.verdict, "REJECT")

    # Property 4: liveness - all TRUE/FALSE-as-expected can ACCEPT
    def test_property_4_liveness_all_satisfied_produces_accept(self) -> None:
        result = nd.derive_contract_verdict(complete_proof_predicates(), policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "ACCEPT")

    # Property 12: unrelated optional UNKNOWN predicate does not flip ACCEPT->REJECT
    def test_property_12_optional_unknown_does_not_affect_accept(self) -> None:
        p = policy(
            required_ids=("EXPECTED_EFFECT", "DETERMINISTIC_VERIFICATION", "METHODOLOGY_READY"),
            blocking_ids=("GATE_TAMPERING", "BLOCKING_FAILURE"),
            optional_ids=("NICE_TO_HAVE",),
        )
        predicates = complete_proof_predicates() + (requirement("NICE_TO_HAVE", "UNKNOWN", required=False),)
        result = nd.derive_contract_verdict(predicates, policy_contract=p)
        self.assertEqual(result.verdict, "ACCEPT")

    # Property 13: adding a proven blocking violation converts ACCEPT-able set to REJECT
    def test_property_13_adding_blocking_violation_converts_to_reject(self) -> None:
        p = policy(
            required_ids=("EXPECTED_EFFECT", "DETERMINISTIC_VERIFICATION", "METHODOLOGY_READY"),
            blocking_ids=("GATE_TAMPERING", "BLOCKING_FAILURE", "NEW_VIOLATION"),
        )
        predicates = complete_proof_predicates() + (violation("NEW_VIOLATION", "TRUE"),)
        result = nd.derive_contract_verdict(predicates, policy_contract=p)
        self.assertEqual(result.verdict, "REJECT")

    # Property 14: replacing mandatory TRUE with UNKNOWN converts ACCEPT to ABSTAIN
    def test_property_14_true_to_unknown_converts_accept_to_abstain(self) -> None:
        predicates = [dataclasses.replace(pr, truth_value="UNKNOWN") if pr.predicate_id == "EXPECTED_EFFECT" else pr for pr in complete_proof_predicates()]
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "ABSTAIN")

    # Property 15: replacing mandatory TRUE with CONFLICT converts ACCEPT to ABSTAIN
    def test_property_15_true_to_conflict_converts_accept_to_abstain(self) -> None:
        predicates = [dataclasses.replace(pr, truth_value="CONFLICT") if pr.predicate_id == "EXPECTED_EFFECT" else pr for pr in complete_proof_predicates()]
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "ABSTAIN")

    def test_required_false_rejects(self) -> None:
        predicates = [dataclasses.replace(pr, truth_value="FALSE") if pr.predicate_id == "EXPECTED_EFFECT" else pr for pr in complete_proof_predicates()]
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "REJECT")

    def test_missing_evidence_never_equals_reject(self) -> None:
        # UNKNOWN ("missing evidence") must route to ABSTAIN, never REJECT.
        predicates = [dataclasses.replace(pr, truth_value="UNKNOWN") if pr.predicate_id == "DETERMINISTIC_VERIFICATION" else pr for pr in complete_proof_predicates()]
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertNotEqual(result.verdict, "REJECT")
        self.assertEqual(result.verdict, "ABSTAIN")

    def test_no_failure_evidence_never_equals_accept(self) -> None:
        # violation FALSE (absence of failure) alone, with a mandatory UNKNOWN
        # requirement, must not become ACCEPT.
        predicates = (
            requirement("EXPECTED_EFFECT", "UNKNOWN"),
            violation("BLOCKING_FAILURE", "FALSE"),
        )
        p = policy(required_ids=("EXPECTED_EFFECT",), blocking_ids=("BLOCKING_FAILURE",))
        result = nd.derive_contract_verdict(predicates, policy_contract=p)
        self.assertNotEqual(result.verdict, "ACCEPT")

    def test_scope_mismatch_fails_closed_s7(self) -> None:
        mismatched_scope_predicate = requirement("EXPECTED_EFFECT", "TRUE", scope_ref="TASK:proj-1:OTHER-TASK")
        predicates = [mismatched_scope_predicate if pr.predicate_id == "EXPECTED_EFFECT" else pr for pr in complete_proof_predicates()]
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY, scope=scope())

    def test_matching_scope_ref_is_accepted(self) -> None:
        matching = requirement("EXPECTED_EFFECT", "TRUE", scope_ref=scope().canonical_id())
        predicates = [matching if pr.predicate_id == "EXPECTED_EFFECT" else pr for pr in complete_proof_predicates()]
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY, scope=scope())
        self.assertEqual(result.verdict, "ACCEPT")


# --- DecisionDeterminismTests (property 5, 9-11) -------------------------------------

class DecisionDeterminismTests(unittest.TestCase):
    # Property 5 / Mandatory Scenario 8: permutation of predicate input order does not
    # change the verdict.
    def test_property_5_scenario_8_order_independence(self) -> None:
        base = list(complete_proof_predicates())
        verdicts = set()
        reason_sets = set()
        for perm in itertools.permutations(base):
            result = nd.derive_contract_verdict(list(perm), policy_contract=COMPLETE_PROOF_POLICY)
            verdicts.add(result.verdict)
            reason_sets.add(frozenset(result.reason_codes))
        self.assertEqual(verdicts, {"ACCEPT"})
        self.assertEqual(len(reason_sets), 1)

    def test_property_5_order_independence_on_abstain(self) -> None:
        base = [dataclasses.replace(pr, truth_value="UNKNOWN") if pr.predicate_id == "DETERMINISTIC_VERIFICATION" else pr for pr in complete_proof_predicates()]
        verdicts = set()
        for perm in itertools.permutations(base):
            result = nd.derive_contract_verdict(list(perm), policy_contract=COMPLETE_PROOF_POLICY)
            verdicts.add(result.verdict)
        self.assertEqual(verdicts, {"ABSTAIN"})

    # Property 9: malformed enum fails closed
    def test_property_9_malformed_enum_fails_closed(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("P1", "SORT_OF")

    # Property 10: same contract inputs serialize canonically/deterministically
    def test_property_10_canonical_json_stable(self) -> None:
        ev1 = make_evaluation(evaluated_at="2026-09-02T00:00:00Z")
        ev2 = make_evaluation(evaluated_at="2026-09-02T01:00:00Z")
        self.assertEqual(nd.canonical_json(ev1), nd.canonical_json(ev2))

    def test_property_10_canonical_json_differs_on_real_change(self) -> None:
        ev1 = make_evaluation()
        unknown_predicates = tuple(dataclasses.replace(pr, truth_value="UNKNOWN") for pr in complete_proof_predicates())
        ev2 = make_evaluation(
            predicate_results=unknown_predicates,
            verdict="ABSTAIN",
            unknown_predicates=tuple(pr.predicate_id for pr in unknown_predicates),
            satisfied_predicates=(), failed_predicates=(),
        )
        self.assertNotEqual(nd.canonical_json(ev1), nd.canonical_json(ev2))

    # Property 11: reason code ordering does not depend on insertion order
    def test_property_11_reason_code_ordering_stable(self) -> None:
        forward = nd.derive_contract_verdict(
            [dataclasses.replace(pr, truth_value="CONFLICT") for pr in complete_proof_predicates()],
            policy_contract=COMPLETE_PROOF_POLICY,
        )
        reversed_input = nd.derive_contract_verdict(
            list(reversed([dataclasses.replace(pr, truth_value="CONFLICT") for pr in complete_proof_predicates()])),
            policy_contract=COMPLETE_PROOF_POLICY,
        )
        self.assertEqual(forward.reason_codes, reversed_input.reason_codes)


# --- DecisionFailClosedTests (property 6-8) -------------------------------------------

class DecisionFailClosedTests(unittest.TestCase):
    # Property 6 / Mandatory Scenario 10: duplicate contradictory predicate fails closed
    def test_property_6_scenario_10_duplicate_contradictory_predicate_fails_closed(self) -> None:
        predicates = [requirement("P1", "TRUE"), requirement("P1", "FALSE")]
        p = policy(required_ids=("P1",))
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict(predicates, policy_contract=p)

    def test_duplicate_agreeing_predicate_also_fails_closed(self) -> None:
        # Even identical duplicates fail closed - never select "the" duplicate,
        # first or last; the input itself is malformed.
        predicates = [requirement("P1", "TRUE"), requirement("P1", "TRUE")]
        p = policy(required_ids=("P1",))
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict(predicates, policy_contract=p)

    # Property 7 / Mandatory Scenario 9: unknown predicate referenced by policy fails closed
    def test_property_7_scenario_9_unknown_policy_predicate_fails_closed(self) -> None:
        p = policy(required_ids=("MISSING_PREDICATE",))
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict([requirement("OTHER", "TRUE")], policy_contract=p)

    # Property 8: conflicting policy classification fails closed
    def test_property_8_conflicting_policy_classification_fails_closed(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            policy(required_ids=("P1",), blocking_ids=("P1",))

    def test_predicate_result_role_inconsistent_with_policy_classification_fails_closed(self) -> None:
        # policy says P1 is required (REQUIREMENT), but the supplied result is a
        # VIOLATION - fail closed rather than silently reinterpreting it.
        p = policy(required_ids=("P1",))
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict([violation("P1", "FALSE", blocking=False)], policy_contract=p)

    def test_predicate_result_declared_required_but_policy_says_optional_fails_closed(self) -> None:
        p = policy(optional_ids=("P1",))
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict([requirement("P1", "TRUE", required=True)], policy_contract=p)

    def test_unclassified_predicate_result_fails_closed(self) -> None:
        p = policy(required_ids=("P1",))
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict(
                [requirement("P1", "TRUE"), requirement("P2", "TRUE", required=False)],
                policy_contract=p,
            )

    def test_non_predicate_result_input_fails_closed(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict([{"predicate_id": "P1", "truth_value": "TRUE"}], policy_contract=policy(required_ids=("P1",)))

    def test_non_policy_contract_input_fails_closed(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict([requirement("P1", "TRUE")], policy_contract={"required_predicate_ids": ["P1"]})


# --- DecisionAdversarialContractTests (attacks A-J) ------------------------------------

class DecisionAdversarialContractTests(unittest.TestCase):
    # A: fake text "ALL TESTS PASSED" cannot instantiate/prove ACCEPT by itself.
    def test_attack_a_fake_text_cannot_prove_accept(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict("ALL TESTS PASSED", policy_contract=COMPLETE_PROOF_POLICY)

    # B: advisory model votes cannot manufacture ACCEPT.
    def test_attack_b_advisory_model_votes_produce_no_verdict(self) -> None:
        advisory_votes = {"claude": "PASS", "codex": "PASS", "other": "PASS"}
        # There is no function in this module that accepts a dict of advisory
        # votes and returns a DecisionVerdict - the only entry point is
        # derive_contract_verdict, which requires DecisionPredicateResult objects.
        self.assertFalse(hasattr(nd, "vote"))
        self.assertFalse(hasattr(nd, "consensus_verdict"))
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict(list(advisory_votes.values()), policy_contract=COMPLETE_PROOF_POLICY)

    # Mandatory Scenario 6: three models agreeing cannot manufacture acceptance
    # when mandatory deterministic verification is UNKNOWN.
    def test_scenario_6_model_consensus_attack_abstains(self) -> None:
        p = policy(
            required_ids=("DETERMINISTIC_VERIFICATION",),
            blocking_ids=(), optional_ids=("CLAUDE_ADVISORY", "CODEX_ADVISORY", "OTHER_ADVISORY"),
        )
        predicates = (
            requirement("DETERMINISTIC_VERIFICATION", "UNKNOWN"),
            requirement("CLAUDE_ADVISORY", "TRUE", required=False),
            requirement("CODEX_ADVISORY", "TRUE", required=False),
            requirement("OTHER_ADVISORY", "TRUE", required=False),
        )
        result = nd.derive_contract_verdict(predicates, policy_contract=p)
        self.assertEqual(result.verdict, "ABSTAIN")

    # C: missing evidence -> cannot be ACCEPT.
    def test_attack_c_missing_evidence_cannot_accept(self) -> None:
        p = policy(required_ids=("P1",))
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict([], policy_contract=p)  # required predicate simply absent

    # D: conflicting PASS/FAIL-equivalent predicate inputs -> cannot be ACCEPT.
    def test_attack_d_conflicting_predicate_inputs_cannot_accept(self) -> None:
        predicates = [dataclasses.replace(pr, truth_value="CONFLICT") if pr.predicate_id == "EXPECTED_EFFECT" else pr for pr in complete_proof_predicates()]
        result = nd.derive_contract_verdict(predicates, policy_contract=COMPLETE_PROOF_POLICY)
        self.assertNotEqual(result.verdict, "ACCEPT")

    # E: duplicate predicate ID, one TRUE one FALSE -> fail closed, never latest/first.
    def test_attack_e_duplicate_id_contradictory_fails_closed_not_latest_or_first(self) -> None:
        p = policy(required_ids=("P1",))
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict([requirement("P1", "FALSE"), requirement("P1", "TRUE")], policy_contract=p)

    # F: unknown policy predicate -> fail closed.
    def test_attack_f_unknown_policy_predicate_fails_closed(self) -> None:
        p = policy(blocking_ids=("GHOST_VIOLATION",))
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict([], policy_contract=p)

    # G: unknown authority class -> fail closed.
    def test_attack_g_unknown_authority_class_fails_closed(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            request(requester_authority="SUPER_ADMIN")

    # H: executor claims self-review - authority data cannot magically become
    # acceptance authority.
    def test_attack_h_executor_self_review_not_acceptance_authority(self) -> None:
        pr = requirement("P1", "TRUE", authority_refs=("actor-x",))
        # There is no helper anywhere in this module that maps an authority
        # class (or an actor ref) to verdict-issuing capability - authority_refs
        # is inert metadata the algebra never consults.
        self.assertFalse(hasattr(nd, "authority_class_is_acceptance_capable"))
        self.assertEqual(pr.authority_refs, ("actor-x",))
        result = nd.derive_contract_verdict([requirement("P1", "TRUE")], policy_contract=policy(required_ids=("P1",)))
        self.assertEqual(result.verdict, "ACCEPT")  # driven only by truth_value, never by authority_refs content

    # I: READY_FOR_DECISION string supplied as a verdict -> rejected.
    def test_attack_i_ready_for_decision_rejected_as_verdict(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_record(verdict="READY_FOR_DECISION")

    # J: SUPPORTED string supplied as a verdict -> rejected.
    def test_attack_j_supported_rejected_as_verdict(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_record(verdict="SUPPORTED")


# --- Mandatory Scenario 7: namespace confusion (also DecisionNamespaceSeparationTests) --

class MandatoryScenarioNamespaceTests(unittest.TestCase):
    def test_scenario_7_namespace_confusion_all_rejected(self) -> None:
        for banned in ("SUPPORTED", "READY_FOR_DECISION", "SUCCEEDED", "HEALTHY", "PASS"):
            with self.assertRaises(nd.DecisionValidationError):
                make_record(verdict=banned)


class DecisionNamespaceSeparationTests(unittest.TestCase):
    def test_research_outcomes_disjoint_from_verdicts(self) -> None:
        import nogap_research as nr
        self.assertTrue(nd.DECISION_VERDICTS.isdisjoint(nr.ASSESSMENT_OUTCOMES))

    def test_lifecycle_readiness_outcomes_disjoint_from_verdicts(self) -> None:
        import nogap_lifecycle as nlc
        self.assertTrue(nd.DECISION_VERDICTS.isdisjoint(nlc.READINESS_OUTCOMES))

    def test_deployment_statuses_disjoint_from_verdicts(self) -> None:
        import nogap_lifecycle as nlc
        self.assertTrue(nd.DECISION_VERDICTS.isdisjoint(nlc.DEPLOYMENT_STATUSES))

    def test_lifecycle_outcomes_disjoint_from_verdicts(self) -> None:
        import nogap_lifecycle as nlc
        self.assertTrue(nd.DECISION_VERDICTS.isdisjoint(nlc.LIFECYCLE_OUTCOMES))

    def test_review_verdict_vocabulary_disjoint_from_decision_verdicts(self) -> None:
        import nogap_verification as nv
        uppercased = {v.upper() for v in nv.REVIEW_VERDICTS}
        self.assertTrue(nd.DECISION_VERDICTS.isdisjoint(uppercased))

    # Property 19: research outcome enum cannot be used as DecisionVerdict.
    def test_property_19_research_outcome_rejected_as_verdict(self) -> None:
        import nogap_research as nr
        for outcome in nr.ASSESSMENT_OUTCOMES:
            with self.assertRaises(nd.DecisionValidationError):
                make_record(verdict=outcome)

    # Property 20: verification status enum cannot be used as DecisionVerdict.
    def test_property_20_verification_status_rejected_as_verdict(self) -> None:
        import nogap_verification as nv
        for verdict in nv.REVIEW_VERDICTS:
            with self.assertRaises(nd.DecisionValidationError):
                make_record(verdict=verdict.upper())

    # Property 21: lifecycle status enum cannot be used as DecisionVerdict.
    def test_property_21_lifecycle_outcome_rejected_as_verdict(self) -> None:
        import nogap_lifecycle as nlc
        for outcome in nlc.LIFECYCLE_OUTCOMES:
            with self.assertRaises(nd.DecisionValidationError):
                make_record(verdict=outcome)

    # Property 22: deployment status enum cannot be used as DecisionVerdict.
    def test_property_22_deployment_status_rejected_as_verdict(self) -> None:
        import nogap_lifecycle as nlc
        for status in nlc.DEPLOYMENT_STATUSES:
            with self.assertRaises(nd.DecisionValidationError):
                make_record(verdict=status)

    def test_readiness_outcome_rejected_as_verdict(self) -> None:
        import nogap_lifecycle as nlc
        for outcome in nlc.READINESS_OUTCOMES:
            with self.assertRaises(nd.DecisionValidationError):
                make_record(verdict=outcome)


# --- DecisionAuthoritySeparationTests (S5, S8-S12, property 16) -----------------------

class DecisionAuthoritySeparationTests(unittest.TestCase):
    # Property 16: executor authority cannot satisfy an acceptance-authority
    # requirement merely because its actor name equals the reviewer's name.
    def test_property_16_actor_name_equality_does_not_grant_authority(self) -> None:
        pr_execution = requirement("P1", "TRUE", authority_refs=("same-actor",))
        pr_review = requirement("P2", "TRUE", authority_refs=("same-actor",))
        # There is no code path anywhere in this module - no helper, no
        # algebra branch - where a matching actor name/ref upgrades EXECUTION
        # (or any class) toward verdict-issuing capability. authority_refs is
        # opaque metadata; derive_contract_verdict() does not read it at all.
        self.assertEqual(pr_execution.authority_refs, pr_review.authority_refs)
        p = policy(required_ids=("P1", "P2"))
        result = nd.derive_contract_verdict([pr_execution, pr_review], policy_contract=p)
        self.assertEqual(result.verdict, "ACCEPT")  # driven by truth_value TRUE on both, not by the shared actor name

    # S8: research SUPPORTED cannot imply technical ACCEPT.
    def test_s8_research_supported_cannot_imply_accept(self) -> None:
        import nogap_research as nr
        self.assertIn("SUPPORTED", nr.ASSESSMENT_OUTCOMES)
        self.assertNotIn("SUPPORTED", nd.DECISION_VERDICTS)
        with self.assertRaises(nd.DecisionValidationError):
            make_record(verdict="SUPPORTED")

    # S9: verification PASS alone cannot imply technical ACCEPT.
    def test_s9_verification_pass_alone_cannot_imply_accept(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_record(verdict="PASS")

    # S10: deployment SUCCEEDED cannot imply technical ACCEPT.
    def test_s10_deployment_succeeded_cannot_imply_accept(self) -> None:
        import nogap_lifecycle as nlc
        self.assertIn("SUCCEEDED", nlc.DEPLOYMENT_STATUSES)
        with self.assertRaises(nd.DecisionValidationError):
            make_record(verdict="SUCCEEDED")

    # S11: memory projection cannot imply technical ACCEPT - this module has no
    # MEMORY.md-consuming code path at all.
    def test_s11_no_memory_authority_path_exists(self) -> None:
        import inspect
        source = inspect.getsource(nd)
        self.assertNotIn("MEMORY.md", source)
        self.assertNotIn("nogap_memory", source)

    # S12: model consensus cannot imply technical ACCEPT - no model/AgentRuntime/
    # provider/vote/score code path exists anywhere in this module.
    def test_s12_no_model_or_scoring_path_exists(self) -> None:
        # Scoped to actual code patterns, not prose - this module's own docstring
        # legitimately explains what it does NOT call (e.g. "does NOT call ...
        # AgentRuntime"), which would trip a bare substring check on the word
        # itself. These patterns only match real usage: an import, a call, or an
        # instantiation.
        import inspect
        source = inspect.getsource(nd)
        # DecisionScore/acceptance_probability/weighted_vote are checked
        # structurally (hasattr + dataclass field names) in DecisionNoScoreTests
        # below - not here, since this module's own docstring legitimately names
        # them in its "there is no X" disclaimer.
        for banned_pattern in (
            "AgentRuntime(", "import nogap_adapters", "OpenRouter(", "import requests",
            "import openai", "import anthropic", "import subprocess", "import urllib",
        ):
            self.assertNotIn(banned_pattern, source)

    def test_module_has_zero_project_imports(self) -> None:
        import ast
        tree = ast.parse(Path(nd.__file__).read_text(encoding="utf-8"))
        project_modules = {p.stem for p in (ROOT / "scripts").glob("*.py")} - {"nogap_decision"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertTrue(imported.isdisjoint(project_modules), f"nogap_decision.py must not import other project modules; found {imported & project_modules}")

    def test_no_filesystem_access_in_module_source(self) -> None:
        import inspect
        source = inspect.getsource(nd)
        for banned_token in ("open(", "Path(", "os.listdir", "iterdir", "glob("):
            self.assertNotIn(banned_token, source)


# --- DecisionVersioningTests ---------------------------------------------------------

class DecisionVersioningTests(unittest.TestCase):
    def test_schema_and_engine_version_constants_are_simple_strings(self) -> None:
        self.assertEqual(nd.M8_DECISION_SCHEMA_VERSION, "1")
        self.assertEqual(nd.M8_DECISION_ENGINE_VERSION, "1")

    def test_unsupported_schema_version_fails_closed_on_request(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            request(schema_version="2")

    def test_unsupported_schema_version_fails_closed_on_evaluation(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_evaluation(schema_version="2")

    def test_unsupported_engine_version_fails_closed_on_record(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_record(engine_version="2")

    def test_unsupported_schema_version_fails_closed_on_record(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            make_record(schema_version="2")


# --- No-score-based-acceptance guard --------------------------------------------------

class DecisionNoScoreTests(unittest.TestCase):
    def test_no_score_fields_anywhere_in_module(self) -> None:
        for name in ("DecisionScore", "acceptance_probability", "weighted_vote", "confidence"):
            self.assertFalse(hasattr(nd, name), f"{name} must not exist in nogap_decision")
        for cls in (nd.DecisionPredicateResult, nd.DecisionPolicyContract, nd.DecisionRequestContract,
                    nd.DecisionEvaluationContract, nd.DecisionRecordContract):
            field_names = {f.name for f in dataclasses.fields(cls)}
            self.assertFalse(field_names & {"score", "confidence", "weight", "probability"}, f"{cls.__name__} must not carry a score-like field")

    def test_no_threshold_constant_in_module(self) -> None:
        module_vars = vars(nd)
        for key in module_vars:
            self.assertNotIn("THRESHOLD", key.upper())


# --- M8-C: Predicate Evidence Binding ------------------------------------------------

# A. RESULT FINGERPRINT

class ResultFingerprintTests(unittest.TestCase):
    def test_1_deterministic_for_equal_semantic_claims(self) -> None:
        a = requirement("P1", "TRUE")
        b = requirement("P1", "TRUE")
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)

    def test_2_predicate_id_change_changes_fingerprint(self) -> None:
        a = requirement("P1", "TRUE")
        b = requirement("P2", "TRUE")
        self.assertNotEqual(a.result_fingerprint, b.result_fingerprint)

    def test_3_role_change_changes_fingerprint(self) -> None:
        a = requirement("P1", "TRUE")
        b = violation("P1", "TRUE")
        self.assertNotEqual(a.result_fingerprint, b.result_fingerprint)

    def test_4_truth_value_change_changes_fingerprint(self) -> None:
        a = requirement("P1", "TRUE")
        b = requirement("P1", "FALSE")
        self.assertNotEqual(a.result_fingerprint, b.result_fingerprint)

    def test_5_required_change_does_not_change_fingerprint(self) -> None:
        a = requirement("P1", "TRUE", required=True)
        b = requirement("P1", "TRUE", required=False)
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)

    def test_6_blocking_change_does_not_change_fingerprint(self) -> None:
        a = requirement("P1", "TRUE", blocking=False)
        b = requirement("P1", "TRUE", blocking=True)
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)

    def test_7_reason_codes_change_does_not_change_fingerprint(self) -> None:
        a = requirement("P1", "FALSE", reason_codes=())
        b = requirement("P1", "FALSE", reason_codes=("MANDATORY_PREDICATE_FALSE",))
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)

    def test_8_source_refs_change_does_not_change_fingerprint(self) -> None:
        a = requirement("P1", "TRUE", source_refs=())
        b = requirement("P1", "TRUE", source_refs=("evidence-1",))
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)

    def test_9_authority_refs_change_does_not_change_fingerprint(self) -> None:
        a = requirement("P1", "TRUE", authority_refs=())
        b = requirement("P1", "TRUE", authority_refs=("actor-1",))
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)

    def test_10_scope_ref_change_does_not_change_fingerprint(self) -> None:
        a = requirement("P1", "TRUE", scope_ref=None)
        b = requirement("P1", "TRUE", scope_ref="TASK:proj-1:TASK-1")
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)

    def test_11_freshness_status_change_does_not_change_fingerprint(self) -> None:
        # only combinations valid under S4 (truth_value=TRUE cannot pair with STALE)
        a = requirement("P1", "TRUE", freshness_status=None)
        b = requirement("P1", "TRUE", freshness_status="FRESH")
        c = requirement("P1", "TRUE", freshness_status="UNKNOWN")
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)
        self.assertEqual(a.result_fingerprint, c.result_fingerprint)

    def test_12_details_change_does_not_change_fingerprint(self) -> None:
        a = requirement("P1", "TRUE", details=None)
        b = requirement("P1", "TRUE", details="looks fine to me")
        self.assertEqual(a.result_fingerprint, b.result_fingerprint)

    def test_semantic_payload_contains_exactly_three_fields(self) -> None:
        payload = requirement("P1", "TRUE").semantic_payload()
        self.assertEqual(set(payload), {"predicate_id", "role", "truth_value"})

    def test_result_fingerprint_uses_existing_fingerprint_payload(self) -> None:
        r = requirement("P1", "TRUE")
        expected = nd.fingerprint_payload(r.semantic_payload())
        self.assertEqual(r.result_fingerprint, expected)


# B. PREDICATEEVIDENCEBINDING CONTRACT

class PredicateEvidenceBindingContractTests(unittest.TestCase):
    def test_13_valid_construction(self) -> None:
        b = m8c_binding()
        self.assertEqual(b.verifier_id, "verifier-x")

    def test_14_invalid_result_fingerprint_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            m8c_binding(predicate_result_fingerprint="not-a-digest")

    def test_15_invalid_snapshot_fingerprint_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            m8c_binding(snapshot_fingerprint="not-a-digest")

    def test_16_empty_policy_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            m8c_binding(policy_id="")

    def test_17_empty_policy_version_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            m8c_binding(policy_version="")

    def test_18_empty_verifier_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            m8c_binding(verifier_id="")

    def test_19_invalid_optional_authority_class_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            m8c_binding(authority_class="SUPERUSER")

    def test_20_evidence_refs_stored_as_tuple(self) -> None:
        b = m8c_binding(evidence_refs=[M8C_EVIDENCE])
        self.assertIsInstance(b.evidence_refs, tuple)

    def test_21_duplicate_evidence_refs_rejected(self) -> None:
        dup = evidence_ref(ref_id="v1", fingerprint=digest("content-A"))
        conflicting = evidence_ref(ref_id="v1", fingerprint=digest("content-B"))
        with self.assertRaises(nd.DecisionValidationError):
            m8c_binding(evidence_refs=(dup, conflicting))

    def test_22_caller_aliasing_defeated(self) -> None:
        refs_list = [evidence_ref(ref_id="v1")]
        b = m8c_binding(evidence_refs=refs_list)
        refs_list.append(evidence_ref(ref_id="v2"))
        self.assertEqual(len(b.evidence_refs), 1)

    def test_23_frozen_dataclass_mutation_rejected(self) -> None:
        b = m8c_binding()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            b.verifier_id = "attacker"

    def test_24_no_metadata_field_exists(self) -> None:
        field_names = {f.name for f in dataclasses.fields(nd.PredicateEvidenceBinding)}
        self.assertNotIn("metadata", field_names)

    def test_25_no_predicate_id_field_exists(self) -> None:
        field_names = {f.name for f in dataclasses.fields(nd.PredicateEvidenceBinding)}
        self.assertNotIn("predicate_id", field_names)

    def test_optional_correlation_fields_validated_when_present(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            m8c_binding(execution_run_id="")
        with self.assertRaises(nd.DecisionValidationError):
            m8c_binding(evaluation_id="")
        with self.assertRaises(nd.DecisionValidationError):
            m8c_binding(evaluated_at="")

    def test_authority_class_structural_validation_only(self) -> None:
        # valid class constructs fine - this is NOT the same as granting admissibility
        b = m8c_binding(authority_class="ACCEPTANCE")
        self.assertEqual(b.authority_class, "ACCEPTANCE")


# C. BINDING FINGERPRINT

class BindingFingerprintTests(unittest.TestCase):
    def test_26_deterministic_for_equal_semantic_binding(self) -> None:
        a = m8c_binding()
        b = m8c_binding()
        self.assertEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_27_predicate_result_fingerprint_change_changes_it(self) -> None:
        other_result = requirement("P1", "FALSE")
        a = m8c_binding()
        b = m8c_binding(predicate_result_fingerprint=other_result.result_fingerprint)
        self.assertNotEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_28_snapshot_fingerprint_change_changes_it(self) -> None:
        other_snapshot = m8c_snapshot(subject=m8c_subject(revision_ref=revision("rev-2")))
        a = m8c_binding()
        b = m8c_binding(snapshot_fingerprint=other_snapshot.snapshot_fingerprint)
        self.assertNotEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_29_policy_id_change_changes_it(self) -> None:
        a = m8c_binding()
        b = m8c_binding(policy_id="other-policy")
        self.assertNotEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_30_policy_version_change_changes_it(self) -> None:
        a = m8c_binding()
        b = m8c_binding(policy_version="2")
        self.assertNotEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_31_evidence_refs_change_changes_it(self) -> None:
        a = m8c_binding()
        b = m8c_binding(evidence_refs=(evidence_ref(ref_id="other-ev"),))
        self.assertNotEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_32_verifier_id_change_does_not_change_it(self) -> None:
        a = m8c_binding(verifier_id="verifier-x")
        b = m8c_binding(verifier_id="verifier-y")
        self.assertEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_33_authority_class_change_does_not_change_it(self) -> None:
        a = m8c_binding(authority_class=None)
        b = m8c_binding(authority_class="ACCEPTANCE")
        self.assertEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_34_execution_run_id_change_does_not_change_it(self) -> None:
        a = m8c_binding(execution_run_id="run-1")
        b = m8c_binding(execution_run_id="run-2")
        self.assertEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_35_evaluation_id_change_does_not_change_it(self) -> None:
        a = m8c_binding(evaluation_id="eval-1")
        b = m8c_binding(evaluation_id="eval-2")
        self.assertEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_36_evaluated_at_change_does_not_change_it(self) -> None:
        a = m8c_binding(evaluated_at="2026-01-01T00:00:00Z")
        b = m8c_binding(evaluated_at="2030-01-01T00:00:00Z")
        self.assertEqual(a.binding_fingerprint, b.binding_fingerprint)

    def test_binding_semantic_payload_contains_exactly_five_fields(self) -> None:
        payload = m8c_binding().semantic_payload()
        self.assertEqual(set(payload), {
            "predicate_result_fingerprint", "snapshot_fingerprint", "policy_id", "policy_version", "evidence_refs",
        })


# D. CLAIM SUBSTITUTION DEFENSE

class ClaimSubstitutionDefenseTests(unittest.TestCase):
    def test_37_true_binding_against_false_result_fails_closed(self) -> None:
        true_result = requirement("P1", "TRUE")
        false_result = requirement("P1", "FALSE")
        b = m8c_binding(predicate_result_fingerprint=true_result.result_fingerprint)
        result = m8c_admit(b, predicate_result=false_result)
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "INPUT_INVALID")

    def test_38_false_binding_against_true_result_fails_closed(self) -> None:
        false_result = requirement("P1", "FALSE")
        true_result = requirement("P1", "TRUE")
        b = m8c_binding(predicate_result_fingerprint=false_result.result_fingerprint, evidence_refs=(M8C_EVIDENCE,))
        result = m8c_admit(b, predicate_result=true_result)
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "INPUT_INVALID")

    def test_39_unknown_binding_against_true_result_fails_closed(self) -> None:
        unknown_result = requirement("P1", "UNKNOWN")
        true_result = requirement("P1", "TRUE")
        b = m8c_binding(predicate_result_fingerprint=unknown_result.result_fingerprint, evidence_refs=())
        result = m8c_admit(b, predicate_result=true_result)
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "INPUT_INVALID")

    def test_40_role_substitution_fails_closed(self) -> None:
        requirement_result = requirement("P1", "TRUE")
        violation_result = violation("P1", "TRUE")
        b = m8c_binding(predicate_result_fingerprint=requirement_result.result_fingerprint)
        result = m8c_admit(b, predicate_result=violation_result)
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "INPUT_INVALID")

    def test_41_predicate_id_substitution_fails_closed(self) -> None:
        p1_result = requirement("P1", "TRUE")
        p2_result = requirement("P2", "TRUE")
        b = m8c_binding(predicate_result_fingerprint=p1_result.result_fingerprint)
        result = m8c_admit(b, predicate_result=p2_result, current_policy=policy(required_ids=("P2",)))
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "INPUT_INVALID")


# E. SNAPSHOT / POLICY REPLAY DEFENSE

class SnapshotPolicyReplayDefenseTests(unittest.TestCase):
    def test_42_correct_snapshot_passes_binding_check(self) -> None:
        result = m8c_admit(m8c_binding())
        self.assertTrue(result.admissible)

    def test_43_wrong_snapshot_fails_stale_required_evidence(self) -> None:
        other_snapshot = m8c_snapshot(subject=m8c_subject(revision_ref=revision("rev-2")))
        result = m8c_admit(m8c_binding(), current_snapshot=other_snapshot)
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "STALE_REQUIRED_EVIDENCE")

    def test_44_old_revision_binding_replay_fails_closed(self) -> None:
        snap_a = m8c_snapshot(subject=m8c_subject(revision_ref=revision("rev-A")))
        snap_b = m8c_snapshot(subject=m8c_subject(revision_ref=revision("rev-B")))
        self.assertNotEqual(snap_a.snapshot_fingerprint, snap_b.snapshot_fingerprint)
        b = m8c_binding(snapshot_fingerprint=snap_a.snapshot_fingerprint)
        result = m8c_admit(b, current_snapshot=snap_b)
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "STALE_REQUIRED_EVIDENCE")

    def test_45_correct_policy_id_version_passes(self) -> None:
        result = m8c_admit(m8c_binding())
        self.assertTrue(result.admissible)

    def test_46_wrong_policy_id_fails(self) -> None:
        other_policy = policy(policy_id="other-policy", required_ids=("P1",))
        result = m8c_admit(m8c_binding(), current_policy=other_policy)
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "DECISION_POLICY_INVALID")

    def test_47_wrong_policy_version_fails(self) -> None:
        other_policy = policy(policy_version="2", required_ids=("P1",))
        result = m8c_admit(m8c_binding(), current_policy=other_policy)
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "DECISION_POLICY_INVALID")


# F. EVIDENCE REQUIREMENTS

class EvidenceRequirementTests(unittest.TestCase):
    def test_48_true_plus_empty_evidence_inadmissible(self) -> None:
        true_result = requirement("P1", "TRUE")
        b = m8c_binding(predicate_result_fingerprint=true_result.result_fingerprint, evidence_refs=())
        result = m8c_admit(b, predicate_result=true_result)
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "MISSING_REQUIRED_EVIDENCE")

    def test_49_false_plus_empty_evidence_inadmissible(self) -> None:
        false_result = requirement("P1", "FALSE")
        b = m8c_binding(predicate_result_fingerprint=false_result.result_fingerprint, evidence_refs=())
        result = m8c_admit(b, predicate_result=false_result)
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "MISSING_REQUIRED_EVIDENCE")

    def test_50_unknown_plus_empty_evidence_may_be_admissible(self) -> None:
        unknown_result = requirement("P1", "UNKNOWN")
        b = m8c_binding(predicate_result_fingerprint=unknown_result.result_fingerprint, evidence_refs=())
        result = m8c_admit(b, predicate_result=unknown_result)
        self.assertTrue(result.admissible)

    def test_51_actual_evidence_ref_permits_true_false_to_proceed(self) -> None:
        false_result = requirement("P1", "FALSE")
        b = m8c_binding(predicate_result_fingerprint=false_result.result_fingerprint, evidence_refs=(M8C_EVIDENCE,))
        result = m8c_admit(b, predicate_result=false_result)
        self.assertTrue(result.admissible)


# G. AUTHORITY INDEPENDENCE

class AuthorityIndependenceTests(unittest.TestCase):
    def test_52_independent_verifier_for_acceptance_critical_predicate_may_proceed(self) -> None:
        b = m8c_binding(verifier_id="independent-verifier")
        result = m8c_admit(b, executor_ids=frozenset({"executor-1"}))
        self.assertTrue(result.admissible)

    def test_53_verifier_equals_executor_identity_invalid_authority(self) -> None:
        b = m8c_binding(verifier_id="executor-1")
        result = m8c_admit(b, executor_ids=frozenset({"executor-1"}))
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "INVALID_AUTHORITY")

    def test_54_authority_class_acceptance_cannot_override_self_verification(self) -> None:
        b = m8c_binding(verifier_id="executor-1", authority_class="ACCEPTANCE")
        result = m8c_admit(b, executor_ids=frozenset({"executor-1"}))
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "INVALID_AUTHORITY")

    def test_55_authority_class_human_cannot_override_self_verification(self) -> None:
        b = m8c_binding(verifier_id="executor-1", authority_class="HUMAN")
        result = m8c_admit(b, executor_ids=frozenset({"executor-1"}))
        self.assertFalse(result.admissible)
        self.assertEqual(result.reason_code, "INVALID_AUTHORITY")

    def test_56_non_acceptance_critical_predicate_independence_not_enforced(self) -> None:
        # documented, designed behavior: check 6 only applies when the
        # predicate_id is required/blocking under current_policy - an
        # OPTIONAL predicate has no independence requirement in this design.
        optional_result = requirement("P_OPT", "TRUE")
        b = m8c_binding(predicate_result_fingerprint=optional_result.result_fingerprint, verifier_id="executor-1")
        optional_policy = policy(optional_ids=("P_OPT",))
        result = m8c_admit(b, predicate_result=optional_result, current_policy=optional_policy, executor_ids=frozenset({"executor-1"}))
        self.assertTrue(result.admissible)


# H. FAIL-CLOSED / NON-REGRESSION

class M8CFailClosedNonRegressionTests(unittest.TestCase):
    def test_57_invalid_binding_never_mutates_truth_value(self) -> None:
        true_result = requirement("P1", "TRUE")
        false_result = requirement("P1", "FALSE")
        b = m8c_binding(predicate_result_fingerprint=true_result.result_fingerprint)
        m8c_admit(b, predicate_result=false_result)
        self.assertEqual(false_result.truth_value, "FALSE")
        self.assertEqual(true_result.truth_value, "TRUE")

    def test_58_invalid_binding_never_becomes_unknown_automatically(self) -> None:
        # is_binding_admissible() returns AdmissibilityResult, never a
        # DecisionPredicateResult - there is no code path anywhere by which
        # an inadmissible binding could synthesize an UNKNOWN truth value.
        result = m8c_admit(m8c_binding(), current_snapshot=m8c_snapshot(subject=m8c_subject(revision_ref=revision("other"))))
        self.assertFalse(result.admissible)
        self.assertFalse(hasattr(result, "truth_value"))

    def test_59_no_multi_evaluation_resolver_exists(self) -> None:
        self.assertFalse(hasattr(nd, "resolve_predicate_truth"))

    def test_60_existing_duplicate_predicate_id_behavior_still_raises(self) -> None:
        dup = [requirement("P1", "TRUE"), requirement("P1", "TRUE")]
        with self.assertRaises(nd.DecisionValidationError):
            nd.derive_contract_verdict(dup, policy_contract=policy(required_ids=("P1",)))

    def test_61_decision_truth_values_unchanged(self) -> None:
        self.assertEqual(nd.DECISION_TRUTH_VALUES, frozenset({"TRUE", "FALSE", "UNKNOWN", "CONFLICT"}))

    def test_62_decision_verdicts_unchanged(self) -> None:
        self.assertEqual(nd.DECISION_VERDICTS, frozenset({"ACCEPT", "REJECT", "ABSTAIN"}))

    def test_63_existing_decision_predicate_result_validations_unchanged(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            requirement("P1", "TRUE", freshness_status="STALE")  # S4 still enforced
        with self.assertRaises(nd.DecisionValidationError):
            requirement("", "TRUE")  # empty predicate_id still rejected

    def test_64_derive_contract_verdict_existing_behavior_unchanged(self) -> None:
        result = nd.derive_contract_verdict(complete_proof_predicates(), policy_contract=COMPLETE_PROOF_POLICY)
        self.assertEqual(result.verdict, "ACCEPT")

    def test_65_m8b_snapshot_construction_unaffected(self) -> None:
        snap = m8c_snapshot()
        self.assertEqual(len(snap.snapshot_fingerprint), 64)

    def test_66_no_authority_class_permission_shortcut_exists(self) -> None:
        import inspect
        source = inspect.getsource(nd.is_binding_admissible)
        self.assertNotIn("authority_class ==", source)
        self.assertNotIn(".authority_class", source)


# --- M8-C static safety sweep ----------------------------------------------------------

class M8CStaticSafetySweepTests(unittest.TestCase):
    def test_no_second_hash_or_canonicalizer_implementation(self) -> None:
        import inspect
        source = inspect.getsource(nd)
        self.assertEqual(source.count("def fingerprint_payload"), 1)
        self.assertEqual(source.count("def canonical_json"), 1)
        self.assertEqual(source.count("def _canonicalize"), 1)
        self.assertEqual(source.count("def _deep_freeze"), 1)

    def test_no_second_evidence_reference_type(self) -> None:
        self.assertFalse(hasattr(nd, "EvidenceReference"))

    def test_no_m6_m7_imports_introduced(self) -> None:
        import ast
        tree = ast.parse(Path(nd.__file__).read_text(encoding="utf-8"))
        project_modules = {p.stem for p in (ROOT / "scripts").glob("*.py")} - {"nogap_decision"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertTrue(imported.isdisjoint(project_modules), f"found forbidden project imports: {imported & project_modules}")

    def test_no_nondeterminism_tokens_in_new_surface(self) -> None:
        import inspect
        source = inspect.getsource(nd.PredicateEvidenceBinding) + inspect.getsource(nd.is_binding_admissible) + inspect.getsource(nd.AdmissibilityResult)
        for banned in ("random.", "uuid.", "time.time(", "datetime.now(", "hash("):
            self.assertNotIn(banned, source)

    def test_is_binding_admissible_is_pure_no_io(self) -> None:
        import inspect
        source = inspect.getsource(nd.is_binding_admissible)
        for banned in ("open(", "Path(", "os.listdir", "iterdir", "glob("):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
