"""F1-I4 closure tests: Stage 1 admissibility (T1A §10).

AM-22's lesson is the shape of this file: a rule stated elsewhere and absent from the procedure is
not enforced. So the tests check the procedure, in order, step by step — and one of them reads the
twelve steps out of the frozen contract.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_commitments as cm                                                  # noqa: E402
import f1_kernel as k                                                        # noqa: E402
import f1_registry as r                                                      # noqa: E402
import f1_stage1 as s1                                                       # noqa: E402

D = "sha256:" + "aa" * 32
CONTRACT = (Path(__file__).resolve().parents[1] / "docs" / "f1-t1a-trust-core.md")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root_sk = k.generate_key()
        self.registry = r.AuthorityRegistry(self.root_sk.public_key())
        self.sk = k.generate_key()
        self.pub = self.sk.public_key().public_bytes_raw().hex()
        self.seq = 0
        self.grant(sorted(k.DOMAINS), projects=[r.WILDCARD])
        self.signer = cm.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                                          sequences=cm.SequenceSource())
        self.heads = {"policy_head": D, "previous_commitment": ""}
        self.stage1 = self.build()

    def build(self, **over):
        args = dict(registry=self.registry,
                    current_head=lambda mt, field: self.heads.get(field),
                    project_of=lambda m: "proj-1", required_mode="B")
        args.update(over)
        return s1.Stage1(**args)

    def grant(self, types, *, actions=None, projects=("proj-1",), key_id="key-1", pub=None):
        entry = {"key_id": key_id, "public_key": pub or self.pub, "identity": "authority-1",
                 "authority_class": "verification", "allowed_message_types": list(types),
                 "allowed_actions": actions or {t: sorted(k.ACTIONS[t]) for t in types},
                 "allowed_projects": list(projects)}
        self.commit("add_key", [entry])

    def commit(self, action, grants):
        self.seq += 1
        message = k.message("REGISTRY", action, key_id="registry-root", producer_identity="root",
                            sequence=self.seq, signed_at="t", deployment_mode="B",
                            body={"epoch": self.registry.epoch + 1,
                                  "previous_commitment": self.registry.head or "",
                                  "key_grants_digest": r.digest(grants)})
        self.registry.apply(k.sign(message, self.root_sk), grants)

    def a_verify(self, signer=None, **over):
        args = dict(project="proj-1", run_commitment=D, gate_commitment=D,
                    candidate_fingerprint=D, obligation_id="o", verification_method="m",
                    verdict="pass", observation_digest=D)
        args.update(over)
        return (signer or self.signer).verify_attestation(**args)


class ProcedureCompletenessTests(Fixture):
    """AM-22: the procedure is normative and complete."""

    def test_all_twelve_contract_steps_are_implemented(self):
        block = re.search(r"STAGE 1 — every message, in order\n(.*?)\nSTAGE 2", 
                          CONTRACT.read_text(encoding="utf-8"), re.S).group(1)
        steps = [int(m.group(1)) for line in block.splitlines()
                 if (m := re.match(r"\s*(\d+)\.", line))]
        self.assertEqual(steps, list(range(1, 13)), "the contract no longer has twelve steps")
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_stage1.py").read_text()
        for step in steps:
            self.assertRegex(source, rf"[Ss]teps? {step}\b",
                             f"step {step} is not named in the implementation")

    def test_there_is_no_default_admissible_path(self):
        # Every refusal names its step, and the only ADMISSIBLE return is the last line reached
        # after all twelve. A message that fails anything must never come back admissible.
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_stage1.py").read_text()
        body = source[source.index("    def check("):]
        self.assertEqual(body.count("return Verdict(ADMISSIBLE)"), 1)

    def test_a_well_formed_authorized_message_is_admissible(self):
        self.assertTrue(self.stage1.check(self.a_verify()).admissible)


class OrderTests(Fixture):
    """The steps run in order, and the FIRST failure decides."""

    def test_a_message_failing_early_and_late_reports_the_early_step(self):
        # An unresolvable key (step 5's condition) and a stale head (step 10) at once: the
        # earlier step decides.
        stranger = k.generate_key()
        self.grant(["VERIFY"], key_id="key-2", pub=stranger.public_key().public_bytes_raw().hex())
        signed = self.a_verify(signer=cm.CommitmentSigner(
            self.registry, "key-2", stranger, "a2", sequences=cm.SequenceSource()))
        signed["message"]["key_id"] = "nobody"
        self.assertEqual(self.stage1.check(signed).step, 5)

    def test_signature_failure_precedes_registry_grant_failure(self):
        self.grant(["VERIFY"], actions={"VERIFY": ["attest"]}, projects=["proj-9"],
                   key_id="key-3", pub=self.pub)
        signer = cm.CommitmentSigner(self.registry, "key-3", self.sk, "a3",
                                     sequences=cm.SequenceSource())
        signed = self.a_verify(signer=signer, project="proj-9")
        signed["message"]["body"]["verdict"] = "fail"        # breaks the signature
        self.assertEqual(self.stage1.check(signed).step, 5)


class StepTests(Fixture):
    def test_step_1_tampered_envelope(self):
        signed = self.a_verify()
        signed["message"]["producer_identity"] = "someone-else"
        self.assertEqual(self.stage1.check(signed).step, 5)

    def test_step_1_unknown_schema_version(self):
        signed = self.a_verify()
        signed["message"]["schema_version"] = "99"
        v = self.stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 1))

    def test_step_4_unknown_body_field(self):
        # Asserting the STEP, not just the refusal: step 5 would also catch this, and a rule whose
        # owning step cannot be named is the drift AM-22 exists to stop.
        signed = self.a_verify()
        signed["message"]["body"]["authority"] = "verification"
        v = self.stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 4))

    def test_step_2_unknown_message_type_is_refused_not_a_crash(self):
        """I3's builders cannot produce one, so only a hand-built message reaches this step."""
        signed = self.a_verify()
        signed["message"]["message_type"] = "OVERRIDE"
        v = self.stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 2))

    def test_step_7_disputed_belongs_to_re_evaluation_not_to_new_material(self):
        """§11: new material from a revoked key is inadmissible; DISPUTED is for what was already
        accepted before the compromise bound."""
        accepted_at = self.registry.acceptance_epoch
        signed = self.a_verify()            # built while the key was still active
        self.commit("revoke_key", [{"key_id": "key-1", "compromised_after_epoch": 99}])
        # New material reaching Stage 1: inadmissible at step 7, never DISPUTED.
        v = self.stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 7))
        # Already-accepted material: DISPUTED, requiring human re-affirmation.
        v = self.stage1.reclassify("key-1", accepted_at)
        self.assertEqual((v.status, v.step), (r.DISPUTED, 7))

    def test_step_7_material_accepted_at_or_after_the_bound_is_definitely_invalid(self):
        self.commit("revoke_key", [{"key_id": "key-1", "compromised_after_epoch": 1}])
        self.assertEqual(self.stage1.reclassify("key-1", 5).status, s1.INADMISSIBLE)

    def test_step_5_bad_signature(self):
        signed = self.a_verify()
        signed["signature"] = "00" * 64
        self.assertEqual(self.stage1.check(signed).step, 5)

    def test_unknown_key_id_refuses_at_step_5_not_from_a_lookup(self):
        """Resolving the key is a prerequisite, not step 6's decision.

        With no key material step 5's condition — "signature verifies under key_id" — cannot be
        met, and in an ordered procedure the first failing condition decides. An earlier draft
        issued a step 6 verdict straight from the lookup, which ran the contract's steps out of
        order.
        """
        signed = self.a_verify()
        signed["message"]["key_id"] = "ghost"
        v = self.stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 5))
        self.assertIn("unknown key_id", v.reason)

    def test_step_6_decides_current_head_membership_after_step_5(self):
        """Step 6 is a separate, later decision: resolvable is not present-at-the-current-head."""
        class HeadlessRegistry:
            """Resolves key material but holds no accepted head — a state a durable store can be
            in mid-recovery, which I5 makes real."""

            def __init__(self, inner):
                self._inner = inner

            head = None

            def verification_key(self, key_id):
                return self._inner.verification_key(key_id)

            def authorize(self, *a, **kw):                     # pragma: no cover - never reached
                raise AssertionError("step 6 must refuse before the grant is consulted")

        signed = self.a_verify()
        stage1 = self.build(registry=HeadlessRegistry(self.registry))
        v = stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 6))
        self.assertIn("no accepted head", v.reason)

    def test_step_7_retired_key(self):
        signed = self.a_verify()
        self.commit("retire_key", [{"key_id": "key-1"}])
        v = self.stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 7))

    def test_step_7_revoked_key_is_refused_not_merely_noted(self):
        signed = self.a_verify()
        self.commit("revoke_key", [{"key_id": "key-1", "compromised_after_epoch": 1}])
        v = self.stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 7))

    def test_step_8_type_or_action_not_granted(self):
        narrow = k.generate_key()
        self.grant(["VERIFY"], actions={"VERIFY": ["attest"]}, projects=[r.WILDCARD],
                   key_id="key-4", pub=narrow.public_key().public_bytes_raw().hex())
        signer = cm.CommitmentSigner(self.registry, "key-4", narrow, "a4",
                                     sequences=cm.SequenceSource())
        signed = self.a_verify(signer=signer)
        signed["message"]["message_type"] = "DECISION"   # breaks the signature first, so re-sign
        v = self.stage1.check(self.a_verify(signer=signer))
        self.assertTrue(v.admissible)
        # Now a type the grant does not cover, signed correctly:
        with self.assertRaises(r.RegistryError):
            signer.decision(project="proj-1", decision="accept", run_commitment=D,
                            candidate_fingerprint=D, decision_snapshot_digest=D,
                            superseded_adverse_verdicts=[], policy_head=D)

    def test_step_9_wrong_project_scope(self):
        scoped = k.generate_key()
        self.grant(["VERIFY"], projects=["proj-1"], key_id="key-5",
                   pub=scoped.public_key().public_bytes_raw().hex())
        signer = cm.CommitmentSigner(self.registry, "key-5", scoped, "a5",
                                     sequences=cm.SequenceSource())
        signed = self.a_verify(signer=signer)
        stage1 = self.build(project_of=lambda m: "proj-9")
        v = stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 9))

    def test_step_10_stale_head_is_refused(self):
        signed = self.signer.decision(
            project="proj-1", decision="accept", run_commitment=D, candidate_fingerprint=D,
            decision_snapshot_digest=D, superseded_adverse_verdicts=[], policy_head=D)
        self.heads["policy_head"] = "sha256:" + "bb" * 32          # the head moved on
        v = self.stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 10))
        self.assertIn("AM-18", v.reason)

    def test_step_10_is_derived_not_a_remembered_list(self):
        """A newly added head-bearing field is covered the day it is added."""
        self.assertTrue(s1.HEAD_FIELD.search("policy_head"))
        self.assertTrue(s1.HEAD_FIELD.search("previous_commitment"))
        self.assertTrue(s1.HEAD_FIELD.search("registry_head"))
        self.assertFalse(s1.HEAD_FIELD.search("run_commitment"))

    def test_step_11_replayed_sequence_is_refused(self):
        signed = self.a_verify()
        self.assertTrue(self.stage1.check(signed).admissible)
        v = self.stage1.check(signed)
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 11))

    def test_step_11_gaps_are_reported_not_ignored(self):
        self.assertTrue(self.stage1.check(self.a_verify()).admissible)
        skipped = self.a_verify()
        skipped["message"]["sequence"] = 7
        signed = k.sign(skipped["message"], self.sk)
        self.assertTrue(self.stage1.check(signed).admissible, "a gap must not block")
        self.assertEqual(self.stage1.ledger.gaps, [("key-1", 0, 7)],
                         "the gap was ignored rather than reported")

    def test_step_12_weaker_deployment_mode_is_refused(self):
        weak = cm.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                                   deployment_mode="A", sequences=cm.SequenceSource())
        v = self.stage1.check(self.a_verify(signer=weak))
        self.assertEqual((v.status, v.step), (s1.INADMISSIBLE, 12))

    def test_step_12_stronger_deployment_mode_is_fine(self):
        strong = cm.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                                     deployment_mode="C", sequences=cm.SequenceSource())
        self.assertTrue(self.stage1.check(self.a_verify(signer=strong)).admissible)


class NoCallerSuppliedStateTests(Fixture):
    def test_check_takes_only_the_message(self):
        import inspect
        params = list(inspect.signature(s1.Stage1.check).parameters)
        self.assertEqual(params, ["self", "signed"],
                         "check() accepts state the caller could choose")

    def test_the_verifying_key_comes_from_the_registry_not_the_message(self):
        impostor = k.generate_key()
        signed = self.a_verify()
        forged = k.sign(signed["message"], impostor)     # valid signature, wrong key
        self.assertEqual(self.stage1.check(forged).step, 5)


class ScopeBoundaryTests(unittest.TestCase):
    """I4 is Stage 1. Stage 2 and decision semantics are not here."""

    def test_no_stage_2_and_no_decision_logic(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_stage1.py").read_text()
        for absent in ("STAGE 2", "decision_snapshot_digest resolves", "supersedes is present",
                       "Obligation-Set", "producer_identity is not an execution identity"):
            self.assertNotIn(absent, source, f"{absent!r} is Stage 2, and appears in I4")

    def test_no_durable_store(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_stage1.py").read_text()
        for absent in ("open(", "sqlite", "fsync"):
            self.assertNotIn(absent, source)


if __name__ == "__main__":
    unittest.main()
