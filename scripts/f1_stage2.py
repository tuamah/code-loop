#!/usr/bin/env python3
"""F1-I6 — Stage 2 Admissibility (T1A §10, T1B §B3/§B4).

The per-message-type stage, after Stage 1's twelve common steps have passed. Eleven explicit
handlers, one per domain, and **no generic fallback**: a message type with no handler is
inadmissible rather than waved through, which is what "a message type with no stage-2 clause is
inadmissible" means (AM-22).

**Every authoritative fact is read from the durable state I5b wired up.** Not a parallel copy, not
a cache, and never from the message itself — the whole of F1 is the claim that a statement about
authority is worth nothing unless the trusted state says so independently. `check()` takes a
message and nothing else; there is no parameter through which a caller supplies the facts it will
be judged against.

**No default-accept path.** Each handler returns a verdict or falls through to the one ADMISSIBLE
at its end, and dispatch itself refuses an unknown type. Controller/worker isolation is I7 and is
not here.
"""

from __future__ import annotations

from typing import Any, Callable

from f1_kernel import DOMAINS
from f1_registry import ADMISSIBLE
from f1_stage1 import INADMISSIBLE, Verdict

STALE = "STALE"


class TrustedFacts:
    """The TCB's own view, read from the one transactional domain (AM-26).

    Every method answers a question the contract asks Stage 2 to put to the trusted state. None of
    them accept an assertion from the message being judged: a body naming a commitment is a claim,
    and these turn a claim into a fact or refuse to.
    """

    def __init__(self, store: Any, scope: str = "tcb"):
        self._store = store
        self._scope = scope

    def _facts(self) -> dict[str, Any]:
        return self._store.read().get(self._scope, {})

    def _table(self, name: str) -> dict[str, Any]:
        return self._facts().get(name, {})

    # -- commitments and identities ---------------------------------------------------------------

    def resolves(self, table: str, reference: str) -> bool:
        return reference in self._table(table)

    def record(self, table: str, reference: str) -> dict[str, Any] | None:
        return self._table(table).get(reference)

    def gate_for_run(self, run_commitment: str) -> str | None:
        run = self.record("runs", run_commitment)
        return run.get("gate_commitment") if run else None

    def live_candidate(self, run_commitment: str) -> str | None:
        run = self.record("runs", run_commitment)
        return run.get("candidate_fingerprint") if run else None

    def execution_identities(self, run_commitment: str) -> frozenset[str]:
        run = self.record("runs", run_commitment)
        return frozenset(run.get("execution_identities", ())) if run else frozenset()

    def is_descendant(self, candidate: str, ancestor: str) -> bool:
        """TCB-recorded descent (AM-9), structural and never claimed by the caller."""
        seen, current = set(), candidate
        while current and current not in seen:
            seen.add(current)
            record = self.record("candidates", current)
            if record is None:
                return False
            current = record.get("parent")
            if current == ancestor:
                return True
        return False

    # -- verdicts and obligations -----------------------------------------------------------------

    def verdict(self, reference: str) -> dict[str, Any] | None:
        return self.record("verdicts", reference)

    def applicable_obligations(self, obligation_set: str) -> frozenset[str] | None:
        record = self.record("obligation_sets", obligation_set)
        return frozenset(record.get("applicable", ())) if record else None

    def current_pass(self, obligation_id: str, candidate: str) -> bool:
        """A current PASS on this obligation, bound to THIS candidate (T1B §B3)."""
        current = self._table("current_verdicts").get(f"{obligation_id}|{candidate}")
        return bool(current) and current.get("verdict") == "pass"

    def snapshot(self, digest: str) -> dict[str, Any] | None:
        return self.record("snapshots", digest)

    # -- heads and policy ---------------------------------------------------------------------------

    def head(self, name: str) -> tuple[str, int] | None:
        return self._store.head(name)

    def strength(self, kind: str, commitment: str) -> int | None:
        record = self.record(f"{kind}_strength", commitment)
        return record.get("strength") if record else None

    # -- authorizations ------------------------------------------------------------------------------

    def authorization(self, reference: str) -> dict[str, Any] | None:
        return self.record("authorizations", reference)

    def is_consumed(self, authorization_id: str) -> bool:
        return self._store.is_consumed(authorization_id)

    def trust_root_key(self) -> str | None:
        return self._facts().get("trust_root_key_id")

    def provisioning(self, project_id: str) -> dict[str, Any] | None:
        return self.record("provisioning", project_id)

    def authorized_relation(self, project_commitment: str, task_digest: str) -> str | None:
        record = self.record("task_relations", f"{project_commitment}|{task_digest}")
        return record.get("relation") if record else None

    def minted_run_id(self, run_id: str) -> bool:
        return self.resolves("minted_run_ids", run_id)


class Stage2:
    """Eleven handlers, dispatched by message_type. No fallback, no caller-supplied state."""

    def __init__(self, facts: TrustedFacts):
        self._facts = facts
        self._handlers: dict[str, Callable[[dict[str, Any]], Verdict]] = {
            "VERIFY": self._verify, "DECISION": self._decision, "GATE": self._gate,
            "HUMAN": self._human, "PROJECT": self._project, "TASK": self._task,
            "RUN": self._run, "POLICY": self._policy, "APPLICABILITY": self._applicability,
            "REGISTRY": self._registry, "MIGRATION": self._migration,
        }

    def check(self, message: dict[str, Any]) -> Verdict:
        """Stage 2 for one Stage-1-admissible message."""
        message_type = message.get("message_type")
        handler = self._handlers.get(message_type)
        if handler is None:
            # AM-22: a message type with no stage-2 clause is inadmissible, never waved through.
            # This is also why there is no generic fallback to add one to.
            return Verdict(INADMISSIBLE, 2,
                           f"{message_type!r} has no Stage 2 handler; a message type with no "
                           f"stage-2 clause is inadmissible (AM-22)")
        return handler(message)

    # -- handlers -----------------------------------------------------------------------------------

    def _verify(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        run = body["run_commitment"]

        authentic_gate = facts.gate_for_run(run)
        if authentic_gate is None or authentic_gate != body["gate_commitment"]:
            return Verdict(INADMISSIBLE, 2,
                           f"gate_commitment is not the authenticated commitment for run {run!r}")

        live = facts.live_candidate(run)
        if live is None or live != body["candidate_fingerprint"]:
            # STALE, not INADMISSIBLE: the verdict may be genuine and simply about a candidate the
            # run has moved past. The contract distinguishes the two, so this must too.
            return Verdict(STALE, 2, "candidate_fingerprint does not match the live candidate")

        if message["producer_identity"] in facts.execution_identities(run):
            return Verdict(INADMISSIBLE, 2,
                           f"{message['producer_identity']!r} is an execution identity of this "
                           f"run; execution authority does not attest its own work")

        superseded_ref = body.get("supersedes")
        if superseded_ref is not None:
            return self._supersession(message, superseded_ref)
        return Verdict(ADMISSIBLE)

    def _supersession(self, message: dict[str, Any], superseded_ref: str) -> Verdict:
        """AM-40's five conditions. A supersession may only raise the burden, never lower it."""
        body, facts = message["body"], self._facts
        superseded = facts.verdict(superseded_ref)
        if superseded is None:
            return Verdict(INADMISSIBLE, 2, f"superseded verdict {superseded_ref!r} does not resolve")
        if superseded.get("obligation_id") != body["obligation_id"]:
            return Verdict(INADMISSIBLE, 2, "supersession crosses obligations; same obligation_id "
                                            "is required")
        if not facts.is_descendant(body["candidate_fingerprint"],
                                   superseded.get("candidate_fingerprint", "")):
            return Verdict(INADMISSIBLE, 2,
                           "this candidate is not a TCB-recorded descendant of the superseded "
                           "one; descent is structural, never claimed (AM-9)")
        for kind, commitment in (("gate", body["gate_commitment"]),
                                 ("policy", facts.head("policy")[0] if facts.head("policy")
                                  else "")):
            now = facts.strength(kind, commitment)
            before = facts.strength(kind, superseded.get(f"{kind}_commitment", ""))
            if now is None or before is None or now < before:
                return Verdict(INADMISSIBLE, 2,
                               f"the {kind} in force at this head is weaker than the one the "
                               f"superseded verdict was made under")
        if body["verdict"] != "pass":
            return Verdict(INADMISSIBLE, 2, "only a PASS may supersede an adverse verdict")
        if superseded.get("superseded_by"):
            return Verdict(INADMISSIBLE, 2,
                           "that verdict is already superseded; one adverse verdict cleared by "
                           "many descendants at once is A24's race applied to verdicts")
        return Verdict(ADMISSIBLE)

    def _decision(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        snapshot = facts.snapshot(body["decision_snapshot_digest"])
        if snapshot is None:
            return Verdict(INADMISSIBLE, 2, "decision_snapshot_digest does not resolve")
        for name, observed in sorted(snapshot.get("heads", {}).items()):
            current = facts.head(name)
            if (current[0] if current else "") != observed:
                return Verdict(INADMISSIBLE, 2,
                               f"the snapshot's {name} head was not current at CAS (AM-15)")

        if message["producer_identity"] in facts.execution_identities(body["run_commitment"]):
            return Verdict(INADMISSIBLE, 2,
                           "execution authority does not decide on its own run")

        if body["decision"] == "accept":
            obligations = facts.applicable_obligations(snapshot.get("obligation_set", ""))
            if obligations is None:
                return Verdict(INADMISSIBLE, 2,
                               "the Obligation-Set Commitment does not resolve; an obligation set "
                               "assembled ad hoc is refused (AM-16)")
            for obligation in sorted(obligations):
                if not facts.current_pass(obligation, body["candidate_fingerprint"]):
                    return Verdict(INADMISSIBLE, 2,
                                   f"no current PASS on {obligation!r} for this exact candidate; "
                                   f"no inherited PASS and no credit from a sibling (T1B §B3)")

        resolved = sorted(snapshot.get("superseded_adverse_verdicts", []))
        if sorted(body["superseded_adverse_verdicts"]) != resolved:
            return Verdict(INADMISSIBLE, 2,
                           "superseded_adverse_verdicts does not equal what the snapshot "
                           "resolves; the decider reports supersessions, never asserts them "
                           "(AM-40)")
        return Verdict(ADMISSIBLE)

    def _gate(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        if not facts.resolves("run_commitments", body["run_commitment"]):
            return Verdict(INADMISSIBLE, 2, "the gate does not name a TCB-held Run Commitment")
        if body.get("baseline_match") is True:
            return Verdict(ADMISSIBLE)
        authorization = facts.authorization(body.get("human_authorization", ""))
        if authorization is None:
            return Verdict(INADMISSIBLE, 2,
                           "a gate deviating from the baseline needs a HUMAN authorization (§8)")
        if authorization.get("subject_digest") != body["gate_content_digest"]:
            return Verdict(INADMISSIBLE, 2,
                           "the authorization is not for THIS gate content; an approval detached "
                           "from its object is a token anyone can spend (§6.1)")
        return Verdict(ADMISSIBLE)

    def _human(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        operation = facts.record("pending_operations", body["subject_digest"])
        if operation is None:
            return Verdict(INADMISSIBLE, 2,
                           "the authorization names no operation the TCB is holding")
        for field in ("action_type", "target_message_type", "subject_digest",
                      "requested_transition"):
            if body.get(field) != operation.get(field):
                return Verdict(INADMISSIBLE, 2,
                               f"purpose-binding fails on {field!r}: authentication proves who "
                               f"signed, authorization must prove what exact operation (AM-21)")
        if facts.is_consumed(body["authorization_id"]):
            if body["use_semantics"] != "reusable":
                return Verdict(INADMISSIBLE, 2,
                               "a single-use authorization presented twice is refused on the "
                               "second attempt (AM-24)")
            if operation.get("scope") not in (body.get("reusable_scope"), None):
                return Verdict(INADMISSIBLE, 2,
                               "a reusable authorization is refused outside its declared scope")
        current = facts.head("policy")
        if (current[0] if current else "") != body["policy_head"]:
            return Verdict(INADMISSIBLE, 2,
                           "policy_head is no longer current: approval was given under rules that "
                           "have since changed (§6.1)")
        if facts.record("expired_authorizations", body["authorization_id"]):
            return Verdict(INADMISSIBLE, 2, "the authorization has expired")
        return Verdict(ADMISSIBLE)

    def _project(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        ceremony = facts.provisioning(body["project_id"])
        if ceremony is None:
            return Verdict(INADMISSIBLE, 2,
                           "no provisioning ceremony is recorded; a root created implicitly on "
                           "first use is a root the adversary can create first (§5)")
        if ceremony.get("repository_identity") != body["repository_identity"]:
            return Verdict(INADMISSIBLE, 2,
                           "repository_identity does not bind to the recorded ceremony (§7.0.1)")
        return Verdict(ADMISSIBLE)

    def _task(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        if not facts.resolves("project_commitments", body["project_commitment"]):
            return Verdict(INADMISSIBLE, 2, "project_commitment does not resolve")
        authorized = facts.authorized_relation(body["project_commitment"], body["task_digest"])
        if authorized is None:
            return Verdict(INADMISSIBLE, 2,
                           "no authorized relation is recorded; a caller asserting NEW_TASK is "
                           "exactly the A7 move (§7.0)")
        if authorized != body["relation"]:
            return Verdict(INADMISSIBLE, 2,
                           f"the relation is authorized as {authorized!r}, not the declared "
                           f"{body['relation']!r}; relation is authorized, not declared")
        return Verdict(ADMISSIBLE)

    def _run(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        if not facts.resolves("task_commitments", body["task_commitment"]):
            return Verdict(INADMISSIBLE, 2, "task_commitment does not resolve")
        if not facts.minted_run_id(body["run_id"]):
            return Verdict(INADMISSIBLE, 2,
                           "run_id was not TCB-minted; the caller never chooses run identity "
                           "(AM-4)")
        if not facts.resolves("base_commitments", body["authorized_base_commitment"]):
            return Verdict(INADMISSIBLE, 2,
                           "authorized_base_commitment does not resolve; a caller-named base is "
                           "refused (AM-9)")
        return Verdict(ADMISSIBLE)

    def _policy(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        chained = self._chains(facts, "policy", body)
        if chained is not None:
            return chained
        for field in ("class_authority_map_digest", "predicate_class_map_digest"):
            if not facts.resolves("maps", body[field]):
                return Verdict(INADMISSIBLE, 2,
                               f"{field} does not resolve to a retrievable map (AM-39)")
        return Verdict(ADMISSIBLE)

    def _applicability(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        chained = self._chains(facts, "applicability", body)
        if chained is not None:
            return chained
        authorization = facts.authorization(body["authorization_ref"])
        if authorization is None:
            return Verdict(INADMISSIBLE, 2, "authorization_ref does not resolve")
        if authorization.get("obligation_class") != body["obligation_class"]:
            return Verdict(INADMISSIBLE, 2,
                           "the authorization is not for this obligation class; protection is "
                           "fixed in advance by class, never by current state (AM-13)")
        if authorization.get("transition") != body["transition"]:
            return Verdict(INADMISSIBLE, 2,
                           "the authorization is not for this transition; narrowing needs the "
                           "same authority as removal (T1B §B4)")
        for field in ("predicate_scope_digest", "condition_commitment"):
            if not facts.resolves("commitments", body[field]):
                return Verdict(INADMISSIBLE, 2, f"{field} does not resolve (AM-39)")
        return Verdict(ADMISSIBLE)

    def _registry(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        root = facts.trust_root_key()
        if root is None or message["key_id"] != root:
            return Verdict(INADMISSIBLE, 2,
                           "registry commitments are signed by the trust root (§5)")
        return self._chains(facts, "registry", body) or Verdict(ADMISSIBLE)

    def _migration(self, message: dict[str, Any]) -> Verdict:
        body, facts = message["body"], self._facts
        chained = self._chains(facts, "migration", body)
        if chained is not None:
            return chained
        authorization = facts.authorization(body["authorization_ref"])
        if authorization is None or authorization.get("target_message_type") != "MIGRATION":
            return Verdict(INADMISSIBLE, 2,
                           "migration needs a HUMAN authorization for THIS grant (§12)")
        if not body["project_commitments"]:
            return Verdict(INADMISSIBLE, 2,
                           "migration must enumerate its projects, never a wildcard (§12)")
        if not body.get("expiry"):
            return Verdict(INADMISSIBLE, 2,
                           "migration needs an expiry: a bound, never open-ended (§12)")
        return Verdict(ADMISSIBLE)

    @staticmethod
    def _chains(facts: TrustedFacts, name: str, body: dict[str, Any]) -> Verdict | None:
        """epoch is the current head's successor and previous_commitment chains (§10.3, AM-18)."""
        current = facts.head(name)
        expected_previous = current[0] if current else ""
        if body["previous_commitment"] != expected_previous:
            return Verdict(INADMISSIBLE, 2,
                           f"previous_commitment does not chain from the current {name} head; "
                           f"a valid head is not the current head (AM-18)")
        expected_epoch = (current[1] if current else 0) + 1
        if body["epoch"] != expected_epoch:
            return Verdict(INADMISSIBLE, 2,
                           f"epoch {body['epoch']} does not chain from {expected_epoch - 1}")
        return None
