#!/usr/bin/env python3
"""M7-A acceptance checks for the methodology contracts under methodology/.

Covers every stated acceptance criterion: all P0-P23 represented, all nine macro
phases represented, five loops represented, schema-shaped validation, a version
attached, and both malformed-methodology and unknown-phase-reference failing
closed (never a silent partial load).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from nogap_methodology import (  # noqa: E402
    LOOPS,
    MACRO_PHASES,
    METHODOLOGY_DIR,
    MethodologyValidationError,
    load_methodology,
)


class RealMethodologyContractTests(unittest.TestCase):
    """Checks against the actual, committed methodology/ directory."""

    def setUp(self) -> None:
        self.definition = load_methodology()

    def test_version_is_attached(self) -> None:
        self.assertTrue(self.definition.methodology_id)
        self.assertTrue(self.definition.version)

    def test_all_p0_through_p23_are_represented(self) -> None:
        expected = {f"P{n}" for n in range(24)}
        self.assertEqual(set(self.definition.phases), expected)

    def test_all_nine_macro_phases_are_represented(self) -> None:
        self.assertEqual(set(self.definition.macro_phases), MACRO_PHASES)
        for macro in MACRO_PHASES:
            self.assertTrue(self.definition.phases_in_macro(macro), f"{macro} has no phases")

    def test_all_five_loops_are_represented(self) -> None:
        self.assertEqual(set(self.definition.loops), LOOPS)
        used_loops = {phase.loop for phase in self.definition.phases.values() if phase.loop}
        # repair_loop is reached via failure_transition, not owned by any phase as its primary loop
        self.assertTrue(used_loops)
        self.assertTrue(used_loops.issubset(LOOPS))

    def test_twenty_principles_present_and_classified(self) -> None:
        self.assertEqual(len(self.definition.principles), 20)
        for principle in self.definition.principles.values():
            self.assertIn(principle.cls, {"A", "B", "C"})

    def test_three_profiles_present(self) -> None:
        self.assertEqual(set(self.definition.profiles), {"LIGHT", "STANDARD", "STRICT"})

    def test_every_phase_transition_reference_resolves(self) -> None:
        for phase in self.definition.phases.values():
            for ref in (*phase.allowed_next, *phase.allowed_back_transitions):
                self.assertIn(ref, self.definition.phases, f"{phase.id} references unknown phase {ref}")
            if phase.failure_transition and phase.failure_transition != "REPAIR_LOOP":
                self.assertIn(phase.failure_transition, self.definition.phases)

    def test_p0_only_allows_forward_to_p1(self) -> None:
        p0 = self.definition.get_phase("P0")
        self.assertEqual(p0.allowed_next, ["P1"])

    def test_p2_cannot_enter_build_directly(self) -> None:
        # DEFINE (P2) must not be able to jump straight into BUILD (P12+); RESEARCH/DESIGN/PREPARE
        # (P3-P11) must be traversed first.
        p2 = self.definition.get_phase("P2")
        build_phase_ids = {phase.id for phase in self.definition.phases_in_macro("BUILD")}
        self.assertFalse(set(p2.allowed_next) & build_phase_ids)

    def test_p18_supports_repair_requirement_and_architecture_return_paths(self) -> None:
        p18 = self.definition.get_phase("P18")
        self.assertIn("P13", p18.allowed_back_transitions)  # implementation defect
        self.assertIn("P6", p18.allowed_back_transitions)   # requirement defect
        self.assertIn("P7", p18.allowed_back_transitions)   # architecture defect

    def test_p21_incident_points_to_repair_loop(self) -> None:
        p21 = self.definition.get_phase("P21")
        self.assertEqual(p21.failure_transition, "REPAIR_LOOP")

    def test_p22_can_return_to_an_earlier_phase(self) -> None:
        p22 = self.definition.get_phase("P22")
        self.assertTrue(p22.allowed_back_transitions)

    def test_gate_immutability_principle_is_machine_enforced_class(self) -> None:
        principle = self.definition.get_principle("GP-17")
        self.assertEqual(principle.name, "Never Change the Gate Merely to Make a Result Pass")
        self.assertEqual(principle.cls, "A")

    def test_execution_authority_not_acceptance_authority_is_machine_enforced_class(self) -> None:
        principle = self.definition.get_principle("GP-8")
        self.assertEqual(principle.cls, "A")


class FailClosedTests(unittest.TestCase):
    """Malformed contracts and unknown references must never silently partial-load."""

    def _copy_methodology(self, tmp: Path) -> Path:
        import shutil
        dest = tmp / "methodology"
        shutil.copytree(METHODOLOGY_DIR, dest)
        return dest

    def test_missing_methodology_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            with self.assertRaises(MethodologyValidationError):
                load_methodology(empty)

    def test_malformed_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            (methodology_dir / "methodology.json").write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_methodology(methodology_dir)

    def test_unknown_phase_reference_in_allowed_next_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            p0_path = methodology_dir / "phases" / "p00.json"
            p0 = json.loads(p0_path.read_text(encoding="utf-8"))
            p0["allowed_next"] = ["P99"]
            p0_path.write_text(json.dumps(p0), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError) as ctx:
                load_methodology(methodology_dir)
            self.assertIn("unknown phase", str(ctx.exception))

    def test_unknown_macro_phase_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            p0_path = methodology_dir / "phases" / "p00.json"
            p0 = json.loads(p0_path.read_text(encoding="utf-8"))
            p0["macro_phase"] = "NOT_A_REAL_MACRO_PHASE"
            p0_path.write_text(json.dumps(p0), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_methodology(methodology_dir)

    def test_subphases_list_mismatch_with_files_on_disk_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            top_path = methodology_dir / "methodology.json"
            top = json.loads(top_path.read_text(encoding="utf-8"))
            top["subphases"].remove("P23")
            top_path.write_text(json.dumps(top), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError) as ctx:
                load_methodology(methodology_dir)
            self.assertIn("do not match", str(ctx.exception))

    def test_principles_list_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            top_path = methodology_dir / "methodology.json"
            top = json.loads(top_path.read_text(encoding="utf-8"))
            top["principles"].append("GP-99")
            top_path.write_text(json.dumps(top), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_methodology(methodology_dir)

    def test_duplicate_phase_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            p0 = json.loads((methodology_dir / "phases" / "p00.json").read_text(encoding="utf-8"))
            p0["id"] = "P1"  # collide with the real P1
            (methodology_dir / "phases" / "p00_dup.json").write_text(json.dumps(p0), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError) as ctx:
                load_methodology(methodology_dir)
            self.assertIn("duplicate", str(ctx.exception))

    def test_invalid_principle_class_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            principles_path = methodology_dir / "principles.json"
            data = json.loads(principles_path.read_text(encoding="utf-8"))
            data["principles"][0]["class"] = "Z"
            principles_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_methodology(methodology_dir)

    def test_profile_referencing_unknown_skippable_phase_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            light_path = methodology_dir / "profiles" / "light.json"
            data = json.loads(light_path.read_text(encoding="utf-8"))
            data["skippable_phases"].append("P99")
            light_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_methodology(methodology_dir)

    def test_get_phase_unknown_id_fails_closed(self) -> None:
        definition = load_methodology()
        with self.assertRaises(MethodologyValidationError):
            definition.get_phase("P99")

    def test_get_principle_unknown_id_fails_closed(self) -> None:
        definition = load_methodology()
        with self.assertRaises(MethodologyValidationError):
            definition.get_principle("GP-99")

    def test_get_profile_unknown_id_fails_closed(self) -> None:
        definition = load_methodology()
        with self.assertRaises(MethodologyValidationError):
            definition.get_profile("EXTREME")


if __name__ == "__main__":
    unittest.main()
