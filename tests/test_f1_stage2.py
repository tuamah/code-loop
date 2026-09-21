"""F1-I6 closure tests: Stage 2 admissibility (T1A §10, T1B §B3/§B4).

One handler per domain, and the adversarial cases are the point: a Stage 2 that passes its happy
paths but accepts a decision with no current PASS has implemented the shape of the clauses and
none of their content.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_kernel as k                                                        # noqa: E402
import f1_stage1 as s1                                                       # noqa: E402
import f1_stage2 as s2                                                       # noqa: E402
import f1_state as st                                                        # noqa: E402

D = "sha256:" + "aa" * 32
CAND, PARENT = "sha256:" + "c1" * 32, "sha256:" + "c0" * 32
CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "f1-t1a-trust-core.md"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.store = st.AuthoritativeStore(Path(self.dir.name) / "state.json")
        self.seed()
        # A policy head exists: the supersession clause compares the policy in force AT THIS HEAD
        # against the one the superseded verdict was made under, and with no head there is nothing
        # to compare, which fails closed. That is correct, and it is a separate test below.
        with self.store.transaction() as tx:
            tx.set_head("policy", D, 1)
        self.stage2 = s2.Stage2(s2.TrustedFacts(self.store))

    def seed(self, **over):
        facts = {
            "trust_root_key_id": "registry-root",
            "runs": {D: {"gate_commitment": D, "candidate_fingerprint": CAND,
                         "execution_identities": ["executor-1"]}},
            "run_commitments": {D: {}}, "project_commitments": {D: {}},
            "task_commitments": {D: {}}, "base_commitments": {D: {}},
            "minted_run_ids": {"run-1": {}}, "commitments": {D: {}}, "maps": {D: {}},
            "candidates": {CAND: {"parent": PARENT}, PARENT: {"parent": None}},
            "provisioning": {"proj-1": {"repository_identity": "git:abc"}},
            "task_relations": {f"{D}|{D}": {"relation": "NEW_TASK"}},
            "obligation_sets": {D: {"applicable": ["obl-1"]}},
            "current_verdicts": {f"obl-1|{CAND}": {"verdict": "pass"}},
            "verdicts": {"v-old": {"obligation_id": "obl-1", "candidate_fingerprint": PARENT,
                                   "gate_commitment": D, "policy_commitment": D,
                                   "superseded_by": None}},
            "snapshots": {D: {"heads": {}, "obligation_set": D,
                              "superseded_adverse_verdicts": []}},
            "authorizations": {D: {"subject_digest": D, "obligation_class": "HIGH",
                                   "transition": "activate", "target_message_type": "MIGRATION"}},
            "pending_operations": {D: {"action_type": "freeze", "target_message_type": "GATE",
                                       "subject_digest": D, "requested_transition": "a->b"}},
            "gate_strength": {D: {"strength": 5}},
            "policy_strength": {D: {"strength": 5}},
            "expired_authorizations": {},
        }
        facts.update(over)
        state = self.store.read()
        state["tcb"] = facts
        with self.store._exclusive():
            self.store._write(state)

    def msg(self, message_type, body, *, producer="authority-1", key_id="key-1", action=None):
        return {"message_type": message_type, "action": action or sorted(k.ACTIONS[message_type])[0],
                "producer_identity": producer, "key_id": key_id, "body": body}

    def verify_body(self, **over):
        body = {"run_commitment": D, "gate_commitment": D, "candidate_fingerprint": CAND,
                "obligation_id": "obl-1", "verification_method": "m", "verdict": "pass",
                "observation_digest": D}
        body.update(over)
        return body

    def decision_body(self, **over):
        body = {"run_commitment": D, "candidate_fingerprint": CAND, "decision": "accept",
                "decision_snapshot_digest": D, "superseded_adverse_verdicts": [],
                "policy_head": D}
        body.update(over)
        return body


class CompletenessTests(Fixture):
    def test_every_contract_clause_has_a_handler(self):
        block = re.search(r"STAGE 2 — by message_type\n(.*?)\n```", CONTRACT.read_text("utf-8"),
                          re.S).group(1)
        declared = {m.group(1) for line in block.splitlines()
                    if (m := re.match(r"\s([A-Z]+)\s{2,}\S", line))}
        self.assertEqual(declared, set(self.stage2._handlers))
        self.assertEqual(len(declared), 11)

    def test_no_generic_fallback(self):
        verdict = self.stage2.check(self.msg("VERIFY", self.verify_body()))
        self.assertTrue(verdict.admissible)
        unknown = {"message_type": "OVERRIDE", "action": "apply", "producer_identity": "x",
                   "key_id": "k", "body": {}}
        result = self.stage2.check(unknown)
        self.assertEqual(result.status, s1.INADMISSIBLE)
        self.assertIn("no Stage 2 handler", result.reason)

    def test_check_takes_only_the_message(self):
        import inspect
        self.assertEqual(list(inspect.signature(s2.Stage2.check).parameters),
                         ["self", "message"])

    def test_facts_are_read_from_the_authoritative_store(self):
        """Not a parallel copy: change the store, and Stage 2's answer changes."""
        self.assertTrue(self.stage2.check(self.msg("VERIFY", self.verify_body())).admissible)
        self.seed(runs={D: {"gate_commitment": "sha256:" + "ff" * 32,
                            "candidate_fingerprint": CAND, "execution_identities": []}})
        self.assertFalse(self.stage2.check(self.msg("VERIFY", self.verify_body())).admissible)


class VerifyTests(Fixture):
    def test_gate_must_be_the_authenticated_commitment_for_this_run(self):
        body = self.verify_body(gate_commitment="sha256:" + "ee" * 32)
        self.assertEqual(self.stage2.check(self.msg("VERIFY", body)).status, s1.INADMISSIBLE)

    def test_a_candidate_the_run_moved_past_is_stale_not_inadmissible(self):
        body = self.verify_body(candidate_fingerprint=PARENT)
        self.assertEqual(self.stage2.check(self.msg("VERIFY", body)).status, s2.STALE)

    def test_an_execution_identity_cannot_attest_its_own_run(self):
        verdict = self.stage2.check(self.msg("VERIFY", self.verify_body(), producer="executor-1"))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)

    def test_supersession_requires_the_same_obligation(self):
        body = self.verify_body(supersedes="v-old", obligation_id="obl-2")
        self.assertEqual(self.stage2.check(self.msg("VERIFY", body)).status, s1.INADMISSIBLE)

    def test_supersession_requires_tcb_recorded_descent(self):
        self.seed(candidates={CAND: {"parent": None}, PARENT: {"parent": None}})
        body = self.verify_body(supersedes="v-old")
        verdict = self.stage2.check(self.msg("VERIFY", body))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("descendant", verdict.reason)

    def test_supersession_refuses_a_weaker_gate(self):
        """The gate in force now must be equal or STRONGER than the superseded verdict's."""
        strong = "sha256:" + "51" * 32
        facts = self.store.read()["tcb"]
        facts["verdicts"]["v-old"]["gate_commitment"] = strong
        self.seed(verdicts=facts["verdicts"],
                  gate_strength={D: {"strength": 1}, strong: {"strength": 9}})
        body = self.verify_body(supersedes="v-old")
        verdict = self.stage2.check(self.msg("VERIFY", body))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("weaker", verdict.reason)

    def test_only_a_pass_may_supersede(self):
        body = self.verify_body(supersedes="v-old", verdict="fail")
        self.assertEqual(self.stage2.check(self.msg("VERIFY", body)).status, s1.INADMISSIBLE)

    def test_an_already_superseded_verdict_cannot_be_superseded_again(self):
        facts = self.store.read()["tcb"]
        facts["verdicts"]["v-old"]["superseded_by"] = "v-1"
        self.seed(verdicts=facts["verdicts"])
        body = self.verify_body(supersedes="v-old")
        verdict = self.stage2.check(self.msg("VERIFY", body))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("already superseded", verdict.reason)

    def test_a_valid_supersession_passes(self):
        body = self.verify_body(supersedes="v-old")
        self.assertTrue(self.stage2.check(self.msg("VERIFY", body)).admissible)

    def test_supersession_fails_closed_when_the_policy_in_force_is_unknown(self):
        """With no policy head there is nothing to compare the superseded verdict against."""
        fresh = st.AuthoritativeStore(Path(self.dir.name) / "other.json")
        state = fresh.read()
        state["tcb"] = self.store.read()["tcb"]
        with fresh._exclusive():
            fresh._write(state)
        stage2 = s2.Stage2(s2.TrustedFacts(fresh))
        body = self.verify_body(supersedes="v-old")
        verdict = stage2.check(self.msg("VERIFY", body))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("weaker", verdict.reason)


class DecisionTests(Fixture):
    def test_accept_requires_a_current_pass_on_every_applicable_obligation(self):
        self.seed(current_verdicts={})
        verdict = self.stage2.check(self.msg("DECISION", self.decision_body()))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("no current PASS", verdict.reason)

    def test_a_pass_on_a_sibling_candidate_is_no_credit(self):
        self.seed(current_verdicts={f"obl-1|{PARENT}": {"verdict": "pass"}})
        verdict = self.stage2.check(self.msg("DECISION", self.decision_body()))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)

    def test_a_failing_obligation_blocks_accept(self):
        self.seed(current_verdicts={f"obl-1|{CAND}": {"verdict": "fail"}})
        self.assertEqual(self.stage2.check(self.msg("DECISION", self.decision_body())).status,
                         s1.INADMISSIBLE)

    def test_a_non_accept_decision_does_not_need_the_passes(self):
        self.seed(current_verdicts={})
        body = self.decision_body(decision="abstain")
        self.assertTrue(self.stage2.check(self.msg("DECISION", body, action="abstain")).admissible)

    def test_the_snapshot_must_resolve(self):
        body = self.decision_body(decision_snapshot_digest="sha256:" + "99" * 32)
        self.assertEqual(self.stage2.check(self.msg("DECISION", body)).status, s1.INADMISSIBLE)

    def test_a_snapshot_head_that_is_no_longer_current_is_refused(self):
        self.seed(snapshots={D: {"heads": {"policy": "sha256:" + "77" * 32},
                                 "obligation_set": D, "superseded_adverse_verdicts": []}})
        verdict = self.stage2.check(self.msg("DECISION", self.decision_body()))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("AM-15", verdict.reason)

    def test_the_decider_reports_supersessions_and_never_asserts_them(self):
        body = self.decision_body(superseded_adverse_verdicts=["v-old"])
        verdict = self.stage2.check(self.msg("DECISION", body))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("never asserts them", verdict.reason)

    def test_an_execution_identity_cannot_decide_on_its_own_run(self):
        verdict = self.stage2.check(self.msg("DECISION", self.decision_body(),
                                             producer="executor-1"))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)

    def test_a_well_formed_accept_passes(self):
        self.assertTrue(self.stage2.check(self.msg("DECISION", self.decision_body())).admissible)


class OtherHandlerTests(Fixture):
    def gate_body(self, **over):
        body = {"run_commitment": D, "gate_content_digest": D, "freeze_policy_version": "v1",
                "baseline_match": True}
        body.update(over)
        return body

    def test_gate_needs_a_tcb_held_run_commitment(self):
        body = self.gate_body(run_commitment="sha256:" + "55" * 32)
        self.assertEqual(self.stage2.check(self.msg("GATE", body)).status, s1.INADMISSIBLE)

    def test_a_deviating_gate_needs_an_authorization_for_this_content(self):
        body = self.gate_body(human_authorization=D, gate_content_digest="sha256:" + "66" * 32)
        del body["baseline_match"]
        verdict = self.stage2.check(self.msg("GATE", body))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("THIS gate content", verdict.reason)

    def human_body(self, **over):
        body = {"authorization_id": "a-1", "action_type": "freeze", "target_message_type": "GATE",
                "project_commitment": D, "subject_digest": D, "policy_head": D,
                "use_semantics": "single-use", "expiry": "2027",
                "requested_transition": "a->b"}
        body.update(over)
        return body

    def test_human_purpose_binding_must_match_the_operation(self):
        for field, wrong in (("action_type", "weaken"), ("target_message_type", "POLICY"),
                             ("requested_transition", "x->y")):
            with self.subTest(field=field):
                body = self.human_body(**{field: wrong})
                verdict = self.stage2.check(self.msg("HUMAN", body))
                self.assertEqual(verdict.status, s1.INADMISSIBLE)
                self.assertIn("purpose-binding", verdict.reason)

    def test_a_single_use_authorization_is_refused_on_the_second_attempt(self):
        with self.store.transaction() as tx:
            tx.consume_authorization("a-1")
        verdict = self.stage2.check(self.msg("HUMAN", self.human_body()))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("second attempt", verdict.reason)

    def test_an_authorization_under_a_stale_policy_head_is_refused(self):
        verdict = self.stage2.check(
            self.msg("HUMAN", self.human_body(policy_head="sha256:" + "88" * 32)))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("no longer current", verdict.reason)

    def test_project_needs_a_recorded_ceremony_that_binds(self):
        body = {"project_id": "proj-1", "repository_identity": "git:evil",
                "initial_base_digest": D, "policy_baseline": D, "gate_baseline": D,
                "obligation_policy_baseline": D, "provisioned_by": "h", "provisioning_sequence": 0}
        self.assertEqual(self.stage2.check(self.msg("PROJECT", body)).status, s1.INADMISSIBLE)

    def test_task_relation_is_authorized_not_declared(self):
        body = {"project_commitment": D, "task_digest": D, "relation": "SUPERSEDES(task-1)"}
        verdict = self.stage2.check(self.msg("TASK", body))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("authorized, not declared", verdict.reason)

    def test_run_id_must_be_tcb_minted(self):
        body = {"project_commitment": D, "task_commitment": D, "creation_nonce": "n",
                "run_id": "run-chosen-by-caller", "parent_run_commitments": [],
                "authorized_base_commitment": D, "policy_head": D}
        verdict = self.stage2.check(self.msg("RUN", body))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("TCB-minted", verdict.reason)

    def test_policy_needs_both_map_digests_to_resolve(self):
        body = {"project_commitment": D, "epoch": 2, "previous_commitment": D,
                "class_authority_map_digest": D,
                "predicate_class_map_digest": "sha256:" + "44" * 32}
        verdict = self.stage2.check(self.msg("POLICY", body, action="create"))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("AM-39", verdict.reason)

    def test_a_stale_head_is_refused_for_every_headed_type(self):
        body = {"project_commitment": D, "epoch": 1, "previous_commitment": "",
                "class_authority_map_digest": D, "predicate_class_map_digest": D}
        verdict = self.stage2.check(self.msg("POLICY", body, action="update"))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("AM-18", verdict.reason)

    def test_applicability_authorization_must_match_class_and_transition(self):
        body = {"project_commitment": D, "obligation_id": "o", "obligation_class": "LOW",
                "predicate_scope_digest": D, "condition_commitment": D, "transition": "activate",
                "epoch": 1, "previous_commitment": "", "authorization_ref": D}
        verdict = self.stage2.check(self.msg("APPLICABILITY", body, action="activate"))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertIn("obligation class", verdict.reason)

    def test_registry_must_be_signed_by_the_trust_root(self):
        body = {"epoch": 1, "previous_commitment": "", "key_grants_digest": D}
        verdict = self.stage2.check(self.msg("REGISTRY", body, key_id="key-1"))
        self.assertEqual(verdict.status, s1.INADMISSIBLE)
        self.assertTrue(self.stage2.check(
            self.msg("REGISTRY", body, key_id="registry-root")).admissible)

    def test_migration_needs_enumerated_projects_and_an_expiry(self):
        base = {"project_commitments": [D], "reason": "r", "expiry": "2027",
                "authorization_ref": D, "epoch": 1, "previous_commitment": ""}
        self.assertTrue(self.stage2.check(self.msg("MIGRATION", dict(base))).admissible)
        for broken in ({"project_commitments": []}, {"expiry": ""}):
            with self.subTest(broken=broken):
                verdict = self.stage2.check(self.msg("MIGRATION", dict(base, **broken)))
                self.assertEqual(verdict.status, s1.INADMISSIBLE)


class ScopeBoundaryTests(unittest.TestCase):
    def test_no_controller_worker_isolation_yet(self):
        """Checks imports, not prose.

        A raw text scan matched this module's own sentence saying isolation is I7's — the fourth
        time in this work that a scope test has confused an explanation for an implementation.
        What actually distinguishes I6 from I7 is whether the module can *run* anything.
        """
        import ast
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_stage2.py").read_text()
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for absent in ("subprocess", "os", "shutil", "tempfile", "socket"):
            self.assertNotIn(absent, imported,
                             f"I6 imports {absent!r}; running or isolating anything is I7's")


if __name__ == "__main__":
    unittest.main()
