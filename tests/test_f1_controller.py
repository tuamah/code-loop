"""F1-I7 closure tests: Trusted Controller / Worker.

This is where untrusted project code finally runs, so the isolation must be demonstrated rather
than asserted: the worker tests launch the real worker in a real subprocess against a real
ephemeral copy, and check what it can and cannot reach.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_commitments as cm                                                  # noqa: E402
import f1_controller as ctl                                                  # noqa: E402
import f1_durable as dur                                                     # noqa: E402
import f1_ingest as ing                                                      # noqa: E402
import f1_kernel as k                                                        # noqa: E402
import f1_registry as r                                                      # noqa: E402
import f1_stage1 as s1                                                       # noqa: E402
import f1_stage2 as s2                                                       # noqa: E402
import f1_state as st                                                        # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
WORKER = SCRIPTS / "f1_worker.py"


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.store = st.AuthoritativeStore(self.root / "state.json")
        self.root_sk, self.sk = k.generate_key(), k.generate_key()
        self.registry = r.AuthorityRegistry(
            self.root_sk.public_key(), store=dur.DurableRegistryStore(self.store))
        self.seq = 0
        self.grant()
        self.facts = s2.TrustedFacts(self.store)
        self.stage1 = s1.Stage1(registry=self.registry, current_head=self.current_head,
                                project_of=lambda m: "proj-1", required_mode="B",
                                ledger=dur.DurableSequenceLedger(self.store))
        self.ingest = ing.Ingest(self.store, self.stage1, s2.Stage2(self.facts))
        self.signer = cm.CommitmentSigner(self.registry, "key-1", self.sk, "verifier-1",
                                          sequences=dur.DurableSequenceSource(self.store))
        self.objects = {}
        self.seed()
        self.controller = ctl.VerificationController(
            facts=self.facts, ingest=self.ingest, signer=self.signer, objects=self.objects,
            master_root=self.root / "tcb", identity="verifier-1")

    def current_head(self, message_type, field):
        name = (ing.HEADED.get(message_type, message_type.lower())
                if field == "previous_commitment" else field[:-len("_head")])
        current = self.store.head(name)
        return current[0] if current else ""

    def grant(self):
        entry = {"key_id": "key-1", "public_key": self.sk.public_key().public_bytes_raw().hex(),
                 "identity": "verifier-1", "authority_class": "verification",
                 "allowed_message_types": sorted(k.DOMAINS),
                 "allowed_actions": {t: sorted(k.ACTIONS[t]) for t in k.DOMAINS},
                 "allowed_projects": [r.WILDCARD]}
        self.seq += 1
        message = k.message("REGISTRY", "add_key", key_id="registry-root",
                            producer_identity="root", sequence=self.seq, signed_at="t",
                            deployment_mode="B",
                            body={"epoch": self.registry.epoch + 1,
                                  "previous_commitment": self.registry.head or "",
                                  "key_grants_digest": r.digest([entry])})
        self.registry.apply(k.sign(message, self.root_sk), [entry])

    def seed(self, checks=None, base=None, patch=None):
        self.objects["sha256:base"] = base or {"app.py": "print('hello')\n"}
        self.objects["sha256:patch"] = patch or {"fix.txt": "a fix\n"}
        run_ref = "sha256:" + "11" * 32
        gate_ref = "sha256:" + "22" * 32
        state = self.store.read()
        state["tcb"] = {
            "runs": {run_ref: {"gate_commitment": gate_ref, "candidate_fingerprint": None,
                               "execution_identities": []}},
            "run_commitments": {run_ref: {}},
            "candidate_bindings": {run_ref: {"base_digest": "sha256:base",
                                             "patch_digest": "sha256:patch"}},
            "gate_plans": {gate_ref: {"checks": checks if checks is not None else [
                {"check_id": "c1", "command": [sys.executable, "-c", "raise SystemExit(0)"]}]}},
            "verification_requests": {"req-1": {"run_commitment": run_ref, "project": "proj-1",
                                                "obligation_id": "obl-1"}},
            "trust_root_key_id": "registry-root",
        }
        with self.store._exclusive():
            self.store._write(state)
        self.run_ref, self.gate_ref = run_ref, gate_ref


class InterfaceTests(Pipeline):
    def test_verify_takes_a_request_id_and_nothing_else(self):
        """No parameter for a fingerprint, an identity or a verdict — the forgery surface."""
        import inspect
        params = list(inspect.signature(ctl.VerificationController.verify).parameters)
        self.assertEqual(params, ["self", "request_id"])
        for forgeable in ("candidate_fingerprint", "actor_id", "identity", "verdict"):
            self.assertNotIn(forgeable, params)

    def test_a_caller_cannot_supply_a_fingerprint_or_identity_anywhere(self):
        with self.assertRaises(TypeError):
            self.controller.verify("req-1", candidate_fingerprint="sha256:" + "ff" * 32)
        with self.assertRaises(TypeError):
            self.controller.verify("req-1", verdict="pass")

    def test_an_unknown_request_is_refused(self):
        with self.assertRaises(ctl.ControllerError):
            self.controller.verify("req-nope")

    def test_the_controller_never_imports_project_code_or_the_worker(self):
        """Project code in the process holding the key is §2's second failure mode."""
        import ast
        source = (SCRIPTS / "f1_controller.py").read_text()
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("f1_worker", imported,
                         "the controller imports the worker; the boundary is a process, not a "
                         "class")
        for runner in ("importlib", "runpy", "exec", "eval"):
            self.assertNotIn(runner, imported)


class WorkerCapabilityTests(Pipeline):
    """Mode B, demonstrated cross-process rather than by class separation."""

    def worker_result(self, snippet: str) -> dict:
        """Run the REAL worker, with a check that attempts the forbidden thing."""
        work = self.root / "probe"
        work.mkdir(exist_ok=True)
        plan = {"workdir": str(work),
                "checks": [{"check_id": "probe", "command": [sys.executable, "-c", snippet]}]}
        completed = subprocess.run([sys.executable, str(WORKER)], input=json.dumps(plan),
                                   capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)["observations"][0]

    def test_the_worker_holds_no_key_and_cannot_sign(self):
        source = WORKER.read_text()
        for forbidden in ("Ed25519", "private_key", "sign(", "f1_kernel", "generate_key"):
            self.assertNotIn(forbidden, source,
                             f"the worker references {forbidden!r}; it holds no authority")

    def test_the_worker_module_cannot_write_trusted_state(self):
        source = WORKER.read_text()
        for forbidden in ("f1_state", "f1_registry", "f1_ingest", "AuthoritativeStore"):
            self.assertNotIn(forbidden, source)

    def test_the_worker_is_handed_no_key_material(self):
        """The real property: nothing the worker receives contains a key.

        An earlier version of this test asserted that a string did not appear in a state file,
        which proved nothing about what the worker can reach. What matters is the interface: the
        plan the controller writes to the worker's stdin, and the argv it is launched with.
        """
        captured = {}
        real_run = ctl.subprocess.run

        def capture(cmd, **kwargs):
            captured["argv"] = cmd
            captured["stdin"] = kwargs.get("input", "")
            return real_run(cmd, **kwargs)

        ctl.subprocess.run = capture
        try:
            self.controller.verify("req-1")
        finally:
            ctl.subprocess.run = real_run

        private_hex = self.sk.private_bytes_raw().hex()
        public_hex = self.sk.public_key().public_bytes_raw().hex()
        blob = json.dumps(captured)
        self.assertNotIn(private_hex, blob, "the private key reached the worker")
        self.assertNotIn(public_hex, blob)
        self.assertEqual(set(json.loads(captured["stdin"])), {"workdir", "checks"},
                         "the worker's plan carries more than a workdir and a check list")

    def test_a_check_cannot_reach_the_master_through_its_copy(self):
        """The worker's cwd is the ephemeral copy; the master is elsewhere on disk."""
        self.seed(checks=[{"check_id": "c1", "command": [
            sys.executable, "-c",
            "import os,sys; sys.exit(0 if 'worker-' in os.getcwd() else 1)"]}])
        self.assertEqual(self.controller.verify("req-1")["verdict"], "pass",
                         "the worker was not running inside an ephemeral copy")

    def test_a_check_that_writes_to_its_copy_cannot_reach_the_master(self):
        self.seed(checks=[{"check_id": "c1", "command":
                           [sys.executable, "-c",
                            "open('app.py','w').write('TAMPERED'); raise SystemExit(0)"]}])
        outcome = self.controller.verify("req-1")
        self.assertEqual(outcome["verdict"], "pass")
        # The fingerprint is of the master, which the worker's write never touched.
        self.assertTrue(outcome["candidate_fingerprint"].startswith("sha256:"))

    def test_a_check_that_destroys_its_copy_does_not_abort_the_verification(self):
        self.seed(checks=[{"check_id": "c1", "command":
                           [sys.executable, "-c",
                            "import shutil,os; shutil.rmtree(os.getcwd(), ignore_errors=True); "
                            "raise SystemExit(0)"]}])
        outcome = self.controller.verify("req-1")
        self.assertIn(outcome["verdict"], ("pass", "fail"))
        self.assertTrue(outcome["candidate_fingerprint"].startswith("sha256:"))

    def test_isolation_is_a_separate_process(self):
        source = (SCRIPTS / "f1_controller.py").read_text()
        self.assertIn("subprocess.run", source)
        self.assertIn("self._python", source)


class VerdictTests(Pipeline):
    def test_a_verdict_field_from_the_real_worker_would_be_rejected_outright(self):
        """The worker's schema has no verdict field, so adding one fails closed at the boundary."""
        controller = ctl.VerificationController(
            facts=self.facts, ingest=self.ingest, signer=self.signer, objects=self.objects,
            master_root=self.root / "tcb", identity="verifier-1",
            worker=self._worker_emitting("{'check_id':'c1','exit_code':0,'verdict':'pass'}"))
        with self.assertRaises(ctl.ControllerError) as caught:
            controller.verify("req-1")
        self.assertIn("unknown field", str(caught.exception))

    def _worker_emitting(self, observation: str) -> Path:
        path = self.root / "verdict_worker.py"
        path.write_text("import json,sys; sys.stdin.read(); sys.stdout.write(json.dumps("
                        "{'observations':[%s]}))\n" % observation)
        return path

    def test_the_controller_re_derives_the_verdict_and_ignores_the_workers_claim(self):
        """A forged verdict in worker output never reaches the attestation."""
        liar = self.root / "liar.py"
        # No forged verdict key here: that is now rejected outright at the boundary, covered by
        # its own test. This one proves the other half -- the controller reaches its OWN
        # conclusion from the observations, rather than reporting whatever the checks "meant".
        liar.write_text(
            "import json,sys; json.loads(sys.stdin.read());"
            "sys.stdout.write(json.dumps({'observations':"
            "[{'check_id':'c1','exit_code':1,'output_head':'ALL TESTS PASSED'}]}))\n")
        controller = ctl.VerificationController(
            facts=self.facts, ingest=self.ingest, signer=self.signer, objects=self.objects,
            master_root=self.root / "tcb", identity="verifier-1", worker=liar)
        outcome = controller.verify("req-1")
        self.assertEqual(outcome["verdict"], "fail",
                         "the worker's claimed verdict was believed")

    def test_a_failing_check_produces_a_fail(self):
        self.seed(checks=[{"check_id": "c1",
                           "command": [sys.executable, "-c", "raise SystemExit(3)"]}])
        self.assertEqual(self.controller.verify("req-1")["verdict"], "fail")

    def test_no_observations_is_a_fail_not_a_pass(self):
        self.seed(checks=[])
        self.assertEqual(self.controller.verify("req-1")["verdict"], "fail")

    def test_the_attestation_enters_the_ordinary_pipeline(self):
        outcome = self.controller.verify("req-1")
        self.assertTrue(outcome["result"].admissible, outcome["result"].reason)
        self.assertEqual(len(self.facts._table("verdicts")), 1)
        self.assertTrue(self.facts.current_pass("obl-1", outcome["candidate_fingerprint"]))


class HostileWorkerOutputTests(Pipeline):
    def controller_with(self, script: str):
        path = self.root / "hostile.py"
        path.write_text(script)
        return ctl.VerificationController(
            facts=self.facts, ingest=self.ingest, signer=self.signer, objects=self.objects,
            master_root=self.root / "tcb", identity="verifier-1", worker=path)

    def test_malformed_output_fails_closed(self):
        controller = self.controller_with(
            "import sys; sys.stdin.read(); sys.stdout.write('not json')\n")
        with self.assertRaises(ctl.ControllerError):
            controller.verify("req-1")

    def test_oversized_output_fails_closed(self):
        """VALID JSON, over the bound.

        Mutation testing showed the earlier version proved nothing: 200000 x's are not JSON, so
        removing the size check left it refused by the parser instead. The bound only has a test
        if the oversized payload would otherwise have been accepted.
        """
        controller = self.controller_with(
            "import json,sys; sys.stdin.read(); sys.stdout.write(json.dumps({'observations':"
            "[{'check_id':'c'+str(i),'exit_code':0} for i in range(5000)]}))\n")
        with self.assertRaises(ctl.ControllerError) as caught:
            controller.verify("req-1")
        self.assertIn("exceeds its bound", str(caught.exception))

    def test_unknown_fields_fail_closed(self):
        controller = self.controller_with(
            "import json,sys; sys.stdin.read(); sys.stdout.write(json.dumps({'observations':"
            "[{'check_id':'c1','exit_code':0,'authority':'verification'}]}))\n")
        with self.assertRaises(ctl.ControllerError) as caught:
            controller.verify("req-1")
        self.assertIn("unknown field", str(caught.exception))

    def test_a_missing_required_field_fails_closed(self):
        controller = self.controller_with(
            "import json,sys; sys.stdin.read(); sys.stdout.write(json.dumps("
            "{'observations':[{'check_id':'c1'}]}))\n")
        with self.assertRaises(ctl.ControllerError):
            controller.verify("req-1")

    def test_an_unknown_top_level_key_fails_closed(self):
        """A worker emitting its own verdict alongside the observations."""
        controller = self.controller_with(
            "import json,sys; sys.stdin.read(); sys.stdout.write(json.dumps({'observations':"
            "[{'check_id':'c1','exit_code':0}],'verdict':'pass'}))\n")
        with self.assertRaises(ctl.ControllerError) as caught:
            controller.verify("req-1")
        self.assertIn("unknown top-level key", str(caught.exception))

    def test_a_non_object_observation_fails_closed(self):
        controller = self.controller_with(
            "import json,sys; sys.stdin.read(); sys.stdout.write(json.dumps("
            "{'observations':['pass']}))\n")
        with self.assertRaises(ctl.ControllerError):
            controller.verify("req-1")


class MasterIntegrityTests(Pipeline):
    def test_a_master_changed_during_verification_aborts_with_no_attestation(self):
        """§7.5: re-confirm the master is unchanged, else ABORT."""
        original = ctl.VerificationController._run_worker

        def tamper(self_, master, checks):
            (master / "injected.py").write_text("changed under the verification\n")
            return original(self_, master, checks)

        ctl.VerificationController._run_worker = tamper
        try:
            with self.assertRaises(ctl.AbortedError):
                self.controller.verify("req-1")
        finally:
            ctl.VerificationController._run_worker = original
        self.assertEqual(self.facts._table("verdicts"), {},
                         "an attestation was produced for an aborted verification")

    def test_the_master_is_built_in_tcb_storage_not_the_workspace(self):
        outcome = self.controller.verify("req-1")
        self.assertTrue(outcome["candidate_fingerprint"].startswith("sha256:"))
        self.assertTrue((self.root / "tcb").exists())

    def test_an_unresolvable_object_refuses_before_anything_runs(self):
        self.objects.pop("sha256:patch")
        with self.assertRaises(ctl.ControllerError):
            self.controller.verify("req-1")
        self.assertEqual(self.facts._table("verdicts"), {})

    def test_a_candidate_binding_that_does_not_resolve_is_refused_by_that_rule(self):
        # Asserting the REASON, not just the refusal: without §7.5's REFUSE, materialization fails
        # later anyway, so the rule itself was never what the test exercised. Mutation testing
        # found this, and an earlier attempt to fix it silently failed to apply -- which looks
        # exactly like a fix that worked.
        state = self.store.read()
        state["tcb"]["candidate_bindings"][self.run_ref] = {"base_digest": "", "patch_digest": ""}
        with self.store._exclusive():
            self.store._write(state)
        with self.assertRaises(ctl.ControllerError) as caught:
            self.controller.verify("req-1")
        self.assertIn("REFUSE", str(caught.exception))

    def test_a_missing_candidate_binding_is_refused(self):
        state = self.store.read()
        state["tcb"]["candidate_bindings"] = {}
        with self.store._exclusive():
            self.store._write(state)
        with self.assertRaises(ctl.ControllerError) as caught:
            self.controller.verify("req-1")
        self.assertIn("REFUSE", str(caught.exception))


class IdentityTests(Pipeline):
    def test_the_execution_identity_is_produced_by_the_controller(self):
        self.assertEqual(self.facts.execution_identities(self.run_ref), frozenset())
        self.controller.verify("req-1")
        self.assertEqual(self.facts.execution_identities(self.run_ref),
                         frozenset({"executor:req-1"}))

    def test_an_execution_identity_equal_to_the_verification_identity_is_refused(self):
        controller = ctl.VerificationController(
            facts=self.facts, ingest=self.ingest, signer=self.signer, objects=self.objects,
            master_root=self.root / "tcb", identity="executor:req-1")
        with self.assertRaises(ctl.ControllerError) as caught:
            controller.verify("req-1")
        self.assertIn("never the same principal", str(caught.exception))

    def test_the_fingerprint_is_derived_from_the_master_contents(self):
        first = self.controller.verify("req-1")["candidate_fingerprint"]
        self.seed(base={"app.py": "print('different')\n"})
        second = self.controller.verify("req-1")["candidate_fingerprint"]
        self.assertNotEqual(first, second, "the fingerprint does not depend on the master")


if __name__ == "__main__":
    unittest.main()
