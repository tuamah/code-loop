"""F2b D3: BENCHMARK_PROTOCOL moved DEFERRED -> ENFORCED, bound via P10's declared
artifact_field_bindings (Rev 2.1 sec 2.4).

Rev 2.1 sec 2.4: an artifact resolves, is ACTIVE, is valid (validate_record), and
measurement_procedure is present and non-empty. Unlike D1/D2 this kind does not repeat a
declared field name (P10 requires BASELINE, BENCHMARK_PROTOCOL, METRICS - three kinds sharing
one P10_BASELINE artifact), so the resolver mapping is proven correct against an explicit
declaration in the phase contract (artifact_field_bindings) rather than against name
similarity. The guard below is that proof: a resolver mapping with no matching declaration, or
a declaration the resolver disagrees with, must fail - "the whole point of Part A", per spec.
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


class BenchmarkProtocolEnforced(unittest.TestCase):
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
        # This helper drives phases whose leaving obligation under test is the artifact
        # verdict, not evidence - a fabricated evidence ref would now be rejected by the
        # real ledger build_p0_p11_chain establishes, for no reason relevant here.
        return can_transition(self.project, phase.allowed_next[0],
                              evidence_refs=[], artifact_refs=refs)

    # -- T1: a real, valid measurement_procedure resolves, VALIDATES, transition allowed -----

    def test_valid_measurement_procedure_validates_and_allows_transition(self):
        ref = self.chain["P10"]["artifact_id"]
        verdict = self.verdicts("P10", [ref])["BENCHMARK_PROTOCOL"]
        self.assertEqual(verdict.status, rk.PASS)
        self.assertEqual(verdict.outcome, rk.VALIDATED)
        self.assertFalse(verdict.blocks_transition)
        self.assertTrue(self.forward("P10", [ref])["allowed"])

    # -- T2: empty measurement_procedure -> BLOCKED, attributable to BENCHMARK_PROTOCOL -------

    def test_empty_measurement_procedure_blocks_and_is_attributed(self):
        ref = self.chain["P10"]["artifact_id"]
        self.rewrite(ref, measurement_procedure="")
        verdict = self.verdicts("P10", [ref])["BENCHMARK_PROTOCOL"]
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertTrue(verdict.blocks_transition)
        result = self.forward("P10", [ref])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("BENCHMARK_PROTOCOL" in r for r in result["blocked_reasons"]))

    # -- T3: missing measurement_procedure -> fails, not silently passed ----------------------

    def test_missing_measurement_procedure_fails(self):
        ref = self.chain["P10"]["artifact_id"]
        self.drop_field(ref, "measurement_procedure")
        verdict = self.verdicts("P10", [ref])["BENCHMARK_PROTOCOL"]
        # a valid P10_BASELINE with no measurement_procedure fails validate_record itself
        # (the artifact type requires it), so the kind fails INVALID, not MISSING/PASS.
        self.assertIn(verdict.status, (rk.INVALID, rk.MISSING))
        self.assertNotEqual(verdict.status, rk.PASS)
        self.assertTrue(verdict.blocks_transition)

    # -- regression pin: existing "manual timing" fixtures still validate ---------------------

    def test_existing_manual_timing_fixture_still_validates(self):
        ref = self.chain["P10"]["artifact_id"]
        record = json.loads((na.artifacts_dir(self.project) / f"{ref}.json").read_text())
        self.assertEqual(record["fields"]["measurement_procedure"], "manual timing")
        verdict = self.verdicts("P10", [ref])["BENCHMARK_PROTOCOL"]
        self.assertEqual(verdict.status, rk.PASS)

    # -- no longer DEFERRED -------------------------------------------------------------------

    def test_benchmark_protocol_no_longer_deferred(self):
        self.assertNotIn("BENCHMARK_PROTOCOL", rk.DEFERRED_KINDS)
        self.assertIn("BENCHMARK_PROTOCOL", rk.ENFORCED_KINDS)


class DeclarationResolverAgreementGuard(unittest.TestCase):
    """T4 / M4: the ENFORCED_KINDS mapping must agree with the phase contract's own
    artifact_field_bindings declaration for every kind the contract binds.

    A correct resolver mapping paired with a wrong (or absent) declaration must be caught -
    without this guard the artifact_field_bindings primitive from Part A is decoration.
    """

    def test_every_declared_binding_matches_its_enforced_kind_resolver(self):
        methodology = nm.load_methodology()
        checked = 0
        for phase in methodology.phases.values():
            for kind, binding in phase.artifact_field_bindings.items():
                checked += 1
                spec = rk.ENFORCED_KINDS.get(kind)
                self.assertIsInstance(
                    spec, rk.ArtifactField,
                    f"{kind} is declared as an artifact_field_binding in {phase.id} but "
                    f"ENFORCED_KINDS does not map it through ArtifactField",
                )
                self.assertEqual(
                    (spec.artifact_type, spec.field),
                    (binding["artifact_type"], binding["field"]),
                    f"{kind}: ENFORCED_KINDS resolver ({spec.artifact_type}, {spec.field}) "
                    f"disagrees with the phase contract's declared binding "
                    f"({binding['artifact_type']}, {binding['field']})",
                )
        self.assertGreaterEqual(checked, 1, "no artifact_field_bindings declared anywhere - "
                                            "this guard would pass vacuously")

    def test_benchmark_protocol_binding_matches(self):
        phase = nm.load_methodology().get_phase("P10")
        binding = phase.artifact_field_bindings["BENCHMARK_PROTOCOL"]
        spec = rk.ENFORCED_KINDS["BENCHMARK_PROTOCOL"]
        self.assertEqual(spec.artifact_type, binding["artifact_type"])
        self.assertEqual(spec.field, binding["field"])


class PartitionCountsPinned(unittest.TestCase):
    def test_partition_is_35_enforced_2_deferred_37_declared(self):
        self.assertEqual(len(rk.ENFORCED_KINDS), 35)
        self.assertEqual(len(rk.DEFERRED_KINDS), 1)
        self.assertEqual(len(rk.declared_required_kinds()), 36)


if __name__ == "__main__":
    unittest.main()
