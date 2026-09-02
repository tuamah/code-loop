#!/usr/bin/env python3
"""M8-B: Immutable Decision Snapshot - regression suite.

Covers SnapshotReference, DecisionSubject, DecisionSnapshot,
build_decision_snapshot(), fingerprint_payload(), the 12 mandatory
scenarios, the 20 required property tests, and adversarial attacks A-J from
the M8-B review brief. Like tests/test_decision_contracts.py, this file
tests CONTRACTS ONLY - no filesystem, Git, methodology, or CLI dependency
anywhere except sys.path setup and the plain sys/hashlib/itertools/
dataclasses stdlib used to build fixtures.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap_decision as nd  # noqa: E402


# --- shared builders ---------------------------------------------------------------

def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def revision(seed: str) -> str:
    return digest(seed)[:40]  # 40-hex, matches the SHA-1-shaped Git revision contract


def scope(**overrides) -> nd.DecisionScope:
    fields = dict(scope_type="TASK", scope_id="TASK-17", project_id="proj-1")
    fields.update(overrides)
    return nd.DecisionScope(**fields)


def subject(**overrides) -> nd.DecisionSubject:
    fields = dict(subject_type="TASK", subject_id="TASK-17", project_id="proj-1", revision_ref=revision("rev-1"))
    fields.update(overrides)
    return nd.DecisionSubject(**fields)


def ref(ref_kind: str = "VERIFICATION_EVIDENCE", ref_id: str = "v1", fingerprint: str | None = None, **overrides) -> nd.SnapshotReference:
    fields = dict(ref_kind=ref_kind, ref_id=ref_id, fingerprint=fingerprint or digest(f"{ref_kind}:{ref_id}"))
    fields.update(overrides)
    return nd.SnapshotReference(**fields)


def policy_ref(**overrides) -> nd.SnapshotReference:
    return ref(ref_kind="POLICY", ref_id="policy-1", **overrides)


def snapshot(**overrides) -> nd.DecisionSnapshot:
    fields = dict(request_id="req-1", decision_type="TASK_ACCEPTANCE", scope=scope(), subject=subject(), policy_ref=policy_ref())
    fields.update(overrides)
    return nd.build_decision_snapshot(**fields)


def full_snapshot(**overrides) -> nd.DecisionSnapshot:
    """A snapshot with at least one reference in every category, useful for
    change-sensitivity sweeps."""
    fields = dict(
        request_id="req-1", decision_type="TASK_ACCEPTANCE", scope=scope(), subject=subject(),
        policy_ref=policy_ref(),
        methodology_ref=ref(ref_kind="METHODOLOGY", ref_id="methodology-1"),
        requirement_refs=[ref(ref_kind="REQUIREMENT", ref_id="req-a")],
        gate_refs=[ref(ref_kind="GATE", ref_id="gate-0001")],
        execution_evidence_refs=[ref(ref_kind="EXECUTION_EVIDENCE", ref_id="exec-1")],
        verification_evidence_refs=[ref(ref_kind="VERIFICATION_EVIDENCE", ref_id="ver-1")],
        review_refs=[ref(ref_kind="REVIEW", ref_id="review-1")],
        failure_refs=[ref(ref_kind="FAILURE", ref_id="failure-1")],
        research_refs=[ref(ref_kind="RESEARCH", ref_id="research-1")],
        release_refs=[ref(ref_kind="RELEASE", ref_id="release-1")],
        captured_at="2026-09-02T00:00:00Z",
    )
    fields.update(overrides)
    return nd.build_decision_snapshot(**fields)


# --- SnapshotReferenceTests ----------------------------------------------------------

class SnapshotReferenceTests(unittest.TestCase):
    def test_valid_reference_constructs(self) -> None:
        r = ref()
        self.assertEqual(r.ref_kind, "VERIFICATION_EVIDENCE")

    def test_unknown_ref_kind_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ref(ref_kind="SPECULATIVE")

    def test_empty_ref_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ref(ref_id="")

    def test_malformed_fingerprint_rejected_too_short(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ref(fingerprint="ab12")

    def test_malformed_fingerprint_rejected_uppercase(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ref(fingerprint="A" * 64)

    def test_malformed_fingerprint_rejected_non_hex(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ref(fingerprint="z" * 64)

    def test_truncated_fingerprint_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ref(fingerprint=digest("x")[:63])

    def test_locator_is_optional_and_non_authoritative(self) -> None:
        r = ref(locator=".code-loop/runtime/verification/v-17.json")
        self.assertEqual(r.locator, ".code-loop/runtime/verification/v-17.json")

    def test_empty_locator_rejected_when_provided(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ref(locator="")

    def test_identity_key_is_kind_and_id_only(self) -> None:
        r = ref(ref_id="v1", fingerprint=digest("a"))
        self.assertEqual(r.identity_key(), ("VERIFICATION_EVIDENCE", "v1"))

    def test_reference_is_immutable(self) -> None:
        r = ref()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.fingerprint = digest("other")

    def test_no_hash_of_ref_id_only_shortcut_exists(self) -> None:
        # There is no helper that fabricates a fingerprint FROM a ref_id -
        # fingerprint is always caller-supplied; hashing "verification-17"
        # itself would only prove a name was hashed, never that content was
        # inspected.
        self.assertFalse(hasattr(nd, "fingerprint_ref_id"))
        self.assertFalse(hasattr(nd, "hash_ref_id"))


# --- DecisionSubjectTests -------------------------------------------------------------

class DecisionSubjectTests(unittest.TestCase):
    def test_valid_subject_constructs(self) -> None:
        s = subject()
        self.assertEqual(s.subject_type, "TASK")

    def test_unknown_subject_type_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            subject(subject_type="RELEASE_CANDIDATE")

    def test_empty_subject_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            subject(subject_id="")

    # Mandatory Scenario 8 / adversarial: branch name is not a revision.
    def test_branch_name_rejected_as_revision(self) -> None:
        for bad in ("main", "architecture/m8-decision-engine", "HEAD", "master", ""):
            with self.assertRaises(nd.DecisionValidationError):
                subject(revision_ref=bad)

    def test_short_sha_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            subject(revision_ref=revision("rev-1")[:7])  # a typical abbreviated SHA

    def test_full_sha1_length_revision_accepted(self) -> None:
        s = subject(revision_ref=revision("rev-1"))
        self.assertEqual(len(s.revision_ref), 40)

    def test_full_sha256_length_revision_accepted(self) -> None:
        s = subject(revision_ref=digest("rev-1"))  # 64-hex
        self.assertEqual(len(s.revision_ref), 64)

    def test_uppercase_revision_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            subject(revision_ref=revision("rev-1").upper())

    def test_candidate_fingerprint_optional(self) -> None:
        s = subject(candidate_fingerprint=None)
        self.assertIsNone(s.candidate_fingerprint)

    def test_candidate_fingerprint_validated_when_present(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            subject(candidate_fingerprint="not-a-digest")

    def test_candidate_fingerprint_accepts_valid_digest_verbatim(self) -> None:
        # M8-B never recomputes this - it is exactly whatever
        # nogap_lifecycle.compute_candidate_fingerprint() already produced.
        s = subject(candidate_fingerprint=digest("candidate-material"))
        self.assertEqual(s.candidate_fingerprint, digest("candidate-material"))

    def test_artifact_refs_must_be_artifact_kind(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            subject(artifact_refs=[ref(ref_kind="VERIFICATION_EVIDENCE", ref_id="not-an-artifact")])

    def test_artifact_refs_duplicate_fails_closed(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            subject(artifact_refs=[
                ref(ref_kind="ARTIFACT", ref_id="a1", fingerprint=digest("v1")),
                ref(ref_kind="ARTIFACT", ref_id="a1", fingerprint=digest("v2")),
            ])

    def test_canonical_id_deterministic(self) -> None:
        s1 = subject()
        s2 = subject()
        self.assertEqual(s1.canonical_id(), s2.canonical_id())
        self.assertIn(s1.revision_ref, s1.canonical_id())

    def test_subject_is_immutable(self) -> None:
        s = subject()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            s.revision_ref = revision("other")

    def test_subject_mutable_input_list_does_not_leak(self) -> None:
        artifact_list = [ref(ref_kind="ARTIFACT", ref_id="a1")]
        s = subject(artifact_refs=artifact_list)
        artifact_list.append(ref(ref_kind="ARTIFACT", ref_id="a2"))
        self.assertEqual(len(s.artifact_refs), 1)


# --- ReferenceSetValidationTests ------------------------------------------------------

class ReferenceSetValidationTests(unittest.TestCase):
    def test_wrong_kind_in_typed_collection_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(gate_refs=[ref(ref_kind="REVIEW", ref_id="not-a-gate")])

    # Mandatory Scenario 6: duplicate id, different fingerprint -> fail closed.
    def test_scenario_6_duplicate_id_different_fingerprint_fails_closed(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(verification_evidence_refs=[
                ref(ref_id="v1", fingerprint=digest("content-A")),
                ref(ref_id="v1", fingerprint=digest("content-B")),
            ])

    def test_duplicate_id_same_fingerprint_also_fails_closed(self) -> None:
        # Never silently deduplicated, even when the fingerprints agree.
        same = ref(ref_id="v1", fingerprint=digest("content-A"))
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(verification_evidence_refs=[same, ref(ref_id="v1", fingerprint=digest("content-A"))])

    def test_different_kinds_may_reuse_same_ref_id(self) -> None:
        # Cross-kind identity: ref_kind + ref_id + fingerprint together, not
        # ref_id alone - a GATE and a REVIEW may legitimately share "v1".
        s = snapshot(
            gate_refs=[ref(ref_kind="GATE", ref_id="v1", fingerprint=digest("gate-content"))],
            review_refs=[ref(ref_kind="REVIEW", ref_id="v1", fingerprint=digest("review-content"))],
        )
        self.assertEqual(len(s.gate_refs), 1)
        self.assertEqual(len(s.review_refs), 1)

    def test_non_reference_entry_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(verification_evidence_refs=[{"ref_kind": "VERIFICATION_EVIDENCE", "ref_id": "v1"}])

    def test_not_a_collection_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.DecisionSnapshot(
                request_id="r1", decision_type="TASK_ACCEPTANCE", scope=scope(), subject=subject(),
                policy_ref=policy_ref(), verification_evidence_refs="not-a-list",
            )


# --- DecisionSnapshotContractTests ----------------------------------------------------

class DecisionSnapshotContractTests(unittest.TestCase):
    def test_valid_snapshot_constructs(self) -> None:
        snap = snapshot()
        self.assertEqual(snap.decision_type, "TASK_ACCEPTANCE")

    def test_empty_request_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(request_id="")

    def test_unknown_decision_type_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(decision_type="RESEARCH_OUTCOME")

    def test_scope_must_be_decision_scope(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(scope={"scope_type": "TASK"})

    def test_subject_must_be_decision_subject(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(subject={"subject_type": "TASK"})

    def test_subject_outside_scope_project_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(subject=subject(project_id="other-project"))

    def test_subject_outside_scope_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(subject=subject(subject_id="TASK-99"))

    def test_subject_outside_scope_type_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(scope=scope(scope_type="TASK"), subject=subject(subject_type="REPAIR", subject_id="TASK-17"))

    def test_policy_ref_must_be_policy_kind(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(policy_ref=ref(ref_kind="GATE", ref_id="not-a-policy"))

    def test_methodology_ref_optional(self) -> None:
        snap = snapshot(methodology_ref=None)
        self.assertIsNone(snap.methodology_ref)

    def test_methodology_ref_must_be_methodology_kind(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(methodology_ref=ref(ref_kind="GATE", ref_id="not-methodology"))

    def test_metadata_must_be_json_compatible(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(metadata={"bad": object()})

    def test_unsupported_schema_version_rejected(self) -> None:
        # schema_version/engine_version are not exposed on the pure builder
        # (they default from the module-wide constants) - construct the
        # contract directly to exercise this validation.
        with self.assertRaises(nd.DecisionValidationError):
            nd.DecisionSnapshot(request_id="r1", decision_type="TASK_ACCEPTANCE", scope=scope(), subject=subject(),
                                 policy_ref=policy_ref(), schema_version="99")

    def test_unsupported_engine_version_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.DecisionSnapshot(request_id="r1", decision_type="TASK_ACCEPTANCE", scope=scope(), subject=subject(),
                                 policy_ref=policy_ref(), engine_version="99")

    def test_snapshot_is_immutable(self) -> None:
        snap = snapshot()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snap.request_id = "changed"

    # Principle 6: no verdict-shaped field exists anywhere on the class.
    def test_no_verdict_field_exists(self) -> None:
        field_names = {f.name for f in dataclasses.fields(nd.DecisionSnapshot)}
        for banned in ("verdict", "requested_verdict", "accept", "reject", "abstain", "confidence", "score", "vote"):
            self.assertNotIn(banned, field_names)

    def test_no_verdict_field_on_snapshot_reference(self) -> None:
        field_names = {f.name for f in dataclasses.fields(nd.SnapshotReference)}
        for banned in ("verdict", "requested_verdict", "confidence", "score", "vote"):
            self.assertNotIn(banned, field_names)

    def test_no_verdict_deriving_method_on_snapshot(self) -> None:
        for banned in ("verdict", "derive_verdict", "accept", "to_verdict", "evaluate"):
            self.assertFalse(hasattr(nd.DecisionSnapshot, banned), f"DecisionSnapshot must not expose {banned}()")


# --- FingerprintFormulaTests -----------------------------------------------------------

class FingerprintFormulaTests(unittest.TestCase):
    def test_snapshot_fingerprint_is_valid_digest_shape(self) -> None:
        import re
        self.assertTrue(re.match(r"^[0-9a-f]{64}$", snapshot().snapshot_fingerprint))

    def test_fingerprint_payload_matches_manual_sha256(self) -> None:
        payload = {"a": 1, "b": [3, 2, 1]}
        expected = hashlib.sha256(nd.canonical_json(payload).encode("utf-8")).hexdigest()
        self.assertEqual(nd.fingerprint_payload(payload), expected)

    def test_semantic_payload_excludes_non_semantic_fields(self) -> None:
        payload = full_snapshot().semantic_payload()
        for excluded in ("request_id", "captured_at", "metadata", "snapshot_id"):
            self.assertNotIn(excluded, payload)

    def test_semantic_payload_includes_required_fields(self) -> None:
        payload = full_snapshot().semantic_payload()
        for included in ("schema_version", "engine_version", "decision_type", "scope", "subject", "policy_ref",
                          "methodology_ref", "requirement_refs", "gate_refs", "execution_evidence_refs",
                          "verification_evidence_refs", "review_refs", "failure_refs", "research_refs", "release_refs"):
            self.assertIn(included, payload)

    def test_reused_canonical_json_not_a_second_canonicalizer(self) -> None:
        # snapshot_fingerprint must be expressible purely via canonical_json();
        # there is no separate/competing serialization path.
        snap = snapshot()
        expected = hashlib.sha256(nd.canonical_json(snap.semantic_payload()).encode("utf-8")).hexdigest()
        self.assertEqual(snap.snapshot_fingerprint, expected)


# --- ReplayDeterminismTests (Mandatory Scenarios 1, 5, 12; properties 1-2, 9) ----------

class ReplayDeterminismTests(unittest.TestCase):
    # Mandatory Scenario 1: same semantic input, different captured_at.
    def test_scenario_1_same_state_different_captured_at_same_fingerprint(self) -> None:
        snap1 = snapshot(captured_at="2026-09-02T00:00:00Z")
        snap2 = snapshot(captured_at="2026-09-02T01:00:00Z")
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    # Property 2: timestamp invariance, explicit.
    def test_property_2_timestamp_invariance(self) -> None:
        snap1 = full_snapshot(captured_at="t1")
        snap2 = full_snapshot(captured_at="t2")
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_request_id_does_not_affect_fingerprint(self) -> None:
        snap1 = full_snapshot(request_id="req-A")
        snap2 = full_snapshot(request_id="req-B")
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    # Mandatory Scenario 5 / Property 1: order independence.
    def test_scenario_5_property_1_reference_order_independence(self) -> None:
        refs_forward = [ref(ref_id=f"v{i}") for i in range(4)]
        refs_backward = list(reversed(refs_forward))
        snap1 = snapshot(verification_evidence_refs=refs_forward)
        snap2 = snapshot(verification_evidence_refs=refs_backward)
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_full_permutation_sweep_order_independence(self) -> None:
        base_refs = [ref(ref_id=f"v{i}") for i in range(4)]
        fingerprints = set()
        for perm in itertools.permutations(base_refs):
            snap = snapshot(verification_evidence_refs=list(perm))
            fingerprints.add(snap.snapshot_fingerprint)
        self.assertEqual(len(fingerprints), 1)

    # Property 9: canonical serialization stability across independently-
    # constructed-but-semantically-equal snapshots.
    def test_property_9_canonical_stability_across_independent_construction(self) -> None:
        snap1 = full_snapshot()
        snap2 = full_snapshot()  # independently built, same semantic content
        self.assertEqual(nd.canonical_json(snap1.semantic_payload()), nd.canonical_json(snap2.semantic_payload()))

    # Mandatory Scenario 12: canonical roundtrip determinism.
    def test_scenario_12_canonical_roundtrip_deterministic(self) -> None:
        snap = full_snapshot()
        fp1 = nd.fingerprint_payload(snap.semantic_payload())
        fp2 = nd.fingerprint_payload(snap.semantic_payload())
        self.assertEqual(fp1, fp2)
        self.assertEqual(fp1, snap.snapshot_fingerprint)


# --- ChangeSensitivityTests (Mandatory Scenarios 2-4, property 3, 17-18) ---------------

class ChangeSensitivityTests(unittest.TestCase):
    # Mandatory Scenario 2: revision drift.
    def test_scenario_2_revision_drift_changes_fingerprint(self) -> None:
        snap1 = snapshot()
        snap2 = snapshot(subject=subject(revision_ref=revision("rev-2")))
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    # Mandatory Scenario 3: policy drift (same id/version, different content fingerprint).
    def test_scenario_3_policy_content_drift_changes_fingerprint(self) -> None:
        snap1 = snapshot(policy_ref=ref(ref_kind="POLICY", ref_id="policy-1", fingerprint=digest("policy-v1")))
        snap2 = snapshot(policy_ref=ref(ref_kind="POLICY", ref_id="policy-1", fingerprint=digest("policy-v2")))
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    # Property 17: policy name alone (same ref_id) is not sufficient identity -
    # only fingerprint drift, proven above, actually changes anything; same
    # id+fingerprint must NOT drift.
    def test_property_17_same_policy_identity_same_fingerprint_contributes_same(self) -> None:
        p = ref(ref_kind="POLICY", ref_id="policy-1", fingerprint=digest("policy-v1"))
        snap1 = snapshot(policy_ref=p)
        snap2 = snapshot(policy_ref=ref(ref_kind="POLICY", ref_id="policy-1", fingerprint=digest("policy-v1")))
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    # Mandatory Scenario 4: verification drift (same ref id, different fingerprint).
    def test_scenario_4_verification_content_drift_changes_fingerprint(self) -> None:
        snap1 = snapshot(verification_evidence_refs=[ref(ref_id="v1", fingerprint=digest("content-A"))])
        snap2 = snapshot(verification_evidence_refs=[ref(ref_id="v1", fingerprint=digest("content-B"))])
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_decision_type_change_changes_fingerprint(self) -> None:
        snap1 = snapshot(decision_type="TASK_ACCEPTANCE")
        snap2 = snapshot(decision_type="REPAIR_ACCEPTANCE", scope=scope(scope_type="REPAIR"), subject=subject(subject_type="REPAIR"))
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_scope_id_change_changes_fingerprint(self) -> None:
        snap1 = snapshot()
        snap2 = snapshot(scope=scope(scope_id="TASK-18"), subject=subject(subject_id="TASK-18"))
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_project_id_change_changes_fingerprint(self) -> None:
        snap1 = snapshot()
        snap2 = snapshot(scope=scope(project_id="proj-2"), subject=subject(project_id="proj-2"))
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    # Property 18: artifact identity changes fingerprint.
    def test_property_18_artifact_fingerprint_change_changes_snapshot_fingerprint(self) -> None:
        snap1 = snapshot(subject=subject(artifact_refs=[ref(ref_kind="ARTIFACT", ref_id="a1", fingerprint=digest("art-v1"))]))
        snap2 = snapshot(subject=subject(artifact_refs=[ref(ref_kind="ARTIFACT", ref_id="a1", fingerprint=digest("art-v2"))]))
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_methodology_fingerprint_change_changes_snapshot_fingerprint(self) -> None:
        snap1 = snapshot(methodology_ref=ref(ref_kind="METHODOLOGY", ref_id="m1", fingerprint=digest("meth-v1")))
        snap2 = snapshot(methodology_ref=ref(ref_kind="METHODOLOGY", ref_id="m1", fingerprint=digest("meth-v2")))
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_requirement_fingerprint_change_changes_snapshot_fingerprint(self) -> None:
        snap1 = snapshot(requirement_refs=[ref(ref_kind="REQUIREMENT", ref_id="r1", fingerprint=digest("req-v1"))])
        snap2 = snapshot(requirement_refs=[ref(ref_kind="REQUIREMENT", ref_id="r1", fingerprint=digest("req-v2"))])
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_gate_fingerprint_change_changes_snapshot_fingerprint(self) -> None:
        snap1 = snapshot(gate_refs=[ref(ref_kind="GATE", ref_id="g1", fingerprint=digest("gate-v1"))])
        snap2 = snapshot(gate_refs=[ref(ref_kind="GATE", ref_id="g1", fingerprint=digest("gate-v2"))])
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_execution_evidence_fingerprint_change_changes_snapshot_fingerprint(self) -> None:
        snap1 = snapshot(execution_evidence_refs=[ref(ref_kind="EXECUTION_EVIDENCE", ref_id="e1", fingerprint=digest("exec-v1"))])
        snap2 = snapshot(execution_evidence_refs=[ref(ref_kind="EXECUTION_EVIDENCE", ref_id="e1", fingerprint=digest("exec-v2"))])
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_review_fingerprint_change_changes_snapshot_fingerprint(self) -> None:
        snap1 = snapshot(review_refs=[ref(ref_kind="REVIEW", ref_id="rv1", fingerprint=digest("review-v1"))])
        snap2 = snapshot(review_refs=[ref(ref_kind="REVIEW", ref_id="rv1", fingerprint=digest("review-v2"))])
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_failure_fingerprint_change_changes_snapshot_fingerprint(self) -> None:
        snap1 = snapshot(failure_refs=[ref(ref_kind="FAILURE", ref_id="f1", fingerprint=digest("failure-v1"))])
        snap2 = snapshot(failure_refs=[ref(ref_kind="FAILURE", ref_id="f1", fingerprint=digest("failure-v2"))])
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_release_fingerprint_change_changes_snapshot_fingerprint(self) -> None:
        snap1 = snapshot(release_refs=[ref(ref_kind="RELEASE", ref_id="rel1", fingerprint=digest("release-v1"))])
        snap2 = snapshot(release_refs=[ref(ref_kind="RELEASE", ref_id="rel1", fingerprint=digest("release-v2"))])
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)


# --- NonSemanticStabilityTests (property 4 partial, Mandatory scenario "G" adversarial) -

class NonSemanticStabilityTests(unittest.TestCase):
    def test_captured_at_does_not_affect_fingerprint(self) -> None:
        snap1 = full_snapshot(captured_at="2026-01-01T00:00:00Z")
        snap2 = full_snapshot(captured_at="2030-12-31T23:59:59Z")
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_metadata_does_not_affect_fingerprint(self) -> None:
        snap1 = full_snapshot(metadata={"note": "first pass"})
        snap2 = full_snapshot(metadata={"note": "totally different note"})
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_snapshot_id_does_not_affect_fingerprint(self) -> None:
        snap1 = full_snapshot(snapshot_id="snap-aaa")
        snap2 = full_snapshot(snapshot_id="snap-bbb")
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_locator_does_not_affect_fingerprint(self) -> None:
        # Mandatory Scenario 11 / attack A: locator replacement is not identity.
        snap1 = snapshot(verification_evidence_refs=[ref(ref_id="v1", locator="/path/one.json")])
        snap2 = snapshot(verification_evidence_refs=[ref(ref_id="v1", locator="/path/two.json")])
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)


# --- MutationResistanceTests (Mandatory Scenario 7, property 4) -----------------------

class MutationResistanceTests(unittest.TestCase):
    def test_scenario_7_mutable_metadata_input_does_not_leak(self) -> None:
        meta = {"note": "original"}
        snap = snapshot(metadata=meta)
        fp_before = snap.snapshot_fingerprint
        meta["note"] = "mutated after construction"
        meta["injected"] = "new key"
        self.assertEqual(snap.metadata, {"note": "original"})
        self.assertEqual(snap.snapshot_fingerprint, fp_before)

    def test_scenario_7_mutable_reference_list_input_does_not_leak(self) -> None:
        refs_list = [ref(ref_id="v1")]
        snap = snapshot(verification_evidence_refs=refs_list)
        fp_before = snap.snapshot_fingerprint
        refs_list.append(ref(ref_id="v2"))
        self.assertEqual(len(snap.verification_evidence_refs), 1)
        self.assertEqual(snap.snapshot_fingerprint, fp_before)

    def test_metadata_attribute_is_a_detached_copy_not_the_same_object(self) -> None:
        meta = {"note": "original"}
        snap = snapshot(metadata=meta)
        self.assertIsNot(snap.metadata, meta)


# --- RevisionBindingTests (Mandatory Scenario 8, attack C) -----------------------------

class RevisionBindingTests(unittest.TestCase):
    def test_scenario_8_branch_not_accepted_as_revision(self) -> None:
        for bad in ("main", "architecture/m8-decision-engine"):
            with self.assertRaises(nd.DecisionValidationError):
                subject(revision_ref=bad)

    # Attack C: branch moves to a new commit; old snapshot stays bound to old revision.
    def test_attack_c_branch_move_does_not_retroactively_change_old_snapshot(self) -> None:
        old_subject = subject(revision_ref=revision("commit-old"))
        snap_old = snapshot(subject=old_subject)
        fp_old = snap_old.snapshot_fingerprint
        # constructing a NEW snapshot at a new revision does not touch snap_old at all
        new_subject = subject(revision_ref=revision("commit-new"))
        snap_new = snapshot(subject=new_subject)
        self.assertEqual(snap_old.snapshot_fingerprint, fp_old)
        self.assertNotEqual(snap_old.snapshot_fingerprint, snap_new.snapshot_fingerprint)
        self.assertEqual(snap_old.subject.revision_ref, revision("commit-old"))


# --- PolicyBindingTests -----------------------------------------------------------------

class PolicyBindingTests(unittest.TestCase):
    def test_policy_ref_requires_fingerprint_not_just_id(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            nd.SnapshotReference(ref_kind="POLICY", ref_id="policy-1", fingerprint="not-a-real-fingerprint")

    def test_same_policy_id_different_content_is_different_identity(self) -> None:
        p1 = ref(ref_kind="POLICY", ref_id="policy-1", fingerprint=digest("content-v1"))
        p2 = ref(ref_kind="POLICY", ref_id="policy-1", fingerprint=digest("content-v2"))
        self.assertNotEqual(p1.fingerprint, p2.fingerprint)
        self.assertEqual(p1.identity_key(), p2.identity_key())  # same logical id...
        snap1, snap2 = snapshot(policy_ref=p1), snapshot(policy_ref=p2)
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)  # ...but different snapshot identity


# --- MethodologyBindingTests -------------------------------------------------------------

class MethodologyBindingTests(unittest.TestCase):
    def test_methodology_ref_is_optional_for_legacy_uninitialized_projects(self) -> None:
        snap = snapshot(methodology_ref=None)
        self.assertIsNone(snap.methodology_ref)

    def test_methodology_ref_captures_identity_only_no_current_phase_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(nd.SnapshotReference)}
        self.assertNotIn("current_phase", field_names)
        import inspect
        self.assertNotIn("current_phase", inspect.getsource(nd))

    def test_methodology_fingerprint_reusable_via_fingerprint_payload(self) -> None:
        # M8-B offers no dedicated "methodology fingerprint" owner - callers use
        # the same general fingerprint_payload() utility on whatever identity
        # tuple they choose (e.g. {"methodology_id":..., "methodology_version":...}).
        fp = nd.fingerprint_payload({"methodology_id": "nogap-v1", "methodology_version": "1.0.0"})
        m_ref = nd.SnapshotReference(ref_kind="METHODOLOGY", ref_id="nogap-v1", fingerprint=fp)
        self.assertEqual(m_ref.fingerprint, fp)


# --- GateBindingTests ---------------------------------------------------------------------

class GateBindingTests(unittest.TestCase):
    def test_gate_ref_representable_without_comparison(self) -> None:
        # M8-B only makes frozen vs. executed gate identity REPRESENTABLE; it
        # never compares them (that is M8-D/E/F). Two distinct GATE refs (e.g.
        # "gate-frozen" and "gate-executed") can coexist in gate_refs without
        # this module drawing any REJECT/ACCEPT conclusion from a mismatch.
        frozen = ref(ref_kind="GATE", ref_id="gate-frozen", fingerprint=digest("gate-content-A"))
        executed = ref(ref_kind="GATE", ref_id="gate-executed", fingerprint=digest("gate-content-B"))
        snap = snapshot(gate_refs=[frozen, executed])
        self.assertEqual(len(snap.gate_refs), 2)

    def test_no_gate_comparison_logic_in_module(self) -> None:
        # M8-B must not implement "if frozen_gate != executed_gate: REJECT" -
        # that comparison belongs to M8-D/E/F. Only representability is in
        # scope here (both gate identities can coexist as separate refs).
        import inspect
        source = inspect.getsource(nd)
        self.assertNotIn("frozen_gate", source)
        self.assertNotIn("executed_gate", source)
        self.assertNotIn('"GATE_TAMPERING" if', source)


# --- EvidenceBindingTests / namespace preservation (property 19) ----------------------

class EvidenceBindingTests(unittest.TestCase):
    def test_execution_and_verification_evidence_are_distinct_fields(self) -> None:
        field_names = {f.name for f in dataclasses.fields(nd.DecisionSnapshot)}
        self.assertIn("execution_evidence_refs", field_names)
        self.assertIn("verification_evidence_refs", field_names)

    def test_execution_evidence_cannot_be_placed_in_verification_field(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(verification_evidence_refs=[ref(ref_kind="EXECUTION_EVIDENCE", ref_id="e1")])

    # Property 19: evidence namespace preserved across review/research/failure/release too.
    def test_property_19_review_research_failure_release_remain_distinct(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(review_refs=[ref(ref_kind="RESEARCH", ref_id="x")])
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(research_refs=[ref(ref_kind="FAILURE", ref_id="x")])
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(failure_refs=[ref(ref_kind="RELEASE", ref_id="x")])
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(release_refs=[ref(ref_kind="REVIEW", ref_id="x")])


# --- EmptyAbsenceSemanticsTests (Mandatory Scenario 9, property 20) --------------------

class EmptyAbsenceSemanticsTests(unittest.TestCase):
    # Mandatory Scenario 9 / Property 20: empty category is structurally valid
    # and asserts nothing about completeness.
    def test_scenario_9_empty_verification_refs_structurally_valid(self) -> None:
        snap = snapshot(verification_evidence_refs=())
        self.assertEqual(snap.verification_evidence_refs, ())

    def test_property_20_empty_category_has_no_verdict_producing_side_effect(self) -> None:
        snap_empty = snapshot(failure_refs=())
        snap_with_failure = snapshot(failure_refs=[ref(ref_kind="FAILURE", ref_id="f1")])
        # Both are equally "just a snapshot" - neither one is closer to ACCEPT;
        # DecisionSnapshot has no verdict-producing method to even ask.
        for snap in (snap_empty, snap_with_failure):
            self.assertFalse(hasattr(snap, "verdict"))

    def test_empty_does_not_imply_verification_complete(self) -> None:
        # Documented, testable claim: zero verification refs means "zero were
        # captured", never "verification is complete" or "nothing failed".
        snap = snapshot(verification_evidence_refs=())
        self.assertEqual(len(snap.verification_evidence_refs), 0)
        self.assertFalse(hasattr(snap, "verification_complete"))
        self.assertFalse(hasattr(snap, "is_verified"))


# --- PureBuilderTests (properties 13-15) ------------------------------------------------

class PureBuilderTests(unittest.TestCase):
    def test_builder_requires_explicit_captured_at_no_implicit_clock(self) -> None:
        import inspect
        source = inspect.getsource(nd.build_decision_snapshot)
        for banned in ("datetime.now", "time.time", "utcnow"):
            self.assertNotIn(banned, source)

    def test_property_13_no_filesystem_dependence_in_snapshot_code(self) -> None:
        import inspect
        source = inspect.getsource(nd)
        for banned in ("open(", "os.listdir", "iterdir", "Path(", "glob("):
            self.assertNotIn(banned, source)

    def test_property_14_no_clock_dependence_in_pure_builder(self) -> None:
        import inspect
        source = inspect.getsource(nd.build_decision_snapshot) + inspect.getsource(nd.DecisionSnapshot)
        for banned in ("datetime.now(", "time.time(", "utcnow("):
            self.assertNotIn(banned, source)

    def test_property_15_no_random_dependence(self) -> None:
        import inspect
        source = inspect.getsource(nd)
        for banned in ("random.", "uuid.", "secrets."):
            self.assertNotIn(banned, source)

    def test_builder_produces_same_object_shape_as_direct_construction(self) -> None:
        s1 = nd.build_decision_snapshot(request_id="r1", decision_type="TASK_ACCEPTANCE", scope=scope(), subject=subject(), policy_ref=policy_ref())
        s2 = nd.DecisionSnapshot(request_id="r1", decision_type="TASK_ACCEPTANCE", scope=scope(), subject=subject(), policy_ref=policy_ref())
        self.assertEqual(s1.snapshot_fingerprint, s2.snapshot_fingerprint)

    def test_no_project_imports_in_module(self) -> None:
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


# --- AdversarialSnapshotTests (attacks A-J) --------------------------------------------

class AdversarialSnapshotTests(unittest.TestCase):
    # A: old verification file path reused with new content -> not the same identity.
    def test_attack_a_locator_reuse_with_new_content_is_different_identity(self) -> None:
        old = ref(ref_id="v1", fingerprint=digest("old-content"), locator="/same/path.json")
        new = ref(ref_id="v1", fingerprint=digest("new-content"), locator="/same/path.json")
        self.assertNotEqual(old.fingerprint, new.fingerprint)
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(verification_evidence_refs=[old, new])  # same ref_id, different fingerprint -> fail closed, not "the new one wins"

    # B: old policy ID reused after modification -> identity changes.
    def test_attack_b_policy_id_reuse_after_modification_changes_identity(self) -> None:
        snap1 = snapshot(policy_ref=ref(ref_kind="POLICY", ref_id="policy-1", fingerprint=digest("v1")))
        snap2 = snapshot(policy_ref=ref(ref_kind="POLICY", ref_id="policy-1", fingerprint=digest("v2")))
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    # C covered by RevisionBindingTests.test_attack_c_*

    # D: evidence list reordered maliciously -> no fingerprint change.
    def test_attack_d_malicious_reorder_no_fingerprint_change(self) -> None:
        a, b, c = ref(ref_id="v1"), ref(ref_id="v2"), ref(ref_id="v3")
        snap1 = snapshot(verification_evidence_refs=[a, b, c])
        snap2 = snapshot(verification_evidence_refs=[c, b, a])
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    # E: conflicting duplicate reference injected last -> fail closed regardless of position.
    def test_attack_e_conflicting_duplicate_injected_last_fails_closed(self) -> None:
        legit = [ref(ref_id="v1"), ref(ref_id="v2"), ref(ref_id="v3")]
        conflicting = ref(ref_id="v1", fingerprint=digest("malicious-alternate-content"))
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(verification_evidence_refs=legit + [conflicting])

    # F: mutable metadata altered after construction -> no snapshot mutation.
    def test_attack_f_mutable_metadata_altered_after_construction_no_mutation(self) -> None:
        meta = {"k": "v"}
        snap = snapshot(metadata=meta)
        meta["k"] = "attacker-controlled"
        meta["new"] = "injected"
        self.assertEqual(snap.metadata, {"k": "v"})

    # G: captured_at modified between otherwise-identical captures -> no semantic change.
    def test_attack_g_captured_at_modification_no_semantic_fingerprint_change(self) -> None:
        snap1 = full_snapshot(captured_at="2026-01-01T00:00:00Z")
        snap2 = full_snapshot(captured_at="2099-01-01T00:00:00Z")
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    # H: "PASS" text inserted in metadata -> cannot create a verdict; snapshot has none.
    def test_attack_h_pass_text_in_metadata_creates_no_verdict(self) -> None:
        snap = snapshot(metadata={"note": "PASS"})
        self.assertFalse(hasattr(snap, "verdict"))
        field_names = {f.name for f in dataclasses.fields(nd.DecisionSnapshot)}
        self.assertNotIn("verdict", field_names)

    # I: "ACCEPT" inserted in a display label -> cannot create DecisionVerdict.
    def test_attack_i_accept_text_in_snapshot_id_creates_no_verdict(self) -> None:
        snap = snapshot(snapshot_id="ACCEPT-this-please")
        self.assertFalse(hasattr(snap, "verdict"))
        # snapshot_id is non-semantic and excluded entirely from the payload
        # that gets hashed - its exact text never even reaches canonical_json.
        self.assertNotIn("ACCEPT-this-please", nd.canonical_json(snap.semantic_payload()))
        other = snapshot(snapshot_id="totally-different-label")
        self.assertEqual(snap.snapshot_fingerprint, other.snapshot_fingerprint)

    # J: one reference fingerprint malformed/truncated -> fail closed.
    def test_attack_j_malformed_fingerprint_fails_closed(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(verification_evidence_refs=[ref(fingerprint=digest("x")[:20])])


# --- MandatoryScenarioIndexTests (documents coverage of the 12 scenarios by name) -----

class MandatoryScenarioIndexTests(unittest.TestCase):
    """Scenarios 1, 2, 3, 4, 5, 7, 8, 9, 12 have dedicated tests above (by
    name, in ReplayDeterminismTests/ChangeSensitivityTests/
    MutationResistanceTests/RevisionBindingTests/EmptyAbsenceSemanticsTests).
    Scenario 6 is in ReferenceSetValidationTests. Scenarios 10 (model
    consensus irrelevance) and 11 (locator replacement) are covered here and
    in NonSemanticStabilityTests respectively."""

    # Mandatory Scenario 10: no model-vote-shaped field exists to even attempt
    # to change a verdict with - there is no verdict at the snapshot layer at all.
    def test_scenario_10_no_model_vote_field_exists(self) -> None:
        field_names = {f.name for f in dataclasses.fields(nd.DecisionSnapshot)}
        for banned in ("model_votes", "claude_vote", "codex_vote", "consensus", "advisory_votes"):
            self.assertNotIn(banned, field_names)

    # Mandatory Scenario 11: locator replacement is not the same reference.
    def test_scenario_11_locator_replacement_is_not_same_reference(self) -> None:
        same_locator_different_content = [
            ref(ref_id="v1", fingerprint=digest("content-A"), locator="/same/path.json"),
            ref(ref_id="v1", fingerprint=digest("content-B"), locator="/same/path.json"),
        ]
        with self.assertRaises(nd.DecisionValidationError):
            snapshot(verification_evidence_refs=same_locator_different_content)


# --- M8-A regression compatibility -----------------------------------------------------

class M8ACompatibilityTests(unittest.TestCase):
    def test_m8a_contracts_still_importable_and_functional(self) -> None:
        from nogap_decision import (  # noqa: F401
            DecisionScope, DecisionPolicyContract, DecisionRequestContract,
            DecisionEvaluationContract, DecisionRecordContract, derive_contract_verdict,
        )

    def test_derive_contract_verdict_unaffected_by_m8b_additions(self) -> None:
        p1 = nd.DecisionPredicateResult(predicate_id="P1", role="REQUIREMENT", truth_value="TRUE", required=True, blocking=False)
        v1 = nd.DecisionPredicateResult(predicate_id="V1", role="VIOLATION", truth_value="FALSE", required=False, blocking=True)
        policy = nd.DecisionPolicyContract(decision_type="TASK_ACCEPTANCE", policy_id="p", policy_version="1",
                                            required_predicate_ids=("P1",), blocking_predicate_ids=("V1",))
        result = nd.derive_contract_verdict([p1, v1], policy_contract=policy)
        self.assertEqual(result.verdict, "ACCEPT")


# --- DeepImmutabilityTests (final M8-B hardening review) ------------------------------

class DeepImmutabilityTests(unittest.TestCase):
    """A frozen dataclass alone is insufficient if a nested field remains
    mutable: `frozen=True` only blocks `setattr` on the dataclass's OWN
    attributes, not mutation of a mutable object one of those attributes
    happens to reference. Before this fix, `metadata` was only shallow-
    copied (`dict(self.metadata)`), which protected top-level key
    replacement but left any nested dict/list as the SAME object the caller
    could still reach and mutate - both directly through the snapshot
    (`snapshot.metadata["nested"]["x"] = 2`) and indirectly through the
    caller's original input object (an aliasing attack). _deep_freeze() now
    recursively converts every dict to a MappingProxyType (over already-
    frozen values) and every list to a tuple (of already-frozen elements),
    closing both paths."""

    # 1. Direct top-level metadata mutation.
    def test_1_direct_metadata_key_assignment_rejected(self) -> None:
        snap = snapshot(metadata={"x": 1})
        with self.assertRaises(TypeError):
            snap.metadata["x"] = 2
        self.assertEqual(snap.metadata["x"], 1)

    # 2. Nested metadata mutation.
    def test_2_nested_metadata_key_assignment_rejected(self) -> None:
        snap = snapshot(metadata={"nested": {"x": 1}})
        with self.assertRaises(TypeError):
            snap.metadata["nested"]["x"] = 2
        self.assertEqual(snap.metadata["nested"]["x"], 1)

    # 3. Nested list mutation via append.
    def test_3_nested_metadata_list_append_rejected(self) -> None:
        snap = snapshot(metadata={"items": [1, 2]})
        with self.assertRaises(AttributeError):
            snap.metadata["items"].append("x")
        self.assertEqual(snap.metadata["items"], (1, 2))

    # 4. Aliasing attack: mutate the ORIGINAL input after construction.
    def test_4_aliasing_attack_original_input_mutation_after_construction(self) -> None:
        metadata = {"nested": {"x": 1}, "items": [1, 2]}
        snap = snapshot(metadata=metadata)
        fp_before = snap.snapshot_fingerprint
        metadata["nested"]["x"] = 999
        metadata["items"].append(3)
        metadata["nested"]["new_key"] = "injected"
        self.assertEqual(snap.metadata["nested"]["x"], 1)
        self.assertEqual(snap.metadata["items"], (1, 2))
        self.assertNotIn("new_key", snap.metadata["nested"])
        self.assertEqual(snap.snapshot_fingerprint, fp_before)

    # 5. Reference-tuple mutation attempt on DecisionSnapshot.
    def test_5_reference_tuple_mutation_rejected(self) -> None:
        snap = snapshot(verification_evidence_refs=[ref(ref_id="v1")])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snap.verification_evidence_refs += (ref(ref_id="v2"),)
        self.assertEqual(len(snap.verification_evidence_refs), 1)

    # 6. Mutation through DecisionSubject.artifact_refs.
    def test_6_subject_artifact_refs_element_mutation_rejected(self) -> None:
        art = ref(ref_kind="ARTIFACT", ref_id="a1")
        subj = subject(artifact_refs=[art])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            subj.artifact_refs[0].ref_id = "a2"

    def test_6_subject_artifact_refs_tuple_reassignment_rejected(self) -> None:
        subj = subject(artifact_refs=[ref(ref_kind="ARTIFACT", ref_id="a1")])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            subj.artifact_refs += (ref(ref_kind="ARTIFACT", ref_id="a2"),)

    # 7. SnapshotReference has no nested metadata/locator structure to attack
    # beyond locator itself - confirm it is impossible to change post-construction.
    def test_7_snapshot_reference_locator_mutation_rejected(self) -> None:
        r = ref(locator="/original/path.json")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.locator = "/attacker/path.json"
        self.assertEqual(r.locator, "/original/path.json")

    def test_7_snapshot_reference_fingerprint_mutation_rejected(self) -> None:
        r = ref()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.fingerprint = digest("attacker-content")

    # 8. Fingerprint stability across every attempted mutation above.
    def test_8_fingerprint_unchanged_across_all_mutation_attempts(self) -> None:
        metadata = {"nested": {"x": 1}, "items": [1, 2]}
        snap = snapshot(metadata=metadata, verification_evidence_refs=[ref(ref_id="v1")])
        fp_before = snap.snapshot_fingerprint

        attempts = [
            lambda: snap.metadata.__setitem__("x", 2),
            lambda: snap.metadata["nested"].__setitem__("x", 2),
            lambda: snap.metadata["items"].append("x"),
            lambda: setattr(snap, "verification_evidence_refs", snap.verification_evidence_refs + (ref(ref_id="v2"),)),
        ]
        for attempt in attempts:
            with self.assertRaises((TypeError, AttributeError, dataclasses.FrozenInstanceError)):
                attempt()
        metadata["nested"]["x"] = 999
        metadata["items"].append(3)

        self.assertEqual(snap.snapshot_fingerprint, fp_before)

    # Deep aliasing attack, exact shape from the review brief.
    def test_deep_aliasing_attack_exact_scenario(self) -> None:
        nested = {"a": [1, {"b": 2}]}
        snap = snapshot(metadata={"nested": nested})
        fp_before = snap.snapshot_fingerprint

        nested["a"].append(3)
        nested["a"][1]["b"] = 999

        stored = snap.metadata["nested"]
        self.assertEqual(len(stored["a"]), 2)  # NOT 3 - the append never reached the snapshot
        self.assertEqual(stored["a"][0], 1)
        self.assertEqual(stored["a"][1]["b"], 2)  # NOT 999
        self.assertEqual(snap.snapshot_fingerprint, fp_before)

    def test_metadata_is_mappingproxy_not_plain_dict(self) -> None:
        snap = snapshot(metadata={"x": 1})
        self.assertIsInstance(snap.metadata, types.MappingProxyType)

    def test_nested_metadata_dict_is_mappingproxy(self) -> None:
        snap = snapshot(metadata={"nested": {"x": 1}})
        self.assertIsInstance(snap.metadata["nested"], types.MappingProxyType)

    def test_nested_metadata_list_is_tuple(self) -> None:
        snap = snapshot(metadata={"items": [1, 2, 3]})
        self.assertIsInstance(snap.metadata["items"], tuple)

    def test_deep_frozen_metadata_still_json_compatible_content(self) -> None:
        # Deep-freezing is an implementation detail of the STORED
        # representation; validation and canonical_json() both operate on the
        # semantically-equivalent plain content, unaffected by the container
        # type swap.
        snap = snapshot(metadata={"nested": {"x": 1}, "items": [1, 2]})
        self.assertEqual(dict(snap.metadata["nested"]), {"x": 1})
        self.assertEqual(list(snap.metadata["items"]), [1, 2])

    def test_deep_freeze_of_metadata_does_not_change_fingerprint_vs_plain_dict(self) -> None:
        # The freezing implementation detail must not leak into the semantic
        # fingerprint - metadata is excluded from semantic_payload() entirely,
        # so its representation (frozen or not) is irrelevant to identity.
        snap_with_metadata = snapshot(metadata={"nested": {"x": 1}, "items": [1, 2]})
        snap_without_metadata = snapshot(metadata={})
        self.assertEqual(snap_with_metadata.snapshot_fingerprint, snap_without_metadata.snapshot_fingerprint)

    def test_shared_snapshot_id_does_not_imply_same_content(self) -> None:
        # snapshot_id is a caller-supplied correlation label, never proof of
        # content equality - two snapshots can share one while differing in
        # every semantic respect.
        snap1 = snapshot(snapshot_id="shared-label", subject=subject(revision_ref=revision("rev-A")))
        snap2 = snapshot(snapshot_id="shared-label", subject=subject(revision_ref=revision("rev-B")))
        self.assertEqual(snap1.snapshot_id, snap2.snapshot_id)
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_shared_request_id_does_not_imply_same_content(self) -> None:
        snap1 = snapshot(request_id="shared-request", subject=subject(revision_ref=revision("rev-A")))
        snap2 = snapshot(request_id="shared-request", subject=subject(revision_ref=revision("rev-B")))
        self.assertEqual(snap1.request_id, snap2.request_id)
        self.assertNotEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_same_semantic_state_different_request_id_same_fingerprint(self) -> None:
        snap1 = snapshot(request_id="req-A")
        snap2 = snapshot(request_id="req-B")
        self.assertNotEqual(snap1.request_id, snap2.request_id)
        self.assertEqual(snap1.snapshot_fingerprint, snap2.snapshot_fingerprint)

    def test_decision_scope_confirmed_already_fully_immutable(self) -> None:
        # DecisionScope carries only str/None/tuple-of-str fields - no dict or
        # list nesting exists to attack; confirmed structurally, not just by
        # frozen=True.
        for f in dataclasses.fields(nd.DecisionScope):
            self.assertNotIn(f.type, ("dict", "list", "set"))
        s = scope(artifact_refs=("a1",))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            s.artifact_refs += ("a2",)


if __name__ == "__main__":
    unittest.main()
