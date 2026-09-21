#!/usr/bin/env python3
"""F1-I7 — Trusted Verification Controller (T1A §2, §7.5).

The last milestone, and the most dangerous boundary in practice: this is where untrusted project
code finally runs.

**The interface is `verify(request_id)` and nothing more.** A request names a run by id; it carries
no fingerprint, no identity and no verdict, because an API that accepts those is an API through
which the adversary supplies them. Everything else the controller resolves from trusted state
itself. The two facts that were still outside the pipeline after I6b —
`candidate_fingerprint` and `execution_identities` — are produced **here and only here**.

§7.5's sequence, in order:

    resolve the TCB-held Run Commitment            never from the workspace
    load the Gate Commitment bound to it
    resolve base_digest + patch_digest             else REFUSE
    materialize the MASTER into TCB storage
    derive candidate_fingerprint from the MASTER
    hand the worker an EPHEMERAL COPY
    collect bounded observations
    re-confirm the MASTER is unchanged             else ABORT, no attestation
    discard the worker copy
    re-derive verdict, construct payload, sign

**The controller never imports or executes project code.** It materializes content-addressed
objects, copies them, and launches a separate process that is not this one. A test asserts this
module never imports the worker: crossing that line would put project code in the process holding
the key, which is §2's second failure mode.

**The verdict is re-derived, never accepted.** The worker's output is parsed as bounded,
schema-constrained observations, and a `verdict` field in it is discarded. A controller that signs
what the worker claims is a signing oracle with extra steps.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

MAX_WORKER_OUTPUT = 64 * 1024
OBSERVATION_FIELDS = {"check_id", "exit_code", "stdout_bytes", "stderr_bytes", "output_head",
                      "timed_out", "failed_to_start"}
REQUIRED_OBSERVATION_FIELDS = {"check_id", "exit_code"}


class ControllerError(RuntimeError):
    """The verification is refused or aborted. No attestation is produced."""


class AbortedError(ControllerError):
    """The master changed under the verification. §7.5: ABORT, no attestation."""


def _digest_tree(root: Path) -> str:
    """A fingerprint of the materialized master: every path and every byte, in order."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


class VerificationController:
    """Holds the key, never runs project code, and decides the verdict itself."""

    def __init__(self, facts: Any, ingest: Any, signer: Any, objects: Any,
                 master_root: Path, identity: str,
                 worker: Path | None = None, python: str = sys.executable):
        self._facts = facts
        self._ingest = ingest
        self._signer = signer
        self._objects = objects
        self._master_root = Path(master_root)
        self._identity = identity
        self._worker = Path(worker) if worker else Path(__file__).with_name("f1_worker.py")
        self._python = python

    # -- the only entry point ---------------------------------------------------------------------

    def verify(self, request_id: str) -> dict[str, Any]:
        """§7.5. Takes a request id and nothing else.

        There is deliberately no parameter for a fingerprint, an actor id or a verdict: an
        interface that accepts them is the interface through which they are forged.
        """
        request = self._facts.record("verification_requests", request_id)
        if request is None:
            raise ControllerError(f"unknown verification request {request_id!r}")

        run_commitment = request["run_commitment"]
        run = self._facts.record("runs", run_commitment)
        if run is None:
            raise ControllerError("the run is not TCB-held; never resolved from the workspace")
        gate_commitment = run.get("gate_commitment")
        if gate_commitment is None:
            raise ControllerError("no Gate Commitment is bound to this run")

        binding = self._facts.record("candidate_bindings", run_commitment)
        if binding is None or not binding.get("base_digest") or not binding.get("patch_digest"):
            raise ControllerError("the candidate binding does not resolve; REFUSE (§7.5)")

        master = self._materialize(run_commitment, binding)
        try:
            # The fingerprint is DERIVED from the master the controller built, never taken from a
            # request, a workspace or a worker.
            candidate_fingerprint = _digest_tree(master)
            execution_identity = f"executor:{request_id}"

            observations = self._run_worker(master, self._checks(gate_commitment))

            if _digest_tree(master) != candidate_fingerprint:
                raise AbortedError(
                    "the master changed during verification; ABORT with no attestation (§7.5)")
        finally:
            shutil.rmtree(master, ignore_errors=True)

        verdict = self._derive_verdict(observations)
        self._record_run_facts(run_commitment, candidate_fingerprint, execution_identity)

        signed = self._signer.verify_attestation(
            project=request["project"], run_commitment=run_commitment,
            gate_commitment=gate_commitment, candidate_fingerprint=candidate_fingerprint,
            obligation_id=request["obligation_id"], verification_method="f1-worker",
            verdict=verdict,
            observation_digest="sha256:" + hashlib.sha256(
                json.dumps(observations, sort_keys=True).encode("utf-8")).hexdigest())
        # Straight into the ordinary authenticated pipeline: I7 gets no private door.
        return {"verdict": verdict, "candidate_fingerprint": candidate_fingerprint,
                "result": self._ingest.apply(signed)}

    # -- steps ------------------------------------------------------------------------------------

    def _materialize(self, run_commitment: str, binding: dict[str, Any]) -> Path:
        """Build the MASTER in TCB storage from content-addressed objects.

        Not in the project worktree: a master materialized there is not a master, it is the thing
        the adversary is still holding (§7.5, R3).
        """
        self._master_root.mkdir(parents=True, exist_ok=True)
        master = Path(tempfile.mkdtemp(prefix="master-", dir=self._master_root))
        for digest in (binding["base_digest"], binding["patch_digest"]):
            content = self._objects.get(digest)
            if content is None:
                shutil.rmtree(master, ignore_errors=True)
                raise ControllerError(f"content-addressed object {digest!r} does not resolve")
            for name, data in sorted(content.items()):
                target = master / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(data, encoding="utf-8")
        return master

    def _checks(self, gate_commitment: str) -> list[dict[str, Any]]:
        gate = self._facts.record("gate_plans", gate_commitment)
        if gate is None:
            raise ControllerError("the gate names no check plan")
        return list(gate.get("checks", ()))

    def _run_worker(self, master: Path, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Hand the worker an EPHEMERAL COPY and take back bounded observations."""
        copy = Path(tempfile.mkdtemp(prefix="worker-", dir=self._master_root))
        try:
            shutil.copytree(master, copy / "work")
            completed = subprocess.run(
                [self._python, str(self._worker)],
                input=json.dumps({"workdir": str(copy / "work"), "checks": checks}),
                capture_output=True, text=True, timeout=600)
            return self._parse(completed.stdout)
        except subprocess.TimeoutExpired as exc:
            raise ControllerError("the worker did not finish within its bound") from exc
        finally:
            # The worker may have written to or destroyed its copy; either way it goes.
            shutil.rmtree(copy, ignore_errors=True)

    def _parse(self, raw: str) -> list[dict[str, Any]]:
        """Worker output is hostile input (§2): size-bounded and schema-constrained, fail closed."""
        if len(raw) > MAX_WORKER_OUTPUT:
            raise ControllerError("worker output exceeds its bound")
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ControllerError(f"worker output is not parsable: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
            raise ControllerError("worker output is not an observation set")
        # Unknown TOP-LEVEL keys are rejected too, not just unknown fields inside an observation.
        # Mutation testing found the gap: a worker could emit {"observations": [...],
        # "verdict": "pass"} and the extra key was silently ignored. Harmless today, because
        # _derive_verdict never reads it -- and precisely the shape that becomes a hole the day
        # someone reads payload.get("verdict"). §6's rule is that unknown fields are REJECTED.
        extra = set(payload) - {"observations", "truncated"}
        if extra:
            raise ControllerError(f"worker output carries unknown top-level key(s) {sorted(extra)}")
        observations = []
        for entry in payload["observations"]:
            if not isinstance(entry, dict):
                raise ControllerError("an observation is not an object")
            unknown = set(entry) - OBSERVATION_FIELDS
            if unknown:
                raise ControllerError(f"worker output carries unknown field(s) {sorted(unknown)}")
            missing = REQUIRED_OBSERVATION_FIELDS - set(entry)
            if missing:
                raise ControllerError(f"observation is missing {sorted(missing)}")
            observations.append(entry)
        return observations

    @staticmethod
    def _derive_verdict(observations: list[dict[str, Any]]) -> str:
        """The controller's own conclusion. A verdict in the worker's output never reaches here."""
        if not observations:
            return "fail"
        for entry in observations:
            if entry.get("timed_out") or entry.get("failed_to_start"):
                return "fail"
            if entry.get("exit_code") != 0:
                return "fail"
        return "pass"

    def _record_run_facts(self, run_commitment: str, candidate_fingerprint: str,
                          execution_identity: str) -> None:
        """The two facts I6b left outside the pipeline, produced by the controller alone.

        §10 stage 2 refuses an attestation whose producer is an execution identity of the run, so
        recording the executor before signing is what makes that check able to fire at all.
        """
        if execution_identity == self._identity:
            raise ControllerError(
                "the execution identity equals the verification identity; the executor and the "
                "verifier are never the same principal (§4)")
        self._ingest.record_run_observation(
            run_commitment, candidate_fingerprint=candidate_fingerprint,
            execution_identity=execution_identity)
