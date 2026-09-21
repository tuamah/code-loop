#!/usr/bin/env python3
"""F1-I3 — Signed Commitments (T1A §6 bodies, over I1's envelope and I2's registry).

Builds, represents, signs and structurally verifies the eleven message types. **Nothing here
decides anything.** Admissibility is Stage 1 (I4) and Stage 2 (I6); a `DECISION` built here is a
typed signed record of a decision someone else made, never a decision this module reached.

Three slips this module is shaped to prevent:

1. **No generic constructor.** There is no function here taking a `message_type` and a `body`
   dict. Every type has its own builder with named parameters, so "a PROJECT body passed as a
   TASK" is not a runtime check that might be missed — it is unsayable.
2. **No security decision.** The only authority question asked is the one I2 already answers, and
   it is asked *before* signing: may this key sign this type, this action, in this scope?
3. **No Stage 1 shortcut.** Structural validity and admissibility are different questions, and
   fusing them in a constructor is how they stop being distinguishable. A builder proves a message
   is well-formed and authorized to be *produced*; whether it may be *acted on* is not asked here.

`sequence` is per signing identity and monotonic. It is kept in memory with the signer; durability
is I5's, like everything else about persistence.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import f1_kernel as kernel
from f1_canonical import CanonicalizationError, canonicalize
from f1_registry import AuthorityRegistry

# T1A §7.0's closed relation enum. A relation is authorized, not merely declared (AM-7) — that
# check belongs to Stage 2; the shape is this module's.
RELATION = re.compile(r"^(NEW_TASK|(CONTINUATION_OF|SUPERSEDES|CHILD_OF)\([^()]+\))$")

DECISIONS = frozenset({"accept", "repair", "abstain", "human_review"})
TRANSITIONS = frozenset({"activate", "deactivate", "narrow", "reclassify"})
USE_SEMANTICS = frozenset({"single-use", "reusable"})


class CommitmentError(ValueError):
    """The commitment cannot be built, signed or resolved. Fail closed (§12)."""


def commitment_of(signed: dict[str, Any]) -> str:
    """The reference other messages name this one by: a digest over the signed record.

    Covering the signature as well as the message means a reference names *this attestation*, not
    merely a body someone else could have signed differently.
    """
    try:
        return "sha256:" + hashlib.sha256(canonicalize(signed)).hexdigest()
    except CanonicalizationError as exc:
        raise CommitmentError(f"signed record is not canonicalizable: {exc}") from exc


class CommitmentStore:
    """Resolves a reference to the record it names, and refuses one that has been altered.

    In memory, like I2's registry backend: durability is I5. What it does hold now is the property
    a reference is for — resolving a commitment either returns the exact record that was signed, or
    raises. There is no third outcome where a tampered record resolves.
    """

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}

    def put(self, signed: dict[str, Any]) -> str:
        reference = commitment_of(signed)
        self._records[reference] = signed
        return reference

    def resolve(self, reference: str, public_key: Any) -> dict[str, Any]:
        record = self._records.get(reference)
        if record is None:
            raise CommitmentError(f"unknown commitment {reference!r}")
        if commitment_of(record) != reference:
            raise CommitmentError(
                f"commitment {reference!r} does not match the record it names; the record was "
                f"altered after it was referenced")
        try:
            return kernel.verify(record, public_key)
        except kernel.MessageError as exc:
            raise CommitmentError(f"commitment {reference!r} does not verify: {exc}") from exc


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise CommitmentError(f"{name} must be a non-empty string")
    return value


def _digest(name: str, value: Any) -> str:
    value = _text(name, value)
    if not value.startswith("sha256:"):
        raise CommitmentError(f"{name} must be a digest reference, got {value!r}")
    return value


def _index(name: str, value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CommitmentError(f"{name} must be a non-negative integer")
    return value


def _previous(value: Any) -> str:
    """`previous_commitment`: a digest, or "" for the first link in a chain.

    The empty string is the genesis sentinel I2's registry already uses (`previous_commitment !=
    (head or "")`). Two layers disagreeing on how genesis is spelled is the cross-contract defect
    AM-39 was written for, one level down — so it is spelled once, here, the same way.
    """
    if value == "":
        return ""
    return _digest("previous_commitment", value)


def _refs(name: str, values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise CommitmentError(f"{name} must be a list")
    return [_digest(f"{name}[{i}]", v) for i, v in enumerate(values)]


def _member(name: str, value: Any, allowed: frozenset[str]) -> str:
    value = _text(name, value)
    if value not in allowed:
        raise CommitmentError(f"{name} must be one of {sorted(allowed)}, got {value!r}")
    return value


class SequenceSource:
    """Allocates `sequence` per signing identity (§6), not per signer object.

    Two `CommitmentSigner` instances for the same `key_id` each starting at 0 produced
    byte-identical signed messages — Ed25519 is deterministic, so the duplicate was invisible: same
    bytes, same signature, two different attestations collapsing to one commitment reference. A
    test asserting a reference covers the signature caught it.

    `sequence` is "per-signing-identity, atomic, durable" in §6. This gives the first two. Durable
    is I5's, and the seam is here so I5 replaces the allocator without touching a builder.
    """

    def __init__(self) -> None:
        self._next: dict[str, int] = {}

    def allocate(self, key_id: str) -> int:
        value = self._next.get(key_id, 0)
        self._next[key_id] = value + 1
        return value


#: Process-wide default, so two signers for one identity share its ordering rather than each
#: believing it is the only one. Not durable; I5 owns that.
SEQUENCES = SequenceSource()


class CommitmentSigner:
    """One signing identity. Every emission is authorized by the registry before it is signed."""

    def __init__(self, registry: AuthorityRegistry, key_id: str, private_key: Any,
                 producer_identity: str, deployment_mode: str = "B", clock: Any = None,
                 sequences: SequenceSource | None = None):
        self._registry = registry
        self._key_id = key_id
        self._private_key = private_key
        self._producer_identity = producer_identity
        self._deployment_mode = deployment_mode
        self._clock = clock or (lambda: "1970-01-01T00:00:00Z")
        self._sequences = sequences if sequences is not None else SEQUENCES

    def _emit(self, message_type: str, action: str, body: dict[str, Any],
              project: str | None) -> dict[str, Any]:
        # I2's question, asked before signing rather than after: a key that may not sign this
        # type, action or scope never produces a signature at all.
        self._registry.authorize(self._key_id, message_type, action, project)
        # Allocated only after authorization: a refused emission consumes no sequence number.
        sequence = self._sequences.allocate(self._key_id)
        message = kernel.message(
            message_type, action, key_id=self._key_id,
            producer_identity=self._producer_identity, sequence=sequence,
            signed_at=self._clock(), deployment_mode=self._deployment_mode, body=body)
        return kernel.sign(message, self._private_key)

    # -- §6 bodies, one typed builder each ------------------------------------------------------

    def project_genesis(self, *, project_id: str, repository_identity: str,
                        initial_base_digest: str, policy_baseline: str, gate_baseline: str,
                        obligation_policy_baseline: str, provisioned_by: str,
                        provisioning_sequence: int) -> dict[str, Any]:
        return self._emit("PROJECT", "genesis", {
            "project_id": _text("project_id", project_id),
            "repository_identity": _text("repository_identity", repository_identity),
            "initial_base_digest": _digest("initial_base_digest", initial_base_digest),
            "policy_baseline": _digest("policy_baseline", policy_baseline),
            "gate_baseline": _digest("gate_baseline", gate_baseline),
            "obligation_policy_baseline": _digest("obligation_policy_baseline",
                                                  obligation_policy_baseline),
            "provisioned_by": _text("provisioned_by", provisioned_by),
            "provisioning_sequence": _index("provisioning_sequence", provisioning_sequence),
        }, project_id)

    def task(self, *, action: str, project: str, project_commitment: str, task_digest: str,
             relation: str, parent_task_commitment: str | None = None) -> dict[str, Any]:
        body = {
            "project_commitment": _digest("project_commitment", project_commitment),
            "task_digest": _digest("task_digest", task_digest),
            "relation": _text("relation", relation),
        }
        if not RELATION.match(body["relation"]):
            raise CommitmentError(
                f"relation {relation!r} is not in §7.0's closed enum: NEW_TASK, "
                f"CONTINUATION_OF(task-X), SUPERSEDES(task-X), CHILD_OF(task-X)")
        if parent_task_commitment is not None:
            body["parent_task_commitment"] = _digest("parent_task_commitment",
                                                     parent_task_commitment)
        return self._emit("TASK", _member("action", action, kernel.ACTIONS["TASK"]), body, project)

    def run(self, *, project: str, project_commitment: str, task_commitment: str,
            creation_nonce: str, run_id: str, parent_run_commitments: list[str],
            authorized_base_commitment: str, policy_head: str) -> dict[str, Any]:
        return self._emit("RUN", "create", {
            "project_commitment": _digest("project_commitment", project_commitment),
            "task_commitment": _digest("task_commitment", task_commitment),
            "creation_nonce": _text("creation_nonce", creation_nonce),
            "run_id": _text("run_id", run_id),
            "parent_run_commitments": _refs("parent_run_commitments", parent_run_commitments),
            "authorized_base_commitment": _digest("authorized_base_commitment",
                                                  authorized_base_commitment),
            "policy_head": _digest("policy_head", policy_head),
        }, project)

    def gate(self, *, project: str, run_commitment: str, gate_content_digest: str,
             freeze_policy_version: str, baseline_match: bool | None = None,
             human_authorization: str | None = None) -> dict[str, Any]:
        body = {
            "run_commitment": _digest("run_commitment", run_commitment),
            "gate_content_digest": _digest("gate_content_digest", gate_content_digest),
            "freeze_policy_version": _text("freeze_policy_version", freeze_policy_version),
        }
        # §8: a baseline match OR a human authorization for THIS gate content. Neither is a gate
        # nobody authorized; both is a claim the contract does not define, so both are refused.
        if (baseline_match is None) == (human_authorization is None):
            raise CommitmentError(
                "a gate carries exactly one of baseline_match or human_authorization (§8)")
        if baseline_match is not None:
            if not isinstance(baseline_match, bool):
                raise CommitmentError("baseline_match must be a boolean")
            body["baseline_match"] = baseline_match
        else:
            body["human_authorization"] = _digest("human_authorization", human_authorization)
        return self._emit("GATE", "freeze", body, project)

    def verify_attestation(self, *, project: str, run_commitment: str, gate_commitment: str,
                           candidate_fingerprint: str, obligation_id: str,
                           verification_method: str, verdict: str, observation_digest: str,
                           supersedes: str | None = None) -> dict[str, Any]:
        body = {
            "run_commitment": _digest("run_commitment", run_commitment),
            "gate_commitment": _digest("gate_commitment", gate_commitment),
            "candidate_fingerprint": _digest("candidate_fingerprint", candidate_fingerprint),
            "obligation_id": _text("obligation_id", obligation_id),
            "verification_method": _text("verification_method", verification_method),
            "verdict": _text("verdict", verdict),
            "observation_digest": _digest("observation_digest", observation_digest),
        }
        if supersedes is not None:
            # AM-40: the assertion is representable and signed. Whether the five conditions hold
            # is Stage 2's, deliberately not checked here.
            body["supersedes"] = _digest("supersedes", supersedes)
        return self._emit("VERIFY", "attest", body, project)

    def decision(self, *, project: str, decision: str, run_commitment: str,
                 candidate_fingerprint: str, decision_snapshot_digest: str,
                 superseded_adverse_verdicts: list[str], policy_head: str) -> dict[str, Any]:
        """A typed signed record of a decision. This module reaches no decision of its own."""
        return self._emit("DECISION", _member("decision", decision, DECISIONS), {
            "run_commitment": _digest("run_commitment", run_commitment),
            "candidate_fingerprint": _digest("candidate_fingerprint", candidate_fingerprint),
            "decision": decision,
            "decision_snapshot_digest": _digest("decision_snapshot_digest",
                                                decision_snapshot_digest),
            "superseded_adverse_verdicts": _refs("superseded_adverse_verdicts",
                                                 superseded_adverse_verdicts),
            "policy_head": _digest("policy_head", policy_head),
        }, project)

    def policy(self, *, action: str, project: str, project_commitment: str, epoch: int,
               previous_commitment: str, class_authority_map_digest: str,
               predicate_class_map_digest: str) -> dict[str, Any]:
        return self._emit("POLICY", _member("action", action, kernel.ACTIONS["POLICY"]), {
            "project_commitment": _digest("project_commitment", project_commitment),
            "epoch": _index("epoch", epoch),
            "previous_commitment": _previous(previous_commitment),
            "class_authority_map_digest": _digest("class_authority_map_digest",
                                                  class_authority_map_digest),
            # AM-39: two different authorities, two digests, never one bundle.
            "predicate_class_map_digest": _digest("predicate_class_map_digest",
                                                  predicate_class_map_digest),
        }, project)

    def applicability(self, *, project: str, transition: str, project_commitment: str,
                      obligation_id: str, obligation_class: str, predicate_scope_digest: str,
                      condition_commitment: str, epoch: int, previous_commitment: str,
                      authorization_ref: str) -> dict[str, Any]:
        return self._emit("APPLICABILITY", _member("transition", transition, TRANSITIONS), {
            "project_commitment": _digest("project_commitment", project_commitment),
            "obligation_id": _text("obligation_id", obligation_id),
            "obligation_class": _text("obligation_class", obligation_class),
            "predicate_scope_digest": _digest("predicate_scope_digest", predicate_scope_digest),
            "condition_commitment": _digest("condition_commitment", condition_commitment),
            "transition": transition,
            "epoch": _index("epoch", epoch),
            "previous_commitment": _previous(previous_commitment),
            "authorization_ref": _digest("authorization_ref", authorization_ref),
        }, project)

    def registry(self, *, action: str, epoch: int, previous_commitment: str,
                 key_grants_digest: str, project: str | None = None) -> dict[str, Any]:
        return self._emit("REGISTRY", _member("action", action, kernel.ACTIONS["REGISTRY"]), {
            "epoch": _index("epoch", epoch),
            "previous_commitment": _previous(previous_commitment),
            "key_grants_digest": _digest("key_grants_digest", key_grants_digest),
        }, project)

    def migration(self, *, action: str, project_commitments: list[str], reason: str, expiry: str,
                  authorization_ref: str, epoch: int, previous_commitment: str,
                  project: str | None = None) -> dict[str, Any]:
        commitments = _refs("project_commitments", project_commitments)
        if not commitments:
            # §12: enumerated, never a wildcard. An empty enumeration is a wildcard by omission.
            raise CommitmentError("migration must enumerate its projects, never a wildcard (§12)")
        return self._emit("MIGRATION", _member("action", action, kernel.ACTIONS["MIGRATION"]), {
            "project_commitments": commitments,
            "reason": _text("reason", reason),
            "expiry": _text("expiry", expiry),
            "authorization_ref": _digest("authorization_ref", authorization_ref),
            "epoch": _index("epoch", epoch),
            "previous_commitment": _previous(previous_commitment),
        }, project)

    def human_authorization(self, *, project: str, authorization_id: str, action_type: str,
                            target_message_type: str, project_commitment: str,
                            subject_digest: str, policy_head: str, use_semantics: str,
                            expiry: str, requested_transition: str | None = None
                            ) -> dict[str, Any]:
        if target_message_type not in kernel.DOMAINS:
            raise CommitmentError(
                f"target_message_type {target_message_type!r} is not a known domain; an "
                f"authorization names the domain it may be consumed by, and no other (§6.1)")
        body = {
            "authorization_id": _text("authorization_id", authorization_id),
            "action_type": _text("action_type", action_type),
            "target_message_type": target_message_type,
            "project_commitment": _digest("project_commitment", project_commitment),
            "subject_digest": _digest("subject_digest", subject_digest),
            "policy_head": _digest("policy_head", policy_head),
            "use_semantics": _member("use_semantics", use_semantics, USE_SEMANTICS),
            "expiry": _text("expiry", expiry),
        }
        if requested_transition is not None:
            body["requested_transition"] = _text("requested_transition", requested_transition)
        return self._emit("HUMAN", "authorize", body, project)
