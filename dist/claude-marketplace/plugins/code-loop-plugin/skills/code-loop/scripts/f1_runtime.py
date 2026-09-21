#!/usr/bin/env python3
"""F1 Integration — loading the provisioned trust runtime from a project on disk.

`f1_bootstrap.provision()` brings a trust root into existence. This module is the other half:
finding an *already* provisioned root and refusing, loudly, when there is none.

There is deliberately no "create it if it is missing" path here. §5 of T1A:

> The trust root is established out of band by an explicit provisioning ceremony recorded as a
> decision. It is never created implicitly on first use.

An adapter that provisions on first use hands the root to whoever runs the command first, which
on a shared checkout is the adversary. So every path below **fails closed**: no trust state, no
recorded ceremony, no key, or a key that is not the one the ceremony recorded — all raise
`NotProvisionedError` and nothing is created.

**Private key material is never stored in the project.** §6.1 leaves key storage to F1-T2 and does
not assume raw key files. Until T2 exists, the verification key is supplied out of band through
the environment, and that is recorded here as a KNOWN LIMIT rather than papered over: an env var
is a weaker custody story than a hardware-backed key, and the honest thing is to say so, not to
invent a key file and call it custody.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import f1_bootstrap as bootstrap
import f1_canonical as canonical
from f1_controller import VerificationController
from f1_state import AuthoritativeStore

TRUST_DIRNAME = "trust"
STATE_FILENAME = "state.json"
OBJECTS_DIRNAME = "objects"
MASTER_DIRNAME = "tcb"

#: Out-of-band supply of the verification signing key, as a 32-byte Ed25519 seed in hex.
VERIFICATION_KEY_ENV = "NOGAP_F1_VERIFICATION_KEY"


class NotProvisionedError(RuntimeError):
    """No usable trust runtime. Nothing is created in response; the caller stops."""


class ObjectError(RuntimeError):
    """A content-addressed object does not match the digest it is filed under."""


def trust_dir(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / ".code-loop" / TRUST_DIRNAME


def object_digest(content: dict[str, str]) -> str:
    """The content address of an object: sha256 over its canonical encoding."""
    return "sha256:" + hashlib.sha256(canonical.canonicalize(content)).hexdigest()


class ObjectStore:
    """Read-only, content-addressed, and self-checking.

    Read-only on purpose: the trusted verification path has no reason to write objects, and a
    store the verifier can write is a store the verifier can be made to write. Self-checking
    because the file lives in the project directory, which is exactly the surface §2 calls
    hostile: an object whose bytes no longer hash to its own name is refused rather than used.
    """

    def __init__(self, root: str | Path):
        self._root = Path(root)

    def _path(self, digest: str) -> Path:
        # The digest is used as a filename, so it is validated as a digest first. Without this a
        # binding carrying "../../etc/passwd" would be a path traversal into the trusted loader.
        algorithm, _, hexdigest = digest.partition(":")
        if algorithm != "sha256" or len(hexdigest) != 64 or not all(
                c in "0123456789abcdef" for c in hexdigest):
            raise ObjectError(f"not a well-formed object digest: {digest!r}")
        return self._root / f"{hexdigest}.json"

    def get(self, digest: str) -> dict[str, str] | None:
        path = self._path(digest)
        if not path.is_file():
            return None
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            # A trust-boundary read fails as a refusal, not as a traceback: an unhandled decode
            # error reaches the caller as a crash, and a crash is not a decision.
            raise ObjectError(f"object {digest!r} is not readable: {exc}") from exc
        if not isinstance(content, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in content.items()):
            raise ObjectError(f"object {digest!r} is not a name -> text mapping")
        for name in content:
            # The names become paths under the materialized master. An absolute or climbing name
            # writes outside it, so it is refused here rather than materialized and regretted.
            if not name or name.startswith("/") or Path(name).is_absolute() or ".." in Path(name).parts:
                raise ObjectError(f"object {digest!r} carries an unsafe member name {name!r}")
        actual = object_digest(content)
        if actual != digest:
            raise ObjectError(
                f"object filed under {digest!r} hashes to {actual!r}; refusing to use it")
        return content

    def put(self, content: dict[str, str]) -> str:
        """Used by provisioning and tests to file an object under its own address.

        Not reachable from the verification path: the controller receives this store through an
        interface that only ever calls `get`.
        """
        digest = object_digest(content)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path(digest).write_text(
            json.dumps(content, sort_keys=True), encoding="utf-8")
        return digest


class _ReadOnlyObjects:
    """The view the controller gets: `get` and nothing else."""

    def __init__(self, store: ObjectStore):
        self._store = store

    def get(self, digest: str) -> dict[str, str] | None:
        return self._store.get(digest)


def open_store(project_root: str | Path) -> AuthoritativeStore:
    """Open the authoritative state of an already provisioned project, or refuse."""
    path = trust_dir(project_root) / STATE_FILENAME
    if not path.is_file():
        raise NotProvisionedError(
            f"no trust runtime at {path}: the F1 provisioning ceremony has not been performed. "
            "It is never performed implicitly.")
    store = AuthoritativeStore(path)
    if not bootstrap.already_provisioned(store):
        raise NotProvisionedError(
            f"trust state at {path} records no trust root; refusing to proceed")
    return store


def _ceremony(store: AuthoritativeStore) -> tuple[str, dict[str, Any]]:
    provisioning = store.read().get("tcb", {}).get("provisioning", {})
    if len(provisioning) != 1:
        raise NotProvisionedError(
            f"expected exactly one provisioned project, found {len(provisioning)}")
    project_id, record = next(iter(provisioning.items()))
    for field in ("root_public_key", "verification_key_id", "verification_public_key"):
        if not record.get(field):
            raise NotProvisionedError(
                f"the recorded ceremony for {project_id!r} carries no {field}")
    return project_id, record


def load_verification_key(record: dict[str, Any]) -> Any:
    """Load the out-of-band key and check it is the one the ceremony recorded.

    The registry would reject a foreign key at Stage 1 anyway. This check is here because failing
    at the boundary with "that is not the provisioned key" is a different message from failing
    four layers in with "signature does not verify", and only one of them tells an operator what
    actually happened.
    """
    supplied = os.environ.get(VERIFICATION_KEY_ENV, "")
    if not supplied:
        raise NotProvisionedError(
            f"the verification signing key is not available: set {VERIFICATION_KEY_ENV} to the "
            "provisioned key seed (hex). No key is generated in its absence.")
    try:
        seed = bytes.fromhex(supplied.strip())
    except ValueError as exc:
        raise NotProvisionedError(f"{VERIFICATION_KEY_ENV} is not hex: {exc}") from exc
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(seed)
    except Exception as exc:  # noqa: BLE001 - any rejection is the same refusal
        raise NotProvisionedError(f"{VERIFICATION_KEY_ENV} is not an Ed25519 seed: {exc}") from exc
    if private_key.public_key().public_bytes_raw().hex() != record["verification_public_key"]:
        raise NotProvisionedError(
            f"the key in {VERIFICATION_KEY_ENV} is not the key this project was provisioned with")
    return private_key


def load_pipeline(project_root: str | Path) -> bootstrap.Pipeline:
    """Assemble the trusted pipeline for an already provisioned project, or refuse."""
    store = open_store(project_root)
    project_id, record = _ceremony(store)
    private_key = load_verification_key(record)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    root_public_key = Ed25519PublicKey.from_public_bytes(
        bytes.fromhex(record["root_public_key"]))
    return bootstrap.Pipeline(
        store, root_public_key, project_id,
        signing_key_id=record["verification_key_id"], signing_private_key=private_key,
        signing_identity=record.get("verification_identity", record["verification_key_id"]))


def load_controller(project_root: str | Path) -> VerificationController:
    """The trusted verification controller, ready to take a request id and nothing else."""
    root = trust_dir(project_root)
    pipeline = load_pipeline(project_root)
    _, record = _ceremony(pipeline.store)
    return VerificationController(
        facts=pipeline.facts, ingest=pipeline.ingest, signer=pipeline.signer,
        objects=_ReadOnlyObjects(ObjectStore(root / OBJECTS_DIRNAME)),
        master_root=root / MASTER_DIRNAME,
        identity=record.get("verification_identity") or record["verification_key_id"])
