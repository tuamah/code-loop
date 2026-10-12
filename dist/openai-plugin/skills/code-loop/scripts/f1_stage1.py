#!/usr/bin/env python3
"""F1-I4 — Stage 1 Admissibility (T1A §10).

The ordered, fail-closed procedure every message passes before anything type-specific happens.
Stage 2 is I6 and is deliberately absent: this module answers "may this message be considered at
all", never "what does it mean" or "what should happen".

**The procedure is normative and complete (AM-22).** A rule stated in one section and absent from
the procedure that enforces it is not enforced — that is how a valid key signing a type it was
never granted passed every enumerated step in revision 9. So the twelve steps are implemented as
twelve steps, in order, and a test reads them out of the frozen contract and asserts this module
implements each one.

**There is no default-admissible path.** Every step either passes or returns a verdict; falling off
the end of the procedure is impossible by construction, because the verdict is built from the steps
rather than initialised to ADMISSIBLE and downgraded.

**The caller supplies no state.** Heads, key state and sequence history come from the TCB, through
sources this module is constructed with. `check()` takes a message and nothing else, so there is no
parameter through which an adversary offers its own view of "current".
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import f1_kernel as kernel
from f1_canonical import CanonicalizationError
from f1_registry import ADMISSIBLE, DISPUTED, AuthorityRegistry, RegistryError

INADMISSIBLE = "INADMISSIBLE"

#: §3's modes, weakest first. "Not weaker than policy requires" needs an order, and Mode A is
#: explicitly not a security boundary, so it is the weakest.
MODE_STRENGTH = {"A": 0, "B": 1, "C": 2}

#: Step 10 is DERIVED, not a remembered list (§-1): a body field naming a head is one called
#: `previous_commitment` or ending in `_head`. A new head-bearing field is covered the day it is
#: added, which is the opposite of the drift AM-22 found.
HEAD_FIELD = re.compile(r"(^previous_commitment$|_head$)")


class Verdict:
    """The outcome of the procedure. Carries which step decided it, so a refusal is auditable."""

    __slots__ = ("status", "step", "reason")

    def __init__(self, status: str, step: int | None = None, reason: str = ""):
        self.status, self.step, self.reason = status, step, reason

    @property
    def admissible(self) -> bool:
        return self.status == ADMISSIBLE

    def __repr__(self) -> str:
        where = f" at step {self.step}" if self.step else ""
        return f"<{self.status}{where}: {self.reason}>" if self.reason else f"<{self.status}>"


class SequenceLedger:
    """What the TCB has already seen from each signing identity (§6, step 11).

    Gaps are **reported, not ignored**: a missing sequence number means a message this identity
    signed did not arrive, which is a fact about the history, not a formatting detail. In memory
    here; durable in I5, like every other authoritative counter.
    """

    def __init__(self) -> None:
        self._last: dict[str, int] = {}
        self.gaps: list[tuple[str, int, int]] = []

    def observe(self, key_id: str, sequence: int) -> str | None:
        """Record a sequence. Returns a refusal reason, or None. Gaps are recorded and allowed."""
        last = self._last.get(key_id)
        if last is None:
            self._last[key_id] = sequence
            return None
        if sequence <= last:
            # Replay or reordering: this identity has already been seen at or beyond here.
            return (f"sequence {sequence} is not ahead of {last}, the last seen for {key_id!r}; "
                    f"a repeated or reordered sequence is inadmissible")
        if sequence > last + 1:
            self.gaps.append((key_id, last, sequence))
        self._last[key_id] = sequence
        return None


class Stage1:
    """The §10 Stage 1 procedure, bound to TCB-held sources at construction."""

    def __init__(self, registry: AuthorityRegistry,
                 current_head: Callable[[str, str], str | None],
                 project_of: Callable[[dict[str, Any]], str | None],
                 required_mode: str = "B",
                 ledger: SequenceLedger | None = None,
                 acceptance_epoch: Callable[[], int] | None = None):
        self._registry = registry
        self._current_head = current_head
        self._project_of = project_of
        if required_mode not in MODE_STRENGTH:
            raise ValueError(f"required_mode must be one of {sorted(MODE_STRENGTH)}")
        self._required_mode = required_mode
        self._ledger = ledger if ledger is not None else SequenceLedger()
        self._acceptance_epoch = acceptance_epoch or (lambda: registry.acceptance_epoch)

    @property
    def ledger(self) -> SequenceLedger:
        return self._ledger

    def reclassify(self, key_id: str, accepted_at_epoch: int) -> Verdict:
        """Re-read a signature the TCB ALREADY accepted, after a revocation (§11, step 7).

        Step 7 reads "else INADMISSIBLE / DISPUTED", and the two outcomes belong to two different
        questions. For **new** material arriving at `check()`, DISPUTED is unreachable by
        construction: acceptance happens now, which is at or after any compromise bound, so §11
        makes it inadmissible whatever it claims about when it was made. DISPUTED is what becomes
        of material accepted *before* that bound — not silently valid, not silently void,
        requiring human re-affirmation.

        An earlier draft had `check()` test for DISPUTED inline. That branch was unreachable, and
        an unreachable security branch is worse than none: it reads like a handled case.
        """
        try:
            status = self._registry.classify_accepted(key_id, accepted_at_epoch)
        except RegistryError as exc:
            return Verdict(INADMISSIBLE, 7, str(exc))
        if status == DISPUTED:
            return Verdict(DISPUTED, 7,
                           f"{key_id} was accepted at TCB epoch {accepted_at_epoch}, before its "
                           f"compromise bound; requires human re-affirmation (§11)")
        return Verdict(ADMISSIBLE)

    def check(self, signed: dict[str, Any]) -> Verdict:
        """Run the twelve steps in order. The first failure decides, and says which step it was.

        Each step is named and reported separately. An earlier draft collapsed steps 1-5 into one
        kernel call, which passed the same messages but could not say *which* rule a refusal broke
        — and a procedure whose steps are not individually locatable is the drift AM-22 exists to
        stop. The kernel remains the single implementation of §6; these steps ask it the twelve
        questions in the contract's order rather than re-deriving its rules.
        """
        if not isinstance(signed, dict) or set(signed) != {"message", "signature"}:
            return Verdict(INADMISSIBLE, 1, "a signed message carries exactly message+signature")
        message = signed["message"]
        if not isinstance(message, dict):
            return Verdict(INADMISSIBLE, 1, "message is not an object")

        # Step 1: known schema_version, and the envelope re-canonicalizes byte-identically.
        if message.get("schema_version") != kernel.SCHEMA_VERSION:
            return Verdict(INADMISSIBLE, 1,
                           f"unknown schema_version {message.get('schema_version')!r}")
        try:
            if kernel.canonical(message) != kernel.canonical(json.loads(
                    kernel.canonical(message).decode("utf-8"))):
                return Verdict(INADMISSIBLE, 1, "payload does not re-canonicalize byte-identically")
        except (CanonicalizationError, ValueError) as exc:
            return Verdict(INADMISSIBLE, 1, f"payload is not canonicalizable: {exc}")

        # Step 2: message_type is in §6's closed domain list.
        message_type = message.get("message_type")
        if message_type not in kernel.DOMAINS:
            return Verdict(INADMISSIBLE, 2,
                           f"unknown message_type {message_type!r}; the domain list is closed (§6)")

        # Step 3: message_type equals the signed domain prefix. The kernel derives the prefix from
        # the envelope's own message_type and never from a parameter, so the binding holds by
        # construction; an adversary re-labelling a signed message therefore surfaces at step 5,
        # where the signature no longer verifies. This step asserts the binding rather than
        # pretending to re-derive it.
        if not kernel.signing_input(
                {**message, "body": message.get("body", {})}
        ).startswith(kernel.DOMAINS[message_type].encode("ascii")):
            return Verdict(INADMISSIBLE, 3, "message_type does not match the signed domain prefix")

        # Step 4: body validates against THAT message_type's schema; unknown fields reject.
        try:
            kernel.validate(message)
        except kernel.MessageError as exc:
            return Verdict(INADMISSIBLE, 4, str(exc))

        key_id = message["key_id"]

        # PREREQUISITE, not a step. Resolving the verification key is a dependency lookup: the
        # key comes from the registry and never from the message, so there is nothing to verify
        # *with* until it is fetched. Fetching it early is an implementation detail; it does not
        # decide anything, and no verdict is issued here.
        #
        # An earlier draft returned a step 6 verdict straight from this lookup, which really did
        # run the contract's steps out of order — Stage 6's decision was being issued before
        # Stage 5's. The lookup and the decision are now separate.
        key_material: Ed25519PublicKey | None = None
        resolution_failure = ""
        try:
            key_material = Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(self._registry.verification_key(key_id)))
        except RegistryError as exc:
            resolution_failure = str(exc)
        except (ValueError, TypeError) as exc:
            resolution_failure = f"registry holds an unusable public key: {exc}"

        # Step 5: signature verifies under key_id. With no key material the condition cannot be
        # met, so this step refuses — in the contract's order, the first step whose condition
        # fails decides, and that is this one, not a step 6 verdict issued from a lookup.
        if key_material is None:
            return Verdict(INADMISSIBLE, 5,
                           f"signature cannot verify under {key_id!r}: {resolution_failure}")
        try:
            message = kernel.verify(signed, key_material)
        except kernel.MessageError as exc:
            return Verdict(INADMISSIBLE, 5, str(exc))

        # Step 6: key_id resolves in the authenticated registry AT ITS CURRENT HEAD. Distinct from
        # step 5 and decided after it: resolving a key to check an old signature is not the same
        # as that key being present in the authoritative state now (I2's retention rule). A
        # registry that can still resolve key material while holding no accepted head — a state a
        # durable store can genuinely be in mid-recovery — fails here, fail-closed.
        if self._registry.head is None:
            return Verdict(INADMISSIBLE, 6,
                           "the registry holds no accepted head, so nothing resolves at a current "
                           "head; unverifiable authority is inadmissible (§12)")

        action = message["action"]
        project = self._project_of(message)

        # §5.1 answers three of the contract's steps together, so they are asked together and each
        # refusal is attributed to the step that owns it:
        #
        #   Step 7: key state permits this signature at its TCB acceptance epoch, NOT at signed_at
        #   Step 8: registry grants this key_id THIS message_type and action
        #   Step 9: registry grant covers this project scope
        try:
            granted = self._registry.authorize(key_id, message_type, action, project)
        except RegistryError as exc:
            text = str(exc)
            if "revoked" in text or "retired" in text:
                step = 7
            elif "project scope" in text or "must name a project" in text:
                step = 9
            else:
                step = 8
            return Verdict(INADMISSIBLE, step, text)
        del granted
        # Step 10: every head the body names is the CURRENT authoritative head (AM-18).
        for field, value in sorted(message["body"].items()):
            if not HEAD_FIELD.search(field):
                continue
            current = self._current_head(message_type, field)
            if value != (current if current is not None else ""):
                return Verdict(INADMISSIBLE, 10,
                               f"{field}={value!r} is not the current authoritative head "
                               f"{current!r}; a valid head is not the current head (AM-18)")

        # Step 11: sequence consistent for this identity; gaps reported, never ignored.
        refusal = self._ledger.observe(key_id, message["sequence"])
        if refusal is not None:
            return Verdict(INADMISSIBLE, 11, refusal)

        # Step 12: deployment_mode recorded, and not weaker than policy requires.
        mode = message["deployment_mode"]
        if MODE_STRENGTH[mode] < MODE_STRENGTH[self._required_mode]:
            return Verdict(INADMISSIBLE, 12,
                           f"deployment_mode {mode!r} is weaker than the required "
                           f"{self._required_mode!r} (§3)")

        return Verdict(ADMISSIBLE)
