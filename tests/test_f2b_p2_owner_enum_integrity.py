"""D2-PRE: validate_record() owns P2 risk_level/claim_strength enum integrity.

Creating a P2 artifact with risk_level='catastrophic' was already rejected at CREATE time
via _sync_risk_and_claim_from_p2() -> derive_profile(). But editing risk_level on a stored
record afterward passed validate_record() silently - the enum was never enforced on stored
records, only at creation. This mirrors the existing STRATEGY_OPTIONS check in validate_record
exactly, importing the declared RISK_LEVELS/CLAIM_STRENGTHS sets from nogap_methodology rather
than duplicating them.
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

import nogap_artifacts as na                                                 # noqa: E402
import nogap_methodology as nm                                               # noqa: E402


class P2OwnerEnumIntegrity(unittest.TestCase):
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

        sys.path.insert(0, str(ROOT / "tests"))
        import test_methodology_build as chain
        self.chain = chain.build_p0_p11_chain(self.project)

    def rewrite(self, artifact_id: str, **fields) -> None:
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"].update(fields)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # A1 - a valid P2 artifact created through the real API validates clean
    def test_valid_p2_artifact_has_no_problems(self):
        ref = self.chain["P2"]["artifact_id"]
        record = na.load_artifact(self.project, ref)
        problems = na.validate_record(self.project, record)
        self.assertEqual(problems, [])

    # A2 - tampering risk_level on disk to an undeclared value is caught
    def test_tampered_risk_level_is_rejected(self):
        ref = self.chain["P2"]["artifact_id"]
        self.rewrite(ref, risk_level="catastrophic")
        record = na.load_artifact(self.project, ref)
        problems = na.validate_record(self.project, record)
        self.assertTrue(any("risk_level" in p for p in problems), problems)

    # A3 - tampering claim_strength on disk to an undeclared value is caught
    def test_tampered_claim_strength_is_rejected(self):
        ref = self.chain["P2"]["artifact_id"]
        self.rewrite(ref, claim_strength="extreme")
        record = na.load_artifact(self.project, ref)
        problems = na.validate_record(self.project, record)
        self.assertTrue(any("claim_strength" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
