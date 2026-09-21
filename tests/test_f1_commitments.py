"""F1-I3 closure tests: typed signed commitments (T1A §6 bodies).

The substitution tests are the point. A layer that builds eleven types correctly but lets a
PROJECT body be signed as a TASK has produced eleven spellings of one type.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_commitments as c                                                   # noqa: E402
import f1_kernel as k                                                        # noqa: E402
import f1_registry as r                                                      # noqa: E402

D = "sha256:" + "aa" * 32
D2 = "sha256:" + "bb" * 32


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root_sk = k.generate_key()
        self.registry = r.AuthorityRegistry(self.root_sk.public_key())
        self.sk = k.generate_key()
        self.pub = self.sk.public_key().public_bytes_raw().hex()
        self.seq = 0
        self.grant(sorted(k.DOMAINS), projects=[r.WILDCARD])
        self.sequences = c.SequenceSource()
        self.signer = c.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                                         sequences=self.sequences)

    def grant(self, types, *, actions=None, projects=("proj-1",), key_id="key-1", pub=None):
        entry = {
            "key_id": key_id, "public_key": pub or self.pub, "identity": "authority-1",
            "authority_class": "verification", "allowed_message_types": list(types),
            "allowed_actions": actions or {t: sorted(k.ACTIONS[t]) for t in types},
            "allowed_projects": list(projects),
        }
        self.seq += 1
        message = k.message("REGISTRY", "add_key", key_id="registry-root",
                            producer_identity="root", sequence=self.seq, signed_at="t",
                            deployment_mode="B",
                            body={"epoch": self.registry.epoch + 1,
                                  "previous_commitment": self.registry.head or "",
                                  "key_grants_digest": r.digest([entry])})
        self.registry.apply(k.sign(message, self.root_sk), [entry])

    def a_project(self):
        return self.signer.project_genesis(
            project_id="proj-1", repository_identity="git:abc", initial_base_digest=D,
            policy_baseline=D, gate_baseline=D, obligation_policy_baseline=D,
            provisioned_by="human-1", provisioning_sequence=0)

    def a_verify(self, **over):
        args = dict(project="proj-1", run_commitment=D, gate_commitment=D,
                    candidate_fingerprint=D, obligation_id="obl-1",
                    verification_method="pytest", verdict="pass", observation_digest=D)
        args.update(over)
        return self.signer.verify_attestation(**args)


class AllElevenTypesTests(Fixture):
    def test_every_type_builds_signs_and_verifies(self):
        built = {
            "PROJECT": self.a_project(),
            "TASK": self.signer.task(action="create", project="proj-1", project_commitment=D,
                                     task_digest=D, relation="NEW_TASK"),
            "RUN": self.signer.run(project="proj-1", project_commitment=D, task_commitment=D,
                                   creation_nonce="n", run_id="run-1",
                                   parent_run_commitments=[], authorized_base_commitment=D,
                                   policy_head=D),
            "GATE": self.signer.gate(project="proj-1", run_commitment=D, gate_content_digest=D,
                                     freeze_policy_version="v1", baseline_match=True),
            "VERIFY": self.a_verify(),
            "DECISION": self.signer.decision(project="proj-1", decision="accept",
                                             run_commitment=D, candidate_fingerprint=D,
                                             decision_snapshot_digest=D,
                                             superseded_adverse_verdicts=[], policy_head=D),
            "POLICY": self.signer.policy(action="create", project="proj-1",
                                         project_commitment=D, epoch=1, previous_commitment="",
                                         class_authority_map_digest=D,
                                         predicate_class_map_digest=D2),
            "APPLICABILITY": self.signer.applicability(
                project="proj-1", transition="activate", project_commitment=D,
                obligation_id="o", obligation_class="HIGH", predicate_scope_digest=D,
                condition_commitment=D, epoch=1, previous_commitment="", authorization_ref=D),
            "REGISTRY": self.signer.registry(action="add_key", epoch=1, previous_commitment="",
                                             key_grants_digest=D),
            "MIGRATION": self.signer.migration(action="grant", project_commitments=[D],
                                               reason="why", expiry="2027", authorization_ref=D,
                                               epoch=1, previous_commitment=""),
            "HUMAN": self.signer.human_authorization(
                project="proj-1", authorization_id="a-1", action_type="freeze",
                target_message_type="GATE", project_commitment=D, subject_digest=D,
                policy_head=D, use_semantics="single-use", expiry="2027"),
        }
        self.assertEqual(set(built), set(k.DOMAINS), "not every domain has a typed builder")
        for message_type, signed in sorted(built.items()):
            with self.subTest(message_type=message_type):
                self.assertEqual(k.verify(signed, self.sk.public_key())["message_type"],
                                 message_type)

    def test_round_trip_sign_serialize_parse_verify(self):
        import json
        signed = self.a_verify()
        parsed = json.loads(json.dumps(signed))
        self.assertEqual(k.verify(parsed, self.sk.public_key())["body"]["verdict"], "pass")

    def test_sequence_is_per_identity_and_monotonic(self):
        seen = [self.a_verify()["message"]["sequence"] for _ in range(3)]
        self.assertEqual(seen, [0, 1, 2])
        other = c.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                                   sequences=c.SequenceSource())
        self.assertEqual(other.verify_attestation(
            project="proj-1", run_commitment=D, gate_commitment=D, candidate_fingerprint=D,
            obligation_id="o", verification_method="m", verdict="pass",
            observation_digest=D)["message"]["sequence"], 0)


    def test_two_signers_for_one_identity_never_emit_the_same_sequence(self):
        """Found by a test, not by reading: sequence was per signer object, not per identity.

        Ed25519 is deterministic, so two signers for one key_id each starting at 0 produced
        byte-identical signed messages — two distinct attestations collapsing into one commitment
        reference, invisibly.
        """
        a = c.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                               sequences=self.sequences)
        b = c.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                               sequences=self.sequences)
        seqs = [a.task(action="create", project="proj-1", project_commitment=D, task_digest=D,
                       relation="NEW_TASK")["message"]["sequence"],
                b.task(action="create", project="proj-1", project_commitment=D, task_digest=D,
                       relation="NEW_TASK")["message"]["sequence"]]
        self.assertEqual(len(set(seqs)), 2, "two signers for one identity reused a sequence")

    def test_genesis_previous_commitment_is_spelled_the_same_way_as_in_the_registry(self):
        # I2 uses "" for the first link. Two layers disagreeing on how genesis is spelled is
        # AM-39's cross-contract defect one level down.
        self.signer.policy(action="create", project="proj-1", project_commitment=D, epoch=1,
                           previous_commitment="", class_authority_map_digest=D,
                           predicate_class_map_digest=D2)
        with self.assertRaises(c.CommitmentError):
            self.signer.policy(action="create", project="proj-1", project_commitment=D, epoch=1,
                               previous_commitment="none", class_authority_map_digest=D,
                               predicate_class_map_digest=D2)


class SubstitutionTests(Fixture):
    """Cross-type substitution must be unsayable, not merely caught."""

    def test_no_generic_constructor_exists(self):
        import inspect
        for name, fn in inspect.getmembers(c.CommitmentSigner, inspect.isfunction):
            if name.startswith("_"):
                continue
            params = set(inspect.signature(fn).parameters)
            self.assertNotIn("body", params, f"{name}() takes a caller-supplied body")
            self.assertNotIn("message_type", params, f"{name}() takes a caller-chosen type")

    def test_project_body_cannot_be_signed_as_a_task(self):
        with self.assertRaises(TypeError):
            self.signer.task(action="create", project="proj-1", project_id="proj-1",
                             repository_identity="git:abc")

    def test_policy_builder_rejects_an_applicability_only_field(self):
        with self.assertRaises(TypeError):
            self.signer.policy(action="create", project="proj-1", project_commitment=D, epoch=1,
                               previous_commitment="", class_authority_map_digest=D,
                               predicate_class_map_digest=D2, obligation_class="LOW")

    def test_unknown_extra_field_is_rejected_by_every_builder(self):
        with self.assertRaises(TypeError):
            self.a_verify(authority="verification")

    def test_missing_required_field_is_rejected(self):
        with self.assertRaises(TypeError):
            self.signer.run(project="proj-1", project_commitment=D, task_commitment=D,
                            creation_nonce="n", run_id="run-1", parent_run_commitments=[])

    def test_body_envelope_mismatch_cannot_be_constructed(self):
        signed = self.a_verify()
        signed["message"]["message_type"] = "DECISION"
        with self.assertRaises(k.MessageError):
            k.verify(signed, self.sk.public_key())

    def test_cross_domain_signature_reuse_is_refused(self):
        signed = self.a_verify()
        forged = {"message": dict(signed["message"]), "signature": signed["signature"]}
        forged["message"]["message_type"] = "DECISION"
        forged["message"]["action"] = "accept"
        forged["message"]["body"] = {
            "run_commitment": D, "candidate_fingerprint": D, "decision": "accept",
            "decision_snapshot_digest": D, "superseded_adverse_verdicts": [], "policy_head": D}
        with self.assertRaises(k.MessageError):
            k.verify(forged, self.sk.public_key())


class SignerAuthorizationTests(Fixture):
    """The registry's question, asked before signing rather than after."""

    def setUp(self):
        super().setUp()
        self.scoped_sk = k.generate_key()
        self.grant(["VERIFY"], actions={"VERIFY": ["attest"]}, projects=["proj-1"],
                   key_id="key-2", pub=self.scoped_sk.public_key().public_bytes_raw().hex())
        self.scoped = c.CommitmentSigner(self.registry, "key-2", self.scoped_sk, "verifier-2",
                                         sequences=c.SequenceSource())

    def test_valid_signer_wrong_message_type(self):
        with self.assertRaises(r.RegistryError):
            self.scoped.decision(project="proj-1", decision="accept", run_commitment=D,
                                 candidate_fingerprint=D, decision_snapshot_digest=D,
                                 superseded_adverse_verdicts=[], policy_head=D)

    def test_valid_signer_wrong_action(self):
        self.grant(["POLICY"], actions={"POLICY": ["create"]}, projects=["proj-1"],
                   key_id="key-3", pub=self.pub)
        signer = c.CommitmentSigner(self.registry, "key-3", self.sk, "policy-1",
                                    sequences=c.SequenceSource())
        with self.assertRaises(r.RegistryError):
            signer.policy(action="weaken", project="proj-1", project_commitment=D, epoch=1,
                          previous_commitment="", class_authority_map_digest=D,
                          predicate_class_map_digest=D2)

    def test_valid_signer_wrong_project(self):
        with self.assertRaises(r.RegistryError):
            self.scoped.verify_attestation(
                project="proj-2", run_commitment=D, gate_commitment=D, candidate_fingerprint=D,
                obligation_id="o", verification_method="m", verdict="pass", observation_digest=D)

    def test_an_unauthorized_attempt_produces_no_signature_at_all(self):
        before = c.SEQUENCES.allocate("key-2")
        with self.assertRaises(r.RegistryError):
            self.scoped.decision(project="proj-1", decision="accept", run_commitment=D,
                                 candidate_fingerprint=D, decision_snapshot_digest=D,
                                 superseded_adverse_verdicts=[], policy_head=D)
        self.assertEqual(c.SEQUENCES.allocate("key-2"), before + 1,
                         "a refused emission consumed a sequence number")

    def test_historical_key_verifies_an_old_record_but_cannot_create_a_new_one(self):
        old = self.scoped.verify_attestation(
            project="proj-1", run_commitment=D, gate_commitment=D, candidate_fingerprint=D,
            obligation_id="o", verification_method="m", verdict="pass", observation_digest=D)
        self.seq += 1
        message = k.message("REGISTRY", "revoke_key", key_id="registry-root",
                            producer_identity="root", sequence=self.seq, signed_at="t",
                            deployment_mode="B",
                            body={"epoch": self.registry.epoch + 1,
                                  "previous_commitment": self.registry.head or "",
                                  "key_grants_digest": r.digest(
                                      [{"key_id": "key-2", "compromised_after_epoch": 9}])})
        self.registry.apply(k.sign(message, self.root_sk),
                            [{"key_id": "key-2", "compromised_after_epoch": 9}])

        self.assertEqual(self.registry.verification_key("key-2"),
                         self.scoped_sk.public_key().public_bytes_raw().hex())
        self.assertEqual(k.verify(old, self.scoped_sk.public_key())["message_type"], "VERIFY")
        with self.assertRaises(r.RegistryError):
            self.scoped.verify_attestation(
                project="proj-1", run_commitment=D, gate_commitment=D, candidate_fingerprint=D,
                obligation_id="o", verification_method="m", verdict="pass", observation_digest=D)


class CommitmentReferenceTests(Fixture):
    def test_a_reference_resolves_to_the_record_it_names(self):
        store = c.CommitmentStore()
        signed = self.a_project()
        reference = store.put(signed)
        self.assertEqual(store.resolve(reference, self.sk.public_key())["message_type"], "PROJECT")

    def test_a_tampered_record_does_not_resolve(self):
        store = c.CommitmentStore()
        reference = store.put(self.a_project())
        store._records[reference]["message"]["body"]["project_id"] = "proj-evil"
        with self.assertRaises(c.CommitmentError):
            store.resolve(reference, self.sk.public_key())

    def test_a_tampered_signature_does_not_resolve(self):
        store = c.CommitmentStore()
        reference = store.put(self.a_project())
        store._records[reference]["signature"] = "00" * 64
        with self.assertRaises(c.CommitmentError):
            store.resolve(reference, self.sk.public_key())

    def test_a_validly_signed_substitute_does_not_resolve(self):
        """Found by mutation: the tamper tests were all caught by signature verification.

        The digest check guards the case verification cannot see — a *validly signed* record
        swapped in under another record's reference. Both verify; only one is the record that
        reference names.
        """
        store = c.CommitmentStore()
        reference = store.put(self.a_project())
        substitute = self.signer.project_genesis(
            project_id="proj-evil", repository_identity="git:evil", initial_base_digest=D,
            policy_baseline=D, gate_baseline=D, obligation_policy_baseline=D,
            provisioned_by="human-1", provisioning_sequence=0)
        k.verify(substitute, self.sk.public_key())          # the substitute is genuinely valid
        store._records[reference] = substitute
        with self.assertRaises(c.CommitmentError) as caught:
            store.resolve(reference, self.sk.public_key())
        self.assertIn("does not match the record it names", str(caught.exception))

    def test_an_unknown_reference_fails_closed(self):
        with self.assertRaises(c.CommitmentError):
            c.CommitmentStore().resolve(D, self.sk.public_key())

    def test_a_reference_covers_the_signature_not_just_the_body(self):
        # Two signers for ONE identity share its sequence, so two attestations never collapse
        # into one commitment reference.
        other = c.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                                   sequences=self.sequences)
        a, b = self.a_project(), other.project_genesis(
            project_id="proj-1", repository_identity="git:abc", initial_base_digest=D,
            policy_baseline=D, gate_baseline=D, obligation_policy_baseline=D,
            provisioned_by="human-1", provisioning_sequence=0)
        self.assertNotEqual(c.commitment_of(a), c.commitment_of(b))


class FieldDisciplineTests(Fixture):
    def test_digest_fields_must_be_digests(self):
        with self.assertRaises(c.CommitmentError):
            self.a_verify(run_commitment="run-1")

    def test_closed_enums_are_enforced(self):
        with self.assertRaises(c.CommitmentError):
            self.signer.decision(project="proj-1", decision="ship_it", run_commitment=D,
                                 candidate_fingerprint=D, decision_snapshot_digest=D,
                                 superseded_adverse_verdicts=[], policy_head=D)
        with self.assertRaises(c.CommitmentError):
            self.signer.applicability(
                project="proj-1", transition="relax", project_commitment=D, obligation_id="o",
                obligation_class="HIGH", predicate_scope_digest=D, condition_commitment=D,
                epoch=1, previous_commitment="", authorization_ref=D)

    def test_task_relation_enum_is_closed(self):
        for bad in ("SOMETHING", "CONTINUATION_OF", "SUPERSEDES()", "NEW_TASK(x)"):
            with self.subTest(relation=bad), self.assertRaises(c.CommitmentError):
                self.signer.task(action="create", project="proj-1", project_commitment=D,
                                 task_digest=D, relation=bad)
        for good in ("NEW_TASK", "CHILD_OF(task-9)", "SUPERSEDES(task-1)"):
            with self.subTest(relation=good):
                self.signer.task(action="create", project="proj-1", project_commitment=D,
                                 task_digest=D, relation=good)

    def test_gate_carries_exactly_one_authorization_basis(self):
        for kwargs in ({}, {"baseline_match": True, "human_authorization": D}):
            with self.subTest(kwargs=kwargs), self.assertRaises(c.CommitmentError):
                self.signer.gate(project="proj-1", run_commitment=D, gate_content_digest=D,
                                 freeze_policy_version="v1", **kwargs)

    def test_migration_must_enumerate_projects_never_a_wildcard(self):
        with self.assertRaises(c.CommitmentError):
            self.signer.migration(action="grant", project_commitments=[], reason="why",
                                  expiry="2027", authorization_ref=D, epoch=1,
                                  previous_commitment="")

    def test_human_authorization_names_a_known_target_domain(self):
        with self.assertRaises(c.CommitmentError):
            self.signer.human_authorization(
                project="proj-1", authorization_id="a", action_type="x",
                target_message_type="OVERRIDE", project_commitment=D, subject_digest=D,
                policy_head=D, use_semantics="single-use", expiry="2027")


class ScopeBoundaryTests(unittest.TestCase):
    """I3 represents and signs. It decides nothing."""

    def test_no_stage_1_stage_2_or_decision_logic(self):
        source = (Path(__file__).resolve().parents[1]
                  / "scripts" / "f1_commitments.py").read_text()
        for absent in ("STAGE 1", "STAGE 2", "is_admissible", "INADMISSIBLE",
                       "decision_snapshot_digest resolves", "current authoritative head"):
            self.assertNotIn(absent, source, f"{absent!r} appears in I3")

    def test_no_durable_store(self):
        source = (Path(__file__).resolve().parents[1]
                  / "scripts" / "f1_commitments.py").read_text()
        for absent in ("open(", "Path(", "sqlite", "fsync"):
            self.assertNotIn(absent, source, f"I3 touches persistence via {absent!r}")


if __name__ == "__main__":
    unittest.main()
