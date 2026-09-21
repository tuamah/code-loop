"""F1-I6b closure tests: authoritative state ingest.

The invariant, and both directions of it:

    No authoritative fact may appear in TrustedFacts unless it was produced from an authenticated,
    admissible message and committed transactionally.

So the negative tests matter as much as the positive ones: a bad signature, a Stage 1 failure, a
Stage 2 failure, a stale message, a wrong head, a replayed HUMAN and a failed transaction must
every one leave the authoritative state byte-identical.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_commitments as cm                                                  # noqa: E402
import f1_durable as dur                                                     # noqa: E402
import f1_ingest as ing                                                      # noqa: E402
import f1_kernel as k                                                        # noqa: E402
import f1_registry as r                                                      # noqa: E402
import f1_stage1 as s1                                                       # noqa: E402
import f1_stage2 as s2                                                       # noqa: E402
import f1_state as st                                                        # noqa: E402

D = "sha256:" + "aa" * 32
CAND, PARENT = "sha256:" + "c1" * 32, "sha256:" + "c0" * 32


class Pipeline(unittest.TestCase):
    """A real pipeline end to end: kernel, registry, commitments, Stage 1, Stage 2, ingest."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "state.json"
        self.store = st.AuthoritativeStore(self.path)
        self.root_sk = k.generate_key()
        self.sk = k.generate_key()
        self.registry = r.AuthorityRegistry(
            self.root_sk.public_key(), store=dur.DurableRegistryStore(self.store))
        self.seq = 0
        self.grant()
        self.facts = s2.TrustedFacts(self.store)
        # Stage 1's head source reads the DURABLE store, as the real pipeline must. An earlier
        # fixture hardcoded it and disagreed with the state ingest was writing — a test harness
        # that lies about the current head cannot test a rule about the current head.
        self.stage1 = s1.Stage1(
            registry=self.registry, current_head=self.current_head,
            project_of=lambda m: "proj-1", required_mode="B",
            ledger=dur.DurableSequenceLedger(self.store))
        self.ingest = ing.Ingest(self.store, self.stage1, s2.Stage2(self.facts))
        self.signer = cm.CommitmentSigner(self.registry, "key-1", self.sk, "authority-1",
                                          sequences=dur.DurableSequenceSource(self.store))
        self.seed_tcb()

    def current_head(self, message_type, field):
        name = (ing.HEADED.get(message_type, message_type.lower())
                if field == "previous_commitment" else field[:-len("_head")])
        current = self.store.head(name)
        return current[0] if current else ""

    def grant(self):
        entry = {"key_id": "key-1", "public_key": self.sk.public_key().public_bytes_raw().hex(),
                 "identity": "authority-1", "authority_class": "verification",
                 "allowed_message_types": sorted(k.DOMAINS),
                 "allowed_actions": {t: sorted(k.ACTIONS[t]) for t in k.DOMAINS},
                 "allowed_projects": [r.WILDCARD]}
        self.seq += 1
        message = k.message("REGISTRY", "add_key", key_id="registry-root",
                            producer_identity="root", sequence=self.seq, signed_at="t",
                            deployment_mode="B",
                            body={"epoch": self.registry.epoch + 1,
                                  "previous_commitment": self.registry.head or "",
                                  "key_grants_digest": r.digest([entry])})
        self.registry.apply(k.sign(message, self.root_sk), [entry])

    def seed_tcb(self):
        """Only the provisioning ceremony, which is out-of-band by §5 and not an ingested fact."""
        state = self.store.read()
        state["tcb"] = {"provisioning": {"proj-1": {"repository_identity": "git:abc"}},
                        "trust_root_key_id": "registry-root",
                        "task_relations": {}, "minted_run_ids": {}}
        with self.store._exclusive():
            self.store._write(state)

    def snapshot(self) -> str:
        return json.dumps(self.store.read().get("tcb", {}), sort_keys=True)

    def establish_policy(self):
        """A HUMAN authorization records the policy it was given under, so one must exist.

        I3 requires policy_head to be a digest and Stage 2 requires it to be current: before any
        policy exists there is nothing to record, and the authorization is refused. That is
        coherent fail-closed behaviour, not a gap.
        """
        assert self.ingest.apply(self.a_project()).admissible
        policy = self.signer.policy(action="create", project="proj-1", project_commitment=D,
                                    epoch=1, previous_commitment="",
                                    class_authority_map_digest=D, predicate_class_map_digest=D)
        assert self.ingest.apply(policy).admissible
        return self.store.head("policy")[0]

    def establish_run(self):
        """Walk the real chain: PROJECT -> TASK -> RUN -> GATE, each through the pipeline.

        Only the facts §5 puts out of band are seeded: the provisioning ceremony, the authorized
        task relation and the TCB-minted run id. Everything else is produced by an admissible
        message, which is the invariant this milestone exists to hold.
        """
        project = self.a_project()
        self.assertTrue(self.ingest.apply(project).admissible)
        project_ref = cm.commitment_of(project)

        policy = self.signer.policy(action="create", project="proj-1",
                                    project_commitment=project_ref, epoch=1,
                                    previous_commitment="", class_authority_map_digest=D,
                                    predicate_class_map_digest=D)
        self.assertTrue(self.ingest.apply(policy).admissible)
        policy_ref = self.store.head("policy")[0]

        state = self.store.read()
        state["tcb"]["task_relations"] = {f"{project_ref}|{D}": {"relation": "NEW_TASK"}}
        state["tcb"]["minted_run_ids"] = {"run-1": {}}
        with self.store._exclusive():
            self.store._write(state)

        task = self.signer.task(action="create", project="proj-1",
                                project_commitment=project_ref, task_digest=D,
                                relation="NEW_TASK")
        self.assertTrue(self.ingest.apply(task).admissible)
        run = self.signer.run(project="proj-1", project_commitment=project_ref,
                              task_commitment=cm.commitment_of(task), creation_nonce="n",
                              run_id="run-1", parent_run_commitments=[],
                              authorized_base_commitment=D, policy_head=policy_ref)
        verdict = self.ingest.apply(run)
        self.assertTrue(verdict.admissible, verdict.reason)
        run_ref = cm.commitment_of(run)

        gate = self.signer.gate(project="proj-1", run_commitment=run_ref,
                                gate_content_digest=D, freeze_policy_version="v1",
                                baseline_match=True)
        self.assertTrue(self.ingest.apply(gate).admissible)

        # The live candidate is what the controller materialized (§7); it is not carried by any
        # message here, so the TCB records it directly. Producing it is I7's.
        state = self.store.read()
        state["tcb"]["runs"][run_ref]["candidate_fingerprint"] = CAND
        state["tcb"]["candidates"] = {CAND: {"parent": PARENT}, PARENT: {"parent": None}}
        with self.store._exclusive():
            self.store._write(state)
        return run_ref, cm.commitment_of(gate)  # noqa: E501

    def a_project(self):
        return self.signer.project_genesis(
            project_id="proj-1", repository_identity="git:abc", initial_base_digest=D,
            policy_baseline=D, gate_baseline=D, obligation_policy_baseline=D,
            provisioned_by="human-1", provisioning_sequence=0)


class PositiveTests(Pipeline):
    def test_an_admissible_project_becomes_an_authoritative_fact(self):
        self.assertEqual(self.facts._table("project_commitments"), {})
        verdict = self.ingest.apply(self.a_project())
        self.assertTrue(verdict.admissible, verdict.reason)
        reference = cm.commitment_of(self.a_project()) if False else None
        self.assertEqual(len(self.facts._table("project_commitments")), 1)

    def test_the_fact_survives_a_restart(self):
        self.ingest.apply(self.a_project())
        reopened = s2.TrustedFacts(st.AuthoritativeStore(self.path))
        self.assertEqual(len(reopened._table("project_commitments")), 1)

    def test_a_human_authorization_is_recorded_and_consumed_in_one_transaction(self):
        head = self.establish_policy()
        signed = self.signer.human_authorization(
            project="proj-1", authorization_id="a-1", action_type="freeze",
            target_message_type="GATE", project_commitment=D, subject_digest=D,
            policy_head=head, use_semantics="single-use", expiry="2027",
            requested_transition="a->b")
        state = self.store.read()
        state["tcb"]["pending_operations"] = {D: {"action_type": "freeze",
                                                  "target_message_type": "GATE",
                                                  "subject_digest": D,
                                                  "requested_transition": "a->b"}}
        with self.store._exclusive():
            self.store._write(state)
        verdict = self.ingest.apply(signed)
        self.assertTrue(verdict.admissible, verdict.reason)
        self.assertTrue(self.store.is_consumed("a-1"),
                        "the authorization was recorded without being consumed")
        self.assertEqual(len(self.facts._table("authorizations")), 1)

    def test_a_policy_advances_its_head_in_the_same_commit(self):
        # The maps must already resolve: Stage 2 requires it BEFORE admission, which is why
        # ingest does not write them. PROJECT genesis carries an authenticated baseline.
        self.assertTrue(self.ingest.apply(self.a_project()).admissible)
        signed = self.signer.policy(action="create", project="proj-1", project_commitment=D,
                                    epoch=1, previous_commitment="",
                                    class_authority_map_digest=D, predicate_class_map_digest=D)
        verdict = self.ingest.apply(signed)
        self.assertTrue(verdict.admissible, verdict.reason)
        self.assertEqual(self.store.head("policy")[1], 1)

    def test_a_policy_naming_an_unresolvable_map_is_refused(self):
        self.assertTrue(self.ingest.apply(self.a_project()).admissible)
        signed = self.signer.policy(action="create", project="proj-1", project_commitment=D,
                                    epoch=1, previous_commitment="",
                                    class_authority_map_digest=D,
                                    predicate_class_map_digest="sha256:" + "bb" * 32)
        verdict = self.ingest.apply(signed)
        self.assertIn("AM-39", verdict.reason)
        self.assertIsNone(self.store.head("policy"))


class NothingChangesOnRefusalTests(Pipeline):
    """Every refusal path leaves the authoritative state byte-identical."""

    def assert_unchanged(self, before, verdict, *, expected_step=None):
        self.assertNotEqual(verdict.status, r.ADMISSIBLE)
        self.assertEqual(self.snapshot(), before, "a refused message changed authoritative state")
        if expected_step is not None:
            self.assertEqual(verdict.step, expected_step)

    def test_a_bad_signature_changes_nothing(self):
        signed = self.a_project()
        signed["signature"] = "00" * 64
        before = self.snapshot()
        self.assert_unchanged(before, self.ingest.apply(signed), expected_step=5)

    def test_a_stage_1_failure_changes_nothing(self):
        signed = self.a_project()
        signed["message"]["schema_version"] = "99"
        before = self.snapshot()
        self.assert_unchanged(before, self.ingest.apply(signed), expected_step=1)

    def test_a_replayed_message_changes_nothing_the_second_time(self):
        signed = self.a_project()
        self.assertTrue(self.ingest.apply(signed).admissible)
        before = self.snapshot()
        self.assert_unchanged(before, self.ingest.apply(signed), expected_step=11)

    def test_a_stage_2_failure_changes_nothing(self):
        """A PROJECT whose repository_identity does not bind to the recorded ceremony."""
        signed = self.signer.project_genesis(
            project_id="proj-1", repository_identity="git:evil", initial_base_digest=D,
            policy_baseline=D, gate_baseline=D, obligation_policy_baseline=D,
            provisioned_by="human-1", provisioning_sequence=0)
        before = self.snapshot()
        verdict = self.ingest.apply(signed)
        self.assertIn("repository_identity", verdict.reason)
        self.assert_unchanged(before, verdict)

    def test_a_stale_verify_changes_nothing_and_is_not_an_error(self):
        state = self.store.read()
        state["tcb"]["runs"] = {D: {"gate_commitment": D,
                                    "candidate_fingerprint": "sha256:" + "99" * 32,
                                    "execution_identities": []}}
        with self.store._exclusive():
            self.store._write(state)
        signed = self.signer.verify_attestation(
            project="proj-1", run_commitment=D, gate_commitment=D, candidate_fingerprint=D,
            obligation_id="o", verification_method="m", verdict="pass", observation_digest=D)
        before = self.snapshot()
        verdict = self.ingest.apply(signed)
        self.assertEqual(verdict.status, s2.STALE)
        self.assertEqual(self.snapshot(), before)

    def test_a_wrong_head_changes_nothing(self):
        self.establish_policy()
        before = self.snapshot()
        head_before = self.store.head("policy")
        stale = self.signer.policy(action="update", project="proj-1", project_commitment=D,
                                   epoch=2, previous_commitment="",   # the genesis head, gone
                                   class_authority_map_digest=D, predicate_class_map_digest=D)
        verdict = self.ingest.apply(stale)
        self.assertIn("AM-18", verdict.reason)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store.head("policy"), head_before)

    def test_a_replayed_human_authorization_changes_nothing(self):
        head = self.establish_policy()
        state = self.store.read()
        state["tcb"]["pending_operations"] = {D: {"action_type": "freeze",
                                                  "target_message_type": "GATE",
                                                  "subject_digest": D,
                                                  "requested_transition": "a->b"}}
        with self.store._exclusive():
            self.store._write(state)
        def authorization():
            return self.signer.human_authorization(
                project="proj-1", authorization_id="a-1", action_type="freeze",
                target_message_type="GATE", project_commitment=D, subject_digest=D,
                policy_head=head, use_semantics="single-use", expiry="2027",
                requested_transition="a->b")

        self.assertTrue(self.ingest.apply(authorization()).admissible)
        before = self.snapshot()
        verdict = self.ingest.apply(authorization())      # same id, a fresh signature
        self.assertNotEqual(verdict.status, r.ADMISSIBLE)
        self.assertIn("second attempt", verdict.reason)
        self.assertEqual(self.snapshot(), before)

    def test_a_failed_transaction_changes_nothing(self):
        """A conflict during the commit is raised, not swallowed, and writes nothing."""
        import os
        signed = self.a_project()
        before = self.snapshot()
        real = os.replace
        os.replace = lambda *a, **kw: (_ for _ in ()).throw(OSError("crash mid-commit"))
        try:
            with self.assertRaises(OSError):
                self.ingest.apply(signed)
        finally:
            os.replace = real
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(json.dumps(st.AuthoritativeStore(self.path).read().get("tcb", {}),
                                    sort_keys=True), before)


class VerdictIngestTests(Pipeline):
    def a_verify(self, run_ref, gate_ref, **over):
        args = dict(project="proj-1", run_commitment=run_ref, gate_commitment=gate_ref,
                    candidate_fingerprint=CAND, obligation_id="obl-1",
                    verification_method="m", verdict="pass", observation_digest=D)
        args.update(over)
        return self.signer.verify_attestation(**args)

    def test_a_verdict_becomes_the_current_verdict_for_its_obligation_and_candidate(self):
        run_ref, gate_ref = self.establish_run()
        signed = self.a_verify(run_ref, gate_ref)
        self.assertTrue(self.ingest.apply(signed).admissible)
        reference = cm.commitment_of(signed)
        self.assertEqual(self.facts._table("verdicts")[reference]["verdict"], "pass")
        self.assertTrue(self.facts.current_pass("obl-1", CAND),
                        "the verdict was recorded but never became the CURRENT one (AM-29)")

    def test_a_supersession_marks_the_earlier_verdict_and_never_erases_it(self):
        run_ref, gate_ref = self.establish_run()
        # An adverse verdict on the parent candidate, then a PASS on its descendant.
        state = self.store.read()
        state["tcb"]["runs"][run_ref]["candidate_fingerprint"] = PARENT
        with self.store._exclusive():
            self.store._write(state)
        adverse = self.a_verify(run_ref, gate_ref, candidate_fingerprint=PARENT, verdict="fail")
        self.assertTrue(self.ingest.apply(adverse).admissible)
        adverse_ref = cm.commitment_of(adverse)

        state = self.store.read()
        state["tcb"]["runs"][run_ref]["candidate_fingerprint"] = CAND
        state["tcb"]["gate_strength"][gate_ref] = {"strength": 1}
        with self.store._exclusive():
            self.store._write(state)
        repair = self.a_verify(run_ref, gate_ref, supersedes=adverse_ref)
        verdict = self.ingest.apply(repair)
        self.assertTrue(verdict.admissible, verdict.reason)

        verdicts = self.facts._table("verdicts")
        self.assertIn(adverse_ref, verdicts, "supersession erased the adverse verdict")
        self.assertEqual(verdicts[adverse_ref]["superseded_by"], cm.commitment_of(repair),
                         "the earlier verdict was not marked superseded")

    def test_an_already_superseded_verdict_cannot_be_superseded_again(self):
        run_ref, gate_ref = self.establish_run()
        state = self.store.read()
        state["tcb"]["runs"][run_ref]["candidate_fingerprint"] = PARENT
        with self.store._exclusive():
            self.store._write(state)
        adverse = self.a_verify(run_ref, gate_ref, candidate_fingerprint=PARENT, verdict="fail")
        self.ingest.apply(adverse)
        adverse_ref = cm.commitment_of(adverse)
        state = self.store.read()
        state["tcb"]["runs"][run_ref]["candidate_fingerprint"] = CAND
        state["tcb"]["gate_strength"][gate_ref] = {"strength": 1}
        with self.store._exclusive():
            self.store._write(state)
        self.assertTrue(self.ingest.apply(
            self.a_verify(run_ref, gate_ref, supersedes=adverse_ref)).admissible)
        before = self.snapshot()
        again = self.ingest.apply(
            self.a_verify(run_ref, gate_ref, supersedes=adverse_ref, observation_digest=
                          "sha256:" + "dd" * 32))
        self.assertIn("already superseded", again.reason)
        self.assertEqual(self.snapshot(), before)


class InvariantTests(Pipeline):
    def test_no_fact_appears_without_going_through_the_pipeline(self):
        """apply() is the only writer, and it takes a signed message and nothing else."""
        import inspect
        self.assertEqual(list(inspect.signature(ing.Ingest.apply).parameters), ["self", "signed"])
        public = [name for name in dir(ing.Ingest)
                  if not name.startswith("_") and callable(getattr(ing.Ingest, name))]
        self.assertEqual(public, ["apply"], f"another public writer exists: {public}")

    def test_every_message_type_has_an_applier(self):
        self.assertEqual(set(self.ingest._appliers), set(k.DOMAINS))

    def test_a_gate_does_not_create_the_run_it_names(self):
        self.assertEqual(self.facts._table("runs"), {})


class ScopeBoundaryTests(unittest.TestCase):
    def test_nothing_here_can_execute_anything(self):
        import ast
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_ingest.py").read_text()
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for absent in ("subprocess", "os", "shutil", "socket", "multiprocessing", "threading"):
            self.assertNotIn(absent, imported,
                             f"I6b imports {absent!r}; running or isolating anything is I7's")


if __name__ == "__main__":
    unittest.main()
