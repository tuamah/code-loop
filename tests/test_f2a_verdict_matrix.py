"""F2a-Core adversarial matrix: every verdict, reached for real, proven by its EFFECT.

Two rules this suite holds itself to, because T4 in the previous item passed a suite that
proved less than it claimed:

1. **Every verdict is reachable through a real project.** No verdict is produced by calling
   an internal branch with hand-built objects. Each is provoked the way a project would
   provoke it - a tampered artifact, a superseded record, a path outside the tree - so a
   verdict that has become unreachable in practice fails here rather than passing quietly.

2. **Every verdict is asserted by its EFFECT on the transition**, not by the name on an
   object. A test that checks `verdict.status == "STALE"` proves the label was computed; it
   proves nothing about whether a stale artifact can still close out a phase. So each case
   below also asserts `can_transition(...)["allowed"]` and, where it blocks, that the reason
   actually names the kind.

The control case (VALIDATED) is not decoration: without it, a rule that blocks everything
would satisfy every other row in the table.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_artifacts as na                                                 # noqa: E402
import nogap_methodology as nm                                               # noqa: E402
import nogap_required_kinds as rk                                            # noqa: E402
from nogap_methodology import can_transition                                 # noqa: E402


class Matrix(unittest.TestCase):
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

    # -- helpers ---------------------------------------------------------------------------

    def at(self, phase_id: str) -> None:
        path = nm.methodology_state_path(self.project)
        state = json.loads(path.read_text(encoding="utf-8"))
        state["current_phase"] = phase_id
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

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
        self.at(phase_id)
        phase = nm.load_methodology().get_phase(phase_id)
        # None of the phases this helper drives (P1, P4, P13) require evidence to leave,
        # so no evidence_refs are supplied - the matrix below is exclusively about artifact
        # verdicts, and a fabricated evidence ref would now be rejected by the real ledger
        # build_p0_p11_chain establishes, for no reason relevant to what this test checks.
        return can_transition(self.project, phase.allowed_next[0],
                              evidence_refs=[], artifact_refs=refs)

    # -- VALIDATED (control) ----------------------------------------------------------------

    def test_validated_allows_the_transition(self):
        """Control. Without it, a rule that blocked everything would pass every other row."""
        ref = self.chain["P4"]["artifact_id"]
        verdict = self.verdicts("P4", [ref])["GAP_ANALYSIS"]
        self.assertEqual(verdict.status, rk.PASS)
        self.assertEqual(verdict.outcome, rk.VALIDATED)
        self.assertFalse(verdict.blocks_transition)
        self.assertTrue(self.forward("P4", [ref])["allowed"])

    # -- MISSING -----------------------------------------------------------------------------

    def test_missing_blocks_the_transition(self):
        verdict = self.verdicts("P4", ["no-such-artifact"])["GAP_ANALYSIS"]
        self.assertEqual(verdict.status, rk.MISSING)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P4", ["no-such-artifact"])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("GAP_ANALYSIS" in r for r in result["blocked_reasons"]))

    # -- WRONG_TYPE ---------------------------------------------------------------------------

    def test_wrong_type_blocks_the_transition(self):
        """A perfectly valid artifact - of the wrong phase. The old rule accepted this."""
        wrong = self.chain["P0"]["artifact_id"]
        verdict = self.verdicts("P4", [wrong])["GAP_ANALYSIS"]
        self.assertEqual(verdict.status, rk.WRONG_TYPE)
        self.assertIn("P0_PROJECT_INTENT", verdict.detail)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P4", [wrong])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("WRONG_TYPE" in r for r in result["blocked_reasons"]))

    # -- INVALID -------------------------------------------------------------------------------

    def test_invalid_blocks_the_transition(self):
        """Right type, right id, contract not satisfied - an empty required field."""
        ref = self.chain["P4"]["artifact_id"]
        self.rewrite(ref, fields={"gaps": []})
        verdict = self.verdicts("P4", [ref])["GAP_ANALYSIS"]
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P4", [ref])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("INVALID" in r for r in result["blocked_reasons"]))

    def test_a_field_level_kind_fails_when_its_own_field_is_empty(self):
        """The distinction F2a exists for: the TYPE is satisfied, the KIND is not.

        P1_SCOPE stays structurally valid; only problem_statement is emptied. Under a
        "the artifact must be of this phase's type" rule this would pass.
        """
        ref = self.chain["P1"]["artifact_id"]
        self.rewrite(ref, fields={"problem_statement": "   "})
        verdict = self.verdicts("P1", [ref])["PROBLEM_STATEMENT"]
        self.assertTrue(verdict.blocks_transition)
        self.assertIn("problem_statement", verdict.detail)

    # -- STALE ----------------------------------------------------------------------------------

    def test_stale_blocks_the_transition(self):
        """It was real once, which is exactly why it has to be excluded by name."""
        ref = self.chain["P4"]["artifact_id"]
        self.rewrite(ref, status="SUPERSEDED")
        verdict = self.verdicts("P4", [ref])["GAP_ANALYSIS"]
        self.assertEqual(verdict.status, rk.STALE)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P4", [ref])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("STALE" in r for r in result["blocked_reasons"]))

    # -- OUT_OF_BOUNDS ----------------------------------------------------------------------------

    def test_out_of_bounds_blocks_the_transition(self):
        """P13 declares PATCH, a file kind. A path outside the project is not a satisfied
        requirement however real the file is."""
        outside = Path(tempfile.gettempdir()) / "f2a-outside-the-project.patch"
        outside.write_text("diff --git a/x b/x\n", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        verdict = self.verdicts("P13", [str(outside)])["PATCH"]
        self.assertEqual(verdict.status, rk.OUT_OF_BOUNDS)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P13", [str(outside)])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("OUT_OF_BOUNDS" in r for r in result["blocked_reasons"]))

    def test_a_patch_inside_the_project_is_validated(self):
        """The same kind, satisfied - so OUT_OF_BOUNDS is about location, not about files."""
        inside = self.project / "change.patch"
        inside.write_text("diff --git a/x b/x\n", encoding="utf-8")
        self.assertEqual(self.verdicts("P13", ["change.patch"])["PATCH"].status, rk.PASS)

    # -- DEFERRED ---------------------------------------------------------------------------------

    def test_deferred_does_not_block_and_never_reads_as_pass(self):
        """P8 declares ADR (enforced), COST_MODEL (deferred). F2b's METRICS moved P10's own
        former example, BASELINE(P10)/METRICS, to enforced, so this now uses the next
        still-deferred kind with an enforced sibling."""
        ref = self.chain["P8"]["artifact_id"]
        found = self.verdicts("P8", [ref])
        self.assertEqual(found["COST_MODEL"].status, rk.DEFERRED)
        self.assertEqual(found["COST_MODEL"].outcome, rk.DEFERRED_OUTCOME)
        self.assertNotEqual(found["COST_MODEL"].status, rk.PASS)
        self.assertNotEqual(found["COST_MODEL"].outcome, rk.VALIDATED)
        self.assertFalse(found["COST_MODEL"].blocks_transition)
        self.assertTrue(self.forward("P8", [ref])["allowed"])

    def test_deferred_is_visible_in_the_report_under_its_own_name(self):
        ref = self.chain["P8"]["artifact_id"]
        phase = nm.load_methodology().get_phase("P8")
        text = rk.report(rk.check_required_kinds(
            self.project, list(phase.required_artifacts), [ref]))
        self.assertIn("COST_MODEL: DEFERRED", text)
        self.assertIn("ADR: VALIDATED", text)

    def test_a_deferred_kind_cannot_be_satisfied_by_garbage_either(self):
        """DEFERRED is undecided, so it neither blocks nor endorses - and the ENFORCED kinds
        beside it still do their job, which is what keeps the phase honest."""
        result = self.forward("P10", ["not-an-artifact"])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("BASELINE" in r for r in result["blocked_reasons"]))

    # -- UNMAPPED ------------------------------------------------------------------------------------

    def test_unmapped_blocks_the_transition(self):
        """The real scenario: someone adds a required kind to a phase contract and does not
        map it. Simulated by loading the real methodology and adding the kind to a real phase
        contract, so the whole transition path runs - not by calling the branch directly."""
        definition = nm.load_methodology()
        phase = definition.get_phase("P4")
        phase.required_artifacts = list(phase.required_artifacts) + ["A_BRAND_NEW_KIND"]
        ref = self.chain["P4"]["artifact_id"]
        with mock.patch.object(nm, "load_methodology", return_value=definition):
            found = self.verdicts("P4", [ref])
            self.assertEqual(found["A_BRAND_NEW_KIND"].status, rk.UNMAPPED)
            self.assertTrue(found["A_BRAND_NEW_KIND"].blocks_transition)
            result = self.forward("P4", [ref])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("UNMAPPED" in r for r in result["blocked_reasons"]))

    # -- the matrix is complete -------------------------------------------------------------------

    def test_every_verdict_status_is_exercised_by_this_suite(self):
        """Guards the matrix itself: a status nobody provokes is a status nobody tests."""
        import ast
        source = Path(__file__).read_text(encoding="utf-8")
        used = {n.attr for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == "rk"}
        for status in ("PASS", "MISSING", "WRONG_TYPE", "INVALID", "STALE",
                       "OUT_OF_BOUNDS", "UNMAPPED", "DEFERRED"):
            self.assertIn(status, used, f"no test in this matrix provokes {status}")


if __name__ == "__main__":
    unittest.main()


class PartitionGuard(unittest.TestCase):
    """ENFORCED and DEFERRED must exactly partition what the phase contracts declare.

        ENFORCED ∩ DEFERRED = ∅
        ENFORCED ∪ DEFERRED = DECLARED

    Read from methodology/phases/*.json at test time, not from a copy. Adding a
    required_artifacts entry to any phase contract without deciding its meaning breaks CI
    here - which is the point: the alternative is a generic "ignore what we do not
    recognize", and that is how a closed map stops being closed.
    """

    def setUp(self):
        self.declared = rk.declared_required_kinds()
        self.enforced = set(rk.ENFORCED_KINDS)
        self.deferred = set(rk.DEFERRED_KINDS)

    def test_the_two_sets_are_disjoint(self):
        self.assertEqual(self.enforced & self.deferred, set(),
                         "a kind is both enforced and deferred")

    def test_every_declared_kind_is_covered(self):
        self.assertEqual(self.declared - (self.enforced | self.deferred), set(),
                         "a phase contract declares a kind with no decided meaning")

    def test_nothing_is_mapped_that_is_not_declared(self):
        self.assertEqual((self.enforced | self.deferred) - self.declared, set(),
                         "the map carries a kind no phase contract declares")

    def test_the_guard_reads_the_real_contracts(self):
        """Guards the guard: if declared_required_kinds() returned nothing, every assertion
        above would pass vacuously forever."""
        self.assertGreater(len(self.declared), 20)
        self.assertIn("PROJECT_INTENT", self.declared)
        self.assertIn("PATCH", self.declared)

    def test_every_enforced_kind_has_a_known_resolver_class(self):
        known = (rk.ArtifactField, rk.WholeArtifact, rk.ProjectFile,
                 rk.LedgerEvidence, rk.LifecycleRecord, rk.EvidenceBundle, rk.ReviewVerdict)
        for kind, spec in rk.ENFORCED_KINDS.items():
            self.assertIsInstance(spec, known, f"{kind} has no known resolver class")

    def test_every_artifact_mapping_names_a_real_artifact_type(self):
        """No mapping may point at a type that does not exist, and no ArtifactField may
        name a field its type does not declare - the map is checked against the
        declarations it claims to come from."""
        for kind, spec in rk.ENFORCED_KINDS.items():
            if isinstance(spec, (rk.ArtifactField, rk.WholeArtifact)):
                self.assertIn(spec.artifact_type, na.ARTIFACT_TYPES, kind)
            if isinstance(spec, rk.ArtifactField):
                declared = na.ARTIFACT_TYPES[spec.artifact_type]["required_fields"]
                self.assertIn(spec.field, declared,
                              f"{kind} names {spec.field!r}, which {spec.artifact_type} "
                              f"does not declare")
