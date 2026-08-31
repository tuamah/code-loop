#!/usr/bin/env python3
"""M7-B acceptance checks: Project Intent + Adaptive Depth.

Covers the explicitly required scenarios: deterministic profile derivation
across intent/risk/claim-strength combinations, disclosed derivation (never
hidden), explicit phase-level escalation, rejected silent downgrade, recorded
authorized downgrade, fail-closed on malformed state, and truthful status for
missing/uninitialized state.
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

from nogap_methodology import (  # noqa: E402
    MethodologyValidationError,
    derive_profile,
    downgrade_profile,
    escalate_phase,
    init_project,
    load_state,
    methodology_state_path,
    status,
)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/nogap.py", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


class ProfileDerivationTests(unittest.TestCase):
    def test_research_high_risk_strong_claim_is_strict(self) -> None:
        derivation = derive_profile("research", "high", "high")
        self.assertEqual(derivation.profile, "STRICT")

    def test_experimental_low_risk_weak_claim_is_light(self) -> None:
        derivation = derive_profile("experimental", "low", "low")
        self.assertEqual(derivation.profile, "LIGHT")

    def test_production_medium_risk_is_at_least_standard_regardless_of_claim(self) -> None:
        for claim in ("low", "medium", "high"):
            derivation = derive_profile("production", "medium", claim)
            self.assertIn(derivation.profile, {"STANDARD", "STRICT"}, f"claim={claim} gave {derivation.profile}")

    def test_production_low_risk_low_claim_still_floors_at_standard(self) -> None:
        # production's floor applies even when risk/claim would otherwise suggest LIGHT.
        derivation = derive_profile("production", "low", "low")
        self.assertEqual(derivation.profile, "STANDARD")

    def test_derivation_is_disclosed_not_hidden(self) -> None:
        derivation = derive_profile("research", "high", "low")
        as_dict = derivation.as_dict()
        for key in ("intent", "risk", "claim_strength", "risk_score", "claim_score", "intent_floor", "raw_score", "profile", "reason"):
            self.assertIn(key, as_dict)
        self.assertIn("risk=high", as_dict["reason"])

    def test_unknown_intent_fails_closed(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            derive_profile("hobby", "low", "low")

    def test_unknown_risk_fails_closed(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            derive_profile("research", "extreme", "low")

    def test_unknown_claim_strength_fails_closed(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            derive_profile("research", "low", "overwhelming")


class ProjectStateTests(unittest.TestCase):
    def test_status_reports_truthful_uninitialized_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = status(Path(tmp))
            self.assertFalse(result["initialized"])
            self.assertNotIn("derived_profile", result)

    def test_init_writes_disclosed_derivation_and_starts_at_p0(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = init_project(Path(tmp), "production", "high", "high", actor="test")
            self.assertEqual(state["derived_profile"], "STRICT")
            self.assertEqual(state["effective_profile"], "STRICT")
            self.assertEqual(state["current_phase"], "P0")
            self.assertEqual(state["phase_profile_overrides"], {})
            self.assertEqual(state["downgrade_log"], [])
            result = status(Path(tmp))
            self.assertTrue(result["initialized"])

    def test_init_twice_without_force_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            init_project(Path(tmp), "research", "low", "low", actor="test")
            with self.assertRaises(MethodologyValidationError):
                init_project(Path(tmp), "research", "low", "low", actor="test")

    def test_init_twice_with_force_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            init_project(Path(tmp), "research", "low", "low", actor="test")
            state = init_project(Path(tmp), "production", "high", "high", actor="test", force=True)
            self.assertEqual(state["intent"], "production")

    def test_phase_escalation_standard_project_verify_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "production", "medium", "low", actor="test")  # -> STANDARD
            state = escalate_phase(project, "VERIFY", "STRICT", actor="test")
            self.assertEqual(state["phase_profile_overrides"]["VERIFY"], "STRICT")
            self.assertEqual(state["effective_profile"], "STANDARD")  # project baseline unaffected

    def test_escalation_below_effective_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "high", "high", actor="test")  # -> STRICT
            with self.assertRaises(MethodologyValidationError):
                escalate_phase(project, "VERIFY", "LIGHT", actor="test")

    def test_escalation_unknown_phase_or_macro_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            with self.assertRaises(MethodologyValidationError):
                escalate_phase(project, "NOT_A_PHASE", "STANDARD", actor="test")

    def test_attempted_silent_downgrade_without_actor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "high", "high", actor="test")  # -> STRICT
            with self.assertRaises(MethodologyValidationError):
                downgrade_profile(project, "LIGHT", actor="", reason="")

    def test_attempted_silent_downgrade_without_reason_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "high", "high", actor="test")
            with self.assertRaises(MethodologyValidationError):
                downgrade_profile(project, "LIGHT", actor="human:owner", reason="")

    def test_explicit_authorized_downgrade_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "high", "high", actor="test")  # -> STRICT
            state = downgrade_profile(project, "LIGHT", actor="human:owner", reason="explicit low-stakes spike, owner approved")
            self.assertEqual(state["effective_profile"], "LIGHT")
            self.assertEqual(len(state["downgrade_log"]), 1)
            entry = state["downgrade_log"][0]
            self.assertEqual(entry["from_profile"], "STRICT")
            self.assertEqual(entry["to_profile"], "LIGHT")
            self.assertEqual(entry["actor_id"], "human:owner")
            self.assertIn("owner approved", entry["reason"])
            # derived_profile never changes - only effective_profile does
            self.assertEqual(state["derived_profile"], "STRICT")

    def test_downgrade_to_a_higher_or_equal_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "experimental", "low", "low", actor="test")  # -> LIGHT
            with self.assertRaises(MethodologyValidationError):
                downgrade_profile(project, "STRICT", actor="human:owner", reason="not actually a downgrade")

    def test_downgrade_without_prior_init_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MethodologyValidationError):
                downgrade_profile(Path(tmp), "LIGHT", actor="human:owner", reason="x")

    def test_malformed_state_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            methodology_state_path(project).write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_state(project)

    def test_state_missing_required_field_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            path = methodology_state_path(project)
            data = json.loads(path.read_text(encoding="utf-8"))
            del data["effective_profile"]
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_state(project)

    def test_state_with_unknown_profile_value_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project(project, "research", "low", "low", actor="test")
            path = methodology_state_path(project)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["effective_profile"] = "EXTREME"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_state(project)


class MethodologyCliTests(unittest.TestCase):
    """CLI-level checks through the real nogap.py process."""

    def test_status_before_init_reports_not_initialized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_script("methodology", "status", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("NOT INITIALIZED", result.stdout)

    def test_init_requires_all_three_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_script("methodology", "init", tmp, "--intent", "research")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires --intent, --risk, and --claim-strength", result.stdout + result.stderr)

    def test_full_lifecycle_via_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            init_result = run_script(
                "methodology", "init", tmp,
                "--intent", "production", "--risk", "medium", "--claim-strength", "low",
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)
            self.assertIn("STANDARD", init_result.stdout)

            escalate_result = run_script("methodology", "escalate", tmp, "--phase", "VERIFY", "--profile", "STRICT")
            self.assertEqual(escalate_result.returncode, 0, escalate_result.stderr)

            silent_downgrade = run_script("methodology", "downgrade", tmp, "--profile", "LIGHT")
            self.assertNotEqual(silent_downgrade.returncode, 0)
            self.assertIn("requires --profile and --reason", silent_downgrade.stdout + silent_downgrade.stderr)

            authorized_downgrade = run_script(
                "methodology", "downgrade", tmp,
                "--profile", "LIGHT", "--reason", "prototype spike, owner approved", "--actor", "human:owner",
            )
            self.assertEqual(authorized_downgrade.returncode, 0, authorized_downgrade.stderr)

            status_result = run_script("methodology", "status", tmp)
            self.assertIn("effective_profile=LIGHT", status_result.stdout)
            self.assertIn("downgrade history: 1", status_result.stdout)


if __name__ == "__main__":
    unittest.main()
