#!/usr/bin/env python3
"""F1-I5 — Transactional Authoritative State (T1A §10.1, AM-24, AM-25, AM-26, AM-29).

The durable store the earlier milestones deferred to. I2 kept registry semantics behind a
`RegistryStore` interface, I3 declared its sequence bound as one process lifetime, and I4 kept its
sequence ledger in memory — all three named this module as where those debts are paid.

**One transactional domain (AM-26).** A transition routinely spans authorities: validate the
current POLICY head, check the REGISTRY grant, consume a HUMAN authorization, install the new
commitment. Across separate stores that is a distributed commit, which the contract neither
specifies nor wants, and an unspecified distributed commit is exactly how a half-transition
happens. So every authoritative fact lives in one serialized domain, and authorities are scopes
over it rather than separate stores.

**All-or-nothing.** The composite case is the whole point:

    validate registry head + validate policy heads + consume HUMAN authorization
    + allocate epoch/sequence + install transition          =  ONE commit

Either every part is durable or none is. A crash before, during or after the commit leaves the
store readable and consistent: the commit is a single atomic rename, so a reader sees the old state
or the new one and never a partial write.

**Two different durability disciplines, deliberately.**

`consume_authorization()` is a *linear capability* (AM-24) and commits with the transition it
spends, exactly as §10.1 requires — checking and consuming are one operation, never a check
followed by a write.

`allocate_sequence()` commits on its own, immediately. This is not an inconsistency: a sequence
numbers a signature that escapes into the world the moment it is made, so an allocation rolled back
by a later abort would be handed out twice for two different signatures. Reuse is the failure this
must never permit; an unused number is not. The consequence is that gaps are possible, which is
why §6 says gaps are reported and not ignored, and why I4's ledger reports them.

**Concurrency.** One writer at a time, enforced by an exclusive file lock, so two processes
allocating for the same signing identity serialize rather than race. Readers do not block.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

EMPTY: dict[str, Any] = {"heads": {}, "sequences": {}, "consumed": {}}


class StateError(RuntimeError):
    """The transition is refused. Absent, unknown or unverifiable state is never waved through."""


class ConflictError(StateError):
    """A CAS assertion failed: the state moved under the transaction. Retry against the new head."""


class Transaction:
    """A staged set of changes. Nothing it does is visible until `commit()` succeeds."""

    def __init__(self, store: "AuthoritativeStore", state: dict[str, Any]):
        self._store = store
        self._state = state
        self._staged = json.loads(json.dumps(state))
        self._done = False

    # -- reads, which are also the CAS assertions ------------------------------------------------

    def head(self, name: str) -> tuple[str, int] | None:
        entry = self._staged["heads"].get(name)
        return (entry["commitment"], entry["epoch"]) if entry else None

    def assert_head(self, name: str, expected_commitment: str) -> None:
        """`assert current_head == expected_previous else ABORT` (§10.1).

        The assertion is checked again under the lock at commit time, so this is a compare-and-set
        and not a check followed by a write — the shape AM-25 exists to forbid.
        """
        current = self.head(name)
        actual = current[0] if current else ""
        if actual != expected_commitment:
            raise ConflictError(
                f"{name} head is {actual!r}, not the expected {expected_commitment!r}; "
                f"a valid head is not the current head (AM-18)")

    # -- writes ----------------------------------------------------------------------------------

    def allocate_epoch(self, name: str) -> int:
        current = self.head(name)
        return (current[1] if current else 0) + 1

    def set_head(self, name: str, commitment: str, epoch: int) -> None:
        current = self.head(name)
        if current and epoch != current[1] + 1:
            raise StateError(f"{name} epoch {epoch} does not chain from {current[1]}")
        if not current and epoch != 1:
            raise StateError(f"{name} genesis epoch must be 1, got {epoch}")
        self._staged["heads"][name] = {"commitment": commitment, "epoch": epoch}

    def consume_authorization(self, authorization_id: str) -> None:
        """`consume_if_unconsumed(authorization_id)` — one operation, never check-then-write.

        A single-use authorization presented twice is refused on the second attempt, and the
        consumption becomes durable with the transition it spends, never before it.
        """
        if authorization_id in self._staged["consumed"]:
            raise StateError(
                f"authorization {authorization_id!r} is already consumed; a single-use "
                f"authorization is a linear capability (AM-24)")
        self._staged["consumed"][authorization_id] = True

    def is_consumed(self, authorization_id: str) -> bool:
        return authorization_id in self._staged["consumed"]

    # -- completion ------------------------------------------------------------------------------

    def commit(self) -> None:
        if self._done:
            raise StateError("transaction already completed")
        self._done = True
        self._store._commit(self._state, self._staged)

    def abort(self) -> None:
        self._done = True

    def __enter__(self) -> "Transaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._done:
            return False
        if exc_type is None:
            self.commit()
        else:
            self.abort()
        return False


class AuthoritativeStore:
    """Every authoritative fact, in one serialized domain, durable across a crash."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        self._lock = self._path.with_suffix(self._path.suffix + ".lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock.touch(exist_ok=True)

    # -- durability ------------------------------------------------------------------------------

    def read(self) -> dict[str, Any]:
        """The committed state. A crash can never leave this unreadable."""
        try:
            state = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return json.loads(json.dumps(EMPTY))
        except json.JSONDecodeError as exc:
            # Reachable only if something outside this module wrote the file: commits replace it
            # atomically, so a partial write is never published. Fail closed rather than guess.
            raise StateError(f"authoritative state is unreadable: {exc}") from exc
        for key in EMPTY:
            state.setdefault(key, {})
        return state

    def _write(self, state: dict[str, Any]) -> None:
        """Write, flush to disk, then publish with one atomic rename.

        The order matters and is the whole crash story: the temp file is fully on disk before the
        rename, and the rename is atomic, so a reader sees the old state or the new one. A crash
        before the rename leaves the old state; a crash after it leaves the new one. There is no
        instant at which the file holds half a transition.
        """
        with open(self._tmp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(self._tmp, self._path)
        directory = os.open(self._path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)      # the rename itself must survive the crash, not just the data
        finally:
            os.close(directory)

    def _commit(self, observed: dict[str, Any], staged: dict[str, Any]) -> None:
        with self._exclusive():
            current = self.read()
            if current != observed:
                # Re-checked under the lock: between staging and committing, another writer may
                # have moved the state. Check-then-act would silently overwrite them.
                raise ConflictError(
                    "the authoritative state changed while this transaction was open; "
                    "re-read the current head and retry")
            self._write(staged)

    def _exclusive(self):
        store = self

        class _Lock:
            def __enter__(self):
                self._handle = open(store._lock, "r+")
                fcntl.flock(self._handle, fcntl.LOCK_EX)
                return self

            def __exit__(self, *exc):
                fcntl.flock(self._handle, fcntl.LOCK_UN)
                self._handle.close()
                return False

        return _Lock()

    # -- transactions ----------------------------------------------------------------------------

    def transaction(self) -> Transaction:
        return Transaction(self, self.read())

    # -- sequence allocation ---------------------------------------------------------------------

    def allocate_sequence(self, key_id: str) -> int:
        """Atomic, durable, monotonic; never reused after a restart or a crash.

        Committed on its own rather than with a caller's transaction, and the reason is the point:
        the number goes into a signature that exists in the world as soon as it is made. Rolling
        the allocation back on a later abort would hand the same number to a second signature, and
        two attestations sharing a sequence share a commitment reference — the collision I3 was
        built after. An unused number is a gap, which §6 requires be reported, not prevented.
        """
        with self._exclusive():
            state = self.read()
            nxt = state["sequences"].get(key_id, 0)
            state["sequences"][key_id] = nxt + 1
            self._write(state)
            return nxt

    def next_sequence(self, key_id: str) -> int:
        """What `allocate_sequence` would return. A read, never an allocation."""
        return self.read()["sequences"].get(key_id, 0)

    def head(self, name: str) -> tuple[str, int] | None:
        entry = self.read()["heads"].get(name)
        return (entry["commitment"], entry["epoch"]) if entry else None

    def is_consumed(self, authorization_id: str) -> bool:
        return authorization_id in self.read()["consumed"]
