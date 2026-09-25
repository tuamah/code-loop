"""F2b: COST_MODEL resolver (GP-13, COST-MODEL-CLASSIFICATION-PRE).

COST_MODEL = ArtifactField("P8_ADR", "expected_cost") - the same field-name-mismatch shape
D3's BENCHMARK_PROTOCOL and TEST_PLAN already established. No new artifact type: P8's own
exit_gate says "covers_at_least_one_dimension" (never "covers every GP-13 dimension"), and
expected_cost is a real, unconditionally-required field on P8_ADR at every profile today -
vendor_lock_in (STRICT-only) and GP-13's richer dimensions (token/provider pricing, budgets,
runtime cost tracking - none of which exist anywhere in this codebase) stay explicitly out of
scope. This closes F2b entirely: DEFERRED_KINDS is now empty.
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


class CostModelEnforced(unittest.TestCase):
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
        self.p8_id = self.chain["P8"]["artifact_id"]

    def rewrite(self, artifact_id: str, **changes) -> None:
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        for key, value in changes.items():
            if key == "fields":
                record["fields"].update(value)
            else:
                record[key] = value
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
        return nm.can_transition(self.project, phase.allowed_next[0],
                                 evidence_refs=[], artifact_refs=refs)

    # -- mapping / partition --

    def test_mapping_is_artifact_field_p8_adr_expected_cost(self):
        spec = rk.ENFORCED_KINDS["COST_MODEL"]
        self.assertIsInstance(spec, rk.ArtifactField)
        self.assertEqual(spec.artifact_type, "P8_ADR")
        self.assertEqual(spec.field, "expected_cost")
        self.assertNotIn("COST_MODEL", rk.DEFERRED_KINDS)

    def test_partition_guard_holds_f2b_fully_closed(self):
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertEqual(len(enforced), 36)
        self.assertEqual(len(deferred), 0)
        self.assertEqual(deferred, set())

    # -- valid, real expected_cost resolves, VALIDATES, transition allowed --

    def test_valid_expected_cost_validates_and_allows_transition(self):
        verdict = self.verdicts("P8", [self.p8_id])["COST_MODEL"]
        self.assertEqual(verdict.status, rk.PASS)
        self.assertEqual(verdict.outcome, rk.VALIDATED)
        self.assertFalse(verdict.blocks_transition)
        self.assertTrue(self.forward("P8", [self.p8_id])["allowed"])

    # -- MISSING - ref does not resolve at all --

    def test_missing_rejected(self):
        verdict = self.verdicts("P8", ["no-such-artifact"])["COST_MODEL"]
        self.assertEqual(verdict.status, rk.MISSING)
        self.assertTrue(verdict.blocks_transition)

    # -- WRONG_TYPE - a real artifact of a different type --

    def test_wrong_type_rejected(self):
        wrong = self.chain["P0"]["artifact_id"]
        verdict = self.verdicts("P8", [wrong])["COST_MODEL"]
        self.assertEqual(verdict.status, rk.WRONG_TYPE)
        self.assertIn("P8_ADR", verdict.detail)
        self.assertTrue(verdict.blocks_transition)

    # -- INVALID - empty expected_cost, blocks and is attributed by name --

    def test_empty_expected_cost_blocks_and_is_attributed(self):
        self.rewrite(self.p8_id, fields={"expected_cost": ""})
        verdict = self.verdicts("P8", [self.p8_id])["COST_MODEL"]
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P8", [self.p8_id])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("COST_MODEL" in r for r in result["blocked_reasons"]))

    # -- missing field entirely - fails, never silently passes --

    def test_missing_expected_cost_field_fails(self):
        self.drop_field(self.p8_id, "expected_cost")
        verdict = self.verdicts("P8", [self.p8_id])["COST_MODEL"]
        self.assertIn(verdict.status, (rk.INVALID, rk.MISSING))
        self.assertNotEqual(verdict.status, rk.PASS)
        self.assertTrue(verdict.blocks_transition)

    # -- STALE --

    def test_stale_rejected(self):
        self.rewrite(self.p8_id, status="SUPERSEDED")
        verdict = self.verdicts("P8", [self.p8_id])["COST_MODEL"]
        self.assertEqual(verdict.status, rk.STALE)
        self.assertTrue(verdict.blocks_transition)

    # -- independence from ADR: both kinds live on P8_ADR, resolved by the same record, but
    #    each checks its own declared field independently. --

    def test_cost_model_independent_of_adr_whole_record_validity(self):
        # Breaking a DIFFERENT required field (consequences) invalidates the whole record via
        # validate_record - which _check_artifact_kind consults before the field-specific
        # check, so COST_MODEL correctly reports INVALID too (the record it would resolve to
        # is not valid at all), same as ADR. This is not a coupling bug: both kinds share one
        # underlying artifact type by design (ArtifactField), so a broken record breaks every
        # kind resolved from it - independence here means each kind is checked on its own
        # terms against a record that IS valid, not that a wholly invalid record magically
        # passes one kind and not the other.
        self.rewrite(self.p8_id, fields={"consequences": []})
        found = self.verdicts("P8", [self.p8_id])
        self.assertEqual(found["ADR"].status, rk.INVALID)
        self.assertEqual(found["COST_MODEL"].status, rk.INVALID)

    def test_real_transition_p8_to_p9_enforces_cost_model(self):
        self.rewrite(self.p8_id, fields={"expected_cost": ""})
        result = self.forward("P8", [self.p8_id])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("COST_MODEL" in r for r in result["blocked_reasons"]))


if __name__ == "__main__":
    unittest.main()
