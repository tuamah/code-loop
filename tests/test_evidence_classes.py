"""D4-PRE-C: declared evidence classes, stamped at the writer, never derived from kind.

Rev 2.1 (docs/f2b-semantic-contract-proposal.md) is normative. `kind` is storage;
`evidence_class` is semantics. This also pins the G2 closure: independent review and
effect-scope share kind "review" but carry different classes.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import copy
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
import nogap_artifacts as na                                              # noqa: E402
import nogap_methodology as nm                                            # noqa: E402
import methodology_fixture_builder as fbuilder                            # noqa: E402
from nogap_evidence_classes import EVIDENCE_CLASSES                       # noqa: E402


def _git_project(risk: str) -> Path:
    project = Path(tempfile.mkdtemp())
    for args in (["init", "-q"], ["config", "user.email", "t@t.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    (project / "R.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "R.md"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=project, check=True, capture_output=True)
    nm.init_project(project, "research", risk, risk, actor="test")
    return project


class RealPipelineStampsClasses(unittest.TestCase):
    """T1-T3 on records the real verification pipeline actually wrote.

    Medium risk makes P17 (reproducibility) mandatory. The frozen gate carries the P11
    plan's required command so the deterministic layer runs a real non-effect-scope check;
    that command resolves to a trivial passing executable put on PATH for this test.
    """

    @classmethod
    def setUpClass(cls):
        cls.project = _git_project("medium")
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "nogap.py"), "init",
                               str(cls.project), "--objective", "fixture"],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stdout + done.stderr
        gate_path = cls.project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["rules"]["required_commands"] = ["pytest -k unit"]
        gate_path.write_text(json.dumps(gate, indent=2), encoding="utf-8")
        bindir = Path(tempfile.mkdtemp())
        shim = bindir / "pytest"
        shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        env = {"PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            fbuilder.advance_via_real_pipeline(cls.project)
        cls.records = [json.loads(p.read_text(encoding="utf-8")) for p in
                       (cls.project / ".code-loop" / "runtime" / "evidence").glob("*.json")]

    def by_class(self, cls_name: str) -> list[dict]:
        return [r for r in self.records if r.get("evidence_class") == cls_name]

    def test_t1_each_site_stamps_its_class(self):
        verification = [r for r in self.records
                        if r.get("provenance", {}).get("authority") == "verification"]
        self.assertTrue(verification)
        for r in verification:
            self.assertIn(r.get("evidence_class"), EVIDENCE_CLASSES, r["summary"])
        det = self.by_class("deterministic")
        self.assertTrue(det, "no deterministic record")
        self.assertTrue(all(r["kind"] == "test" for r in det))
        eff = self.by_class("effect_scope")
        self.assertEqual(len(eff), 1, "effect_scope comes only from the deterministic run")
        self.assertEqual(eff[0]["kind"], "review")
        rep = self.by_class("reproducibility")
        # every re-run check, including the re-run effect-scope check, is reproducibility
        self.assertEqual(len(rep), len(det) + len(eff))
        self.assertEqual({r["kind"] for r in rep}, {"test", "review"})
        rev = self.by_class("independent_review")
        self.assertEqual(len(rev), 1)
        self.assertTrue(rev[0]["provenance"]["actor_id"].startswith("agent:"))
        exe = self.by_class("execution")
        self.assertTrue(exe)
        self.assertTrue(all(r["kind"] == "execution" for r in exe))

    def test_t2_independent_review_differs_from_effect_scope(self):
        rev = self.by_class("independent_review")
        eff = self.by_class("effect_scope")
        self.assertTrue(rev and eff)
        self.assertEqual({r["kind"] for r in rev} | {r["kind"] for r in eff}, {"review"})
        self.assertNotEqual(rev[0]["evidence_class"], eff[0]["evidence_class"])

    def test_t3_deterministic_differs_from_reproducibility(self):
        det = self.by_class("deterministic")
        rep = [r for r in self.by_class("reproducibility") if r["kind"] == "test"]
        self.assertTrue(det and rep)
        self.assertEqual(det[0]["kind"], rep[0]["kind"])
        self.assertNotEqual(det[0]["evidence_class"], rep[0]["evidence_class"])

    def test_plan_and_skip_are_not_stamped(self):
        for r in self.records:
            if r.get("kind") in {"plan", "skip"}:
                self.assertNotIn("evidence_class", r)


class OwnerValidation(unittest.TestCase):
    """T4/T5: owner fields reject values outside the declared vocabulary."""

    @classmethod
    def setUpClass(cls):
        cls.project = _git_project("low")
        cls.builder = fbuilder.FixtureBuilder(cls.project)
        with contextlib.redirect_stdout(io.StringIO()):
            cls.builder.advance_to("P15")
            cls.builder._artifact_for("P15")

    def _problems(self, phase: str, field: str, value: list[str]) -> list[str]:
        record = copy.deepcopy(self.builder.artifacts[phase])
        record["fields"][field] = value
        return [p for p in na.validate_record(self.project, record) if field in p]

    def test_valid_values_accepted(self):
        self.assertEqual(self._problems("P11", "evidence_requirements", ["execution"]), [])
        self.assertEqual(self._problems("P15", "required_evidence_kinds", ["deterministic"]), [])

    def test_t4_p11_unknown_value_rejected(self):
        self.assertTrue(self._problems("P11", "evidence_requirements", ["execution", "vibes"]))
        self.assertTrue(self._problems("P11", "evidence_requirements", ["plan"]))

    def test_t5_p15_unknown_value_rejected(self):
        self.assertTrue(self._problems("P15", "required_evidence_kinds", ["independent_reviews"]))
        self.assertTrue(self._problems("P15", "required_evidence_kinds", ["skip"]))


class RecordValidation(unittest.TestCase):
    """T6/T7: `nogap validate` on evidence records."""

    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        with contextlib.redirect_stdout(io.StringIO()):
            nogap.cmd_init(argparse.Namespace(target=str(self.project), objective="x",
                                              run_id="run-0001", force=False))
        self.evidence_dir = self.project / ".code-loop" / "runtime" / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def _write(self, **extra) -> Path:
        record = {"id": "evidence-x", "run_id": "run-0001", "kind": "review", "status": "passed",
                  "provenance": {"created_by": "t", "created_at": "2026-01-01T00:00:00Z",
                                 "authority": "verification"},
                  "summary": "s", **extra}
        path = self.evidence_dir / "evidence-x.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def _validate(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            nogap.cmd_validate(argparse.Namespace(path=str(self.project)))

    def test_known_class_passes(self):
        self._write(evidence_class="independent_review")
        self._validate()

    def test_t6_unknown_class_fails(self):
        self._write(evidence_class="review")
        with self.assertRaises(SystemExit) as ctx:
            self._validate()
        self.assertIn("evidence_class", str(ctx.exception))

    def test_t7_legacy_record_loads_and_gets_no_class(self):
        path = self._write()
        before = path.read_bytes()
        self._validate()
        self.assertEqual(path.read_bytes(), before)
        loaded = nogap.load_objects(self.evidence_dir)["evidence-x"]
        self.assertNotIn("evidence_class", loaded)


class Structural(unittest.TestCase):
    def test_t8_writer_has_no_default_class(self):
        param = inspect.signature(nogap.write_isolated_run_evidence).parameters["evidence_class"]
        self.assertIs(param.default, inspect.Parameter.empty)
        self.assertEqual(param.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_t9_no_kind_to_class_derivation(self):
        """Nothing that produces an evidence_class may read `kind`, and no table may map
        storage kinds to classes."""
        storage_kinds = {"execution", "test", "review", "plan", "skip"}

        def mentions_kind(node: ast.AST) -> bool:
            return any((isinstance(n, ast.Name) and n.id == "kind")
                       or (isinstance(n, ast.Attribute) and n.attr == "kind")
                       or (isinstance(n, ast.Constant) and n.value == "kind")
                       for n in ast.walk(node))

        def is_class_target(t: ast.AST) -> bool:
            return ((isinstance(t, ast.Name) and t.id == "evidence_class")
                    or (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                        and t.slice.value == "evidence_class"))

        for name in ("nogap.py", "nogap_artifacts.py", "nogap_evidence_classes.py",
                     "nogap_evidence_ledger.py"):
            tree = ast.parse((ROOT / "scripts" / name).read_text(encoding="utf-8"))
            produced: list[ast.AST] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "evidence_class":
                    produced.append(node.value)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if any(is_class_target(t) for t in targets) and node.value is not None:
                        produced.append(node.value)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr == "setdefault" and node.args \
                        and isinstance(node.args[0], ast.Constant) and node.args[0].value == "evidence_class":
                    produced.extend(node.args[1:])
                elif isinstance(node, ast.Dict):
                    for k, v in zip(node.keys, node.values):
                        if isinstance(k, ast.Constant) and k.value == "evidence_class":
                            produced.append(v)
                    keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
                    vals = {v.value for v in node.values if isinstance(v, ast.Constant)}
                    self.assertFalse(keys & {"test", "review"} and vals & EVIDENCE_CLASSES,
                                     f"{name}: storage-kind -> class table: {ast.unparse(node)[:200]}")
                elif isinstance(node, ast.If) and mentions_kind(node.test):
                    for stmt in node.body + node.orelse:
                        self.assertNotIn("evidence_class", ast.unparse(stmt),
                                         f"{name}: branch on kind sets a class: {ast.unparse(node)[:200]}")
            for value in produced:
                self.assertFalse(mentions_kind(value),
                                 f"{name}: evidence_class derived from kind: {ast.unparse(value)[:200]}")


if __name__ == "__main__":
    unittest.main()
