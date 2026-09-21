#!/usr/bin/env python3
"""F1-I2 — Authority Registry (T1A §5, §5.1, §11).

Answers exactly one question: **is this `key_id` granted this `message_type`, this action, in this
project scope — and is the key in a state that permits the signature at the TCB's acceptance
epoch?**

It does not answer whether a message is admissible. Stage 1 and Stage 2 are I4 and I6; this module
is what their steps 6-9 will call, and it deliberately implements nothing else.

**The invariants this exists to hold.**

    valid key                 is not every authority        (AM-20)
    valid signature           is not an authorized action
    an old valid head         is not the current head       (AM-18)
    a revoked key             is not silently forgotten     (§11 retention)
    the caller                cannot choose the registry head
    the executor              cannot mutate the registry    (§4: it holds no key)
    unknown grant/action/project                            -> fail closed (§12)

**Time.** `signed_at` is the signer's own clock and is never trusted here. Key state is evaluated
at the **TCB acceptance epoch**, a monotonic counter this module assigns when it accepts a
commitment — the only clock the contract trusts (§11, §10.3). Revocation is the one case where the
adversary holds the key and can backdate `signed_at` at will.

**Storage.** In memory, under the TCB. Durable state and the atomic transaction §10.1 requires are
I5; this module keeps the head-and-chain semantics so that I5 has something to make durable, and
does not pretend to be a database.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable

from f1_canonical import CanonicalizationError, canonicalize
from f1_kernel import ACTIONS, DOMAINS, MessageError, verify

WILDCARD = "*"

ACTIVE, RETIRED, REVOKED = "ACTIVE", "RETIRED", "REVOKED"

ADMISSIBLE, DISPUTED = "ADMISSIBLE", "DISPUTED"

# §4: these classes hold no private key of any kind, so they may never be granted anything.
KEYLESS_CLASSES = frozenset({"execution", "tool"})
AUTHORITY_CLASSES = frozenset({"verification", "acceptance", "freeze", "human",
                               "registry_root", "genesis"}) | KEYLESS_CLASSES


class RegistryError(ValueError):
    """The registry refuses. Absent, unknown or unverifiable authority is inadmissible (§12)."""


def digest(value: Any) -> str:
    """Digest of grant material, which is external input crossing into the TCB.

    A value the canonical profile refuses is refused *here*, as a registry error: a caller handing
    the registry unserializable material has failed the registry's check, not some inner one, and
    a trust boundary should present one refusal type rather than leak the layer that noticed.
    """
    try:
        return "sha256:" + hashlib.sha256(canonicalize(value)).hexdigest()
    except CanonicalizationError as exc:
        raise RegistryError(f"grant material is not canonicalizable: {exc}") from exc


class Grant:
    """What one key may do. Enumerated, never inferred from its class (AM-28)."""

    __slots__ = ("key_id", "public_key_hex", "identity", "authority_class",
                 "allowed_message_types", "allowed_actions", "allowed_projects")

    def __init__(self, key_id: str, public_key_hex: str, identity: str, authority_class: str,
                 allowed_message_types: Iterable[str], allowed_actions: dict[str, Iterable[str]],
                 allowed_projects: Iterable[str]):
        if not key_id or not isinstance(key_id, str):
            raise RegistryError("key_id must be a non-empty string")
        if authority_class not in AUTHORITY_CLASSES:
            raise RegistryError(f"unknown authority class {authority_class!r}")
        types = frozenset(allowed_message_types)
        if authority_class in KEYLESS_CLASSES and types:
            raise RegistryError(
                f"{authority_class!r} holds no private key (§4) and may not be granted "
                f"{sorted(types)}; the executor and the verification worker hold no key")
        for message_type in sorted(types):
            if message_type not in DOMAINS:
                raise RegistryError(f"grant names unknown message_type {message_type!r}")
            actions = frozenset(allowed_actions.get(message_type, ()))
            if not actions:
                raise RegistryError(
                    f"grant for {message_type} names no action; a type with no action cannot be "
                    f"granted (AM-20)")
            unknown = actions - ACTIONS[message_type]
            if unknown:
                raise RegistryError(
                    f"grant names action(s) {sorted(unknown)} outside {message_type}'s closed "
                    f"enum {sorted(ACTIONS[message_type])}")
        for extra in sorted(set(allowed_actions) - types):
            raise RegistryError(f"grant lists actions for {extra!r}, which it does not allow")
        projects = tuple(allowed_projects)
        if not projects:
            raise RegistryError("grant names no project scope; a wildcard must be declared (§5.1)")

        self.key_id = key_id
        self.public_key_hex = public_key_hex
        self.identity = identity
        self.authority_class = authority_class
        self.allowed_message_types = types
        self.allowed_actions = {t: frozenset(allowed_actions[t]) for t in types}
        self.allowed_projects = frozenset(projects)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id, "public_key": self.public_key_hex, "identity": self.identity,
            "authority_class": self.authority_class,
            "allowed_message_types": sorted(self.allowed_message_types),
            "allowed_actions": {t: sorted(a) for t, a in sorted(self.allowed_actions.items())},
            "allowed_projects": sorted(self.allowed_projects),
        }

    def covers(self, message_type: str, action: str, project: str | None) -> None:
        if message_type not in self.allowed_message_types:
            raise RegistryError(
                f"{self.key_id} is not granted {message_type}; possessing a valid key is not "
                f"possessing every TCB authority (AM-20)")
        if action not in self.allowed_actions[message_type]:
            raise RegistryError(
                f"{self.key_id} is granted {message_type} but not its action {action!r} "
                f"(granted: {sorted(self.allowed_actions[message_type])})")
        if WILDCARD in self.allowed_projects:
            return
        if project is None:
            raise RegistryError(
                f"{self.key_id} has a scoped grant, so the operation must name a project")
        if project not in self.allowed_projects:
            raise RegistryError(f"{self.key_id} is not granted project scope {project!r}")


class RegistryStore:
    """Where registry state lives. The semantics above never assume how.

    I2 proves the semantics — head, epoch, previous_commitment, grants, rotation, retirement,
    revocation, historical resolution — against an in-memory backend. I5 replaces the backend with
    durable, atomic storage and must not have to change a single rule above it, so the seam is here
    rather than a `dict` the registry reaches into directly.

    `transaction()` is part of the interface from the start, not a later addition: §10.1 requires
    validating and mutating authoritative state to be one operation, and a store that cannot
    express a transaction boundary cannot be made to satisfy that later without reshaping every
    caller. The in-memory implementation stages and swaps; a durable one commits.
    """

    def transaction(self) -> "RegistryStore":
        raise NotImplementedError

    def commit(self) -> None:
        raise NotImplementedError

    def head(self) -> str | None:
        raise NotImplementedError

    def epoch(self) -> int:
        raise NotImplementedError

    def acceptance_epoch(self) -> int:
        raise NotImplementedError

    def set_head(self, commitment: str, epoch: int) -> None:
        raise NotImplementedError

    def next_acceptance_epoch(self) -> int:
        raise NotImplementedError

    def get_key(self, key_id: str) -> "_KeyState | None":
        raise NotImplementedError

    def put_key(self, key_id: str, state: "_KeyState") -> None:
        raise NotImplementedError

    def append_chain(self, entry: dict[str, Any]) -> None:
        raise NotImplementedError


class InMemoryRegistryStore(RegistryStore):
    """I2's backend. Deliberately temporary; it holds no durability claim.

    `transaction()` returns a staged copy and `commit()` swaps it in, so a refused commitment
    leaves nothing behind. That is not the atomicity §10.1 asks for — there is no crash recovery
    here — but a half-applied commitment is a defect at any level of durability: a probe found a
    rejected `apply()` leaving a key ACTIVE that the registry had never accepted, which would
    authorize as soon as any later commitment set a head.
    """

    def __init__(self, keys=None, chain=None, head=None, epoch=0, acceptance_epoch=0):
        self._keys = dict(keys or {})
        self._chain = list(chain or [])
        self._head = head
        self._epoch = epoch
        self._acceptance = acceptance_epoch
        self._parent: "InMemoryRegistryStore | None" = None

    def transaction(self) -> "InMemoryRegistryStore":
        staged = InMemoryRegistryStore(self._keys, self._chain, self._head,
                                       self._epoch, self._acceptance)
        staged._parent = self
        return staged

    def commit(self) -> None:
        if self._parent is None:
            raise RegistryError("commit() outside a transaction")
        parent = self._parent
        parent._keys, parent._chain = self._keys, self._chain
        parent._head, parent._epoch, parent._acceptance = self._head, self._epoch, self._acceptance

    def head(self):
        return self._head

    def epoch(self) -> int:
        return self._epoch

    def acceptance_epoch(self) -> int:
        return self._acceptance

    def set_head(self, commitment: str, epoch: int) -> None:
        self._head, self._epoch = commitment, epoch

    def next_acceptance_epoch(self) -> int:
        self._acceptance += 1
        return self._acceptance

    def get_key(self, key_id: str):
        return self._keys.get(key_id)

    def put_key(self, key_id: str, state) -> None:
        self._keys[key_id] = state

    def append_chain(self, entry: dict[str, Any]) -> None:
        self._chain.append(entry)


class _KeyState:
    __slots__ = ("grant", "state", "registered_at", "retired_at", "compromised_after")

    def __init__(self, grant: Grant, registered_at: int):
        self.grant = grant
        self.state = ACTIVE
        self.registered_at = registered_at
        self.retired_at: int | None = None
        self.compromised_after: int | None = None


class AuthorityRegistry:
    """The TCB-held registry: an append-only, headed chain of accepted REGISTRY commitments."""

    def __init__(self, root_public_key: Any, root_key_id: str = "registry-root",
                 store: RegistryStore | None = None):
        self._root_public_key = root_public_key
        self._root_key_id = root_key_id
        # I2 defaults to memory; I5 passes a durable, atomic store and changes no rule below.
        self._store = store if store is not None else InMemoryRegistryStore()

    # -- head -----------------------------------------------------------------------------------

    @property
    def head(self) -> str | None:
        """The current authoritative head. There is no setter, and no API takes one (AM-18)."""
        return self._store.head()

    @property
    def epoch(self) -> int:
        """The chain epoch of the current head. Read-only, like the head itself."""
        return self._store.epoch()

    @property
    def acceptance_epoch(self) -> int:
        return self._store.acceptance_epoch()

    # -- mutation -------------------------------------------------------------------------------

    def apply(self, signed: dict[str, Any], grants: list[dict[str, Any]]) -> int:
        """Accept one signed REGISTRY commitment. Returns the TCB acceptance epoch it was given.

        `grants` is the material the commitment's `key_grants_digest` commits to; it is checked
        against that digest, so the caller cannot hand over different material than was signed.

        The whole acceptance runs in one store transaction: a refused commitment leaves no key, no
        epoch and no head behind. Durability and crash recovery are I5's; not half-applying is
        this module's, at any level of durability.
        """
        message = verify(signed, self._root_public_key)
        if message["message_type"] != "REGISTRY":
            raise RegistryError("not a REGISTRY commitment")
        if message["key_id"] != self._root_key_id:
            raise RegistryError(
                f"registry commitments are signed by the trust root, not {message['key_id']!r}")
        body = message["body"]

        staged = self._store.transaction()

        # AM-18 / §10.3: the head this extends must be the current one, and the epoch must chain.
        # A fork from an old-but-correctly-signed head is refused here, not reconciled later.
        if body["previous_commitment"] != (staged.head() or ""):
            raise RegistryError(
                f"previous_commitment {body['previous_commitment']!r} is not the current head "
                f"{staged.head()!r}; a valid head is not the current head (AM-18)")
        if body["epoch"] != staged.epoch() + 1:
            raise RegistryError(
                f"epoch {body['epoch']!r} does not chain from {staged.epoch()}")
        if body["key_grants_digest"] != digest(grants):
            raise RegistryError("key_grants_digest does not commit to the grants supplied")

        accepted_at = staged.next_acceptance_epoch()
        for entry in grants:
            self._apply_grant(staged, entry, accepted_at, message["action"])

        commitment = digest(message)
        staged.set_head(commitment, body["epoch"])
        staged.append_chain({"commitment": commitment, "epoch": body["epoch"],
                             "accepted_at": accepted_at, "message": message})
        staged.commit()
        return accepted_at

    def _apply_grant(self, store: RegistryStore, entry: dict[str, Any], at: int,
                     action: str) -> None:
        key_id = entry.get("key_id")
        if action == "add_key":
            grant = Grant(
                key_id=key_id, public_key_hex=entry["public_key"], identity=entry["identity"],
                authority_class=entry["authority_class"],
                allowed_message_types=entry["allowed_message_types"],
                allowed_actions=entry["allowed_actions"],
                allowed_projects=entry["allowed_projects"])
            existing = store.get_key(key_id)
            if existing is not None and existing.grant.public_key_hex != grant.public_key_hex:
                # A key_id is an identity, not a label. Rebinding it to another public key would
                # silently re-attribute every signature it ever made.
                raise RegistryError(
                    f"{key_id} is already bound to a different public key; a key_id is never "
                    f"rebound. Rotation mints a NEW key_id (§11)")
            store.put_key(key_id, _KeyState(grant, registered_at=at))
            return

        state = store.get_key(key_id)
        if state is None:
            raise RegistryError(f"{action} names unknown key_id {key_id!r}")
        if action == "retire_key":
            state.state, state.retired_at = RETIRED, at
        elif action == "revoke_key":
            # A bound on the TCB's own ordering, never an instant the signer asserts.
            bound = entry.get("compromised_after_epoch")
            if not isinstance(bound, int) or isinstance(bound, bool) or bound < 0:
                raise RegistryError(
                    "revocation needs compromised_after_epoch, a TCB acceptance epoch (§11)")
            state.state, state.compromised_after = REVOKED, bound
        elif action == "rotate_root":
            raise RegistryError("root rotation is F1-T2, not I2")
        else:
            raise RegistryError(f"unknown registry action {action!r}")

    # -- queries --------------------------------------------------------------------------------

    def verification_key(self, key_id: str) -> str:
        """The public key for historical verification. Retired and revoked keys resolve here.

        §11 retention: forgetting a key makes every decision it signed unverifiable, which silently
        rewrites history. Resolving a key for verification is never authorizing it to sign — that
        is `authorize()`, and the separation is the point.
        """
        state = self._store.get_key(key_id)
        if state is None:
            raise RegistryError(f"unknown key_id {key_id!r}")
        return state.grant.public_key_hex

    def state_of(self, key_id: str) -> str:
        state = self._store.get_key(key_id)
        if state is None:
            raise RegistryError(f"unknown key_id {key_id!r}")
        return state.state

    def authorize(self, key_id: str, message_type: str, action: str,
                  project: str | None = None) -> str:
        """§5.1's grant check at the current head, evaluated at the TCB acceptance epoch.

        Returns ADMISSIBLE. Raises RegistryError otherwise. It never returns "valid" for an
        unknown anything.
        """
        if self._store.head() is None:
            raise RegistryError("registry has no accepted head; unverifiable authority is "
                                "inadmissible, never legacy-compatible (§12)")
        state = self._store.get_key(key_id)
        if state is None:
            raise RegistryError(f"unknown key_id {key_id!r}")
        state.grant.covers(message_type, action, project)

        if state.state == RETIRED:
            raise RegistryError(
                f"{key_id} is retired and may not sign new material; its earlier signatures stay "
                f"valid (§11)")
        if state.state == REVOKED:
            # §11: state is evaluated at the TCB's acceptance epoch, never at signed_at. New
            # material is accepted now, which is at or after the bound by construction.
            raise RegistryError(
                f"{key_id} is revoked (compromised after TCB epoch "
                f"{state.compromised_after}); new material is inadmissible whatever it claims "
                f"about when it was made (§11)")
        return ADMISSIBLE

    def classify_accepted(self, key_id: str, accepted_at_epoch: int) -> str:
        """How to read a signature ALREADY accepted into TCB state at a given epoch (§11).

        At or after the compromise bound: inadmissible. Earlier: DISPUTED — not silently valid,
        not silently void, requiring human re-affirmation. The runtime never asserts a precise
        compromise instant it cannot establish.
        """
        state = self._store.get_key(key_id)
        if state is None:
            raise RegistryError(f"unknown key_id {key_id!r}")
        if state.state != REVOKED:
            return ADMISSIBLE
        if accepted_at_epoch >= state.compromised_after:
            raise RegistryError(
                f"{key_id}: accepted at TCB epoch {accepted_at_epoch}, at or after the compromise "
                f"bound {state.compromised_after}; definitely invalid (§11)")
        return DISPUTED
