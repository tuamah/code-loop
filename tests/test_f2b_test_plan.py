"""F2b: TEST_PLAN moved DEFERRED -> ENFORCED (Rev 2.1 sec 2.3).

Concrete source: P11_GATE_PLAN.required_tests, already a required_field on that artifact
type - validate_record already enforces it non-empty, so TEST_PLAN = ArtifactField(
"P11_GATE_PLAN", "required_tests") is the same shape D3's BENCHMARK_PROTOCOL already
established for a field-name mismatch. P11 also declares GOLDEN_GATES on the SAME artifact
type; GOLDEN_GATES stays DEFERRED, and check_required_kinds's independence invariant means
this never depends on GOLDEN_GATES having a decided meaning.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_artifacts as na                                                 # noqa: E402
import nogap_methodology as nm                                               # noqa: E402
import nogap_required_kinds as rk                                            # noqa: E402
from nogap_methodology import can_transition                                 # noqa: E402


class TestPlanEnforced(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.project = Path(self.dir.name)
        for args in (["init", "-q"], ["config", "user.email", "t@t.com"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=self.project, check=True, capture_output=True)
        (self.project / "R.md").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "R.md"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=self.project, check=True,
                       capture_output=True)
        nm.init_project(self.project, "research", "low", "low", actor="test")
        import test_methodology_build as chain
        self.chain = chain.build_p0_p11_chain(self.project)

    def rewrite(self, artifact_id: str, **fields) -> None:
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"].update(fields)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def set_status(self, artifact_id: str, status: str) -> None:
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["status"] = status
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def drop_field(self, artifact_id: str, field_name: str) -> None:
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        del record["fields"][field_name]
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def verdicts(self, phase_id: str, refs: list[str]) -> dict[str, rk.Verdict]:
        phase = nm.load_methodology().get_phase(phase_id)
        return {v.kind: v for v in
                rk.check_required_kinds(self.project, list(phase.required_artifacts), refs)}

    def forward(self, phase_id: str, refs: list[str]) -> dict:
        path = nm.methodology_state_path(self.project)
        state = json.loads(path.read_text(encoding="utf-8"))
        state["current_phase"] = phase_id
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        phase = nm.load_methodology().get_phase(phase_id)
        return can_transition(self.project, phase.allowed_next[0],
                              evidence_refs=[], artifact_refs=refs)

    # -- mapping / partition --

    def test_mapping_is_artifact_field_p11_gate_plan_required_tests(self):
        spec = rk.ENFORCED_KINDS["TEST_PLAN"]
        self.assertIsInstance(spec, rk.ArtifactField)
        self.assertEqual(spec.artifact_type, "P11_GATE_PLAN")
        self.assertEqual(spec.field, "required_tests")
        self.assertNotIn("TEST_PLAN", rk.DEFERRED_KINDS)

    def test_partition_guard_holds(self):
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertEqual(len(enforced), 31)
        self.assertEqual(len(deferred), 6)

    # -- T1: a real, valid required_tests resolves, VALIDATES, transition allowed -----

    def test_valid_required_tests_validates_and_allows_transition(self):
        ref = self.chain["P11"]["artifact_id"]
        verdict = self.verdicts("P11", [ref])["TEST_PLAN"]
        self.assertEqual(verdict.status, rk.PASS)
        self.assertEqual(verdict.outcome, rk.VALIDATED)
        self.assertFalse(verdict.blocks_transition)
        self.assertTrue(self.forward("P11", [ref])["allowed"])

    # -- T2: MISSING - ref does not resolve at all --

    def test_missing_rejected(self):
        verdict = self.verdicts("P11", ["no-such-artifact"])["TEST_PLAN"]
        self.assertEqual(verdict.status, rk.MISSING)
        self.assertTrue(verdict.blocks_transition)

    # -- T3: WRONG_TYPE - a real artifact of a different type --

    def test_wrong_type_rejected(self):
        wrong = self.chain["P0"]["artifact_id"]
        verdict = self.verdicts("P11", [wrong])["TEST_PLAN"]
        self.assertEqual(verdict.status, rk.WRONG_TYPE)
        self.assertTrue(verdict.blocks_transition)

    # -- T4: INVALID - empty required_tests, blocks and is attributed by name --

    def test_empty_required_tests_blocks_and_is_attributed(self):
        ref = self.chain["P11"]["artifact_id"]
        self.rewrite(ref, required_tests=[])
        verdict = self.verdicts("P11", [ref])["TEST_PLAN"]
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P11", [ref])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("TEST_PLAN" in r for r in result["blocked_reasons"]))

    # -- T5: missing field entirely - fails, never silently passes --

    def test_missing_required_tests_field_fails(self):
        ref = self.chain["P11"]["artifact_id"]
        self.drop_field(ref, "required_tests")
        verdict = self.verdicts("P11", [ref])["TEST_PLAN"]
        self.assertIn(verdict.status, (rk.INVALID, rk.MISSING))
        self.assertNotEqual(verdict.status, rk.PASS)
        self.assertTrue(verdict.blocks_transition)

    # -- T6: STALE --

    def test_stale_rejected(self):
        ref = self.chain["P11"]["artifact_id"]
        self.set_status(ref, "SUPERSEDED")
        verdict = self.verdicts("P11", [ref])["TEST_PLAN"]
        self.assertEqual(verdict.status, rk.STALE)
        self.assertTrue(verdict.blocks_transition)

    # -- independence from GOLDEN_GATES: same artifact, one kind decided, one still deferred --

    def test_independent_of_golden_gates_which_stays_deferred(self):
        ref = self.chain["P11"]["artifact_id"]
        found = self.verdicts("P11", [ref])
        self.assertEqual(found["TEST_PLAN"].outcome, rk.VALIDATED)
        self.assertEqual(found["GOLDEN_GATES"].status, rk.DEFERRED)
        self.assertEqual(found["GOLDEN_GATES"].outcome, rk.DEFERRED_OUTCOME)
        self.assertFalse(found["GOLDEN_GATES"].blocks_transition)
        # TEST_PLAN being satisfied does not depend on GOLDEN_GATES, and the transition is
        # not blocked by GOLDEN_GATES remaining undecided.
        self.assertTrue(self.forward("P11", [ref])["allowed"])

    def test_golden_gates_still_deferred(self):
        self.assertIn("GOLDEN_GATES", rk.DEFERRED_KINDS)
        self.assertNotIn("GOLDEN_GATES", rk.ENFORCED_KINDS)


if __name__ == "__main__":
    unittest.main()
