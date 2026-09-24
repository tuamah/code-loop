"""G1-A (Rev 2.1 §2.6.1): verification evidence carries the P18 candidate_hash, copied from
the in-scope variable, never reconstructed; the verified patch must be the P14 patch."""
from __future__ import annotations

import argparse
import ast
import contextlib
import inspect
import io
import json
import os
import stat
import subprocess
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
import methodology_fixture_builder as fbuilder                            # noqa: E402
from test_evidence_classes import _git_project                            # noqa: E402
from test_verification_pipeline import (                                  # noqa: E402
    StubExecutor, _ungoverned_project, init_git_repo, run_script)

VERIFY_CLASSES = {"deterministic", "effect_scope", "reproducibility", "independent_review"}


def _prepare(risk: str = "medium") -> tuple[Path, dict]:
    project = _git_project(risk)
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "nogap.py"), "init",
                           str(project), "--objective", "fixture"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    gate_path = project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["rules"]["required_commands"] = ["pytest -k unit"]
    gate_path.write_text(json.dumps(gate, indent=2), encoding="utf-8")
    bindir = Path(tempfile.mkdtemp())
    shim = bindir / "pytest"
    shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return project, {"PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"}


def _records(project: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in (project / ".code-loop" / "runtime" / "evidence").glob("*.json")]


class DeclaredEquality(unittest.TestCase):
    """T1/T4 on records written by the real pipeline."""

    @classmethod
    def setUpClass(cls):
        cls.project, env = _prepare()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            fbuilder.advance_via_real_pipeline(cls.project)
        cls.records = _records(cls.project)
        cls.p18 = na.list_artifacts(cls.project, artifact_type="P18_VERIFICATION_RESULT")

    def test_t1_verification_evidence_candidate_equals_p18(self):
        self.assertEqual(len(self.p18), 1)
        p18 = self.p18[0]["fields"]
        verification = [r for r in self.records if r.get("evidence_class") in VERIFY_CLASSES]
        self.assertEqual({r["evidence_class"] for r in verification}, VERIFY_CLASSES)
        for r in verification:
            self.assertEqual(r["provenance"].get("candidate_hash"), p18["candidate_hash"], r["evidence_class"])
            self.assertEqual(r["provenance"].get("task_id"), p18["task_id"], r["evidence_class"])

    def test_t4_execution_evidence_is_unbound(self):
        exe = [r for r in self.records if r.get("evidence_class") == "execution"]
        self.assertTrue(exe)
        for r in exe:
            self.assertNotIn("candidate_hash", r["provenance"])


class PatchMismatchGuard(unittest.TestCase):
    """T2: a verified patch that is not the P14 self-check patch fails closed."""

    def test_t2_tampered_patch_fails_closed(self):
        project, env = _prepare()
        fbuilder._ensure_git_repo(project)
        builder = fbuilder.FixtureBuilder(project, actor="fixture")
        saved = dict(nogap_adapters.ADAPTERS)
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            builder.advance_to("P12")
            builder._artifact_for("P12")
            task_id = builder.artifacts["P12"]["fields"]["task_id"]
            nogap_adapters.ADAPTERS.clear()
            nogap_adapters.ADAPTERS.update(fbuilder._pipeline_adapters())
            try:
                nogap.cmd_run(argparse.Namespace(path=str(project), actor="fixture", execute=True,
                                                 execute_timeout=600, task_id=task_id))
                before = {r["id"] for r in _records(project)}
                exe = [r for r in _records(project) if r.get("evidence_class") == "execution"][-1]
                patch_path = Path(exe["provenance"]["artifact_path"])
                patch_path.write_text(patch_path.read_text(encoding="utf-8") + "+tampered\n", encoding="utf-8")
                with self.assertRaises(SystemExit) as ctx:
                    nogap.cmd_verify_methodology(argparse.Namespace(
                        path=str(project), dispatch=None, timeout=120, review=True,
                        review_timeout=120, actor="verifier"))
            finally:
                nogap_adapters.ADAPTERS.clear()
                nogap_adapters.ADAPTERS.update(saved)
        self.assertIn("does not match latest P14_SELF_CHECK patch_hash", str(ctx.exception))
        new = [r for r in _records(project) if r["id"] not in before]
        self.assertEqual([r for r in new if r["provenance"].get("authority") == "verification"], [])
        self.assertEqual(na.list_artifacts(project, artifact_type="P18_VERIFICATION_RESULT"), [])


class UntrackedIsUnbound(unittest.TestCase):
    """T3: untracked verification never fabricates a candidate_hash."""

    def test_t3_untracked_verification_has_no_candidate_hash(self):
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
                    nogap.cmd_run(argparse.Namespace(path=str(project), actor="t", execute=True, execute_timeout=60))
            finally:
                nogap_adapters.ADAPTERS.clear()
                nogap_adapters.ADAPTERS.update(saved)
            result = run_script("verify-methodology", str(project))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            verification = [r for r in _records(project) if r["provenance"].get("authority") == "verification"]
            self.assertTrue(verification)
            for r in verification:
                self.assertNotIn("candidate_hash", r["provenance"])


class Structural(unittest.TestCase):
    def test_t5_candidate_hash_keyword_only_no_default(self):
        param = inspect.signature(nogap.write_isolated_run_evidence).parameters["candidate_hash"]
        self.assertIs(param.default, inspect.Parameter.empty)
        self.assertEqual(param.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_t6_candidate_hash_never_derived_from_dispatch_or_run(self):
        tree = ast.parse((ROOT / "scripts" / "nogap.py").read_text(encoding="utf-8"))
        forbidden = {"dispatch_id", "run_id", "dispatch", "execution"}
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for name in ("cmd_verify_methodology", "cmd_run", "cmd_execute", "write_isolated_run_evidence"):
            for node in ast.walk(funcs[name]):
                values = []
                if isinstance(node, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "candidate_hash" for t in node.targets):
                    values.append(node.value)
                if isinstance(node, ast.keyword) and node.arg == "candidate_hash":
                    values.append(node.value)
                for value in values:
                    names = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
                    self.assertFalse(names & forbidden, f"{name}: {ast.unparse(value)}")
        # every writer call site passes the in-scope variable or explicit None, nothing else
        for node in ast.walk(funcs["cmd_verify_methodology"]):
            if isinstance(node, ast.keyword) and node.arg == "candidate_hash":
                self.assertIn(ast.unparse(node.value),
                              {"candidate_hash", "candidate_hash if methodology_tracked else None"})


class RecordValidation(unittest.TestCase):
    """T7."""

    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        with contextlib.redirect_stdout(io.StringIO()):
            nogap.cmd_init(argparse.Namespace(target=str(self.project), objective="x",
                                              run_id="run-0001", force=False))
        self.evidence_dir = self.project / ".code-loop" / "runtime" / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def _validate_with(self, **prov) -> None:
        record = {"id": "evidence-x", "run_id": "run-0001", "kind": "review", "status": "passed",
                  "provenance": {"created_by": "t", "created_at": "2026-01-01T00:00:00Z",
                                 "authority": "verification", **prov}, "summary": "s"}
        (self.evidence_dir / "evidence-x.json").write_text(json.dumps(record), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            nogap.cmd_validate(argparse.Namespace(path=str(self.project)))

    def test_t7_absent_and_wellformed_pass(self):
        self._validate_with()
        self._validate_with(candidate_hash="a" * 64)

    def test_t7_malformed_fails(self):
        for bad in ("A" * 64, "a" * 63, "g" * 64, None, 5, ""):
            with self.subTest(bad=bad), self.assertRaises(SystemExit) as ctx:
                self._validate_with(candidate_hash=bad)
            self.assertIn("malformed candidate_hash", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
