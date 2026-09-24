"""G1-C1: release-candidate candidate_bindings schema + owner-side validation (T1..T9)."""
from __future__ import annotations

import contextlib
import hashlib
import inspect
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_lifecycle as nlc                                             # noqa: E402
import methodology_fixture_builder as fbuilder                            # noqa: E402
from nogap_errors import MethodologyValidationError                       # noqa: E402
from test_evidence_classes import _git_project                            # noqa: E402
from test_methodology_lifecycle import LifecycleFixture, make_task_contract                 # noqa: E402

# G1-C3: source pins of create/update as accepted at G1-C1/G1-C2 (d2e5bdf); G1-C3 must not change them.
CREATE_UPDATE_SOURCE_SHA256 = {
    "create_release_candidate": "f5bd54dfb905c3d9de1b1c01f862b559447c8274bd01f2f606f7d24cdd1004ec",
    "update_release_candidate_bindings": "7d5e900b1fbbc0957bb7c74389677c5b3055ba519cc9160edb2d51aee63600d7",
}
H1 = hashlib.sha256(b"a").hexdigest()


class CandidateBindingsSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = _git_project("low")
        cls.builder = fbuilder.FixtureBuilder(cls.project)
        with contextlib.redirect_stdout(io.StringIO()):
            cls.builder.advance_to("P13")
        cls.task_a = cls.builder.artifacts["P12"]["fields"]["task_id"]
        chain = {"P6": cls.builder.artifacts["P6"], "P11": cls.builder.artifacts["P11"]}
        cls.task_b = make_task_contract(cls.project, chain)["fields"]["task_id"]

    def _create(self, **kw):
        return nlc.create_release_candidate(
            self.project, version="1.0.0", candidate_ref="rc", actor="rm", reason="t", **kw)

    def _rejects(self, needle, **kw):
        with self.assertRaises(MethodologyValidationError) as ctx:
            self._create(**kw)
        self.assertIn(needle, str(ctx.exception))

    def test_t1_subset_bindings_accepted(self):
        rc = self._create(included_task_refs=[self.task_a, self.task_b], candidate_bindings={self.task_a: H1})
        self.assertEqual(rc["candidate_bindings"], {self.task_a: H1})
        self.assertEqual(self._create()["candidate_bindings"], {})

    def test_t2_binding_key_not_included_rejected(self):
        self._rejects("is not in included_task_refs",
                      included_task_refs=[self.task_a], candidate_bindings={self.task_b: H1})

    def test_t3_duplicate_task_refs_rejected(self):
        self._rejects("duplicate included_task_refs", included_task_refs=[self.task_a, self.task_a])

    def test_t4_unresolvable_task_ref_rejected(self):
        self._rejects("unknown task_id", included_task_refs=[self.task_a, "TASK-DOES-NOT-EXIST"])

    def test_t5_malformed_hash_rejected(self):
        for bad in (H1[:-1], H1.upper(), "z" * 64, "sha256:" + H1[7:], 123):
            with self.subTest(bad=bad):
                self._rejects("64-char lowercase hex",
                              included_task_refs=[self.task_a], candidate_bindings={self.task_a: bad})

    def test_t6_partial_coverage_allowed_at_create_and_update(self):
        rc = self._create(included_task_refs=[self.task_a, self.task_b])
        self.assertEqual(rc["candidate_bindings"], {})
        updated = nlc.update_release_candidate_bindings(
            self.project, rc["release_candidate_id"], actor="rm", reason="bind", candidate_bindings={self.task_b: H1})
        self.assertEqual(updated["candidate_bindings"], {self.task_b: H1})
        self.assertEqual(nlc.load_release_candidate(self.project, rc["release_candidate_id"])["candidate_bindings"],
                         {self.task_b: H1})

    def test_update_path_reruns_rules(self):
        rc = self._create(included_task_refs=[self.task_a])
        with self.assertRaises(MethodologyValidationError):
            nlc.update_release_candidate_bindings(self.project, rc["release_candidate_id"], actor="rm",
                                                  reason="x", candidate_bindings={self.task_b: H1})
        with self.assertRaises(MethodologyValidationError):
            nlc.update_release_candidate_bindings(self.project, rc["release_candidate_id"], actor="rm",
                                                  reason="x", candidate_bindings={self.task_a: "bad"})

    def test_t7_not_in_rc_critical_fields(self):
        self.assertNotIn("candidate_bindings", nlc.RC_CRITICAL_FIELDS)

    def test_t8_create_update_unchanged_and_enforcement_freeze_only(self):
        # Replaces the pre-G1-C3 freeze-source pin (its purpose expired when G1-C3 was
        # authorized to change freeze): create/update semantics stay as G1-C1 left them,
        # and resolution/coverage enforcement stays out of them.
        for name, pinned in CREATE_UPDATE_SOURCE_SHA256.items():
            src = inspect.getsource(getattr(nlc, name))
            with self.subTest(fn=name):
                self.assertEqual(hashlib.sha256(src.encode()).hexdigest(), pinned)
                self.assertNotIn("resolve_candidate_binding", src)
        self.assertIn("resolve_candidate_bindings(", inspect.getsource(nlc.freeze_release_candidate))

    def test_t9b_update_rejects_invalidated(self):
        rc = self._create(included_task_refs=[self.task_a])
        nlc.invalidate_release_candidate(self.project, rc["release_candidate_id"], actor="rm", reason="i")
        with self.assertRaises(MethodologyValidationError) as ctx:
            nlc.update_release_candidate_bindings(self.project, rc["release_candidate_id"], actor="rm",
                                                  reason="x", candidate_bindings={self.task_a: H1})
        self.assertIn("cannot update candidate_bindings from status 'INVALIDATED'", str(ctx.exception))


class FrozenRejection(LifecycleFixture):
    def test_t9_update_rejects_frozen(self):
        rc = self.frozen_candidate()
        self.assertEqual(rc["status"], "FROZEN")
        with self.assertRaises(MethodologyValidationError) as ctx:
            nlc.update_release_candidate_bindings(self.project, rc["release_candidate_id"], actor="rm",
                                                  reason="x", candidate_bindings={self.task_id: H1})
        self.assertIn("cannot update candidate_bindings from status 'FROZEN'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
