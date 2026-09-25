"""F2b: GOLDEN_GATES resolver (Rev 2.1 section 2.7) - the Trust Runtime, not any artifact,
is the authoritative owner. Never resolves against artifact_refs at all.

Order (GOLDEN_GATES-ORDER-PRE ruling): zero frozen -> MISSING; more than one frozen ->
INVALID (ambiguous_authoritative_gate), fail-closed rather than picking one; exactly one:
hash mismatch -> INVALID, no binding condition -> INVALID, else VALIDATED. Deliberately no
STALE (no supersession selector exists anywhere in this codebase).
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

import nogap_methodology as nm                                            # noqa: E402
import nogap_required_kinds as rk                                         # noqa: E402
from methodology_fixture_builder import freeze_gate_before_build          # noqa: E402
from test_methodology_build import _ensure_runtime, build_p0_p11_chain    # noqa: E402


class GoldenGatesEnforced(unittest.TestCase):
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
        _ensure_runtime(self.project, "golden gates fixture")
        self.gate_path = self.project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"

    def check(self) -> rk.Verdict:
        (verdict,) = rk.check_required_kinds(self.project, ["GOLDEN_GATES"], [])
        return verdict

    def rewrite_gate(self, **changes) -> None:
        gate = json.loads(self.gate_path.read_text(encoding="utf-8"))
        gate.update(changes)
        self.gate_path.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_mapping_is_golden_gates(self):
        self.assertIsInstance(rk.ENFORCED_KINDS["GOLDEN_GATES"], rk.GoldenGates)
        self.assertNotIn("GOLDEN_GATES", rk.DEFERRED_KINDS)

    def test_partition_guard_holds(self):
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertEqual(len(enforced), 35)
        self.assertEqual(len(deferred), 1)

    # -- no gate at all: draft, never frozen -> MISSING --
    def test_no_frozen_gate_missing(self):
        verdict = self.check()
        self.assertEqual(verdict.status, rk.MISSING)
        self.assertTrue(verdict.blocks_transition)

    # -- exactly one frozen, real binding via forbidden_paths -> VALIDATED --
    def test_single_valid_frozen_gate_with_forbidden_paths_binding_passes(self):
        freeze_gate_before_build(self.project)
        verdict = self.check()
        self.assertEqual(verdict.outcome, rk.VALIDATED, str(verdict))
        self.assertEqual(verdict.status, rk.PASS)
        self.assertFalse(verdict.blocks_transition)

    # -- binding via required_commands alone also satisfies it --
    def test_binding_via_required_commands_alone_passes(self):
        gate = json.loads(self.gate_path.read_text(encoding="utf-8"))
        gate["rules"]["required_commands"] = [f"{sys.executable} -c pass"]
        self.gate_path.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        freeze_gate_before_build(self.project)  # no-op mutation (already bound), just freezes
        verdict = self.check()
        self.assertEqual(verdict.outcome, rk.VALIDATED, str(verdict))

    # -- binding via forbidden_paths alone also satisfies it --
    def test_binding_via_forbidden_paths_alone_passes(self):
        gate = json.loads(self.gate_path.read_text(encoding="utf-8"))
        gate["rules"]["forbidden_paths"] = ["secrets.env"]
        self.gate_path.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        freeze_gate_before_build(self.project)
        verdict = self.check()
        self.assertEqual(verdict.outcome, rk.VALIDATED, str(verdict))

    # -- bad hash: frozen but tampered payload -> INVALID --
    def test_bad_hash_invalid(self):
        freeze_gate_before_build(self.project)
        self.rewrite_gate(hash="sha256:" + "ff" * 32)
        verdict = self.check()
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertIn("hash", verdict.detail)
        self.assertTrue(verdict.blocks_transition)

    # -- frozen, valid hash, but zero binding condition -> INVALID --
    def test_zero_binding_frozen_gate_invalid(self):
        # Freeze WITHOUT going through freeze_gate_before_build - the raw draft gate has
        # empty required_commands/forbidden_paths by default, so this reaches cmd_freeze
        # directly with no binding condition at all.
        import subprocess
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "nogap.py"), "freeze", str(self.project)],
            capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        verdict = self.check()
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertIn("no actual binding condition", verdict.detail)
        self.assertTrue(verdict.blocks_transition)

    # -- more than one frozen gate: ambiguous, fail closed, never pick one --
    def test_multiple_frozen_gates_ambiguous_invalid(self):
        freeze_gate_before_build(self.project)
        gates_dir = self.gate_path.parent
        second = json.loads(self.gate_path.read_text(encoding="utf-8"))
        second["id"] = "gate-0002"
        (gates_dir / "gate-0002.json").write_text(
            json.dumps(second, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verdict = self.check()
        self.assertEqual(verdict.status, rk.INVALID)
        self.assertIn("ambiguous_authoritative_gate", verdict.detail)
        self.assertTrue(verdict.blocks_transition)

    # -- no STALE: a draft/superseded gate beside no frozen one is still MISSING, never STALE --
    def test_draft_only_is_missing_not_stale(self):
        verdict = self.check()
        self.assertEqual(verdict.status, rk.MISSING)
        self.assertNotEqual(verdict.status, rk.STALE)

    # -- refs are never consulted: passing artifact refs changes nothing --
    def test_never_resolves_against_artifact_refs(self):
        freeze_gate_before_build(self.project)
        (verdict_no_refs,) = rk.check_required_kinds(self.project, ["GOLDEN_GATES"], [])
        (verdict_with_refs,) = rk.check_required_kinds(self.project, ["GOLDEN_GATES"], ["not-a-real-ref", "another-one"])
        self.assertEqual(verdict_no_refs.status, verdict_with_refs.status)
        self.assertEqual(verdict_no_refs.outcome, rk.VALIDATED)

    def test_real_transition_p11_to_p12_enforces_golden_gates(self):
        chain = build_p0_p11_chain(self.project, objective="golden gates real transition")
        result = nm.can_transition(self.project, "P12", evidence_refs=[],
                                   artifact_refs=[chain["P11"]["artifact_id"]])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("GOLDEN_GATES" in r for r in result["blocked_reasons"]))

        freeze_gate_before_build(self.project)
        result2 = nm.can_transition(self.project, "P12", evidence_refs=[],
                                    artifact_refs=[chain["P11"]["artifact_id"]])
        self.assertTrue(result2["allowed"], result2["blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
