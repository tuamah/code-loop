"""G1-B: tracked cmd_run binds execution evidence to the candidate born there (one patch-hash
value feeds both the binding and P14); ineligible paths stay unbound, nothing fabricated."""
from __future__ import annotations

import argparse
import ast
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap                                                              # noqa: E402
import nogap_adapters                                                     # noqa: E402
import nogap_artifacts as na                                              # noqa: E402
import nogap_build                                                        # noqa: E402
import nogap_verify_binding as vb                                         # noqa: E402
import methodology_fixture_builder as fbuilder                            # noqa: E402
from test_g1a_candidate_binding import VERIFY_CLASSES, _prepare, _records  # noqa: E402
from test_verification_pipeline import (                                  # noqa: E402
    StubExecutor, _ungoverned_project, init_git_repo, run_script)


class TrackedRunBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project, env = _prepare()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            builder = fbuilder.advance_via_real_pipeline(cls.project)
        cls.task_id = builder.artifacts["P12"]["fields"]["task_id"]
        cls.records = _records(cls.project)
        cls.exe = [r for r in cls.records if r.get("evidence_class") == "execution"]
        p18 = na.list_artifacts(cls.project, artifact_type="P18_VERIFICATION_RESULT")
        cls.p18 = p18[0]["fields"] if len(p18) == 1 else None
        p14 = na.list_artifacts(cls.project, artifact_type="P14_SELF_CHECK")
        cls.p14 = p14[-1]["fields"] if p14 else None

    def test_t1_one_candidate_from_execution_through_verification(self):
        self.assertEqual(len(self.exe), 1)
        self.assertIsNotNone(self.p18)
        born = self.exe[0]["provenance"].get("candidate_hash")
        self.assertEqual(born, self.p18["candidate_hash"])
        verification = [r for r in self.records if r.get("evidence_class") in VERIFY_CLASSES]
        self.assertEqual({r["evidence_class"] for r in verification}, VERIFY_CLASSES)
        for r in verification:
            self.assertEqual(r["provenance"].get("candidate_hash"), born, r["evidence_class"])

    def test_t2_execution_task_id_is_contract_task_id(self):
        self.assertEqual(self.exe[0]["provenance"].get("task_id"), self.task_id)

    def test_t3_p14_patch_hash_is_the_bound_patch_hash(self):
        patch = Path(self.exe[0]["provenance"]["artifact_path"]).read_text(encoding="utf-8")
        self.assertIsNotNone(self.p14)
        self.assertEqual(self.p14["patch_hash"], nogap_build.patch_hash(patch))
        self.assertEqual(self.exe[0]["provenance"]["candidate_hash"],
                         vb.compute_candidate_hash(self.task_id, self.p14["patch_hash"]))


class IneligibleUnbound(unittest.TestCase):
    def _run(self, fn):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            self.assertEqual(run_script("init", str(project), "--objective", "x").returncode, 0)
            self.assertEqual(run_script("freeze", str(project)).returncode, 0)
            saved = dict(nogap_adapters.ADAPTERS)
            nogap_adapters.ADAPTERS.clear()
            nogap_adapters.ADAPTERS.update({"executor": StubExecutor("executor")})
            try:
                with _ungoverned_project(), contextlib.redirect_stdout(io.StringIO()):
                    fn(project)
            finally:
                nogap_adapters.ADAPTERS.clear()
                nogap_adapters.ADAPTERS.update(saved)
            exe = [r for r in _records(project) if r.get("evidence_class") == "execution"]
            self.assertTrue(exe)
            for r in exe:
                self.assertNotIn("candidate_hash", r["provenance"])

    def test_t4_untracked_cmd_run_is_unbound(self):
        self._run(lambda p: nogap.cmd_run(argparse.Namespace(
            path=str(p), actor="t", execute=True, execute_timeout=60)))

    def test_t5_cmd_execute_is_unbound(self):
        self._run(lambda p: nogap.cmd_execute(argparse.Namespace(
            path=str(p), actor="t", timeout=60,
            worktree_command=[sys.executable, "-c", "open('t.txt','w').write('x')"])))


def _funcs():
    tree = ast.parse((ROOT / "scripts" / "nogap.py").read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _is_patch_hash_of_result_patch(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "compute_patch_hash" and len(node.args) == 1
            and ast.unparse(node.args[0]) == "result.patch")


class Structural(unittest.TestCase):
    def test_t6_patch_hash_computed_once_and_feeds_both_uses(self):
        fn = _funcs()["cmd_run"]
        calls = [n for n in ast.walk(fn) if _is_patch_hash_of_result_patch(n)]
        self.assertEqual(len(calls), 1, "patch hash of result.patch must be computed exactly once")
        owners = [a for a in ast.walk(fn) if isinstance(a, ast.Assign)
                  and any(c is calls[0] for c in ast.walk(a.value))]
        self.assertEqual(len(owners), 1)
        self.assertEqual(len(owners[0].targets), 1)
        name = owners[0].targets[0].id
        cand = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                and ast.unparse(n.func) == "vb.compute_candidate_hash"]
        self.assertEqual(len(cand), 1)
        self.assertEqual([ast.unparse(a) for a in cand[0].args], ["task_id", name])
        p14 = [k for n in ast.walk(fn) if isinstance(n, ast.Call)
               and ast.unparse(n.func) == "create_self_check"
               for k in n.keywords if k.arg == "patch_hash"]
        self.assertEqual(len(p14), 1)
        self.assertEqual(ast.unparse(p14[0].value), name)

    def test_t7_no_candidate_hash_from_dispatch_run_or_execution_id(self):
        forbidden = {"dispatch_id", "run_id", "execution_id", "dispatch"}
        funcs = _funcs()
        for fname in ("cmd_run", "cmd_execute"):
            fn = funcs[fname]
            cand_names = {"candidate_hash"}
            for n in ast.walk(fn):
                if isinstance(n, ast.keyword) and n.arg == "candidate_hash" and isinstance(n.value, ast.Name):
                    cand_names.add(n.value.id)
            for n in ast.walk(fn):
                values = []
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in cand_names
                                                     for t in n.targets):
                    values.append(n.value)
                if isinstance(n, ast.keyword) and n.arg == "candidate_hash":
                    values.append(n.value)
                if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("compute_candidate_hash"):
                    values.extend(n.args)
                for v in values:
                    names = {x.id for x in ast.walk(v) if isinstance(x, ast.Name)}
                    names |= {x.attr for x in ast.walk(v) if isinstance(x, ast.Attribute)}
                    self.assertFalse(names & forbidden, f"{fname}: {ast.unparse(v)}")
            if fname == "cmd_execute":
                kws = [ast.unparse(n.value) for n in ast.walk(fn)
                       if isinstance(n, ast.keyword) and n.arg == "candidate_hash"]
                self.assertEqual(kws, ["None"])


if __name__ == "__main__":
    unittest.main()
