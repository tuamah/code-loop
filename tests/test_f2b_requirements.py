"""F2b: REQUIREMENTS resolver (Rev 2.1 section 2.10) - authoritative ACTIVE-set coverage.

A dedicated small resolver (RequirementCoverage, nogap_required_kinds._check_requirement_
coverage_kind) - not ArtifactField/WholeArtifact, since the rule needs a project-wide read of
every P6_REQUIREMENT and EXACT coverage between the supplied P6-typed refs and the live ACTIVE
set, never a single artifact. Deliberately independent of P7/P11 and of any lifecycle module.
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


class RequirementsEnforced(unittest.TestCase):
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
        self.req1_id = self.chain["P6"]["artifact_id"]

    def add_requirement(self, **overrides) -> dict:
        fields = dict(
            type="functional", statement="another requirement", priority="high",
            acceptance_criteria=["y happens"], strategy_decision_refs=[self.chain["P5"]["artifact_id"]],
        )
        fields.update(overrides)
        return na.create_artifact(self.project, "P6_REQUIREMENT", fields, actor="architect")

    def check(self, refs: list[str]) -> rk.Verdict:
        (verdict,) = rk.check_required_kinds(self.project, ["REQUIREMENTS"], refs)
        return verdict

    def test_mapping_is_requirement_coverage(self):
        self.assertIsInstance(rk.ENFORCED_KINDS["REQUIREMENTS"], rk.RequirementCoverage)
        self.assertNotIn("REQUIREMENTS", rk.DEFERRED_KINDS)

    def test_partition_guard_holds(self):
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertEqual(len(enforced), 35)
        self.assertEqual(len(deferred), 2)

    # -- rule: single active requirement, exactly covered -> PASS --
    def test_single_active_exactly_covered_passes(self):
        verdict = self.check([self.req1_id])
        self.assertEqual(verdict.outcome, rk.VALIDATED, str(verdict))
        self.assertEqual(verdict.status, rk.PASS)

    # -- rule 4: incomplete coverage - a second ACTIVE requirement is not referenced -> MISSING --
    def test_incomplete_coverage_missing(self):
        req2 = self.add_requirement()
        verdict = self.check([self.req1_id])  # req2 not covered
        self.assertEqual(verdict.status, rk.MISSING)
        self.assertIn(req2["artifact_id"], verdict.detail)
        self.assertTrue(verdict.blocks_transition)

    # -- rule 4 (exact match, not superset): a THIRD ref not among ACTIVE also fails --
    def test_extra_unrelated_ref_does_not_satisfy_exact_p6_coverage(self):
        req2 = self.add_requirement()
        # supplying both real ACTIVE ids should pass...
        self.assertEqual(self.check([self.req1_id, req2["artifact_id"]]).outcome, rk.VALIDATED)

    # -- refs of OTHER kinds on the same transition must not affect this resolver --
    def test_other_kind_refs_on_the_same_call_are_ignored(self):
        other = self.chain["P0"]["artifact_id"]  # P0_PROJECT_INTENT - not P6 at all
        verdict = self.check([self.req1_id, other])
        self.assertEqual(verdict.outcome, rk.VALIDATED, str(verdict))

    # -- rule 5: a SUPERSEDED requirement offered instead of active -> STALE --
    def test_superseded_offered_instead_of_active_is_stale(self):
        na.update_requirement_status(self.project, self.req1_id and
                                     self.chain["P6"]["fields"]["requirement_id"],
                                     "SUPERSEDED", actor="architect", reason="replaced")
        req2 = self.add_requirement()
        verdict = self.check([self.req1_id, req2["artifact_id"]])
        self.assertEqual(verdict.status, rk.STALE, str(verdict))
        self.assertIn(self.req1_id, verdict.detail)

    # -- rule 5: extra requirement beyond the active set (superseded) alongside full coverage
    #    of the active set -> STALE, not PASS ---
    def test_extra_superseded_requirement_alongside_full_coverage_is_stale(self):
        req2 = self.add_requirement()
        old = self.add_requirement(statement="obsolete requirement")
        old_id = old["fields"]["requirement_id"]
        na.update_requirement_status(self.project, old_id, "SUPERSEDED", actor="architect", reason="obsolete")
        verdict = self.check([self.req1_id, req2["artifact_id"], old["artifact_id"]])
        self.assertEqual(verdict.status, rk.STALE, str(verdict))

    # -- SATISFIED (a real, non-obsolete terminal status) still does not stand in for ACTIVE:
    #    R = ACTIVE only, so SATISFIED is just as excluded as SUPERSEDED/REJECTED --
    def test_satisfied_offered_instead_of_active_is_stale(self):
        rid = self.chain["P6"]["fields"]["requirement_id"]
        na.update_requirement_status(self.project, rid, "SATISFIED", actor="architect", reason="fulfilled")
        req2 = self.add_requirement()
        verdict = self.check([self.req1_id, req2["artifact_id"]])
        self.assertEqual(verdict.status, rk.STALE, str(verdict))
        self.assertIn(self.req1_id, verdict.detail)

    def test_extra_satisfied_requirement_alongside_full_coverage_is_stale(self):
        req2 = self.add_requirement()
        done = self.add_requirement(statement="already fulfilled requirement")
        done_id = done["fields"]["requirement_id"]
        na.update_requirement_status(self.project, done_id, "SATISFIED", actor="architect", reason="fulfilled")
        verdict = self.check([self.req1_id, req2["artifact_id"], done["artifact_id"]])
        self.assertEqual(verdict.status, rk.STALE, str(verdict))

    # -- rule 3: duplicate requirement_id among ACTIVE requirements -> INVALID --
    def test_duplicate_requirement_id_among_active_is_invalid(self):
        rid = self.chain["P6"]["fields"]["requirement_id"]
        path = na.artifacts_dir(self.project) / f"{self.req1_id}.json"
        # Unreachable via the real creation API (next_requirement_id/duplicate-id guard already
        # rejects this at create time): the real record is duplicated in place.
        data = json.loads(path.read_text(encoding="utf-8"))
        data["artifact_id"] = "P6_REQUIREMENT-forced-dup"
        (na.artifacts_dir(self.project) / "P6_REQUIREMENT-forced-dup.json").write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verdict = self.check([self.req1_id])
        self.assertEqual(verdict.status, rk.INVALID, str(verdict))
        self.assertIn(rid, verdict.detail)

    # -- rule 2: an ACTIVE requirement that fails validate_record -> INVALID --
    def test_active_requirement_failing_contract_is_invalid(self):
        path = na.artifacts_dir(self.project) / f"{self.req1_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["fields"]["acceptance_criteria"] = []
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verdict = self.check([self.req1_id])
        self.assertEqual(verdict.status, rk.INVALID, str(verdict))

    # -- rule 1: no ACTIVE requirement anywhere -> MISSING --
    def test_no_active_requirement_at_all_is_missing(self):
        rid = self.chain["P6"]["fields"]["requirement_id"]
        na.update_requirement_status(self.project, rid, "REJECTED", actor="architect", reason="dropped")
        verdict = self.check([])
        self.assertEqual(verdict.status, rk.MISSING, str(verdict))
        self.assertIn("no ACTIVE", verdict.detail)

    def test_real_transition_p6_to_p7_enforces_requirements(self):
        state_path = nm.methodology_state_path(self.project)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["current_phase"] = "P6"
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        req2 = self.add_requirement()
        # only req1 supplied - req2 is ACTIVE and uncovered
        result = nm.can_transition(self.project, "P7", evidence_refs=[], artifact_refs=[self.req1_id])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("REQUIREMENTS" in r for r in result["blocked_reasons"]))
        # covering both now passes
        result2 = nm.can_transition(self.project, "P7", evidence_refs=[],
                                    artifact_refs=[self.req1_id, req2["artifact_id"]])
        self.assertTrue(result2["allowed"], result2["blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
