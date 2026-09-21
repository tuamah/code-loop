#!/usr/bin/env python3
"""F1 Integration — the provisioning ceremony (T1A §5, §7.0.1).

Every F1 test so far generated its own keys inline. Nothing in production code could bring a trust
root into existence, so the pipeline was complete and unreachable. This is the missing step, and
§5 is unusually specific about what it may not be:

> The trust root is established **out of band** by an explicit provisioning ceremony recorded as a
> decision. It is never created implicitly on first use — an implicitly created root is a root the
> adversary can create first.

So `provision()` is explicit, records what it did, and **refuses to run twice**. There is no
lazy "create if missing" path anywhere, because that is the same thing spelled differently.

**This module never generates, reads or writes a private key.** Key material is supplied by the
caller, used to sign, and never persisted — private-key storage and OS isolation are F1-T2's, and
§6.1 says raw key files are not assumed. What reaches the store is public material and
commitments.
"""

from __future__ import annotations

from typing import Any

import f1_commitments as commitments
import f1_ingest as ingest_module
import f1_kernel as kernel
import f1_registry as registry_module
import f1_stage1 as stage1_module
import f1_stage2 as stage2_module
from f1_durable import DurableRegistryStore, DurableSequenceLedger, DurableSequenceSource
from f1_state import AuthoritativeStore

ROOT_KEY_ID = "registry-root"


class ProvisioningError(RuntimeError):
    """The ceremony is refused. A trust root is never brought into existence by accident."""


class Pipeline:
    """The assembled trusted pipeline: registry, facts, Stage 1, Stage 2, ingest, signer.

    Assembled in one place on purpose. Every caller that wired this up by hand got the head source
    subtly wrong at least once — a harness that lies about the current head cannot test a rule
    about the current head, and a runtime that does it cannot enforce one.
    """

    def __init__(self, store: AuthoritativeStore, root_public_key: Any, project_id: str,
                 signing_key_id: str | None = None, signing_private_key: Any = None,
                 signing_identity: str = "", required_mode: str = "B"):
        self.store = store
        self.project_id = project_id
        self.registry = registry_module.AuthorityRegistry(
            root_public_key, store=DurableRegistryStore(store))
        self.facts = stage2_module.TrustedFacts(store)
        self.sequences = DurableSequenceSource(store)
        self.stage1 = stage1_module.Stage1(
            registry=self.registry, current_head=self._current_head,
            project_of=lambda message: project_id, required_mode=required_mode,
            ledger=DurableSequenceLedger(store))
        self.stage2 = stage2_module.Stage2(self.facts)
        self.ingest = ingest_module.Ingest(store, self.stage1, self.stage2)
        self.signer = (
            commitments.CommitmentSigner(self.registry, signing_key_id, signing_private_key,
                                         signing_identity or signing_key_id,
                                         sequences=self.sequences)
            if signing_key_id and signing_private_key is not None else None)

    def _current_head(self, message_type: str, field: str) -> str:
        name = (ingest_module.HEADED.get(message_type, message_type.lower())
                if field == "previous_commitment" else field[: -len("_head")])
        current = self.store.head(name)
        return current[0] if current else ""


def already_provisioned(store: AuthoritativeStore) -> bool:
    return bool(store.read().get("tcb", {}).get("trust_root_key_id"))


def provision(store: AuthoritativeStore, *, project_id: str, repository_identity: str,
              root_private_key: Any, verification_private_key: Any, verification_key_id: str,
              verification_identity: str, operator: str,
              initial_base_digest: str, policy_baseline: str, gate_baseline: str,
              obligation_policy_baseline: str) -> dict[str, Any]:
    """Establish the trust root and the project, once.

    Returns the public record of the ceremony. Raises if a root already exists: re-provisioning
    would replace the authority every existing commitment was made under, which is not a bootstrap
    but a takeover.
    """
    if already_provisioned(store):
        raise ProvisioningError(
            "a trust root already exists; re-provisioning would replace the authority every "
            "existing commitment was made under (§5)")

    root_public = root_private_key.public_key().public_bytes_raw().hex()
    verification_public = verification_private_key.public_key().public_bytes_raw().hex()

    # The ceremony is recorded BEFORE the genesis message, because §10 stage 2 refuses a PROJECT
    # whose repository_identity does not bind to a recorded ceremony. The record is the
    # out-of-band fact; the message is the authenticated claim about it.
    state = store.read()
    facts = state.setdefault("tcb", {})
    facts["trust_root_key_id"] = ROOT_KEY_ID
    facts.setdefault("provisioning", {})[project_id] = {
        "repository_identity": repository_identity, "provisioned_by": operator,
        "root_public_key": root_public,
        # Recorded so a later process can find the trust root WITHOUT being told where it is by
        # the caller: a loader that takes the root key from its invoker verifies against whatever
        # key the invoker chose.
        "verification_key_id": verification_key_id,
        "verification_public_key": verification_public,
        "verification_identity": verification_identity}
    facts.setdefault("maps", {})[policy_baseline] = {"kind": "policy_baseline"}
    facts.setdefault("base_commitments", {})[initial_base_digest] = {"kind": "initial_base"}
    with store._exclusive():
        store._write(state)

    grant = {
        "key_id": verification_key_id, "public_key": verification_public,
        "identity": verification_identity, "authority_class": "verification",
        "allowed_message_types": sorted(kernel.DOMAINS),
        "allowed_actions": {t: sorted(kernel.ACTIONS[t]) for t in kernel.DOMAINS},
        "allowed_projects": [project_id],
    }
    registry = registry_module.AuthorityRegistry(
        root_private_key.public_key(), store=DurableRegistryStore(store))
    sequences = DurableSequenceSource(store)
    root_signer = commitments.CommitmentSigner(
        registry, ROOT_KEY_ID, root_private_key, operator, sequences=sequences)

    # The root's own REGISTRY commitment is not run through the grant check: at this instant the
    # registry is empty, so there is nobody to grant anything. That is what "out of band" means,
    # and it is the one message in F1 whose authority is the ceremony itself rather than a grant.
    message = kernel.message(
        "REGISTRY", "add_key", key_id=ROOT_KEY_ID, producer_identity=operator,
        sequence=sequences.allocate(ROOT_KEY_ID), signed_at="ceremony",
        deployment_mode="B",
        body={"epoch": 1, "previous_commitment": "",
              "key_grants_digest": registry_module.digest([grant])})
    registry.apply(kernel.sign(message, root_private_key), [grant])

    # The PROJECT genesis is an ORDINARY message: it goes through Stage 1, Stage 2 and the
    # transactional apply like everything else. The ceremony supplies the out-of-band facts it
    # will be checked against; it does not get to install itself as a fact directly.
    pipeline = Pipeline(store, root_private_key.public_key(), project_id,
                        signing_key_id=verification_key_id,
                        signing_private_key=verification_private_key,
                        signing_identity=verification_identity)
    genesis = pipeline.signer.project_genesis(
        project_id=project_id, repository_identity=repository_identity,
        initial_base_digest=initial_base_digest, policy_baseline=policy_baseline,
        gate_baseline=gate_baseline,
        obligation_policy_baseline=obligation_policy_baseline,
        provisioned_by=operator, provisioning_sequence=0)
    verdict = pipeline.ingest.apply(genesis)
    if not verdict.admissible:
        raise ProvisioningError(
            f"the genesis message was not admitted: {verdict.reason}")

    return {"project_id": project_id, "root_key_id": ROOT_KEY_ID,
            "root_public_key": root_public,
            "verification_key_id": verification_key_id,
            "verification_public_key": verification_public,
            "registry_head": registry.head, "genesis": genesis,
            "project_commitment": commitments.commitment_of(genesis)}
