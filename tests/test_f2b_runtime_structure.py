"""F2b: RUNTIME_STRUCTURE resolver (D6, docs/d6-runtime-structure-contract.md).

RUNTIME_STRUCTURE = WholeArtifact("P9_RUNTIME_STRUCTURE") - the exact, already-tested
_check_artifact_kind resolver class used for SCOPE/PRIOR_ART_MAP/GOVERNANCE/etc. No new
resolver code exists: the D6 contract's nested schema/enum/uniqueness/endpoint/version/
ref-syntax/authority-conflict/plane-coverage invariants were already implemented in D6-PRE-B
as nogap_artifacts._check_runtime_structure_schema, wired into validate_record -
_check_artifact_kind already calls validate_record for every WholeArtifact kind, so moving
this mapping from DEFERRED_KINDS to ENFORCED_KINDS activates real enforcement with zero new
resolver logic (see tests/test_d6_pre_b_runtime_structure_schema.py for the schema's own
exhaustive coverage; this file only exercises the mapping and the real transition/kind-check
path, exactly like every other WholeArtifact-shaped F2b test file).

P9 also owns P9_GOVERNANCE (GOVERNANCE, already enforced) and, unlike single-owner phases,
a real P9 transition needs valid refs for both kinds independently - proven below.
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


class RuntimeStructureEnforced(unittest.TestCase):
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
        self.rs_id = self.chain["P9_RUNTIME_STRUCTURE"]["artifact_id"]
        self.gov_id = self.chain["P9"]["artifact_id"]  # P9_GOVERNANCE, keyed "P9" historically

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
        (verdict,) = rk.check_required_kinds(self.project, ["RUNTIME_STRUCTURE"], refs)
        return verdict

    def test_mapping_is_whole_artifact_p9_runtime_structure(self):
        self.assertIsInstance(rk.ENFORCED_KINDS["RUNTIME_STRUCTURE"], rk.WholeArtifact)
        self.assertEqual(rk.ENFORCED_KINDS["RUNTIME_STRUCTURE"].artifact_type, "P9_RUNTIME_STRUCTURE")
        self.assertNotIn("RUNTIME_STRUCTURE", rk.DEFERRED_KINDS)

    def test_partition_guard_holds(self):
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertEqual(len(enforced), 35)
        self.assertEqual(len(deferred), 2)
        self.assertIn("RUNTIME_STRUCTURE", enforced)
        self.assertNotIn("RUNTIME_STRUCTURE", deferred)

    def test_valid_minimal_record_passes(self):
        verdict = self.check([self.rs_id])
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
        self.assertIn("P9_RUNTIME_STRUCTURE", verdict.detail)
        self.assertTrue(verdict.blocks_transition)

    def test_invalid_schema_rejected_through_the_real_kind_check(self):
        # Proves _check_artifact_kind's validate_record call actually reaches D6-PRE-B's
        # schema validator - not just that the mapping exists.
        self.rewrite(self.rs_id, fields={"runtime_structure_version": "2"})
        verdict = self.check([self.rs_id])
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertIn("runtime_structure_version", verdict.detail)
        self.assertTrue(verdict.blocks_transition)

    def test_dangling_boundary_endpoint_rejected_through_the_real_kind_check(self):
        self.rewrite(self.rs_id, fields={
            "boundaries": [{
                "boundary_id": "b1", "source_component_id": "ghost",
                "target_component_id": "ghost2", "boundary_type": "state",
                "permitted_flows": ["x"], "enforcement_status": "DOCUMENTED_ONLY",
                "enforcement_ref": None,
            }],
        })
        verdict = self.check([self.rs_id])
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertIn("does not resolve", verdict.detail)

    def test_stale_rejected(self):
        self.rewrite(self.rs_id, status="SUPERSEDED")
        verdict = self.check([self.rs_id])
        self.assertEqual(verdict.status, rk.STALE)
        self.assertTrue(verdict.blocks_transition)

    def test_resolution_depends_only_on_supplied_refs_not_a_project_wide_scan(self):
        """A real, valid P9_RUNTIME_STRUCTURE exists on disk (self.rs_id) but is not among
        the refs passed - if resolution scanned the project instead, this would wrongly pass."""
        verdict = self.check(["not-the-real-one"])
        self.assertEqual(verdict.status, rk.MISSING, str(verdict))

    def test_real_transition_p9_to_p10_enforces_runtime_structure(self):
        state_path = nm.methodology_state_path(self.project)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["current_phase"] = "P9"
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.rewrite(self.rs_id, fields={"runtime_structure_version": "2"})
        result = nm.can_transition(self.project, "P10", evidence_refs=[],
                                   artifact_refs=[self.rs_id, self.gov_id])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("RUNTIME_STRUCTURE" in r for r in result["blocked_reasons"]))

    def test_real_transition_independent_of_governance(self):
        # Both kinds are enforced on P9 now, but independently - a broken RUNTIME_STRUCTURE
        # blocks for its own reason even though GOVERNANCE (a separate, valid ref) resolves
        # fine, and the transition succeeds once both are valid.
        state_path = nm.methodology_state_path(self.project)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["current_phase"] = "P9"
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.rewrite(self.rs_id, fields={"runtime_structure_version": "2"})
        blocked = nm.can_transition(self.project, "P10", evidence_refs=[],
                                    artifact_refs=[self.rs_id, self.gov_id])
        self.assertFalse(blocked["allowed"])
        self.assertTrue(any("RUNTIME_STRUCTURE" in r for r in blocked["blocked_reasons"]))
        self.assertFalse(any("GOVERNANCE" in r and "RUNTIME_STRUCTURE" not in r
                             for r in blocked["blocked_reasons"]))

        self.rewrite(self.rs_id, fields={"runtime_structure_version": "1"})
        allowed = nm.can_transition(self.project, "P10", evidence_refs=[],
                                    artifact_refs=[self.rs_id, self.gov_id])
        self.assertTrue(allowed["allowed"], allowed["blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
