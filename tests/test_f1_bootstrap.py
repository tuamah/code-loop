"""F1 Integration: the provisioning ceremony, and the pipeline reachable from it.

Until now every F1 test generated its own keys inline, so the pipeline was complete and
unreachable. These tests start from nothing and walk the whole system: provision, sign, admit,
ingest, verify.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_bootstrap as boot                                                  # noqa: E402
import f1_commitments as cm                                                  # noqa: E402
import f1_durable as dur                                                     # noqa: E402
import f1_ingest as ing                                                      # noqa: E402
import f1_kernel as k                                                        # noqa: E402
import f1_registry as r                                                      # noqa: E402
import f1_stage1 as s1                                                       # noqa: E402
import f1_stage2 as s2                                                       # noqa: E402
import f1_state as st                                                        # noqa: E402

D = "sha256:" + "aa" * 32


class Ceremony(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "state.json"
        self.store = st.AuthoritativeStore(self.path)
        self.root_sk, self.sk = k.generate_key(), k.generate_key()

    def provision(self, **over):
        args = dict(project_id="proj-1", repository_identity="git:abc",
                    root_private_key=self.root_sk, verification_private_key=self.sk,
                    verification_key_id="verifier-1", verification_identity="verifier-1",
                    operator="human-1", initial_base_digest=D, policy_baseline=D,
                    gate_baseline=D, obligation_policy_baseline=D)
        args.update(over)
        return boot.provision(self.store, **args)


class ProvisioningTests(Ceremony):
    def test_a_ceremony_establishes_a_reachable_trust_root(self):
        self.assertFalse(boot.already_provisioned(self.store))
        record = self.provision()
        self.assertTrue(boot.already_provisioned(self.store))
        self.assertIsNotNone(record["registry_head"])
        self.assertTrue(record["project_commitment"].startswith("sha256:"))

    def test_the_root_is_never_created_implicitly_and_never_twice(self):
        """§5: an implicitly created root is a root the adversary can create first."""
        self.provision()
        with self.assertRaises(boot.ProvisioningError) as caught:
            self.provision()
        self.assertIn("already exists", str(caught.exception))

    def test_no_private_key_is_ever_written_to_the_store(self):
        self.provision()
        raw = self.path.read_text(encoding="utf-8")
        for secret in (self.root_sk.private_bytes_raw().hex(),
                       self.sk.private_bytes_raw().hex()):
            self.assertNotIn(secret, raw, "a private key reached the authoritative store")

    def test_the_module_neither_generates_nor_persists_private_keys(self):
        import ast
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_bootstrap.py").read_text()
        calls = {n.func.attr for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertNotIn("generate_key", calls)
        self.assertNotIn("private_bytes_raw", calls,
                         "the ceremony serializes private key material")

    def test_a_genesis_the_pipeline_refuses_fails_the_ceremony(self):
        """Found by mutation: nothing tested that a refused genesis aborts provisioning.

        A ceremony that reports success while its PROJECT was never admitted would leave a trust
        root with no project behind it — and a caller with every reason to believe otherwise.
        """
        import f1_stage2 as stage2_module

        real_check = stage2_module.Stage2.check
        stage2_module.Stage2.check = lambda self_, message: s1.Verdict(
            s1.INADMISSIBLE, 2, "refused for this test")
        try:
            with self.assertRaises(boot.ProvisioningError) as caught:
                self.provision()
        finally:
            stage2_module.Stage2.check = real_check
        self.assertIn("not admitted", str(caught.exception))

    def test_the_granted_key_is_scoped_to_the_provisioned_project(self):
        self.provision()
        registry = r.AuthorityRegistry(self.root_sk.public_key(),
                                       store=dur.DurableRegistryStore(self.store))
        self.assertEqual(registry.authorize("verifier-1", "VERIFY", "attest", "proj-1"),
                         r.ADMISSIBLE)
        with self.assertRaises(r.RegistryError):
            registry.authorize("verifier-1", "VERIFY", "attest", "other-project")

    def test_the_ceremony_survives_a_restart(self):
        record = self.provision()
        reopened = st.AuthoritativeStore(self.path)
        self.assertTrue(boot.already_provisioned(reopened))
        registry = r.AuthorityRegistry(self.root_sk.public_key(),
                                       store=dur.DurableRegistryStore(reopened))
        self.assertEqual(registry.head, record["registry_head"])


class ReachabilityTests(Ceremony):
    """The point of the ceremony: the trusted pipeline is now usable from a cold start."""

    def pipeline(self):
        """The SHARED assembly, not a hand-rolled copy: every caller that wired this by hand got
        the head source wrong at least once."""
        return boot.Pipeline(self.store, self.root_sk.public_key(), "proj-1",
                             signing_key_id="verifier-1", signing_private_key=self.sk,
                             signing_identity="verifier-1")

    def test_the_genesis_message_was_admitted_through_the_normal_pipeline(self):
        """The ceremony records out-of-band facts; the PROJECT itself is an ordinary message."""
        record = self.provision()
        self.assertIn(record["project_commitment"],
                      self.pipeline().facts._table("project_commitments"))

    def test_a_policy_can_be_installed_after_provisioning(self):
        record = self.provision()
        pipeline = self.pipeline()
        policy = pipeline.signer.policy(action="create", project="proj-1",
                               project_commitment=record["project_commitment"], epoch=1,
                               previous_commitment="", class_authority_map_digest=D,
                               predicate_class_map_digest=D)
        verdict = pipeline.ingest.apply(policy)
        self.assertTrue(verdict.admissible, verdict.reason)
        self.assertEqual(self.store.head("policy")[1], 1)

    def test_a_head_bearing_field_is_checked_against_its_own_head(self):
        """Pipeline resolves `policy_head` to the policy head, not to whatever is convenient.

        Found by mutation: no test carried a `*_head` field, so the branch that maps a field name
        to a head was unexercised. A RUN naming a policy head that is not current must be refused
        at Stage 1 step 10.
        """
        record = self.provision()
        pipeline = self.pipeline()
        policy = pipeline.signer.policy(
            action="create", project="proj-1",
            project_commitment=record["project_commitment"], epoch=1, previous_commitment="",
            class_authority_map_digest=D, predicate_class_map_digest=D)
        self.assertTrue(pipeline.ingest.apply(policy).admissible)

        stale = pipeline.signer.run(
            project="proj-1", project_commitment=record["project_commitment"],
            task_commitment=D, creation_nonce="n", run_id="run-1",
            parent_run_commitments=[], authorized_base_commitment=D,
            policy_head="sha256:" + "ee" * 32)          # not the head just installed
        verdict = pipeline.ingest.apply(stale)
        self.assertEqual((verdict.status, verdict.step), (s1.INADMISSIBLE, 10))
        self.assertIn("AM-18", verdict.reason)

    def test_the_head_source_derives_the_head_name_from_the_field(self):
        """Tested directly, because no message can distinguish it today.

        `policy_head` is the only `*_head` field in §6's frozen schema, so through messages a
        correct derivation and a hardcoded "policy" behave identically — mutation testing showed
        exactly that, and contriving a fake schema to kill it would be testing a fiction. What can
        be tested is the rule itself: the head name comes from the field, so a head-bearing field
        added by a future amendment is resolved correctly the day it appears rather than silently
        reading the policy head.
        """
        self.provision()
        pipeline = self.pipeline()
        self.assertEqual(pipeline._current_head("RUN", "policy_head"), "")
        with self.store.transaction() as tx:
            tx.set_head("registry_scope_probe", "sha256:" + "5a" * 32, 1)
        self.assertEqual(pipeline._current_head("RUN", "registry_scope_probe_head"),
                         "sha256:" + "5a" * 32,
                         "the head name was not derived from the field")

    def test_an_unprovisioned_store_admits_nothing(self):
        """Fail closed from a cold start: no root means no authority at all (§12)."""
        registry = r.AuthorityRegistry(self.root_sk.public_key(),
                                       store=dur.DurableRegistryStore(self.store))
        with self.assertRaises(r.RegistryError) as caught:
            registry.authorize("verifier-1", "VERIFY", "attest", "proj-1")
        self.assertIn("no accepted head", str(caught.exception))

    def test_a_key_that_was_never_granted_is_refused_after_provisioning(self):
        self.provision()
        registry = r.AuthorityRegistry(self.root_sk.public_key(),
                                       store=dur.DurableRegistryStore(self.store))
        with self.assertRaises(r.RegistryError):
            registry.authorize("someone-else", "VERIFY", "attest", "proj-1")


if __name__ == "__main__":
    unittest.main()
