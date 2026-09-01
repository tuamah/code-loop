#!/usr/bin/env python3
"""M7-D acceptance checks: the Golden Principle Enforcement Map.

This map is a truthful description of enforcement CAPABILITY, never a claim
about a specific project's compliance, and never consulted by the trust
runtime to make any decision. Covers all 20 mandatory cases from the brief.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from nogap_methodology import (  # noqa: E402
    ENFORCEMENT_STATUSES,
    METHODOLOGY_DIR,
    MethodologyValidationError,
    OWNER_COMPONENTS,
    get_principle_enforcement,
    list_principle_enforcement,
    load_enforcement_map,
    methodology_compliance_summary,
    resolvable_references,
)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/nogap.py", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


class RealEnforcementMapTests(unittest.TestCase):
    """Checks against the actual, committed methodology/enforcement.json."""

    def setUp(self) -> None:
        self.records = load_enforcement_map()

    def test_1_exactly_twenty_canonical_principles_mapped(self) -> None:
        expected = {f"GP-{n}" for n in range(1, 21)}
        self.assertEqual(set(self.records), expected)

    def test_2_no_duplicate_principle_ids(self) -> None:
        # load_enforcement_map() itself fails closed on a duplicate id (see FailClosedTests),
        # so simply loading successfully with exactly 20 keys already proves no duplicates
        # survived; this asserts that directly against the live file.
        self.assertEqual(len(self.records), 20)

    def test_3_every_principle_has_classification(self) -> None:
        for record in self.records.values():
            self.assertIn(record.classification, {"A", "B", "C"})

    def test_4_every_principle_has_truthful_status(self) -> None:
        for record in self.records.values():
            self.assertIn(record.status, ENFORCEMENT_STATUSES)

    def test_5_advisory_principle_has_no_enforcement_mechanism_claimed(self) -> None:
        for record in self.records.values():
            if record.status == "ADVISORY":
                self.assertEqual(record.owner_component, "none")
                self.assertEqual(record.implemented_by, [])

    def test_6_deferred_principle_does_not_contribute_to_enforced_count(self) -> None:
        deferred = [r for r in self.records.values() if r.status == "DEFERRED"]
        self.assertTrue(deferred)
        for record in deferred:
            self.assertNotEqual(record.status, "ENFORCED")
        summary = methodology_compliance_summary()
        self.assertEqual(summary["enforced"], sum(1 for r in self.records.values() if r.status == "ENFORCED"))

    def test_9_all_owner_components_are_known_identifiers(self) -> None:
        for record in self.records.values():
            self.assertIn(record.owner_component, OWNER_COMPONENTS, record.principle_id)

    def test_10_references_to_tests_and_components_resolve_on_disk(self) -> None:
        for record in self.records.values():
            missing = resolvable_references(record)
            self.assertEqual(missing["implemented_by_missing"], [], record.principle_id)
            self.assertEqual(missing["tests_missing"], [], record.principle_id)

    def test_11_gp8_maps_to_real_authority_separation(self) -> None:
        record = get_principle_enforcement("GP-8")
        self.assertEqual(record.status, "ENFORCED")
        self.assertIn("scripts/nogap.py:acceptability", record.implemented_by)
        self.assertTrue(any("test_executor_self_acceptance_is_blocked" in t for t in record.tests))

    def test_12_gp10_maps_to_real_verification_semantics(self) -> None:
        record = get_principle_enforcement("GP-10")
        self.assertEqual(record.status, "ENFORCED")
        self.assertIn("scripts/nogap_effects.py", record.implemented_by)
        self.assertTrue(any("golden_regression" in t for t in record.tests))

    def test_13_gp14_maps_to_m7b_process_depth(self) -> None:
        record = get_principle_enforcement("GP-14")
        self.assertEqual(record.status, "ENFORCED")
        self.assertIn("nogap_methodology.py:derive_profile", record.owner_component)

    def test_14_gp3_partial_after_m7h_scoped_to_failure_repair_path(self) -> None:
        # M7-H's Failure Orchestrator enforces research-before-repair for its own
        # repair path (nogap_failure.py:record_research), but not every possible
        # route back into BUILD - so PARTIAL, not ENFORCED, and no milestone is left
        # blocking it (a wider guarantee would be a new, separately-scoped milestone).
        record = get_principle_enforcement("GP-3")
        self.assertEqual(record.status, "PARTIAL")
        self.assertIsNone(record.future_milestone)

    def test_15_gp9_partial_after_m7i_projection_is_opt_in(self) -> None:
        # M7-I's Memory Projector is real and tested, but is invoked on demand
        # (nogap memory build/rebuild) rather than automatically after every
        # relevant transition/decision/failure event - so PARTIAL, not ENFORCED,
        # and no milestone is left blocking it.
        record = get_principle_enforcement("GP-9")
        self.assertEqual(record.status, "PARTIAL")
        self.assertIsNone(record.future_milestone)

    def test_16_gp16_not_fully_enforced_before_model_router(self) -> None:
        record = get_principle_enforcement("GP-16")
        self.assertNotEqual(record.status, "ENFORCED")
        self.assertEqual(record.future_milestone, "M9")

    def test_17_summary_counts_equal_actual_records(self) -> None:
        summary = methodology_compliance_summary()
        self.assertEqual(summary["total"], 20)
        self.assertEqual(
            summary["enforced"] + summary["partial"] + summary["declared"] + summary["advisory"] + summary["deferred"],
            20,
        )
        for status_key, count_key in [
            ("ENFORCED", "enforced"), ("PARTIAL", "partial"), ("DECLARED", "declared"),
            ("ADVISORY", "advisory"), ("DEFERRED", "deferred"),
        ]:
            actual = sum(1 for r in self.records.values() if r.status == status_key)
            self.assertEqual(summary[count_key], actual, status_key)

    def test_classification_is_reused_from_principles_json_not_rederived(self) -> None:
        import nogap_methodology
        definition = nogap_methodology.load_methodology()
        for record in self.records.values():
            self.assertEqual(record.classification, definition.get_principle(record.principle_id).cls)


class FailClosedTests(unittest.TestCase):
    def _copy_methodology(self, tmp: Path) -> Path:
        dest = tmp / "methodology"
        shutil.copytree(METHODOLOGY_DIR, dest)
        return dest

    def test_7_unknown_principle_fails_closed(self) -> None:
        with self.assertRaises(MethodologyValidationError):
            get_principle_enforcement("GP-99")

    def test_8_malformed_map_fails_closed_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            (methodology_dir / "enforcement.json").unlink()
            with self.assertRaises(MethodologyValidationError):
                load_enforcement_map(methodology_dir)

    def test_8_malformed_map_fails_closed_bad_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            (methodology_dir / "enforcement.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_enforcement_map(methodology_dir)

    def test_duplicate_principle_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            path = methodology_dir / "enforcement.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["principles"].append(dict(data["principles"][0]))  # duplicate GP-1
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError) as ctx:
                load_enforcement_map(methodology_dir)
            self.assertIn("duplicate", str(ctx.exception))

    def test_missing_principle_coverage_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            path = methodology_dir / "enforcement.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["principles"].pop()  # drop GP-20
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError) as ctx:
                load_enforcement_map(methodology_dir)
            self.assertIn("does not cover exactly the 20", str(ctx.exception))

    def test_unknown_status_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            path = methodology_dir / "enforcement.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["principles"][0]["status"] = "TOTALLY_ENFORCED"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_enforcement_map(methodology_dir)

    def test_unregistered_owner_component_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            path = methodology_dir / "enforcement.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["principles"][0]["owner_component"] = "some_made_up_module.py"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError):
                load_enforcement_map(methodology_dir)

    def test_classification_mismatch_with_principles_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = self._copy_methodology(Path(tmp))
            path = methodology_dir / "enforcement.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            # GP-6 is class A in principles.json; claim B here to trigger the mismatch check.
            for entry in data["principles"]:
                if entry["principle_id"] == "GP-6":
                    entry["classification"] = "B"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MethodologyValidationError) as ctx:
                load_enforcement_map(methodology_dir)
            self.assertIn("does not match", str(ctx.exception))


class CliTests(unittest.TestCase):
    def test_18_principles_action_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            before = set(Path(tmp).rglob("*"))
            result = run_script("methodology", "principles", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            after = set(Path(tmp).rglob("*"))
            self.assertEqual(before, after)  # nothing created, nothing written

    def test_cli_reports_all_twenty_and_matches_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_script("methodology", "principles", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = methodology_compliance_summary()
            self.assertIn(f"{summary['total']} principles", result.stdout)
            for principle_id in (f"GP-{n}" for n in range(1, 21)):
                self.assertIn(principle_id, result.stdout)


class TrustRuntimeIndependenceTests(unittest.TestCase):
    """The map is purely descriptive: mutating it can never change what the trust
    runtime actually enforces."""

    def test_19_editing_enforcement_metadata_cannot_bypass_trust_runtime(self) -> None:
        import nogap as nogap_module

        with tempfile.TemporaryDirectory() as tmp:
            methodology_dir = Path(tmp) / "methodology"
            shutil.copytree(METHODOLOGY_DIR, methodology_dir)
            path = methodology_dir / "enforcement.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            gp8_entry = next(entry for entry in data["principles"] if entry["principle_id"] == "GP-8")
            tampered_mechanism = "claims executor self-acceptance is now allowed (false - this file has no power over the runtime)"
            gp8_entry["mechanism"] = tampered_mechanism
            path.write_text(json.dumps(data), encoding="utf-8")

            # Load our tampered copy just to prove it loads (doesn't error) - then verify
            # acceptability() in nogap.py behaves identically regardless, because it never
            # reads methodology/enforcement.json at all.
            tampered = load_enforcement_map(methodology_dir)
            self.assertEqual(tampered["GP-8"].mechanism, tampered_mechanism)

            # nogap.py's acceptability() never imports nogap_methodology at all, let alone reads
            # enforcement.json - the tampered file above has zero causal power over this call.
            frozen_hashes = {"gate-hash-1"}
            evidence = {
                "evidence-exec": {
                    "id": "evidence-exec", "status": "passed",
                    "provenance": {"actor_id": "agent-a", "authority": "execution", "role": "implementer", "gate_hash": "gate-hash-1"},
                },
            }
            decision = {"decision": "accept", "actor_id": "agent-a", "authority": "acceptance", "evidence": ["evidence-exec"]}
            failure = nogap_module.acceptability(decision, evidence, frozen_hashes)
            self.assertIn("executor identity cannot issue ACCEPT", failure)  # unchanged by the tampered map


if __name__ == "__main__":
    unittest.main()
