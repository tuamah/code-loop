#!/usr/bin/env python3
"""F1-I6b — Authoritative State Ingest.

I6's `TrustedFacts` reads tables that nothing wrote. This is what writes them, and it is the only
thing that may:

    signed message -> Stage 1 -> Stage 2 -> transactional apply -> authoritative tables + heads

**The invariant this milestone exists to hold.**

> No authoritative fact may appear in `TrustedFacts` unless it was produced from an authenticated,
> admissible message and committed transactionally.

So there is no path here that writes a fact without a verdict behind it: `apply()` takes a *signed
message* and nothing else, runs both stages, and only then opens a transaction. A refusal at any
point leaves the state byte-identical — and a failure during the transaction leaves it likewise,
because I5's commit is all-or-nothing.

**Not here.** No project code runs, no worker is spawned, no verification is performed, nothing is
sandboxed, and no decision is orchestrated beyond recording records that are already admissible.
Those are I7. A test asserts this module imports nothing that could execute anything.
"""

from __future__ import annotations

from typing import Any, Callable

from f1_commitments import commitment_of
from f1_registry import ADMISSIBLE
from f1_stage1 import INADMISSIBLE, Stage1, Verdict
from f1_stage2 import STALE, Stage2, TrustedFacts
from f1_state import AuthoritativeStore, StateError

#: Which head each headed message type advances. Derived from the contract's own chaining rule
#: rather than kept as a second list: a type chains if its body carries an epoch and a previous
#: commitment, which is exactly what Stage 2's `_chains` already tests.
HEADED = {"POLICY": "policy", "APPLICABILITY": "applicability",
          "REGISTRY": "registry", "MIGRATION": "migration"}


class IngestError(RuntimeError):
    """The message was not admitted. The authoritative state is unchanged."""


class Ingest:
    """The single writer of authoritative facts."""

    def __init__(self, store: AuthoritativeStore, stage1: Stage1, stage2: Stage2,
                 scope: str = "tcb"):
        self._store = store
        self._stage1 = stage1
        self._stage2 = stage2
        self._scope = scope
        self._appliers: dict[str, Callable[..., None]] = {
            "PROJECT": self._apply_project, "TASK": self._apply_task, "RUN": self._apply_run,
            "GATE": self._apply_gate, "VERIFY": self._apply_verify,
            "DECISION": self._apply_decision, "POLICY": self._apply_headed,
            "APPLICABILITY": self._apply_headed, "REGISTRY": self._apply_headed,
            "MIGRATION": self._apply_migration, "HUMAN": self._apply_human,
        }

    # -- the pipeline ----------------------------------------------------------------------------

    def apply(self, signed: dict[str, Any]) -> Verdict:
        """Admit a signed message and commit its effect, or change nothing at all.

        Returns the verdict. Only ADMISSIBLE reaches the transaction; STALE and INADMISSIBLE are
        returned to the caller with the state untouched, and a STALE verdict is deliberately not
        an error — the message may be genuine and simply about a candidate the run has moved past.
        """
        stage1 = self._stage1.check(signed)
        if not stage1.admissible:
            return stage1
        message = signed["message"]
        stage2 = self._stage2.check(message)
        if stage2.status != ADMISSIBLE:
            return stage2

        reference = commitment_of(signed)
        try:
            with self._store.transaction() as tx:
                facts = tx._staged.setdefault(self._scope, {})
                self._appliers[message["message_type"]](message, facts, reference, tx)
        except StateError as exc:
            # The transaction aborted: nothing was written. Re-raised rather than returned,
            # because a conflict is not a verdict about the message — it is a retryable fact
            # about the state it raced with.
            raise IngestError(str(exc)) from exc
        return stage2

    def record_run_observation(self, run_commitment: str, *, candidate_fingerprint: str,
                               execution_identity: str) -> None:
        """A fact the TCB observed itself, not one carried by a message.

        Two facts in F1 are not asserted by anybody and therefore cannot arrive as signed claims:
        the `candidate_fingerprint` the controller DERIVES from the master it built, and the
        `execution_identity` it launches. §7.5 makes the controller their producer, so requiring a
        message for them would mean requiring someone to *assert* them — which is exactly what
        deriving them instead is for.

        So the invariant is precise rather than absolute:

            a fact derived from a MESSAGE enters only through apply();
            a fact the TCB OBSERVES ITSELF enters only through here, and only ever as values the
            controller computed — this method takes no untrusted input and no verdict.

        Both commit transactionally, and this one refuses to invent the run it annotates.
        """
        with self._store.transaction() as tx:
            facts = tx._staged.setdefault(self._scope, {})
            run = self._table(facts, "runs").get(run_commitment)
            if run is None:
                raise IngestError(
                    "an observation does not create the run it names; the run must already be a "
                    "TCB-held fact")
            run["candidate_fingerprint"] = candidate_fingerprint
            identities = set(run.get("execution_identities", ()))
            identities.add(execution_identity)
            run["execution_identities"] = sorted(identities)
            self._table(facts, "candidates").setdefault(candidate_fingerprint, {"parent": None})

    # -- appliers, one per message type -----------------------------------------------------------

    @staticmethod
    def _table(facts: dict[str, Any], name: str) -> dict[str, Any]:
        return facts.setdefault(name, {})

    def _apply_project(self, message, facts, reference, tx):
        body = message["body"]
        self._table(facts, "project_commitments")[reference] = {
            "project_id": body["project_id"], "repository_identity": body["repository_identity"]}
        self._table(facts, "base_commitments")[body["initial_base_digest"]] = {
            "project_commitment": reference}
        self._table(facts, "maps")[body["policy_baseline"]] = {"kind": "policy_baseline"}
        self._table(facts, "candidates")[body["initial_base_digest"]] = {"parent": None}

    def _apply_task(self, message, facts, reference, tx):
        body = message["body"]
        self._table(facts, "task_commitments")[reference] = {
            "project_commitment": body["project_commitment"], "relation": body["relation"]}

    def _apply_run(self, message, facts, reference, tx):
        body = message["body"]
        self._table(facts, "run_commitments")[reference] = {"run_id": body["run_id"]}
        self._table(facts, "runs")[reference] = {
            "run_id": body["run_id"], "gate_commitment": None, "candidate_fingerprint": None,
            "execution_identities": [], "task_commitment": body["task_commitment"]}

    def _apply_gate(self, message, facts, reference, tx):
        body = message["body"]
        run = self._table(facts, "runs").get(body["run_commitment"])
        if run is None:
            # Stage 2 already required a TCB-held Run Commitment, so this is unreachable through
            # apply(). Refusing rather than creating the run keeps the single-writer rule honest:
            # a gate does not bring a run into existence.
            raise IngestError("a gate does not create the run it names")
        run["gate_commitment"] = reference
        self._table(facts, "gate_strength")[reference] = {
            "strength": 1 if body.get("baseline_match") else 0}

    def _apply_verify(self, message, facts, reference, tx):
        body = message["body"]
        self._table(facts, "verdicts")[reference] = {
            "obligation_id": body["obligation_id"],
            "candidate_fingerprint": body["candidate_fingerprint"],
            "gate_commitment": body["gate_commitment"],
            # The policy IN FORCE when the verdict was made, read from the head rather than left
            # None: AM-40's supersession compares the policy at this head against the one the
            # superseded verdict was made under, and a verdict that records no policy can never
            # satisfy that comparison — the rule would be unreachable rather than enforced.
            "policy_commitment": (tx.head("policy") or ("", 0))[0],
            "verdict": body["verdict"], "superseded_by": None}
        # "The current verdict for this obligation on this candidate" is an authoritative fact a
        # later acceptor reads, so a verdict arriving is a state transition (AM-29), not an
        # append to a log nobody selects over.
        self._table(facts, "current_verdicts")[
            f"{body['obligation_id']}|{body['candidate_fingerprint']}"] = {
                "verdict": body["verdict"], "verdict_commitment": reference}
        superseded = body.get("supersedes")
        if superseded is not None:
            # Records, never erases (T1B §B3): both verdicts remain, and the earlier one is
            # marked so it cannot be cleared twice.
            self._table(facts, "verdicts")[superseded]["superseded_by"] = reference

    def _apply_decision(self, message, facts, reference, tx):
        body = message["body"]
        self._table(facts, "decisions")[reference] = {
            "run_commitment": body["run_commitment"], "decision": body["decision"],
            "candidate_fingerprint": body["candidate_fingerprint"],
            "superseded_adverse_verdicts": list(body["superseded_adverse_verdicts"])}

    def _apply_headed(self, message, facts, reference, tx):
        message_type = message["message_type"]
        body = message["body"]
        self._advance(tx, message_type, body, reference)
        if message_type == "POLICY":
            # The maps themselves are NOT written here. Stage 2 already required both digests to
            # resolve before this message was admitted, so adding them now would be circular —
            # ingest supplying the very facts admission depended on. Map content reaches the TCB
            # out of band or through PROJECT genesis, which carries an authenticated baseline.
            self._table(facts, "policy_strength")[reference] = {"strength": body["epoch"]}
        elif message_type == "APPLICABILITY":
            self._table(facts, "applicability")[body["obligation_id"]] = {
                "obligation_class": body["obligation_class"], "transition": body["transition"],
                "predicate_scope_digest": body["predicate_scope_digest"],
                "condition_commitment": body["condition_commitment"], "commitment": reference}

    def _apply_migration(self, message, facts, reference, tx):
        body = message["body"]
        self._advance(tx, "MIGRATION", body, reference)
        self._table(facts, "migrations")[reference] = {
            "project_commitments": list(body["project_commitments"]),
            "reason": body["reason"], "expiry": body["expiry"]}

    def _apply_human(self, message, facts, reference, tx):
        body = message["body"]
        self._table(facts, "authorizations")[reference] = {
            "authorization_id": body["authorization_id"], "action_type": body["action_type"],
            "target_message_type": body["target_message_type"],
            "subject_digest": body["subject_digest"], "use_semantics": body["use_semantics"]}
        if body["use_semantics"] == "single-use":
            # Consumed in the SAME transaction that records it (AM-24): checking and consuming a
            # linear capability is one operation, never a check followed by a write.
            tx.consume_authorization(body["authorization_id"])

    # -- head advancement ---------------------------------------------------------------------------

    @staticmethod
    def _advance(tx, message_type: str, body: dict[str, Any], reference: str) -> None:
        tx.set_head(HEADED[message_type], reference, body["epoch"])
