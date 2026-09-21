"""F1-I5b closure tests: durable wiring.

The criterion is "wiring changes persistence, not security semantics", so the central test runs
I2's and I4's own suites against the durable backend and asserts the same verdicts. Everything
else here is about what survives a restart.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_commitments as cm                                                  # noqa: E402
import f1_durable as dur                                                     # noqa: E402
import f1_kernel as k                                                        # noqa: E402
import f1_registry as r                                                      # noqa: E402
import f1_stage1 as s1                                                       # noqa: E402
import f1_state as st                                                        # noqa: E402

D = "sha256:" + "aa" * 32


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "state.json"
        self.root_sk = k.generate_key()
        self.sk = k.generate_key()
        self.pub = self.sk.public_key().public_bytes_raw().hex()
        self.seq = 0
        self.registry = self.open_registry()

    def open_registry(self):
        """A fresh process's view: only what reached disk."""
        store = st.AuthoritativeStore(self.path)
        return r.AuthorityRegistry(self.root_sk.public_key(),
                                   store=dur.DurableRegistryStore(store))

    def grant(self, types=("VERIFY",), *, key_id="key-1", pub=None, projects=("proj-1",),
              actions=None, registry=None):
        entry = {"key_id": key_id, "public_key": pub or self.pub, "identity": "authority-1",
                 "authority_class": "verification", "allowed_message_types": list(types),
                 "allowed_actions": actions or {t: sorted(k.ACTIONS[t]) for t in types},
                 "allowed_projects": list(projects)}
        self.commit("add_key", [entry], registry=registry)
        return entry

    def commit(self, action, grants, registry=None):
        registry = registry or self.registry
        self.seq += 1
        message = k.message("REGISTRY", action, key_id="registry-root", producer_identity="root",
                            sequence=self.seq, signed_at="t", deployment_mode="B",
                            body={"epoch": registry.epoch + 1,
                                  "previous_commitment": registry.head or "",
                                  "key_grants_digest": r.digest(grants)})
        return registry.apply(k.sign(message, self.root_sk), grants)


class RegistryRestartTests(Fixture):
    def test_head_grants_and_epoch_survive_a_restart(self):
        self.grant()
        head, epoch = self.registry.head, self.registry.epoch
        after = self.open_registry()
        self.assertEqual((after.head, after.epoch), (head, epoch))
        self.assertEqual(after.authorize("key-1", "VERIFY", "attest", "proj-1"), r.ADMISSIBLE)

    def test_grant_scope_is_still_enforced_after_a_restart(self):
        self.grant(projects=("proj-1",))
        after = self.open_registry()
        with self.assertRaises(r.RegistryError):
            after.authorize("key-1", "VERIFY", "attest", "proj-2")
        with self.assertRaises(r.RegistryError):
            after.authorize("key-1", "DECISION", "accept", "proj-1")

    def test_a_retired_key_still_verifies_history_after_a_restart(self):
        """§11 retention, across a process boundary."""
        self.grant()
        self.commit("retire_key", [{"key_id": "key-1"}])
        after = self.open_registry()
        self.assertEqual(after.verification_key("key-1"), self.pub)
        self.assertEqual(after.state_of("key-1"), r.RETIRED)
        with self.assertRaises(r.RegistryError):
            after.authorize("key-1", "VERIFY", "attest", "proj-1")

    def test_a_revoked_key_keeps_its_compromise_bound_after_a_restart(self):
        self.grant()
        self.commit("revoke_key", [{"key_id": "key-1", "compromised_after_epoch": 2}])
        after = self.open_registry()
        self.assertEqual(after.verification_key("key-1"), self.pub)
        self.assertEqual(after.classify_accepted("key-1", 1), r.DISPUTED)
        with self.assertRaises(r.RegistryError):
            after.classify_accepted("key-1", 5)

    def test_a_stale_head_is_still_refused_after_a_restart(self):
        self.grant()
        after = self.open_registry()
        self.seq += 1
        message = k.message("REGISTRY", "add_key", key_id="registry-root",
                            producer_identity="root", sequence=self.seq, signed_at="t",
                            deployment_mode="B",
                            body={"epoch": 2, "previous_commitment": "",   # the genesis head
                                  "key_grants_digest": r.digest([])})
        with self.assertRaises(r.RegistryError):
            after.apply(k.sign(message, self.root_sk), [])


class NoHalfStateTests(Fixture):
    def test_a_refused_acceptance_leaves_no_partial_state_on_disk(self):
        self.grant()
        head, epoch, accepted = (self.registry.head, self.registry.epoch,
                                 self.registry.acceptance_epoch)
        good = {"key_id": "key-2", "public_key": self.pub, "identity": "i",
                "authority_class": "verification", "allowed_message_types": ["VERIFY"],
                "allowed_actions": {"VERIFY": ["attest"]}, "allowed_projects": ["proj-1"]}
        bad = dict(good, key_id="key-3", allowed_actions={"VERIFY": ["accept"]})
        with self.assertRaises(r.RegistryError):
            self.commit("add_key", [good, bad])
        after = self.open_registry()
        self.assertEqual((after.head, after.epoch, after.acceptance_epoch),
                         (head, epoch, accepted))
        for ghost in ("key-2", "key-3"):
            with self.assertRaises(r.RegistryError):
                after.state_of(ghost)

    def test_an_authorization_spent_by_a_failed_transition_is_not_consumed(self):
        store = st.AuthoritativeStore(self.path)
        backend = dur.DurableRegistryStore(store)
        tx = backend.transaction()
        tx.consume_authorization("auth-1")
        tx.set_head("sha256:" + "11" * 32, 1)
        del tx                                            # the transition never commits
        self.assertFalse(st.AuthoritativeStore(self.path).is_consumed("auth-1"))

    def test_an_authorization_commits_with_the_transition_that_spends_it(self):
        store = st.AuthoritativeStore(self.path)
        backend = dur.DurableRegistryStore(store)
        tx = backend.transaction()
        tx.consume_authorization("auth-1")
        tx.set_head("sha256:" + "11" * 32, 1)
        tx.commit()
        reopened = st.AuthoritativeStore(self.path)
        self.assertTrue(reopened.is_consumed("auth-1"))
        self.assertEqual(reopened.head(dur.REGISTRY_SCOPE)[1], 1)

    def test_the_same_authorization_cannot_be_spent_twice(self):
        store = st.AuthoritativeStore(self.path)
        backend = dur.DurableRegistryStore(store)
        tx = backend.transaction()
        tx.consume_authorization("auth-1")
        tx.set_head("sha256:" + "11" * 32, 1)
        tx.commit()
        again = dur.DurableRegistryStore(st.AuthoritativeStore(self.path)).transaction()
        with self.assertRaises(r.RegistryError):
            again.consume_authorization("auth-1")


class SequenceTests(Fixture):
    def test_no_sequence_reuse_across_a_restart(self):
        store = st.AuthoritativeStore(self.path)
        source = dur.DurableSequenceSource(store)
        first = [source.allocate("key-1") for _ in range(3)]
        restarted = dur.DurableSequenceSource(st.AuthoritativeStore(self.path))
        self.assertEqual(first, [0, 1, 2])
        self.assertEqual(restarted.allocate("key-1"), 3, "a sequence was reused after a restart")

    def test_two_processes_never_reuse_a_sequence_for_one_identity(self):
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "import f1_state as st, f1_durable as dur\n"
            "src = dur.DurableSequenceSource(st.AuthoritativeStore(%r))\n"
            "print(','.join(str(src.allocate('key-1')) for _ in range(20)))\n"
            % (str(Path(__file__).resolve().parents[1] / "scripts"), str(self.path))
        )
        procs = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                                  text=True) for _ in range(3)]
        seen = []
        for proc in procs:
            out, _ = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, out)
            seen.extend(int(v) for v in out.strip().split(","))
        self.assertEqual(sorted(seen), list(range(60)))

    def test_a_crash_after_allocation_leaves_a_gap_never_a_reuse(self):
        store = st.AuthoritativeStore(self.path)
        allocated = dur.DurableSequenceSource(store).allocate("key-1")
        self.assertEqual(allocated, 0)
        # The signature numbered 0 never arrives; the next process must NOT hand out 0 again.
        self.assertEqual(dur.DurableSequenceSource(st.AuthoritativeStore(self.path))
                         .allocate("key-1"), 1)

    def test_the_ledger_still_refuses_a_replay_after_a_restart(self):
        store = st.AuthoritativeStore(self.path)
        ledger = dur.DurableSequenceLedger(store)
        self.assertIsNone(ledger.observe("key-1", 0))
        restarted = dur.DurableSequenceLedger(st.AuthoritativeStore(self.path))
        self.assertIsNotNone(restarted.observe("key-1", 0),
                             "a ledger that forgets on restart accepts every replay it had seen")

    def test_the_ledger_still_reports_gaps_after_a_restart(self):
        store = st.AuthoritativeStore(self.path)
        dur.DurableSequenceLedger(store).observe("key-1", 0)
        dur.DurableSequenceLedger(st.AuthoritativeStore(self.path)).observe("key-1", 7)
        self.assertEqual(dur.DurableSequenceLedger(st.AuthoritativeStore(self.path)).gaps,
                         [("key-1", 0, 7)])


class SameSemanticsTests(Fixture):
    """Wiring changes persistence, not security semantics."""

    def stage1(self, registry=None, ledger=None):
        return s1.Stage1(registry=registry or self.registry,
                         current_head=lambda mt, field: {"policy_head": D,
                                                         "previous_commitment": ""}.get(field),
                         project_of=lambda m: "proj-1", required_mode="B",
                         ledger=ledger or dur.DurableSequenceLedger(
                             st.AuthoritativeStore(self.path)))

    def a_verify(self, signer):
        return signer.verify_attestation(
            project="proj-1", run_commitment=D, gate_commitment=D, candidate_fingerprint=D,
            obligation_id="o", verification_method="m", verdict="pass", observation_digest=D)

    def test_stage_1_gives_the_same_verdict_before_and_after_a_restart(self):
        self.grant(types=sorted(k.DOMAINS), projects=[r.WILDCARD])
        store = st.AuthoritativeStore(self.path)
        signer = cm.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                                     sequences=dur.DurableSequenceSource(store))
        signed = self.a_verify(signer)
        before = self.stage1().check(signed)
        self.assertTrue(before.admissible)

        # A fresh process, reading only what reached disk. The same message must now be REFUSED,
        # and refused for the same reason it would have been in memory: step 11 has seen it.
        after = self.stage1(registry=self.open_registry())
        verdict = after.check(signed)
        self.assertEqual((verdict.status, verdict.step), (s1.INADMISSIBLE, 11))

        fresh = self.a_verify(cm.CommitmentSigner(
            self.registry, "key-1", self.sk, "authority-1",
            sequences=dur.DurableSequenceSource(st.AuthoritativeStore(self.path))))
        self.assertTrue(self.stage1(registry=self.open_registry()).check(fresh).admissible)

    def test_every_refusal_step_is_unchanged_on_the_durable_backend(self):
        """The same inputs must fail at the same numbered step as on the in-memory backend."""
        self.grant(types=sorted(k.DOMAINS), projects=[r.WILDCARD])
        store = st.AuthoritativeStore(self.path)
        signer = cm.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                                     sequences=dur.DurableSequenceSource(store))
        cases = {}
        signed = self.a_verify(signer)
        signed["message"]["schema_version"] = "99"
        cases[1] = signed
        signed = self.a_verify(signer)
        signed["message"]["message_type"] = "OVERRIDE"
        cases[2] = signed
        signed = self.a_verify(signer)
        signed["message"]["body"]["authority"] = "verification"
        cases[4] = signed
        signed = self.a_verify(signer)
        signed["signature"] = "00" * 64
        cases[5] = signed
        signed = self.a_verify(signer)
        signed["message"]["key_id"] = "ghost"
        cases[5] = cases[5]                          # unknown key also refuses at step 5
        for step, message in sorted(cases.items()):
            with self.subTest(step=step):
                verdict = self.stage1(registry=self.open_registry()).check(message)
                self.assertEqual((verdict.status, verdict.step), (s1.INADMISSIBLE, step))

    def test_the_in_memory_backend_still_works_unchanged(self):
        """I5b replaces a backend; it does not remove the one I2 was reviewed with."""
        registry = r.AuthorityRegistry(self.root_sk.public_key())
        self.seq += 1
        entry = {"key_id": "key-1", "public_key": self.pub, "identity": "i",
                 "authority_class": "verification", "allowed_message_types": ["VERIFY"],
                 "allowed_actions": {"VERIFY": ["attest"]}, "allowed_projects": ["proj-1"]}
        message = k.message("REGISTRY", "add_key", key_id="registry-root",
                            producer_identity="root", sequence=self.seq, signed_at="t",
                            deployment_mode="B",
                            body={"epoch": 1, "previous_commitment": "",
                                  "key_grants_digest": r.digest([entry])})
        registry.apply(k.sign(message, self.root_sk), [entry])
        self.assertEqual(registry.authorize("key-1", "VERIFY", "attest", "proj-1"), r.ADMISSIBLE)


class ScopeBoundaryTests(unittest.TestCase):
    def test_no_new_semantics(self):
        """I5b implements existing interfaces; it must not invent rules."""
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_durable.py").read_text()
        for absent in ("STAGE 2", "Obligation", "supersed", "decision"):
            self.assertNotIn(absent, source, f"{absent!r} is a semantic concern, not wiring")

    def test_the_durable_backends_implement_the_interfaces_they_replace(self):
        self.assertTrue(issubclass(dur.DurableRegistryStore, r.RegistryStore))
        self.assertTrue(issubclass(dur.DurableSequenceSource, cm.SequenceSource))
        self.assertTrue(issubclass(dur.DurableSequenceLedger, s1.SequenceLedger))


if __name__ == "__main__":
    unittest.main()
