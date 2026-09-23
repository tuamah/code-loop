"""F2b D1: STRATEGY_DECISION (Rev 2.1 sec 2.8) is ENFORCED, not DEFERRED.

BUILD_VS_BUY_DECISION was renamed to STRATEGY_DECISION because the option set
(`STRATEGY_OPTIONS` in nogap_artifacts.py) is not binary: BUILD, BUY, ADOPT, FORK,
INTEGRATE, HYBRID. A project that selected FORK made a decision the old binary name
could not express - that is the case this suite proves works.
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


class StrategyDecisionEnforced(unittest.TestCase):
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

    def artifact_path(self, artifact_id: str) -> Path:
        return na.artifacts_dir(self.project) / f"{artifact_id}.json"

    def rewrite(self, artifact_id: str, **changes) -> None:
        path = self.artifact_path(artifact_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        for key, value in changes.items():
            if key == "fields":
                record["fields"].update(value)
            else:
                record[key] = value
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
                              evidence_refs=["source-ref-1"], artifact_refs=refs)

    # -- 1: resolves and VALIDATES against a real production artifact -----------------------

    def test_strategy_decision_validates_a_real_artifact(self):
        ref = self.chain["P5"]["artifact_id"]
        verdict = self.verdicts("P5", [ref])["STRATEGY_DECISION"]
        self.assertEqual(verdict.status, rk.PASS)
        self.assertEqual(verdict.outcome, rk.VALIDATED)
        self.assertFalse(verdict.blocks_transition)
        self.assertTrue(self.forward("P5", [ref])["allowed"])

    # -- 2: an out-of-enum value is INVALID --------------------------------------------------

    def test_strategy_outside_the_enum_is_invalid(self):
        ref = self.chain["P5"]["artifact_id"]
        self.rewrite(ref, fields={"selected_strategy": "ACQUIHIRE"})
        verdict = self.verdicts("P5", [ref])["STRATEGY_DECISION"]
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P5", [ref])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("STRATEGY_DECISION" in r for r in result["blocked_reasons"]))

    # -- 3: FORK - a non-binary value - VALIDATES, the whole point of the rename ------------

    def test_fork_strategy_validates(self):
        """The specific case the old binary name BUILD_VS_BUY_DECISION could not express."""
        ref = self.chain["P5"]["artifact_id"]
        self.rewrite(ref, fields={"selected_strategy": "FORK"})
        verdict = self.verdicts("P5", [ref])["STRATEGY_DECISION"]
        self.assertEqual(verdict.status, rk.PASS)
        self.assertEqual(verdict.outcome, rk.VALIDATED)
        self.assertTrue(self.forward("P5", [ref])["allowed"])

    # -- unresolvable gap_analysis_refs fails the artifact's own contract, INVALID ----------

    def test_unresolvable_gap_analysis_refs_is_invalid(self):
        ref = self.chain["P5"]["artifact_id"]
        self.rewrite(ref, fields={"gap_analysis_refs": ["no-such-gap-analysis"]})
        verdict = self.verdicts("P5", [ref])["STRATEGY_DECISION"]
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertTrue(verdict.blocks_transition)

    # -- 4: no phase contract anywhere still names the old kind ------------------------------

    def test_no_phase_contract_references_the_old_name(self):
        methodology_dir = ROOT / "methodology" / "phases"
        for path in sorted(methodology_dir.glob("p*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("BUILD_VS_BUY_DECISION", data.get("required_artifacts") or [],
                             f"{path.name} required_artifacts still names the old kind")
            self.assertNotIn("BUILD_VS_BUY_DECISION", data.get("required_inputs") or [],
                             f"{path.name} required_inputs still names the old kind")

    def test_p5_and_p6_declare_the_new_name(self):
        p05 = json.loads((ROOT / "methodology/phases/p05.json").read_text(encoding="utf-8"))
        p06 = json.loads((ROOT / "methodology/phases/p06.json").read_text(encoding="utf-8"))
        self.assertIn("STRATEGY_DECISION", p05["required_artifacts"])
        self.assertIn("STRATEGY_DECISION", p06["required_inputs"])

    # -- 5: the partition guard still holds ---------------------------------------------------

    def test_partition_guard_holds(self):
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(enforced & deferred, set())
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertIn("STRATEGY_DECISION", enforced)
        self.assertNotIn("STRATEGY_DECISION", deferred)
        self.assertNotIn("BUILD_VS_BUY_DECISION", enforced | deferred)
        self.assertEqual(len(enforced), 24)
        self.assertEqual(len(deferred), 13)


if __name__ == "__main__":
    unittest.main()
