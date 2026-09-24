"""F2b D2: RISK_CLASSIFICATION renamed to RISK_LEVEL and moved DEFERRED -> ENFORCED.

Rev 2.1 sec 2.9: an artifact resolves, is ACTIVE, is valid (validate_record), and risk_level
is present and a declared value. The owner enum check (D2-PRE, nogap_artifacts.validate_record)
supplies the "declared value" half; this resolver only asks whether the field is present and
lets validate_record decide validity - it does not re-implement the enum check.
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


class RiskLevelEnforced(unittest.TestCase):
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
        # This helper drives phases whose leaving obligation under test is the artifact
        # verdict, not evidence - a fabricated evidence ref would now be rejected by the
        # real ledger build_p0_p11_chain establishes, for no reason relevant here.
        return can_transition(self.project, phase.allowed_next[0],
                              evidence_refs=[], artifact_refs=refs)

    # -- B1: a real, valid risk_level resolves, VALIDATES, transition allowed ----------------

    def test_valid_risk_level_validates_and_allows_transition(self):
        ref = self.chain["P2"]["artifact_id"]
        verdict = self.verdicts("P2", [ref])["RISK_LEVEL"]
        self.assertEqual(verdict.status, rk.PASS)
        self.assertEqual(verdict.outcome, rk.VALIDATED)
        self.assertFalse(verdict.blocks_transition)
        self.assertTrue(self.forward("P2", [ref])["allowed"])

    # -- B2: tampered risk_level -> BLOCKED, attributable to RISK_LEVEL ----------------------

    def test_tampered_risk_level_blocks_and_is_attributed_to_risk_level(self):
        ref = self.chain["P2"]["artifact_id"]
        self.rewrite(ref, risk_level="catastrophic")
        verdict = self.verdicts("P2", [ref])["RISK_LEVEL"]
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P2", [ref])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("RISK_LEVEL" in r for r in result["blocked_reasons"]))

    # -- B3: regression pin - tampered claim_strength still blocked by CLAIM_STRENGTH --------

    def test_tampered_claim_strength_still_blocks_via_claim_strength_kind(self):
        ref = self.chain["P2"]["artifact_id"]
        self.rewrite(ref, claim_strength="extreme")
        verdict = self.verdicts("P2", [ref])["CLAIM_STRENGTH"]
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P2", [ref])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("CLAIM_STRENGTH" in r for r in result["blocked_reasons"]))

    # -- no phase contract anywhere still names the old kind ----------------------------------

    def test_no_phase_contract_references_the_old_name(self):
        methodology_dir = ROOT / "methodology" / "phases"
        for path in sorted(methodology_dir.glob("p*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("RISK_CLASSIFICATION", data.get("required_artifacts") or [],
                             f"{path.name} required_artifacts still names the old kind")
            self.assertNotIn("RISK_CLASSIFICATION", data.get("required_inputs") or [],
                             f"{path.name} required_inputs still names the old kind")

    def test_p02_declares_the_new_name(self):
        p02 = json.loads((ROOT / "methodology/phases/p02.json").read_text(encoding="utf-8"))
        self.assertIn("RISK_LEVEL", p02["required_artifacts"])

    # -- partition guard: exactly 25 enforced / 12 deferred, RISK_LEVEL moved -----------------

    def test_partition_guard_holds(self):
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(enforced & deferred, set())
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertIn("RISK_LEVEL", enforced)
        self.assertNotIn("RISK_LEVEL", deferred)
        self.assertNotIn("RISK_CLASSIFICATION", enforced | deferred)
        self.assertEqual(len(enforced), 32)
        self.assertEqual(len(deferred), 5)
        self.assertEqual(len(declared), 37)


if __name__ == "__main__":
    unittest.main()
