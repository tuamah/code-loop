"""Closure item 1: `nogap verify` on the trusted controller, end to end from a project on disk.

These tests start from an empty directory, run the provisioning ceremony into it, and then drive
the real CLI entry point. The four required properties:

  1. an unprovisioned project refuses, and provisions nothing;
  2. a provisioned valid request goes controller -> worker -> Stage 1 -> Stage 2 -> ingest;
  3. the old `mallory` spoofing path is no longer authoritative;
  4. a restart preserves registry, heads and sequences, and verify continues without reprovision.

**What is seeded, honestly**: the Run Commitment, the Gate Commitment and the verification request
are written into trusted state directly here. In the finished system those arrive as ingested RUN
and GATE messages from `nogap run` and `nogap freeze`, which is closure item 3's work, not this
one's. What these tests actually prove is the boundary this item is about: that `cmd_verify` reads
its inputs from trusted state and the controller, and from nowhere else.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_bootstrap as boot                                                  # noqa: E402
import f1_kernel as k                                                        # noqa: E402
import f1_runtime as rt                                                      # noqa: E402
import f1_state as st                                                        # noqa: E402
import nogap                                                                 # noqa: E402

D = "sha256:" + "aa" * 32
PROJECT = "proj-1"


def verify_args(path: str, request_id: str = "req-1") -> argparse.Namespace:
    return argparse.Namespace(path=path, request_id=request_id)


class OnDisk(unittest.TestCase):
    """A provisioned project in a real directory, driven through the real CLI function."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.project = Path(self.dir.name)
        self.root_sk, self.sk = k.generate_key(), k.generate_key()
        self.seed_hex = self.sk.private_bytes_raw().hex()
        patcher = mock.patch.dict(
            os.environ, {rt.VERIFICATION_KEY_ENV: self.seed_hex})
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- helpers --------------------------------------------------------------------------------

    def provision(self) -> None:
        path = rt.trust_dir(self.project) / rt.STATE_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        boot.provision(
            st.AuthoritativeStore(path), project_id=PROJECT,
            repository_identity="repo-1", root_private_key=self.root_sk,
            verification_private_key=self.sk, verification_key_id="key-1",
            verification_identity="verifier-1", operator="operator-1",
            initial_base_digest=D, policy_baseline=D, gate_baseline=D,
            obligation_policy_baseline=D)

    def seed_request(self, checks=None, base=None, patch=None) -> None:
        objects = rt.ObjectStore(rt.trust_dir(self.project) / rt.OBJECTS_DIRNAME)
        base_digest = objects.put(base or {"app.py": "print('hello')\n"})
        patch_digest = objects.put(patch or {"fix.txt": "a fix\n"})
        run_ref, gate_ref = "sha256:" + "11" * 32, "sha256:" + "22" * 32
        store = rt.open_store(self.project)
        state = store.read()
        tcb = state["tcb"]
        tcb["runs"] = {run_ref: {"gate_commitment": gate_ref, "candidate_fingerprint": None,
                                 "execution_identities": []}}
        tcb["run_commitments"] = {run_ref: {}}
        tcb["candidate_bindings"] = {run_ref: {"base_digest": base_digest,
                                               "patch_digest": patch_digest}}
        tcb["gate_plans"] = {gate_ref: {"checks": checks if checks is not None else [
            {"check_id": "c1", "command": [sys.executable, "-c", "raise SystemExit(0)"]}]}}
        tcb["verification_requests"] = {
            "req-1": {"run_commitment": run_ref, "project": PROJECT, "obligation_id": "obl-1"}}
        with store._exclusive():
            store._write(state)
        self.run_ref, self.gate_ref = run_ref, gate_ref

    def trust_state(self) -> dict:
        return json.loads(
            (rt.trust_dir(self.project) / rt.STATE_FILENAME).read_text(encoding="utf-8"))


# -- (1) unprovisioned --------------------------------------------------------------------------

class UnprovisionedFailsClosed(OnDisk):
    def test_verify_refuses_when_no_trust_runtime_exists(self):
        with self.assertRaises(SystemExit) as caught:
            nogap.cmd_verify(verify_args(str(self.project)))
        self.assertIn("provisioning ceremony has not been performed", str(caught.exception))

    def test_refusing_provisions_nothing(self):
        """Fail closed means fail closed: no root is brought into existence by being asked."""
        with self.assertRaises(SystemExit):
            nogap.cmd_verify(verify_args(str(self.project)))
        self.assertFalse((rt.trust_dir(self.project) / rt.STATE_FILENAME).exists())
        self.assertFalse(rt.trust_dir(self.project).exists())

    def test_verify_refuses_when_state_exists_but_records_no_root(self):
        """An empty state file is not a trust runtime, however much it looks like one."""
        path = rt.trust_dir(self.project) / rt.STATE_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            nogap.cmd_verify(verify_args(str(self.project)))
        self.assertIn("no trust root", str(caught.exception))

    def test_verify_refuses_when_the_signing_key_is_absent(self):
        self.provision()
        self.seed_request()
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as caught:
                nogap.cmd_verify(verify_args(str(self.project)))
        self.assertIn("No key is generated in its absence", str(caught.exception))

    def test_verify_refuses_a_key_that_is_not_the_provisioned_one(self):
        """The adversary supplying their own key is the whole point of checking."""
        self.provision()
        self.seed_request()
        other = k.generate_key().private_bytes_raw().hex()
        with mock.patch.dict(os.environ, {rt.VERIFICATION_KEY_ENV: other}):
            with self.assertRaises(SystemExit) as caught:
                nogap.cmd_verify(verify_args(str(self.project)))
        self.assertIn("not the key this project was provisioned with", str(caught.exception))


# -- (2) the trusted path runs ------------------------------------------------------------------

class ProvisionedRequestGoesThroughTheTrustBoundary(OnDisk):
    def setUp(self):
        super().setUp()
        self.provision()
        self.seed_request()

    def test_a_valid_request_is_verified_and_ingested(self):
        nogap.cmd_verify(verify_args(str(self.project)))
        run = self.trust_state()["tcb"]["runs"][self.run_ref]
        # Stage 2 recorded facts the request never carried: the fingerprint was DERIVED.
        self.assertTrue(run["candidate_fingerprint"].startswith("sha256:"))
        self.assertEqual(run["execution_identities"], ["executor:req-1"])

    def test_a_failing_check_produces_a_fail_verdict_and_a_nonzero_exit(self):
        """A check that can fail, failing."""
        self.seed_request(checks=[{"check_id": "c1",
                                   "command": [sys.executable, "-c", "raise SystemExit(3)"]}])
        with self.assertRaises(SystemExit) as caught:
            nogap.cmd_verify(verify_args(str(self.project)))
        self.assertEqual(caught.exception.code, 1)

    def test_an_unknown_request_is_refused_not_invented(self):
        with self.assertRaises(SystemExit) as caught:
            nogap.cmd_verify(verify_args(str(self.project), request_id="req-nope"))
        self.assertIn("unknown verification request", str(caught.exception))

    def test_the_verdict_reaches_state_only_through_ingest(self):
        """No private door: the verdict lands as Stage 2 facts, not as a write from the adapter."""
        self.assertEqual(self.trust_state()["tcb"].get("verdicts", {}), {})
        nogap.cmd_verify(verify_args(str(self.project)))
        tcb = self.trust_state()["tcb"]
        verdicts = tcb["verdicts"]
        self.assertEqual(len(verdicts), 1)
        recorded = next(iter(verdicts.values()))
        self.assertEqual(recorded["verdict"], "pass")
        # Keyed by the VERIFY commitment, so the fact is anchored to the signed message that
        # carried it; a fact with no commitment behind it could not have come through ingest.
        self.assertTrue(next(iter(verdicts)).startswith("sha256:"))
        self.assertIn("obl-1|" + recorded["candidate_fingerprint"], tcb["current_verdicts"])

    def test_the_adapter_never_reads_the_untrusted_runtime_directory(self):
        """`.code-loop/runtime/` is the spoofable surface; the trusted path must not touch it."""
        runtime = self.project / ".code-loop" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        opened: list[str] = []
        real_open = Path.open

        def watching_open(self_path, *a, **kw):
            opened.append(str(self_path))
            return real_open(self_path, *a, **kw)

        with mock.patch.object(Path, "open", watching_open):
            nogap.cmd_verify(verify_args(str(self.project)))
        self.assertEqual([p for p in opened if str(runtime) in p], [])


class TheAdapterAcceptsNoAuthority(unittest.TestCase):
    def test_cmd_verify_takes_only_a_request_id_and_a_path(self):
        """The forgery surface, closed at the CLI as well as at the controller."""
        parser = nogap.build_parser()
        action = next(a for a in parser._subparsers._group_actions
                      if isinstance(a, argparse._SubParsersAction))
        verify = action.choices["verify"]
        options = {a.dest for a in verify._actions} - {"help"}
        self.assertEqual(options, {"request_id", "path"})
        for forgeable in ("actor", "actor_id", "authority", "candidate_fingerprint",
                          "verdict", "gate", "gate_hash", "dispatch"):
            self.assertNotIn(forgeable, options)


# -- (3) the old spoofing path -------------------------------------------------------------------

class TheOldSpoofingPathIsNoLongerAuthoritative(OnDisk):
    """The original exploit, re-run: mallory fabricates verification evidence on disk.

    Required result: the forged file does not enter the authoritative path at all - not rejected
    late, not weighed and discounted, but never consulted.
    """

    def setUp(self):
        super().setUp()
        self.provision()
        self.seed_request()

    def forge(self) -> Path:
        evidence = self.project / ".code-loop" / "runtime" / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        forged = evidence / "ev-mallory.json"
        forged.write_text(json.dumps({
            "id": "ev-mallory", "kind": "test", "status": "passed",
            "provenance": {"authority": "verification", "actor_id": "mallory",
                           "role": "verifier", "dispatch_id": "dispatch-0001",
                           "gate_hash": "whatever", "candidate_fingerprint": D,
                           "verdict": "pass"},
        }), encoding="utf-8")
        return forged

    def test_forged_verification_evidence_changes_nothing_about_the_verdict(self):
        forged = self.forge()
        nogap.cmd_verify(verify_args(str(self.project)))
        run = self.trust_state()["tcb"]["runs"][self.run_ref]
        # The fingerprint is the one the controller derived from the master it built, not the one
        # the forged file asserts.
        self.assertNotEqual(run["candidate_fingerprint"], D)
        self.assertEqual(run["execution_identities"], ["executor:req-1"])
        self.assertTrue(forged.is_file())  # still there, and still irrelevant

    def test_mallory_cannot_make_a_failing_candidate_pass(self):
        """The forged 'passed' evidence does not rescue a candidate whose check fails."""
        self.seed_request(checks=[{"check_id": "c1",
                                   "command": [sys.executable, "-c", "raise SystemExit(1)"]}])
        self.forge()
        with self.assertRaises(SystemExit) as caught:
            nogap.cmd_verify(verify_args(str(self.project)))
        self.assertEqual(caught.exception.code, 1)

    def test_forging_trusted_state_itself_is_caught_by_the_object_digest(self):
        """Mallory's better attempt: swap the content the master is built from."""
        objects = rt.trust_dir(self.project) / rt.OBJECTS_DIRNAME
        target = sorted(objects.glob("*.json"))[0]
        target.write_text(json.dumps({"app.py": "backdoor\n"}), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            nogap.cmd_verify(verify_args(str(self.project)))
        self.assertIn("refusing to use it", str(caught.exception))

    def test_an_unreadable_object_is_refused_not_crashed_on(self):
        """A trust-boundary read fails as a refusal; a traceback is not a decision."""
        objects = rt.trust_dir(self.project) / rt.OBJECTS_DIRNAME
        sorted(objects.glob("*.json"))[0].write_text("{not json", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            nogap.cmd_verify(verify_args(str(self.project)))
        self.assertIn("is not readable", str(caught.exception))

    def test_an_object_member_cannot_write_outside_the_master(self):
        store = rt.ObjectStore(rt.trust_dir(self.project) / rt.OBJECTS_DIRNAME)
        for hostile in ("../escape.txt", "/etc/passwd", "a/../../b", ""):
            digest = store.put({hostile: "x"})
            with self.assertRaises(rt.ObjectError):
                store.get(digest)

    def test_an_object_digest_cannot_walk_out_of_the_object_store(self):
        store = rt.ObjectStore(rt.trust_dir(self.project) / rt.OBJECTS_DIRNAME)
        for hostile in ("../../etc/passwd", "sha256:../x", "sha1:" + "aa" * 20, "nonsense"):
            with self.assertRaises(rt.ObjectError):
                store.get(hostile)


# -- (4) restart ----------------------------------------------------------------------------------

class RestartPreservesTheTrustRuntime(OnDisk):
    def setUp(self):
        super().setUp()
        self.provision()
        self.seed_request()

    def test_verify_continues_across_a_restart_without_reprovisioning(self):
        """Nothing is held in memory: a second process-equivalent load picks up where it left off."""
        nogap.cmd_verify(verify_args(str(self.project)))
        first = self.trust_state()

        # A "restart": every object dropped, everything reloaded from disk alone.
        self.seed_request()
        nogap.cmd_verify(verify_args(str(self.project)))
        second = self.trust_state()

        self.assertEqual(first["tcb"]["trust_root_key_id"],
                         second["tcb"]["trust_root_key_id"])
        self.assertEqual(first["tcb"]["provisioning"], second["tcb"]["provisioning"])
        self.assertEqual(first["heads"]["registry"], second["heads"]["registry"])
        # A second distinct verdict commitment, so the second run really was a second run.
        self.assertEqual(len(first["tcb"]["verdicts"]), 1)
        self.assertEqual(len(second["tcb"]["verdicts"]), 2)
        # Sequences are monotonic across the restart - a reset would let a replay in.
        self.assertGreater(second["sequences"]["key-1"], first["sequences"]["key-1"])

    def test_reprovisioning_an_already_provisioned_project_is_refused(self):
        with self.assertRaises(boot.ProvisioningError):
            self.provision()


if __name__ == "__main__":
    unittest.main()
