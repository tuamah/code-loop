#!/usr/bin/env python3
"""F1-I1 — Cryptographic Message Kernel.

Implements T1A §6: the common signed envelope, the per-message-type body schemas, the closed action
enums, RFC 8785 canonicalization and Ed25519 domain-separated signatures. Nothing above §6 lives
here — no registry lookup, no admissibility procedure, no state. Those are I2 and later, and this
module deliberately cannot reach them.

**There is no signing oracle.** §2's first failure mode is a signer that endorses caller-supplied
assertions. So `sign()` takes a *structured message*, validates it completely, and derives the
signing domain from the validated `message_type`. There is no exported function that signs
caller-supplied bytes, and no parameter through which a caller chooses a domain prefix. A caller
can only ask for a signature over a message the kernel has already agreed is well-formed.

**Everything is fail-closed.** Unknown message type, unknown action for that type, unknown envelope
or body field, missing field, wrong type, a `message_type` that disagrees with the signed prefix,
or a payload that does not re-canonicalize byte-identically: all rejected, none ignored.

    msg = message("VERIFY", "attest", key_id=..., producer_identity=..., sequence=1,
                  signed_at="...", deployment_mode="B", body={...})
    signed = sign(msg, private_key)
    verify(signed, public_key)      -> the validated message, or raises
"""

from __future__ import annotations

from typing import Any

from f1_canonical import CanonicalizationError, canonicalize

# Three different questions, three different answers. Binding them into one string was the first
# design defect in this module: it would have made every historical message unparsable the moment
# T1A was reopened for a rule that does not touch the wire format at all, and F1's own principle is
# that retired material is never forgotten.
#
#   schema_version       how do I decode these bytes?         -> on the wire, below
#   contract revision    under which contract was it created? -> not on the wire; see below
#   current authoritative state
#                        is it still admissible today?        -> resolved at admissibility (I4+)
#
# An old message must stay cryptographically verifiable and structurally parseable; whether it is
# still *acceptable* is a question for current policy, and a reopened contract answers it by
# refusing the message, never by making it unreadable.
SCHEMA_VERSION = "1"

# What this kernel implements, recorded here and deliberately NOT carried in the envelope. Adding
# a wire field for it would be a change to §6's closed envelope, which means reopening a frozen
# contract; the trusted policy and registry context (I2) is where acceptable schema/contract
# combinations are decided.
CONTRACT_REVISION = "f1-t1a-rev24"

# T1A §6. Closed: a message type without a domain string and a body schema cannot be signed, and
# adding one is a contract change.
DOMAINS = {t: f"NOGAP::{t}::v1" for t in (
    "PROJECT", "TASK", "RUN", "GATE", "VERIFY", "DECISION",
    "POLICY", "APPLICABILITY", "REGISTRY", "MIGRATION", "HUMAN")}

# T1A §6 / AM-23. The exact operation, signed rather than inferred.
ACTIONS: dict[str, frozenset[str]] = {
    "PROJECT":       frozenset({"genesis"}),
    "TASK":          frozenset({"create", "relate"}),
    "RUN":           frozenset({"create"}),
    "GATE":          frozenset({"freeze"}),
    "VERIFY":        frozenset({"attest"}),
    "DECISION":      frozenset({"accept", "repair", "abstain", "human_review"}),
    "POLICY":        frozenset({"create", "update", "weaken"}),
    "APPLICABILITY": frozenset({"activate", "deactivate", "narrow", "reclassify"}),
    "REGISTRY":      frozenset({"add_key", "revoke_key", "retire_key", "rotate_root"}),
    "MIGRATION":     frozenset({"grant", "revoke"}),
    "HUMAN":         frozenset({"authorize"}),
}

ENVELOPE = ("schema_version", "message_type", "action", "key_id",
            "producer_identity", "sequence", "signed_at", "deployment_mode")

DEPLOYMENT_MODES = frozenset({"A", "B", "C"})

# T1A §6. Required fields, then optional ones. "Optional" here means may be absent — never null,
# never a shared grab-bag: a field absent from a body's schema is rejected, not ignored.
BODIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "PROJECT":       (("project_id", "repository_identity", "initial_base_digest",
                       "policy_baseline", "gate_baseline", "obligation_policy_baseline",
                       "provisioned_by", "provisioning_sequence"), ()),
    "TASK":          (("project_commitment", "task_digest", "relation"),
                      ("parent_task_commitment",)),
    "RUN":           (("project_commitment", "task_commitment", "creation_nonce", "run_id",
                       "parent_run_commitments", "authorized_base_commitment", "policy_head"), ()),
    "GATE":          (("run_commitment", "gate_content_digest", "freeze_policy_version"),
                      ("baseline_match", "human_authorization")),
    "VERIFY":        (("run_commitment", "gate_commitment", "candidate_fingerprint",
                       "obligation_id", "verification_method", "verdict", "observation_digest"),
                      ("supersedes",)),
    "DECISION":      (("run_commitment", "candidate_fingerprint", "decision",
                       "decision_snapshot_digest", "superseded_adverse_verdicts",
                       "policy_head"), ()),
    "POLICY":        (("project_commitment", "epoch", "previous_commitment",
                       "class_authority_map_digest", "predicate_class_map_digest"), ()),
    "APPLICABILITY": (("project_commitment", "obligation_id", "obligation_class",
                       "predicate_scope_digest", "condition_commitment", "transition",
                       "epoch", "previous_commitment", "authorization_ref"), ()),
    "REGISTRY":      (("epoch", "previous_commitment", "key_grants_digest"), ()),
    "MIGRATION":     (("project_commitments", "reason", "expiry", "authorization_ref",
                       "epoch", "previous_commitment"), ()),
    # T1A §6.1: a purpose-bound authorization, not a token.
    "HUMAN":         (("authorization_id", "action_type", "target_message_type",
                       "project_commitment", "subject_digest", "policy_head",
                       "use_semantics", "expiry"), ("requested_transition",)),
}


class MessageError(ValueError):
    """The message is not well-formed, so it is inadmissible. Never 'legacy compatible' (§12)."""


def _check_envelope(message: dict[str, Any]) -> None:
    keys = set(message) - {"body"}
    for field in ENVELOPE:
        if field not in keys:
            raise MessageError(f"envelope is missing {field!r}")
    for extra in sorted(keys - set(ENVELOPE)):
        raise MessageError(f"unknown envelope field {extra!r}; unknown fields are rejected (§6)")
    if "body" not in message:
        raise MessageError("message has no body")

    if message["schema_version"] != SCHEMA_VERSION:
        raise MessageError(f"unknown schema_version {message['schema_version']!r}")
    message_type = message["message_type"]
    if message_type not in DOMAINS:
        raise MessageError(f"unknown message_type {message_type!r}; the domain list is closed (§6)")
    if message["action"] not in ACTIONS[message_type]:
        raise MessageError(
            f"action {message['action']!r} is not in {message_type}'s closed enum "
            f"{sorted(ACTIONS[message_type])} (AM-23)")
    if message["deployment_mode"] not in DEPLOYMENT_MODES:
        raise MessageError(f"deployment_mode {message['deployment_mode']!r} is not A, B or C (§3)")
    if not isinstance(message["sequence"], int) or isinstance(message["sequence"], bool):
        raise MessageError("sequence must be an integer")
    if message["sequence"] < 0:
        raise MessageError("sequence must not be negative")
    for field in ("key_id", "producer_identity", "signed_at"):
        if not isinstance(message[field], str) or not message[field]:
            raise MessageError(f"{field} must be a non-empty string")


def _check_body(message_type: str, body: Any) -> None:
    if not isinstance(body, dict):
        raise MessageError("body must be an object")
    required, optional = BODIES[message_type]
    for field in required:
        if field not in body:
            raise MessageError(f"{message_type} body is missing {field!r}")
    for extra in sorted(set(body) - set(required) - set(optional)):
        raise MessageError(
            f"{extra!r} is not in {message_type}'s body schema; a field absent from a body's "
            f"schema is rejected, not optional (§6)")
    for field, value in body.items():
        if value is None:
            raise MessageError(f"{field!r} is null; absent fields are omitted, never null (§6)")


def validate(message: dict[str, Any]) -> dict[str, Any]:
    """Full §6 structural validation. Returns the message, or raises MessageError."""
    if not isinstance(message, dict):
        raise MessageError("message must be an object")
    _check_envelope(message)
    _check_body(message["message_type"], message["body"])
    try:
        canonical(message)
    except CanonicalizationError as exc:
        raise MessageError(f"payload is not canonicalizable: {exc}") from exc
    return message


def message(message_type: str, action: str, *, key_id: str, producer_identity: str,
            sequence: int, signed_at: str, deployment_mode: str,
            body: dict[str, Any]) -> dict[str, Any]:
    """Build a validated message. The only way to construct one this module will sign."""
    return validate({
        "schema_version": SCHEMA_VERSION, "message_type": message_type, "action": action,
        "key_id": key_id, "producer_identity": producer_identity, "sequence": sequence,
        "signed_at": signed_at, "deployment_mode": deployment_mode, "body": body,
    })


def canonical(message: dict[str, Any]) -> bytes:
    return canonicalize(message)


def signing_input(message: dict[str, Any]) -> bytes:
    """`NOGAP::TYPE::v1 || canonical_payload` (§6).

    The domain is derived from the validated message_type and is never a parameter. A VERIFY
    signature therefore cannot be reinterpreted as a DECISION even if the bodies coincide.
    """
    domain = DOMAINS[message["message_type"]]
    return domain.encode("ascii") + b"||" + canonical(message)


def sign(message: dict[str, Any], private_key: Any) -> dict[str, Any]:
    """Sign a structured message. There is no interface here that signs caller-supplied bytes."""
    validate(message)
    return {"message": message, "signature": private_key.sign(signing_input(message)).hex()}


def verify(signed: dict[str, Any], public_key: Any) -> dict[str, Any]:
    """Verify a signed message and return its validated content, or raise MessageError."""
    from cryptography.exceptions import InvalidSignature

    if not isinstance(signed, dict) or set(signed) != {"message", "signature"}:
        raise MessageError("a signed message carries exactly 'message' and 'signature'")
    message = validate(signed["message"])
    try:
        signature = bytes.fromhex(signed["signature"])
    except (ValueError, TypeError) as exc:
        raise MessageError("signature is not hex") from exc
    try:
        public_key.verify(signature, signing_input(message))
    except InvalidSignature as exc:
        raise MessageError("signature does not verify under this key and domain") from exc
    return message


def generate_key() -> Any:
    """A test/bootstrap keypair. Key storage and OS isolation are F1-T2, not this module."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.generate()
