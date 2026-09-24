"""G1-C3: freeze enforces exact, P18-resolved candidate_bindings and emits fingerprint V3 (T1..T9)."""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_artifacts as na                                              # noqa: E402
import nogap_lifecycle as nlc                                             # noqa: E402
from nogap_errors import MethodologyValidationError                       # noqa: E402
from nogap_methodology import status as mstatus                           # noqa: E402
from test_methodology_lifecycle import LifecycleFixture, make_task_contract  # noqa: E402

UNATTESTED = hashlib.sha256(b"unattested").hexdigest()


class FreezeV3(LifecycleFixture):
    """Real pipeline to P18: one real task with one real P18_VERIFICATION_RESULT."""

    def real_hash(self) -> str:
        (p18,) = na.list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")
        self.assertEqual(p18["fields"]["task_id"], self.task_id)
        return p18["fields"]["candidate_hash"]

    def assert_unmutated(self, rc_id: str) -> None:
        rec = nlc.load_release_candidate(self.project, rc_id)
        self.assertEqual(rec["status"], "DRAFT")
        self.assertEqual(rec["freeze_status"], "NOT_FROZEN")
        self.assertIsNone(rec["freeze_record"])
        self.assertIsNone(rec["candidate_fingerprint"])
        self.assertNotIn("candidate_fingerprint_version", rec)
        self.assertEqual(mstatus(self.project)["current_phase"], "P18")

    def test_t1_exact_resolved_bindings_freeze_as_v3(self):
        rc = self.frozen_candidate()
        expected = {self.task_id: self.real_hash()}
        self.assertEqual(rc["status"], "FROZEN")
        self.assertEqual(rc["candidate_bindings"], expected)
        self.assertEqual(rc["candidate_fingerprint_version"], "3")
        self.assertEqual(rc["freeze_record"]["candidate_fingerprint_version"], "3")
        self.assertEqual(rc["freeze_record"].get("candidate_bindings"), expected)  # M5: assertion, not KeyError

    def test_t2_partial_coverage_fails_closed_without_mutation(self):
        unbound = make_task_contract(self.project, self.chain)["fields"]["task_id"]
        rc = self.make_candidate(included_task_refs=[self.task_id, unbound],
                                 candidate_bindings={self.task_id: self.real_hash()})
        with self.assertRaises(MethodologyValidationError) as ctx:
            nlc.freeze_release_candidate(self.project, rc["release_candidate_id"], actor="rm", reason="freeze")
        self.assertIn(f"missing=[{unbound!r}]", str(ctx.exception))
        self.assert_unmutated(rc["release_candidate_id"])

    def test_t3_unresolved_pair_fails_closed_without_mutation(self):
        rc = self.make_candidate(candidate_bindings={self.task_id: UNATTESTED})  # G1-C1 allows creating this
        with self.assertRaises(MethodologyValidationError) as ctx:
            nlc.freeze_release_candidate(self.project, rc["release_candidate_id"], actor="rm", reason="freeze")
        self.assertIn("resolves to no P18_VERIFICATION_RESULT", str(ctx.exception))
        self.assert_unmutated(rc["release_candidate_id"])

    def test_t4_v3_payload_is_v2_plus_sorted_bindings(self):
        args = ("rev1", {"b": "h2", "a": "h1"}, ["T2", "T1"], ["R1"], ["v1"], ["e2", "e1"])
        bindings = {"T2": "f" * 64, "T1": "e" * 64}
        v2 = nlc._candidate_fingerprint_payload_v2(*args)
        v3 = nlc._candidate_fingerprint_payload_v3(*args, bindings)
        self.assertEqual(v3, {**v2, "candidate_bindings": dict(sorted(bindings.items()))})
        self.assertEqual(list(v3["candidate_bindings"]), ["T1", "T2"])
        # digest pin on a real V3 freeze
        rc = self.frozen_candidate()
        payload = {**nlc._candidate_fingerprint_payload_v2(
            rc["code_revision"], rc["artifact_fingerprints"], rc["included_task_refs"],
            rc["included_requirement_refs"], rc["verification_refs"], rc["evidence_refs"]),
            "candidate_bindings": dict(sorted(rc["candidate_bindings"].items()))}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertEqual(rc["candidate_fingerprint"], digest)
        v2_digest = nlc.compute_candidate_fingerprint(
            rc["code_revision"], rc["artifact_fingerprints"], rc["included_task_refs"],
            rc["included_requirement_refs"], rc["verification_refs"], rc["evidence_refs"], version="2")
        self.assertNotEqual(rc["candidate_fingerprint"], v2_digest)

    def test_t5_recompute_reproduces_v3_fingerprint(self):
        rc = self.frozen_candidate()
        loaded = nlc.load_release_candidate(self.project, rc["release_candidate_id"])
        self.assertEqual(nlc.recompute_candidate_fingerprint_for_record(loaded), loaded["candidate_fingerprint"])

    def test_t6_v1_v2_records_recompute_under_own_version(self):
        rc = self.frozen_candidate()
        base = (rc["code_revision"], rc["artifact_fingerprints"], rc["included_task_refs"],
                rc["included_requirement_refs"], rc["verification_refs"], rc["evidence_refs"])
        for version in ("1", "2"):
            with self.subTest(version=version):
                legacy = json.loads(json.dumps(rc))  # still carries candidate_bindings: must be ignored
                legacy["candidate_fingerprint_version"] = version
                legacy["candidate_fingerprint"] = nlc.compute_candidate_fingerprint(*base, version=version)
                self.assertEqual(nlc.recompute_candidate_fingerprint_for_record(legacy), legacy["candidate_fingerprint"])
                self.assertNotEqual(legacy["candidate_fingerprint"], rc["candidate_fingerprint"])
                self.assertEqual(legacy["candidate_fingerprint_version"], version)  # no silent upgrade
        no_version = json.loads(json.dumps(rc))
        del no_version["candidate_fingerprint_version"]
        self.assertEqual(nlc.recompute_candidate_fingerprint_for_record(no_version),
                         nlc.compute_candidate_fingerprint(*base, version="1"))

    def test_t7_predicate_only_frozen_v3(self):
        rc = self.frozen_candidate()
        self.assertTrue(nlc.has_fingerprint_frozen_candidate_bindings(rc))
        for version in ("1", "2"):
            with self.subTest(version=version):
                self.assertFalse(nlc.has_fingerprint_frozen_candidate_bindings(
                    {**rc, "candidate_fingerprint_version": version}))
        self.assertFalse(nlc.has_fingerprint_frozen_candidate_bindings({**rc, "status": "DRAFT"}))
        self.assertFalse(nlc.has_fingerprint_frozen_candidate_bindings(self.make_candidate(candidate_ref="d")))


def _called_names(name: str) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(nlc, name))))
    return ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)})


class Structural(unittest.TestCase):
    def test_t8_enforcement_is_freeze_only(self):
        resolvers = {"resolve_candidate_binding", "resolve_candidate_bindings"}
        for name in ("create_release_candidate", "update_release_candidate_bindings"):
            with self.subTest(fn=name):
                self.assertFalse(resolvers & _called_names(name))
        self.assertIn("resolve_candidate_bindings", _called_names("freeze_release_candidate"))

    def test_t9_unknown_version_fails_closed(self):
        with self.assertRaises(MethodologyValidationError):
            nlc.compute_candidate_fingerprint("r", {}, [], [], [], [], version="4")
        with self.assertRaises(MethodologyValidationError):
            nlc.recompute_candidate_fingerprint_for_record({"candidate_fingerprint_version": "99"})


if __name__ == "__main__":
    unittest.main()
