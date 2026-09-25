"""F2b: PRIOR_ART_MAP resolver (Rev 2.1 section 2.2).

PRIOR_ART_MAP = WholeArtifact("P3_PRIOR_ART") - the exact, already-tested _check_artifact_kind
resolver class used for SCOPE/PROJECT_INTENT/GAP_ANALYSIS/ARCHITECTURE/etc. No new resolver
code exists; these tests exercise the mapping and the (already-generic) MISSING/WRONG_TYPE/
INVALID/STALE behaviour specifically through the PRIOR_ART_MAP kind, and pin that resolution
depends only on the refs supplied to the transition - never a project-wide scan.
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


class PriorArtMapEnforced(unittest.TestCase):
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
        self.p3_id = self.chain["P3"]["artifact_id"]

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
        (verdict,) = rk.check_required_kinds(self.project, ["PRIOR_ART_MAP"], refs)
        return verdict

    def test_mapping_is_whole_artifact_p3_prior_art(self):
        self.assertIsInstance(rk.ENFORCED_KINDS["PRIOR_ART_MAP"], rk.WholeArtifact)
        self.assertEqual(rk.ENFORCED_KINDS["PRIOR_ART_MAP"].artifact_type, "P3_PRIOR_ART")
        self.assertNotIn("PRIOR_ART_MAP", rk.DEFERRED_KINDS)

    def test_partition_guard_holds(self):
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertEqual(len(enforced), 36)
        self.assertEqual(len(deferred), 0)
        self.assertIn("PRIOR_ART_MAP", enforced)
        self.assertNotIn("PRIOR_ART_MAP", deferred)

    def test_valid_whole_p3_passes(self):
        verdict = self.check([self.p3_id])
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

    def test_empty_required_field_rejected(self):
        self.rewrite(self.p3_id, fields={"key_findings": []})
        verdict = self.check([self.p3_id])
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertIn("key_findings", verdict.detail)
        self.assertTrue(verdict.blocks_transition)

    def test_stale_rejected(self):
        self.rewrite(self.p3_id, status="SUPERSEDED")
        verdict = self.check([self.p3_id])
        self.assertEqual(verdict.status, rk.STALE)
        self.assertTrue(verdict.blocks_transition)

    def test_resolution_depends_only_on_supplied_refs_not_a_project_wide_scan(self):
        """A real, valid P3_PRIOR_ART exists on disk (self.p3_id) but is not among the refs
        passed - if resolution scanned the project instead of the supplied refs, this
        would wrongly pass."""
        verdict = self.check(["not-the-real-one"])
        self.assertEqual(verdict.status, rk.MISSING, str(verdict))

    def test_real_transition_p3_to_p4_enforces_prior_art_map(self):
        state_path = nm.methodology_state_path(self.project)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["current_phase"] = "P3"
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.rewrite(self.p3_id, fields={"key_findings": []})
        result = nm.can_transition(self.project, "P4", evidence_refs=[], artifact_refs=[self.p3_id])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("PRIOR_ART_MAP" in r for r in result["blocked_reasons"]))


if __name__ == "__main__":
    unittest.main()
