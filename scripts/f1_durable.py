#!/usr/bin/env python3
"""F1-I5b — Durable Wiring.

I5 proved the transactional store on its own; I2, I3 and I4 were still running on temporary
in-memory backends. This module replaces those seams with the durable store and **adds no
semantics**.

    RegistryStore           -> durable backend, one AuthoritativeStore transaction per acceptance
    SequenceSource          -> durable allocate_sequence(key_id)
    SequenceLedger          -> durable last-seen and gap record
    authorization consume   -> the same transaction as the dependent transition
    current heads           -> persistent, with CAS

**The criterion this milestone is judged by: wiring changes persistence, not security semantics.**
Every accept/reject behaviour from I1-I4 must be identical, only with durable state — so the
seams here implement the interfaces those milestones already defined rather than reshaping them.
If a rule had to change to make persistence work, that would be a finding, not a wiring step.

Keeping this separate from I6 is deliberate: bundling durable wiring with Stage 2 semantics would
mix two kinds of change in one step, and any regression afterwards would be ambiguous between
them.
"""

from __future__ import annotations

from typing import Any

from f1_commitments import SequenceSource
from f1_registry import ACTIVE, Grant, RegistryError, RegistryStore, _KeyState
from f1_stage1 import SequenceLedger
from f1_state import AuthoritativeStore, StateError

#: The registry's head lives under this scope name in the one transactional domain (AM-26).
REGISTRY_SCOPE = "registry"


def _key_to_dict(state: _KeyState) -> dict[str, Any]:
    return {"grant": state.grant.as_dict(), "state": state.state,
            "registered_at": state.registered_at, "retired_at": state.retired_at,
            "compromised_after": state.compromised_after}


def _key_from_dict(raw: dict[str, Any]) -> _KeyState:
    grant_fields = raw["grant"]
    grant = Grant(
        key_id=grant_fields["key_id"], public_key_hex=grant_fields["public_key"],
        identity=grant_fields["identity"], authority_class=grant_fields["authority_class"],
        allowed_message_types=grant_fields["allowed_message_types"],
        allowed_actions=grant_fields["allowed_actions"],
        allowed_projects=grant_fields["allowed_projects"])
    state = _KeyState(grant, registered_at=raw["registered_at"])
    state.state = raw["state"]
    state.retired_at = raw["retired_at"]
    state.compromised_after = raw["compromised_after"]
    return state


class DurableRegistryStore(RegistryStore):
    """I2's `RegistryStore`, backed by the one transactional domain.

    The interface is I2's, unchanged. A registry acceptance runs inside one `AuthoritativeStore`
    transaction, so the head, the epoch, the acceptance counter, every grant it installs and any
    authorization it spends commit together or not at all — the half-commit I2 already refused in
    memory now refuses across a crash as well.
    """

    def __init__(self, store: AuthoritativeStore, scope: str = REGISTRY_SCOPE,
                 _transaction: Any = None, _parent: "DurableRegistryStore | None" = None):
        self._store = store
        self._scope = scope
        self._tx = _transaction
        self._parent = _parent
        self._authorizations: list[str] = []

    # -- transaction ----------------------------------------------------------------------------

    def transaction(self) -> "DurableRegistryStore":
        return DurableRegistryStore(self._store, self._scope,
                                    _transaction=self._store.transaction(), _parent=self)

    def commit(self) -> None:
        if self._tx is None:
            raise RegistryError("commit() outside a transaction")
        try:
            self._tx.commit()
        except StateError as exc:
            raise RegistryError(str(exc)) from exc

    def consume_authorization(self, authorization_id: str) -> None:
        """Spend a single-use authorization in the SAME transaction as the transition (AM-24)."""
        if self._tx is None:
            raise RegistryError("an authorization is consumed inside a transaction, never outside")
        try:
            self._tx.consume_authorization(authorization_id)
        except StateError as exc:
            raise RegistryError(str(exc)) from exc

    # -- state ----------------------------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        return self._tx._staged if self._tx is not None else self._store.read()

    def _registry(self) -> dict[str, Any]:
        return self._read().setdefault("registries", {}).setdefault(
            self._scope, {"keys": {}, "chain": [], "acceptance": 0})

    def head(self) -> str | None:
        current = (self._tx.head(self._scope) if self._tx is not None
                   else self._store.head(self._scope))
        return current[0] if current else None

    def epoch(self) -> int:
        current = (self._tx.head(self._scope) if self._tx is not None
                   else self._store.head(self._scope))
        return current[1] if current else 0

    def acceptance_epoch(self) -> int:
        return self._registry()["acceptance"]

    def set_head(self, commitment: str, epoch: int) -> None:
        if self._tx is None:
            raise RegistryError("the head moves inside a transaction, never outside")
        try:
            self._tx.set_head(self._scope, commitment, epoch)
        except StateError as exc:
            raise RegistryError(str(exc)) from exc

    def next_acceptance_epoch(self) -> int:
        registry = self._registry()
        registry["acceptance"] += 1
        return registry["acceptance"]

    def get_key(self, key_id: str) -> _KeyState | None:
        raw = self._registry()["keys"].get(key_id)
        return _key_from_dict(raw) if raw is not None else None

    def put_key(self, key_id: str, state: _KeyState) -> None:
        self._registry()["keys"][key_id] = _key_to_dict(state)

    def append_chain(self, entry: dict[str, Any]) -> None:
        # The chain records what was accepted and when. Retention is §11's rule: nothing here is
        # ever removed, so a historical key stays resolvable across a restart.
        self._registry()["chain"].append(
            {"commitment": entry["commitment"], "epoch": entry["epoch"],
             "accepted_at": entry["accepted_at"]})


class DurableSequenceSource(SequenceSource):
    """I3's `SequenceSource`, with the bound it declared now actually closed.

    I3 guaranteed uniqueness and monotonicity per identity *within one process lifetime*, and said
    plainly that cross-process uniqueness and crash-persistent monotonicity needed durable shared
    sequencing. This is that allocator: atomic, durable, monotonic, never reused after a restart,
    and shared by every signer for the identity.
    """

    def __init__(self, store: AuthoritativeStore):
        self._store = store

    def allocate(self, key_id: str) -> int:
        return self._store.allocate_sequence(key_id)


class DurableSequenceLedger(SequenceLedger):
    """I4's ledger, made durable. Same rule: a gap is reported, a repeat or reorder is refused.

    A ledger that forgets on restart would accept a replay of every message it had already seen,
    which is the step 11 check not being a check at all.
    """

    def __init__(self, store: AuthoritativeStore, scope: str = "sequence_ledger"):
        self._store = store
        self._scope = scope

    def _read(self) -> dict[str, Any]:
        return self._store.read().setdefault(self._scope, {"last": {}, "gaps": []})

    @property
    def gaps(self) -> list[tuple[str, int, int]]:
        return [tuple(gap) for gap in self._read()["gaps"]]

    def observe(self, key_id: str, sequence: int) -> str | None:
        with self._store._exclusive():
            state = self._store.read()
            ledger = state.setdefault(self._scope, {"last": {}, "gaps": []})
            last = ledger["last"].get(key_id)
            if last is None:
                ledger["last"][key_id] = sequence
                self._store._write(state)
                return None
            if sequence <= last:
                return (f"sequence {sequence} is not ahead of {last}, the last seen for "
                        f"{key_id!r}; a repeated or reordered sequence is inadmissible")
            if sequence > last + 1:
                ledger["gaps"].append([key_id, last, sequence])
            ledger["last"][key_id] = sequence
            self._store._write(state)
            return None
