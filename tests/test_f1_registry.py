"""F1-I2 closure tests: the authority registry (T1A §5, §5.1, §11).

The ten adversarial cases are the point of this file. A registry that resolves keys correctly but
lets a valid key sign a domain it was never granted has implemented a lookup table, not §5.1.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_kernel as k                                                        # noqa: E402
import f1_registry as r                                                      # noqa: E402


def grant_entry(key_id, public_key, *, identity="verifier-1", authority_class="verification",
                types=("VERIFY",), actions=None, projects=("proj-1",)):
    return {
        "key_id": key_id, "public_key": public_key, "identity": identity,
        "authority_class": authority_class, "allowed_message_types": list(types),
        "allowed_actions": actions or {t: sorted(k.ACTIONS[t]) for t in types},
        "allowed_projects": list(projects),
    }


class RegistryFixture(unittest.TestCase):
    def setUp(self):
        self.root_sk = k.generate_key()
        self.registry = r.AuthorityRegistry(self.root_sk.public_key())
        self.signer_sk = k.generate_key()
        self.pub = self.signer_sk.public_key().public_bytes_raw().hex()
        self.seq = 0

    def commit(self, action, grants, *, previous=None, epoch=None, registry=None):
        registry = registry or self.registry
        self.seq += 1
        message = k.message(
            "REGISTRY", action, key_id="registry-root", producer_identity="trust-root",
            sequence=self.seq, signed_at="2026-09-21T00:00:00Z", deployment_mode="B",
            body={"epoch": epoch if epoch is not None else registry.epoch + 1,
                  "previous_commitment": previous if previous is not None
                  else (registry.head or ""),
                  "key_grants_digest": r.digest(grants)})
        return registry.apply(k.sign(message, self.root_sk), grants)

    def add_key(self, **over):
        return self.commit("add_key", [grant_entry("key-1", self.pub, **over)])


class GrantEnforcementTests(RegistryFixture):
    """valid key != every authority (AM-20); valid signature != authorized action."""

    def test_case_1_valid_key_forbidden_message_type(self):
        self.add_key(types=("VERIFY",))
        self.assertEqual(self.registry.authorize("key-1", "VERIFY", "attest", "proj-1"),
                         r.ADMISSIBLE)
        with self.assertRaises(r.RegistryError) as caught:
            self.registry.authorize("key-1", "DECISION", "accept", "proj-1")
        self.assertIn("not granted DECISION", str(caught.exception))

    def test_case_2_allowed_type_forbidden_action(self):
        self.add_key(types=("DECISION",), actions={"DECISION": ["abstain"]},
                     authority_class="acceptance")
        self.assertEqual(self.registry.authorize("key-1", "DECISION", "abstain", "proj-1"),
                         r.ADMISSIBLE)
        with self.assertRaises(r.RegistryError) as caught:
            self.registry.authorize("key-1", "DECISION", "accept", "proj-1")
        self.assertIn("not its action", str(caught.exception))

    def test_case_3_allowed_action_wrong_project(self):
        self.add_key(projects=("proj-1",))
        with self.assertRaises(r.RegistryError):
            self.registry.authorize("key-1", "VERIFY", "attest", "proj-2")

    def test_scoped_grant_refuses_an_unscoped_operation(self):
        self.add_key(projects=("proj-1",))
        with self.assertRaises(r.RegistryError):
            self.registry.authorize("key-1", "VERIFY", "attest", None)

    def test_declared_wildcard_is_honoured(self):
        self.add_key(projects=(r.WILDCARD,))
        self.assertEqual(self.registry.authorize("key-1", "VERIFY", "attest", "anything"),
                         r.ADMISSIBLE)

    def test_unknown_key_fails_closed(self):
        self.add_key()
        with self.assertRaises(r.RegistryError):
            self.registry.authorize("ghost", "VERIFY", "attest", "proj-1")

    def test_grant_cannot_name_an_unknown_type_or_action(self):
        with self.assertRaises(r.RegistryError):
            r.Grant("k", "aa", "i", "verification", ["OVERRIDE"], {"OVERRIDE": ["x"]}, ["p"])
        with self.assertRaises(r.RegistryError):
            r.Grant("k", "aa", "i", "verification", ["VERIFY"], {"VERIFY": ["accept"]}, ["p"])

    def test_grant_with_no_action_is_refused(self):
        with self.assertRaises(r.RegistryError):
            r.Grant("k", "aa", "i", "verification", ["VERIFY"], {"VERIFY": []}, ["p"])

    def test_grant_with_no_project_scope_is_refused(self):
        with self.assertRaises(r.RegistryError):
            r.Grant("k", "aa", "i", "verification", ["VERIFY"], {"VERIFY": ["attest"]}, [])

    def test_executor_holds_no_key_and_may_be_granted_nothing(self):
        """§4: the executor and the verification worker hold no key of any class."""
        for keyless in ("execution", "tool"):
            with self.subTest(authority_class=keyless), self.assertRaises(r.RegistryError):
                r.Grant("k", "aa", "i", keyless, ["REGISTRY"],
                        {"REGISTRY": ["add_key"]}, [r.WILDCARD])


class HeadTests(RegistryFixture):
    """an old valid head is not the current head (AM-18); the caller never chooses it."""

    def test_case_4_stale_but_correctly_signed_head_is_refused(self):
        self.add_key()
        stale = ""                                     # the head before the first commitment
        with self.assertRaises(r.RegistryError) as caught:
            self.commit("add_key", [grant_entry("key-2", self.pub)], previous=stale)
        self.assertIn("is not the current head", str(caught.exception))

    def test_case_7_fork_from_the_same_previous_head_is_refused(self):
        self.add_key()
        head = self.registry.head
        self.commit("add_key", [grant_entry("key-2", self.pub)], previous=head)
        with self.assertRaises(r.RegistryError):
            self.commit("add_key", [grant_entry("key-3", self.pub)], previous=head)

    def test_epoch_must_chain(self):
        self.add_key()
        with self.assertRaises(r.RegistryError):
            self.commit("add_key", [grant_entry("key-2", self.pub)], epoch=99)

    def test_case_9_caller_cannot_supply_a_current_head(self):
        import inspect
        self.assertIsNone(getattr(type(self.registry).head, "fset", None),
                          "head has a setter; the caller can choose the registry head")
        for name in ("authorize", "verification_key", "state_of", "classify_accepted"):
            params = set(inspect.signature(getattr(self.registry, name)).parameters)
            self.assertFalse(params & {"head", "registry", "commitment", "epoch"},
                             f"{name}() lets the caller supply a registry view")

    def test_grants_must_match_the_signed_digest(self):
        signed_grants = [grant_entry("key-1", self.pub)]
        swapped = [grant_entry("key-1", self.pub, projects=(r.WILDCARD,))]
        self.seq += 1
        message = k.message("REGISTRY", "add_key", key_id="registry-root",
                            producer_identity="trust-root", sequence=self.seq,
                            signed_at="t", deployment_mode="B",
                            body={"epoch": 1, "previous_commitment": "",
                                  "key_grants_digest": r.digest(signed_grants)})
        with self.assertRaises(r.RegistryError):
            self.registry.apply(k.sign(message, self.root_sk), swapped)

    def test_registry_must_be_signed_by_the_trust_root(self):
        impostor = k.generate_key()
        self.seq += 1
        message = k.message("REGISTRY", "add_key", key_id="registry-root",
                            producer_identity="trust-root", sequence=self.seq,
                            signed_at="t", deployment_mode="B",
                            body={"epoch": 1, "previous_commitment": "",
                                  "key_grants_digest": r.digest([])})
        with self.assertRaises(k.MessageError):
            self.registry.apply(k.sign(message, impostor), [])

    def test_root_signature_alone_is_not_enough_the_key_id_must_be_the_root(self):
        """Found by mutation: signing with the root key while naming another key_id.

        The signature check alone never reaches this — it passes. Only the key_id check refuses,
        and nothing exercised it until this test.
        """
        self.seq += 1
        message = k.message("REGISTRY", "add_key", key_id="some-other-key",
                            producer_identity="trust-root", sequence=self.seq,
                            signed_at="t", deployment_mode="B",
                            body={"epoch": 1, "previous_commitment": "",
                                  "key_grants_digest": r.digest([])})
        with self.assertRaises(r.RegistryError) as caught:
            self.registry.apply(k.sign(message, self.root_sk), [])
        self.assertIn("signed by the trust root", str(caught.exception))

    def test_no_head_means_fail_closed_for_the_right_reason(self):
        # Asserting the reason, not just the refusal: an empty registry must fail closed by rule,
        # not incidentally because no key happens to be present yet.
        with self.assertRaises(r.RegistryError) as caught:
            self.registry.authorize("key-1", "VERIFY", "attest", "proj-1")
        self.assertIn("no accepted head", str(caught.exception))


class LifecycleTests(RegistryFixture):
    """rotation, retirement, revocation, retention (§11)."""

    def test_case_5_revoked_key_cannot_backdate_signed_at(self):
        """signed_at is the signer's clock; state is read at the TCB acceptance epoch."""
        self.add_key()
        self.commit("revoke_key", [{"key_id": "key-1", "compromised_after_epoch": 1}])
        with self.assertRaises(r.RegistryError) as caught:
            self.registry.authorize("key-1", "VERIFY", "attest", "proj-1")
        self.assertIn("whatever it claims about when it was made", str(caught.exception))

    def test_revocation_needs_a_tcb_epoch_not_a_timestamp(self):
        self.add_key()
        for bad in ("2026-01-01T00:00:00Z", None, -1, True):
            with self.subTest(bound=bad), self.assertRaises(r.RegistryError):
                self.commit("revoke_key",
                            [{"key_id": "key-1", "compromised_after_epoch": bad}])

    def test_signature_accepted_before_the_bound_is_disputed_not_void(self):
        accepted_at = self.add_key()
        self.commit("revoke_key", [{"key_id": "key-1", "compromised_after_epoch": 2}])
        self.assertEqual(self.registry.classify_accepted("key-1", accepted_at), r.DISPUTED)

    def test_signature_accepted_at_or_after_the_bound_is_definitely_invalid(self):
        self.add_key()
        self.commit("revoke_key", [{"key_id": "key-1", "compromised_after_epoch": 2}])
        for epoch in (2, 3):
            with self.subTest(epoch=epoch), self.assertRaises(r.RegistryError):
                self.registry.classify_accepted("key-1", epoch)

    def test_case_6_retired_key_cannot_sign_new_material(self):
        self.add_key()
        self.commit("retire_key", [{"key_id": "key-1"}])
        with self.assertRaises(r.RegistryError) as caught:
            self.registry.authorize("key-1", "VERIFY", "attest", "proj-1")
        self.assertIn("retired", str(caught.exception))

    def test_case_8_duplicate_key_id_with_a_different_public_key_is_refused(self):
        self.add_key()
        other = k.generate_key().public_key().public_bytes_raw().hex()
        with self.assertRaises(r.RegistryError) as caught:
            self.commit("add_key", [grant_entry("key-1", other)])
        self.assertIn("never rebound", str(caught.exception))

    def test_case_10_historical_keys_are_never_forgotten(self):
        """Forgetting a key makes every decision it signed unverifiable (§11 retention)."""
        self.add_key()
        self.commit("retire_key", [{"key_id": "key-1"}])
        self.assertEqual(self.registry.verification_key("key-1"), self.pub)
        self.commit("revoke_key", [{"key_id": "key-1", "compromised_after_epoch": 3}])
        self.assertEqual(self.registry.verification_key("key-1"), self.pub,
                         "a revoked key must still resolve for historical verification")
        self.assertEqual(self.registry.state_of("key-1"), r.REVOKED)

    def test_rotation_mints_a_new_key_id_and_leaves_history_alone(self):
        self.add_key()
        new_pub = k.generate_key().public_key().public_bytes_raw().hex()
        self.commit("add_key", [grant_entry("key-2", new_pub)])
        self.commit("retire_key", [{"key_id": "key-1"}])
        self.assertEqual(self.registry.verification_key("key-1"), self.pub)
        self.assertEqual(self.registry.authorize("key-2", "VERIFY", "attest", "proj-1"),
                         r.ADMISSIBLE)

    def test_lifecycle_action_on_an_unknown_key_fails_closed(self):
        with self.assertRaises(r.RegistryError):
            self.commit("retire_key", [{"key_id": "ghost"}])

    def test_root_rotation_is_out_of_scope_and_says_so(self):
        self.add_key()
        with self.assertRaises(r.RegistryError) as caught:
            self.commit("rotate_root", [{"key_id": "key-1"}])
        self.assertIn("F1-T2", str(caught.exception))


class StoreBoundaryTests(RegistryFixture):
    """I2 proves semantics; I5 swaps the backend without touching a rule above it."""

    def test_a_refused_commitment_leaves_nothing_behind(self):
        """Found by probing, not by a test: a rejected apply() used to half-commit.

        One bad entry in a batch left the earlier keys ACTIVE and burned an acceptance epoch while
        the head stayed unset — so a key the registry had never accepted would authorize as soon as
        any later commitment set a head.
        """
        good = grant_entry("key-1", self.pub)
        bad = grant_entry("key-2", self.pub, actions={"VERIFY": ["accept"]})   # not VERIFY's verb
        before = self.registry.acceptance_epoch
        with self.assertRaises(r.RegistryError):
            self.commit("add_key", [good, bad])
        self.assertIsNone(self.registry.head)
        self.assertEqual(self.registry.acceptance_epoch, before, "a refused apply burned an epoch")
        with self.assertRaises(r.RegistryError):
            self.registry.state_of("key-1")

    def test_a_refused_commitment_does_not_disturb_existing_state(self):
        self.add_key()
        head, epoch, accepted = self.registry.head, self.registry.epoch, \
            self.registry.acceptance_epoch
        with self.assertRaises(r.RegistryError):
            self.commit("add_key", [grant_entry("key-2", self.pub),
                                    grant_entry("key-3", self.pub, actions={"VERIFY": ["accept"]})])
        self.assertEqual((self.registry.head, self.registry.epoch,
                          self.registry.acceptance_epoch), (head, epoch, accepted))
        with self.assertRaises(r.RegistryError):
            self.registry.state_of("key-2")
        self.assertEqual(self.registry.state_of("key-1"), r.ACTIVE)

    def test_the_registry_reaches_into_no_concrete_storage(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_registry.py").read_text()
        registry_class = source[source.index("class AuthorityRegistry"):]
        for leak in ("self._keys", "self._chain", "self._head", "self._epoch =",
                     "self._acceptance"):
            self.assertNotIn(leak, registry_class,
                             f"AuthorityRegistry touches {leak!r} directly; I5 could not swap the "
                             f"backend without changing the semantics above it")

    def test_the_store_interface_can_express_a_transaction(self):
        # §10.1 requires validate-and-mutate to be one operation. A store that cannot express a
        # transaction boundary cannot be made to satisfy that later without reshaping callers.
        for required in ("transaction", "commit"):
            self.assertTrue(callable(getattr(r.RegistryStore, required, None)))

    def test_lifecycle_changes_are_written_back_through_put_key(self):
        """Found by I5b's durable wiring, not by this suite.

        Retirement and revocation mutated the object get_key returned and never called put_key.
        That worked only because the in-memory store hands back a live reference — an aliasing
        assumption the RegistryStore interface never made. A store that deserializes silently
        dropped both. This asserts the contract the code actually depends on.
        """
        class NoAliasing(r.InMemoryRegistryStore):
            """Returns a copy, like any store that serializes."""

            def get_key(self, key_id):
                import copy
                state = super().get_key(key_id)
                return copy.deepcopy(state) if state is not None else None

        registry = r.AuthorityRegistry(self.root_sk.public_key(), store=NoAliasing())
        self.commit("add_key", [grant_entry("key-1", self.pub)], registry=registry)
        self.commit("retire_key", [{"key_id": "key-1"}], registry=registry)
        self.assertEqual(registry.state_of("key-1"), r.RETIRED,
                         "retirement was lost because it was never written back")
        self.commit("revoke_key", [{"key_id": "key-1", "compromised_after_epoch": 2}],
                    registry=registry)
        self.assertEqual(registry.state_of("key-1"), r.REVOKED)

    def test_commit_outside_a_transaction_is_refused(self):
        # Found by mutation. Nothing in I2's flow reaches it, but I5 writes the next store against
        # this interface, and a commit() that silently no-ops outside a transaction is how a
        # durable backend quietly loses a write.
        with self.assertRaises(r.RegistryError):
            r.InMemoryRegistryStore().commit()

    def test_semantics_do_not_depend_on_the_backend_being_in_memory(self):
        """The same rules must hold against any store implementing the interface."""
        class Recording(r.InMemoryRegistryStore):
            calls: list[str] = []

            def transaction(self):
                Recording.calls.append("transaction")
                staged = Recording(self._keys, self._chain, self._head,
                                   self._epoch, self._acceptance)
                staged._parent = self
                return staged

        registry = r.AuthorityRegistry(self.root_sk.public_key(), store=Recording())
        self.commit("add_key", [grant_entry("key-1", self.pub)], registry=registry)
        self.assertEqual(registry.authorize("key-1", "VERIFY", "attest", "proj-1"), r.ADMISSIBLE)
        with self.assertRaises(r.RegistryError):
            registry.authorize("key-1", "DECISION", "accept", "proj-1")
        self.assertIn("transaction", Recording.calls)


class VerificationIsNotAuthorizationTests(RegistryFixture):
    """Resolving a key to check an old signature is never permission to sign new material."""

    def test_revoked_key_verifies_history_but_authorizes_nothing(self):
        self.add_key()
        self.commit("revoke_key", [{"key_id": "key-1", "compromised_after_epoch": 1}])
        self.assertEqual(self.registry.verification_key("key-1"), self.pub)
        with self.assertRaises(r.RegistryError):
            self.registry.authorize("key-1", "VERIFY", "attest", "proj-1")

    def test_retired_key_verifies_history_but_authorizes_nothing(self):
        self.add_key()
        self.commit("retire_key", [{"key_id": "key-1"}])
        self.assertEqual(self.registry.verification_key("key-1"), self.pub)
        with self.assertRaises(r.RegistryError):
            self.registry.authorize("key-1", "VERIFY", "attest", "proj-1")


class ScopeBoundaryTests(unittest.TestCase):
    """I2 implements §5.1 and nothing above it."""

    def test_registry_does_not_implement_stage_1_or_stage_2(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_registry.py").read_text()
        for absent in ("STAGE 1", "STAGE 2", "admissibility procedure", "decision_snapshot"):
            self.assertNotIn(absent, source,
                             f"{absent!r} appears in I2; Stage 1 is I4 and Stage 2 is I6")

    def test_authority_classes_match_the_contract_table(self):
        contract = (Path(__file__).resolve().parents[1]
                    / "docs" / "f1-t1a-trust-core.md").read_text(encoding="utf-8")
        for declared in ("execution", "verification", "acceptance", "freeze", "human", "tool"):
            self.assertIn(f"`{declared}`", contract)
            self.assertIn(declared, r.AUTHORITY_CLASSES)


if __name__ == "__main__":
    unittest.main()
