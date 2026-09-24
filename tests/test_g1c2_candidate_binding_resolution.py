"""G1-C2: candidate_bindings -> P18_VERIFICATION_RESULT resolution, status-agnostic (T1..T7)."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import inspect
import io
import json
import os
import sys
import textwrap
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_artifacts as na                                              # noqa: E402
import nogap_lifecycle as nlc                                             # noqa: E402
import methodology_fixture_builder as fbuilder                            # noqa: E402
from nogap_errors import MethodologyValidationError                       # noqa: E402
from test_g1a_candidate_binding import _prepare                           # noqa: E402

UNATTESTED = hashlib.sha256(b"unattested").hexdigest()


class CandidateBindingResolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project, env = _prepare()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            builder = fbuilder.advance_via_real_pipeline(cls.project)
        cls.task_id = builder.artifacts["P12"]["fields"]["task_id"]
        p18 = na.list_artifacts(cls.project, artifact_type="P18_VERIFICATION_RESULT")
        assert len(p18) == 1, f"expected exactly one real P18, got {len(p18)}"
        cls.p18 = p18[0]
        cls.hash = cls.p18["fields"]["candidate_hash"]
        assert cls.p18["fields"]["task_id"] == cls.task_id and len(cls.hash) == 64

    def _unresolved(self, task_id, candidate_hash, needle="resolves to no P18_VERIFICATION_RESULT"):
        with self.assertRaises(MethodologyValidationError) as ctx:
            nlc.resolve_candidate_binding(self.project, task_id, candidate_hash)
        self.assertIn(needle, str(ctx.exception))

    def test_t1_exact_single_match_resolves(self):
        got = nlc.resolve_candidate_binding(self.project, self.task_id, self.hash)
        self.assertEqual(got["artifact_id"], self.p18["artifact_id"])

    def test_t2_unattested_pair_does_not_resolve(self):
        self._unresolved(self.task_id, UNATTESTED)          # right task, wrong hash

    def test_t2b_cross_task_hash_does_not_resolve(self):
        self._unresolved("TASK-OTHER", self.hash)           # real hash, wrong task

    def test_t3_status_agnostic(self):
        run_id = self.p18["fields"]["verification_run_id"]
        original = na.load_artifact(self.project, self.p18["artifact_id"])["status"]
        try:
            for status in ("VERIFICATION_IN_PROGRESS", "VERIFICATION_FAILED", "VERIFICATION_INCONCLUSIVE",
                           "VERIFICATION_COMPLETE_AWAITING_DECISION"):
                with self.subTest(status=status):
                    na.update_verification_result(self.project, run_id, "t", "t3", status=status)
                    got = nlc.resolve_candidate_binding(self.project, self.task_id, self.hash)
                    self.assertEqual(got["status"], status)
                    self.assertEqual(got["artifact_id"], self.p18["artifact_id"])
        finally:
            na.update_verification_result(self.project, run_id, "t", "restore", status=original)

    def test_t4_ambiguity_fails_closed(self):
        src = na.artifacts_dir(self.project) / f"{self.p18['artifact_id']}.json"
        dup = json.loads(src.read_text(encoding="utf-8"))
        dup["artifact_id"] = f"dup-{uuid.uuid4().hex}"
        dup_path = na.artifacts_dir(self.project) / f"{dup['artifact_id']}.json"
        dup_path.write_text(json.dumps(dup), encoding="utf-8")
        try:
            with self.assertRaises(MethodologyValidationError) as ctx:
                nlc.resolve_candidate_binding(self.project, self.task_id, self.hash)
            msg = str(ctx.exception)
            for needle in ("ambiguous", "2 P18_VERIFICATION_RESULT", self.task_id, self.hash,
                           self.p18["artifact_id"], dup["artifact_id"]):
                self.assertIn(needle, msg)
        finally:
            dup_path.unlink()

    def test_t5_bulk_check(self):
        got = nlc.resolve_candidate_bindings(self.project, {self.task_id: self.hash})
        self.assertEqual(got[self.task_id]["artifact_id"], self.p18["artifact_id"])
        self.assertEqual(nlc.resolve_candidate_bindings(self.project, {}), {})
        with self.assertRaises(MethodologyValidationError) as ctx:
            nlc.resolve_candidate_bindings(self.project, {self.task_id: self.hash, "TASK-OTHER": UNATTESTED})
        self.assertIn("candidate_bindings['TASK-OTHER']", str(ctx.exception))
        self.assertIn(UNATTESTED, str(ctx.exception))


def _fn(name):
    return ast.parse(textwrap.dedent(inspect.getsource(getattr(nlc, name)))).body[0]


class Structural(unittest.TestCase):
    def test_t6_resolution_enforced_only_at_freeze(self):
        # G1-C3 flipped the freeze half by design: freeze now enforces resolution.
        # create/update still never resolve, and stay DRAFT/ASSEMBLED-only.
        resolvers = {"resolve_candidate_binding", "resolve_candidate_bindings"}

        def called(name):
            names = {n.id for n in ast.walk(_fn(name)) if isinstance(n, ast.Name)}
            return names | {n.attr for n in ast.walk(_fn(name)) if isinstance(n, ast.Attribute)}
        for name in ("create_release_candidate", "update_release_candidate_bindings"):
            with self.subTest(fn=name):
                self.assertFalse(resolvers & called(name))
        self.assertIn("resolve_candidate_bindings", called("freeze_release_candidate"))
        self.assertIn('record["status"] in {"DRAFT", "ASSEMBLED"}',
                      inspect.getsource(nlc.update_release_candidate_bindings))
        self.assertIn('"status": "DRAFT"', inspect.getsource(nlc.create_release_candidate))

    def test_t7_no_status_read_in_resolution(self):
        for name in ("resolve_candidate_binding", "resolve_candidate_bindings"):
            tree = _fn(name)
            consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            attrs = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
            with self.subTest(fn=name):
                self.assertNotIn("status", consts)
                self.assertNotIn("status", attrs)
                self.assertFalse(any(c.startswith("VERIFICATION_") for c in consts))


if __name__ == "__main__":
    unittest.main()
