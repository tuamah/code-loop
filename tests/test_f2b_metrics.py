"""F2b: METRICS moved DEFERRED -> ENFORCED (Rev 2.1 sec 2.5).

METRICS = WholeArtifact("P10_BASELINE") - the same resolver class already used for
SCOPE/PROJECT_INTENT/ARCHITECTURE/etc. The normative "primary_metric mandatory,
secondary_metrics must-exist-but-may-be-empty" rule is now expressed directly by the artifact
contract itself (METRICS-PRE's allow_empty_fields), so validate_record already enforces it -
no new resolver logic here, only the mapping.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_artifacts as na                                              # noqa: E402
import nogap_methodology as nm                                            # noqa: E402
import nogap_required_kinds as rk                                         # noqa: E402
from test_methodology_build import build_p0_p11_chain                     # noqa: E402


class MetricsEnforced(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.project = Path(self.dir.name)
        import subprocess
        for args in (["init", "-q"], ["config", "user.email", "t@t.com"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=self.project, check=True, capture_output=True)
        (self.project / "R.md").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "R.md"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=self.project, check=True,
                       capture_output=True)
        nm.init_project(self.project, "research", "low", "low", actor="test")
        self.chain = build_p0_p11_chain(self.project)
        self.p10_id = self.chain["P10"]["artifact_id"]

    def rewrite(self, artifact_id: str, **changes) -> None:
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        for key, value in changes.items():
            if key == "fields":
                record["fields"].update(value)
            else:
                record[key] = value
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def check(self, refs: list[str]) -> rk.Verdict:
        (verdict,) = rk.check_required_kinds(self.project, ["METRICS"], refs)
        return verdict

    def test_mapping_is_whole_artifact_p10_baseline(self):
        self.assertIsInstance(rk.ENFORCED_KINDS["METRICS"], rk.WholeArtifact)
        self.assertEqual(rk.ENFORCED_KINDS["METRICS"].artifact_type, "P10_BASELINE")
        self.assertNotIn("METRICS", rk.DEFERRED_KINDS)

    def test_partition_guard_holds(self):
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertEqual(len(enforced), 36)
        self.assertEqual(len(deferred), 0)
        self.assertIn("METRICS", enforced)
        self.assertNotIn("METRICS", deferred)

    def test_valid_metric_set_passes(self):
        verdict = self.check([self.p10_id])
        self.assertEqual(verdict.outcome, rk.VALIDATED, str(verdict))
        self.assertEqual(verdict.status, rk.PASS)
        self.assertFalse(verdict.blocks_transition)

    def test_missing_rejected(self):
        verdict = self.check(["no-such-artifact"])
        self.assertEqual(verdict.status, rk.MISSING)
        self.assertTrue(verdict.blocks_transition)

    def test_wrong_type_rejected(self):
        wrong = self.chain["P0"]["artifact_id"]
        verdict = self.check([wrong])
        self.assertEqual(verdict.status, rk.WRONG_TYPE)
        self.assertIn("P0_PROJECT_INTENT", verdict.detail)
        self.assertTrue(verdict.blocks_transition)

    def test_empty_primary_metric_rejected(self):
        self.rewrite(self.p10_id, fields={"primary_metric": ""})
        verdict = self.check([self.p10_id])
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertIn("primary_metric", verdict.detail)
        self.assertTrue(verdict.blocks_transition)

    def test_empty_secondary_metrics_still_validates(self):
        """The exact point of METRICS-PRE's allow_empty_fields: a baseline with one measure
        is legitimate, and METRICS must accept it, not reject it as incomplete."""
        self.rewrite(self.p10_id, fields={"secondary_metrics": []})
        verdict = self.check([self.p10_id])
        self.assertEqual(verdict.outcome, rk.VALIDATED, str(verdict))

    def test_stale_rejected(self):
        self.rewrite(self.p10_id, status="SUPERSEDED")
        verdict = self.check([self.p10_id])
        self.assertEqual(verdict.status, rk.STALE)
        self.assertTrue(verdict.blocks_transition)

    def test_resolution_depends_only_on_supplied_refs_not_a_project_wide_scan(self):
        verdict = self.check(["not-the-real-one"])
        self.assertEqual(verdict.status, rk.MISSING, str(verdict))

    def test_real_transition_p10_to_p11_enforces_metrics(self):
        state_path = nm.methodology_state_path(self.project)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["current_phase"] = "P10"
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.rewrite(self.p10_id, fields={"primary_metric": ""})
        result = nm.can_transition(self.project, "P11", evidence_refs=[], artifact_refs=[self.p10_id])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("METRICS" in r for r in result["blocked_reasons"]))


if __name__ == "__main__":
    unittest.main()
